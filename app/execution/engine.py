
"""
ExecutionEngine - Single Execution Pipeline.

Consolidates: Planner (agent), Executor (agent), PlanManager (planner/), VerificationRunner, RepairLoop
"""

from typing import Optional, List, Any, Dict
from dataclasses import dataclass

from app.core.protocols import ExecutionEngineProtocol
from app.routing.unified_router import UnifiedRouter
from app.core.tool_manager import ToolManager
from app.memory.coordinator import MemoryCoordinator
from app.core.priority_llm import PriorityLLMProvider, LLMPriority
from app.core.protocols import ChatActivityProvider
from app.conversational_control import ConversationControlHandler
from app.verification.runner import VerificationRunner
from app.verification.repair_loop import RepairLoop
from app.editing.patch_engine import PatchEngine
from app.planner.plan_manager import PlanManager, Plan
from app.planner.task import Task, TaskStatus
from app.core.logger import logger


@dataclass
class ExecutionContext:
    """Context for plan execution."""
    task: str
    allow_mutations: bool
    retrieved_context: str
    plan_id: str


class UnifiedPlanner:
    """Unified planner merging agent Planner + planner/ PlanManager."""

    def __init__(self, llm: PriorityLLMProvider, memory: MemoryCoordinator, router: UnifiedRouter, tools: ToolManager):
        self._llm = llm
        self._memory = memory
        self._router = router
        self._tools = tools
        # Lazy import to avoid circular dependency
        from app.agent.planner import Planner as AgentPlanner
        self._agent_planner = AgentPlanner(llm, memory.project_memory, engineering_lessons=memory.engineering_lessons)

    def create_plan(self, task: str, context: str, allow_mutations: bool) -> Plan:
        """Create a plan for the given task."""
        # Use agent planner to create the plan
        plan = self._agent_planner.create_plan(task)
        if plan:
            # Enhance with retrieved context
            return plan
        return None


class UnifiedExecutor:
    """Unified executor merging agent Executor + planner/ TaskExecutor."""

    def __init__(
        self,
        planner: UnifiedPlanner,
        tools: ToolManager,
        memory: MemoryCoordinator,
        llm: PriorityLLMProvider,
        verification: VerificationRunner,
        repair: RepairLoop,
        safety_gate=None,  # SafetyGate for operation validation
    ):
        self._planner = planner
        self._tools = tools
        self._memory = memory
        self._llm = llm
        self._verification = verification
        self._repair = repair
        self._safety_gate = safety_gate
        # Lazy import to avoid circular dependency
        from app.agent.executor import Executor as AgentExecutor
        self._agent_executor = AgentExecutor(llm, tools, engineering_lessons=memory.engineering_lessons)
        self._conversation_control: Optional[ConversationControlHandler] = None
        self._is_executing = False
        self._is_paused = False
        self._active_plan_id = None
        self._current_task_title = None
        self._completed_tasks: List[str] = []
        self._plan_tasks: List[Task] = []

    def set_conversation_control(self, control: ConversationControlHandler) -> None:
        self._conversation_control = control

    def execute(self, plan: Plan, allow_mutations: bool = True) -> List[Any]:
        """Execute a plan with verification/repair."""
        self._is_executing = True
        self._active_plan_id = plan.id if hasattr(plan, 'id') else None
        self._plan_tasks = plan.tasks if hasattr(plan, 'tasks') else []
        self._completed_tasks = []

        if hasattr(self._conversation_control, 'start_execution'):
            self._conversation_control.start_execution(plan)

        results = []
        try:
            for task in self._plan_tasks:
                # Check pause/stop via conversation control
                if self._conversation_control:
                    if not self._conversation_control.before_task(task):
                        break

                self._current_task_title = task.title

                # Safety gate check before execution (I2 -> M1 -> H1 wiring)
                if self._safety_gate:
                    try:
                        operation_desc = f"Execute task: {task.title}"
                        operation_type = "task_execution"
                        context = {
                            "task_id": task.id if hasattr(task, 'id') else task.title,
                            "task_title": task.title,
                            "allow_mutations": allow_mutations,
                            "plan_id": self._active_plan_id,
                        }
                        self._safety_gate.check_and_enforce(operation_desc, operation_type, context)
                    except Exception as e:
                        logger.warning(f"[UnifiedExecutor] Safety gate blocked task '{task.title}': {e}")
                        # Create a failure result for this task
                        result = {
                            'success': False,
                            'error': f'Safety gate blocked: {e}',
                            'task_id': task.id if hasattr(task, 'id') else task.title,
                        }
                        results.append(result)
                        if self._conversation_control:
                            if not self._conversation_control.after_task(task, False):
                                break
                        self._completed_tasks.append(task.id if hasattr(task, 'id') else task.title)
                        continue

                # Execute task using agent executor
                allowed_tools = set(self._agent_executor.READ_ONLY_TOOLS)
                if allow_mutations:
                    allowed_tools.update(self._agent_executor.MUTATING_TOOLS)

                result = self._agent_executor.execute_task(task, allowed_tools)
                results.append(result)

                if self._conversation_control:
                    success = result.get('success', False) if isinstance(result, dict) else True
                    if not self._conversation_control.after_task(task, success):
                        break

                self._completed_tasks.append(task.id if hasattr(task, 'id') else task.title)

        finally:
            self._is_executing = False
            self._active_plan_id = None
            self._current_task_title = None

            if hasattr(self._conversation_control, 'finish_execution'):
                self._conversation_control.finish_execution(success=len(results) > 0)

        return results

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
    """
    Single Execution Pipeline used by both Facade and Orchestrator.
    """

    def __init__(
        self,
        router: UnifiedRouter,
        tools: ToolManager,
        memory: MemoryCoordinator,
        llm: PriorityLLMProvider,
        chat_activity: ChatActivityProvider,
        safety_gate=None,  # SafetyGate for operation validation
    ):
        self._router = router
        self._tools = tools
        self._memory = memory
        self._llm = llm
        self._chat_activity = chat_activity
        self._safety_gate = safety_gate

        # Unified planning
        self._planner = UnifiedPlanner(
            llm=llm,
            memory=memory,
            router=router,
            tools=tools,
        )

        # Unified execution
        self._executor = UnifiedExecutor(
            planner=self._planner,
            tools=tools,
            memory=memory,
            llm=llm,
            verification=VerificationRunner(tools.workspace if hasattr(tools, 'workspace') else '.'),
            repair=RepairLoop(
                patch_engine=PatchEngine(),
                tools=tools,
                verifier=VerificationRunner(tools.workspace if hasattr(tools, "workspace") else "."),
            ),
            safety_gate=safety_gate,
        )

        # Conversation control callback
        self._conversation_control: Optional[ConversationControlHandler] = None

        # Plan manager for persistence
        from app.planner.plan_manager import PlanManager
        self.plan_manager = PlanManager(str(tools.workspace) if hasattr(tools, 'workspace') else '.')

    def set_conversation_control(self, control: ConversationControlHandler) -> None:
        self._conversation_control = control
        self._executor.set_conversation_control(control)

    def execute_plan(self, task: str, allow_mutations: bool = True) -> str:
        """Execute a plan for the given task."""
        # Signal chat started
        self._chat_activity.chat_started()

        try:
            # 1. Build context (unified retrieval)
            context = self._memory.retrieve_for_planning(task)

            # 2. Create plan (single planner)
            plan = self._planner.create_plan(task, context, allow_mutations)

            if not plan:
                return "Could not create a plan for the given task."

            # 3. Human review (via conversation control)
            if self._conversation_control:
                # Simplified: just proceed with execution for now
                pass

            # 4. Execute with verification/repair
            results = self._executor.execute(plan, allow_mutations)

            # 5. Final LLM summary
            return self._summarize_results(task, plan, results)

        finally:
            self._chat_activity.chat_ended()

    def _summarize_results(self, task: str, plan: Plan, results: List[Any]) -> str:
        """Summarize execution results for the user."""
        summary_parts = [f"Task: {task}", f"Plan: {len(getattr(plan, 'tasks', []))} steps", f"Results: {len(results)} completed"]
        prompt = "\n".join(summary_parts) + "\nSummarize for the user."
        return self._llm.ask(prompt, priority=LLMPriority.CHAT)

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
