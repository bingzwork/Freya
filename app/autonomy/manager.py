"""AutonomyManager - Coordinates Watchdog, SelfInitiatedWorkManager, and MaintenanceManager."""

import threading
from typing import Any, Dict, List, Optional

from app.core.background_jobs import BackgroundJobService, get_job_service
from app.core.events import EventBus, get_event_bus
from app.core.observability import ObservabilityHub, get_observability_hub
from app.learning.pipeline import LearningPipeline, create_learning_pipeline
from app.memory.goals.manager import GoalStorage
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, get_workflow_orchestrator

from .models import AutonomyConfig
from .watchdog import Watchdog
from .self_initiated import SelfInitiatedWorkManager
from .maintenance import MaintenanceManager


class AutonomyStartupError(RuntimeError):
    """Raised when required autonomy dependencies are unavailable at startup."""


class AutonomyManager:
    """
    AutonomyManager - Main coordinator for Autonomy + Observation.
    
    Owns:
    - Watchdog (observes system events and metrics, feeds LearningPipeline)
    - SelfInitiatedWorkManager (reads goals, creates autonomous work via WorkflowOrchestrator)
    - MaintenanceManager (creates maintenance work via WorkflowOrchestrator)
    
    Uses shared BackgroundJobService for scheduling; does not create another scheduler.
    """

    def __init__(
        self,
        config: Optional[AutonomyConfig] = None,
        event_bus: Optional[EventBus] = None,
        observability: Optional[ObservabilityHub] = None,
        learning_pipeline: Optional[LearningPipeline] = None,
        goal_storage: Optional[GoalStorage] = None,
        workflow_orchestrator: Optional[WorkflowOrchestrator] = None,
        job_service: Optional[BackgroundJobService] = None,
    ):
        self.config = config or AutonomyConfig()
        
        # Shared infrastructure (from SystemInitializer)
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()
        self._learning_pipeline = learning_pipeline
        self._goal_storage = goal_storage
        self._workflow_orchestrator = workflow_orchestrator
        self._job_service = job_service or get_job_service()
        
        # Sub-components
        self._watchdog: Optional[Watchdog] = None
        self._self_initiated: Optional[SelfInitiatedWorkManager] = None
        self._maintenance: Optional[MaintenanceManager] = None
        self._learning_started = False
        
        self._lock = threading.RLock()
        self._running = False
        
        # Initialize sub-components
        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize all autonomy sub-components."""
        # Watchdog
        self._watchdog = Watchdog(
            config=self.config,
            event_bus=self._event_bus,
            observability=self._observability,
            learning_pipeline=self._learning_pipeline,
            job_service=self._job_service,
        )
        
        # Self-Initiated Work Manager
        self._self_initiated = SelfInitiatedWorkManager(
            config=self.config,
            goal_storage=self._goal_storage,
            workflow_orchestrator=self._workflow_orchestrator,
            job_service=self._job_service,
        )
        
        # Maintenance Manager
        self._maintenance = MaintenanceManager(
            config=self.config,
            workflow_orchestrator=self._workflow_orchestrator,
            job_service=self._job_service,
        )

    @property
    def watchdog(self) -> Optional[Watchdog]:
        """Get the Watchdog component."""
        return self._watchdog

    @property
    def self_initiated(self) -> Optional[SelfInitiatedWorkManager]:
        """Get the SelfInitiatedWorkManager component."""
        return self._self_initiated

    @property
    def maintenance(self) -> Optional[MaintenanceManager]:
        """Get the MaintenanceManager component."""
        return self._maintenance

    def _validate_startup_dependencies(self) -> None:
        """Ensure every enabled autonomy path has its explicit production dependency."""
        missing = []
        if self._event_bus is None:
            missing.append("event_bus")
        if self._observability is None:
            missing.append("observability")
        if self.config.use_background_job_service and self._job_service is None:
            missing.append("job_service")
        if self.config.watchdog_enabled and self._learning_pipeline is None:
            missing.append("learning_pipeline")
        if self.config.self_initiated_enabled:
            if self._goal_storage is None:
                missing.append("goal_storage")
            if self._workflow_orchestrator is None:
                missing.append("workflow_orchestrator")
        if self.config.maintenance_enabled and self._workflow_orchestrator is None:
            missing.append("workflow_orchestrator")
        if missing:
            raise AutonomyStartupError(
                "Autonomy startup requires injected dependencies: "
                + ", ".join(sorted(set(missing)))
            )

    def _stop_started_components(self) -> None:
        """Best-effort rollback for a partially completed startup."""
        for component in (self._maintenance, self._self_initiated, self._watchdog):
            if component:
                try:
                    component.stop()
                except Exception:
                    pass

    def start(self) -> bool:
        """Start all enabled autonomy components after validating their dependencies."""
        with self._lock:
            if self._running:
                return True
            if not self.config.enabled:
                return False

            self._validate_startup_dependencies()
            try:
                if self._learning_pipeline is not None and hasattr(self._learning_pipeline, "start"):
                    if not self._learning_pipeline.start(self._job_service, interval_seconds=60.0):
                        raise AutonomyStartupError("Canonical learning pipeline failed to start")
                    self._learning_started = True
                if self._watchdog:
                    self._watchdog.start()
                if self._self_initiated:
                    self._self_initiated.start()
                if self._maintenance:
                    self._maintenance.start()

                for enabled, component, name in (
                    (self.config.watchdog_enabled, self._watchdog, "watchdog"),
                    (self.config.self_initiated_enabled, self._self_initiated, "self_initiated"),
                    (self.config.maintenance_enabled, self._maintenance, "maintenance"),
                ):
                    if enabled and (component is None or not component.is_running()):
                        raise AutonomyStartupError(f"Autonomy component failed to start: {name}")

                self._running = True
                return True
            except Exception as exc:
                self._stop_started_components()
                if self._learning_started and self._learning_pipeline is not None:
                    try:
                        self._learning_pipeline.stop()
                    except Exception:
                        pass
                    self._learning_started = False
                self._running = False
                if isinstance(exc, AutonomyStartupError):
                    raise
                raise AutonomyStartupError("Autonomy startup failed") from exc

    def stop(self) -> None:
        """Stop all autonomy components."""
        if not self._running:
            return
            
        # Stop in reverse order
        if self._maintenance:
            self._maintenance.stop()
        if self._self_initiated:
            self._self_initiated.stop()
        if self._watchdog:
            self._watchdog.stop()
        if self._learning_started and self._learning_pipeline is not None:
            self._learning_pipeline.stop()
            self._learning_started = False
            
        self._running = False

    def is_running(self) -> bool:
        """Check if autonomy manager is running."""
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """Get status of all autonomy components."""
        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "learning_pipeline": {
                "running": bool(self._learning_pipeline and getattr(self._learning_pipeline, "is_running", lambda: False)()),
                "started_by_autonomy": self._learning_started,
            },
            "watchdog": {
                "running": self._watchdog.is_running() if self._watchdog else False,
                "enabled": self.config.watchdog_enabled,
            },
            "self_initiated": {
                "running": self._self_initiated.is_running() if self._self_initiated else False,
                "enabled": self.config.self_initiated_enabled,
                "active_work_count": len(self._self_initiated.get_active_work()) if self._self_initiated else 0,
            },
            "maintenance": {
                "running": self._maintenance.is_running() if self._maintenance else False,
                "enabled": self.config.maintenance_enabled,
                "active_work_count": len(self._maintenance.get_active_work()) if self._maintenance else 0,
                "scheduled_tasks": len(self._maintenance.get_scheduled_tasks()) if self._maintenance else 0,
            },
        }

    def set_goal_storage(self, goal_storage: GoalStorage) -> None:
        """Set goal storage (for late binding from SystemInitializer)."""
        self._goal_storage = goal_storage
        if self._self_initiated:
            self._self_initiated.set_goal_storage(goal_storage)

    def set_workflow_orchestrator(self, orchestrator: WorkflowOrchestrator) -> None:
        """Set workflow orchestrator (for late binding)."""
        self._workflow_orchestrator = orchestrator
        if self._self_initiated:
            self._self_initiated.set_workflow_orchestrator(orchestrator)
        if self._maintenance:
            self._maintenance.set_workflow_orchestrator(orchestrator)

    def set_learning_pipeline(self, pipeline: LearningPipeline) -> None:
        """Set learning pipeline (for late binding)."""
        self._learning_pipeline = pipeline
        if self._watchdog:
            self._watchdog.set_learning_pipeline(pipeline)

    # Convenience methods for external systems to report observations
    def observe_task_stalled(self, task_id: str, details: Dict[str, Any]) -> None:
        """Report a stalled task to watchdog."""
        if self._watchdog:
            self._watchdog.observe_task_stalled(task_id, details)

    def observe_task_failed(self, task_id: str, error: str, details: Dict[str, Any]) -> None:
        """Report a failed task to watchdog."""
        if self._watchdog:
            self._watchdog.observe_task_failed(task_id, error, details)

    def observe_goal_stalled(self, goal_id: str, details: Dict[str, Any]) -> None:
        """Report a stalled goal to watchdog."""
        if self._watchdog:
            self._watchdog.observe_goal_stalled(goal_id, details)

    def observe_goal_failed(self, goal_id: str, error: str, details: Dict[str, Any]) -> None:
        """Report a failed goal to watchdog."""
        if self._watchdog:
            self._watchdog.observe_goal_failed(goal_id, error, details)

    def observe_resource_pressure(self, resource: str, usage: float, threshold: float) -> None:
        """Report resource pressure to watchdog."""
        if self._watchdog:
            self._watchdog.observe_resource_pressure(resource, usage, threshold)