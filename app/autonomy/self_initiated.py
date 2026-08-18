"""SelfInitiatedWorkManager - Reads goals, creates autonomous work via WorkflowOrchestrator."""

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.memory.goals.manager import GoalStorage
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, WorkflowSpec, WorkflowStrategy, get_workflow_orchestrator
from app.orchestrator.workflow_composer import IntentType
from app.core.background_jobs import BackgroundJobService, get_job_service, JobTriggerConfig, JobTriggerType
from app.core.request_context import RequestContext
from app.core.logger import logger

from .models import (
    AutonomyConfig,
    AutonomousWorkItem,
    AutonomyCandidate,
    GoalContext,
)


class SelfInitiatedWorkManager:
    """
    SelfInitiatedWorkManager - Generates autonomous work from goals.
    
    Reads goals through GoalManager.
    Creates autonomous work through WorkflowOrchestrator (normal safety/execution path).
    Uses BackgroundJobService for scheduling.
    """

    def __init__(
        self,
        config: Optional[AutonomyConfig] = None,
        goal_storage: Optional[GoalStorage] = None,
        workflow_orchestrator: Optional[WorkflowOrchestrator] = None,
        job_service: Optional[BackgroundJobService] = None,
    ):
        self.config = config or AutonomyConfig()
        self._goal_storage = goal_storage
        self._workflow_orchestrator = workflow_orchestrator
        self._job_service = job_service
        
        self._lock = threading.RLock()
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Track active autonomous work
        self._active_work: Dict[str, AutonomousWorkItem] = {}
        self._work_history: List[AutonomousWorkItem] = []
        self._max_history = 100
        self._cycle_actions = 0
        self._dedup_completed_at: Dict[str, float] = {}
        self._retry_state: Dict[str, Dict[str, Any]] = {}
        self._monitor_threads: Dict[str, threading.Thread] = {}
        
        # Scheduled job ID
        self._check_job_id: Optional[str] = None
        
        # Callback for work completion
        self._work_completion_callback: Optional[Callable[[AutonomousWorkItem, bool, Dict[str, Any]], None]] = None

    def start(self) -> None:
        """Start the self-initiated work manager."""
        if self._running:
            return
            
        if not self.config.self_initiated_enabled:
            return
            
        self._running = True
        self._shutdown_event.clear()
        
        # Ensure dependencies are available
        self._ensure_dependencies()
        
        # Schedule periodic check via BackgroundJobService
        if self.config.use_background_job_service and self._job_service:
            self._schedule_periodic_check()
            
        # Periodic work is owned exclusively by BackgroundJobService.

    def stop(self) -> None:
        """Stop the self-initiated work manager."""
        if not self._running:
            return
            
        self._running = False
        self._shutdown_event.set()

        with self._lock:
            active_items = list(self._active_work.values())
            monitor_threads = list(self._monitor_threads.values())
        for work_item in active_items:
            if self._workflow_orchestrator and work_item.workflow_execution_id:
                try:
                    self._workflow_orchestrator.cancel_workflow(work_item.workflow_execution_id)
                except Exception:
                    pass
            self._complete_work(work_item, False, {"final_status": "shutdown", "error": "autonomy manager stopped"})
        for thread in monitor_threads:
            thread.join(timeout=1.0)
        with self._lock:
            self._monitor_threads.clear()
        
        # Cancel scheduled job
        if self._check_job_id and self._job_service:
            try:
                self._job_service.remove_job(self._check_job_id)
            except Exception:
                pass
                

    def _ensure_dependencies(self) -> None:
        """Require the dependencies supplied by the production initializer."""
        missing = []
        if self._goal_storage is None:
            missing.append("goal_storage")
        if self._workflow_orchestrator is None:
            missing.append("workflow_orchestrator")
        if self.config.use_background_job_service and self._job_service is None:
            missing.append("job_service")
        if missing:
            raise RuntimeError(
                "Self-initiated work requires injected dependencies: " + ", ".join(missing)
            )

    def _schedule_periodic_check(self) -> None:
        """Schedule periodic goal check via BackgroundJobService."""
        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=self.config.self_initiated_check_interval_seconds,
        )
        self._check_job_id = self._job_service.schedule(
            job_id="self_initiated_work_check",
            func=self._check_and_generate_work,
            trigger=trigger,
            name="Self-Initiated Work Check",
        )

    def _check_loop(self) -> None:
        """Background check loop as fallback."""
        while not self._shutdown_event.is_set():
            try:
                self._check_and_generate_work()
            except Exception:
                pass
            # Sleep in small chunks
            for _ in range(30):
                if self._shutdown_event.is_set():
                    break
                time.sleep(self.config.self_initiated_check_interval_seconds / 30.0)

    def _check_and_generate_work(self) -> None:
        """Check goals and generate a bounded, provenance-bearing autonomous action."""
        if not self._goal_storage or not self._workflow_orchestrator or not self._running:
            return

        with self._lock:
            self._cycle_actions = 0
            active_count = len([w for w in self._active_work.values() if w.status == "running"])
            if active_count >= self.config.max_concurrent_autonomous_tasks:
                return

        goals_context = self._get_eligible_goals()
        for goal_ctx in goals_context:
            if not self._running or self._cycle_actions >= max(0, self.config.max_actions_per_cycle):
                break
            dedup_key = self._deduplication_key(goal_ctx)
            with self._lock:
                existing = [w for w in self._active_work.values()
                            if w.metadata.get("deduplication_key") == dedup_key
                            and w.status in ["pending", "scheduled", "running"]]
                retry_state = self._retry_state.get(dedup_key, {})
                now = time.time()
                if existing:
                    continue
                if retry_state:
                    if retry_state.get("attempt", 0) > retry_state.get("max_retries", self.config.max_retries_per_task):
                        continue
                    if now < retry_state.get("next_retry_at", now):
                        continue
                else:
                    completed_at = self._dedup_completed_at.get(dedup_key, 0.0)
                    if (now - completed_at) < self.config.repeated_failure_cooldown_seconds:
                        continue

            work_item = self._create_work_from_goal(goal_ctx)
            if work_item:
                with self._lock:
                    self._cycle_actions += 1
                self._execute_work(work_item)

    @staticmethod
    def _deduplication_key(goal_ctx: GoalContext) -> str:
        """Return a stable key for equivalent goal-driven actions."""
        raw = f"self_initiated|{goal_ctx.goal_id}|{goal_ctx.name.strip()}|{goal_ctx.description.strip()}"
        return "autonomy:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _get_eligible_goals(self) -> List[GoalContext]:
        """Get goals that are eligible for autonomous work."""
        if not self._goal_storage:
            return []
            
        try:
            # Get goals that are active and not blocked
            goals = self._goal_storage.get_next_eligible_goals(limit=10)
            
            eligible = []
            for g in goals:
                # Convert to GoalContext
                goal_ctx = GoalContext(
                    goal_id=g["goal_id"],
                    name=g["name"],
                    description=g["description"],
                    status=g["status"],
                    priority=str(g["priority"]),
                    progress=g.get("progress", 0.0),
                    is_blocked=g.get("is_blocked", False),
                    blocking_reasons=g.get("blocking_reasons", []),
                    dependencies=g.get("dependencies", []),
                    duration_estimate=g.get("duration_estimate"),
                    metadata=g.get("metadata", {}),
                    created_at=g.get("created_at", ""),
                    updated_at=g.get("updated_at", ""),
                )
                
                # Filter: only consider goals that are in progress or pending, not blocked
                if goal_ctx.status in ["in_progress", "pending", "active"] and not goal_ctx.is_blocked:
                    eligible.append(goal_ctx)
                    
            return eligible
        except Exception:
            raise

    def _create_work_from_goal(self, goal_ctx: GoalContext) -> Optional[AutonomousWorkItem]:
        """Create an autonomous work item from a validated goal context."""
        if not goal_ctx.goal_id or not goal_ctx.name.strip() or not goal_ctx.description.strip():
            logger.warning("[Autonomy] rejected candidate without complete goal provenance")
            return None

        dedup_key = self._deduplication_key(goal_ctx)
        trace_id = RequestContext.create(
            original_message=f"Autonomous work for goal: {goal_ctx.name}",
            source="autonomy",
            channel="background",
        ).trace_id
        retry_state = dict(self._retry_state.get(
            dedup_key,
            {"attempt": 0, "max_retries": self.config.max_retries_per_task},
        ))
        candidate = AutonomyCandidate(
            source="goal_storage",
            source_id=goal_ctx.goal_id,
            proposed_action="make_progress_on_goal",
            reason=f"Goal is {goal_ctx.status} and eligible for bounded autonomous progress",
            goal={"goal_id": goal_ctx.goal_id, "name": goal_ctx.name, "description": goal_ctx.description},
            expected_value="Advance the originating user goal through the normal workflow path",
            urgency=goal_ctx.priority,
            risk="workflow_actions_must_pass_safety_gate",
            required_authorization="safety_gate_and_verification",
            required_resources=["planning_engine", "code_execution"],
            deduplication_key=dedup_key,
            retry_state=retry_state,
            trace_id=trace_id,
        )

        # Build workflow spec
        workflow_spec = {
            "name": f"Autonomous: {goal_ctx.name}",
            "description": f"Autonomous work to make progress on goal: {goal_ctx.description}",
            "intent": IntentType.TASK,
            "strategy": WorkflowStrategy.ADAPTIVE.value,
            "required_capabilities": ["planning_engine", "code_execution"],
            "context": {
                "autonomous": True,
                "goal_id": goal_ctx.goal_id,
                "goal_name": goal_ctx.name,
                "goal_description": goal_ctx.description,
                "goal_priority": goal_ctx.priority,
                "autonomy_candidate": candidate.to_dict(),
                "request_context": {
                    "trace_id": trace_id,
                    "source": "autonomy",
                    "channel": "background",
                    "session_id": f"autonomy_session_{goal_ctx.goal_id}",
                },
            },
            "max_steps": 10,
            "max_parallel": 2,
            "timeout_seconds": 300.0,
        }
        
        work_item = AutonomousWorkItem(
            source="self_initiated",
            description=f"Autonomous work for goal: {goal_ctx.name}",
            workflow_spec=workflow_spec,
            priority=self._priority_to_int(goal_ctx.priority),
            goal_id=goal_ctx.goal_id,
            metadata={
                "goal_progress": goal_ctx.progress,
                "goal_status": goal_ctx.status,
                "source": candidate.source,
                "source_id": candidate.source_id,
                "reason": candidate.reason,
                "deduplication_key": dedup_key,
                "autonomy_candidate": candidate.to_dict(),
                "trace_id": trace_id,
                "retry_state": retry_state,
            },
        )
        
        return work_item

    def _priority_to_int(self, priority: str) -> int:
        """Convert priority string to int."""
        mapping = {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        }
        return mapping.get(priority.lower(), 2)

    def _execute_work(self, work_item: AutonomousWorkItem) -> None:
        """Execute an autonomous work item via WorkflowOrchestrator."""
        if not self._workflow_orchestrator:
            return
            
        try:
            # Create WorkflowSpec from dict
            spec = WorkflowSpec(
                name=work_item.workflow_spec.get("name", "Autonomous Work"),
                description=work_item.workflow_spec.get("description", ""),
                intent=None,
                strategy=WorkflowStrategy(work_item.workflow_spec.get("strategy", "adaptive")),
                context=work_item.workflow_spec.get("context", {}),
                max_steps=work_item.workflow_spec.get("max_steps", 10),
                max_parallel=work_item.workflow_spec.get("max_parallel", 2),
                timeout_seconds=work_item.workflow_spec.get("timeout_seconds", 300.0),
            )
            
            candidate = work_item.metadata.get("autonomy_candidate", {})
            if not candidate.get("source_id") or not candidate.get("reason") or not candidate.get("deduplication_key"):
                raise ValueError("Autonomous work requires provenance, reason, and deduplication key")

            # Execute via WorkflowOrchestrator; its normal safety/execution pipeline remains authoritative.
            execution_id = self._workflow_orchestrator.execute_workflow(spec, async_mode=True)
            
            # Update work item
            work_item.status = "running"
            work_item.workflow_execution_id = execution_id
            work_item.scheduled_for = datetime.now(timezone.utc).isoformat()
            
            # Track active work
            with self._lock:
                self._active_work[work_item.id] = work_item
                
            # Start monitoring thread for this work
            monitor_thread = threading.Thread(
                target=self._monitor_work,
                args=(work_item,),
                daemon=True,
                name=f"WorkMonitor-{work_item.id[:8]}"
            )
            with self._lock:
                self._monitor_threads[work_item.id] = monitor_thread
            monitor_thread.start()
            
        except Exception as e:
            work_item.status = "failed"
            work_item.metadata["error"] = str(e)
            dedup_key = work_item.metadata.get("deduplication_key")
            with self._lock:
                state = dict(self._retry_state.get(dedup_key, work_item.metadata.get("retry_state", {})))
                state["attempt"] = int(state.get("attempt", 0)) + 1
                state["max_retries"] = int(state.get("max_retries", self.config.max_retries_per_task))
                state["next_retry_at"] = time.time() + self.config.failure_backoff_seconds
                self._retry_state[dedup_key] = state
            work_item.metadata["retry_state"] = state
            self._complete_work(work_item, False, {"error": str(e), "retry_state": state, "retry_recorded": True})
            logger.warning(f"[trace={work_item.metadata.get('trace_id', 'none')}] autonomous work failed: {e}")

    def _monitor_work(self, work_item: AutonomousWorkItem) -> None:
        """Monitor a work item until completion."""
        if not self._workflow_orchestrator:
            return
            
        execution_id = work_item.workflow_execution_id
        if not execution_id:
            return
            
        # Poll for status
        while self._running:
            try:
                status = self._workflow_orchestrator.get_workflow_status(execution_id)
                if not status:
                    break
                    
                from app.orchestrator.workflow_orchestrator import WorkflowStatus
                
                if status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
                    verification = self._workflow_verification(execution_id)
                    verified = verification.get("status") == "verified"
                    success = status == WorkflowStatus.COMPLETED and verified
                    details = {"final_status": status.value, "verification": verification}
                    if status == WorkflowStatus.COMPLETED and not verified:
                        details["error"] = "workflow reached terminal status without VERIFIED outcome"
                    self._complete_work(work_item, success, details)
                    break
                    
            except Exception:
                break
                
            time.sleep(5.0)

    def _workflow_verification(self, execution_id: str) -> Dict[str, Any]:
        """Read verification evidence from the orchestrator without treating terminal status as proof."""
        if not self._workflow_orchestrator:
            return {"status": "unknown", "reason": "orchestrator unavailable"}
        getter = getattr(self._workflow_orchestrator, "get_workflow_verification", None)
        if not callable(getter):
            return {"status": "unknown", "reason": "verification API unavailable"}
        try:
            evidence = getter(execution_id)
            if hasattr(evidence, "status"):
                return {"status": getattr(evidence.status, "value", str(evidence.status))}
            if isinstance(evidence, dict):
                return dict(evidence)
        except Exception as exc:
            return {"status": "unknown", "reason": str(exc)}
        return {"status": "unknown", "reason": "no verification evidence"}

    def _complete_work(self, work_item: AutonomousWorkItem, success: bool, details: Dict[str, Any]) -> None:
        """Mark work as complete only when workflow status and verification both permit it."""
        work_item.status = "completed" if success else "failed"
        work_item.metadata["completion_details"] = details
        if not success and not details.get("retry_recorded"):
            dedup_key = work_item.metadata.get("deduplication_key")
            if dedup_key:
                with self._lock:
                    state = dict(self._retry_state.get(dedup_key, work_item.metadata.get("retry_state", {})))
                    state["attempt"] = int(state.get("attempt", 0)) + 1
                    state["max_retries"] = int(state.get("max_retries", self.config.max_retries_per_task))
                    state["next_retry_at"] = time.time() + self.config.failure_backoff_seconds
                    self._retry_state[dedup_key] = state
                    work_item.metadata["retry_state"] = state
                details["retry_state"] = state
        
        with self._lock:
            # Move to history
            if work_item.id in self._active_work:
                del self._active_work[work_item.id]
            self._monitor_threads.pop(work_item.id, None)
            if not success and work_item.metadata.get("deduplication_key"):
                self._dedup_completed_at[work_item.metadata["deduplication_key"]] = time.time()
            self._work_history.append(work_item)
            if len(self._work_history) > self._max_history:
                self._work_history = self._work_history[-self._max_history:]
                
        # Call completion callback
        if self._work_completion_callback:
            try:
                self._work_completion_callback(work_item, success, details)
            except Exception:
                pass

    def set_work_completion_callback(
        self,
        callback: Callable[[AutonomousWorkItem, bool, Dict[str, Any]], None]
    ) -> None:
        """Set callback for work completion."""
        self._work_completion_callback = callback

    def set_goal_storage(self, goal_storage: GoalStorage) -> None:
        """Set goal storage (for late binding)."""
        self._goal_storage = goal_storage

    def set_workflow_orchestrator(self, orchestrator: WorkflowOrchestrator) -> None:
        """Set workflow orchestrator (for late binding)."""
        self._workflow_orchestrator = orchestrator

    def get_active_work(self) -> List[AutonomousWorkItem]:
        """Get currently active autonomous work items."""
        with self._lock:
            return list(self._active_work.values())

    def get_work_history(self) -> List[AutonomousWorkItem]:
        """Get work history."""
        with self._lock:
            return list(self._work_history)

    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running