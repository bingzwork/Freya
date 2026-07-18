"""Health Monitor for tracking project vital signs.

This module provides continuous monitoring of project health metrics
and can trigger alerts when thresholds are exceeded.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
import threading
import time
from pathlib import Path

from app.health.health_metrics import (
    Metric,
    HealthStatus,
    CodeQualityMetrics,
    TestMetrics,
    PerformanceMetrics,
    SystemMetrics,
)


@dataclass
class Alert:
    """Represents a health alert."""
    metric_name: str
    current_value: float
    threshold: float
    status: HealthStatus
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary."""
        return {
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
        }


class AlertCallback:
    """Base class for alert callbacks."""

    def on_alert(self, alert: Alert) -> None:
        """Called when an alert is triggered."""
        raise NotImplementedError

    def on_resolve(self, alert: Alert) -> None:
        """Called when an alert is resolved."""
        raise NotImplementedError


class LoggingAlertCallback(AlertCallback):
    """Logs alerts to the console."""

    def on_alert(self, alert: Alert) -> None:
        """Log alert to console."""
        print(f"[ALERT] {alert.status.value.upper()}: {alert.message}")

    def on_resolve(self, alert: Alert) -> None:
        """Log resolution to console."""
        print(f"[RESOLVED] {alert.metric_name}: {alert.message}")


class HealthMonitor:
    """Monitors project health metrics and triggers alerts.

    This class provides continuous monitoring of various health metrics
    and can trigger alerts when metrics fall below configured thresholds.
    """

    def __init__(
        self,
        workspace: str = ".",
        check_interval: int = 300,  # 5 minutes
        alert_callbacks: Optional[List[AlertCallback]] = None,
    ):
        """Initialize the health monitor.

        Args:
            workspace: The project workspace directory.
            check_interval: Interval between health checks in seconds.
            alert_callbacks: List of callbacks for alerts.
        """
        self.workspace = Path(workspace).resolve()
        self.check_interval = check_interval
        self.alert_callbacks = alert_callbacks or []
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._current_metrics: Dict[str, Metric] = {}
        self._alerts: Dict[str, Alert] = {}
        self._history: List[Dict[str, Any]] = []

        # Thresholds for each metric
        self.thresholds: Dict[str, Dict[str, float]] = {
            "total_files": {"excellent": 50, "good": 30, "fair": 15, "poor": 5},
            "python_files": {"excellent": 30, "good": 20, "fair": 10, "poor": 5},
            "lines_of_code": {"excellent": 10000, "good": 5000, "fair": 2000, "poor": 1000},
            "pep8_compliance": {"excellent": 95, "good": 85, "fair": 70, "poor": 50},
            "docstring_coverage": {"excellent": 80, "good": 60, "fair": 40, "poor": 20},
            "type_hint_coverage": {"excellent": 80, "good": 60, "fair": 40, "poor": 20},
            "total_tests": {"excellent": 100, "good": 50, "fair": 25, "poor": 10},
            "test_pass_rate": {"excellent": 95, "good": 85, "fair": 70, "poor": 50},
            "test_coverage": {"excellent": 80, "good": 60, "fair": 40, "poor": 20},
            "indexing_speed": {"excellent": 10, "good": 20, "fair": 30, "poor": 60},  # seconds
            "llm_response_time": {"excellent": 5, "good": 10, "fair": 20, "poor": 30},  # seconds
            "cpu_usage": {"excellent": 50, "good": 70, "fair": 80, "poor": 90},  # %
            "memory_usage": {"excellent": 50, "good": 70, "fair": 80, "poor": 90},  # %
            "disk_usage": {"excellent": 50, "good": 70, "fair": 80, "poor": 90},  # %
        }

        # Custom thresholds can be set
        self.custom_thresholds: Dict[str, Dict[str, float]] = {}

    def set_threshold(self, metric_name: str, level: str, value: float) -> None:
        """Set a custom threshold for a metric.

        Args:
            metric_name: Name of the metric.
            level: One of 'excellent', 'good', 'fair', 'poor'.
            value: Threshold value.
        """
        if metric_name not in self.custom_thresholds:
            self.custom_thresholds[metric_name] = {}
        self.custom_thresholds[metric_name][level] = value

    def get_metrics(self) -> Dict[str, Metric]:
        """Get the current metrics."""
        return self._current_metrics.copy()

    def get_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return list(self._alerts.values())

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get metric history."""
        return self._history[-limit:]

    def collect_metrics(self) -> Dict[str, Metric]:
        """Collect all health metrics."""
        metrics: Dict[str, Metric] = {}

        # Code Quality Metrics
        cq = CodeQualityMetrics(str(self.workspace))
        for m in cq.collect_all():
            self._apply_threshold(m)
            metrics[m.name] = m

        # Test Metrics
        tm = TestMetrics(str(self.workspace))
        for m in tm.collect_all():
            self._apply_threshold(m)
            metrics[m.name] = m

        # Performance Metrics
        pm = PerformanceMetrics(str(self.workspace))
        for m in pm.collect_all():
            self._apply_threshold(m)
            metrics[m.name] = m

        # System Metrics
        sm = SystemMetrics(str(self.workspace))
        for m in sm.collect_all():
            self._apply_threshold(m)
            metrics[m.name] = m

        return metrics

    def _apply_threshold(self, metric: Metric) -> None:
        """Apply custom thresholds to a metric."""
        if metric.name in self.custom_thresholds:
            thresholds = self.custom_thresholds[metric.name]
            metric.threshold_excellent = thresholds.get("excellent", metric.threshold_excellent)
            metric.threshold_good = thresholds.get("good", metric.threshold_good)
            metric.threshold_fair = thresholds.get("fair", metric.threshold_fair)
            metric.threshold_poor = thresholds.get("poor", metric.threshold_poor)

    def check_metrics(self) -> Dict[str, Alert]:
        """Check all metrics and return any alerts."""
        metrics = self.collect_metrics()
        alerts: Dict[str, Alert] = {}

        for name, metric in metrics.items():
            # Evaluate status
            metric.status = metric.evaluate_status()

            # Check for alerts (status is POOR or CRITICAL)
            if metric.status in [HealthStatus.POOR, HealthStatus.CRITICAL]:
                alert = Alert(
                    metric_name=name,
                    current_value=metric.value or 0,
                    threshold=metric.threshold_poor,
                    status=metric.status,
                    message=f"{metric.name} is {metric.status.value}: {metric.value}{metric.unit}",
                )
                alerts[name] = alert

                # Trigger callbacks
                for callback in self.alert_callbacks:
                    callback.on_alert(alert)

            # Check if previously alerted metric is now resolved
            elif name in self._alerts and metric.status in [HealthStatus.EXCELLENT, HealthStatus.GOOD, HealthStatus.FAIR]:
                old_alert = self._alerts[name]
                old_alert.resolved = True
                for callback in self.alert_callbacks:
                    callback.on_resolve(old_alert)
                del self._alerts[name]

        # Update current metrics
        self._current_metrics = metrics

        # Update alerts
        self._alerts = alerts

        # Record history
        self._record_history(metrics, alerts)

        return self._alerts

    def _record_history(self, metrics: Dict[str, Metric], alerts: Dict[str, Alert]) -> None:
        """Record metrics and alerts to history."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {name: m.to_dict() for name, m in metrics.items()},
            "alerts": {name: a.to_dict() for name, a in alerts.items()},
        }
        self._history.append(entry)
        # Keep history size reasonable
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

    def start(self) -> None:
        """Start continuous monitoring in background."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self) -> None:
        """Stop continuous monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=self.check_interval + 1)
            self._monitor_thread = None

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self.check_metrics()
            except Exception as e:
                print(f"[ERROR] Health monitor error: {e}")
            # Sleep for the check interval
            for _ in range(self.check_interval // 5):
                if not self._running:
                    break
                time.sleep(5)

    def get_health_score(self) -> float:
        """Calculate an overall health score (0-100)."""
        if not self._current_metrics:
            return 0.0

        total = 0.0
        count = 0

        for metric in self._current_metrics.values():
            if metric.value is not None:
                # Normalize to 0-100 based on thresholds
                if metric.value >= metric.threshold_excellent:
                    score = 100.0
                elif metric.value >= metric.threshold_good:
                    score = 85.0
                elif metric.value >= metric.threshold_fair:
                    score = 60.0
                elif metric.value >= metric.threshold_poor:
                    score = 30.0
                else:
                    score = 0.0
                total += score
                count += 1

        if count == 0:
            return 0.0

        return total / count

    def get_status(self) -> HealthStatus:
        """Get overall health status."""
        score = self.get_health_score()
        if score >= 85:
            return HealthStatus.EXCELLENT
        elif score >= 70:
            return HealthStatus.GOOD
        elif score >= 50:
            return HealthStatus.FAIR
        elif score >= 25:
            return HealthStatus.POOR
        else:
            return HealthStatus.CRITICAL

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current health status."""
        return {
            "status": self.get_status().value,
            "score": round(self.get_health_score(), 2),
            "metrics_count": len(self._current_metrics),
            "alerts_count": len(self._alerts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
