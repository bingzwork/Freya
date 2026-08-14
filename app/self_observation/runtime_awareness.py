"""Runtime Awareness Service for Self Observation.

Maintains a continuously updated operational view of Freya's runtime state:
- Current activity
- Running tasks
- Active goals
- Current reasoning state
- Tool usage
- Resource consumption
- System health
- Memory state
- Pending work
- Autonomous background activities
- Overall execution context

Exposes a reusable Runtime Awareness interface for other subsystems.
Reuses existing monitoring and observability data wherever possible.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from app.core.events import get_event_bus, Event
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType
from app.decision.manager import DecisionManager, get_default_manager
from app.world_model.model import WorldModel, create_world_model
from app.memory.unified_retrieval import UnifiedRetrieval
from app.failure_recovery.orchestrator import RecoveryOrchestrator
from app.autonomous_learning.pipeline import AutonomousLearningPipeline
from app.long_term_autonomy.manager import AutonomyManager
from app.memory.goals import GoalStorage

from .models import (
    AwarenessComponent,
    RuntimeAwarenessState,
    ConfidenceLevel,
)

# Type checking imports to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class AwarenessConfig:
    """Configuration for runtime awareness."""
    update_interval_seconds: float = 10.0  # More frequent than self-analysis
    min_samples_for_trend: int = 10
    trend_window_seconds: float = 300.0  # 5 minutes
    max_history: int = 200


class RuntimeAwareness:
    """
    Runtime Awareness Service.

    Maintains a continuously updated operational view by collecting data from
    all integrated subsystems. Provides real-time awareness of:
    - Current activity (from ActivityReporter)
    - Running/queued tasks (from TaskExecutor)
    - Active goals (from GoalStorage)
    - Current reasoning state (from DecisionManager, Planner)
    - Tool usage (from capability registry, tool manager)
    - Resource consumption (from ObservabilityHub, WorldModel)
    - System health (from ObservabilityHub)
    - Memory state (from UnifiedRetrieval, GoalStorage, etc.)
    - Pending work (from WorkflowComposer, TaskExecutor, JobService)
    - Autonomous background activities (from AutonomyManager, LearningPipeline)
    - Overall execution context (composite view)
    """

    def __init__(
        self,
        orchestrator: "Optional[WorkflowOrchestrator]" = None,
        decision_manager: Optional[DecisionManager] = None,
        world_model: Optional[WorldModel] = None,
        memory_retrieval: Optional[UnifiedRetrieval] = None,
        failure_recovery: Optional[RecoveryOrchestrator] = None,
        autonomous_learning: Optional[AutonomousLearningPipeline] = None,
        autonomy_manager: Optional[AutonomyManager] = None,
        goal_storage: Optional[GoalStorage] = None,
        config: Optional[AwarenessConfig] = None,
    ):
        """Initialize the runtime awareness service."""
        self._orchestrator = orchestrator
        self._decision_manager = decision_manager
        self._world_model = world_model
        self._memory_retrieval = memory_retrieval
        self._failure_recovery = failure_recovery
        self._autonomous_learning = autonomous_learning
        self._autonomy_manager = autonomy_manager
        self._goal_storage = goal_storage
        self._config = config or AwarenessConfig()

        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()

        self._lock = threading.RLock()
        self._running = False
        self._awareness_thread: Optional[threading.Thread] = None

        # Current awareness state
        self._current_state: Optional[RuntimeAwarenessState] = None

        # Awareness history for trends
        self._awareness_history: List[RuntimeAwarenessState] = []
        self._max_history = self._config.max_history

        # Cached metrics for trend analysis
        self._metric_cache: Dict[str, List[Tuple[float, float]]] = {}
        self._cache_lock = threading.RLock()

        # Component status tracking
        self._component_status: Dict[str, str] = {}

        # Subscribe to events
        self._subscribe_events()

        # Register with observability
        from app.core.observability import ComponentInfo, ComponentType
        self._observability.register_component(
            ComponentInfo(
                name="RuntimeAwareness",
                component_type=ComponentType.SERVICE,
                description="Runtime awareness service for continuous operational view",
                version="1.0.0"
            )
        )

        logger.info("RuntimeAwareness initialized")

    def _subscribe_events(self) -> None:
        """Subscribe to events for real-time updates."""
        self._event_bus.subscribe("orchestrator.intent_executed", self._on_activity_event)
        self._event_bus.subscribe("workflow.started", self._on_workflow_event)
        self._event_bus.subscribe("workflow.completed", self._on_workflow_event)
        self._event_bus.subscribe("workflow.failed", self._on_workflow_event)
        self._event_bus.subscribe("task.started", self._on_task_event)
        self._event_bus.subscribe("task.completed", self._on_task_event)
        self._event_bus.subscribe("task.failed", self._on_task_event)
        self._event_bus.subscribe("decision.made", self._on_decision_event)
        self._event_bus.subscribe("goal.activated", self._on_goal_event)
        self._event_bus.subscribe("goal.completed", self._on_goal_event)
        self._event_bus.subscribe("autonomy.cycle_completed", self._on_autonomy_event)
        self._event_bus.subscribe("autonomous_learning.research_completed", self._on_learning_event)
        self._event_bus.subscribe("component.registered", self._on_component_event)
        self._event_bus.subscribe("health.check.completed", self._on_health_event)

    def start(self) -> None:
        """Start the awareness service."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._awareness_thread = threading.Thread(
            target=self._awareness_loop,
            daemon=True,
            name="RuntimeAwareness"
        )
        self._awareness_thread.start()
        logger.info("RuntimeAwareness started")

    def stop(self) -> None:
        """Stop the awareness service."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._awareness_thread and self._awareness_thread.is_alive():
            self._awareness_thread.join(timeout=5.0)

        logger.info("RuntimeAwareness stopped")

    def _awareness_loop(self) -> None:
        """Background awareness update loop."""
        while self._running:
            try:
                self.update_awareness()
            except Exception as e:
                logger.error(f"Error in awareness loop: {e}")

            time.sleep(self._config.update_interval_seconds)

    def update_awareness(self) -> RuntimeAwarenessState:
        """Update and return current runtime awareness state."""
        start_time = time.perf_counter()

        # Gather all awareness components
        state = RuntimeAwarenessState()

        # 1. Current activity (from ActivityReporter)
        self._gather_current_activity(state)

        # 2. Running/queued tasks (from TaskExecutor)
        self._gather_running_tasks(state)

        # 3. Active goals (from GoalStorage)
        self._gather_active_goals(state)

        # 4. Current reasoning state (from DecisionManager, Planner)
        self._gather_reasoning_state(state)

        # 5. Tool usage (from orchestrator capability registry)
        self._gather_tool_usage(state)

        # 6. Resource consumption (from ObservabilityHub, WorldModel)
        self._gather_resource_consumption(state)

        # 7. System health (from ObservabilityHub)
        self._gather_system_health(state)

        # 8. Memory state (from UnifiedRetrieval, GoalStorage)
        self._gather_memory_state(state)

        # 9. Pending work (from WorkflowComposer, TaskExecutor, JobService)
        self._gather_pending_work(state)

        # 10. Autonomous background activities (from AutonomyManager, LearningPipeline)
        self._gather_autonomous_activities(state)

        # 11. Overall execution context (composite)
        self._gather_execution_context(state)

        # Update metadata
        state.metadata["collection_time_ms"] = (time.perf_counter() - start_time) * 1000
        state.metadata["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Store current state
        with self._lock:
            self._current_state = state
            self._awareness_history.append(state)
            if len(self._awareness_history) > self._max_history:
                self._awareness_history.pop(0)

        # Update metric cache for trends
        self._update_metric_cache(state)

        # Emit event
        self._event_bus.emit(
            "runtime_awareness.updated",
            data={
                "awareness_id": state.awareness_id,
                "activity": state.current_activity,
                "running_tasks": len(state.running_tasks),
                "active_goals": len(state.active_goals),
                "cpu_usage": state.cpu_usage,
                "memory_usage_mb": state.memory_usage_mb,
                "system_health": state.system_health_status,
            },
            source="RuntimeAwareness"
        )

        # Record metrics
        self._observability.record_metric("runtime_awareness.running_tasks", len(state.running_tasks))
        self._observability.record_metric("runtime_awareness.active_goals", len(state.active_goals))
        self._observability.record_metric("runtime_awareness.cpu_usage", state.cpu_usage)
        self._observability.record_metric("runtime_awareness.memory_usage_mb", state.memory_usage_mb)
        self._observability.record_metric("runtime_awareness.pending_workflows", state.pending_workflows)

        logger.debug(
            f"Runtime awareness updated: activity={state.current_activity}, "
            f"tasks={len(state.running_tasks)}, goals={len(state.active_goals)}, "
            f"cpu={state.cpu_usage:.1f}%, mem={state.memory_usage_mb:.0f}MB"
        )

        return state

    def _gather_current_activity(self, state: RuntimeAwarenessState) -> None:
        """Gather current activity from ActivityReporter."""
        if self._orchestrator and self._orchestrator.activity_reporter:
            reporter = self._orchestrator.activity_reporter
            recent = reporter.get_recent_summary(5)
            if recent:
                state.current_activity = "working"
                state.activity_description = recent
                state.activity_start_time = datetime.now(timezone.utc).isoformat()
            else:
                state.current_activity = "idle"
                state.activity_description = "No recent activity"
        else:
            state.current_activity = "idle"
            state.activity_description = "Activity reporter not available"

    def _gather_running_tasks(self, state: RuntimeAwarenessState) -> None:
        """Gather running and queued tasks from TaskExecutor."""
        if self._orchestrator and self._orchestrator.task_executor:
            executor = self._orchestrator.task_executor

            # Get active workflows
            with executor._lock:
                for wf_id, ctx in executor._active_executions.items():
                    task_info = {
                        "workflow_id": wf_id,
                        "status": ctx.task_graph.get_status_summary() if hasattr(ctx.task_graph, 'get_status_summary') else "running",
                        "current_step": ctx.current_step_index,
                        "total_steps": len(ctx.task_graph.nodes) if ctx.task_graph else 0,
                        "completed_steps": list(ctx.completed_steps) if ctx.completed_steps else [],
                        "paused": ctx.pause_requested,
                        "cancel_requested": ctx.cancel_requested,
                    }
                    state.running_tasks.append(task_info)

                # Also get queued workflows from workflow composer
                if self._orchestrator.workflow_composer:
                    wf_stats = self._orchestrator.workflow_composer.get_stats()
                    # Could add pending workflows here

    def _gather_active_goals(self, state: RuntimeAwarenessState) -> None:
        """Gather active goals from GoalStorage."""
        if self._goal_storage:
            active_goal = self._goal_storage.active_goal()
            if active_goal:
                state.current_goal = active_goal.to_dict()

            # Get all goals and filter active ones
            all_goals = list(self._goal_storage._goals.values())
            for goal in all_goals:
                if goal.status in ("active", "in_progress", "pending"):
                    state.active_goals.append(goal.to_dict())

    def _gather_reasoning_state(self, state: RuntimeAwarenessState) -> None:
        """Gather current reasoning state from DecisionManager and Planner."""
        if self._decision_manager:
            stats = self._decision_manager.get_statistics()
            state.reasoning_phase = "deciding"
            state.reasoning_context = {
                "total_decisions": stats.get("total_decisions", 0),
                "auto_executed": stats.get("auto_executed", 0),
                "human_review_required": stats.get("human_review_required", 0),
                "avg_confidence": stats.get("avg_confidence", 0.0),
            }
            state.decision_history = []  # Could be populated from history
        else:
            state.reasoning_phase = "observing"
            state.reasoning_context = {}

    def _gather_tool_usage(self, state: RuntimeAwarenessState) -> None:
        """Gather tool usage from capability registry."""
        if self._orchestrator and self._orchestrator.capability_registry:
            caps = self._orchestrator.capability_registry.list_capabilities(active_only=True)
            state.active_tools = [c.name for c in caps]

            # Get tool stats if available
            for cap in caps:
                if hasattr(cap, 'execution_count'):
                    state.tool_success_rates[cap.name] = 1.0  # placeholder

    def _gather_resource_consumption(self, state: RuntimeAwarenessState) -> None:
        """Gather resource consumption from ObservabilityHub, WorldModel, and GPU monitor."""
        # Get system metrics
        system_metrics = self._observability.get_system_metrics()
        state.cpu_usage = system_metrics.get("system.cpu.percent", 0.0)
        state.memory_usage_mb = system_metrics.get("system.process.memory_mb", 0.0)
        state.disk_io_mb_s = system_metrics.get("system.disk.read_mb_s", 0.0) + system_metrics.get("system.disk.write_mb_s", 0.0)
        state.network_io_mb_s = system_metrics.get("system.network.sent_mb_s", 0.0) + system_metrics.get("system.network.recv_mb_s", 0.0)

        # Get more detailed metrics from WorldModel
        if self._world_model:
            snapshot = self._world_model.get_snapshot()
            state.cpu_usage = snapshot.resources.cpu_percent
            state.memory_usage_mb = snapshot.resources.memory_used_gb * 1024

        # Get GPU metrics if available
        self._gather_gpu_metrics(state)

    def _gather_gpu_metrics(self, state: RuntimeAwarenessState) -> None:
        """Gather GPU metrics from GPU monitor."""
        try:
            from app.monitoring.gpu_monitor import get_gpu_monitor
            gpu_monitor = get_gpu_monitor()
            if gpu_monitor and gpu_monitor.enabled:
                gpu_metrics = gpu_monitor.get_current_metrics()
                if gpu_metrics:
                    total_util = 0.0
                    total_mem_used = 0.0
                    total_mem_total = 0.0
                    max_temp = None

                    for m in gpu_metrics:
                        gpu_info = {
                            "index": m.index,
                            "vendor": m.vendor.value if hasattr(m.vendor, 'value') else str(m.vendor),
                            "name": m.name,
                            "utilization_percent": m.gpu_utilization_percent,
                            "memory_percent": m.memory_utilization_percent,
                            "memory_used_mb": m.memory_used_mb,
                            "memory_total_mb": m.memory_total_mb,
                            "temperature_celsius": m.temperature_celsius,
                            "power_draw_watts": m.power_draw_watts,
                        }
                        state.gpu_devices.append(gpu_info)

                        total_util += m.gpu_utilization_percent
                        total_mem_used += m.memory_used_mb
                        total_mem_total += m.memory_total_mb

                        if m.temperature_celsius is not None:
                            if max_temp is None or m.temperature_celsius > max_temp:
                                max_temp = m.temperature_celsius

                    # Compute averages
                    if gpu_metrics:
                        state.gpu_utilization_percent = total_util / len(gpu_metrics)
                        state.gpu_memory_used_mb = total_mem_used
                        state.gpu_memory_total_mb = total_mem_total
                        state.gpu_temperature_celsius = max_temp

        except Exception:
            # GPU monitoring not available or error
            pass

    def _gather_system_health(self, state: RuntimeAwarenessState) -> None:
        """Gather system health from ObservabilityHub."""
        health = self._observability.get_health()
        state.system_health_status = health.get("status", "unknown")
        alerts = self._observability.get_active_alerts()
        state.alerts = alerts

        # Component health
        components = self._observability.list_components()
        for comp in components:
            state.component_health[comp["name"]] = comp["status"]

    def _gather_memory_state(self, state: RuntimeAwarenessState) -> None:
        """Gather memory state from UnifiedRetrieval and GoalStorage."""
        # Working memory - from unified retrieval
        if self._memory_retrieval:
            # Could get working memory stats
            state.working_memory_size = 0  # placeholder

        # Long-term memory
        if self._goal_storage:
            state.long_term_memory_size = len(self._goal_storage._goals)

        # Consolidation status - from autonomous learning
        if self._autonomous_learning:
            state.consolidation_status = "idle"  # placeholder

    def _gather_pending_work(self, state: RuntimeAwarenessState) -> None:
        """Gather pending work from various sources."""
        # Pending workflows from workflow composer
        if self._orchestrator and self._orchestrator.workflow_composer:
            wf_stats = self._orchestrator.workflow_composer.get_stats()
            state.pending_workflows = wf_stats.get("by_status", {}).get("pending", 0)

        # Pending decisions - could check decision manager
        state.pending_decisions = 0  # placeholder

        # Pending approvals from safety gate
        if self._orchestrator and self._orchestrator.safety_gate:
            state.pending_approvals = 0  # placeholder

        # Background jobs
        from app.core.background_jobs import get_job_service
        job_service = get_job_service()
        state.background_jobs = len(job_service.get_jobs()) if hasattr(job_service, 'get_jobs') else 0

    def _gather_autonomous_activities(self, state: RuntimeAwarenessState) -> None:
        """Gather autonomous background activities."""
        # From autonomy manager
        if self._autonomy_manager:
            # Would check for self-initiated work, maintenance tasks, etc.
            state.autonomous_activities = []
            state.maintenance_tasks = []
            state.learning_tasks = []

        # From autonomous learning
        if self._autonomous_learning:
            # Would check for active research, gap detection, etc.
            pass

    def _gather_execution_context(self, state: RuntimeAwarenessState) -> None:
        """Gather overall execution context."""
        if self._orchestrator:
            state.session_duration_seconds = self._orchestrator.get_system_status().get("orchestrator", {}).get("uptime_seconds", 0)

        state.execution_mode = "autonomous" if (self._autonomy_manager and self._autonomy_manager.is_running) else "normal"

        # Count totals
        if self._orchestrator and self._orchestrator.task_executor:
            stats = self._orchestrator.task_executor.get_stats()
            state.total_tasks_completed = stats.get("completed_workflows", 0) + stats.get("failed_workflows", 0)
            state.total_failures = stats.get("failed_workflows", 0)

        if self._decision_manager:
            stats = self._decision_manager.get_statistics()
            state.total_decisions_made = stats.get("total_decisions", 0)

    def _update_metric_cache(self, state: RuntimeAwarenessState) -> None:
        """Update metric cache for trend analysis."""
        now = time.time()
        with self._cache_lock:
            metrics = {
                "awareness.cpu_usage": state.cpu_usage,
                "awareness.memory_usage_mb": state.memory_usage_mb,
                "awareness.running_tasks": len(state.running_tasks),
                "awareness.active_goals": len(state.active_goals),
                "awareness.pending_workflows": state.pending_workflows,
                "awareness.background_jobs": state.background_jobs,
                "awareness.session_duration": state.session_duration_seconds,
            }

            # Add GPU metrics if available
            if state.gpu_devices:
                metrics["awareness.gpu_utilization_percent"] = state.gpu_utilization_percent
                metrics["awareness.gpu_memory_used_mb"] = state.gpu_memory_used_mb
                metrics["awareness.gpu_memory_total_mb"] = state.gpu_memory_total_mb
                if state.gpu_temperature_celsius is not None:
                    metrics["awareness.gpu_temperature_celsius"] = state.gpu_temperature_celsius

            for key, value in metrics.items():
                if key not in self._metric_cache:
                    self._metric_cache[key] = []
                self._metric_cache[key].append((now, value))

                # Trim old entries
                cutoff = now - self._config.trend_window_seconds
                self._metric_cache[key] = [(t, v) for t, v in self._metric_cache[key] if t > cutoff]

    def get_trend(self, metric_name: str, window_seconds: float = 300.0) -> Dict[str, Any]:
        """Get trend data for a metric."""
        key = f"awareness.{metric_name}" if not metric_name.startswith("awareness.") else metric_name
        with self._cache_lock:
            data = self._metric_cache.get(key, [])

        if len(data) < self._config.min_samples_for_trend:
            return {"trend": "insufficient_data", "samples": len(data)}

        cutoff = time.time() - window_seconds
        recent = [(t, v) for t, v in data if t > cutoff]

        if len(recent) < 2:
            return {"trend": "insufficient_data", "samples": len(recent)}

        t_vals = [t for t, _ in recent]
        v_vals = [v for _, v in recent]
        t_mean = sum(t_vals) / len(t_vals)
        v_mean = sum(v_vals) / len(v_vals)

        numerator = sum((t - t_mean) * (v - v_mean) for t, v in recent)
        denominator = sum((t - t_mean) ** 2 for t in t_vals)

        slope = numerator / denominator if denominator > 0 else 0

        if abs(slope) < 0.0001:
            trend = "stable"
        elif slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        return {
            "trend": trend,
            "slope": slope,
            "samples": len(recent),
            "current_value": v_vals[-1],
            "mean_value": v_mean,
        }

    def get_all_trends(self, window_seconds: float = 300.0) -> Dict[str, Any]:
        """Get trends for all cached metrics."""
        with self._cache_lock:
            metric_names = list(self._metric_cache.keys())

        return {
            name.replace("awareness.", ""): self.get_trend(name, window_seconds)
            for name in metric_names
        }

    # Event handlers for real-time updates
    def _on_activity_event(self, event: Event) -> None:
        pass  # State updated on next loop

    def _on_workflow_event(self, event: Event) -> None:
        pass

    def _on_task_event(self, event: Event) -> None:
        pass

    def _on_decision_event(self, event: Event) -> None:
        pass

    def _on_goal_event(self, event: Event) -> None:
        pass

    def _on_autonomy_event(self, event: Event) -> None:
        pass

    def _on_learning_event(self, event: Event) -> None:
        pass

    def _on_component_event(self, event: Event) -> None:
        data = event.data or {}
        self._component_status[data.get("name", "")] = data.get("status", "unknown")

    def _on_health_event(self, event: Event) -> None:
        pass

    # Public API
    def get_current_state(self) -> Optional[RuntimeAwarenessState]:
        """Get the most recent awareness state."""
        with self._lock:
            return self._current_state

    def get_history(self, limit: int = 10) -> List[RuntimeAwarenessState]:
        """Get awareness history."""
        with self._lock:
            return self._awareness_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get awareness service statistics."""
        with self._lock:
            return {
                "running": self._running,
                "total_updates": len(self._awareness_history),
                "current_state": self._current_state.awareness_id if self._current_state else None,
                "update_interval_seconds": self._config.update_interval_seconds,
                "cached_metrics": list(self._metric_cache.keys()),
                "tracked_components": len(self._component_status),
            }

    def get_component(self, name: str) -> Optional[AwarenessComponent]:
        """Get a specific awareness component by name."""
        if not self._current_state:
            return None

        # Map component names to AwarenessComponent enums
        component_map = {
            "current_activity": AwarenessComponent.CURRENT_ACTIVITY,
            "running_tasks": AwarenessComponent.RUNNING_TASKS,
            "active_goals": AwarenessComponent.ACTIVE_GOALS,
            "reasoning_state": AwarenessComponent.CURRENT_REASONING_STATE,
            "tool_usage": AwarenessComponent.TOOL_USAGE,
            "resource_consumption": AwarenessComponent.RESOURCE_CONSUMPTION,
            "system_health": AwarenessComponent.SYSTEM_HEALTH,
            "memory_state": AwarenessComponent.MEMORY_STATE,
            "pending_work": AwarenessComponent.PENDING_WORK,
            "autonomous_activities": AwarenessComponent.AUTONOMOUS_BACKGROUND_ACTIVITIES,
            "execution_context": AwarenessComponent.OVERALL_EXECUTION_CONTEXT,
        }

        comp = component_map.get(name)
        return comp

    def get_summary(self) -> Dict[str, Any]:
        """Get a human-readable summary of current runtime awareness."""
        if not self._current_state:
            return {"status": "no_data"}

        s = self._current_state
        summary = {
            "activity": s.current_activity,
            "description": s.activity_description,
            "running_tasks": len(s.running_tasks),
            "active_goals": len(s.active_goals),
            "current_goal": s.current_goal.get("name") if s.current_goal else None,
            "reasoning_phase": s.reasoning_phase,
            "active_tools": len(s.active_tools),
            "cpu_usage": f"{s.cpu_usage:.1f}%",
            "memory_mb": f"{s.memory_usage_mb:.0f}",
            "system_health": s.system_health_status,
            "pending_workflows": s.pending_workflows,
            "pending_approvals": s.pending_approvals,
            "background_jobs": s.background_jobs,
            "autonomous_activities": len(s.autonomous_activities),
            "execution_mode": s.execution_mode,
            "session_duration": f"{s.session_duration_seconds/60:.1f}m",
            "total_decisions": s.total_decisions_made,
            "total_tasks": s.total_tasks_completed,
            "total_failures": s.total_failures,
        }

        # Add GPU info if available
        if s.gpu_devices:
            summary["gpu_devices"] = len(s.gpu_devices)
            summary["gpu_utilization"] = f"{s.gpu_utilization_percent:.1f}%"
            summary["gpu_memory_used_mb"] = f"{s.gpu_memory_used_mb:.0f}"
            summary["gpu_memory_total_mb"] = f"{s.gpu_memory_total_mb:.0f}"
            if s.gpu_temperature_celsius is not None:
                summary["gpu_temperature_celsius"] = f"{s.gpu_temperature_celsius:.1f}"

        return summary


# Global instance
_runtime_awareness: Optional[RuntimeAwareness] = None
_awareness_lock = threading.Lock()


def get_runtime_awareness(
    orchestrator: "Optional[WorkflowOrchestrator]" = None,
    decision_manager: Optional[DecisionManager] = None,
    world_model: Optional[WorldModel] = None,
    memory_retrieval: Optional[UnifiedRetrieval] = None,
    failure_recovery: Optional[RecoveryOrchestrator] = None,
    autonomous_learning: Optional[AutonomousLearningPipeline] = None,
    autonomy_manager: Optional[AutonomyManager] = None,
    goal_storage: Optional[GoalStorage] = None,
    config: Optional[AwarenessConfig] = None,
) -> RuntimeAwareness:
    """Get or create the global runtime awareness instance."""
    global _runtime_awareness
    with _awareness_lock:
        if _runtime_awareness is None:
            _runtime_awareness = RuntimeAwareness(
                orchestrator=orchestrator,
                decision_manager=decision_manager,
                world_model=world_model,
                memory_retrieval=memory_retrieval,
                failure_recovery=failure_recovery,
                autonomous_learning=autonomous_learning,
                autonomy_manager=autonomy_manager,
                goal_storage=goal_storage,
                config=config,
            )
        return _runtime_awareness


def set_runtime_awareness(awareness: RuntimeAwareness) -> None:
    """Set the global runtime awareness instance."""
    global _runtime_awareness
    with _awareness_lock:
        _runtime_awareness = awareness