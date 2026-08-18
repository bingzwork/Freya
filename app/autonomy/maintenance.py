"""MaintenanceManager - Creates maintenance work via WorkflowOrchestrator."""

import hashlib
import threading
import time

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, WorkflowSpec, WorkflowStrategy, get_workflow_orchestrator
from app.orchestrator.workflow_composer import IntentType
from app.core.background_jobs import BackgroundJobService, get_job_service, JobTriggerConfig, JobTriggerType
from app.core.request_context import RequestContext
from app.core.logger import logger

from .models import (
    AutonomyConfig,
    AutonomousWorkItem,
    AutonomyCandidate,
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
        self._cycle_actions = 0
        self._active_dedup_keys = set()
        self._monitor_threads: Dict[str, threading.Thread] = {}
        
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
            
        # Periodic maintenance is owned exclusively by BackgroundJobService.

    def stop(self) -> None:
        """Stop the maintenance manager."""
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
            self._complete_work(work_item, False, {"final_status": "shutdown", "error": "maintenance manager stopped"})
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
            self._cycle_actions = 0
            # Check concurrent work limit
            active_count = len([w for w in self._active_work.values() if w.status == "running"])
            if active_count >= min(2, self.config.max_concurrent_autonomous_tasks):
                return

            due_tasks = []

            for task_type, task_config in self._maintenance_tasks.items():
                last = self._last_run.get(task_type, 0)
                interval = task_config["interval_seconds"]
                if now - last >= interval:
                    due_tasks.append((task_type, task_config))
                    
        # Execute due tasks, bounded by the shared autonomy cycle budget.
        for task_type, task_config in due_tasks:
            if not self._running or self._cycle_actions >= max(0, self.config.max_actions_per_cycle):
                break
            dedup_key = self._deduplication_key(task_type)
            with self._lock:
                if dedup_key in self._active_dedup_keys:
                    continue
                self._active_dedup_keys.add(dedup_key)
                self._cycle_actions += 1
            self._execute_maintenance(task_type, task_config, dedup_key)

            # Update last run time even when execution is rejected; the scheduler remains bounded.
            with self._lock:
                self._last_run[task_type] = now

    @staticmethod
    def _deduplication_key(task_type: str) -> str:
        return "maintenance:" + hashlib.sha256(task_type.encode("utf-8")).hexdigest()[:24]

    def _execute_maintenance(self, task_type: str, task_config: Dict[str, Any], dedup_key: Optional[str] = None) -> None:
        """Execute a provenance-bearing maintenance task via WorkflowOrchestrator."""
        dedup_key = dedup_key or self._deduplication_key(task_type)
        trace_id = RequestContext.create(
            original_message=f"Scheduled maintenance: {task_type}",
            source="autonomy",
            channel="background",
        ).trace_id
        candidate = AutonomyCandidate(
            source="maintenance_schedule",
            source_id=task_type,
            proposed_action=task_type,
            reason="Approved recurring maintenance responsibility is due",
            goal={"maintenance_task_type": task_type, "name": task_config["name"]},
            expected_value=task_config["description"],
            urgency="scheduled",
            risk="maintenance_actions_must_pass_safety_gate",
            required_authorization="safety_gate_and_verification",
            required_resources=list(task_config["workflow_spec"].get("required_capabilities", ["system_monitoring"])),
            deduplication_key=dedup_key,
            retry_state={"attempt": 0, "max_retries": self.config.max_retries_per_task},
            trace_id=trace_id,
        )
        try:
            workflow_spec_dict = dict(task_config["workflow_spec"])
            workflow_context = dict(workflow_spec_dict.get("context", {}))
            workflow_context.update({
                "autonomous": True,
                "autonomy_candidate": candidate.to_dict(),
                "request_context": {
                    "trace_id": trace_id,
                    "source": "autonomy",
                    "channel": "background",
                    "session_id": f"autonomy_session_{task_type}",
                },
            })

            # Create WorkflowSpec
            spec = WorkflowSpec(
                name=workflow_spec_dict.get("name", f"Maintenance: {task_type}"),
                description=workflow_spec_dict.get("description", ""),
                intent=IntentType.SYSTEM_STATUS,
                strategy=WorkflowStrategy(workflow_spec_dict.get("strategy", "sequential")),
                required_capabilities=workflow_spec_dict.get(
                    "required_capabilities", ["system_monitoring"]
                ),
                context=workflow_context,

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
                    "source": candidate.source,
                    "source_id": candidate.source_id,
                    "reason": candidate.reason,
                    "deduplication_key": dedup_key,
                    "autonomy_candidate": candidate.to_dict(),
                    "trace_id": trace_id,
                },

            )
            work_item.status = "running"
            work_item.workflow_execution_id = execution_id
            work_item.scheduled_for = datetime.now(timezone.utc).isoformat()
            
            # Track active work
            with self._lock:
                self._active_work[work_item.id] = work_item
                
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self._monitor_work,
                args=(work_item,),
                daemon=True,
                name=f"MaintMonitor-{work_item.id[:8]}"
            )
            with self._lock:
                self._monitor_threads[work_item.id] = monitor_thread
            monitor_thread.start()

        except Exception as exc:
            with self._lock:
                self._active_dedup_keys.discard(dedup_key)
            logger.warning(f"[trace={trace_id}] maintenance work failed before tracking: {exc}")

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
                    verification = self._workflow_verification(execution_id)
                    verified = verification.get("status") == "verified"
                    success = status == WorkflowStatus.COMPLETED and verified
                    details = {"final_status": status.value, "verification": verification}
                    if status == WorkflowStatus.COMPLETED and not verified:
                        details["error"] = "maintenance workflow reached terminal status without VERIFIED outcome"
                    self._complete_work(work_item, success, details)
                    break

            except Exception:
                break
                
            time.sleep(5.0)

    def _workflow_verification(self, execution_id: str) -> Dict[str, Any]:
        """Read authoritative verification evidence without trusting terminal status alone."""
        getter = getattr(self._workflow_orchestrator, "get_workflow_verification", None) if self._workflow_orchestrator else None
        if not callable(getter):
            return {"status": "unknown", "reason": "verification API unavailable"}
        try:
            evidence = getter(execution_id)
            return dict(evidence) if isinstance(evidence, dict) else {"status": "unknown"}
        except Exception as exc:
            return {"status": "unknown", "reason": str(exc)}

    def _complete_work(self, work_item: AutonomousWorkItem, success: bool, details: Dict[str, Any]) -> None:
        """Mark work complete only when workflow status and verification both permit it."""

        work_item.status = "completed" if success else "failed"
        work_item.metadata["completion_details"] = details
        
        with self._lock:
            if work_item.id in self._active_work:
                del self._active_work[work_item.id]
            self._monitor_threads.pop(work_item.id, None)
            self._active_dedup_keys.discard(work_item.metadata.get("deduplication_key"))
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