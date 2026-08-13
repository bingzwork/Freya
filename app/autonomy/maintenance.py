"""MaintenanceManager - Creates maintenance work via WorkflowOrchestrator."""

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, WorkflowSpec, WorkflowStrategy, get_workflow_orchestrator
from app.orchestrator.workflow_composer import IntentType
from app.core.background_jobs import BackgroundJobService, get_job_service, JobTriggerConfig, JobTriggerType

from .models import (
    AutonomyConfig,
    AutonomousWorkItem,
)


class MaintenanceManager:
    """
    MaintenanceManager - Generates and executes maintenance work.
    
    Creates maintenance work through WorkflowOrchestrator (normal safety/execution path).
    Uses BackgroundJobService for scheduling.
    """

    def __init__(
        self,
        config: Optional[AutonomyConfig] = None,
        workflow_orchestrator: Optional[WorkflowOrchestrator] = None,
        job_service: Optional[BackgroundJobService] = None,
    ):
        self.config = config or AutonomyConfig()
        self._workflow_orchestrator = workflow_orchestrator
        self._job_service = job_service
        
        self._lock = threading.RLock()
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Track active maintenance work
        self._active_work: Dict[str, AutonomousWorkItem] = {}
        self._work_history: List[AutonomousWorkItem] = []
        self._max_history = 100
        
        # Scheduled job ID
        self._check_job_id: Optional[str] = None
        
        # Default maintenance task types and their workflow specs
        self._maintenance_tasks: Dict[str, Dict[str, Any]] = {
            "health_check": {
                "name": "System Health Check",
                "description": "Comprehensive system health verification",
                "workflow_spec": {
                    "name": "Maintenance: Health Check",
                    "description": "Run comprehensive health checks on all system components",
                    "strategy": WorkflowStrategy.SEQUENTIAL.value,
                    "context": {"maintenance_type": "health_check"},
                    "max_steps": 5,
                    "max_parallel": 1,
                    "timeout_seconds": 120.0,
                },
                "interval_seconds": 3600.0,  # 1 hour
            },
            "memory_consolidation": {
                "name": "Memory Consolidation",
                "description": "Consolidate and optimize memory stores",
                "workflow_spec": {
                    "name": "Maintenance: Memory Consolidation",
                    "description": "Run memory consolidation to optimize storage and retrieval",
                    "strategy": WorkflowStrategy.SEQUENTIAL.value,
                    "context": {"maintenance_type": "memory_consolidation"},
                    "max_steps": 5,
                    "max_parallel": 1,
                    "timeout_seconds": 180.0,
                },
                "interval_seconds": 86400.0,  # 1 day
            },
            "learning_garbage_collection": {
                "name": "Learning Garbage Collection",
                "description": "Clean up temporary learning artifacts and validate stored knowledge",
                "workflow_spec": {
                    "name": "Maintenance: Learning GC",
                    "description": "Garbage collect learning pipeline temporary items",
                    "strategy": WorkflowStrategy.SEQUENTIAL.value,
                    "context": {"maintenance_type": "learning_garbage_collection"},
                    "max_steps": 5,
                    "max_parallel": 1,
                    "timeout_seconds": 120.0,
                },
                "interval_seconds": 86400.0,  # 1 day
            },
            "goal_progress_review": {
                "name": "Goal Progress Review",
                "description": "Review and update goal progress, detect stalled goals",
                "workflow_spec": {
                    "name": "Maintenance: Goal Review",
                    "description": "Review goal progress and identify stalled goals",
                    "strategy": WorkflowStrategy.SEQUENTIAL.value,
                    "context": {"maintenance_type": "goal_progress_review"},
                    "max_steps": 5,
                    "max_parallel": 1,
                    "timeout_seconds": 120.0,
                },
                "interval_seconds": 3600.0,  # 1 hour
            },
            "capability_audit": {
                "name": "Capability Audit",
                "description": "Audit registered capabilities for health and relevance",
                "workflow_spec": {
                    "name": "Maintenance: Capability Audit",
                    "description": "Audit capability registry for health and relevance",
                    "strategy": WorkflowStrategy.SEQUENTIAL.value,
                    "context": {"maintenance_type": "capability_audit"},
                    "max_steps": 5,
                    "max_parallel": 1,
                    "timeout_seconds": 180.0,
                },
                "interval_seconds": 86400.0,  # 1 day
            },
        }
        
        # Track last run times
        self._last_run: Dict[str, float] = {}

    def start(self) -> None:
        """Start the maintenance manager."""
        if self._running:
            return
            
        if not self.config.maintenance_enabled:
            return
            
        self._running = True
        self._shutdown_event.clear()
        
        # Ensure dependencies
        self._ensure_dependencies()
        
        # Schedule periodic check via BackgroundJobService
        if self.config.use_background_job_service and self._job_service:
            self._schedule_periodic_check()
            
        # Also start local thread as backup
        self._check_thread = threading.Thread(
            target=self._check_loop,
            daemon=True,
            name="MaintenanceChecker"
        )
        self._check_thread.start()

    def stop(self) -> None:
        """Stop the maintenance manager."""
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
                
        if hasattr(self, '_check_thread') and self._check_thread.is_alive():
            self._check_thread.join(timeout=5.0)

    def _ensure_dependencies(self) -> None:
        """Require the dependencies supplied by the production initializer."""
        missing = []
        if self._workflow_orchestrator is None:
            missing.append("workflow_orchestrator")
        if self.config.use_background_job_service and self._job_service is None:
            missing.append("job_service")
        if missing:
            raise RuntimeError(
                "Maintenance requires injected dependencies: " + ", ".join(missing)
            )

    def _schedule_periodic_check(self) -> None:
        """Schedule periodic maintenance check via BackgroundJobService."""
        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=self.config.maintenance_check_interval_seconds,
        )
        self._check_job_id = self._job_service.schedule(
            job_id="maintenance_check",
            func=self._check_and_run_maintenance,
            trigger=trigger,
            name="Maintenance Check",
        )

    def _check_loop(self) -> None:
        """Background check loop as fallback."""
        while not self._shutdown_event.is_set():
            try:
                self._check_and_run_maintenance()
            except Exception:
                pass
            # Sleep in small chunks
            for _ in range(60):
                if self._shutdown_event.is_set():
                    break
                time.sleep(self.config.maintenance_check_interval_seconds / 60.0)

    def _check_and_run_maintenance(self) -> None:
        """Check for due maintenance tasks and execute them."""
        if not self._workflow_orchestrator:
            return
            
        now = time.time()
        
        with self._lock:
            # Check concurrent work limit
            active_count = len([w for w in self._active_work.values() if w.status == "running"])
            if active_count >= 2:  # Limit concurrent maintenance tasks
                return
                
            due_tasks = []
            for task_type, task_config in self._maintenance_tasks.items():
                last = self._last_run.get(task_type, 0)
                interval = task_config["interval_seconds"]
                if now - last >= interval:
                    due_tasks.append((task_type, task_config))
                    
        # Execute due tasks
        for task_type, task_config in due_tasks:
            if not self._running:
                break
            self._execute_maintenance(task_type, task_config)
            
            # Update last run time
            with self._lock:
                self._last_run[task_type] = now

    def _execute_maintenance(self, task_type: str, task_config: Dict[str, Any]) -> None:
        """Execute a maintenance task via WorkflowOrchestrator."""
        try:
            workflow_spec_dict = task_config["workflow_spec"]
            
            # Create WorkflowSpec
            spec = WorkflowSpec(
                name=workflow_spec_dict.get("name", f"Maintenance: {task_type}"),
                description=workflow_spec_dict.get("description", ""),
                intent=IntentType.SYSTEM_STATUS,
                strategy=WorkflowStrategy(workflow_spec_dict.get("strategy", "sequential")),
                required_capabilities=workflow_spec_dict.get(
                    "required_capabilities", ["system_monitoring"]
                ),
                context=workflow_spec_dict.get("context", {}),
                max_steps=workflow_spec_dict.get("max_steps", 5),
                max_parallel=workflow_spec_dict.get("max_parallel", 1),
                timeout_seconds=workflow_spec_dict.get("timeout_seconds", 180.0),
            )
            
            # Execute via WorkflowOrchestrator
            execution_id = self._workflow_orchestrator.execute_workflow(spec, async_mode=True)
            
            # Create work item for tracking
            work_item = AutonomousWorkItem(
                source="maintenance",
                description=task_config["description"],
                workflow_spec=workflow_spec_dict,
                priority=2,
                maintenance_task_type=task_type,
                metadata={
                    "maintenance_task_name": task_config["name"],
                    "interval_seconds": task_config["interval_seconds"],
                },
            )
            work_item.status = "running"
            work_item.workflow_execution_id = execution_id
            work_item.scheduled_for = datetime.now(timezone.utc).isoformat()
            
            # Track active work
            with self._lock:
                self._active_work[work_item.id] = work_item
                
            # Start monitoring thread
            threading.Thread(
                target=self._monitor_work,
                args=(work_item,),
                daemon=True,
                name=f"MaintMonitor-{work_item.id[:8]}"
            ).start()
            
        except Exception:
            raise

    def _monitor_work(self, work_item: AutonomousWorkItem) -> None:
        """Monitor a maintenance work item until completion."""
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
        """Mark work as complete."""
        work_item.status = "completed" if success else "failed"
        work_item.metadata["completion_details"] = details
        
        with self._lock:
            if work_item.id in self._active_work:
                del self._active_work[work_item.id]
            self._work_history.append(work_item)
            if len(self._work_history) > self._max_history:
                self._work_history = self._work_history[-self._max_history:]

    def add_maintenance_task(self, task_type: str, name: str, description: str, 
                           workflow_spec: Dict[str, Any], interval_seconds: float) -> None:
        """Add a custom maintenance task."""
        with self._lock:
            self._maintenance_tasks[task_type] = {
                "name": name,
                "description": description,
                "workflow_spec": workflow_spec,
                "interval_seconds": interval_seconds,
            }

    def remove_maintenance_task(self, task_type: str) -> bool:
        """Remove a maintenance task."""
        with self._lock:
            if task_type in self._maintenance_tasks:
                del self._maintenance_tasks[task_type]
                return True
            return False

    def set_workflow_orchestrator(self, orchestrator: WorkflowOrchestrator) -> None:
        """Set workflow orchestrator (for late binding)."""
        self._workflow_orchestrator = orchestrator

    def get_active_work(self) -> List[AutonomousWorkItem]:
        """Get currently active maintenance work items."""
        with self._lock:
            return list(self._active_work.values())

    def get_work_history(self) -> List[AutonomousWorkItem]:
        """Get work history."""
        with self._lock:
            return list(self._work_history)

    def get_scheduled_tasks(self) -> List[Dict[str, Any]]:
        """Get scheduled maintenance tasks with next run times."""
        now = time.time()
        result = []
        with self._lock:
            for task_type, task_config in self._maintenance_tasks.items():
                last = self._last_run.get(task_type, 0)
                interval = task_config["interval_seconds"]
                next_run = last + interval
                result.append({
                    "task_type": task_type,
                    "name": task_config["name"],
                    "description": task_config["description"],
                    "interval_seconds": interval,
                    "last_run": last if last > 0 else None,
                    "next_run": next_run,
                    "due": now >= next_run,
                })
        return result

    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running