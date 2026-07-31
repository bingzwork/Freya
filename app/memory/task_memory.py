"""Task Memory for Freya AI.

This module provides persistent storage for active task execution state.
It tracks the current task, completed/pending/blocked steps, dependencies,
and progress information to support interruption and resumption.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional


@dataclass
class TaskStep:
    """A single step within a task."""
    step_id: str
    description: str
    status: str = "pending"  # pending, in_progress, completed, blocked, failed
    dependencies: List[str] = field(default_factory=list)  # Step IDs this depends on
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskStep":
        return cls(**data)


@dataclass
class TaskState:
    """The complete state of a task for persistence and resumption."""
    task_id: str
    description: str
    status: str = "active"  # active, paused, completed, failed, cancelled
    steps: List[TaskStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    working_memory_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskState":
        # Convert step dicts to TaskStep objects
        if "steps" in data and data["steps"]:
            data["steps"] = [TaskStep.from_dict(s) if isinstance(s, dict) else s for s in data["steps"]]
        return cls(**data)

    def get_step(self, step_id: str) -> Optional[TaskStep]:
        """Get a step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_steps_by_status(self, status: str) -> List[TaskStep]:
        """Get all steps with a specific status."""
        return [s for s in self.steps if s.status == status]

    def get_next_pending_step(self) -> Optional[TaskStep]:
        """Get the next pending step that has all dependencies satisfied."""
        completed_ids = {s.step_id for s in self.steps if s.status == "completed"}
        for step in self.steps:
            if step.status == "pending":
                if all(dep in completed_ids for dep in step.dependencies):
                    return step
        return None

    def get_progress(self) -> Dict[str, Any]:
        """Get progress information."""
        total = len(self.steps)
        if total == 0:
            return {"total": 0, "completed": 0, "pending": 0, "blocked": 0, "failed": 0, "percentage": 0}

        completed = len([s for s in self.steps if s.status == "completed"])
        pending = len([s for s in self.steps if s.status == "pending"])
        in_progress = len([s for s in self.steps if s.status == "in_progress"])
        blocked = len([s for s in self.steps if s.status == "blocked"])
        failed = len([s for s in self.steps if s.status == "failed"])

        return {
            "total": total,
            "completed": completed,
            "pending": pending + in_progress,
            "blocked": blocked,
            "failed": failed,
            "percentage": (completed / total * 100) if total > 0 else 0
        }


class TaskMemory:
    """Persistent memory for active task execution state.

    Features:
    - Track current task with steps, dependencies, and progress
    - Automatic state updates during execution
    - Support for interruption and resumption
    - Prevents repeating completed work
    - Atomic JSON persistence
    - Thread-safe operations

    Example usage:
        task_memory = TaskMemory(workspace=".")

        # Start a new task
        task = task_memory.start_task(
            task_id="task_123",
            description="Implement user authentication",
            steps=[
                {"step_id": "s1", "description": "Create user model"},
                {"step_id": "s2", "description": "Create login endpoint", "dependencies": ["s1"]},
                {"step_id": "s3", "description": "Add JWT handling", "dependencies": ["s1"]},
            ]
        )

        # Mark step as in progress
        task_memory.update_step("s1", status="in_progress")

        # Complete step
        task_memory.update_step("s1", status="completed")

        # Resume later
        task = task_memory.resume_task("task_123")
        next_step = task.get_next_pending_step()  # Returns s2
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/task_memory.json",
        max_tasks: int = 100,
    ):
        """Initialize Task Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_tasks: Maximum number of tasks to keep in history
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_tasks = max_tasks
        self._lock = threading.RLock()
        self._tasks: Dict[str, TaskState] = {}
        self._active_task_id: Optional[str] = None
        self._sequence_counter = 0
        self._load()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_timestamp(self) -> str:
        """Generate a timestamp with timezone."""
        return datetime.now(timezone.utc).isoformat()

    def _save(self) -> None:
        """Save all tasks to storage (atomic write)."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "tasks": [t.to_dict() for t in self._tasks.values()],
                "active_task_id": self._active_task_id,
                "sequence_counter": self._sequence_counter,
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _load(self) -> None:
        """Load tasks from storage file."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._tasks = {}
            for task_data in data.get("tasks", []):
                task = TaskState.from_dict(task_data)
                self._tasks[task.task_id] = task

            self._active_task_id = data.get("active_task_id")
            self._sequence_counter = data.get("sequence_counter", 0)
        except Exception:
            self._tasks = {}
            self._active_task_id = None
            self._sequence_counter = 0

    def _enforce_limit(self) -> None:
        """Enforce max_tasks limit by removing oldest completed tasks."""
        if len(self._tasks) <= self.max_tasks:
            return

        # Sort by completed_at (or updated_at) and remove oldest completed
        sorted_tasks = sorted(
            self._tasks.items(),
            key=lambda x: x[1].completed_at or x[1].updated_at
        )
        to_remove = len(self._tasks) - self.max_tasks
        for task_id, _ in sorted_tasks[:to_remove]:
            # Only remove completed/failed/cancelled tasks
            task = self._tasks.get(task_id)
            if task and task.status in ("completed", "failed", "cancelled"):
                del self._tasks[task_id]

    def start_task(
        self,
        task_id: str,
        description: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        working_memory_snapshot: Optional[Dict[str, Any]] = None,
    ) -> TaskState:
        """Start a new task or resume an existing one.

        Args:
            task_id: Unique identifier for the task
            description: Human-readable task description
            steps: Optional list of step definitions (dicts with step_id, description, dependencies)
            metadata: Optional metadata for the task
            working_memory_snapshot: Optional snapshot of working memory state

        Returns:
            The created or resumed TaskState
        """
        with self._lock:
            if task_id in self._tasks:
                # Resume existing task
                task = self._tasks[task_id]
                task.status = "active"
                task.updated_at = self._generate_timestamp()
                self._active_task_id = task_id
                self._save()
                return task

            # Create new task
            task_steps = []
            if steps:
                for step_data in steps:
                    step = TaskStep(
                        step_id=step_data["step_id"],
                        description=step_data["description"],
                        dependencies=step_data.get("dependencies", []),
                        metadata=step_data.get("metadata", {}),
                    )
                    task_steps.append(step)

            task = TaskState(
                task_id=task_id,
                description=description,
                status="active",
                steps=task_steps,
                metadata=metadata or {},
                working_memory_snapshot=working_memory_snapshot or {},
            )

            self._tasks[task_id] = task
            self._active_task_id = task_id
            self._sequence_counter += 1
            self._enforce_limit()
            self._save()
            return task

    def get_task(self, task_id: str) -> Optional[TaskState]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_task(self) -> Optional[TaskState]:
        """Get the currently active task."""
        with self._lock:
            if self._active_task_id:
                return self._tasks.get(self._active_task_id)
            return None

    def resume_task(self, task_id: str) -> Optional[TaskState]:
        """Resume a task by setting it as active."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "active"
                task.updated_at = self._generate_timestamp()
                self._active_task_id = task_id
                self._save()
            return task

    def pause_task(self, task_id: str) -> bool:
        """Pause a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "paused"
                task.updated_at = self._generate_timestamp()
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._save()
                return True
            return False

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "completed"
                task.completed_at = self._generate_timestamp()
                task.updated_at = task.completed_at
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._save()
                return True
            return False

    def fail_task(self, task_id: str, error: str) -> bool:
        """Mark a task as failed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "failed"
                task.metadata["error"] = error
                task.completed_at = self._generate_timestamp()
                task.updated_at = task.completed_at
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._save()
                return True
            return False

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "cancelled"
                task.completed_at = self._generate_timestamp()
                task.updated_at = task.completed_at
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._save()
                return True
            return False

    def update_step(
        self,
        step_id: str,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update a step's status.

        Args:
            step_id: The step ID to update
            task_id: Task ID (uses active task if not specified)
            status: New status (pending, in_progress, completed, blocked, failed)
            error: Error message if failed
            metadata: Additional metadata to merge

        Returns:
            True if step was found and updated
        """
        with self._lock:
            target_task_id = task_id or self._active_task_id
            if not target_task_id:
                return False

            task = self._tasks.get(target_task_id)
            if not task:
                return False

            step = task.get_step(step_id)
            if not step:
                return False

            if status:
                step.status = status
                if status == "in_progress" and not step.started_at:
                    step.started_at = self._generate_timestamp()
                elif status == "completed":
                    step.completed_at = self._generate_timestamp()
                elif status == "failed":
                    step.completed_at = self._generate_timestamp()
                    step.error = error

            if error:
                step.error = error

            if metadata:
                step.metadata.update(metadata)

            task.updated_at = self._generate_timestamp()
            self._save()
            return True

    def add_step(
        self,
        step_id: str,
        description: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> bool:
        """Add a new step to a task."""
        with self._lock:
            target_task_id = task_id or self._active_task_id
            if not target_task_id:
                return False

            task = self._tasks.get(target_task_id)
            if not task:
                return False

            if task.get_step(step_id):
                return False  # Step already exists

            step = TaskStep(
                step_id=step_id,
                description=description,
                dependencies=dependencies or [],
                metadata=metadata or {},
            )
            task.steps.append(step)
            task.updated_at = self._generate_timestamp()
            self._save()
            return True

    def get_next_action(self, task_id: Optional[str] = None) -> Optional[TaskStep]:
        """Get the next step to execute for a task."""
        with self._lock:
            target_task_id = task_id or self._active_task_id
            if not target_task_id:
                return None

            task = self._tasks.get(target_task_id)
            if not task:
                return None

            return task.get_next_pending_step()

    def get_all_tasks(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[TaskState]:
        """Get all tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())
            if status:
                tasks = [t for t in tasks if t.status == status]
            # Sort by most recent first
            tasks.sort(key=lambda t: t.updated_at, reverse=True)
            if limit:
                tasks = tasks[:limit]
            return tasks

    def get_task_history(
        self,
        limit: int = 50,
        include_active: bool = True,
    ) -> List[TaskState]:
        """Get recent task history."""
        with self._lock:
            tasks = [t for t in self._tasks.values() if include_active or t.status != "active"]
            tasks.sort(key=lambda t: t.updated_at, reverse=True)
            return tasks[:limit]

    def delete_task(self, task_id: str) -> bool:
        """Delete a task permanently."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._save()
                return True
            return False

    def clear_completed(self, older_than_days: int = 30) -> int:
        """Remove completed tasks older than specified days."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        with self._lock:
            to_remove = []
            for task_id, task in self._tasks.items():
                if task.status in ("completed", "failed", "cancelled"):
                    try:
                        task_time = datetime.fromisoformat(task.completed_at or task.updated_at)
                        if task_time < cutoff:
                            to_remove.append(task_id)
                    except Exception:
                        pass

            for task_id in to_remove:
                del self._tasks[task_id]

            if to_remove:
                self._save()
            return len(to_remove)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about tasks."""
        with self._lock:
            status_counts: Dict[str, int] = {}
            total_steps = 0
            completed_steps = 0

            for task in self._tasks.values():
                status_counts[task.status] = status_counts.get(task.status, 0) + 1
                progress = task.get_progress()
                total_steps += progress["total"]
                completed_steps += progress["completed"]

            return {
                "total_tasks": len(self._tasks),
                "active_task_id": self._active_task_id,
                "status_counts": status_counts,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "completion_rate": completed_steps / total_steps if total_steps > 0 else 0,
            }

    def __len__(self) -> int:
        return len(self._tasks)

    def is_empty(self) -> bool:
        return len(self._tasks) == 0


def create_task_memory(
    workspace: str = ".",
    storage_path: Optional[str] = None,
    max_tasks: int = 100,
) -> TaskMemory:
    """Factory function to create TaskMemory with sensible defaults."""
    if storage_path is None:
        storage_path = "data/memory/task_memory.json"
    return TaskMemory(
        workspace=workspace,
        storage_path=storage_path,
        max_tasks=max_tasks,
    )