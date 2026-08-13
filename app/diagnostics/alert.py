"""Diagnostics Alerting System.

This module provides alert rules and auto-recovery for the diagnostic engine.
It integrates with the existing EventBus and AlertManager architecture.
"""

import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from app.core.events import get_event_bus, Event, EventPriority
from app.core.logger import logger
from app.diagnostics.issue import Issue, IssueSeverity, IssueType
from app.monitoring.alert_manager import AlertManager, SystemAlert, AlertSeverity, AlertStatus


class DiagnosticAlertType(Enum):
    """Types of diagnostic alerts."""
    HIGH_ERROR_COUNT = "high_error_count"
    HIGH_CRITICAL_COUNT = "high_critical_count"
    SECURITY_ISSUES_FOUND = "security_issues_found"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    CODE_QUALITY_DECLINE = "code_quality_decline"
    NEW_ISSUES_INTRODUCED = "new_issues_introduced"
    UNRESOLVED_ISSUES_ACCUMULATING = "unresolved_issues_accumulating"


class RecoveryActionType(Enum):
    """Types of safe auto-recovery actions."""
    CLEAR_CACHE = "clear_cache"
    RESTART_INDEXING = "restart_indexing"
    RELOAD_CONFIG = "reload_config"
    CLEAR_TEMP_FILES = "clear_temp_files"
    RESET_CONNECTIONS = "reset_connections"
    REFRESH_CAPABILITIES = "refresh_capabilities"


@dataclass
class DiagnosticAlertRule:
    """Rule for generating diagnostic alerts."""
    rule_id: str
    name: str
    description: str
    alert_type: DiagnosticAlertType
    condition: Callable[[Dict[str, Any]], bool]
    severity: AlertSeverity = field(default=AlertSeverity.MEDIUM)
    cooldown_seconds: float = 300.0
    enabled: bool = True
    auto_recovery: Optional[RecoveryActionType] = None
    recovery_max_attempts: int = 3
    recovery_cooldown_seconds: float = 3600.0
    last_triggered: Optional[float] = None
    recovery_attempts: int = 0
    last_recovery_at: Optional[float] = None


@dataclass
class DiagnosticAlert:
    """A diagnostic alert that was triggered."""
    alert_id: str
    rule_id: str
    rule_name: str
    alert_type: DiagnosticAlertType
    severity: AlertSeverity
    message: str
    details: Dict[str, Any]
    triggered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    acknowledged: bool = False
    recovery_attempted: bool = False
    recovery_success: bool = False


class CircuitBreaker:
    """Circuit breaker to prevent recovery loops."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 3600.0,
        half_open_max_calls: int = 1
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._failure_count = 0
        self._last_failure_time = None
        self._state = "closed"  # closed, open, half-open
        self._half_open_calls = 0
        self._lock = threading.RLock()

    @property
    def state(self):
        with self._lock:
            if self._state == "open":
                if self._last_failure_time and (time.time() - self._last_failure_time) >= self.recovery_timeout:
                    self._state = "half-open"
                    self._half_open_calls = 0
            return self._state

    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        with self._lock:
            if self.state == "open":
                raise CircuitBreakerOpenError("Circuit breaker is open")

            if self.state == "half-open":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError("Circuit breaker half-open limit reached")
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._half_open_calls = 0

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = "open"
            if self._state == "half-open":
                self._state = "open"

    def reset(self):
        """Manually reset the circuit breaker."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._half_open_calls = 0
            self._last_failure_time = None


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker prevents an action."""
    pass


class DiagnosticAlerter:
    """
    Alerting system for diagnostics.

    Connects diagnostic engine results to EventBus and AlertManager.
    Provides safe, bounded auto-recovery actions.
    """

    def __init__(
        self,
        workspace: str = ".",
        event_bus = None,
        alert_manager = None,
        config_path = None,
    ):
        self.workspace = Path(workspace).resolve()
        self._event_bus = event_bus or get_event_bus()
        self._alert_manager = alert_manager or AlertManager(str(self.workspace))
        self._lock = threading.RLock()

        # Alert rules
        self._alert_rules = {}

        # Active alerts
        self._active_alerts = {}
        self._alert_history = []
        self._max_alerts = 1000

        # Circuit breakers for each recovery action
        self._circuit_breakers = {}

        # Recovery callbacks
        self._recovery_handlers = {}

        # Stats
        self._stats = {
            "total_alerts_triggered": 0,
            "total_recoveries_attempted": 0,
            "total_recoveries_succeeded": 0,
            "last_check": None,
        }

        # Initialize default alert rules
        self._initialize_default_rules()

        # Initialize circuit breakers
        self._initialize_circuit_breakers()

        # Initialize recovery handlers (to be overridden by integration)
        self._initialize_default_recovery_handlers()

        # Register callback with alert manager
        self._alert_manager.add_callback(self._on_system_alert)

        # Subscribe to diagnostic events
        self._subscribe_to_events()

    def _initialize_default_rules(self):
        """Initialize default diagnostic alert rules."""
        rules = [
            DiagnosticAlertRule(
                rule_id="diag_high_critical",
                name="High Critical Issues",
                description="Critical severity issues detected",
                alert_type=DiagnosticAlertType.HIGH_CRITICAL_COUNT,
                condition=lambda metrics: metrics.get("critical_count", 0) > 0,
                severity=AlertSeverity.CRITICAL,
                cooldown_seconds=600.0,
                auto_recovery=RecoveryActionType.REFRESH_CAPABILITIES,
            ),
            DiagnosticAlertRule(
                rule_id="diag_high_error",
                name="High Error Count",
                description="Error severity issues exceed threshold",
                alert_type=DiagnosticAlertType.HIGH_ERROR_COUNT,
                condition=lambda metrics: metrics.get("error_count", 0) > 10,
                severity=AlertSeverity.HIGH,
                cooldown_seconds=300.0,
                auto_recovery=RecoveryActionType.CLEAR_CACHE,
            ),
            DiagnosticAlertRule(
                rule_id="diag_security_issues",
                name="Security Issues Found",
                description="Security-type diagnostic issues detected",
                alert_type=DiagnosticAlertType.SECURITY_ISSUES_FOUND,
                condition=lambda metrics: metrics.get("security_count", 0) > 0,
                severity=AlertSeverity.CRITICAL,
                cooldown_seconds=600.0,
            ),
            DiagnosticAlertRule(
                rule_id="diag_quality_decline",
                name="Code Quality Decline",
                description="Code quality issues exceed threshold",
                alert_type=DiagnosticAlertType.CODE_QUALITY_DECLINE,
                condition=lambda metrics: metrics.get("code_quality_count", 0) > 50,
                severity=AlertSeverity.MEDIUM,
                cooldown_seconds=1800.0,
            ),
            DiagnosticAlertRule(
                rule_id="diag_new_issues",
                name="New Issues Introduced",
                description="New issues detected since last run",
                alert_type=DiagnosticAlertType.NEW_ISSUES_INTRODUCED,
                condition=lambda metrics: metrics.get("new_issues_count", 0) > 5,
                severity=AlertSeverity.MEDIUM,
                cooldown_seconds=600.0,
            ),
            DiagnosticAlertRule(
                rule_id="diag_unresolved_accumulating",
                name="Unresolved Issues Accumulating",
                description="Unresolved issues count growing",
                alert_type=DiagnosticAlertType.UNRESOLVED_ISSUES_ACCUMULATING,
                condition=lambda metrics: metrics.get("unresolved_count", 0) > 100,
                severity=AlertSeverity.HIGH,
                cooldown_seconds=3600.0,
                auto_recovery=RecoveryActionType.RELOAD_CONFIG,
            ),
        ]

        for rule in rules:
            self.add_alert_rule(rule)

    def _initialize_circuit_breakers(self):
        """Initialize circuit breakers for each recovery action."""
        for action in RecoveryActionType:
            self._circuit_breakers[action] = CircuitBreaker(
                failure_threshold=3,
                recovery_timeout=3600.0,  # 1 hour
                half_open_max_calls=1
            )

    def _initialize_default_recovery_handlers(self):
        """Initialize default no-op recovery handlers."""
        # These are placeholders - actual handlers should be registered by the integrating component
        for action in RecoveryActionType:
            self._recovery_handlers[action] = self._default_recovery_handler

    def _default_recovery_handler(self, action, alert):
        """Default no-op recovery handler."""
        logger.info("[DiagnosticAlerter] Recovery action {} requested but no handler registered".format(action.value))
        return False

    def _subscribe_to_events(self):
        """Subscribe to relevant diagnostic events."""
        self._event_bus.subscribe("diagnostic.run.started", self._on_diagnostic_started)
        self._event_bus.subscribe("diagnostic.run.completed", self._on_diagnostic_completed)
        self._event_bus.subscribe("diagnostic.run.failed", self._on_diagnostic_failed)

    def _on_diagnostic_started(self, event):
        """Handle diagnostic run started event."""
        self._stats["last_check"] = datetime.now(timezone.utc).isoformat()
        logger.debug("[DiagnosticAlerter] Diagnostic run started: {}".format(event.data))

    def _on_diagnostic_completed(self, event):
        """Handle diagnostic run completed event - check alert rules."""
        data = event.data if hasattr(event, "data") else event
        metrics = self._extract_diagnostic_metrics(data)
        self._check_alert_rules(metrics)

    def _on_diagnostic_failed(self, event):
        """Handle diagnostic run failed event."""
        data = event.data if hasattr(event, "data") else event
        logger.error("[DiagnosticAlerter] Diagnostic run failed: {}".format(data))

    def _on_system_alert(self, alert):
        """Handle alert from AlertManager."""
        logger.debug("[DiagnosticAlerter] System alert received: {}".format(alert.title))

    def _extract_diagnostic_metrics(self, data):
        """Extract metrics from diagnostic run data."""
        metrics = {
            "critical_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "security_count": 0,
            "code_quality_count": 0,
            "performance_count": 0,
            "unresolved_count": 0,
            "new_issues_count": 0,
            "total_issues": 0,
        }

        try:
            issues = []
            if hasattr(data, "get"):
                issues = data.get("issues", [])
            elif hasattr(data, "issues"):
                issues = data.issues
            elif isinstance(data, list):
                issues = data
            else:
                issues = []

            # Track seen issues for new issue detection
            seen_issue_keys = set()

            for issue in issues:
                if hasattr(issue, "severity"):
                    sev = issue.severity
                    if isinstance(sev, IssueSeverity):
                        sev = sev.value
                elif isinstance(issue, dict):
                    sev = issue.get("severity", "info")
                else:
                    sev = "info"

                if sev == "critical":
                    metrics["critical_count"] += 1
                elif sev == "error":
                    metrics["error_count"] += 1
                elif sev == "warning":
                    metrics["warning_count"] += 1
                elif sev == "info":
                    metrics["info_count"] += 1

                # Issue type
                if hasattr(issue, "issue_type"):
                    itype = issue.issue_type
                    if isinstance(itype, IssueType):
                        itype = itype.value
                elif isinstance(issue, dict):
                    itype = issue.get("type", "bug")
                else:
                    itype = "bug"

                if itype == "security":
                    metrics["security_count"] += 1
                elif itype == "code_quality":
                    metrics["code_quality_count"] += 1
                elif itype == "performance":
                    metrics["performance_count"] += 1

                # Resolved status
                if hasattr(issue, "resolved"):
                    resolved = issue.resolved
                elif isinstance(issue, dict):
                    resolved = issue.get("resolved", False)
                else:
                    resolved = False

                if not resolved:
                    metrics["unresolved_count"] += 1

                # Create key for new issue detection
                if hasattr(issue, "id"):
                    key = issue.id
                elif isinstance(issue, dict):
                    key = issue.get("id", "")
                else:
                    key = ""

                if key and key not in seen_issue_keys:
                    seen_issue_keys.add(key)

            # New issues would need comparison with previous run
            # For now, we use a simple heuristic
            metrics["new_issues_count"] = metrics["unresolved_count"]  # Simplified
            metrics["total_issues"] = len(issues)

        except Exception as e:
            logger.error("[DiagnosticAlerter] Error extracting metrics: {}".format(e))

        return metrics

    def _check_alert_rules(self, metrics):
        """Check all alert rules against current metrics."""
        now = time.time()

        for rule_id, rule in self._alert_rules.items():
            if not rule.enabled:
                continue

            # Check cooldown
            if rule.last_triggered and (now - rule.last_triggered) < rule.cooldown_seconds:
                continue

            try:
                triggered = rule.condition(metrics)
            except Exception as e:
                logger.error("[DiagnosticAlerter] Error evaluating rule {}: {}".format(rule_id, e))
                continue

            if triggered:
                self._trigger_alert(rule, metrics, now)

    def _trigger_alert(self, rule, metrics, now):
        """Trigger a diagnostic alert."""
        alert = DiagnosticAlert(
            alert_id="diag_alert_%d" % int(now * 1000),
            rule_id=rule.rule_id,
            rule_name=rule.name,
            alert_type=rule.alert_type,
            severity=rule.severity,
            message="{}: {}".format(rule.description, metrics),
            details=metrics,
        )

        with self._lock:
            self._active_alerts[alert.alert_id] = alert
            self._alert_history.append(alert)
            if len(self._alert_history) > self._max_alerts:
                self._alert_history.pop(0)
            rule.last_triggered = now
            self._stats["total_alerts_triggered"] += 1

        # Publish to EventBus
        self._publish_diagnostic_alert_event(alert)

        # Also trigger in AlertManager for unified alerting
        system_alert = SystemAlert(
            id=alert.alert_id,
            title="Diagnostic: {}".format(rule.name),
            description=alert.message,
            severity=rule.severity,
            metric_name=rule.alert_type.value,
            current_value=1.0,
            threshold=1.0,
            tags=["diagnostic", rule.alert_type.value],
            context={"rule_id": rule.rule_id, "metrics": metrics},
        )
        self._alert_manager.trigger(system_alert)

        logger.warning("[DiagnosticAlerter] Alert triggered: {}".format(alert.message))

        # Attempt auto-recovery if configured
        if rule.auto_recovery:
            self._attempt_recovery(rule, alert)

    def _publish_diagnostic_alert_event(self, alert):
        """Publish alert event to EventBus."""
        self._event_bus.emit(
            name="diagnostic.alert.triggered",
            data={
                "alert_id": alert.alert_id,
                "rule_id": alert.rule_id,
                "rule_name": alert.rule_name,
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "message": alert.message,
                "details": alert.details,
                "triggered_at": alert.triggered_at,
            },
            source="diagnostic_alerter",
            priority=EventPriority.HIGH if alert.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL) else EventPriority.NORMAL,
            tags={"diagnostic": "true", "alert_type": alert.alert_type.value},
        )

    def _attempt_recovery(self, rule, alert):
        """Attempt auto-recovery with circuit breaker protection."""
        action = rule.auto_recovery
        if not action:
            return

        # Check recovery cooldown
        now = time.time()
        if rule.last_recovery_at and (now - rule.last_recovery_at) < rule.recovery_cooldown_seconds:
            logger.debug("[DiagnosticAlerter] Recovery cooldown active for {}".format(rule.name))
            return

        # Check max attempts
        if rule.recovery_attempts >= rule.recovery_max_attempts:
            logger.warning("[DiagnosticAlerter] Max recovery attempts reached for {}".format(rule.name))
            return

        # Check circuit breaker
        circuit_breaker = self._circuit_breakers.get(action)
        if not circuit_breaker:
            logger.error("[DiagnosticAlerter] No circuit breaker for action {}".format(action))
            return

        # Check if already attempted for this alert
        if alert.recovery_attempted:
            return

        alert.recovery_attempted = True
        rule.recovery_attempts += 1
        rule.last_recovery_at = now
        self._stats["total_recoveries_attempted"] += 1

        # Run recovery with circuit breaker
        def do_recovery():
            handler = self._recovery_handlers.get(action)
            if not handler:
                raise ValueError("No handler for recovery action {}".format(action))
            return handler(action, alert)

        try:
            success = circuit_breaker.call(do_recovery)
            alert.recovery_success = success
            if success:
                self._stats["total_recoveries_succeeded"] += 1
                logger.info("[DiagnosticAlerter] Recovery {} succeeded for alert {}".format(action.value, alert.alert_id))
            else:
                logger.warning("[DiagnosticAlerter] Recovery {} returned False for alert {}".format(action.value, alert.alert_id))
        except CircuitBreakerOpenError:
            logger.warning("[DiagnosticAlerter] Circuit breaker open, skipping recovery {}".format(action.value))
            rule.recovery_attempts -= 1  # Don't count circuit breaker opens as attempts
        except Exception as e:
            logger.error("[DiagnosticAlerter] Recovery {} failed: {}".format(action.value, e))

    # Public API for integration

    def add_alert_rule(self, rule):
        """Add a diagnostic alert rule."""
        with self._lock:
            self._alert_rules[rule.rule_id] = rule

    def remove_alert_rule(self, rule_id):
        """Remove an alert rule."""
        with self._lock:
            if rule_id in self._alert_rules:
                del self._alert_rules[rule_id]
                return True
            return False

    def set_recovery_handler(self, action, handler):
        """Set a custom recovery handler for an action."""
        self._recovery_handlers[action] = handler

    def get_active_alerts(self):
        """Get currently active diagnostic alerts."""
        with self._lock:
            return list(self._active_alerts.values())

    def get_alert_history(self, limit=100):
        """Get diagnostic alert history."""
        with self._lock:
            return self._alert_history[-limit:]

    def acknowledge_alert(self, alert_id):
        """Acknowledge a diagnostic alert."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if alert:
                alert.acknowledged = True
                alert.resolved_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    def resolve_alert(self, alert_id):
        """Manually resolve a diagnostic alert."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if alert:
                alert.resolved_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    def get_stats(self):
        """Get alerter statistics."""
        with self._lock:
            return {
                **self._stats,
                "active_alerts": len(self._active_alerts),
                "alert_rules": len(self._alert_rules),
                "circuit_breakers": {
                    action.value: cb.state for action, cb in self._circuit_breakers.items()
                },
            }

    def reset_circuit_breaker(self, action):
        """Manually reset a circuit breaker."""
        cb = self._circuit_breakers.get(action)
        if cb:
            cb.reset()

    def check_metrics(self, metrics):
        """Manually check alert rules against metrics (for testing or external use)."""
        self._check_alert_rules(metrics)


# Global instance getter
_diagnostic_alerter = None


def get_diagnostic_alerter(workspace="."):
    """Get the global diagnostic alerter instance."""
    global _diagnostic_alerter
    if _diagnostic_alerter is None:
        _diagnostic_alerter = DiagnosticAlerter(workspace=workspace)
    return _diagnostic_alerter


def set_diagnostic_alerter(alerter):
    """Set the global diagnostic alerter instance."""
    global _diagnostic_alerter
    _diagnostic_alerter = alerter
