"""Plan Manager for managing project plans.

This module provides high-level management of project plans,
including creation, modification, saving, and loading plans.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.planner.task import Task, TaskStatus, TaskPriority, TaskCategory
from app.planner.task_graph import TaskGraph, CycleDetectedError
from app.planner.scheduler import Scheduler, Schedule, SchedulingStrategy
from app.planner.resource_allocator import ResourceAllocator, Resource, ResourceType
from app.planner.progress_tracker import ProgressTracker


@dataclass
class PlanConfig:
    """Configuration for a plan."""
    name: str = "Unnamed Plan"
    description: str = ""
    scheduling_strategy: SchedulingStrategy = SchedulingStrategy.ASAP
    default_priority: TaskPriority = TaskPriority.MEDIUM
    default_category: TaskCategory = TaskCategory.IMPLEMENTATION
    default_estimated_hours: float = 2.0
    auto_schedule: bool = True
    track_progress: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scheduling_strategy": self.scheduling_strategy.value,
            "default_priority": self.default_priority.value,
            "default_category": self.default_category.value,
            "default_estimated_hours": self.default_estimated_hours,
            "auto_schedule": self.auto_schedule,
            "track_progress": self.track_progress,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanConfig":
        return cls(
            name=data.get("name", "Unnamed Plan"),
            description=data.get("description", ""),
            scheduling_strategy=SchedulingStrategy(data.get("scheduling_strategy", "asap")),
            default_priority=TaskPriority(data.get("default_priority", "medium")),
            default_category=TaskCategory(data.get("default_category", "implementation")),
            default_estimated_hours=data.get("default_estimated_hours", 2.0),
            auto_schedule=data.get("auto_schedule", True),
            track_progress=data.get("track_progress", True),
        )


@dataclass
class Plan:
    """Represents a project plan."""
    id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    config: PlanConfig = field(default_factory=PlanConfig)
    tasks: List[Task] = field(default_factory=list)
    resources: List[Resource] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "draft"  # draft, active, completed, archived

    # Internal state
    _graph: Optional[TaskGraph] = field(default=None, repr=False)
    _scheduler: Optional[Scheduler] = field(default=None, repr=False)
    _allocator: Optional[ResourceAllocator] = field(default=None, repr=False)
    _tracker: Optional[ProgressTracker] = field(default=None, repr=False)

    def __post_init__(self):
        # Initialize internal components
        self._graph = TaskGraph()
        for task in self.tasks:
            self._graph.add_task(task)

        self._scheduler = Scheduler(self._graph, self.config.scheduling_strategy)
        self._allocator = ResourceAllocator()
        for resource in self.resources:
            self._allocator.add_resource(resource)

        self._tracker = ProgressTracker()
        for task in self.tasks:
            self._tracker.add_task(task)

    def to_dict(self) -> Dict[str, Any]:
        """Convert plan to dictionary."""
        return {
            "id": self.id,
            "config": self.config.to_dict(),
            "tasks": [t.to_dict() for t in self.tasks],
            "resources": [r.to_dict() for r in self.resources],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create plan from dictionary."""
        config = PlanConfig.from_dict(data.get("config", {}))
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        resources = [Resource.from_dict(r) for r in data.get("resources", [])]

        plan = cls(
            id=data.get("id", f"plan_{uuid.uuid4().hex[:8]}"),
            config=config,
            tasks=tasks,
            resources=resources,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            status=data.get("status", "draft"),
        )
        return plan

    def _update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def validate_graph(self) -> None:
        """Validate the task graph for cycles.

        Raises:
            CycleDetectedError: If the graph contains a cycle.
        """
        if self._graph:
            self._graph.topological_sort()  # Raises CycleDetectedError if cyclic

    def get_task_graph(self) -> Optional[TaskGraph]:
        """Get the task graph for this plan."""
        return self._graph

    # Phase 5: Adaptive Replanning methods

    def get_completed_task_ids(self) -> List[str]:
        """Get IDs of all completed tasks (to preserve during replanning)."""
        return [task.id for task in self.tasks if task.status == TaskStatus.COMPLETED]

    def get_pending_or_failed_task_ids(self) -> List[str]:
        """Get IDs of tasks that are not completed (pending, in_progress, failed, blocked)."""
        return [task.id for task in self.tasks if task.status != TaskStatus.COMPLETED]

    def invalidate_from_failure(self, failed_task_id: str) -> List[str]:
        """Invalidate a failed task and its dependents for replanning.

        Marks the failed task and all downstream dependents as PENDING,
        while preserving COMPLETED tasks outside the affected subgraph.

        Args:
            failed_task_id: ID of the task that failed

        Returns:
            List of task IDs that were invalidated (marked PENDING)
        """
        if not self._graph:
            return []

        invalidated = self._graph.invalidate_subgraph(failed_task_id)

        # Sync the plan's task list with the graph
        for task_id in invalidated:
            for task in self.tasks:
                if task.id == task_id:
                    task.status = TaskStatus.PENDING
                    task.progress_percent = 0.0
                    task.start_time = None
                    task.end_time = None
                    task.actual_duration = None
                    break

        # Update tracker
        if self._tracker:
            for task_id in invalidated:
                task = self._graph.get_task(task_id)
                if task:
                    self._tracker.update_task(task)

        self._update_timestamp()
        return invalidated

    def add_replacement_tasks(self, new_task_titles: List[str], anchor_task_id: Optional[str] = None,
                              priority: Optional[TaskPriority] = None,
                              category: Optional[TaskCategory] = None,
                              estimated_hours: Optional[float] = None) -> List[str]:
        """Add new tasks to replace an invalidated subgraph.

        Args:
            new_task_titles: List of titles for new tasks
            anchor_task_id: Optional task ID that new tasks should depend on (the task before the invalidated section)
            priority: Task priority (uses plan default if not specified)
            category: Task category (uses plan default if not specified)
            estimated_hours: Estimated hours (uses plan default if not specified)

        Returns:
            List of new task IDs added
        """
        if not self._graph:
            return []

        config = self.config
        priority = priority or config.default_priority
        category = category or config.default_category
        estimated_hours = estimated_hours or config.default_estimated_hours

        # Create new Task objects
        new_tasks = []
        for title in new_task_titles:
            task = Task(
                title=title,
                description="",
                priority=priority,
                category=category,
                estimated_hours=estimated_hours,
            )
            new_tasks.append(task)
            self.tasks.append(task)

        # Add to graph with dependencies
        added_ids = self._graph.add_tasks_with_dependencies(new_tasks, anchor_task_id)

        # Add to tracker
        if self._tracker:
            for task in new_tasks:
                self._tracker.add_task(task)

        # Rebuild schedule if auto_schedule is enabled
        if self.config.auto_schedule:
            self._rebuild_schedule()

        self._update_timestamp()
        return added_ids

    def replan_after_failure(self, failed_task_id: str, new_steps: List[str],
                             anchor_task_id: Optional[str] = None) -> Dict[str, Any]:
        """Perform adaptive replanning after a task failure.

        This is the main entry point for adaptive replanning:
        1. Invalidate the failed task and its dependents
        2. Add new replacement tasks
        3. Emit a replanning progress snapshot

        Args:
            failed_task_id: ID of the task that failed
            new_steps: List of new step descriptions to replace the failed portion
            anchor_task_id: Optional task ID to anchor new tasks after (defaults to task before failed task)

        Returns:
            Dictionary with replanning results
        """
        # 1. Invalidate the affected subgraph
        invalidated = self.invalidate_from_failure(failed_task_id)

        # 2. Determine anchor task (the last completed task before the failed one)
        if anchor_task_id is None:
            # Find the task that the failed task depended on (if any)
            failed_task = self._graph.get_task(failed_task_id)
            if failed_task and failed_task.dependencies:
                # Use the first dependency as anchor
                anchor_task_id = failed_task.dependencies[0]

        # 3. Add replacement tasks
        added_ids = self.add_replacement_tasks(new_steps, anchor_task_id)

        # 4. Emit replanning progress snapshot
        replanning_event = {
            "type": "replanning",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failed_task_id": failed_task_id,
            "invalidated_task_ids": invalidated,
            "added_task_ids": added_ids,
            "anchor_task_id": anchor_task_id,
            "new_steps": new_steps,
        }

        if self._tracker:
            snapshot = ProgressSnapshot.create_replanning_snapshot(
                list(self._graph.get_all_tasks()),
                replanning_event
            )
            self._tracker._snapshots.append(snapshot)
            self._tracker._notify_callbacks(snapshot)

        self._update_timestamp()
        return {
            "invalidated": invalidated,
            "added": added_ids,
            "replanning_event": replanning_event,
        }

    def _rebuild_schedule(self) -> Optional[Schedule]:
        """Rebuild the schedule for the active plan."""
        if not self._graph:
            return None

        # Rebuild the graph from tasks
        self._graph = TaskGraph()
        for task in self.tasks:
            self._graph.add_task(task)

        # Re-add dependencies from task.dependencies field
        for task in self.tasks:
            for dep_id in task.dependencies:
                try:
                    self._graph.add_dependency(dep_id, task.id)
                except CycleDetectedError:
                    # Log warning but continue - graph should already be validated
                    pass

        # Rebuild the scheduler
        self._scheduler = Scheduler(
            self._graph,
            self.config.scheduling_strategy
        )

        return self._scheduler.schedule()


class PlanManager:
    """Manages project plans.

    This class provides high-level operations for creating, managing,
    and executing project plans.
    """

    def __init__(self, workspace: str = "."):
        """Initialize the plan manager.

        Args:
            workspace: The project workspace directory.
        """
        self.workspace = Path(workspace).resolve()
        self.plans_dir = self.workspace / ".plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)

        # Loaded plans: plan_id -> Plan
        self._plans: Dict[str, Plan] = {}

        # Active plan
        self._active_plan: Optional[Plan] = None

        # Load existing plans
        self._load_plans()

    def create_plan(self, name: str, description: str = "") -> Plan:
        """Create a new plan.

        Args:
            name: Name of the plan
            description: Description of the plan

        Returns:
            The newly created plan
        """
        config = PlanConfig(name=name, description=description)
        plan = Plan(config=config)
        self._plans[plan.id] = plan
        self._active_plan = plan
        self._save_plan(plan)
        return plan

    def load_plan(self, plan_id: str) -> Optional[Plan]:
        """Load a plan by ID.

        Args:
            plan_id: ID of the plan to load

        Returns:
            The loaded plan, or None if not found
        """
        return self._plans.get(plan_id)

    def get_active_plan(self) -> Optional[Plan]:
        """Get the currently active plan."""
        return self._active_plan

    def set_active_plan(self, plan_id: str) -> bool:
        """Set the active plan.

        Args:
            plan_id: ID of the plan to activate

        Returns:
            True if plan was found and set as active
        """
        if plan_id in self._plans:
            self._active_plan = self._plans[plan_id]
            return True
        return False

    def list_plans(self) -> List[Plan]:
        """List all loaded plans."""
        return list(self._plans.values())

    def delete_plan(self, plan_id: str) -> bool:
        """Delete a plan.

        Args:
            plan_id: ID of the plan to delete

        Returns:
            True if plan was deleted
        """
        if plan_id in self._plans:
            del self._plans[plan_id]
            if self._active_plan and self._active_plan.id == plan_id:
                self._active_plan = None

            # Delete from disk
            plan_file = self.plans_dir / f"{plan_id}.json"
            if plan_file.exists():
                plan_file.unlink()

            return True
        return False

    def _load_plans(self) -> None:
        """Load plans from disk."""
        for plan_file in self.plans_dir.glob("*.json"):
            try:
                with open(plan_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                plan = Plan.from_dict(data)
                self._plans[plan.id] = plan
                # Set the first plan as active by default
                if self._active_plan is None:
                    self._active_plan = plan
            except Exception as e:
                print(f"Error loading plan {plan_file}: {e}")

    def _save_plan(self, plan: Plan) -> None:
        """Save a plan to disk."""
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plan_file = self.plans_dir / f"{plan.id}.json"
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, indent=2, ensure_ascii=False)

    def save_plan(self, plan: Plan) -> None:
        """Save a plan to disk.

        Args:
            plan: The plan to save
        """
        plan._update_timestamp()
        self._save_plan(plan)

    def save_all(self) -> None:
        """Save all plans to disk."""
        for plan in self._plans.values():
            self.save_plan(plan)

    # Task operations

    def add_task(
        self,
        title: str,
        description: str = "",
        priority: Optional[TaskPriority] = None,
        category: Optional[TaskCategory] = None,
        estimated_hours: Optional[float] = None,
        dependencies: Optional[List[str]] = None,
        **kwargs,
    ) -> Optional[Task]:
        """Add a task to the active plan.

        Args:
            title: Task title
            description: Task description
            priority: Task priority (uses plan default if not specified)
            category: Task category (uses plan default if not specified)
            estimated_hours: Estimated hours (uses plan default if not specified)
            dependencies: List of task IDs this task depends on
            **kwargs: Additional task metadata

        Returns:
            The created task, or None if no active plan
        """
        if not self._active_plan:
            return None

        config = self._active_plan.config

        task = Task(
            title=title,
            description=description,
            priority=priority or config.default_priority,
            category=category or config.default_category,
            estimated_hours=estimated_hours or config.default_estimated_hours,
            dependencies=dependencies or [],
            metadata=kwargs,
        )

        self._active_plan.tasks.append(task)
        self._active_plan._graph.add_task(task)
        self._active_plan._tracker.add_task(task)

        if self._active_plan.config.auto_schedule:
            self._rebuild_schedule()

        self._active_plan._update_timestamp()
        self.save_plan(self._active_plan)

        return task

    def get_task(self, plan_id: str, task_id: str) -> Optional[Task]:
        """Get a task from a plan.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task

        Returns:
            The task, or None if not found
        """
        plan = self._plans.get(plan_id)
        if plan:
            for task in plan.tasks:
                if task.id == task_id:
                    return task
        return None

    def update_task(
        self,
        plan_id: str,
        task_id: str,
        **kwargs,
    ) -> bool:
        """Update a task in a plan.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task
            **kwargs: Task attributes to update

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)

        # Update the graph and tracker
        plan._graph.add_task(task)
        plan._tracker.update_task(task)

        if plan.config.auto_schedule:
            self._rebuild_schedule()

        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def delete_task(self, plan_id: str, task_id: str) -> bool:
        """Delete a task from a plan.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task

        Returns:
            True if task was deleted
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        task_index = -1
        for i, t in enumerate(plan.tasks):
            if t.id == task_id:
                task = t
                task_index = i
                break

        if not task:
            return False

        # Remove from tasks list
        plan.tasks.pop(task_index)

        # Remove from graph and tracker
        plan._graph.remove_task(task_id)
        plan._tracker.remove_task(task_id)

        if plan.config.auto_schedule:
            self._rebuild_schedule()

        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def add_dependency(self, plan_id: str, from_task_id: str, to_task_id: str) -> bool:
        """Add a dependency between tasks in a plan.

        Args:
            plan_id: ID of the plan
            from_task_id: Task that must be completed first
            to_task_id: Task that depends on from_task_id

        Returns:
            True if dependency was added

        Raises:
            CycleDetectedError: If adding the dependency would create a cycle
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        result = plan._graph.add_dependency(from_task_id, to_task_id)
        if result:
            # Also update the task's dependencies field so _rebuild_schedule can reconstruct
            for task in plan.tasks:
                if task.id == to_task_id:
                    if from_task_id not in task.dependencies:
                        task.dependencies.append(from_task_id)
                    break

            if plan.config.auto_schedule:
                self._rebuild_schedule()
        plan._update_timestamp()
        self.save_plan(plan)
        return result

    # Resource operations

    def add_resource(
        self,
        name: str,
        resource_type: ResourceType = ResourceType.DEVELOPER,
        capacity: float = 1.0,
        unit: str = "unit",
        description: str = "",
        **kwargs,
    ) -> Optional[Resource]:
        """Add a resource to the active plan.

        Args:
            name: Resource name
            resource_type: Type of resource
            capacity: Total capacity
            unit: Unit of measurement
            description: Resource description
            **kwargs: Additional metadata

        Returns:
            The created resource, or None if no active plan
        """
        if not self._active_plan:
            return None

        resource = Resource(
            id=f"res_{uuid.uuid4().hex[:8]}",
            name=name,
            resource_type=resource_type,
            capacity=capacity,
            available=capacity,
            unit=unit,
            description=description,
            metadata=kwargs,
        )

        self._active_plan.resources.append(resource)
        self._active_plan._allocator.add_resource(resource)
        self._active_plan._update_timestamp()
        self.save_plan(self._active_plan)

        return resource

    # Schedule operations

    def get_schedule(self, plan_id: str, regenerate: bool = False) -> Optional[Schedule]:
        """Get the schedule for a plan.

        Args:
            plan_id: ID of the plan
            regenerate: If True, regenerate the schedule

        Returns:
            The schedule, or None if no plan found
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return None

        if regenerate or not plan._scheduler:
            return self._rebuild_schedule()

        return plan._scheduler.schedule()

    def _rebuild_schedule(self) -> Optional[Schedule]:
        """Rebuild the schedule for the active plan."""
        if not self._active_plan:
            return None

        # Rebuild the graph
        self._active_plan._graph = TaskGraph()
        for task in self._active_plan.tasks:
            self._active_plan._graph.add_task(task)

        # Re-add dependencies from task.dependencies field
        for task in self._active_plan.tasks:
            for dep_id in task.dependencies:
                try:
                    self._active_plan._graph.add_dependency(dep_id, task.id)
                except CycleDetectedError:
                    # Log warning but continue - graph should already be validated
                    pass

        # Rebuild the scheduler
        self._active_plan._scheduler = Scheduler(
            self._active_plan._graph,
            self._active_plan.config.scheduling_strategy
        )

        return self._active_plan._scheduler.schedule()

    # Progress tracking

    def get_progress(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get progress for a plan.

        Args:
            plan_id: ID of the plan

        Returns:
            Progress summary, or None if no plan found
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return None

        return plan._tracker.get_summary()

    def take_progress_snapshot(self, plan_id: str) -> None:
        """Take a progress snapshot for a plan.

        Args:
            plan_id: ID of the plan
        """
        plan = self._plans.get(plan_id)
        if plan:
            plan._tracker.take_snapshot()
            self.save_plan(plan)

    def mark_task_in_progress(self, plan_id: str, task_id: str) -> bool:
        """Mark a task as in progress.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        task.mark_in_progress()
        plan._tracker.update_task(task)
        # Emit progress snapshot for the transition (auto-detected)
        plan._tracker.on_task_status_changed(task)
        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def mark_task_completed(self, plan_id: str, task_id: str) -> bool:
        """Mark a task as completed.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        task.mark_completed()
        plan._tracker.update_task(task)
        # Emit progress snapshot for the transition (auto-detected)
        plan._tracker.on_task_status_changed(task)
        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def mark_task_ready(self, plan_id: str, task_id: str) -> bool:
        """Mark a task as ready to start.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        task.mark_ready()
        plan._tracker.update_task(task)
        # Emit progress snapshot for the transition (auto-detected)
        plan._tracker.on_task_status_changed(task)
        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def mark_task_failed(self, plan_id: str, task_id: str, reason: str = "") -> bool:
        """Mark a task as failed.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task
            reason: Reason for failure

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        task.mark_failed(reason)
        plan._tracker.update_task(task)
        # Emit progress snapshot for the transition (auto-detected)
        plan._tracker.on_task_status_changed(task)
        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def mark_task_blocked(self, plan_id: str, task_id: str, reason: str = "") -> bool:
        """Mark a task as blocked.

        Args:
            plan_id: ID of the plan
            task_id: ID of the task
            reason: Reason for being blocked

        Returns:
            True if task was updated
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        task = None
        for t in plan.tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return False

        task.mark_blocked(reason)
        plan._tracker.update_task(task)
        # Emit progress snapshot for the transition (auto-detected)
        plan._tracker.on_task_status_changed(task)
        plan._update_timestamp()
        self.save_plan(plan)

        return True

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all plans."""
        return {
            "total_plans": len(self._plans),
            "active_plan_id": self._active_plan.id if self._active_plan else None,
            "plans": [
                {
                    "id": p.id,
                    "name": p.config.name,
                    "status": p.status,
                    "task_count": len(p.tasks),
                    "resource_count": len(p.resources),
                    "created_at": p.created_at,
                }
                for p in self._plans.values()
            ],
        }

    # Progress data export methods for diagnostics, monitoring, backlog

    def get_progress_for_diagnostics(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get progress data formatted for diagnostics consumption."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        return plan._tracker.export_for_diagnostics()

    def get_progress_for_monitoring(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get progress data formatted for monitoring consumption."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        return plan._tracker.export_for_monitoring()

    def get_progress_for_backlog(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get progress data formatted for backlog consumption."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        return plan._tracker.export_for_backlog()

    def get_all_active_progress(self) -> Dict[str, Any]:
        """Get progress data for the active plan (for monitoring/backlog integration)."""
        if not self._active_plan:
            return {}
        return {
            "plan_id": self._active_plan.id,
            "diagnostics": self._active_plan._tracker.export_for_diagnostics(),
            "monitoring": self._active_plan._tracker.export_for_monitoring(),
            "backlog": self._active_plan._tracker.export_for_backlog(),
        }
