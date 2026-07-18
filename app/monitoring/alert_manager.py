"""Alert Manager for system monitoring alerts.

This module provides alert management capabilities including:
- Alert creation and tracking
- Alert severity levels
- Alert status management
- Alert deduplication
- Alert history
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict


class AlertSeverity(Enum):
    """Severity levels for alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def score(self) -> int:
        """Get numeric severity score."""
        scores = {
            AlertSeverity.LOW: 0,
            AlertSeverity.MEDIUM: 1,
            AlertSeverity.HIGH: 2,
            AlertSeverity.CRITICAL: 3,
        }
        return scores.get(self, 0)


class AlertStatus(Enum):
    """Status of an alert."""
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


@dataclass
class SystemAlert:
    """Represents a system alert."""
    id: str
    title: str
    description: str
    severity: AlertSeverity
    metric_name: Optional[str] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    status: AlertStatus = AlertStatus.TRIGGERED
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    related_alerts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.severity, str):
            self.severity = AlertSeverity(self.severity)
        if isinstance(self.status, str):
            self.status = AlertStatus(self.status)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemAlert":
        """Create alert from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            severity=data.get("severity", AlertSeverity.MEDIUM.value),
            metric_name=data.get("metric_name"),
            current_value=data.get("current_value"),
            threshold=data.get("threshold"),
            status=data.get("status", AlertStatus.TRIGGERED.value),
            timestamp=data.get("timestamp", ""),
            acknowledged_at=data.get("acknowledged_at"),
            acknowledged_by=data.get("acknowledged_by"),
            resolved_at=data.get("resolved_at"),
            resolved_by=data.get("resolved_by"),
            related_alerts=data.get("related_alerts", []),
            tags=data.get("tags", []),
            context=data.get("context", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "related_alerts": self.related_alerts,
            "tags": self.tags,
            "context": self.context,
        }

    def acknowledge(self, by: str = "system") -> None:
        """Acknowledge the alert."""
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = datetime.now(timezone.utc).isoformat()
        self.acknowledged_by = by

    def resolve(self, by: str = "system") -> None:
        """Resolve the alert."""
        self.status = AlertStatus.RESOLVED
        self.resolved_at = datetime.now(timezone.utc).isoformat()
        self.resolved_by = by

    def suppress(self, by: str = "system") -> None:
        """Suppress the alert."""
        self.status = AlertStatus.SUPPRESSED

    def is_active(self) -> bool:
        """Check if alert is still active (not resolved)."""
        return self.status in (AlertStatus.TRIGGERED, AlertStatus.ACKNOWLEDGED)

    def __lt__(self, other: "SystemAlert") -> bool:
        """Compare alerts by severity (higher severity first)."""
        return self.severity.score > other.severity.score


class AlertDeduplicator:
    """Deduplicates alerts based on content similarity."""

    def __init__(self, window_seconds: float = 300.0):
        """Initialize deduplicator.

        Args:
            window_seconds: Time window for deduplication
        """
        self.window_seconds = window_seconds
        self._seen_alerts: Dict[str, float] = {}

    def is_duplicate(self, alert: SystemAlert) -> bool:
        """Check if alert is a duplicate."""
        key = self._get_alert_key(alert)
        last_time = self._seen_alerts.get(key, 0.0)

        now = time.time()
        if now - last_time < self.window_seconds:
            return True

        self._seen_alerts[key] = now
        return False

    def _get_alert_key(self, alert: SystemAlert) -> str:
        """Generate a key for deduplication."""
        return f"{alert.metric_name}:{alert.severity.value}:{alert.title}"


class AlertManager:
    """Manages system alerts.

    This class provides comprehensive alert management including:
    - Alert creation and tracking
    - Alert deduplication
    - Alert history
    - Alert callbacks
    """

    def __init__(
        self,
        workspace: str = ".",
        history_size: int = 1000,
        dedup_window_seconds: float = 300.0,
    ):
        """Initialize alert manager.

        Args:
            workspace: The project workspace directory.
            history_size: Maximum number of alerts to keep in history
            dedup_window_seconds: Time window for deduplication
        """
        self.workspace = Path(workspace).resolve()
        self.history_size = history_size
        self.dedup_window_seconds = dedup_window_seconds

        # Active alerts: id -> SystemAlert
        self._active_alerts: Dict[str, SystemAlert] = {}

        # Alert history: timestamp -> SystemAlert
        self._alert_history: Dict[str, SystemAlert] = {}

        # Callbacks for new alerts
        self._alert_callbacks: List[Callable[[SystemAlert], None]] = []

        # Deduplicator
        self._deduplicator = AlertDeduplicator(dedup_window_seconds)

    def add_callback(self, callback: Callable[[SystemAlert], None]) -> None:
        """Add a callback for new alerts."""
        self._alert_callbacks.append(callback)

    def remove_callback(self, callback: Callable[[SystemAlert], None]) -> None:
        """Remove a callback."""
        if callback in self._alert_callbacks:
            self._alert_callbacks.remove(callback)

    def trigger(self, alert: SystemAlert) -> Optional[SystemAlert]:
        """Trigger a new alert.

        Args:
            alert: Alert to trigger

        Returns:
            The alert that was triggered, or None if deduplicated
        """
        # Check for duplicate
        if self._deduplicator.is_duplicate(alert):
            return None

        # Check if same alert is already active
        existing = self._active_alerts.get(alert.id)
        if existing:
            # Update existing alert
            existing.description = alert.description
            existing.current_value = alert.current_value
            existing.timestamp = alert.timestamp
            return existing

        # Add to active alerts
        self._active_alerts[alert.id] = alert
        self._alert_history[alert.id] = alert

        # Notify callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                print(f"Error in alert callback: {e}")

        # Trim history
        if len(self._alert_history) > self.history_size:
            old_keys = list(self._alert_history.keys())
            for key in old_keys[:len(old_keys) - self.history_size]:
                old_alert = self._alert_history[key]
                if old_alert.id not in self._active_alerts:
                    del self._alert_history[key]

        return alert

    def acknowledge(self, alert_id: str, by: str = "system") -> bool:
        """Acknowledge an alert.

        Args:
            alert_id: ID of the alert to acknowledge
            by: Who acknowledged the alert

        Returns:
            True if alert was found and acknowledged
        """
        alert = self._active_alerts.get(alert_id)
        if alert:
            alert.acknowledge(by)
            return True
        return False

    def resolve(self, alert_id: str, by: str = "system") -> bool:
        """Resolve an alert.

        Args:
            alert_id: ID of the alert to resolve
            by: Who resolved the alert

        Returns:
            True if alert was found and resolved
        """
        alert = self._active_alerts.get(alert_id)
        if alert:
            alert.resolve(by)
            # Move to history
            self._alert_history[alert_id] = alert
            del self._active_alerts[alert_id]
            return True
        return False

    def suppress(self, alert_id: str, by: str = "system") -> bool:
        """Suppress an alert.

        Args:
            alert_id: ID of the alert to suppress
            by: Who suppressed the alert

        Returns:
            True if alert was found and suppressed
        """
        alert = self._active_alerts.get(alert_id)
        if alert:
            alert.suppress(by)
            return True
        return False

    def get_active_alerts(self) -> List[SystemAlert]:
        """Get all active alerts."""
        return list(self._active_alerts.values())

    def get_alert(self, alert_id: str) -> Optional[SystemAlert]:
        """Get a specific alert."""
        return self._active_alerts.get(alert_id) or self._alert_history.get(alert_id)

    def get_active_by_severity(self, severity: AlertSeverity) -> List[SystemAlert]:
        """Get active alerts filtered by severity."""
        return [a for a in self._active_alerts.values() if a.severity == severity]

    def get_active_by_status(self, status: AlertStatus) -> List[SystemAlert]:
        """Get active alerts filtered by status."""
        return [a for a in self._active_alerts.values() if a.status == status]

    def get_history(self, count: Optional[int] = None, severity: Optional[AlertSeverity] = None) -> List[SystemAlert]:
        """Get alert history.

        Args:
            count: Maximum number of alerts to return
            severity: Filter by severity
        """
        alerts = list(self._alert_history.values())

        # Sort by timestamp (newest first)
        alerts = sorted(alerts, key=lambda a: a.timestamp, reverse=True)

        # Filter by severity
        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        # Limit count
        if count:
            alerts = alerts[:count]

        return alerts

    def get_worst_alerts(self, count: int = 5) -> List[SystemAlert]:
        """Get the most severe active alerts."""
        alerts = list(self._active_alerts.values())
        # Sort by severity (higher severity first) - no reverse since __lt__ already handles it
        return sorted(alerts)[:count]

    def clear(self, all_history: bool = False) -> None:
        """Clear alerts.

        Args:
            all_history: If True, also clear history
        """
        self._active_alerts.clear()
        if all_history:
            self._alert_history.clear()

    def count(self, status: Optional[AlertStatus] = None) -> Dict[str, int]:
        """Count alerts by status."""
        counts: Dict[str, int] = defaultdict(int)

        for alert in self._active_alerts.values():
            counts[alert.status.value] += 1

        if status:
            return {status.value: counts.get(status.value, 0)}

        return dict(counts)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of alerts."""
        counts = self.count()
        return {
            "active_alerts": len(self._active_alerts),
            "total_history": len(self._alert_history),
            "counts": counts,
            "worst_alerts": [a.to_dict() for a in self.get_worst_alerts(5)],
        }

    def export_json(self, path: str) -> None:
        """Export alerts to JSON file."""
        data = {
            "active_alerts": [a.to_dict() for a in self._active_alerts.values()],
            "history": [a.to_dict() for a in self._alert_history.values()],
            "summary": self.get_summary(),
        }

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# Fix circular import issue with SystemAlert type hint
# The TYPE_CHECKING block handles the forward reference
