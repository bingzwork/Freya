"""Progress Tracker for monitoring task progress.

This module provides tracking and reporting of task progress,
including history, metrics, and visualization.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict

from app.planner.task import Task, TaskStatus

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub
from app.core.observability import HealthStatus, HealthResult


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
    # Track which task triggered this snapshot
    trigger_task_id: Optional[str] = None
    trigger_transition: Optional[str] = None
    # Replanning event data
    replanning_event: Optional[Dict[str, Any]] = None
    # Replanning event tracking (Phase 5)
    replanning_event: Optional[Dict[str, Any]] = None

    @classmethod
    def create(cls, tasks: List[Task], trigger_task_id: Optional[str] = None, trigger_transition: Optional[str] = None) -> "ProgressSnapshot":
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
            trigger_task_id=trigger_task_id,
            trigger_transition=trigger_transition,
        )

    @classmethod
    def create_replanning_snapshot(
        cls,
        tasks: List[Task],
        replanning_event: Dict[str, Any],
    ) -> "ProgressSnapshot":
        """Create a snapshot specifically for a replanning event."""
        snapshot = cls.create(tasks)
        snapshot.replanning_event = replanning_event
        return snapshot

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
            "trigger_task_id": self.trigger_task_id,
            "trigger_transition": self.trigger_transition,
            "replanning_event": self.replanning_event,
        }


class ProgressTracker:
    """Tracks progress of tasks over time.

    This class provides methods for tracking task completion,
    calculating metrics, and generating progress reports.
    Emits ProgressSnapshot objects on task state transitions.
    """

    def __init__(
        self,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize the progress tracker.

        Args:
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        # Task ID -> Task
        self._tasks: Dict[str, Task] = {}

        # Timeline of snapshots
        self._snapshots: List[ProgressSnapshot] = []

        # Task completion history
        self._completion_history: List[Dict[str, Any]] = []

        # Task state history (chronological)
        self._state_history: List[Dict[str, Any]] = []

        # Start time
        self._start_time: Optional[str] = None

        # Callbacks for progress notifications
        self._callbacks: List[Callable[[ProgressSnapshot], None]] = []

        # Track last known status for each task to detect transitions
        self._last_status: Dict[str, TaskStatus] = {}

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic snapshot
        self._schedule_periodic_snapshots()

    def _register_with_observability(self) -> None:
        """Register health check with observability hub."""
        if self._observability:
            from app.core.observability import HealthCheck, ComponentInfo, ComponentType
            self._observability.add_health_check(HealthCheck(
                name="progress_tracker_health",
                component="ProgressTracker",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="ProgressTracker",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Task progress tracking and metrics",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for ProgressTracker."""
        task_count = len(self._tasks)
        snapshot_count = len(self._snapshots)

        return HealthResult(
            name="progress_tracker_health",
            component="ProgressTracker",
            status=HealthStatus.HEALTHY,
            message=f"Tracking {task_count} tasks, {snapshot_count} snapshots",
            details={
                "task_count": task_count,
                "snapshot_count": snapshot_count,
                "completion_count": len(self._completion_history),
            }
        )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception as e:
            # Don't let event publishing break the tracker
            pass

    def _schedule_periodic_snapshots(self, interval_seconds: int = 60) -> None:
        """Schedule periodic progress snapshots."""
        # Guard against duplicate scheduling (e.g., in tests where multiple instances created)
        if self._job_service.get_job("progress_tracker_snapshot") is not None:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="progress_tracker_snapshot",
            func=self.take_snapshot,
            trigger=trigger,
            name="Progress Tracker Periodic Snapshot",
            priority=JobPriority.LOW,
        )

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

    def take_snapshot(self, trigger_task_id: Optional[str] = None, trigger_transition: Optional[str] = None) -> ProgressSnapshot:
        """Take a snapshot of the current progress."""
        snapshot = ProgressSnapshot.create(list(self._tasks.values()), trigger_task_id=trigger_task_id, trigger_transition=trigger_transition)
        self._snapshots.append(snapshot)
        self._notify_callbacks(snapshot)

        # Publish progress snapshot event
        self._publish_event("progress.snapshot", {
            "snapshot": snapshot.to_dict(),
            "trigger_task_id": trigger_task_id,
            "trigger_transition": trigger_transition,
        })

        return snapshot

    def get_current_snapshot(self) -> ProgressSnapshot:
        """Get the most recent snapshot."""
        if self._snapshots:
            return self._snapshots[-1]
        return ProgressSnapshot.create(list(self._tasks.values()), trigger_task_id=None, trigger_transition=None)

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
        self._state_history.clear()
        self._start_time = None
        self._last_status.clear()
        self._callbacks.clear()

    # Progress notification callbacks

    def add_callback(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        """Add a callback to be notified when a new snapshot is taken."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self, snapshot: ProgressSnapshot) -> None:
        """Notify all callbacks of a new snapshot."""
        for callback in self._callbacks:
            try:
                callback(snapshot)
            except Exception:
                # Don't let callback errors break the tracker
                pass

    # Task state transition handling

    def _detect_transition(self, task_id: str, new_status: TaskStatus) -> Optional[str]:
        """Detect and return the transition string if status changed."""
        old_status = self._last_status.get(task_id)
        if old_status is None:
            # First time seeing this task
            transition = f"PENDING → {new_status.value.upper()}"
            self._last_status[task_id] = new_status
            return transition
        elif old_status != new_status:
            transition = f"{old_status.value.upper()} → {new_status.value.upper()}"
            self._last_status[task_id] = new_status
            return transition
        return None

    def on_task_status_changed(self, task: Task, transition: Optional[str] = None) -> Optional[ProgressSnapshot]:
        """Called when a task's status changes. Takes a snapshot and records the transition.

        Args:
            task: The task whose status changed
            transition: Optional explicit transition string (e.g., "PENDING -> IN_PROGRESS")

        Returns:
            The ProgressSnapshot that was created, or None if no status change occurred
        """
        # Update the task in our tracking
        self._tasks[task.id] = task
        if self._start_time is None:
            self._start_time = datetime.now(timezone.utc).isoformat()

        # Detect transition if not provided
        if transition is None:
            transition = self._detect_transition(task.id, task.status)

        # If no transition (status unchanged), don't take a snapshot
        if transition is None:
            return None

        # Record state history
        state_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task.id,
            "task_title": task.title,
            "new_status": task.status.value,
            "transition": transition,
        }
        self._state_history.append(state_record)

        # Take a snapshot
        snapshot = self.take_snapshot(trigger_task_id=task.id, trigger_transition=transition)

        # If completed or failed, track completion
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            self.track_completion(task.id)

        # Publish task status change event
        self._publish_event("progress.task_status_changed", {
            "task_id": task.id,
            "task_title": task.title,
            "old_status": self._last_status.get(task.id, TaskStatus.PENDING).value if task.id in self._last_status else "UNKNOWN",
            "new_status": task.status.value,
            "transition": transition,
        })

        return snapshot

    def get_state_history(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get the chronological state transition history.

        Args:
            count: Maximum number of records to return (most recent)

        Returns:
            List of state transition records
        """
        if count is None:
            return list(self._state_history)
        return list(self._state_history[-count:])

    def get_snapshots(self, count: Optional[int] = None) -> List[ProgressSnapshot]:
        """Get progress snapshots.

        Args:
            count: Maximum number of snapshots to return (most recent)
        """
        if count is None:
            return list(self._snapshots)
        return list(self._snapshots[-count:])

    def get_progress_history_summary(self) -> Dict[str, Any]:
        """Get a summary of the progress history for external consumers (diagnostics, monitoring, backlog).

        Returns:
            Dictionary with progress summary suitable for diagnostics/monitoring/backlog
        """
        snapshots = self._snapshots
        if not snapshots:
            return {
                "total_snapshots": 0,
                "first_snapshot": None,
                "last_snapshot": None,
                "total_duration_seconds": 0,
                "state_transitions": len(self._state_history),
                "final_progress": 0,
            }

        first = snapshots[0]
        last = snapshots[-1]

        # Calculate total duration
        try:
            first_time = datetime.fromisoformat(first.timestamp)
            last_time = datetime.fromisoformat(last.timestamp)
            duration = (last_time - first_time).total_seconds()
        except Exception:
            duration = 0

        # Count unique transitions
        transitions = defaultdict(int)
        for record in self._state_history:
            if record.get("transition"):
                transitions[record["transition"]] += 1

        return {
            "total_snapshots": len(snapshots),
            "first_snapshot": first.to_dict(),
            "last_snapshot": last.to_dict(),
            "total_duration_seconds": duration,
            "state_transitions": len(self._state_history),
            "transitions_by_type": dict(transitions),
            "final_progress": last.overall_progress,
            "completed_tasks": last.completed_tasks,
            "total_tasks": last.total_tasks,
            "state_history": self._state_history[-50:],  # Last 50 records
        }

    # Export methods for diagnostics, monitoring, backlog

    def export_for_diagnostics(self) -> Dict[str, Any]:
        """Export progress data formatted for diagnostics consumption."""
        return {
            "source": "ProgressTracker",
            "type": "execution_progress",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_progress_history_summary(),
            "snapshots": [s.to_dict() for s in self._snapshots],
            "completion_history": self._completion_history,
        }

    def export_for_monitoring(self) -> Dict[str, Any]:
        """Export progress data formatted for monitoring consumption."""
        return {
            "source": "ProgressTracker",
            "type": "task_execution_metrics",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_progress_history_summary(),
            "velocity": self.get_velocity(),
            "burndown": self.get_burndown_data(),
            "current_tasks": [t.to_dict() for t in self._tasks.values()],
        }

    def export_for_backlog(self) -> Dict[str, Any]:
        """Export progress data formatted for backlog consumption."""
        completed_tasks = [t for t in self._tasks.values() if t.status == TaskStatus.COMPLETED]
        failed_tasks = [t for t in self._tasks.values() if t.status == TaskStatus.FAILED]
        blocked_tasks = [t for t in self._tasks.values() if t.status == TaskStatus.BLOCKED]

        return {
            "source": "ProgressTracker",
            "type": "execution_outcome",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_progress_history_summary(),
            "outcomes": {
                "completed": len(completed_tasks),
                "failed": len(failed_tasks),
                "blocked": len(blocked_tasks),
                "total": len(self._tasks),
            },
            "completed_task_details": [t.to_dict() for t in completed_tasks],
            "failed_task_details": [t.to_dict() for t in failed_tasks],
            "blocked_task_details": [t.to_dict() for t in blocked_tasks],
            "state_history": self._state_history,
        }
