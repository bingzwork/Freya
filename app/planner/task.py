"""Task representation for the Planner System.

This module defines the data structures for representing tasks and their properties.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Set


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority levels for tasks."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def score(self) -> int:
        """Get numeric priority score (higher is more urgent)."""
        scores = {
            TaskPriority.CRITICAL: 4,
            TaskPriority.HIGH: 3,
            TaskPriority.MEDIUM: 2,
            TaskPriority.LOW: 1,
        }
        return scores.get(self, 0)


class TaskCategory(Enum):
    """Categories of tasks."""
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    REVIEW = "review"
    REFACTORING = "refactoring"
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    MAINTENANCE = "maintenance"
    RESEARCH = "research"
    OTHER = "other"


@dataclass
class Task:
    """Represents a task in the planning system."""
    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    category: TaskCategory = TaskCategory.IMPLEMENTATION

    # Time estimation
    estimated_duration: Optional[timedelta] = None
    estimated_hours: float = 0.0

    # Actual tracking
    actual_duration: Optional[timedelta] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    # Dependencies
    dependencies: List[str] = field(default_factory=list)  # Task IDs
    dependents: List[str] = field(default_factory=list)  # Task IDs that depend on this

    # Resource requirements
    required_resources: List[str] = field(default_factory=list)
    assignee: Optional[str] = None

    # Tags and metadata
    tags: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)

    # Time constraints
    deadline: Optional[str] = None
    start_after: Optional[str] = None

    # Progress
    progress_percent: float = 0.0

    # Creation and modification timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Custom fields
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.priority, str):
            self.priority = TaskPriority(self.priority)
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)
        if isinstance(self.category, str):
            self.category = TaskCategory(self.category)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create task from dictionary."""
        # Convert estimated_hours to timedelta if provided
        estimated_duration = None
        if data.get("estimated_hours"):
            estimated_duration = timedelta(hours=data["estimated_hours"])

        actual_duration = None
        if data.get("actual_hours"):
            actual_duration = timedelta(hours=data["actual_hours"])

        return cls(
            id=data.get("id", f"task_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", TaskStatus.PENDING.value),
            priority=data.get("priority", TaskPriority.MEDIUM.value),
            category=data.get("category", TaskCategory.IMPLEMENTATION.value),
            estimated_duration=estimated_duration,
            estimated_hours=data.get("estimated_hours", 0.0),
            actual_duration=actual_duration,
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            dependencies=data.get("dependencies", []),
            dependents=data.get("dependents", []),
            required_resources=data.get("required_resources", []),
            assignee=data.get("assignee"),
            tags=data.get("tags", []),
            labels=data.get("labels", {}),
            deadline=data.get("deadline"),
            start_after=data.get("start_after"),
            progress_percent=data.get("progress_percent", 0.0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "category": self.category.value,
            "estimated_hours": self.estimated_hours,
            "actual_hours": self.actual_duration.total_seconds() / 3600 if self.actual_duration else 0,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "required_resources": self.required_resources,
            "assignee": self.assignee,
            "tags": self.tags,
            "labels": self.labels,
            "deadline": self.deadline,
            "start_after": self.start_after,
            "progress_percent": self.progress_percent,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    def set_estimated_hours(self, hours: float) -> None:
        """Set the estimated hours for the task."""
        self.estimated_hours = hours
        self.estimated_duration = timedelta(hours=hours)
        self._update_timestamp()

    def set_start_time(self, time_str: Optional[str] = None) -> None:
        """Set the start time for the task."""
        if time_str is None:
            time_str = datetime.now(timezone.utc).isoformat()
        self.start_time = time_str
        self.status = TaskStatus.IN_PROGRESS
        self._update_timestamp()

    def set_end_time(self, time_str: Optional[str] = None) -> None:
        """Set the end time for the task."""
        if time_str is None:
            time_str = datetime.now(timezone.utc).isoformat()
        self.end_time = time_str

        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.actual_duration = end - start

        self.status = TaskStatus.COMPLETED
        self.progress_percent = 100.0
        self._update_timestamp()

    def set_progress(self, percent: float) -> None:
        """Set the progress percentage."""
        self.progress_percent = max(0, min(100, percent))
        self._update_timestamp()

    def add_dependency(self, task_id: str) -> None:
        """Add a dependency to this task."""
        if task_id not in self.dependencies:
            self.dependencies.append(task_id)
        self._update_timestamp()

    def remove_dependency(self, task_id: str) -> None:
        """Remove a dependency from this task."""
        if task_id in self.dependencies:
            self.dependencies.remove(task_id)
        self._update_timestamp()

    def add_dependent(self, task_id: str) -> None:
        """Add a dependent task."""
        if task_id not in self.dependents:
            self.dependents.append(task_id)
        self._update_timestamp()

    def require_resource(self, resource_id: str) -> None:
        """Add a required resource."""
        if resource_id not in self.required_resources:
            self.required_resources.append(resource_id)
        self._update_timestamp()

    def _update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_ready(self) -> None:
        """Mark the task as ready to start."""
        self.status = TaskStatus.READY
        self._update_timestamp()

    def mark_in_progress(self) -> None:
        """Mark the task as in progress."""
        if self.start_time is None:
            self.set_start_time()
        self.status = TaskStatus.IN_PROGRESS
        self._update_timestamp()

    def mark_blocked(self, reason: str = "") -> None:
        """Mark the task as blocked."""
        self.status = TaskStatus.BLOCKED
        self.metadata["blocked_reason"] = reason
        self._update_timestamp()

    def mark_completed(self) -> None:
        """Mark the task as completed."""
        self.set_end_time()
        self.status = TaskStatus.COMPLETED
        self.progress_percent = 100.0
        self._update_timestamp()

    def mark_failed(self, reason: str = "") -> None:
        """Mark the task as failed."""
        self.end_time = datetime.now(timezone.utc).isoformat()
        self.status = TaskStatus.FAILED
        self.metadata["failure_reason"] = reason
        self._update_timestamp()

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark the task as cancelled."""
        self.status = TaskStatus.CANCELLED
        self.metadata["cancel_reason"] = reason
        self._update_timestamp()

    @property
    def is_complete(self) -> bool:
        """Check if the task is complete."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED)

    @property
    def is_active(self) -> bool:
        """Check if the task is actively being worked on."""
        return self.status in (TaskStatus.IN_PROGRESS, TaskStatus.READY)

    @property
    def can_start(self) -> bool:
        """Check if the task can be started (all dependencies are complete)."""
        # This would need to be checked against the actual state of dependencies
        # For now, just check status
        return self.status in (TaskStatus.PENDING, TaskStatus.READY)

    def __lt__(self, other: "Task") -> bool:
        """Compare tasks by priority (higher priority first)."""
        return self.priority.score > other.priority.score

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return False
        return self.id == other.id
