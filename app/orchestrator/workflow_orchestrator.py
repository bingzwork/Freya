"""Workflow Orchestrator for Freya.

A streamlined orchestrator that coordinates workflow execution using extracted
components: WorkflowComposer, TaskExecutor, SelfObserver, CapabilityRegistry,
SafetyGate, and ActivityReporter. Designed to work with SystemInitializer.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority

from app.orchestrator.capability_registry import (
    Capability, CapabilityCategory, CapabilityMetadata, CapabilityRegistry, CapabilityState,
    get_capability_registry, reset_capability_registry
)
from app.orchestrator.workflow_composer import (
    WorkflowComposer, WorkflowSpec, WorkflowStrategy, ComposedWorkflow, WorkflowStatus,
    WorkflowStep, CapabilitySelector, IntentBasedSelector, KeywordBasedSelector, DependencyAwareSelector
)
from app.orchestrator.task_executor import TaskExecutor, ExecutionContext, ExecutionState, Checkpoint, ExecutableCapability
from app.orchestrator.safety_gate import SafetyGate, SafetyPolicy, SafetyGateMode, SafetyAction, SafetyAssessment, SafetyViolationError, HumanOversightInterface, DefaultHumanOversight, check_safety
from app.orchestrator.self_observer import SelfObserver, ObservationLevel, SystemSnapshot, AlertRule, Alert
from app.orchestrator.capabilities import create_all_capabilities
from app.orchestrator.activity_reporter import ActivityReporter, ActivityLevel, ActivityUpdate
from app.orchestrator.gui_interface import OrchestratorGUIInterface, OrchestratorStreamingInterface
from app.orchestrator.failure_recovery_integration import FailureRecoveryIntegration, create_failure_recovery_integration


logger = logging.getLogger(__name__)


class OrchestratorState(Enum):
    """State of the workflow orchestrator."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class WorkflowOrchestratorConfig:
    """Configuration for the Workflow Orchestrator."""
    auto_discovery: bool = True
    health_check_interval: float = 30.0
    default_strategy: WorkflowStrategy = WorkflowStrategy.ADAPTIVE
    max_workflow_steps: int = 20
    max_parallel_steps: int = 5
    workflow_timeout: float = 300.0
    max_concurrent_workflows: int = 10
    default_task_retries: int = 3
    checkpoint_interval: int = 5
    safety_mode: SafetyGateMode = SafetyGateMode.BALANCED
    safety_require_approval_for: List[str] = field(default_factory=list)
    observation_level: ObservationLevel = ObservationLevel.STANDARD
    snapshot_interval: float = 60.0
    enable_intent_classification: bool = True
    intent_confidence_threshold: float = 0.7
    enable_background_jobs: bool = True
class WorkflowOrchestrator:
    """
    Workflow Orchestrator - Streamlined coordination for workflow execution.
    """

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
        router: Any = None,
        executor: Any = None,
        safety_gate: Optional[SafetyGate] = None,
        chat_activity: Any = None,
        event_bus: Any = None,
        job_service: Any = None,
        config: Optional[WorkflowOrchestratorConfig] = None,
    ):
        self.config = config or WorkflowOrchestratorConfig()
        self._state = OrchestratorState.STOPPED
        self._lock = threading.RLock()
        self._capability_registry = capability_registry
        self._router = router
        self._executor = executor
        self._chat_activity = chat_activity
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = get_observability_hub()
        self._workflow_composer: Optional[WorkflowComposer] = None
        self._task_executor: Optional[TaskExecutor] = None
        self._safety_gate: Optional[SafetyGate] = safety_gate
        self._self_observer: Optional[SelfObserver] = None
        self._activity_reporter: Optional[ActivityReporter] = None
        self._gui_interface: Optional[OrchestratorGUIInterface] = None
        self._streaming_interface: Optional[OrchestratorStreamingInterface] = None
        self._failure_recovery: Optional[FailureRecoveryIntegration] = None
        self._start_time: Optional[float] = None
        self._main_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._active_workflows: Dict[str, ComposedWorkflow] = {}
        self._workflow_lock = threading.RLock()
        self._observability.register_component(ComponentInfo(
            name="WorkflowOrchestrator",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Streamlined workflow orchestration using extracted components",
            metadata={}
        ))

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def capability_registry(self) -> Optional[CapabilityRegistry]:
        return self._capability_registry

    @property
    def workflow_composer(self) -> Optional[WorkflowComposer]:
        return self._workflow_composer

    @property
    def task_executor(self) -> Optional[TaskExecutor]:
        return self._task_executor

    @property
    def safety_gate(self) -> Optional[SafetyGate]:
        return self._safety_gate

    @property
    def self_observer(self) -> Optional[SelfObserver]:
        return self._self_observer

    @property
    def activity_reporter(self) -> Optional[ActivityReporter]:
        return self._activity_reporter

    @property
    def gui_interface(self) -> Optional[OrchestratorGUIInterface]:
        return self._gui_interface

    @property
    def streaming_interface(self) -> Optional[OrchestratorStreamingInterface]:
        return self._streaming_interface

    @property
    def failure_recovery(self) -> Optional[FailureRecoveryIntegration]:
        return self._failure_recovery

    @property
    def _start_time_property(self) -> Optional[float]:
        return self._start_time

    def start(self) -> bool:
        with self._lock:
            if self._state != OrchestratorState.STOPPED:
                logger.warning(f"Orchestrator already in state: {self._state}")
                return False
            self._state = OrchestratorState.STARTING
        try:
            logger.info("Starting Workflow Orchestrator...")
            self._initialize_components()
            self._start_components()
            self._register_builtin_capabilities()
            if self.config.enable_background_jobs:
                self._start_background_jobs()
            self._state = OrchestratorState.RUNNING
            self._start_time = time.time()
            self._shutdown_event.clear()
            self._main_thread = threading.Thread(
                target=self._coordination_loop,
                daemon=True,
                name="WorkflowOrchestrator-Coordination"
            )
            self._main_thread.start()
            self._publish_event("orchestrator.started", {
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            logger.info("Workflow Orchestrator started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}")
            self._state = OrchestratorState.ERROR
            return False

    def stop(self, timeout: float = 30.0) -> bool:
        with self._lock:
            if self._state == OrchestratorState.STOPPED:
                return True
            if self._state == OrchestratorState.STOPPING:
                pass
            self._state = OrchestratorState.STOPPING
        try:
            logger.info("Stopping Workflow Orchestrator...")
            self._shutdown_event.set()
            if self._main_thread and self._main_thread.is_alive():
                self._main_thread.join(timeout=timeout)
            self._stop_components()
            self._state = OrchestratorState.STOPPED
            self._publish_event("orchestrator.stopped", {
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            logger.info("Workflow Orchestrator stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping orchestrator: {e}")
            self._state = OrchestratorState.ERROR
            return False

    def pause(self) -> bool:
        with self._lock:
            if self._state != OrchestratorState.RUNNING:
                return False
            self._state = OrchestratorState.PAUSED
        if self._task_executor:
            for wf_id in self._task_executor.list_active_workflows():
                self._task_executor.pause(wf_id)
        self._publish_event("orchestrator.paused", {})
        logger.info("Orchestrator paused")
        return True

    def resume(self) -> bool:
        with self._lock:
            if self._state != OrchestratorState.PAUSED:
                return False
            self._state = OrchestratorState.RUNNING
        if self._task_executor:
            for wf_id in self._task_executor.list_active_workflows():
                self._task_executor.resume(wf_id)
        self._publish_event("orchestrator.resumed", {})
        logger.info("Orchestrator resumed")
        return True

    def _initialize_components(self):
        if self._capability_registry is None:
            # CapabilityRegistry does not yet implement auto-discovery or
            # health-check configuration; use its supported constructor.
            self._capability_registry = CapabilityRegistry()
        if self._safety_gate is None:
            safety_policy = SafetyPolicy(
                mode=self.config.safety_mode,
                always_require_approval=set(self.config.safety_require_approval_for),
            )
            self._safety_gate = SafetyGate(
                decision_manager=None,
                policy=safety_policy,
                registry=self._capability_registry,
            )
        self._workflow_composer = WorkflowComposer(
            registry=self._capability_registry,
            decision_manager=None,
            intent_classifier=None,
            memory_retrieval=None,
        )
        self._task_executor = TaskExecutor(
            registry=self._capability_registry,
            max_concurrent_workflows=self.config.max_concurrent_workflows,
            safety_gate=self._safety_gate,
            verification_runner=getattr(self._executor, "verification_runner", None),
            repair_loop=getattr(self._executor, "repair_loop", None),
        )
        self._self_observer = SelfObserver(
            capability_registry=self._capability_registry,
            workflow_composer=self._workflow_composer,
            task_executor=self._task_executor,
            safety_gate=self._safety_gate,
            observation_level=self.config.observation_level,
            snapshot_interval=self.config.snapshot_interval,
        )
        self._activity_reporter = ActivityReporter(
            enable_plain_english=True,
            debug_mode=False,
        )
        self._gui_interface = OrchestratorGUIInterface(self)
        self._streaming_interface = OrchestratorStreamingInterface(self._gui_interface)
        self._failure_recovery = create_failure_recovery_integration(
            task_executor=self._task_executor,
            workflow_composer=self._workflow_composer,
            capability_registry=self._capability_registry,
        )

    def _start_components(self):
        self._capability_registry.start()
        self._self_observer.start()

    def _stop_components(self):
        if self._self_observer:
            self._self_observer.stop()
        if self._capability_registry:
            self._capability_registry.stop()

    def _register_builtin_capabilities(self):
        capabilities = create_all_capabilities()
        registered_count = 0
        for cap in capabilities:
            if self._capability_registry.register(cap):
                registered_count += 1
        logger.info(f"Registered {registered_count} built-in capabilities")

    def _start_background_jobs(self):
        pass

    def _coordination_loop(self):
        logger.debug("Coordination loop started")
        while not self._shutdown_event.is_set():
            try:
                self._run_housekeeping()
            except Exception as e:
                logger.error(f"Error in coordination loop: {e}")
            for _ in range(10):
                if self._shutdown_event.is_set():
                    break
                time.sleep(0.5)
        logger.debug("Coordination loop stopped")

    def _run_housekeeping(self):
        with self._workflow_lock:
            to_remove = []
            for wf_id, workflow in self._active_workflows.items():
                if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
                    if workflow.completed_at and (time.time() - workflow.completed_at) > 300:
                        to_remove.append(wf_id)
            for wf_id in to_remove:
                del self._active_workflows[wf_id]

    def execute_workflow(self, spec: WorkflowSpec, async_mode: bool = True) -> str:
        if self._state != OrchestratorState.RUNNING:
            raise RuntimeError(f"Orchestrator not running (state: {self._state})")
        workflow = self._workflow_composer.compose(spec)
        with self._workflow_lock:
            self._active_workflows[workflow.spec.workflow_id] = workflow
        capabilities = {}
        for step in workflow.steps:
            cap = self._capability_registry.get_capability(step.capability_name)
            if cap:
                capabilities[step.capability_name] = cap

        try:
            self._safety_gate.check_and_enforce(
                f"Execute workflow: {workflow.spec.name or workflow.spec.workflow_id}",
                "workflow_execution",
                {
                    "workflow_id": workflow.spec.workflow_id,
                    "workflow_name": workflow.spec.name,
                    "description": workflow.spec.description,
                    "capabilities": list(capabilities),
                    "context": spec.context,
                },
            )
        except Exception as error:
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.now(timezone.utc).isoformat()
            workflow.metadata.update({
                "execution_state": ExecutionState.SAFETY_DENIED.value,
                "error": str(error),
            })
            self._publish_event("workflow.safety_denied", {
                "workflow_id": workflow.spec.workflow_id,
                "error": str(error),
            })
            raise

        execution_id = self._task_executor.execute(
            workflow_id=workflow.spec.workflow_id,
            task_graph=workflow.task_graph,
            capabilities=capabilities,
            global_inputs=spec.context,
            async_mode=async_mode,
            safety_approved=True,
        )
        workflow.status = WorkflowStatus.EXECUTING
        workflow.started_at = datetime.now(timezone.utc).isoformat()
        self._publish_event("workflow.started", {
            "workflow_id": workflow.spec.workflow_id,
            "name": workflow.spec.name,
            "steps": len(workflow.steps),
        })
        return execution_id

    def execute_intent(self, user_input: str, context: Optional[Dict[str, Any]] = None, async_mode: bool = True) -> str:
        spec = WorkflowSpec(
            name=f"Intent: {user_input[:50]}",
            description=user_input,
            intent=None,
            strategy=self.config.default_strategy,
            context=context or {},
            max_steps=self.config.max_workflow_steps,
            max_parallel=self.config.max_parallel_steps,
            timeout_seconds=self.config.workflow_timeout,
        )
        return self.execute_workflow(spec, async_mode)

    def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowStatus]:
        if self._task_executor:
            exec_state = self._task_executor.get_status(workflow_id)
            if exec_state:
                mapping = {
                    ExecutionState.PENDING: WorkflowStatus.PENDING,
                    ExecutionState.QUEUED: WorkflowStatus.PENDING,
                    ExecutionState.RUNNING: WorkflowStatus.EXECUTING,
                    ExecutionState.PAUSED: WorkflowStatus.EXECUTING,
                    ExecutionState.COMPLETED: WorkflowStatus.COMPLETED,
                    ExecutionState.FAILED: WorkflowStatus.FAILED,
                    ExecutionState.CANCELLED: WorkflowStatus.CANCELLED,
                    ExecutionState.RETRYING: WorkflowStatus.EXECUTING,
                    ExecutionState.CHECKPOINTING: WorkflowStatus.EXECUTING,
                    ExecutionState.RECOVERING: WorkflowStatus.EXECUTING,
                    ExecutionState.SAFETY_CHECKING: WorkflowStatus.EXECUTING,
                    ExecutionState.SAFETY_DENIED: WorkflowStatus.FAILED,
                    ExecutionState.AUTHORIZED: WorkflowStatus.EXECUTING,
                    ExecutionState.VERIFYING: WorkflowStatus.EXECUTING,
                    ExecutionState.VERIFICATION_FAILED: WorkflowStatus.FAILED,
                }
                status = mapping.get(exec_state, WorkflowStatus.PENDING)
                with self._workflow_lock:
                    workflow = self._active_workflows.get(workflow_id)
                    if workflow and status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
                        workflow.status = status
                        workflow.completed_at = workflow.completed_at or datetime.now(timezone.utc).isoformat()
                return status
        with self._workflow_lock:
            workflow = self._active_workflows.get(workflow_id)
            if workflow:
                return workflow.status
        return None

    def pause_workflow(self, workflow_id: str) -> bool:
        if self._task_executor:
            return self._task_executor.pause(workflow_id)
        return False

    def resume_workflow(self, workflow_id: str) -> bool:
        if self._task_executor:
            return self._task_executor.resume(workflow_id)
        return False

    def cancel_workflow(self, workflow_id: str) -> bool:
        if self._task_executor:
            return self._task_executor.cancel(workflow_id)
        return False

    def register_capability(self, capability: Capability, registered_by: str = "user") -> bool:
        if not self._capability_registry:
            return False
        return self._capability_registry.register(capability, registered_by)

    def unregister_capability(self, name: str) -> bool:
        if not self._capability_registry:
            return False
        return self._capability_registry.unregister(name)

    def get_capability(self, name: str) -> Optional[Capability]:
        if not self._capability_registry:
            return None
        return self._capability_registry.get_capability(name)

    def list_capabilities(self, category: Optional[CapabilityCategory] = None) -> List[CapabilityMetadata]:
        if not self._capability_registry:
            return []
        return self._capability_registry.list_capabilities(category=category, active_only=True)

    def check_safety(self, operation: str, operation_type: str, context: Dict[str, Any] = None):
        if not self._safety_gate:
            return None
        return self._safety_gate.check_and_enforce(operation, operation_type, context)

    def set_safety_mode(self, mode: SafetyGateMode):
        if self._safety_gate:
            self._safety_gate.set_mode(mode)

    def get_activity_history(self, limit: int = 100, category: Optional[str] = None, workflow_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._activity_reporter:
            return []
        activities = self._activity_reporter.get_history(limit=limit, category=category, workflow_id=workflow_id)
        return [a.to_dict() for a in activities]

    def get_recent_activity_summary(self, count: int = 10) -> str:
        if not self._activity_reporter:
            return "Activity reporter not available."
        return self._activity_reporter.get_recent_summary(count)

    def get_failure_stats(self) -> Dict[str, Any]:
        if not self._failure_recovery:
            return {}
        return self._failure_recovery.get_recovery_stats()

    def set_auto_recovery(self, enabled: bool):
        if self._failure_recovery:
            self._failure_recovery.set_auto_recovery(enabled)

    def get_failure_history(self, workflow_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._failure_recovery:
            return []
        failures = self._failure_recovery.get_failure_history(workflow_id, limit)
        return [
            {
                "workflow_id": f.workflow_id,
                "task_id": f.task_id,
                "capability_name": f.capability_name,
                "error": f.error,
                "error_type": f.error_type,
                "attempt": f.attempt,
                "timestamp": f.timestamp,
            }
            for f in failures
        ]

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "orchestrator": {
                "state": self._state.value,
                "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
            },
            "capability_registry": self._capability_registry.get_stats() if self._capability_registry else {},
            "workflow_composer": self._workflow_composer.get_stats() if self._workflow_composer else {},
            "task_executor": self._task_executor.get_stats() if self._task_executor else {},
            "safety_gate": self._safety_gate.get_stats() if self._safety_gate else {},
            "self_observer": self._self_observer.get_stats() if self._self_observer else {},
        }

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="workflow_orchestrator",
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")
# -------------------------------------------------------------------------
# Singleton access (optional - for compatibility)
# -------------------------------------------------------------------------

_workflow_orchestrator_instance: Optional[WorkflowOrchestrator] = None
_workflow_orchestrator_lock = threading.Lock()


def get_workflow_orchestrator(
    capability_registry: Optional[CapabilityRegistry] = None,
    router: Any = None,
    executor: Any = None,
    safety_gate: Optional[SafetyGate] = None,
    chat_activity: Any = None,
    event_bus: Any = None,
    job_service: Any = None,
    config: Optional[WorkflowOrchestratorConfig] = None,
) -> WorkflowOrchestrator:
    """Get or create the global workflow orchestrator instance."""
    global _workflow_orchestrator_instance
    with _workflow_orchestrator_lock:
        if _workflow_orchestrator_instance is None:
            _workflow_orchestrator_instance = WorkflowOrchestrator(
                capability_registry=capability_registry,
                router=router,
                executor=executor,
                safety_gate=safety_gate,
                chat_activity=chat_activity,
                event_bus=event_bus,
                job_service=job_service,
                config=config,
            )
        return _workflow_orchestrator_instance


def reset_workflow_orchestrator() -> None:
    """Reset the global workflow orchestrator instance (for testing)."""
    global _workflow_orchestrator_instance
    with _workflow_orchestrator_lock:
        if _workflow_orchestrator_instance:
            _workflow_orchestrator_instance.stop()
        _workflow_orchestrator_instance = None

# -------------------------------------------------------------------------
# Exports
# -------------------------------------------------------------------------

__all__ = [
    "WorkflowOrchestrator",
    "WorkflowOrchestratorConfig",
    "OrchestratorState",
    "get_workflow_orchestrator",
    "reset_workflow_orchestrator",
]

__version__ = "1.0.0"
