"""GUI-Compatible Interfaces for Central Orchestrator.

This module provides stable, versioned interfaces for future GUI integration.
All interfaces are designed to be backwards-compatible and provide
comprehensive state exposure for UI components.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path

from app.core.events import get_event_bus, Event, EventPriority
from app.orchestrator.capability_registry import CapabilityMetadata, CapabilityCategory, CapabilityState
from app.orchestrator.workflow_composer import WorkflowStatus, WorkflowStrategy
from app.orchestrator.task_executor import ExecutionState

logger = logging.getLogger(__name__)


class GUIInterfaceVersion(Enum):
    """Supported GUI interface versions."""
    V1 = "1.0"
    CURRENT = V1


# =============================================================================
# Data Transfer Objects (DTOs)
# =============================================================================

@dataclass
class OrchestratorStatusDTO:
    """DTO for orchestrator status - GUI compatible."""
    version: str = "1.0"
    state: str = "stopped"
    uptime_seconds: float = 0.0
    active_workflows: int = 0
    max_concurrent_workflows: int = 10
    registered_capabilities: int = 0
    active_capabilities: int = 0
    safety_mode: str = "balanced"
    observation_level: str = "standard"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkflowSummaryDTO:
    """DTO for workflow summary - GUI compatible."""
    workflow_id: str
    name: str
    description: str
    status: str
    strategy: str
    intent: Optional[str] = None
    goal_id: Optional[str] = None
    progress: float = 0.0
    current_step: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkflowDetailDTO(WorkflowSummaryDTO):
    """DTO for detailed workflow info - GUI compatible."""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    step_history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CapabilitySummaryDTO:
    """DTO for capability summary - GUI compatible."""
    name: str
    description: str
    category: str
    version: str
    state: str
    is_singleton: bool
    is_active: bool
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    registered_by: Optional[str] = None
    registered_at: Optional[str] = None
    last_health_check: Optional[str] = None
    health_status: str = "unknown"
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_execution_time_ms: float = 0.0


@dataclass
class CapabilityDetailDTO(CapabilitySummaryDTO):
    """DTO for detailed capability info - GUI compatible."""
    metadata: Dict[str, Any] = field(default_factory=dict)
    configuration: Dict[str, Any] = field(default_factory=dict)
    recent_executions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutionContextDTO:
    """DTO for execution context - GUI compatible."""
    workflow_id: str
    current_step_index: int
    completed_steps: List[str] = field(default_factory=list)
    step_outputs: Dict[str, Any] = field(default_factory=dict)
    step_errors: Dict[str, str] = field(default_factory=dict)
    global_inputs: Dict[str, Any] = field(default_factory=dict)
    global_outputs: Dict[str, Any] = field(default_factory=dict)
    retries: Dict[str, int] = field(default_factory=dict)
    pause_requested: bool = False
    cancel_requested: bool = False
    execution_state: str = "running"
    checkpoint_count: int = 0
    last_checkpoint: Optional[str] = None


@dataclass
class SystemMetricsDTO:
    """DTO for system metrics - GUI compatible."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    orchestrator_uptime_seconds: float = 0.0
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_capabilities: int = 0
    active_capabilities: int = 0
    capability_executions_total: int = 0
    capability_success_rate: float = 0.0
    avg_workflow_duration_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    event_bus_queue_size: int = 0
    background_jobs_pending: int = 0
    background_jobs_running: int = 0


@dataclass
class EventDTO:
    """DTO for event - GUI compatible."""
    event_id: str
    name: str
    source: str
    priority: str
    timestamp: str
    data: Dict[str, Any]
    correlation_id: Optional[str] = None


@dataclass
class ActivityUpdateDTO:
    """DTO for activity update - GUI compatible (plain English)."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str = ""  # workflow_started, step_started, step_completed, workflow_completed, etc.
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    capability_name: Optional[str] = None
    message: str = ""  # Plain English message
    progress: Optional[float] = None
    level: str = "info"  # info, warning, error, success
    details: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# GUI Interface Classes
# =============================================================================

class OrchestratorGUIInterface:
    """
    Main GUI interface for the Central Orchestrator.

    Provides stable, versioned APIs for GUI integration.
    All methods return DTOs that are backwards-compatible.
    """

    def __init__(self, orchestrator):
        self._orchestrator = orchestrator
        self._version = GUIInterfaceVersion.CURRENT.value
        self._activity_callbacks: List[Callable[[ActivityUpdateDTO], None]] = []
        self._lock = threading.RLock()

        # Subscribe to orchestrator events for activity updates
        self._setup_event_subscriptions()

    @property
    def version(self) -> str:
        return self._version

    def _setup_event_subscriptions(self):
        """Subscribe to orchestrator events for activity reporting."""
        bus = get_event_bus()
        bus.subscribe("orchestrator.*", self._on_orchestrator_event)
        bus.subscribe("workflow.*", self._on_workflow_event)
        bus.subscribe("task.*", self._on_task_event)
        bus.subscribe("capability.*", self._on_capability_event)

    def _on_orchestrator_event(self, event: Event):
        """Handle orchestrator events."""
        activity = ActivityUpdateDTO(
            event_type=event.name,
            message=self._format_orchestrator_message(event.name, event.data),
            level="info",
            details=event.data,
        )
        self._emit_activity(activity)

    def _on_workflow_event(self, event: Event):
        """Handle workflow events."""
        activity = ActivityUpdateDTO(
            event_type=event.name,
            workflow_id=event.data.get("workflow_id"),
            message=self._format_workflow_message(event.name, event.data),
            level="info",
            details=event.data,
        )
        self._emit_activity(activity)

    def _on_task_event(self, event: Event):
        """Handle task events."""
        activity = ActivityUpdateDTO(
            event_type=event.name,
            workflow_id=event.data.get("workflow_id"),
            step_id=event.data.get("task_id"),
            capability_name=event.data.get("capability"),
            message=self._format_task_message(event.name, event.data),
            level="info" if "failed" not in event.name and "error" not in event.name else "error",
            details=event.data,
        )
        self._emit_activity(activity)

    def _on_capability_event(self, event: Event):
        """Handle capability events."""
        activity = ActivityUpdateDTO(
            event_type=event.name,
            capability_name=event.data.get("capability") or event.data.get("name"),
            message=self._format_capability_message(event.name, event.data),
            level="info",
            details=event.data,
        )
        self._emit_activity(activity)

    def _format_orchestrator_message(self, event_name: str, data: Dict[str, Any]) -> str:
        """Format orchestrator event as plain English."""
        messages = {
            "orchestrator.started": "Orchestrator started and ready to process requests",
            "orchestrator.stopped": "Orchestrator stopped",
            "orchestrator.paused": "Orchestrator paused",
            "orchestrator.resumed": "Orchestrator resumed",
            "orchestrator.health_degraded": "System health degraded - some components may be slow",
            "orchestrator.intent_executed": f"Processing request: {data.get('user_input', 'Unknown')[:50]}",
        }
        return messages.get(event_name, f"Orchestrator event: {event_name}")

    def _format_workflow_message(self, event_name: str, data: Dict[str, Any]) -> str:
        """Format workflow event as plain English."""
        wf_name = data.get("name", "workflow")
        messages = {
            "workflow.started": f"Started workflow: {wf_name}",
            "workflow.completed": f"Completed workflow: {wf_name}",
            "workflow.failed": f"Workflow failed: {wf_name} - {data.get('error', 'Unknown error')}",
            "workflow.cancelled": f"Cancelled workflow: {wf_name}",
            "workflow.paused": f"Paused workflow: {wf_name}",
            "workflow.resumed": f"Resumed workflow: {wf_name}",
        }
        return messages.get(event_name, f"Workflow event: {event_name}")

    def _format_task_message(self, event_name: str, data: Dict[str, Any]) -> str:
        """Format task event as plain English."""
        task = data.get("task_id", "task")
        cap = data.get("capability", "a capability")
        messages = {
            "task.started": f"Running {cap} for {task}",
            "task.completed": f"Finished {cap} for {task} ({data.get('duration_ms', 0):.0f}ms)",
            "task.failed": f"Failed {cap} for {task}: {data.get('error', 'Unknown error')}",
            "task.retrying": f"Retrying {cap} for {task} (attempt {data.get('attempt', 1)})",
        }
        return messages.get(event_name, f"Task event: {event_name}")

    def _format_capability_message(self, event_name: str, data: Dict[str, Any]) -> str:
        """Format capability event as plain English."""
        cap = data.get("name", data.get("capability", "capability"))
        messages = {
            "capability.registered": f"Registered capability: {cap}",
            "capability.unregistered": f"Unregistered capability: {cap}",
            "capability.activated": f"Activated capability: {cap}",
            "capability.deactivated": f"Deactivated capability: {cap}",
            "capability.health_check_failed": f"Health check failed for {cap}",
        }
        return messages.get(event_name, f"Capability event: {event_name}")

    def _emit_activity(self, activity: ActivityUpdateDTO):
        """Emit activity to all registered callbacks."""
        with self._lock:
            for callback in self._activity_callbacks:
                try:
                    callback(activity)
                except Exception as e:
                    logger.warning(f"Activity callback failed: {e}")

    # =========================================================================
    # Activity Update Subscription
    # =========================================================================

    def subscribe_activities(self, callback: Callable[[ActivityUpdateDTO], None]) -> str:
        """Subscribe to activity updates for real-time GUI updates.

        Returns:
            Subscription ID for later unsubscription
        """
        import uuid
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._activity_callbacks.append(callback)
        return sub_id

    def unsubscribe_activities(self, subscription_id: str) -> bool:
        """Unsubscribe from activity updates."""
        # Note: In production, track subscription IDs
        with self._lock:
            if self._activity_callbacks:
                self._activity_callbacks.pop()
                return True
        return False

    # =========================================================================
    # Orchestrator Status
    # =========================================================================

    def get_status(self) -> OrchestratorStatusDTO:
        """Get current orchestrator status."""
        if not self._orchestrator:
            return OrchestratorStatusDTO(state="not_initialized")

        status = self._orchestrator.get_system_status()
        orch_state = status.get("orchestrator", {})

        return OrchestratorStatusDTO(
            state=orch_state.get("state", "unknown"),
            uptime_seconds=orch_state.get("uptime_seconds", 0.0),
            active_workflows=status.get("task_executor", {}).get("active_workflows", 0),
            max_concurrent_workflows=status.get("task_executor", {}).get("max_concurrent", 10),
            registered_capabilities=status.get("capability_registry", {}).get("total_capabilities", 0),
            active_capabilities=status.get("capability_registry", {}).get("active_capabilities", 0),
            safety_mode=status.get("safety_gate", {}).get("mode", "balanced"),
            observation_level=status.get("self_observer", {}).get("observation_level", "standard"),
        )

    # =========================================================================
    # Workflow Management
    # =========================================================================

    def list_workflows(
        self,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[WorkflowSummaryDTO]:
        """List workflows with optional filtering."""
        if not self._orchestrator or not self._orchestrator._workflow_composer:
            return []

        # Get from workflow composer
        workflows = self._orchestrator._workflow_composer.list_workflows(
            status=WorkflowStatus(status_filter) if status_filter else None,
            limit=limit,
            offset=offset
        )

        dto_list = []
        for wf in workflows:
            steps = wf.steps if hasattr(wf, 'steps') else []
            completed = sum(1 for s in steps if s.status == "completed")
            total = len(steps)

            dto_list.append(WorkflowSummaryDTO(
                workflow_id=wf.spec.workflow_id,
                name=wf.spec.name,
                description=wf.spec.description,
                status=wf.status.value,
                strategy=wf.spec.strategy.value,
                intent=wf.spec.intent.value if wf.spec.intent else None,
                goal_id=wf.spec.goal_id,
                progress=(completed / total * 100) if total > 0 else 0.0,
                completed_steps=completed,
                total_steps=total,
                started_at=wf.started_at,
                completed_at=wf.completed_at,
                error=wf.error,
                created_at=wf.spec.created_at,
            ))

        return dto_list

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDetailDTO]:
        """Get detailed workflow information."""
        if not self._orchestrator or not self._orchestrator._workflow_composer:
            return None

        wf = self._orchestrator._workflow_composer.get_workflow(workflow_id)
        if not wf:
            return None

        # Get execution context if available
        exec_context = None
        if self._orchestrator._task_executor:
            exec_context = self._orchestrator._task_executor.get_context(workflow_id)

        steps = wf.steps if hasattr(wf, 'steps') else []
        step_list = []
        for s in steps:
            step_list.append({
                "step_id": s.step_id,
                "capability_name": s.capability_name,
                "action": s.action,
                "status": getattr(s, 'status', 'pending'),
                "inputs": s.inputs,
                "depends_on": s.depends_on,
            })

        dto = WorkflowDetailDTO(
            workflow_id=wf.spec.workflow_id,
            name=wf.spec.name,
            description=wf.spec.description,
            status=wf.status.value,
            strategy=wf.spec.strategy.value,
            intent=wf.spec.intent.value if wf.spec.intent else None,
            goal_id=wf.spec.goal_id,
            progress=0.0,
            completed_steps=sum(1 for s in steps if getattr(s, 'status', '') == 'completed'),
            total_steps=len(steps),
            started_at=wf.started_at,
            completed_at=wf.completed_at,
            error=wf.error,
            created_at=wf.spec.created_at,
            steps=step_list,
            context=wf.spec.context,
            outputs=exec_context.global_outputs if exec_context else {},
            step_history=exec_context.step_outputs if exec_context else {},
        )

        # Calculate progress
        if dto.total_steps > 0:
            dto.progress = (dto.completed_steps / dto.total_steps) * 100

        return dto

    def get_workflow_execution_context(self, workflow_id: str) -> Optional[ExecutionContextDTO]:
        """Get execution context for a workflow."""
        if not self._orchestrator or not self._orchestrator._task_executor:
            return None

        context = self._orchestrator._task_executor.get_context(workflow_id)
        if not context:
            return None

        exec_state = self._orchestrator._task_executor.get_status(workflow_id)

        return ExecutionContextDTO(
            workflow_id=workflow_id,
            current_step_index=context.current_step_index,
            completed_steps=list(context.completed_steps),
            step_outputs=context.step_outputs,
            step_errors=context.step_errors,
            global_inputs=context.global_inputs,
            global_outputs=context.global_outputs,
            retries=context.retries,
            pause_requested=context.pause_requested,
            cancel_requested=context.cancel_requested,
            execution_state=exec_state.value if exec_state else "unknown",
            checkpoint_count=0,
            last_checkpoint=context.last_checkpoint.created_at if context.last_checkpoint else None,
        )

    def pause_workflow(self, workflow_id: str) -> bool:
        """Pause a workflow."""
        if not self._orchestrator:
            return False
        return self._orchestrator.pause_workflow(workflow_id)

    def resume_workflow(self, workflow_id: str) -> bool:
        """Resume a workflow."""
        if not self._orchestrator:
            return False
        return self._orchestrator.resume_workflow(workflow_id)

    def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow."""
        if not self._orchestrator:
            return False
        return self._orchestrator.cancel_workflow(workflow_id)

    # =========================================================================
    # Capability Management
    # =========================================================================

    def list_capabilities(
        self,
        category: Optional[str] = None,
        active_only: bool = True
    ) -> List[CapabilitySummaryDTO]:
        """List capabilities with optional filtering."""
        if not self._orchestrator or not self._orchestrator._capability_registry:
            return []

        cat = CapabilityCategory(category) if category else None
        capabilities = self._orchestrator._capability_registry.list_capabilities(
            category=cat,
            active_only=active_only
        )

        dto_list = []
        for cap_meta in capabilities:
            cap = self._orchestrator._capability_registry.get_capability(cap_meta.name)
            if cap:
                stats = cap.get_stats() if hasattr(cap, 'get_stats') else {}
                dto_list.append(CapabilitySummaryDTO(
                    name=cap_meta.name,
                    description=cap_meta.description,
                    category=cap_meta.category.value,
                    version=cap_meta.version,
                    state=cap.state.value if hasattr(cap, 'state') else "unknown",
                    is_singleton=cap_meta.is_singleton,
                    is_active=cap.state == CapabilityState.ACTIVE if hasattr(cap, 'state') else False,
                    dependencies=cap_metadata.get("dependencies", []),
                    dependents=cap_metadata.get("dependents", []),
                    registered_by=cap_meta.registered_by,
                    registered_at=cap_meta.registered_at,
                    last_health_check=cap_meta.last_health_check,
                    health_status=cap_meta.health_status,
                    execution_count=stats.get("execution_count", 0),
                    success_count=stats.get("success_count", 0),
                    failure_count=stats.get("failure_count", 0),
                    avg_execution_time_ms=stats.get("avg_execution_time_ms", 0.0),
                ))

        return dto_list

    def get_capability(self, name: str) -> Optional[CapabilityDetailDTO]:
        """Get detailed capability information."""
        if not self._orchestrator or not self._orchestrator._capability_registry:
            return None

        cap = self._orchestrator._capability_registry.get_capability(name)
        if not cap:
            return None

        cap_meta = cap.metadata
        stats = cap.get_stats() if hasattr(cap, 'get_stats') else {}

        return CapabilityDetailDTO(
            name=cap_meta.name,
            description=cap_meta.description,
            category=cap_meta.category.value,
            version=cap_meta.version,
            state=cap.state.value if hasattr(cap, 'state') else "unknown",
            is_singleton=cap_meta.is_singleton,
            is_active=cap.state == CapabilityState.ACTIVE if hasattr(cap, 'state') else False,
            dependencies=cap_meta.dependencies,
            dependents=cap_meta.dependents,
            registered_by=cap_meta.registered_by,
            registered_at=cap_meta.registered_at,
            last_health_check=cap_meta.last_health_check,
            health_status=cap_meta.health_status,
            execution_count=stats.get("execution_count", 0),
            success_count=stats.get("success_count", 0),
            failure_count=stats.get("failure_count", 0),
            avg_execution_time_ms=stats.get("avg_execution_time_ms", 0.0),
            metadata=asdict(cap_meta) if hasattr(cap_meta, '__dataclass_fields__') else {},
            configuration=cap_meta.configuration if hasattr(cap_meta, 'configuration') else {},
            recent_executions=stats.get("recent_executions", []),
        )

    def check_capability_health(self, name: str) -> Dict[str, Any]:
        """Check health of a specific capability."""
        if not self._orchestrator or not self._orchestrator._capability_registry:
            return {"healthy": False, "error": "Orchestrator not initialized"}

        cap = self._orchestrator._capability_registry.get_capability(name)
        if not cap:
            return {"healthy": False, "error": "Capability not found"}

        if hasattr(cap, 'run_health_check'):
            return cap.run_health_check()
        return {"healthy": True, "status": cap.state.value if hasattr(cap, 'state') else "unknown"}

    # =========================================================================
    # Intent Execution
    # =========================================================================

    def execute_intent(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
        async_mode: bool = True
    ) -> str:
        """Execute a user intent."""
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        return self._orchestrator.execute_intent(user_input, context, goal_id, async_mode)

    # =========================================================================
    # System Metrics
    # =========================================================================

    def get_metrics(self) -> SystemMetricsDTO:
        """Get system metrics."""
        if not self._orchestrator:
            return SystemMetricsDTO()

        status = self._orchestrator.get_system_status()
        task_exec = status.get("task_executor", {})
        cap_reg = status.get("capability_registry", {})

        return SystemMetricsDTO(
            orchestrator_uptime_seconds=status.get("orchestrator", {}).get("uptime_seconds", 0.0),
            active_workflows=task_exec.get("active_workflows", 0),
            completed_workflows=task_exec.get("states", {}).get("completed", 0),
            failed_workflows=task_exec.get("states", {}).get("failed", 0),
            total_capabilities=cap_reg.get("total_capabilities", 0),
            active_capabilities=cap_reg.get("active_capabilities", 0),
            capability_executions_total=cap_reg.get("total_executions", 0),
            capability_success_rate=cap_reg.get("success_rate", 0.0),
        )

    # =========================================================================
    # Safety Control
    # =========================================================================

    def get_safety_status(self) -> Dict[str, Any]:
        """Get safety gate status."""
        if not self._orchestrator or not self._orchestrator._safety_gate:
            return {"mode": "unknown", "stats": {}}

        return {
            "mode": self._orchestrator._safety_gate.policy.mode.value if hasattr(self._orchestrator._safety_gate, 'policy') else "balanced",
            "stats": self._orchestrator._safety_gate.get_stats(),
        }

    def set_safety_mode(self, mode: str) -> bool:
        """Set safety mode."""
        if not self._orchestrator or not self._orchestrator._safety_gate:
            return False

        from app.orchestrator.safety_gate import SafetyGateMode
        try:
            self._orchestrator.set_safety_mode(SafetyGateMode(mode))
            return True
        except Exception:
            return False

    # =========================================================================
    # Event History
    # =========================================================================

    def get_event_history(
        self,
        limit: int = 100,
        event_filter: Optional[str] = None
    ) -> List[EventDTO]:
        """Get event history."""
        bus = get_event_bus()
        history = bus.get_history(limit=limit)

        events = []
        for evt in history:
            if event_filter and event_filter not in evt.name:
                continue
            events.append(EventDTO(
                event_id=evt.id,
                name=evt.name,
                source=evt.source,
                priority=evt.priority.value,
                timestamp=evt.timestamp,
                data=evt.data,
                correlation_id=evt.correlation_id,
            ))

        return events

    # =========================================================================
    # Orchestrator Control
    # =========================================================================

    def start(self) -> bool:
        """Start the orchestrator."""
        if not self._orchestrator:
            return False
        return self._orchestrator.start()

    def stop(self) -> bool:
        """Stop the orchestrator."""
        if not self._orchestrator:
            return False
        return self._orchestrator.stop()

    def pause(self) -> bool:
        """Pause the orchestrator."""
        if not self._orchestrator:
            return False
        return self._orchestrator.pause()

    def resume(self) -> bool:
        """Resume the orchestrator."""
        if not self._orchestrator:
            return False
        return self._orchestrator.resume()

    # =========================================================================
    # Export/Import
    # =========================================================================

    def export_state(self) -> Dict[str, Any]:
        """Export complete orchestrator state for backup/debugging."""
        if not self._orchestrator:
            return {}

        return {
            "version": self._version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": asdict(self.get_status()),
            "workflows": [asdict(w) for w in self.list_workflows()],
            "metrics": asdict(self.get_metrics()),
            "safety": self.get_safety_status(),
        }


# =============================================================================
# WebSocket-compatible streaming interface (for future GUI)
# =============================================================================

class OrchestratorStreamingInterface:
    """
    Streaming interface for real-time GUI updates.
    Designed for WebSocket or Server-Sent Events integration.
    """

    def __init__(self, gui_interface: OrchestratorGUIInterface):
        self._gui = gui_interface
        self._subscriber_queues: Dict[str, asyncio.Queue] = {}
        self._lock = threading.Lock()

    def create_subscriber(self) -> asyncio.Queue:
        """Create a new subscriber queue for streaming updates."""
        import uuid
        sub_id = str(uuid.uuid4())
        queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscriber_queues[sub_id] = queue
        return queue

    def remove_subscriber(self, queue: asyncio.Queue):
        """Remove a subscriber queue."""
        with self._lock:
            for sub_id, q in list(self._subscriber_queues.items()):
                if q is queue:
                    del self._subscriber_queues[sub_id]
                    break

    async def stream_activities(self, queue: asyncio.Queue):
        """Stream activity updates to a queue."""
        # Subscribe to activity updates
        def on_activity(activity: ActivityUpdateDTO):
            try:
                queue.put_nowait(activity)
            except asyncio.QueueFull:
                pass  # Drop oldest if queue full

        sub_id = self._gui.subscribe_activities(on_activity)
        try:
            while True:
                activity = await queue.get()
                yield activity
        finally:
            self._gui.unsubscribe_activities(sub_id)
            self.remove_subscriber(queue)

    async def stream_workflow_updates(self, workflow_id: str, queue: asyncio.Queue):
        """Stream specific workflow updates."""
        # Filter activities for this workflow
        def on_activity(activity: ActivityUpdateDTO):
            if activity.workflow_id == workflow_id:
                try:
                    queue.put_nowait(activity)
                except asyncio.QueueFull:
                    pass

        sub_id = self._gui.subscribe_activities(on_activity)
        try:
            while True:
                activity = await queue.get()
                yield activity
        finally:
            self._gui.unsubscribe_activities(sub_id)
            self.remove_subscriber(queue)