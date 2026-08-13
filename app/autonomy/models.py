"""Data models for Autonomy + Observation components."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class WatchdogEventType(Enum):
    """Types of events the watchdog can observe."""
    SYSTEM_EVENT = "system_event"           # From EventBus
    HEALTH_CHECK = "health_check"           # From ObservabilityHub
    METRIC_ALERT = "metric_alert"           # From ObservabilityHub
    TASK_STALLED = "task_stalled"           # From workflow execution
    TASK_FAILED = "task_failed"             # From workflow execution
    RESOURCE_PRESSURE = "resource_pressure" # CPU, memory, disk
    GOAL_STALLED = "goal_stalled"           # From GoalManager
    GOAL_FAILED = "goal_failed"             # From GoalManager


class WatchdogSeverity(Enum):
    """Severity levels for watchdog observations."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class WatchdogObservation:
    """An observation from the watchdog that can be fed to the LearningPipeline."""
    id: str = field(default_factory=lambda: f"obs_{uuid4().hex[:8]}")
    event_type: WatchdogEventType = WatchdogEventType.SYSTEM_EVENT
    severity: WatchdogSeverity = WatchdogSeverity.INFO
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""  # e.g., "EventBus", "ObservabilityHub", "WorkflowOrchestrator"
    component: str = ""  # Which component this observation relates to
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def to_learning_candidate(self) -> Dict[str, Any]:
        """Convert to a format suitable for LearningPipeline input."""
        from app.learning.models import LearningCandidate, LearningCandidateType
        return {
            "candidate_type": LearningCandidateType.WATCHDOG_OBSERVATION,
            "source_component": "Watchdog",
            "raw_observation": {
                "event_type": self.event_type.value,
                "severity": self.severity.value,
                "source": self.source,
                "component": self.component,
                "message": self.message,
                "details": self.details,
            },
            "context": {
                "watchdog_observation_id": self.id,
                "timestamp": self.timestamp,
            },
            "tags": self.tags + ["watchdog", self.event_type.value, self.severity.value],
        }


@dataclass
class AutonomyConfig:
    """Configuration for the AutonomyManager and its components."""
    # General settings
    enabled: bool = True
    
    # Watchdog settings
    watchdog_enabled: bool = True
    watchdog_event_subscriptions: List[str] = field(default_factory=lambda: [
        "task.*", "workflow.*", "health.*", "alert.*", "goal.*", "memory.*"
    ])
    
    # Self-initiated work settings
    self_initiated_enabled: bool = True
    self_initiated_check_interval_seconds: float = 300.0  # 5 minutes
    max_concurrent_autonomous_tasks: int = 3
    
    # Maintenance settings
    maintenance_enabled: bool = True
    maintenance_check_interval_seconds: float = 3600.0  # 1 hour
    
    # Background job integration
    use_background_job_service: bool = True
    
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AutonomousWorkItem:
    """Represents a unit of autonomous work to be executed via WorkflowOrchestrator."""
    id: str = field(default_factory=lambda: f"auto_work_{uuid4().hex[:8]}")
    source: str = ""  # "self_initiated" or "maintenance"
    description: str = ""
    workflow_spec: Dict[str, Any] = field(default_factory=dict)  # WorkflowSpec as dict
    priority: int = 2  # 1=low, 2=medium, 3=high
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scheduled_for: Optional[str] = None
    goal_id: Optional[str] = None  # Link to originating goal for self-initiated work
    maintenance_task_type: Optional[str] = None  # Link to maintenance task type
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, scheduled, running, completed, failed
    workflow_execution_id: Optional[str] = None


@dataclass
class GoalContext:
    """Context from GoalManager for autonomous work decisions."""
    goal_id: str
    name: str
    description: str
    status: str
    priority: str
    progress: float
    is_blocked: bool
    blocking_reasons: List[str]
    dependencies: List[Dict[str, Any]]
    duration_estimate: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str