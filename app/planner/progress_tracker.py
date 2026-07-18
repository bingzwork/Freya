"""Progress Tracker for monitoring task progress.

This module provides tracking and reporting of task progress,
including history, metrics, and visualization.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from app.planner.task import Task, TaskStatus


@dataclass
class ProgressSnapshot:
    """A snapshot of progress at a point in time."""
    timestamp: str
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    blocked_tasks: int
    overall_progress: float  # 0-100
    tasks_by_status: Dict[str, int] = field(default_factory=dict)
    tasks_by_priority: Dict[str, int] = field(default_factory=dict)
    tasks_by_category: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def create(cls, tasks: List[Task]) -> "ProgressSnapshot":
        """Create a snapshot from a list of tasks."""
        timestamp = datetime.now(timezone.utc).isoformat()
        total = len(tasks)

        status_counts: Dict[str, int] = defaultdict(int)
        priority_counts: Dict[str, int] = defaultdict(int)
        category_counts: Dict[str, int] = defaultdict(int)

        for task in tasks:
            status_counts[task.status.value] += 1
            priority_counts[task.priority.value] += 1
            category_counts[task.category.value] += 1

        completed = status_counts.get(TaskStatus.COMPLETED.value, 0)
        in_progress = status_counts.get(TaskStatus.IN_PROGRESS.value, 0)
        pending = status_counts.get(TaskStatus.PENDING.value, 0)
        blocked = status_counts.get(TaskStatus.BLOCKED.value, 0)

        overall_progress = (completed / total * 100) if total > 0 else 0

        return cls(
            timestamp=timestamp,
            total_tasks=total,
            completed_tasks=completed,
            in_progress_tasks=in_progress,
            pending_tasks=pending,
            blocked_tasks=blocked,
            overall_progress=overall_progress,
            tasks_by_status=dict(status_counts),
            tasks_by_priority=dict(priority_counts),
            tasks_by_category=dict(category_counts),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "in_progress_tasks": self.in_progress_tasks,
            "pending_tasks": self.pending_tasks,
            "blocked_tasks": self.blocked_tasks,
            "overall_progress": self.overall_progress,
            "tasks_by_status": self.tasks_by_status,
            "tasks_by_priority": self.tasks_by_priority,
            "tasks_by_category": self.tasks_by_category,
        }


class ProgressTracker:
    """Tracks progress of tasks over time.

    This class provides methods for tracking task completion,
    calculating metrics, and generating progress reports.
    """

    def __init__(self):
        """Initialize the progress tracker."""
        # Task ID -> Task
        self._tasks: Dict[str, Task] = {}

        # Timeline of snapshots
        self._snapshots: List[ProgressSnapshot] = []

        # Task completion history
        self._completion_history: List[Dict[str, Any]] = []

        # Start time
        self._start_time: Optional[str] = None

    def add_task(self, task: Task) -> None:
        """Add a task to the tracker."""
        self._tasks[task.id] = task
        if self._start_time is None:
            self._start_time = datetime.now(timezone.utc).isoformat()

    def update_task(self, task: Task) -> None:
        """Update a task in the tracker."""
        self._tasks[task.id] = task

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the tracker."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """Get all tracked tasks."""
        return list(self._tasks.values())

    def take_snapshot(self) -> ProgressSnapshot:
        """Take a snapshot of the current progress."""
        snapshot = ProgressSnapshot.create(list(self._tasks.values()))
        self._snapshots.append(snapshot)
        return snapshot

    def get_current_snapshot(self) -> ProgressSnapshot:
        """Get the most recent snapshot."""
        if self._snapshots:
            return self._snapshots[-1]
        return ProgressSnapshot.create(list(self._tasks.values()))

    def get_snapshots(self, count: Optional[int] = None) -> List[ProgressSnapshot]:
        """Get progress snapshots.

        Args:
            count: Maximum number of snapshots to return (most recent)
        """
        if count is None:
            return list(self._snapshots)
        return list(self._snapshots[-count:])

    def track_completion(self, task_id: str, end_time: Optional[str] = None) -> None:
        """Track task completion.

        Args:
            task_id: ID of the completed task
            end_time: Optional end time (ISO format)
        """
        task = self._tasks.get(task_id)
        if task:
            record = {
                "task_id": task_id,
                "title": task.title,
                "end_time": end_time or datetime.now(timezone.utc).isoformat(),
                "duration_seconds": task.actual_duration.total_seconds() if task.actual_duration else 0,
            }
            self._completion_history.append(record)

    def get_completion_history(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get task completion history."""
        if count is None:
            return list(self._completion_history)
        return list(self._completion_history[-count:])

    def get_overall_progress(self) -> float:
        """Get the overall progress percentage."""
        return self.get_current_snapshot().overall_progress

    def get_burndown_data(self) -> List[Dict[str, Any]]:
        """Get burndown chart data.

        Returns:
            List of data points with timestamp and remaining work.
        """
        data = []
        for snapshot in self._snapshots:
            remaining = snapshot.total_tasks - snapshot.completed_tasks
            data.append({
                "timestamp": snapshot.timestamp,
                "remaining": remaining,
                "completed": snapshot.completed_tasks,
            })
        return data

    def get_velocity(self) -> Dict[str, Any]:
        """Calculate the current velocity (rate of task completion).

        Returns:
            Dictionary with velocity metrics.
        """
        if len(self._completion_history) < 2:
            return {
                "tasks_per_hour": 0,
                "average_duration_hours": 0,
            }

        # Calculate tasks per hour
        first_completion = datetime.fromisoformat(self._completion_history[0]["end_time"])
        last_completion = datetime.fromisoformat(self._completion_history[-1]["end_time"])
        total_hours = (last_completion - first_completion).total_seconds() / 3600

        if total_hours <= 0:
            return {
                "tasks_per_hour": 0,
                "average_duration_hours": 0,
            }

        tasks_completed = len(self._completion_history)
        tasks_per_hour = tasks_completed / total_hours

        # Calculate average duration
        total_duration = sum(h["duration_seconds"] for h in self._completion_history)
        average_duration_hours = total_duration / 3600 / tasks_completed if tasks_completed > 0 else 0

        return {
            "tasks_per_hour": tasks_per_hour,
            "average_duration_hours": average_duration_hours,
        }

    def get_blocked_tasks(self) -> List[Task]:
        """Get all blocked tasks."""
        return [task for task in self._tasks.values() if task.status == TaskStatus.BLOCKED]

    def get_overdue_tasks(self) -> List[Task]:
        """Get all overdue tasks (past deadline)."""
        now = datetime.now(timezone.utc)
        overdue = []
        for task in self._tasks.values():
            if task.deadline:
                deadline = datetime.fromisoformat(task.deadline)
                if now > deadline and task.status != TaskStatus.COMPLETED:
                    overdue.append(task)
        return overdue

    def get_upcoming_deadlines(self, days_ahead: int = 7) -> List[Task]:
        """Get tasks with deadlines in the next N days."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        upcoming = []
        for task in self._tasks.values():
            if task.deadline:
                deadline = datetime.fromisoformat(task.deadline)
                if now <= deadline <= cutoff and task.status != TaskStatus.COMPLETED:
                    upcoming.append(task)
        return upcoming

    def get_progress_by_category(self) -> Dict[str, Dict[str, Any]]:
        """Get progress breakdown by category."""
        categories: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "completed": 0, "progress": 0.0}
        )

        for task in self._tasks.values():
            cat = task.category.value
            categories[cat]["total"] += 1
            if task.status == TaskStatus.COMPLETED:
                categories[cat]["completed"] += 1

        for cat, data in categories.items():
            data["progress"] = (data["completed"] / data["total"] * 100) if data["total"] > 0 else 0

        return dict(categories)

    def get_progress_by_priority(self) -> Dict[str, Dict[str, Any]]:
        """Get progress breakdown by priority."""
        priorities: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "completed": 0, "progress": 0.0}
        )

        for task in self._tasks.values():
            pri = task.priority.value
            priorities[pri]["total"] += 1
            if task.status == TaskStatus.COMPLETED:
                priorities[pri]["completed"] += 1

        for pri, data in priorities.items():
            data["progress"] = (data["completed"] / data["total"] * 100) if data["total"] > 0 else 0

        return dict(priorities)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current progress."""
        snapshot = self.get_current_snapshot()
        velocity = self.get_velocity()

        return {
            "total_tasks": snapshot.total_tasks,
            "completed_tasks": snapshot.completed_tasks,
            "in_progress_tasks": snapshot.in_progress_tasks,
            "pending_tasks": snapshot.pending_tasks,
            "blocked_tasks": snapshot.blocked_tasks,
            "overall_progress": snapshot.overall_progress,
            "velocity": velocity,
            "blocked_count": len(self.get_blocked_tasks()),
            "overdue_count": len(self.get_overdue_tasks()),
            "by_category": self.get_progress_by_category(),
            "by_priority": self.get_progress_by_priority(),
        }

    def get_estimated_remaining_time(self) -> Optional[timedelta]:
        """Estimate the remaining time to complete all tasks.

        Returns:
            Estimated remaining time, or None if not enough data.
        """
        snapshot = self.get_current_snapshot()
        pending = snapshot.total_tasks - snapshot.completed_tasks

        if pending <= 0:
            return timedelta(0)

        velocity = self.get_velocity()
        if velocity["tasks_per_hour"] <= 0:
            return None

        remaining_hours = pending / velocity["tasks_per_hour"]
        return timedelta(hours=remaining_hours)

    def clear(self) -> None:
        """Clear all tracked data."""
        self._tasks.clear()
        self._snapshots.clear()
        self._completion_history.clear()
        self._start_time = None
