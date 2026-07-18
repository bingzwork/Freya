"""Plan Visualizer for generating visualizations of plans.

This module provides text-based and structured visualizations
of task plans, schedules, and progress.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from app.planner.task import Task, TaskStatus, TaskPriority
from app.planner.task_graph import TaskGraph, CycleDetectedError
from app.planner.scheduler import Schedule, ScheduleItem


@dataclass
class VisualizationOptions:
    """Options for customizing visualizations."""
    show_ids: bool = True
    show_priority: bool = True
    show_status: bool = True
    show_dependencies: bool = True
    show_duration: bool = True
    color_output: bool = False
    max_depth: Optional[int] = None


class PlanVisualizer:
    """Generates visualizations of task plans and schedules.

    This class provides various visualization formats for plans,
    including text, Gantt charts, and dependency graphs.
    """

    def __init__(self, options: Optional[VisualizationOptions] = None):
        """Initialize the visualizer.

        Args:
            options: Visualization options
        """
        self.options = options or VisualizationOptions()

    def visualize_graph(self, graph: TaskGraph) -> str:
        """Generate a text-based visualization of the task graph."""
        lines = []
        lines.append("=" * 60)
        lines.append("TASK DEPENDENCY GRAPH")
        lines.append("=" * 60)
        lines.append("")

        try:
            topo_order = graph.topological_sort()
        except CycleDetectedError:
            lines.append("ERROR: Graph contains cycles!")
            lines.append("")
            # Show cycles
            cycles = graph.detect_cycles()
            for cycle in cycles:
                lines.append(f"  Cycle detected: {' -> '.join(cycle)}")
            lines.append("")
            return "\n".join(lines)

        # Group tasks by level (tasks with no dependencies, then their dependents, etc.)
        levels = graph.get_parallel_tasks()

        for i, level in enumerate(levels):
            lines.append(f"Level {i + 1}:")
            for task_id in level:
                task = graph.get_task(task_id)
                if task:
                    lines.append(self._format_task(task, indent=2))
            lines.append("")

        # Show critical path
        critical_path = graph.get_critical_path()
        if critical_path:
            lines.append("-" * 60)
            lines.append("CRITICAL PATH")
            lines.append("-" * 60)
            for task_id in critical_path:
                task = graph.get_task(task_id)
                if task:
                    lines.append(self._format_task(task, indent=0))
            lines.append("")

        return "\n".join(lines)

    def visualize_schedule(self, schedule: Schedule, tasks: Optional[Dict[str, Task]] = None) -> str:
        """Generate a text-based Gantt chart visualization of the schedule."""
        lines = []
        lines.append("=" * 60)
        lines.append("TASK SCHEDULE (GANTT CHART)")
        lines.append("=" * 60)
        lines.append("")

        if not schedule.items:
            lines.append("No tasks scheduled.")
            return "\n".join(lines)

        # Sort items by start time
        sorted_items = sorted(
            schedule.items,
            key=lambda x: x.start_time
        )

        # Create time scale
        start_time = sorted_items[0].start_time
        end_time = sorted_items[-1].end_time

        lines.append(f"Timeline: {start_time} to {end_time}")
        lines.append("")

        for item in sorted_items:
            task = tasks.get(item.task_id) if tasks else None
            if task:
                lines.append(self._format_schedule_item(item, task))
            else:
                lines.append(f"[{item.start_time[:19]} -> {item.end_time[:19]}] Task {item.task_id}")

        lines.append("")
        lines.append("-" * 60)
        lines.append(f"Total Duration: {schedule.total_duration}")
        lines.append("-" * 60)

        return "\n".join(lines)

    def visualize_progress(self, tracker) -> str:
        """Generate a progress visualization."""
        from app.planner.progress_tracker import ProgressTracker
        if not isinstance(tracker, ProgressTracker):
            return "Invalid tracker type"

        lines = []
        lines.append("=" * 60)
        lines.append("PROGRESS REPORT")
        lines.append("=" * 60)
        lines.append("")

        summary = tracker.get_summary()

        # Overall progress
        lines.append(f"Overall Progress: {summary['overall_progress']:.1f}%")
        lines.append("")

        # Task counts
        lines.append("Task Status:")
        lines.append(f"  Total: {summary['total_tasks']}")
        lines.append(f"  Completed: {summary['completed_tasks']}")
        lines.append(f"  In Progress: {summary['in_progress_tasks']}")
        lines.append(f"  Pending: {summary['pending_tasks']}")
        lines.append(f"  Blocked: {summary['blocked_tasks']}")
        lines.append("")

        # Velocity
        velocity = summary.get("velocity", {})
        lines.append(f"Velocity: {velocity.get('tasks_per_hour', 0):.2f} tasks/hour")
        lines.append("")

        # Blocked tasks
        blocked = tracker.get_blocked_tasks()
        if blocked:
            lines.append("BLOCKED TASKS:")
            for task in blocked:
                lines.append(f"  - {task.title} ({task.id})")
                if "blocked_reason" in task.metadata:
                    lines.append(f"    Reason: {task.metadata['blocked_reason']}")
            lines.append("")

        # Overdue tasks
        overdue = tracker.get_overdue_tasks()
        if overdue:
            lines.append("OVERDUE TASKS:")
            for task in overdue:
                lines.append(f"  - {task.title} ({task.id})")
                if task.deadline:
                    lines.append(f"    Deadline: {task.deadline}")
            lines.append("")

        # Progress by category
        by_category = summary.get("by_category", {})
        if by_category:
            lines.append("Progress by Category:")
            for category, data in by_category.items():
                lines.append(f"  {category}: {data['progress']:.1f}% ({data['completed']}/{data['total']})")
            lines.append("")

        return "\n".join(lines)

    def visualize_burndown(self, tracker) -> str:
        """Generate a burndown chart visualization."""
        from app.planner.progress_tracker import ProgressTracker
        if not isinstance(tracker, ProgressTracker):
            return "Invalid tracker type"

        lines = []
        lines.append("=" * 60)
        lines.append("BURNDOWN CHART")
        lines.append("=" * 60)
        lines.append("")

        data = tracker.get_burndown_data()
        if not data:
            lines.append("No burndown data available.")
            return "\n".join(lines)

        # Simple text-based burndown
        max_remaining = max(d["remaining"] for d in data)
        max_ticks = 20

        for point in data:
            remaining = point["remaining"]
            completed = point["completed"]
            timestamp = point["timestamp"][:19]  # Shorten timestamp

            # Scale to max_ticks
            bar_length = int((remaining / max_remaining) * max_ticks) if max_remaining > 0 else 0
            bar = "#" * bar_length
            space = " " * (max_ticks - bar_length)

            lines.append(f"{timestamp} |{bar}{space}| {remaining} remaining, {completed} completed")

        return "\n".join(lines)

    def _format_task(self, task: Task, indent: int = 0) -> str:
        """Format a task for display."""
        prefix = " " * indent

        parts = []
        if self.options.show_priority:
            parts.append(f"[{task.priority.value.upper()}]")
        if self.options.show_status:
            parts.append(f"({task.status.value})")

        title = f"{prefix}{task.title}"
        if parts:
            title = f"{prefix}{' '.join(parts)} {task.title}"

        suffix = []
        if self.options.show_ids:
            suffix.append(f"[id:{task.id[:8]}]")
        if self.options.show_duration and task.estimated_hours:
            suffix.append(f"~{task.estimated_hours}h")

        line = title
        if suffix:
            line += f" {' '.join(suffix)}"

        if self.options.show_dependencies and task.dependencies:
            dep_ids = [d[:8] for d in task.dependencies]
            line += f"\n{prefix}  Depends on: {', '.join(dep_ids)}"

        return line

    def _format_schedule_item(self, item: ScheduleItem, task: Task) -> str:
        """Format a schedule item for display."""
        start = item.start_time[:19]
        end = item.end_time[:19]
        duration = item.duration

        # Format duration as hours and minutes
        total_seconds = duration.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

        # Build the line
        parts = [
            f"[{start} -> {end}]",
            f"{task.title}",
            f"({duration_str})",
        ]

        if self.options.show_ids:
            parts.append(f"[id:{task.id[:8]}]")

        if self.options.show_priority:
            parts.append(f"[{task.priority.value.upper()}]")

        if item.resource_id:
            parts.append(f"@:{item.resource_id}")

        return " ".join(parts)

    def generate_json(self, graph: TaskGraph) -> Dict[str, Any]:
        """Generate a JSON representation of the task graph."""
        return graph.to_dict()

    def generate_schedule_json(self, schedule: Schedule) -> Dict[str, Any]:
        """Generate a JSON representation of the schedule."""
        return schedule.to_dict()

    def generate_mermaid_graph(self, graph: TaskGraph) -> str:
        """Generate a Mermaid.js compatible graph visualization."""
        lines = []
        lines.append("graph TD")

        for node in graph._nodes.values():
            task = node.task
            # Format task display
            display = task.title.replace("\"", "'")
            if self.options.show_ids:
                display += f"\n({task.id[:8]})"
            if self.options.show_priority:
                display += f"\n[{task.priority.value.upper()}]"

            # Escape special characters
            display = display.replace("\"", "'")

            lines.append(f'    {task.id}["{display}"]')

        for edge in graph.get_edges():
            lines.append(f"    {edge.from_task_id} --> {edge.to_task_id}")

        return "\n".join(lines)

    def generate_mermaid_gantt(self, schedule: Schedule, tasks: Optional[Dict[str, Task]] = None) -> str:
        """Generate a Mermaid.js compatible Gantt chart."""
        lines = []
        lines.append("gantt")
        lines.append("    title Freya Task Schedule")
        lines.append("    dateFormat  YYYY-MM-DD HH:mm:ss")
        lines.append("")

        tasks = tasks or {}
        for item in schedule.items:
            task = tasks.get(item.task_id)
            if task:
                name = task.title.replace("\"", "'")
                # Use the actual start and end times
                lines.append(f'    {name} :{item.start_time[:19]}, {item.duration.total_seconds() // 3600}h')

        return "\n".join(lines)
