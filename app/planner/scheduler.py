"""Scheduler for task execution planning.

This module provides scheduling capabilities for determining the optimal
order and timing of task execution based on dependencies, resources,
and priorities.
"""

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Set, Callable
from collections import defaultdict

from app.planner.task import Task, TaskStatus, TaskPriority
from app.planner.task_graph import TaskGraph


class SchedulingStrategy(Enum):
    """Scheduling strategies."""
    # Execute tasks as soon as their dependencies are met
    ASAP = "asap"
    # Execute highest priority tasks first
    PRIORITY_FIRST = "priority_first"
    # Execute tasks with the longest duration first (critical path method)
    LONGEST_DURATION_FIRST = "longest_duration_first"
    # Execute tasks with the earliest deadline first
    DEADLINE_FIRST = "deadline_first"
    # Minimize resource contention
    RESOURCE_OPTIMIZED = "resource_optimized"


@dataclass
class ScheduleItem:
    """Represents a scheduled task execution."""
    task_id: str
    start_time: str
    end_time: str
    resource_id: Optional[str] = None

    @property
    def duration(self) -> timedelta:
        """Get the duration of the scheduled item."""
        start = datetime.fromisoformat(self.start_time)
        end = datetime.fromisoformat(self.end_time)
        return end - start

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "resource_id": self.resource_id,
        }


@dataclass
class Schedule:
    """Represents a complete schedule for tasks."""
    items: List[ScheduleItem] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = None
    total_duration: Optional[timedelta] = None

    def add_item(self, item: ScheduleItem) -> None:
        """Add a scheduled item."""
        self.items.append(item)

    def get_task_schedule(self, task_id: str) -> Optional[ScheduleItem]:
        """Get the schedule for a specific task."""
        for item in self.items:
            if item.task_id == task_id:
                return item
        return None

    def get_schedule_for_resource(self, resource_id: str) -> List[ScheduleItem]:
        """Get all scheduled items for a resource."""
        return [item for item in self.items if item.resource_id == resource_id]

    def calculate_total_duration(self) -> timedelta:
        """Calculate the total duration of the schedule."""
        if not self.items:
            return timedelta(0)

        end_times = [datetime.fromisoformat(item.end_time) for item in self.items]
        return max(end_times) - datetime.fromisoformat(self.start_time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_seconds": self.total_duration.total_seconds() if self.total_duration else 0,
            "items": [item.to_dict() for item in self.items],
        }

    def is_feasible(self, graph: TaskGraph) -> bool:
        """Check if the schedule respects all dependencies."""
        task_end_times = {}
        for item in self.items:
            task_end_times[item.task_id] = datetime.fromisoformat(item.end_time)

        for item in self.items:
            task = graph.get_task(item.task_id)
            if task:
                for dep_id in task.dependencies:
                    if dep_id not in task_end_times:
                        # Dependency not scheduled
                        return False
                    if task_end_times[dep_id] > datetime.fromisoformat(item.start_time):
                        # Dependency ends after this task starts
                        return False

        return True


class Scheduler:
    """Schedules tasks based on dependencies, resources, and priorities.

    This class provides various scheduling strategies for determining
    the optimal execution order for tasks.
    """

    def __init__(
        self,
        graph: Optional[TaskGraph] = None,
        strategy: SchedulingStrategy = SchedulingStrategy.ASAP,
    ):
        """Initialize the scheduler.

        Args:
            graph: The task graph to schedule
            strategy: The scheduling strategy to use
        """
        self.graph = graph or TaskGraph()
        self.strategy = strategy

    def schedule(self, start_time: Optional[str] = None) -> Schedule:
        """Generate a schedule for all tasks.

        Args:
            start_time: The start time for the schedule (ISO format string)

        Returns:
            A Schedule object containing the scheduled tasks
        """
        if start_time is None:
            start_time = datetime.now(timezone.utc).isoformat()

        if self.strategy == SchedulingStrategy.ASAP:
            return self._schedule_asap(start_time)
        elif self.strategy == SchedulingStrategy.PRIORITY_FIRST:
            return self._schedule_priority_first(start_time)
        elif self.strategy == SchedulingStrategy.LONGEST_DURATION_FIRST:
            return self._schedule_longest_duration_first(start_time)
        elif self.strategy == SchedulingStrategy.DEADLINE_FIRST:
            return self._schedule_deadline_first(start_time)
        else:
            return self._schedule_asap(start_time)

    def _schedule_asap(self, start_time: str) -> Schedule:
        """Schedule tasks as soon as possible (ASAP)."""
        schedule = Schedule(start_time=start_time)

        try:
            # Get topological order
            topo_order = self.graph.topological_sort()
        except Exception:
            # If cycle, just use all tasks
            topo_order = list(self.graph._nodes.keys())

        # Track task completion times
        completion_times: Dict[str, datetime] = {}

        for task_id in topo_order:
            task = self.graph.get_task(task_id)
            if task is None:
                continue

            # Calculate start time (max of all dependency completion times)
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(start_time))
                for dep_id in task.dependencies
            ]
            start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(start_time)

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task_id,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
            ))

            completion_times[task_id] = end

        schedule.total_duration = schedule.calculate_total_duration()
        schedule.end_time = (datetime.fromisoformat(start_time) + schedule.total_duration).isoformat()

        return schedule

    def _schedule_priority_first(self, start_time: str) -> Schedule:
        """Schedule tasks by priority (highest first)."""
        schedule = Schedule(start_time=start_time)

        # Get all tasks
        tasks = list(self.graph._nodes.values())

        # Sort by priority (descending)
        tasks.sort(key=lambda n: n.task.priority.score, reverse=True)

        completion_times: Dict[str, datetime] = {}
        scheduled_task_ids: Set[str] = set()

        while tasks:
            # Find tasks whose dependencies are all scheduled
            ready_tasks = []
            for node in tasks:
                if node.task_id in scheduled_task_ids:
                    continue

                # Check if all dependencies are scheduled
                all_deps_scheduled = all(
                    dep_id in scheduled_task_ids or dep_id not in self.graph._dependencies
                    for dep_id in self.graph._dependencies.get(node.task_id, set())
                )

                if all_deps_scheduled:
                    ready_tasks.append(node)

            if not ready_tasks:
                # Can't schedule any more tasks (cycle or unschedulable)
                break

            # Sort ready tasks by priority
            ready_tasks.sort(key=lambda n: n.task.priority.score, reverse=True)

            # Schedule the highest priority ready task
            task_node = ready_tasks[0]
            task = task_node.task

            # Calculate start time
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(start_time))
                for dep_id in task.dependencies
            ]
            start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(start_time)

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task.id,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
            ))

            completion_times[task.id] = end
            scheduled_task_ids.add(task.id)

            # Remove from tasks list
            tasks = [t for t in tasks if t.task_id != task.id]

        schedule.total_duration = schedule.calculate_total_duration()
        schedule.end_time = (datetime.fromisoformat(start_time) + schedule.total_duration).isoformat()

        return schedule

    def _schedule_longest_duration_first(self, start_time: str) -> Schedule:
        """Schedule tasks with longest duration first (Critical Path Method)."""
        schedule = Schedule(start_time=start_time)

        try:
            topo_order = self.graph.topological_sort()
        except Exception:
            topo_order = list(self.graph._nodes.keys())

        completion_times: Dict[str, datetime] = {}

        # Sort by estimated duration (descending)
        sorted_tasks = sorted(
            topo_order,
            key=lambda tid: self.graph.get_task(tid).estimated_hours,
            reverse=True
        )

        for task_id in sorted_tasks:
            task = self.graph.get_task(task_id)
            if task is None:
                continue

            # Calculate start time
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(start_time))
                for dep_id in task.dependencies
            ]
            start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(start_time)

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task_id,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
            ))

            completion_times[task_id] = end

        schedule.total_duration = schedule.calculate_total_duration()
        schedule.end_time = (datetime.fromisoformat(start_time) + schedule.total_duration).isoformat()

        return schedule

    def _schedule_deadline_first(self, start_time: str) -> Schedule:
        """Schedule tasks with earliest deadline first."""
        schedule = Schedule(start_time=start_time)

        # Get all tasks with deadlines
        tasks_with_deadlines = []
        tasks_without_deadlines = []

        for node in self.graph._nodes.values():
            task = node.task
            if task.deadline:
                tasks_with_deadlines.append((task, datetime.fromisoformat(task.deadline)))
            else:
                tasks_without_deadlines.append(task)

        # Sort by deadline (ascending)
        tasks_with_deadlines.sort(key=lambda x: x[1])

        completion_times: Dict[str, datetime] = {}
        scheduled_task_ids: Set[str] = set()

        # First schedule tasks with deadlines
        for task, deadline in tasks_with_deadlines:
            if task.id in scheduled_task_ids:
                continue

            # Check if dependencies are scheduled
            all_deps_scheduled = all(
                dep_id in scheduled_task_ids or dep_id not in self.graph._dependencies
                for dep_id in self.graph._dependencies.get(task.id, set())
            )

            if not all_deps_scheduled:
                continue

            # Calculate start time
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(start_time))
                for dep_id in task.dependencies
            ]
            start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(start_time)

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task.id,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
            ))

            completion_times[task.id] = end
            scheduled_task_ids.add(task.id)

        # Then schedule remaining tasks
        for task in tasks_without_deadlines:
            if task.id in scheduled_task_ids:
                continue

            # Check if dependencies are scheduled
            all_deps_scheduled = all(
                dep_id in scheduled_task_ids or dep_id not in self.graph._dependencies
                for dep_id in self.graph._dependencies.get(task.id, set())
            )

            if not all_deps_scheduled:
                continue

            # Calculate start time
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(start_time))
                for dep_id in task.dependencies
            ]
            start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(start_time)

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task.id,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
            ))

            completion_times[task.id] = end
            scheduled_task_ids.add(task.id)

        schedule.total_duration = schedule.calculate_total_duration()
        schedule.end_time = (datetime.fromisoformat(start_time) + schedule.total_duration).isoformat()

        return schedule

    def get_critical_path_duration(self) -> timedelta:
        """Get the duration of the critical path."""
        try:
            critical_path = self.graph.get_critical_path()
        except Exception:
            return timedelta(0)

        total = timedelta(0)
        for task_id in critical_path:
            task = self.graph.get_task(task_id)
            if task:
                total += task.estimated_duration or timedelta(hours=task.estimated_hours)

        return total

    def get_parallel_execution_levels(self) -> int:
        """Get the maximum number of tasks that can be executed in parallel."""
        levels = self.graph.get_parallel_tasks()
        return max(len(level) for level in levels) if levels else 0

    def optimize_for_resources(self, resource_count: int) -> Schedule:
        """Optimize the schedule for a given number of resources.

        Args:
            resource_count: Number of resources available

        Returns:
            A schedule optimized for the given resources
        """
        # This is a simplified implementation
        # A full implementation would track resource availability over time
        schedule = Schedule(start_time=datetime.now(timezone.utc).isoformat())

        try:
            topo_order = self.graph.topological_sort()
        except Exception:
            topo_order = list(self.graph._nodes.keys())

        # Track resource availability
        resource_end_times = [datetime.fromisoformat(schedule.start_time)] * resource_count

        completion_times: Dict[str, datetime] = {}

        for task_id in topo_order:
            task = self.graph.get_task(task_id)
            if task is None:
                continue

            # Calculate start time (max of all dependency completion times)
            dep_completion_times = [
                completion_times.get(dep_id, datetime.fromisoformat(schedule.start_time))
                for dep_id in task.dependencies
            ]
            dep_start = max(dep_completion_times) if dep_completion_times else datetime.fromisoformat(schedule.start_time)

            # Find the earliest available resource
            earliest_resource_idx = min(
                range(resource_count),
                key=lambda i: resource_end_times[i]
            )
            resource_start = max(dep_start, resource_end_times[earliest_resource_idx])

            # Calculate duration
            duration = task.estimated_duration or timedelta(hours=task.estimated_hours)

            # Calculate end time
            end = resource_start + duration

            # Add to schedule
            schedule.add_item(ScheduleItem(
                task_id=task_id,
                start_time=resource_start.isoformat(),
                end_time=end.isoformat(),
                resource_id=f"resource_{earliest_resource_idx}",
            ))

            completion_times[task_id] = end
            resource_end_times[earliest_resource_idx] = end

        schedule.total_duration = schedule.calculate_total_duration()
        schedule.end_time = (datetime.fromisoformat(schedule.start_time) + schedule.total_duration).isoformat()

        return schedule
