"""
ExecutionEngine - Single Execution Pipeline.

Consolidates: Planner (agent), Executor (agent), planner/TaskExecutor,
VerificationRunner, and RepairLoop behind the canonical facade boundary.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.priority_llm import LLMPriority, PriorityLLMProvider
from app.core.protocols import ChatActivityProvider
from app.core.tool_manager import ToolManager
from app.conversational_control import ConversationControlHandler
from app.editing.patch_engine import PatchEngine
from app.memory.coordinator import MemoryCoordinator
from app.planner.plan_manager import Plan, PlanManager
from app.planner.task import Task
from app.routing.unified_router import UnifiedRouter
from app.verification.repair_loop import RepairLoop
from app.verification.runner import VerificationResult, VerificationRunner


class ExecutionLifecycleState(str, Enum):
    """States for the canonical proposal-to-outcome execution lifecycle."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    SAFETY_CHECKING = "safety_checking"
    AUTHORIZED = "authorized"
    SAFETY_DENIED = "safety_denied"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRecord:
    """The final, observable result of one plan execution."""

    plan_id: str
    task: str
    state: ExecutionLifecycleState
    results: List[Any]
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
    completed_at: str = ""


@dataclass
class ExecutionContext:
    """Context for plan execution."""

    task: str
    allow_mutations: bool
    retrieved_context: str
    plan_id: str


class UnifiedPlanner:
    """Unified planner merging agent Planner and planner/PlanManager."""

    def __init__(self, llm: PriorityLLMProvider, memory: MemoryCoordinator, router: UnifiedRouter, tools: ToolManager):
        self._llm = llm
        self._memory = memory
        self._router = router
        self._tools = tools
        from app.agent.planner import Planner as AgentPlanner
        self._agent_planner = AgentPlanner(
            llm,
            memory.project_memory,
            engineering_lessons=memory.engineering_lessons,
        )

    def create_plan(self, task: str, context: str, allow_mutations: bool) -> Plan:
        """Create a plan for the given task."""
        plan = self._agent_planner.create_plan(task)
        if plan:
            return plan
        return None


class UnifiedExecutor:
    """Execute plan tasks through the agent executor and safety gate."""

    def __init__(
        self,
        planner: UnifiedPlanner,
        tools: ToolManager,
        memory: MemoryCoordinator,
        llm: PriorityLLMProvider,
        verification: VerificationRunner,
        repair: RepairLoop,
        safety_gate=None,
    ):
        self._planner = planner
        self._tools = tools
        self._memory = memory
        self._llm = llm
        self._verification = verification
        self._repair = repair
        self._safety_gate = safety_gate
        from app.agent.executor import Executor as AgentExecutor
        self._agent_executor = AgentExecutor(
            llm,
            tools,
            engineering_lessons=memory.engineering_lessons,
        )
        self._conversation_control: Optional[ConversationControlHandler] = None
        self._is_executing = False
        self._is_paused = False
        self._active_plan_id = None
        self._current_task_title = None
        self._completed_tasks: List[str] = []
        self._plan_tasks: List[Task] = []

    def set_conversation_control(self, control: ConversationControlHandler) -> None:
        self._conversation_control = control
        if hasattr(self._agent_executor, "set_conversation_control"):
            self._agent_executor.set_conversation_control(control)

    def execute(
        self,
        plan: Plan,
        allow_mutations: bool = True,
        safety_approved: bool = False,
    ) -> List[Any]:
        """Execute a plan, stopping at the first unsafe or failed task.

        ``ExecutionEngine`` performs the plan-level safety decision and passes
        ``safety_approved=True``.  Direct callers of this lower-level adapter
        still receive a safety check before the first task.
        """
        self._is_executing = True
        self._active_plan_id = plan.id if hasattr(plan, "id") else None
        self._plan_tasks = list(plan.tasks) if hasattr(plan, "tasks") else []
        self._completed_tasks = []
        results: List[Any] = []

        if self._conversation_control and hasattr(self._conversation_control, "start_execution"):
            self._conversation_control.start_execution(plan)

        try:
            for task in self._plan_tasks:
                if self._conversation_control and not self._conversation_control.before_task(task):
                    task.mark_cancelled("Execution cancelled before task started")
                    break

                self._current_task_title = task.title

                if self._safety_gate:
                    try:
                        self._safety_gate.check_and_enforce(
                            f"Execute task: {task.title}",
                            "task_execution",
                            {
                                "task_id": getattr(task, "id", task.title),
                                "task_title": task.title,
                                "allow_mutations": allow_mutations,
                                "plan_id": self._active_plan_id,
                            },
                        )
                    except Exception as error:
                        message = f"Safety gate blocked: {error}"
                        task.mark_failed(message)
                        result = {
                            "success": False,
                            "error": message,
                            "failure_type": "safety_denied",
                            "task_id": getattr(task, "id", task.title),
                        }
                        results.append(result)
                        if self._conversation_control:
                            self._conversation_control.after_task(task, False)
                        break

                allowed_tools = set(self._agent_executor.READ_ONLY_TOOLS)
                if allow_mutations:
                    allowed_tools.update(self._agent_executor.MUTATING_TOOLS)

                task.mark_in_progress()
                try:
                    # The agent executor exposes execute_step, not execute_task.
                    result = self._agent_executor.execute_step(task.title, allowed_tools)
                except Exception as error:
                    task.mark_failed(str(error))
                    result = {
                        "success": False,
                        "error": str(error),
                        "failure_type": "execution_error",
                        "task_id": getattr(task, "id", task.title),
                    }

                results.append(result)
                success = self._result_succeeded(result)
                if success:
                    task.mark_completed()
                    self._completed_tasks.append(getattr(task, "id", task.title))
                else:
                    error = self._result_error(result)
                    task.mark_failed(error)

                if self._conversation_control and not self._conversation_control.after_task(task, success):
                    break
                if not success:
                    break

        finally:
            self._is_executing = False
            self._active_plan_id = None
            self._current_task_title = None
            if self._conversation_control and hasattr(self._conversation_control, "finish_execution"):
                complete = bool(self._plan_tasks) and len(self._completed_tasks) == len(self._plan_tasks)
                self._conversation_control.finish_execution(success=complete)

        return results

    @staticmethod
    def _result_succeeded(result: Any) -> bool:
        if getattr(result, "success", True) is False:
            return False
        if not isinstance(result, dict):
            return True
        if result.get("success") is False or result.get("error"):
            return False
        nested = result.get("result")
        return not (isinstance(nested, dict) and (nested.get("success") is False or nested.get("error")))

    @staticmethod
    def _result_error(result: Any) -> str:
        if getattr(result, "error", None):
            return str(result.error)
        if isinstance(result, dict):
            if result.get("error"):
                return str(result["error"])
            nested = result.get("result")
            if isinstance(nested, dict) and nested.get("error"):
                return str(nested["error"])
        return "Execution returned an unsuccessful result."

    def shutdown(self) -> None:
        self._is_executing = False

    @property
    def is_executing(self) -> bool:
        return self._is_executing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def active_plan_id(self) -> Optional[str]:
        return self._active_plan_id

    @property
    def current_task_title(self) -> Optional[str]:
        return self._current_task_title

    @property
    def completed_tasks(self) -> List[str]:
        return self._completed_tasks

    @property
    def plan_tasks(self) -> List[Task]:
        return self._plan_tasks


class ExecutionEngine:
    """Single execution pipeline used by both facade and orchestrator."""

    def __init__(
        self,
        router: UnifiedRouter,
        tools: ToolManager,
        memory: MemoryCoordinator,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
        safety_gate=None,
    ):
        self._router = router
        self._tools = tools
        self._memory = memory
        self._llm = llm
        self._chat_activity = chat_activity
        self._safety_gate = safety_gate
        self._planner = UnifiedPlanner(llm=llm, memory=memory, router=router, tools=tools)

        verification_runner = VerificationRunner(tools.workspace if hasattr(tools, "workspace") else ".")
        self._executor = UnifiedExecutor(
            planner=self._planner,
            tools=tools,
            memory=memory,
            llm=llm,
            verification=verification_runner,
            repair=RepairLoop(
                patch_engine=PatchEngine(),
                tools=tools,
                verifier=verification_runner,
            ),
            safety_gate=safety_gate,
        )
        self._conversation_control: Optional[ConversationControlHandler] = None
        self.plan_manager = PlanManager(str(tools.workspace) if hasattr(tools, "workspace") else ".")
        self._lifecycle_state = ExecutionLifecycleState.CANCELLED
        self._execution_records: Dict[str, ExecutionRecord] = {}
        self._last_outcome: Optional[ExecutionRecord] = None

    def set_conversation_control(self, control: ConversationControlHandler) -> None:
        self._conversation_control = control
        self._executor.set_conversation_control(control)

    def execute_plan(self, task: str, allow_mutations: bool = True) -> str:
        """Execute a plan through safety, execution, verification, and safe failure."""
        self._chat_activity.chat_started()
        plan: Optional[Plan] = None
        results: List[Any] = []
        verification: Optional[VerificationResult] = None
        error: Optional[str] = None
        self._set_lifecycle_state(ExecutionLifecycleState.PROPOSED)

        try:
            context = self._memory.retrieve_for_planning(task)
            plan = self._planner.create_plan(task, context, allow_mutations)
            if not plan:
                error = "Could not create a plan for the given task."
                self._set_lifecycle_state(ExecutionLifecycleState.FAILED)
                return error

            self._set_lifecycle_state(ExecutionLifecycleState.VALIDATED)
            self._set_lifecycle_state(ExecutionLifecycleState.SAFETY_CHECKING)
            if self._safety_gate:
                self._safety_gate.check_and_enforce(
                    f"Execute plan: {task}",
                    "plan_execution",
                    {
                        "plan_id": plan.id,
                        "task": task,
                        "allow_mutations": allow_mutations,
                    },
                )
            self._set_lifecycle_state(ExecutionLifecycleState.AUTHORIZED)

            self._set_lifecycle_state(ExecutionLifecycleState.EXECUTING)
            results = self._executor.execute(plan, allow_mutations, safety_approved=True)
            if not results or not all(self._result_succeeded(result) for result in results):
                error = self._first_result_error(results) or "Execution did not produce a successful result."
                self._set_lifecycle_state(ExecutionLifecycleState.FAILED)
            else:
                self._set_lifecycle_state(ExecutionLifecycleState.EXECUTED)
                self._set_lifecycle_state(ExecutionLifecycleState.VERIFYING)
                verification = self._executor._verification.dry_run_verify()
                if not verification.success:
                    self._set_lifecycle_state(ExecutionLifecycleState.REPAIRING)
                    repair_result = self._executor._repair.run(lambda _feedback: [])
                    if repair_result.get("success"):
                        attempts = repair_result.get("attempts", [])
                        if attempts:
                            verification = attempts[-1].get("verification")
                    if not verification or not verification.success:
                        error = self._verification_error(verification)
                        self._set_lifecycle_state(ExecutionLifecycleState.FAILED)
                    else:
                        self._set_lifecycle_state(ExecutionLifecycleState.SUCCEEDED)
                else:
                    self._set_lifecycle_state(ExecutionLifecycleState.SUCCEEDED)

            if self._lifecycle_state == ExecutionLifecycleState.SUCCEEDED:
                self._persist_outcome(plan, task, results, verification, None)
                return self._summarize_results(task, plan, results)

            error = error or "Execution failed and was not verified."
            self._persist_outcome(plan, task, results, verification, error)
            return self._safe_failure_message(task, error)

        except Exception as caught:
            error = str(caught)
            if self._lifecycle_state == ExecutionLifecycleState.SAFETY_CHECKING:
                self._set_lifecycle_state(ExecutionLifecycleState.SAFETY_DENIED)
            else:
                self._set_lifecycle_state(ExecutionLifecycleState.FAILED)
            if plan is not None:
                self._persist_outcome(plan, task, results, verification, error)
            return self._safe_failure_message(task, error)
        finally:
            self._chat_activity.chat_ended()

    def _set_lifecycle_state(self, state: ExecutionLifecycleState) -> None:
        self._lifecycle_state = state

    @staticmethod
    def _result_succeeded(result: Any) -> bool:
        return UnifiedExecutor._result_succeeded(result)

    @staticmethod
    def _first_result_error(results: List[Any]) -> Optional[str]:
        for result in results:
            if not UnifiedExecutor._result_succeeded(result):
                return UnifiedExecutor._result_error(result)
        return None

    @staticmethod
    def _verification_error(verification: Optional[VerificationResult]) -> str:
        if verification is None:
            return "Execution verification did not produce a result."
        detail = (verification.stderr or verification.stdout or "verification failed").strip()
        return f"Execution verification failed: {detail}"

    def _persist_outcome(
        self,
        plan: Plan,
        task: str,
        results: List[Any],
        verification: Optional[VerificationResult],
        error: Optional[str],
    ) -> None:
        final_state = self._lifecycle_state
        final_error = error
        for plan_task in getattr(plan, "tasks", []):
            plan_task.metadata["execution_state"] = final_state.value
            plan_task.metadata["execution_verified"] = final_state == ExecutionLifecycleState.SUCCEEDED
            if final_error:
                plan_task.metadata["execution_error"] = final_error
                if not plan_task.is_complete:
                    plan_task.mark_failed(final_error)

        plan.status = "completed" if final_state == ExecutionLifecycleState.SUCCEEDED else "failed"
        self.plan_manager.save_plan(plan)
        record = ExecutionRecord(
            plan_id=plan.id,
            task=task,
            state=final_state,
            results=results,
            verification=verification,
            error=final_error,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._execution_records[plan.id] = record
        self._last_outcome = record

    def _safe_failure_message(self, task: str, error: str) -> str:
        return f"Task execution was not completed safely (state={self._lifecycle_state.value}): {error}"

    def _summarize_results(self, task: str, plan: Plan, results: List[Any]) -> str:
        """Summarize only a verified execution result for the user."""
        summary_parts = [
            f"Task: {task}",
            f"Plan: {len(getattr(plan, 'tasks', []))} steps",
            f"Results: {len(results)} completed",
            "Verification: passed",
        ]
        prompt = "\n".join(summary_parts) + "\nSummarize for the user."
        return self._llm.ask(prompt, priority=LLMPriority.CHAT)

    @property
    def lifecycle_state(self) -> ExecutionLifecycleState:
        return self._lifecycle_state

    @property
    def last_outcome(self) -> Optional[ExecutionRecord]:
        return self._last_outcome

    @property
    def verification_runner(self) -> VerificationRunner:
        return self._executor._verification

    @property
    def repair_loop(self) -> RepairLoop:
        return self._executor._repair

    @property
    def is_executing(self) -> bool:
        return self._executor.is_executing

    @property
    def is_paused(self) -> bool:
        return self._executor.is_paused

    @property
    def active_plan_id(self) -> Optional[str]:
        return self._executor.active_plan_id

    @property
    def current_task_title(self) -> Optional[str]:
        return self._executor.current_task_title

    @property
    def completed_tasks(self) -> List[str]:
        return self._executor.completed_tasks

    @property
    def plan_tasks(self) -> List[Task]:
        return self._executor.plan_tasks

    def shutdown(self) -> None:
        self._executor.shutdown()


__all__ = [
    "ExecutionContext",
    "ExecutionEngine",
    "ExecutionLifecycleState",
    "ExecutionRecord",
    "UnifiedExecutor",
    "UnifiedPlanner",
]
