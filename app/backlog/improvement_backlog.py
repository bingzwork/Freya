"""Improvement Backlog System.

This module provides a prioritized backlog for tracking improvements,
technical debt, and feature requests in the Freya AI system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
import json
from pathlib import Path
import uuid


class ImprovementPriority(Enum):
    """Priority levels for improvement items."""
    CRITICAL = "critical"  # Must be fixed immediately
    HIGH = "high"  # Should be addressed in the next iteration
    MEDIUM = "medium"  # Important but can wait
    LOW = "low"  # Nice to have
    BACKLOG = "backlog"  # For future consideration

    @property
    def weight(self) -> int:
        """Numeric weight for sorting (higher = more important)."""
        weights = {
            ImprovementPriority.CRITICAL: 100,
            ImprovementPriority.HIGH: 80,
            ImprovementPriority.MEDIUM: 50,
            ImprovementPriority.LOW: 20,
            ImprovementPriority.BACKLOG: 0,
        }
        return weights.get(self, 0)

    @property
    def color(self) -> str:
        """Color code for display."""
        colors = {
            ImprovementPriority.CRITICAL: "red",
            ImprovementPriority.HIGH: "orange",
            ImprovementPriority.MEDIUM: "yellow",
            ImprovementPriority.LOW: "light_blue",
            ImprovementPriority.BACKLOG: "gray",
        }
        return colors.get(self, "gray")


class ImprovementStatus(Enum):
    """Status of an improvement item."""
    PROPOSED = "proposed"  # Item has been suggested
    APPROVED = "approved"  # Item has been approved for implementation
    IN_PROGRESS = "in_progress"  # Someone is working on this
    BLOCKED = "blocked"  # Cannot be completed due to dependencies
    COMPLETED = "completed"  # Item has been completed
    REJECTED = "rejected"  # Item has been rejected
    DEFERRED = "deferred"  # Postponed to a later date


class ImprovementType(Enum):
    """Type of improvement item."""
    BUG_FIX = "bug_fix"  # Fix for a bug
    FEATURE = "feature"  # New feature
    ENHANCEMENT = "enhancement"  # Enhancement to existing feature
    REFACTORING = "refactoring"  # Code refactoring
    PERFORMANCE = "performance"  # Performance improvement
    SECURITY = "security"  # Security fix or improvement
    DOCUMENTATION = "documentation"  # Documentation improvement
    TESTING = "testing"  # Test-related improvement
    ARCHITECTURE = "architecture"  # Architectural change
    TECHNICAL_DEBT = "technical_debt"  # Technical debt reduction
    USABILITY = "usability"  # Usability improvement
    COMPLIANCE = "compliance"  # Compliance-related change


@dataclass
class ImprovementItem:
    """Represents a single item in the improvement backlog."""
    title: str
    description: str = ""
    item_id: str = field(default_factory=lambda: f"improvement_{uuid.uuid4().hex[:8]}")
    improvement_type: ImprovementType = ImprovementType.FEATURE
    priority: ImprovementPriority = ImprovementPriority.MEDIUM
    status: ImprovementStatus = ImprovementStatus.PROPOSED
    estimated_effort: Optional[float] = None  # In hours
    actual_effort: Optional[float] = None  # In hours
    complexity: str = "medium"  # low, medium, high
    impact: str = "medium"  # low, medium, high
    assignee: Optional[str] = None  # Who is assigned to this
    created_by: str = "system"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    due_date: Optional[str] = None  # ISO date string
    dependencies: List[str] = field(default_factory=list)  # IDs of dependent items
    blocked_by: List[str] = field(default_factory=list)  # IDs that block this item
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.improvement_type, str):
            self.improvement_type = ImprovementType(self.improvement_type)
        if isinstance(self.priority, str):
            self.priority = ImprovementPriority(self.priority)
        if isinstance(self.status, str):
            self.status = ImprovementStatus(self.status)

    @property
    def is_active(self) -> bool:
        """Check if the item is still active (not completed or rejected)."""
        return self.status in [
            ImprovementStatus.PROPOSED,
            ImprovementStatus.APPROVED,
            ImprovementStatus.IN_PROGRESS,
            ImprovementStatus.BLOCKED,
        ]

    @property
    def is_completed(self) -> bool:
        """Check if the item is completed."""
        return self.status == ImprovementStatus.COMPLETED

    @property
    def is_blocked(self) -> bool:
        """Check if the item is blocked."""
        return self.status == ImprovementStatus.BLOCKED or len(self.blocked_by) > 0

    @property
    def age_days(self) -> int:
        """Get the age of this item in days."""
        created = datetime.fromisoformat(self.created_at)
        now = datetime.now(timezone.utc)
        delta = now - created
        return delta.days

    @property
    def score(self) -> float:
        """Calculate a priority score for sorting.

        Higher score = higher priority.
        """
        # Base score from priority
        base = self.priority.weight

        # Adjust for impact
        impact_multiplier = {"high": 1.5, "medium": 1.0, "low": 0.5}.get(self.impact, 1.0)

        # Adjust for complexity (simpler = higher priority)
        complexity_multiplier = {"low": 1.2, "medium": 1.0, "high": 0.7}.get(self.complexity, 1.0)

        # Adjust for age (older items get slight priority boost)
        age_factor = 1.0 + (self.age_days * 0.001)

        # Adjust for status
        status_multiplier = {
            ImprovementStatus.COMPLETED: 0.0,
            ImprovementStatus.REJECTED: 0.0,
            ImprovementStatus.BLOCKED: 0.3,
            ImprovementStatus.IN_PROGRESS: 1.5,
            ImprovementStatus.APPROVED: 1.2,
            ImprovementStatus.PROPOSED: 1.0,
            ImprovementStatus.DEFERRED: 0.5,
        }.get(self.status, 1.0)

        return base * impact_multiplier * complexity_multiplier * age_factor * status_multiplier

    def update_status(self, status: ImprovementStatus) -> None:
        """Update the status of this item."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def assign(self, assignee: str) -> None:
        """Assign this item to someone."""
        self.assignee = assignee
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_dependency(self, item_id: str) -> None:
        """Add a dependency."""
        if item_id not in self.dependencies:
            self.dependencies.append(item_id)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_blocker(self, item_id: str) -> None:
        """Add a blocking item."""
        if item_id not in self.blocked_by:
            self.blocked_by.append(item_id)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_tag(self, tag: str) -> None:
        """Add a tag."""
        if tag not in self.tags:
            self.tags.append(tag)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "improvement_type": self.improvement_type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "estimated_effort": self.estimated_effort,
            "actual_effort": self.actual_effort,
            "complexity": self.complexity,
            "impact": self.impact,
            "assignee": self.assignee,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "due_date": self.due_date,
            "dependencies": self.dependencies,
            "blocked_by": self.blocked_by,
            "tags": self.tags,
            "metadata": self.metadata,
            "is_active": self.is_active,
            "is_completed": self.is_completed,
            "is_blocked": self.is_blocked,
            "age_days": self.age_days,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImprovementItem":
        """Create from dictionary."""
        return cls(
            item_id=data.get("item_id", f"improvement_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            improvement_type=data.get("improvement_type", "feature"),
            priority=data.get("priority", "medium"),
            status=data.get("status", "proposed"),
            estimated_effort=data.get("estimated_effort"),
            actual_effort=data.get("actual_effort"),
            complexity=data.get("complexity", "medium"),
            impact=data.get("impact", "medium"),
            assignee=data.get("assignee"),
            created_by=data.get("created_by", "system"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            due_date=data.get("due_date"),
            dependencies=data.get("dependencies", []),
            blocked_by=data.get("blocked_by", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    def __lt__(self, other: "ImprovementItem") -> bool:
        """Compare items by score (for sorting)."""
        return self.score > other.score


class ImprovementBacklog:
    """Manages a prioritized backlog of improvement items.

    Provides methods for adding, updating, querying, and tracking
    improvement items.
    """

    def __init__(self, workspace: Optional[str] = None):
        self._items: Dict[str, ImprovementItem] = {}
        self._workspace = Path(workspace) if workspace else Path(".")
        self._backlog_file = self._workspace / ".improvement_backlog.json"
        self._load_backlog()

    def _load_backlog(self) -> None:
        """Load backlog from disk."""
        if not self._backlog_file.exists():
            return
        try:
            with open(self._backlog_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._items = {}
                for item_data in data.get("items", []):
                    item = ImprovementItem.from_dict(item_data)
                    self._items[item.item_id] = item
        except Exception as e:
            print(f"Error loading improvement backlog: {e}")

    def _save_backlog(self) -> None:
        """Save backlog to disk."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        data = {
            "items": [item.to_dict() for item in self._items.values()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._backlog_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving improvement backlog: {e}")

    def add_item(
        self,
        title: str,
        description: str = "",
        improvement_type: ImprovementType = ImprovementType.FEATURE,
        priority: ImprovementPriority = ImprovementPriority.MEDIUM,
        status: ImprovementStatus = ImprovementStatus.PROPOSED,
        estimated_effort: Optional[float] = None,
        complexity: str = "medium",
        impact: str = "medium",
        assignee: Optional[str] = None,
        created_by: str = "system",
        due_date: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        blocked_by: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ImprovementItem:
        """Add a new improvement item to the backlog.

        Args:
            title: Title of the improvement
            description: Description of the improvement
            improvement_type: Type of improvement
            priority: Priority level
            status: Initial status
            estimated_effort: Estimated effort in hours
            complexity: Complexity level (low, medium, high)
            impact: Impact level (low, medium, high)
            assignee: Who is assigned to this
            created_by: Who created this item
            due_date: Due date (ISO format)
            dependencies: List of dependent item IDs
            blocked_by: List of blocking item IDs
            tags: List of tags
            metadata: Additional metadata

        Returns:
            The created ImprovementItem
        """
        item = ImprovementItem(
            title=title,
            description=description,
            improvement_type=improvement_type,
            priority=priority,
            status=status,
            estimated_effort=estimated_effort,
            complexity=complexity,
            impact=impact,
            assignee=assignee,
            created_by=created_by,
            due_date=due_date,
            dependencies=dependencies or [],
            blocked_by=blocked_by or [],
            tags=tags or [],
            metadata=metadata or {},
        )
        self._items[item.item_id] = item
        self._save_backlog()
        return item

    def update_item(self, item_id: str, **kwargs) -> bool:
        """Update an existing improvement item.

        Args:
            item_id: The ID of the item to update
            **kwargs: Fields to update

        Returns:
            True if the item was found and updated, False otherwise
        """
        item = self._items.get(item_id)
        if not item:
            return False

        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_backlog()
        return True

    def get_item(self, item_id: str) -> Optional[ImprovementItem]:
        """Get an improvement item by ID.

        Args:
            item_id: The ID of the item

        Returns:
            The ImprovementItem if found, None otherwise
        """
        return self._items.get(item_id)

    def remove_item(self, item_id: str) -> bool:
        """Remove an improvement item from the backlog.

        Args:
            item_id: The ID of the item to remove

        Returns:
            True if the item was found and removed, False otherwise
        """
        if item_id in self._items:
            del self._items[item_id]
            self._save_backlog()
            return True
        return False

    def list_items(
        self,
        status: Optional[ImprovementStatus] = None,
        priority: Optional[ImprovementPriority] = None,
        improvement_type: Optional[ImprovementType] = None,
        assignee: Optional[str] = None,
        tags: Optional[List[str]] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ImprovementItem]:
        """List improvement items with optional filters.

        Args:
            status: Filter by status
            priority: Filter by priority
            improvement_type: Filter by type
            assignee: Filter by assignee
            tags: Filter by tags (items must have at least one of these tags)
            search: Search in title and description
            limit: Maximum number of items to return

        Returns:
            List of matching ImprovementItem objects
        """
        items = list(self._items.values())

        if status:
            items = [i for i in items if i.status == status]
        if priority:
            items = [i for i in items if i.priority == priority]
        if improvement_type:
            items = [i for i in items if i.improvement_type == improvement_type]
        if assignee:
            items = [i for i in items if i.assignee == assignee]
        if tags:
            items = [i for i in items if any(t in i.tags for t in tags)]
        if search:
            search_lower = search.lower()
            items = [
                i
                for i in items
                if search_lower in i.title.lower() or search_lower in i.description.lower()
            ]

        # Sort by score (highest first)
        items.sort(reverse=True)

        if limit:
            items = items[:limit]

        return items

    def list_active(self) -> List[ImprovementItem]:
        """List all active (non-completed, non-rejected) items.

        Returns:
            List of active ImprovementItem objects
        """
        return [i for i in self._items.values() if i.is_active]

    def list_by_priority(self) -> List[ImprovementItem]:
        """List items sorted by priority.

        Returns:
            List of items sorted by priority (highest first)
        """
        items = list(self._items.values())
        items.sort(reverse=True)
        return items

    def list_completed(self) -> List[ImprovementItem]:
        """List all completed items.

        Returns:
            List of completed ImprovementItem objects
        """
        return self.list_items(status=ImprovementStatus.COMPLETED)

    def list_blocked(self) -> List[ImprovementItem]:
        """List all blocked items.

        Returns:
            List of blocked ImprovementItem objects
        """
        return self.list_items(status=ImprovementStatus.BLOCKED)

    def list_by_assignee(self, assignee: str) -> List[ImprovementItem]:
        """List items assigned to a specific person.

        Args:
            assignee: The name of the assignee

        Returns:
            List of items assigned to that person
        """
        return self.list_items(assignee=assignee)

    def list_by_type(self, improvement_type: ImprovementType) -> List[ImprovementItem]:
        """List items by type.

        Args:
            improvement_type: The type of improvement

        Returns:
            List of items of that type
        """
        return self.list_items(improvement_type=improvement_type)

    def get_next_item(self) -> Optional[ImprovementItem]:
        """Get the next item to work on (highest priority, not in progress).

        Returns:
            The next ImprovementItem to work on, or None if none available
        """
        # Get all active items sorted by score
        active_items = self.list_active()

        # Filter out already in-progress items and return the highest priority one
        for item in active_items:
            if item.status != ImprovementStatus.IN_PROGRESS:
                return item
        return None

    def get_high_priority_items(self, limit: int = 10) -> List[ImprovementItem]:
        """Get high priority items.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of high priority items
        """
        return self.list_items(
            priority=ImprovementPriority.HIGH,
            limit=limit,
        )

    def get_critical_items(self) -> List[ImprovementItem]:
        """Get all critical priority items.

        Returns:
            List of critical items
        """
        return self.list_items(priority=ImprovementPriority.CRITICAL)

    def get_overdue_items(self) -> List[ImprovementItem]:
        """Get items that are past their due date.

        Returns:
            List of overdue items
        """
        now = datetime.now(timezone.utc).isoformat()
        items = []
        for item in self._items.values():
            if item.due_date and item.due_date < now and item.is_active:
                items.append(item)
        items.sort(reverse=True)
        return items

    @property
    def count(self) -> int:
        """Get the total number of items."""
        return len(self._items)

    @property
    def active_count(self) -> int:
        """Get the number of active items."""
        return len([i for i in self._items.values() if i.is_active])

    @property
    def completed_count(self) -> int:
        """Get the number of completed items."""
        return len([i for i in self._items.values() if i.is_completed])

    @property
    def blocked_count(self) -> int:
        """Get the number of blocked items."""
        return len([i for i in self._items.values() if i.is_blocked])

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the backlog.

        Returns:
            Summary dictionary with statistics
        """
        # Count by status
        by_status: Dict[str, int] = {}
        for item in self._items.values():
            status_key = item.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

        # Count by priority
        by_priority: Dict[str, int] = {}
        for item in self._items.values():
            priority_key = item.priority.value
            by_priority[priority_key] = by_priority.get(priority_key, 0) + 1

        # Count by type
        by_type: Dict[str, int] = {}
        for item in self._items.values():
            type_key = item.improvement_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

        # Total estimated effort
        total_effort = sum(
            i.estimated_effort or 0 for i in self._items.values() if i.is_active
        )

        return {
            "total_items": self.count,
            "active_items": self.active_count,
            "completed_items": self.completed_count,
            "blocked_items": self.blocked_count,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_type": by_type,
            "total_estimated_effort_hours": total_effort,
        }

    def get_distribution(self) -> Dict[str, Any]:
        """Get the distribution of items by various criteria.

        Returns:
            Distribution dictionary
        """
        summary = self.get_summary()
        return {
            "by_status": summary["by_status"],
            "by_priority": summary["by_priority"],
            "by_type": summary["by_type"],
        }

    def clear(self) -> None:
        """Clear all items from the backlog."""
        self._items = {}
        try:
            self._backlog_file.unlink()
        except FileNotFoundError:
            pass

    def export_to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary."""
        return {
            "items": [item.to_dict() for item in self._items.values()],
            "summary": self.get_summary(),
        }

    def import_from_dict(self, data: Dict[str, Any]) -> None:
        """Import data from a dictionary."""
        self._items = {}
        for item_data in data.get("items", []):
            item = ImprovementItem.from_dict(item_data)
            self._items[item.item_id] = item
        self._save_backlog()
