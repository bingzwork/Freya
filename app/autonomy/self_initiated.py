"""SelfInitiatedWorkManager - Reads goals, creates autonomous work via WorkflowOrchestrator."""

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.memory.goals.manager import GoalStorage
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, WorkflowSpec, WorkflowStrategy, get_workflow_orchestrator
from app.orchestrator.workflow_composer import IntentType
from app.core.background_jobs import BackgroundJobService, get_job_service, JobTriggerConfig, JobTriggerType

from .models import (
    AutonomyConfig,
    AutonomousWorkItem,
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
        """Check goals and generate autonomous work items."""
        if not self._goal_storage or not self._workflow_orchestrator:
            return
            
        # Check concurrent work limit
        with self._lock:
            active_count = len([w for w in self._active_work.values() if w.status == "running"])
            if active_count >= self.config.max_concurrent_autonomous_tasks:
                return
                
        # Get eligible goals
        goals_context = self._get_eligible_goals()
        if not goals_context:
            return
            
        # Generate work for each eligible goal
        for goal_ctx in goals_context:
            if not self._running:
                break
                
            # Check if we already have work for this goal
            with self._lock:
                existing = [w for w in self._active_work.values() 
                           if w.goal_id == goal_ctx.goal_id and w.status in ["pending", "scheduled", "running"]]
                if existing:
                    continue
                    
            # Generate work item
            work_item = self._create_work_from_goal(goal_ctx)
            if work_item:
                self._execute_work(work_item)

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
        """Create an autonomous work item from a goal context."""
        # Determine what kind of work to generate based on goal
        # For now, create a generic "make progress on goal" workflow
        
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
            
            # Execute via WorkflowOrchestrator
            execution_id = self._workflow_orchestrator.execute_workflow(spec, async_mode=True)
            
            # Update work item
            work_item.status = "running"
            work_item.workflow_execution_id = execution_id
            work_item.scheduled_for = datetime.now(timezone.utc).isoformat()
            
            # Track active work
            with self._lock:
                self._active_work[work_item.id] = work_item
                
            # Start monitoring thread for this work
            threading.Thread(
                target=self._monitor_work,
                args=(work_item,),
                daemon=True,
                name=f"WorkMonitor-{work_item.id[:8]}"
            ).start()
            
        except Exception as e:
            work_item.status = "failed"
            work_item.metadata["error"] = str(e)
            self._complete_work(work_item, False, {"error": str(e)})
            raise

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
                    success = status == WorkflowStatus.COMPLETED
                    self._complete_work(work_item, success, {"final_status": status.value})
                    break
                    
            except Exception:
                break
                
            time.sleep(5.0)

    def _complete_work(self, work_item: AutonomousWorkItem, success: bool, details: Dict[str, Any]) -> None:
        """Mark work as complete and notify callback."""
        work_item.status = "completed" if success else "failed"
        work_item.metadata["completion_details"] = details
        
        with self._lock:
            # Move to history
            if work_item.id in self._active_work:
                del self._active_work[work_item.id]
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