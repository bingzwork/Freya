"""Self-Observer for the Central Autonomous Orchestrator.

Provides self-observation capabilities via ObservabilityHub including
metrics collection, health monitoring, alerting, and performance tracking.
Integrates with the orchestrator's components for comprehensive observability.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType
from app.core.events import get_event_bus, Event, EventPriority
from app.orchestrator.capability_registry import CapabilityRegistry, get_capability_registry
from app.orchestrator.workflow_composer import WorkflowComposer
from app.orchestrator.task_executor import TaskExecutor
from app.orchestrator.safety_gate import SafetyGate


logger = logging.getLogger(__name__)


class ObservationLevel(Enum):
    """Level of observation detail."""
    MINIMAL = "minimal"      # Basic health only
    STANDARD = "standard"    # Health + key metrics
    DETAILED = "detailed"    # Full metrics + traces
    DEBUG = "debug"          # Everything including debug info


@dataclass
class SystemSnapshot:
    """A snapshot of the entire system state."""
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Component states
    capability_registry: Dict[str, Any] = field(default_factory=dict)
    workflow_composer: Dict[str, Any] = field(default_factory=dict)
    task_executor: Dict[str, Any] = field(default_factory=dict)
    safety_gate: Dict[str, Any] = field(default_factory=dict)

    # Aggregated metrics
    total_capabilities: int = 0
    active_capabilities: int = 0
    total_workflows: int = 0
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0

    # Performance
    avg_workflow_duration_ms: float = 0.0
    avg_task_duration_ms: float = 0.0
    success_rate: float = 0.0

    # Health
    overall_health: HealthStatus = HealthStatus.UNKNOWN
    health_issues: List[str] = field(default_factory=list)


@dataclass
class AlertRule:
    """Rule for generating alerts."""
    rule_id: str = field(default_factory=lambda: f"alert_{uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    metric_name: str = ""
    condition: str = ""  # e.g., "> 0.8", "< 0.5"
    threshold: float = 0.0
    severity: str = "warning"  # info, warning, critical
    cooldown_seconds: float = 300.0
    enabled: bool = True
    last_triggered: Optional[float] = None


@dataclass
class Alert:
    """An activated alert."""
    alert_id: str = field(default_factory=lambda: f"alert_{uuid4().hex[:8]}")
    rule_id: str = ""
    rule_name: str = ""
    severity: str = "warning"
    message: str = ""
    metric_name: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    triggered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    acknowledged: bool = False


class SelfObserver:
    """
    Self-observation component for the Central Autonomous Orchestrator.

    Provides:
    - Continuous metrics collection from all components
    - Health monitoring with custom checks
    - Alerting based on configurable rules
    - System snapshots for debugging and analysis
    - Performance tracking and trends
    """

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
        workflow_composer: Optional[WorkflowComposer] = None,
        task_executor: Optional[TaskExecutor] = None,
        safety_gate: Optional[SafetyGate] = None,
        observation_level: ObservationLevel = ObservationLevel.STANDARD,
        snapshot_interval: float = 60.0,
    ):
        self.capability_registry = capability_registry or get_capability_registry()
        self.workflow_composer = workflow_composer
        self.task_executor = task_executor
        self.safety_gate = safety_gate

        self.observation_level = observation_level
        self.snapshot_interval = snapshot_interval

        self._observability = get_observability_hub()
        self._event_bus = get_event_bus()
        self._lock = threading.RLock()

        # State
        self._running = False
        self._stop_event = threading.Event()
        self._snapshot_thread: Optional[threading.Thread] = None
        self._snapshots: List[SystemSnapshot] = []
        self._max_snapshots = 1000

        # Alerts
        self._alert_rules: Dict[str, AlertRule] = {}
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._max_alerts = 1000

        # Performance tracking
        self._workflow_durations: List[float] = []
        self._task_durations: List[float] = []
        self._workflow_outcomes: List[bool] = []  # True = success, False = failure

        # Default alert rules
        self._initialize_default_alerts()

        # Register with observability
        self._observability.register_component(ComponentInfo(
            name="SelfObserver",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Self-observation and monitoring for the Central Autonomous Orchestrator",
            metadata={}
        ))

        # Subscribe to component events
        self._subscribe_to_events()

    def _initialize_default_alerts(self):
        """Initialize default alert rules."""
        rules = [
            AlertRule(
                name="high_failure_rate",
                description="Workflow failure rate exceeds 20%",
                metric_name="workflow_failure_rate",
                condition=">",
                threshold=0.2,
                severity="critical",
                cooldown_seconds=600.0,
            ),
            AlertRule(
                name="capability_degraded",
                description="One or more capabilities in degraded state",
                metric_name="capabilities_degraded_count",
                condition=">",
                threshold=0,
                severity="warning",
                cooldown_seconds=300.0,
            ),
            AlertRule(
                name="capability_error",
                description="Capabilities in error state",
                metric_name="capabilities_error_count",
                condition=">",
                threshold=0,
                severity="critical",
                cooldown_seconds=120.0,
            ),
            AlertRule(
                name="high_task_latency",
                description="Average task duration exceeds 30 seconds",
                metric_name="avg_task_duration_ms",
                condition=">",
                threshold=30000,
                severity="warning",
                cooldown_seconds=600.0,
            ),
            AlertRule(
                name="workflow_queue_backlog",
                description="Too many pending workflows",
                metric_name="pending_workflows",
                condition=">",
                threshold=50,
                severity="warning",
                cooldown_seconds=300.0,
            ),
            AlertRule(
                name="safety_blocks_high",
                description="High number of safety blocks",
                metric_name="safety_blocks_per_hour",
                condition=">",
                threshold=100,
                severity="warning",
                cooldown_seconds=3600.0,
            ),
            AlertRule(
                name="low_success_rate",
                description="Overall success rate below 80%",
                metric_name="success_rate",
                condition="<",
                threshold=0.8,
                severity="warning",
                cooldown_seconds=600.0,
            ),
        ]

        for rule in rules:
            self.add_alert_rule(rule)

    def _subscribe_to_events(self):
        """Subscribe to events from orchestrator components."""
        # Workflow events
        self._event_bus.subscribe("workflow.started", self._on_workflow_started)
        self._event_bus.subscribe("workflow.completed", self._on_workflow_completed)
        self._event_bus.subscribe("workflow.failed", self._on_workflow_failed)
        self._event_bus.subscribe("workflow.cancelled", self._on_workflow_cancelled)

        # Task events
        self._event_bus.subscribe("task.started", self._on_task_started)
        self._event_bus.subscribe("task.completed", self._on_task_completed)
        self._event_bus.subscribe("task.failed", self._on_task_failed)

        # Capability events
        self._event_bus.subscribe("capability.activated", self._on_capability_activated)
        self._event_bus.subscribe("capability.deactivated", self._on_capability_deactivated)
        self._event_bus.subscribe("capability.error", self._on_capability_error)

        # Safety events
        self._event_bus.subscribe("safety.assessment", self._on_safety_assessment)
        self._event_bus.subscribe("safety.approval_requested", self._on_approval_requested)

    def start(self):
        """Start the self-observer."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()

        self._snapshot_thread = threading.Thread(
            target=self._snapshot_loop,
            daemon=True,
            name="SelfObserver-Snapshots"
        )
        self._snapshot_thread.start()

        logger.info("SelfObserver started")

    def stop(self):
        """Stop the self-observer."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._snapshot_thread:
            self._snapshot_thread.join(timeout=5.0)

        logger.info("SelfObserver stopped")

    def _snapshot_loop(self):
        """Periodic snapshot collection loop."""
        while self._running:
            try:
                self._take_snapshot()
            except Exception as e:
                logger.error(f"Error taking snapshot: {e}")

            self._stop_event.wait(self.snapshot_interval)

    def _take_snapshot(self) -> SystemSnapshot:
        """Take a snapshot of the current system state."""
        snapshot = SystemSnapshot()

        # Capability registry stats
        if self.capability_registry:
            reg_stats = self.capability_registry.get_stats()
            snapshot.capability_registry = reg_stats
            snapshot.total_capabilities = reg_stats.get("total_capabilities", 0)
            snapshot.active_capabilities = reg_stats.get("by_state", {}).get("active", 0)

        # Workflow composer stats
        if self.workflow_composer:
            wf_stats = self.workflow_composer.get_stats()
            snapshot.workflow_composer = wf_stats
            snapshot.total_workflows = wf_stats.get("total_composed", 0)
            by_status = wf_stats.get("by_status", {})
            snapshot.active_workflows = by_status.get("executing", 0)
            snapshot.completed_workflows = by_status.get("completed", 0)
            snapshot.failed_workflows = by_status.get("failed", 0)

        # Task executor stats
        if self.task_executor:
            exec_stats = self.task_executor.get_stats()
            snapshot.task_executor = exec_stats

        # Safety gate stats
        if self.safety_gate:
            safety_stats = self.safety_gate.get_stats()
            snapshot.safety_gate = safety_stats

        # Calculate aggregated metrics
        self._calculate_metrics(snapshot)

        # Store snapshot
        with self._lock:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > self._max_snapshots:
                self._snapshots.pop(0)

        # Check alert rules
        self._check_alerts(snapshot)

        # Record metrics to observability
        self._record_metrics(snapshot)

        return snapshot

    def _calculate_metrics(self, snapshot: SystemSnapshot):
        """Calculate aggregated metrics from snapshot."""
        # Workflow duration
        if self._workflow_durations:
            snapshot.avg_workflow_duration_ms = sum(self._workflow_durations) / len(self._workflow_durations)

        # Task duration
        if self._task_durations:
            snapshot.avg_task_duration_ms = sum(self._task_durations) / len(self._task_durations)

        # Success rate
        if self._workflow_outcomes:
            snapshot.success_rate = sum(self._workflow_outcomes) / len(self._workflow_outcomes)

        # Overall health
        health_issues = []

        # Check capability health
        cap_reg = snapshot.capability_registry
        degraded = cap_reg.get("by_state", {}).get("degraded", 0)
        error = cap_reg.get("by_state", {}).get("error", 0)
        if degraded > 0:
            health_issues.append(f"{degraded} capabilities degraded")
        if error > 0:
            health_issues.append(f"{error} capabilities in error")

        # Check workflow health
        if snapshot.failed_workflows > 0 and snapshot.completed_workflows > 0:
            failure_rate = snapshot.failed_workflows / (snapshot.completed_workflows + snapshot.failed_workflows)
            if failure_rate > 0.2:
                health_issues.append(f"High workflow failure rate: {failure_rate:.1%}")

        # Determine overall health
        if error > 0 or (snapshot.failed_workflows > 0 and snapshot.completed_workflows == 0):
            snapshot.overall_health = HealthStatus.UNHEALTHY
        elif degraded > 0 or (snapshot.failed_workflows > 0 and snapshot.completed_workflows > 0 and
                             snapshot.failed_workflows / (snapshot.completed_workflows + snapshot.failed_workflows) > 0.1):
            snapshot.overall_health = HealthStatus.DEGRADED
        else:
            snapshot.overall_health = HealthStatus.HEALTHY

        snapshot.health_issues = health_issues

    def _check_alerts(self, snapshot: SystemSnapshot):
        """Check alert rules against current metrics."""
        # Build current metrics dict
        metrics = {
            "workflow_failure_rate": 0.0,
            "capabilities_degraded_count": 0,
            "capabilities_error_count": 0,
            "avg_task_duration_ms": snapshot.avg_task_duration_ms,
            "pending_workflows": snapshot.active_workflows,
            "safety_blocks_per_hour": 0,
            "success_rate": snapshot.success_rate,
        }

        if snapshot.completed_workflows + snapshot.failed_workflows > 0:
            metrics["workflow_failure_rate"] = snapshot.failed_workflows / (snapshot.completed_workflows + snapshot.failed_workflows)

        cap_reg = snapshot.capability_registry
        metrics["capabilities_degraded_count"] = cap_reg.get("by_state", {}).get("degraded", 0)
        metrics["capabilities_error_count"] = cap_reg.get("by_state", {}).get("error", 0)

        safety_stats = snapshot.safety_gate
        if safety_stats:
            # Approximate blocks per hour from assessments
            total = safety_stats.get("total_assessments", 0)
            blocks = safety_stats.get("actions", {}).get("block", 0)
            metrics["safety_blocks_per_hour"] = blocks  # Simplified

        now = time.time()
        for rule_id, rule in self._alert_rules.items():
            if not rule.enabled:
                continue

            # Check cooldown
            if rule.last_triggered and (now - rule.last_triggered) < rule.cooldown_seconds:
                continue

            current_value = metrics.get(rule.metric_name, 0)
            triggered = self._evaluate_condition(current_value, rule.condition, rule.threshold)

            if triggered:
                self._trigger_alert(rule, current_value, now)

    def _evaluate_condition(self, value: float, condition: str, threshold: float) -> bool:
        """Evaluate alert condition."""
        if condition == ">":
            return value > threshold
        elif condition == ">=":
            return value >= threshold
        elif condition == "<":
            return value < threshold
        elif condition == "<=":
            return value <= threshold
        elif condition == "==":
            return value == threshold
        elif condition == "!=":
            return value != threshold
        return False

    def _trigger_alert(self, rule: AlertRule, current_value: float, now: float):
        """Trigger an alert."""
        alert = Alert(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            message=f"{rule.description}: {rule.metric_name} = {current_value} (threshold: {rule.condition} {rule.threshold})",
            metric_name=rule.metric_name,
            current_value=current_value,
            threshold=rule.threshold,
        )

        with self._lock:
            self._active_alerts[alert.alert_id] = alert
            self._alert_history.append(alert)
            if len(self._alert_history) > self._max_alerts:
                self._alert_history.pop(0)
            rule.last_triggered = now

        # Publish alert event
        self._event_bus.publish(Event(
            name="observability.alert",
            data={
                "alert_id": alert.alert_id,
                "rule_name": rule.name,
                "severity": rule.severity,
                "message": alert.message,
                "metric_name": rule.metric_name,
                "current_value": current_value,
                "threshold": rule.threshold,
            },
            source="self_observer",
            priority=EventPriority.HIGH if rule.severity == "critical" else EventPriority.NORMAL
        ))

        logger.warning(f"Alert triggered: {alert.message}")

    def _record_metrics(self, snapshot: SystemSnapshot):
        """Record metrics to observability hub."""
        try:
            # Capability metrics
            cap_reg = snapshot.capability_registry
            if cap_reg:
                self._observability.record_metric("orchestrator.capabilities.total", cap_reg.get("total_capabilities", 0))
                for state, count in cap_reg.get("by_state", {}).items():
                    self._observability.record_metric(f"orchestrator.capabilities.{state}", count)

            # Workflow metrics
            wf_comp = snapshot.workflow_composer
            if wf_comp:
                self._observability.record_metric("orchestrator.workflows.total", wf_comp.get("total_composed", 0))
                for status, count in wf_comp.get("by_status", {}).items():
                    self._observability.record_metric(f"orchestrator.workflows.{status}", count)

            # Performance metrics
            self._observability.record_metric("orchestrator.performance.avg_workflow_duration_ms", snapshot.avg_workflow_duration_ms)
            self._observability.record_metric("orchestrator.performance.avg_task_duration_ms", snapshot.avg_task_duration_ms)
            self._observability.record_metric("orchestrator.performance.success_rate", snapshot.success_rate)

            # Health metric
            health_value = {
                HealthStatus.HEALTHY: 1.0,
                HealthStatus.DEGRADED: 0.5,
                HealthStatus.UNHEALTHY: 0.0,
                HealthStatus.UNKNOWN: 0.0,
            }.get(snapshot.overall_health, 0.0)
            self._observability.record_metric("orchestrator.health.overall", health_value)

        except Exception as e:
            logger.error(f"Failed to record metrics: {e}")

    # Event handlers
    def _on_workflow_started(self, event: Event):
        pass

    def _on_workflow_completed(self, event: Event):
        payload = event.data
        duration = payload.get("duration_seconds", 0) * 1000
        self._workflow_durations.append(duration)
        self._workflow_outcomes.append(True)
        if len(self._workflow_durations) > 1000:
            self._workflow_durations.pop(0)
        if len(self._workflow_outcomes) > 1000:
            self._workflow_outcomes.pop(0)

    def _on_workflow_failed(self, event: Event):
        payload = event.data
        duration = payload.get("duration_seconds", 0) * 1000
        self._workflow_durations.append(duration)
        self._workflow_outcomes.append(False)
        if len(self._workflow_durations) > 1000:
            self._workflow_durations.pop(0)
        if len(self._workflow_outcomes) > 1000:
            self._workflow_outcomes.pop(0)

    def _on_workflow_cancelled(self, event: Event):
        pass

    def _on_task_started(self, event: Event):
        pass

    def _on_task_completed(self, event: Event):
        duration = event.data.get("duration_ms", 0)
        if duration > 0:
            self._task_durations.append(duration)
            if len(self._task_durations) > 1000:
                self._task_durations.pop(0)

    def _on_task_failed(self, event: Event):
        duration = event.data.get("duration_ms", 0)
        if duration > 0:
            self._task_durations.append(duration)
            if len(self._task_durations) > 1000:
                self._task_durations.pop(0)

    def _on_capability_activated(self, event: Event):
        pass

    def _on_capability_deactivated(self, event: Event):
        pass

    def _on_capability_error(self, event: Event):
        pass

    def _on_safety_assessment(self, event: Event):
        pass

    def _on_approval_requested(self, event: Event):
        pass

    # Public API
    def add_alert_rule(self, rule: AlertRule):
        """Add an alert rule."""
        with self._lock:
            self._alert_rules[rule.rule_id] = rule

    def remove_alert_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        with self._lock:
            if rule_id in self._alert_rules:
                del self._alert_rules[rule_id]
                return True
            return False

    def get_active_alerts(self) -> List[Alert]:
        """Get currently active alerts."""
        with self._lock:
            return list(self._active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get alert history."""
        with self._lock:
            return self._alert_history[-limit:]

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if alert:
                alert.acknowledged = True
                alert.resolved_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    def get_latest_snapshot(self) -> Optional[SystemSnapshot]:
        """Get the latest system snapshot."""
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_snapshots(self, limit: int = 100) -> List[SystemSnapshot]:
        """Get recent snapshots."""
        with self._lock:
            return self._snapshots[-limit:]

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        with self._lock:
            return {
                "avg_workflow_duration_ms": sum(self._workflow_durations) / len(self._workflow_durations) if self._workflow_durations else 0,
                "avg_task_duration_ms": sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0,
                "success_rate": sum(self._workflow_outcomes) / len(self._workflow_outcomes) if self._workflow_outcomes else 0,
                "total_workflows": len(self._workflow_outcomes),
                "successful_workflows": sum(self._workflow_outcomes),
                "failed_workflows": len(self._workflow_outcomes) - sum(self._workflow_outcomes),
            }

    def is_healthy(self) -> bool:
        """Check if the system is healthy."""
        snapshot = self.get_latest_snapshot()
        if not snapshot:
            return True  # No data yet
        return snapshot.overall_health in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def get_stats(self) -> Dict[str, Any]:
        """Get observer statistics."""
        with self._lock:
            return {
                "running": self._running,
                "observation_level": self.observation_level.value,
                "snapshot_interval": self.snapshot_interval,
                "total_snapshots": len(self._snapshots),
                "active_alerts": len(self._active_alerts),
                "alert_rules": len(self._alert_rules),
                "performance": self.get_performance_stats(),
            }