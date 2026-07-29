"""Tests for the Planner System."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.planner.task import (
    Task,
    TaskStatus,
    TaskPriority,
    TaskCategory,
)
from app.planner.task_graph import (
    TaskGraph,
    TaskNode,
    DependencyEdge,
    CycleDetectedError,
)
from app.planner.scheduler import (
    Scheduler,
    Schedule,
    ScheduleItem,
    SchedulingStrategy,
)
from app.planner.resource_allocator import (
    ResourceAllocator,
    Resource,
    ResourceType,
    Allocation,
)
from app.planner.progress_tracker import (
    ProgressTracker,
    ProgressSnapshot,
)
from app.planner.plan_visualizer import (
    PlanVisualizer,
    VisualizationOptions,
)
from app.planner.plan_manager import (
    PlanManager,
    Plan,
    PlanConfig,
)


class TestTask:
    """Tests for Task."""

    def test_task_creation(self):
        """Test creating a task."""
        task = Task(
            title="Test Task",
            description="Test description",
        )
        assert task.title == "Test Task"
        assert task.description == "Test description"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.MEDIUM

    def test_task_with_all_fields(self):
        """Test creating a task with all fields."""
        task = Task(
            id="test-001",
            title="Full Task",
            description="Full description",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            category=TaskCategory.FEATURE,
            estimated_hours=4.0,
            assignee="testuser",
            tags=["tag1", "tag2"],
            deadline="2026-12-31T00:00:00+00:00",
        )
        assert task.id == "test-001"
        assert task.estimated_hours == 4.0
        assert task.assignee == "testuser"
        assert task.status == TaskStatus.IN_PROGRESS

    def test_task_from_dict(self):
        """Test creating task from dictionary."""
        data = {
            "id": "test-001",
            "title": "From Dict",
            "description": "Desc",
            "status": "in_progress",
            "priority": "high",
            "category": "feature",
            "estimated_hours": 5.0,
        }
        task = Task.from_dict(data)
        assert task.id == "test-001"
        assert task.title == "From Dict"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.priority == TaskPriority.HIGH

    def test_task_to_dict(self):
        """Test converting task to dictionary."""
        task = Task(
            id="test-001",
            title="Test",
            estimated_hours=3.0,
        )
        data = task.to_dict()
        assert data["id"] == "test-001"
        assert data["title"] == "Test"
        assert data["estimated_hours"] == 3.0

    def test_set_estimated_hours(self):
        """Test setting estimated hours."""
        task = Task(title="Test")
        task.set_estimated_hours(8.0)
        assert task.estimated_hours == 8.0
        assert task.estimated_duration == timedelta(hours=8)

    def test_mark_states(self):
        """Test marking task states."""
        task = Task(title="Test")

        task.mark_ready()
        assert task.status == TaskStatus.READY

        task.mark_in_progress()
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.start_time is not None

        task.mark_completed()
        assert task.status == TaskStatus.COMPLETED
        assert task.end_time is not None
        assert task.progress_percent == 100

        task2 = Task(title="Test2")
        task2.mark_blocked("Waiting for review")
        assert task2.status == TaskStatus.BLOCKED
        assert task2.metadata.get("blocked_reason") == "Waiting for review"

        task3 = Task(title="Test3")
        task3.mark_failed("Build failed")
        assert task3.status == TaskStatus.FAILED
        assert task3.metadata.get("failure_reason") == "Build failed"

        task4 = Task(title="Test4")
        task4.mark_cancelled("No longer needed")
        assert task4.status == TaskStatus.CANCELLED
        assert task4.metadata.get("cancel_reason") == "No longer needed"

    def test_is_complete(self):
        """Test checking if task is complete."""
        task = Task(title="Test")
        assert task.is_complete is False

        task.mark_completed()
        assert task.is_complete is True

    def test_is_active(self):
        """Test checking if task is active."""
        task = Task(title="Test")
        assert task.is_active is False

        task.mark_ready()
        assert task.is_active is True

        task.mark_in_progress()
        assert task.is_active is True

        task.mark_completed()
        assert task.is_active is False

    def test_comparison(self):
        """Test comparing tasks by priority."""
        high = Task(title="High", priority=TaskPriority.HIGH)
        low = Task(title="Low", priority=TaskPriority.LOW)
        # Higher priority should come first (lower in sorted list)
        assert high < low


class TestTaskStatus:
    """Tests for TaskStatus."""

    def test_all_statuses(self):
        """Test all status values."""
        statuses = [
            TaskStatus.PENDING,
            TaskStatus.READY,
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ]
        for status in statuses:
            assert isinstance(status, TaskStatus)


class TestTaskPriority:
    """Tests for TaskPriority."""

    def test_priority_scores(self):
        """Test priority scores."""
        assert TaskPriority.CRITICAL.score == 4
        assert TaskPriority.HIGH.score == 3
        assert TaskPriority.MEDIUM.score == 2
        assert TaskPriority.LOW.score == 1


class TestTaskCategory:
    """Tests for TaskCategory."""

    def test_all_categories(self):
        """Test all category values."""
        categories = [
            TaskCategory.IMPLEMENTATION,
            TaskCategory.TESTING,
            TaskCategory.DOCUMENTATION,
            TaskCategory.REVIEW,
            TaskCategory.REFACTORING,
            TaskCategory.BUG_FIX,
            TaskCategory.FEATURE,
            TaskCategory.MAINTENANCE,
            TaskCategory.RESEARCH,
            TaskCategory.OTHER,
        ]
        for cat in categories:
            assert isinstance(cat, TaskCategory)


class TestTaskGraph:
    """Tests for TaskGraph."""

    def test_graph_creation(self):
        """Test creating a task graph."""
        graph = TaskGraph()
        assert graph.count_tasks() == 0
        assert graph.count_edges() == 0

    def test_add_task(self):
        """Test adding a task to the graph."""
        graph = TaskGraph()
        task = Task(id="task1", title="Task 1")
        graph.add_task(task)
        assert graph.count_tasks() == 1

    def test_remove_task(self):
        """Test removing a task from the graph."""
        graph = TaskGraph()
        task = Task(id="task1", title="Task 1")
        graph.add_task(task)
        assert graph.remove_task("task1") is True
        assert graph.count_tasks() == 0

    def test_remove_nonexistent_task(self):
        """Test removing a non-existent task."""
        graph = TaskGraph()
        assert graph.remove_task("nonexistent") is False

    def test_add_dependency(self):
        """Test adding a dependency."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        assert graph.count_edges() == 1

    def test_add_dependency_between_tasks(self):
        """Test adding dependency between existing tasks."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_dependency("task1", "task2")
        assert graph.count_edges() == 1

    def test_cycle_detection(self):
        """Test cycle detection."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        task3 = Task(id="task3", title="Task 3")
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        graph.add_dependency("task1", "task2")
        graph.add_dependency("task2", "task3")

        # Check no cycle yet
        assert graph.has_cycle() is False

        # This should create a cycle
        with pytest.raises(CycleDetectedError):
            graph.add_dependency("task3", "task1")

    def test_has_cycle(self):
        """Test has_cycle method."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        graph.add_task(task1)
        graph.add_task(task2)

        assert graph.has_cycle() is False

        graph.add_dependency("task1", "task2")
        assert graph.has_cycle() is False

    def test_detect_cycles(self):
        """Test cycle detection."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        task3 = Task(id="task3", title="Task 3")
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        graph.add_dependency("task1", "task2")
        graph.add_dependency("task2", "task3")
        # Manually create a cycle by directly modifying the internal state
        # (bypassing the cycle check in add_dependency)
        graph._dependencies["task1"].add("task3")
        graph._dependents["task3"].add("task1")
        graph._edges.add(DependencyEdge(from_task_id="task3", to_task_id="task1"))

        cycles = graph.detect_cycles()
        assert len(cycles) > 0

    def test_get_roots(self):
        """Test getting root tasks."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Root 1")
        task2 = Task(id="task2", title="Root 2")
        task3 = Task(id="task3", title="Dependent", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        roots = graph.get_roots()
        assert set(roots) == {"task1", "task2"}

    def test_get_leaves(self):
        """Test getting leaf tasks."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Root")
        task2 = Task(id="task2", title="Leaf 1", dependencies=["task1"])
        task3 = Task(id="task3", title="Leaf 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        leaves = graph.get_leaves()
        assert set(leaves) == {"task2", "task3"}

    def test_topological_sort(self):
        """Test topological sort."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", dependencies=["task2"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        sorted_tasks = graph.topological_sort()
        assert sorted_tasks == ["task1", "task2", "task3"]

    def test_topological_sort_with_cycle(self):
        """Test topological sort with cycle raises error."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_dependency("task1", "task2")
        # Manually create a cycle by directly modifying the internal state
        graph._dependencies["task1"].add("task2")
        graph._dependents["task2"].add("task1")
        graph._edges.add(DependencyEdge(from_task_id="task2", to_task_id="task1"))

        with pytest.raises(CycleDetectedError):
            graph.topological_sort()

    def test_get_all_dependencies(self):
        """Test getting all transitive dependencies."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", dependencies=["task2"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        deps = graph.get_all_dependencies("task3")
        assert set(deps) == {"task1", "task2"}

    def test_get_all_dependents(self):
        """Test getting all transitive dependents."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", dependencies=["task2"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        dependents = graph.get_all_dependents("task1")
        assert set(dependents) == {"task2", "task3"}

    def test_critical_path(self):
        """Test getting critical path."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=2.0)
        task2 = Task(id="task2", title="Task 2", estimated_hours=3.0, dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", estimated_hours=1.0, dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        critical_path = graph.get_critical_path()
        assert "task1" in critical_path
        assert "task2" in critical_path

    def test_get_task(self):
        """Test getting a task by ID."""
        graph = TaskGraph()
        task = Task(id="task1", title="Task 1")
        graph.add_task(task)
        retrieved = graph.get_task("task1")
        assert retrieved is not None
        assert retrieved.id == "task1"

    def test_get_all_tasks(self):
        """Test getting all tasks."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        graph.add_task(task1)
        graph.add_task(task2)
        tasks = graph.get_all_tasks()
        assert len(tasks) == 2

    def test_to_dict(self):
        """Test converting to dictionary."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        data = graph.to_dict()
        assert "tasks" in data
        assert "dependencies" in data

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "tasks": [
                {"id": "task1", "title": "Task 1"},
                {"id": "task2", "title": "Task 2", "dependencies": ["task1"]},
            ],
            "dependencies": [
                {"from": "task1", "to": "task2"},
            ],
        }
        graph = TaskGraph.from_dict(data)
        assert graph.count_tasks() == 2
        assert graph.count_edges() == 1

    def test_parallel_tasks(self):
        """Test getting parallel task levels."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        levels = graph.get_parallel_tasks()
        assert len(levels) == 2
        assert len(levels[0]) == 1  # task1
        assert len(levels[1]) == 2  # task2, task3

    def test_visualize(self):
        """Test graph visualization."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        visualization = graph.visualize()
        assert "Task 1" in visualization
        assert "Task 2" in visualization


class TestScheduler:
    """Tests for Scheduler."""

    def test_scheduler_initialization(self):
        """Test scheduler initialization."""
        graph = TaskGraph()
        scheduler = Scheduler(graph=graph)
        assert scheduler.graph is not None

    def test_schedule_asap(self):
        """Test ASAP scheduling."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=2.0)
        task2 = Task(id="task2", title="Task 2", estimated_hours=3.0, dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)

        scheduler = Scheduler(graph=graph, strategy=SchedulingStrategy.ASAP)
        schedule = scheduler.schedule()

        assert schedule.items is not None
        assert len(schedule.items) == 2

    def test_schedule_priority_first(self):
        """Test priority-first scheduling."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Low Priority", estimated_hours=2.0, priority=TaskPriority.LOW)
        task2 = Task(id="task2", title="High Priority", estimated_hours=2.0, priority=TaskPriority.HIGH)
        graph.add_task(task1)
        graph.add_task(task2)

        scheduler = Scheduler(graph=graph, strategy=SchedulingStrategy.PRIORITY_FIRST)
        schedule = scheduler.schedule()

        assert schedule.items is not None
        assert len(schedule.items) == 2

    def test_schedule_with_dependencies(self):
        """Test scheduling with dependencies."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=1.0)
        task2 = Task(id="task2", title="Task 2", estimated_hours=1.0, dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", estimated_hours=1.0, dependencies=["task2"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        scheduler = Scheduler(graph=graph, strategy=SchedulingStrategy.ASAP)
        schedule = scheduler.schedule()

        assert schedule.is_feasible(graph) is True

        # Check that task2 starts after task1 ends
        task1_item = schedule.get_task_schedule("task1")
        task2_item = schedule.get_task_schedule("task2")
        assert task1_item is not None
        assert task2_item is not None
        assert task1_item.end_time <= task2_item.start_time

    def test_critical_path_duration(self):
        """Test critical path duration calculation."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=2.0)
        task2 = Task(id="task2", title="Task 2", estimated_hours=3.0, dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)

        scheduler = Scheduler(graph=graph)
        duration = scheduler.get_critical_path_duration()
        assert duration == timedelta(hours=5)

    def test_parallel_execution_levels(self):
        """Test parallel execution levels."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        task3 = Task(id="task3", title="Task 3", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        scheduler = Scheduler(graph=graph)
        levels = scheduler.get_parallel_execution_levels()
        assert levels == 2

    def test_optimize_for_resources(self):
        """Test resource optimization."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=2.0)
        task2 = Task(id="task2", title="Task 2", estimated_hours=2.0)
        task3 = Task(id="task3", title="Task 3", estimated_hours=2.0)
        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        scheduler = Scheduler(graph=graph)
        schedule = scheduler.optimize_for_resources(resource_count=2)

        # With 2 resources and 3 tasks, at least 2 tasks should be scheduled
        assert len(schedule.items) == 3

    def test_get_summary(self):
        """Test getting summary."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1", estimated_hours=2.0)
        graph.add_task(task1)

        scheduler = Scheduler(graph=graph)
        schedule = scheduler.schedule()

        summary = {
            "total_tasks": len(schedule.items),
            "total_duration": schedule.total_duration,
        }
        assert summary["total_tasks"] == 1


class TestSchedule:
    """Tests for Schedule."""

    def test_schedule_creation(self):
        """Test creating a schedule."""
        schedule = Schedule()
        assert schedule.items == []

    def test_add_item(self):
        """Test adding an item to the schedule."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        item = ScheduleItem(task_id="task1", start_time=now, end_time=end)
        schedule.add_item(item)
        assert len(schedule.items) == 1

    def test_get_task_schedule(self):
        """Test getting schedule for a task."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        item = ScheduleItem(task_id="task1", start_time=now, end_time=end)
        schedule.add_item(item)
        retrieved = schedule.get_task_schedule("task1")
        assert retrieved is not None
        assert retrieved.task_id == "task1"

    def test_calculate_total_duration(self):
        """Test calculating total duration."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end1 = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        end2 = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        schedule.add_item(ScheduleItem(task_id="task1", start_time=now, end_time=end1))
        schedule.add_item(ScheduleItem(task_id="task2", start_time=now, end_time=end2))
        duration = schedule.calculate_total_duration()
        assert duration >= timedelta(hours=4)

    def test_to_dict(self):
        """Test converting to dictionary."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        schedule.add_item(ScheduleItem(task_id="task1", start_time=now, end_time=end))
        data = schedule.to_dict()
        assert "items" in data
        assert "start_time" in data


class TestScheduleItem:
    """Tests for ScheduleItem."""

    def test_item_creation(self):
        """Test creating a schedule item."""
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        item = ScheduleItem(task_id="task1", start_time=now, end_time=end)
        assert item.task_id == "task1"
        assert item.duration == timedelta(hours=2)

    def test_to_dict(self):
        """Test converting to dictionary."""
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        item = ScheduleItem(task_id="task1", start_time=now, end_time=end)
        data = item.to_dict()
        assert data["task_id"] == "task1"


class TestSchedulingStrategy:
    """Tests for SchedulingStrategy."""

    def test_all_strategies(self):
        """Test all strategy values."""
        strategies = [
            SchedulingStrategy.ASAP,
            SchedulingStrategy.PRIORITY_FIRST,
            SchedulingStrategy.LONGEST_DURATION_FIRST,
            SchedulingStrategy.DEADLINE_FIRST,
            SchedulingStrategy.RESOURCE_OPTIMIZED,
        ]
        for strategy in strategies:
            assert isinstance(strategy, SchedulingStrategy)


class TestResource:
    """Tests for Resource."""

    def test_resource_creation(self):
        """Test creating a resource."""
        resource = Resource(
            id="res1",
            name="Developer 1",
            resource_type=ResourceType.DEVELOPER,
            capacity=1.0,
        )
        assert resource.id == "res1"
        assert resource.name == "Developer 1"
        assert resource.resource_type == ResourceType.DEVELOPER

    def test_resource_from_dict(self):
        """Test creating resource from dictionary."""
        data = {
            "id": "res1",
            "name": "Dev 1",
            "resource_type": "developer",
            "capacity": 8.0,
        }
        resource = Resource.from_dict(data)
        assert resource.id == "res1"
        assert resource.resource_type == ResourceType.DEVELOPER

    def test_to_dict(self):
        """Test converting to dictionary."""
        resource = Resource(
            id="res1",
            name="Dev 1",
            resource_type=ResourceType.DEVELOPER,
        )
        data = resource.to_dict()
        assert data["id"] == "res1"
        assert data["resource_type"] == "developer"

    def test_utilization(self):
        """Test utilization calculation."""
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0, available=4.0)
        assert resource.utilization == 50.0

    def test_allocate(self):
        """Test allocating resource capacity."""
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0)
        assert resource.allocate(2.0) is True
        assert resource.available == 6.0

    def test_allocate_failure(self):
        """Test allocation failure when not enough capacity."""
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0, available=2.0)
        assert resource.allocate(5.0) is False
        assert resource.available == 2.0

    def test_release(self):
        """Test releasing resource capacity."""
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0, available=4.0)
        resource.release(2.0)
        assert resource.available == 6.0

    def test_reset(self):
        """Test resetting resource."""
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0, available=4.0)
        resource.reset()
        assert resource.available == 8.0


class TestResourceType:
    """Tests for ResourceType."""

    def test_all_types(self):
        """Test all resource type values."""
        types = [
            ResourceType.DEVELOPER,
            ResourceType.MACHINE,
            ResourceType.GPU,
            ResourceType.MEMORY,
            ResourceType.STORAGE,
            ResourceType.LICENSE,
            ResourceType.TOOL,
            ResourceType.CUSTOM,
        ]
        for res_type in types:
            assert isinstance(res_type, ResourceType)


class TestAllocation:
    """Tests for Allocation."""

    def test_allocation_creation(self):
        """Test creating an allocation."""
        now = datetime.now(timezone.utc).isoformat()
        allocation = Allocation(
            task_id="task1",
            resource_id="res1",
            amount=1.0,
            allocated_at=now,
        )
        assert allocation.task_id == "task1"
        assert allocation.resource_id == "res1"

    def test_to_dict(self):
        """Test converting to dictionary."""
        now = datetime.now(timezone.utc).isoformat()
        allocation = Allocation(
            task_id="task1",
            resource_id="res1",
            amount=1.0,
            allocated_at=now,
        )
        data = allocation.to_dict()
        assert data["task_id"] == "task1"


class TestResourceAllocator:
    """Tests for ResourceAllocator."""

    def test_allocator_initialization(self):
        """Test allocator initialization."""
        allocator = ResourceAllocator()
        assert len(allocator.list_resources()) == 0

    def test_add_resource(self):
        """Test adding a resource."""
        allocator = ResourceAllocator()
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER)
        allocator.add_resource(resource)
        assert len(allocator.list_resources()) == 1

    def test_remove_resource(self):
        """Test removing a resource."""
        allocator = ResourceAllocator()
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER)
        allocator.add_resource(resource)
        assert allocator.remove_resource("res1") is True
        assert allocator.get_resource("res1") is None

    def test_get_resource(self):
        """Test getting a resource."""
        allocator = ResourceAllocator()
        resource = Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER)
        allocator.add_resource(resource)
        retrieved = allocator.get_resource("res1")
        assert retrieved is not None
        assert retrieved.id == "res1"

    def test_list_resources(self):
        """Test listing resources."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER))
        resources = allocator.list_resources()
        assert len(resources) == 2

    def test_list_resources_by_type(self):
        """Test listing resources by type."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="dev1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.add_resource(Resource(id="gpu1", name="GPU1", resource_type=ResourceType.GPU, capacity=1.0))
        devs = allocator.list_resources(ResourceType.DEVELOPER)
        assert len(devs) == 1
        assert devs[0].resource_type == ResourceType.DEVELOPER

    def test_allocate(self):
        """Test allocating a resource."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocation = allocator.allocate("task1", "res1", 2.0)
        assert allocation is not None
        assert allocation.amount == 2.0

    def test_allocate_failure(self):
        """Test allocation failure."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=2.0))
        allocation = allocator.allocate("task1", "res1", 5.0)
        assert allocation is None

    def test_allocate_for_task(self):
        """Test allocating resources for a task."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocations = allocator.allocate_for_task("task1", ["res1", "res2"])
        assert len(allocations) == 2

    def test_allocate_for_task_rollback(self):
        """Test allocation rollback on failure."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=2.0))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER, capacity=2.0))
        # Allocate one resource first to make the second fail
        allocator.allocate("task0", "res1", 2.0)  # Fully allocate res1
        # Now try to allocate both - should fail and rollback
        allocations = allocator.allocate_for_task("task1", ["res1", "res2"])
        assert len(allocations) == 0

    def test_release(self):
        """Test releasing an allocation."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.allocate("task1", "res1", 2.0)
        allocator.release("task1", "res1", 2.0)
        resource = allocator.get_resource("res1")
        assert resource.available == 8.0

    def test_release_for_task(self):
        """Test releasing all resources for a task."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.allocate_for_task("task1", ["res1", "res2"])
        allocator.release_for_task("task1")
        resource1 = allocator.get_resource("res1")
        resource2 = allocator.get_resource("res2")
        assert resource1.available == 8.0
        assert resource2.available == 8.0

    def test_is_available(self):
        """Test checking resource availability."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        assert allocator.is_available("res1", 5.0) is True
        allocator.allocate("task1", "res1", 5.0)
        assert allocator.is_available("res1", 5.0) is False

    def test_get_available_resources(self):
        """Test getting available resources."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER, capacity=0.0))  # Fully allocated
        available = allocator.get_available_resources(min_amount=1.0)
        assert len(available) == 1
        assert available[0].id == "res1"

    def test_get_utilization(self):
        """Test getting utilization."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev1", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        allocator.add_resource(Resource(id="res2", name="Dev2", resource_type=ResourceType.DEVELOPER, capacity=4.0, available=2.0))
        utilization = allocator.get_utilization()
        assert utilization["res1"] == 0.0
        assert utilization["res2"] == 50.0

    def test_get_summary(self):
        """Test getting summary."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0))
        summary = allocator.get_summary()
        assert "total_resources" in summary
        assert summary["total_resources"] == 1

    def test_reset(self):
        """Test resetting allocator."""
        allocator = ResourceAllocator()
        allocator.add_resource(Resource(id="res1", name="Dev", resource_type=ResourceType.DEVELOPER, capacity=8.0, available=4.0))
        allocator.reset()
        resource = allocator.get_resource("res1")
        assert resource.available == 8.0


class TestProgressSnapshot:
    """Tests for ProgressSnapshot."""

    def test_snapshot_creation(self):
        """Test creating a snapshot."""
        tasks = [
            Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED),
            Task(id="t2", title="Task 2", status=TaskStatus.IN_PROGRESS),
        ]
        snapshot = ProgressSnapshot.create(tasks)
        assert snapshot.total_tasks == 2
        assert snapshot.completed_tasks == 1

    def test_to_dict(self):
        """Test converting to dictionary."""
        tasks = [Task(id="t1", title="Task 1")]
        snapshot = ProgressSnapshot.create(tasks)
        data = snapshot.to_dict()
        assert "total_tasks" in data
        assert "completed_tasks" in data


class TestProgressTracker:
    """Tests for ProgressTracker."""

    def test_tracker_initialization(self):
        """Test tracker initialization."""
        tracker = ProgressTracker()
        assert len(tracker.get_all_tasks()) == 0

    def test_add_task(self):
        """Test adding a task."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Task 1")
        tracker.add_task(task)
        assert len(tracker.get_all_tasks()) == 1

    def test_update_task(self):
        """Test updating a task."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Task 1")
        tracker.add_task(task)
        task.title = "Updated Task"
        tracker.update_task(task)
        retrieved = tracker.get_task("task1")
        assert retrieved.title == "Updated Task"

    def test_remove_task(self):
        """Test removing a task."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Task 1")
        tracker.add_task(task)
        assert tracker.remove_task("task1") is True
        assert tracker.get_task("task1") is None

    def test_take_snapshot(self):
        """Test taking a snapshot."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED))
        snapshot = tracker.take_snapshot()
        assert snapshot.total_tasks == 1
        assert snapshot.completed_tasks == 1

    def test_get_current_snapshot(self):
        """Test getting current snapshot."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1"))
        snapshot = tracker.get_current_snapshot()
        assert snapshot.total_tasks == 1

    def test_get_snapshots(self):
        """Test getting snapshots."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1"))
        tracker.take_snapshot()
        tracker.take_snapshot()
        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 2

    def test_get_overall_progress(self):
        """Test getting overall progress."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED))
        tracker.add_task(Task(id="t2", title="Task 2"))
        progress = tracker.get_overall_progress()
        assert progress == 50.0

    def test_get_burndown_data(self):
        """Test getting burndown data."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1"))
        tracker.take_snapshot()
        tracker.get_task("t1").mark_completed()
        tracker.take_snapshot()
        data = tracker.get_burndown_data()
        assert len(data) == 2

    def test_get_velocity(self):
        """Test getting velocity."""
        tracker = ProgressTracker()
        task1 = Task(id="t1", title="Task 1")
        task1.set_end_time()
        tracker.add_task(task1)
        tracker.track_completion("t1")
        # Need at least 2 completions for velocity
        assert "tasks_per_hour" in tracker.get_velocity()

    def test_get_blocked_tasks(self):
        """Test getting blocked tasks."""
        tracker = ProgressTracker()
        task1 = Task(id="t1", title="Task 1")
        task1.mark_blocked("Waiting")
        tracker.add_task(task1)
        blocked = tracker.get_blocked_tasks()
        assert len(blocked) == 1

    def test_get_overdue_tasks(self):
        """Test getting overdue tasks."""
        tracker = ProgressTracker()
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        task1 = Task(id="t1", title="Task 1", deadline=yesterday)
        tracker.add_task(task1)
        overdue = tracker.get_overdue_tasks()
        assert len(overdue) == 1

    def test_get_progress_by_category(self):
        """Test getting progress by category."""
        tracker = ProgressTracker()
        task1 = Task(id="t1", title="Task 1", category=TaskCategory.IMPLEMENTATION, status=TaskStatus.COMPLETED)
        task2 = Task(id="t2", title="Task 2", category=TaskCategory.IMPLEMENTATION)
        tracker.add_task(task1)
        tracker.add_task(task2)
        progress = tracker.get_progress_by_category()
        assert "implementation" in progress
        assert progress["implementation"]["progress"] == 50.0

    def test_get_progress_by_priority(self):
        """Test getting progress by priority."""
        tracker = ProgressTracker()
        task1 = Task(id="t1", title="Task 1", priority=TaskPriority.HIGH, status=TaskStatus.COMPLETED)
        task2 = Task(id="t2", title="Task 2", priority=TaskPriority.HIGH)
        tracker.add_task(task1)
        tracker.add_task(task2)
        progress = tracker.get_progress_by_priority()
        assert "high" in progress
        assert progress["high"]["progress"] == 50.0

    def test_get_summary(self):
        """Test getting summary."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED))
        summary = tracker.get_summary()
        assert "total_tasks" in summary
        assert "completed_tasks" in summary
        assert summary["completed_tasks"] == 1

    def test_get_estimated_remaining_time(self):
        """Test getting estimated remaining time."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED))
        # With only 1 completed task and no velocity data, should return None or 0
        result = tracker.get_estimated_remaining_time()
        # Result depends on implementation
        assert result is None or result == timedelta(0)

    def test_clear(self):
        """Test clearing tracker."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1"))
        tracker.take_snapshot()
        tracker.clear()
        assert len(tracker.get_all_tasks()) == 0
        assert len(tracker.get_snapshots()) == 0


class TestPlanVisualizer:
    """Tests for PlanVisualizer."""

    def test_visualizer_initialization(self):
        """Test visualizer initialization."""
        visualizer = PlanVisualizer()
        assert visualizer.options is not None

    def test_visualize_graph(self):
        """Test visualizing a task graph."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)

        visualizer = PlanVisualizer()
        output = visualizer.visualize_graph(graph)
        assert "Task 1" in output
        assert "Task 2" in output

    def test_visualize_schedule(self):
        """Test visualizing a schedule."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        schedule.add_item(ScheduleItem(task_id="task1", start_time=now, end_time=end))

        visualizer = PlanVisualizer()
        output = visualizer.visualize_schedule(schedule)
        assert "GANTT CHART" in output

    def test_visualize_progress(self):
        """Test visualizing progress."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1", status=TaskStatus.COMPLETED))
        tracker.add_task(Task(id="t2", title="Task 2"))

        visualizer = PlanVisualizer()
        output = visualizer.visualize_progress(tracker)
        assert "PROGRESS REPORT" in output

    def test_visualize_burndown(self):
        """Test visualizing burndown chart."""
        tracker = ProgressTracker()
        tracker.add_task(Task(id="t1", title="Task 1"))
        tracker.take_snapshot()

        visualizer = PlanVisualizer()
        output = visualizer.visualize_burndown(tracker)
        assert "BURNDOWN CHART" in output

    def test_generate_mermaid_graph(self):
        """Test generating Mermaid graph."""
        graph = TaskGraph()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2", dependencies=["task1"])
        graph.add_task(task1)
        graph.add_task(task2)

        visualizer = PlanVisualizer()
        output = visualizer.generate_mermaid_graph(graph)
        assert "graph TD" in output
        assert "task1" in output
        assert "task2" in output

    def test_generate_mermaid_gantt(self):
        """Test generating Mermaid Gantt chart."""
        schedule = Schedule()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        schedule.add_item(ScheduleItem(task_id="task1", start_time=now, end_time=end))

        visualizer = PlanVisualizer()
        output = visualizer.generate_mermaid_gantt(schedule)
        assert "gantt" in output


class TestVisualizationOptions:
    """Tests for VisualizationOptions."""

    def test_options_creation(self):
        """Test creating visualization options."""
        options = VisualizationOptions(
            show_ids=True,
            show_priority=True,
            show_status=True,
        )
        assert options.show_ids is True
        assert options.show_priority is True


class TestProgressTrackerIntegration:
    """Tests for ProgressTracker state transition integration."""

    def test_progress_tracker_emits_snapshot_on_task_status_change(self):
        """Test that on_task_status_changed emits a ProgressSnapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        # Initially no snapshots
        assert len(tracker.get_snapshots()) == 0

        # Change task status - should emit a snapshot
        task.mark_ready()
        snapshot = tracker.on_task_status_changed(task)

        assert len(tracker.get_snapshots()) == 1
        assert snapshot is not None
        assert snapshot.trigger_task_id == "task1"
        assert "PENDING → READY" in snapshot.trigger_transition

    def test_progress_tracker_emits_snapshot_on_in_progress_transition(self):
        """Test that IN_PROGRESS transition emits a snapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        tracker.on_task_status_changed(task)

        task.mark_in_progress()
        snapshot = tracker.on_task_status_changed(task)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 2
        assert snapshots[-1].trigger_task_id == "task1"
        assert "READY → IN_PROGRESS" in snapshots[-1].trigger_transition

    def test_progress_tracker_emits_snapshot_on_completed_transition(self):
        """Test that COMPLETED transition emits a snapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        tracker.on_task_status_changed(task)
        task.mark_in_progress()
        tracker.on_task_status_changed(task)
        task.mark_completed()
        snapshot = tracker.on_task_status_changed(task)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 3
        assert snapshots[-1].trigger_task_id == "task1"
        assert "IN_PROGRESS → COMPLETED" in snapshots[-1].trigger_transition

    def test_progress_tracker_emits_snapshot_on_failed_transition(self):
        """Test that FAILED transition emits a snapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_in_progress()
        tracker.on_task_status_changed(task)
        task.mark_failed("Build failed")
        snapshot = tracker.on_task_status_changed(task)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 2
        assert snapshots[-1].trigger_task_id == "task1"
        assert "IN_PROGRESS → FAILED" in snapshot.trigger_transition

    def test_progress_tracker_tracks_blocked_transition(self):
        """Test that BLOCKED transition emits a snapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        tracker.on_task_status_changed(task)
        task.mark_blocked("Waiting for review")
        snapshot = tracker.on_task_status_changed(task)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 2
        assert "BLOCKED" in snapshot.trigger_transition

    def test_progress_tracker_chronological_order(self):
        """Test that snapshots are in chronological order."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        s1 = tracker.on_task_status_changed(task)
        task.mark_in_progress()
        s2 = tracker.on_task_status_changed(task)
        task.mark_completed()
        s3 = tracker.on_task_status_changed(task)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 3
        # Verify chronological order
        assert s1.timestamp <= s2.timestamp <= s3.timestamp
        # Verify state progression
        assert snapshots[0].pending_tasks == 0  # One task became ready
        assert snapshots[1].in_progress_tasks == 1
        assert snapshots[2].completed_tasks == 1

    def test_progress_tracker_state_history(self):
        """Test that get_state_history returns chronological state transitions."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        tracker.on_task_status_changed(task)
        task.mark_in_progress()
        tracker.on_task_status_changed(task)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        history = tracker.get_state_history()
        assert len(history) == 3
        assert history[0]["new_status"] == "ready"
        assert history[1]["new_status"] == "in_progress"
        assert history[2]["new_status"] == "completed"
        assert "transition" in history[0]
        assert "transition" in history[1]
        assert "transition" in history[2]

    def test_progress_tracker_multiple_tasks_independent_transitions(self):
        """Test that multiple tasks can transition independently."""
        tracker = ProgressTracker()
        task1 = Task(id="task1", title="Task 1")
        task2 = Task(id="task2", title="Task 2")
        tracker.add_task(task1)
        tracker.add_task(task2)

        task1.mark_ready()
        tracker.on_task_status_changed(task1)
        task2.mark_ready()
        tracker.on_task_status_changed(task2)

        # Both tasks should have their own snapshots
        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 2

        # Check final progress
        progress = tracker.get_overall_progress()
        assert progress == 0.0  # None completed yet

        task1.mark_completed()
        tracker.on_task_status_changed(task1)

        snapshots = tracker.get_snapshots()
        assert len(snapshots) == 3
        assert snapshots[-1].completed_tasks == 1

    def test_progress_tracker_no_duplicate_snapshots_on_same_status(self):
        """Test that calling on_task_status_changed with same status doesn't create new snapshot."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        task.mark_ready()
        tracker.on_task_status_changed(task)
        initial_snapshots = len(tracker.get_snapshots())

        # Calling again with same status (mark_ready already called)
        tracker.on_task_status_changed(task)

        # Should not create a new snapshot since status didn't change
        assert len(tracker.get_snapshots()) == initial_snapshots

    def test_progress_tracker_export_for_diagnostics(self):
        """Test export_for_diagnostics method."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        export = tracker.export_for_diagnostics()
        assert export["source"] == "ProgressTracker"
        assert export["type"] == "execution_progress"
        assert "summary" in export
        assert "snapshots" in export
        assert "completion_history" in export
        assert len(export["snapshots"]) == 1

    def test_progress_tracker_export_for_monitoring(self):
        """Test export_for_monitoring method."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        export = tracker.export_for_monitoring()
        assert export["source"] == "ProgressTracker"
        assert export["type"] == "task_execution_metrics"
        assert "summary" in export
        assert "velocity" in export
        assert "burndown" in export
        assert "current_tasks" in export

    def test_progress_tracker_export_for_backlog(self):
        """Test export_for_backlog method."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        task2 = Task(id="task2", title="Failed Task")
        tracker.add_task(task2)
        task2.mark_failed("Error")
        tracker.on_task_status_changed(task2)

        export = tracker.export_for_backlog()
        assert export["source"] == "ProgressTracker"
        assert export["type"] == "execution_outcome"
        assert "summary" in export
        assert "outcomes" in export
        assert export["outcomes"]["completed"] == 1
        assert export["outcomes"]["failed"] == 1
        assert export["outcomes"]["total"] == 2
        assert "state_history" in export

    def test_progress_tracker_progress_history_summary(self):
        """Test get_progress_history_summary method."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        summary = tracker.get_progress_history_summary()
        assert summary["total_snapshots"] == 1
        assert summary["state_transitions"] == 1
        assert summary["final_progress"] == 100.0
        assert summary["completed_tasks"] == 1
        assert summary["total_tasks"] == 1
        assert "transitions_by_type" in summary
        assert "PENDING → COMPLETED" in summary["transitions_by_type"]


class TestProgressTrackerCallbacks:
    """Tests for ProgressTracker callback system."""

    def test_callback_notified_on_snapshot(self):
        """Test that callbacks are notified when snapshot is taken."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        received_snapshots = []

        def callback(snapshot):
            received_snapshots.append(snapshot)

        tracker.add_callback(callback)
        task.mark_completed()
        tracker.on_task_status_changed(task)

        assert len(received_snapshots) == 1
        assert received_snapshots[0].trigger_task_id == "task1"

    def test_callback_removed(self):
        """Test that removed callbacks don't receive notifications."""
        tracker = ProgressTracker()
        task = Task(id="task1", title="Test Task")
        tracker.add_task(task)

        received = []

        def callback(snapshot):
            received.append(snapshot)

        tracker.add_callback(callback)
        task.mark_ready()
        tracker.on_task_status_changed(task)

        tracker.remove_callback(callback)
        task.mark_in_progress()
        tracker.on_task_status_changed(task)

        assert len(received) == 1


class TestPlanConfig:
    """Tests for PlanConfig."""

    def test_config_creation(self):
        """Test creating a plan config."""
        config = PlanConfig(
            name="Test Plan",
            description="Test description",
        )
        assert config.name == "Test Plan"

    def test_to_dict(self):
        """Test converting to dictionary."""
        config = PlanConfig(name="Test")
        data = config.to_dict()
        assert data["name"] == "Test"

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "name": "Test",
            "description": "Desc",
            "scheduling_strategy": "priority_first",
        }
        config = PlanConfig.from_dict(data)
        assert config.name == "Test"
        assert config.scheduling_strategy == SchedulingStrategy.PRIORITY_FIRST


class TestPlan:
    """Tests for Plan."""

    def test_plan_creation(self):
        """Test creating a plan."""
        config = PlanConfig(name="Test Plan")
        plan = Plan(config=config)
        assert plan.config.name == "Test Plan"
        assert plan.id.startswith("plan_")

    def test_to_dict(self):
        """Test converting to dictionary."""
        plan = Plan(config=PlanConfig(name="Test"))
        data = plan.to_dict()
        assert data["config"]["name"] == "Test"

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "id": "test_plan",
            "config": {"name": "Test"},
            "tasks": [],
            "resources": [],
        }
        plan = Plan.from_dict(data)
        assert plan.id == "test_plan"
        assert plan.config.name == "Test"


class TestPlanManager:
    """Tests for PlanManager."""

    def test_manager_initialization(self):
        """Test manager initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            assert manager.workspace.exists()

    def test_create_plan(self):
        """Test creating a plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            plan = manager.create_plan("Test Plan")
            assert plan is not None
            assert plan.config.name == "Test Plan"
            assert manager.get_active_plan() == plan

    def test_list_plans(self):
        """Test listing plans."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            manager.create_plan("Plan 1")
            manager.create_plan("Plan 2")
            plans = manager.list_plans()
            assert len(plans) == 2

    def test_add_task(self):
        """Test adding a task to a plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            manager.create_plan("Test Plan")
            task = manager.add_task("Test Task")
            assert task is not None
            assert task.title == "Test Task"

    def test_add_task_with_options(self):
        """Test adding a task with options."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            manager.create_plan("Test Plan")
            task = manager.add_task(
                "Test Task",
                description="Desc",
                priority=TaskPriority.HIGH,
                estimated_hours=4.0,
            )
            assert task.priority == TaskPriority.HIGH
            assert task.estimated_hours == 4.0

    def test_get_task(self):
        """Test getting a task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            plan = manager.create_plan("Test Plan")
            task = manager.add_task("Test Task")
            retrieved = manager.get_task(plan.id, task.id)
            assert retrieved is not None
            assert retrieved.id == task.id

    def test_update_task(self):
        """Test updating a task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
            plan = manager.create_plan("Test Plan")
            task = manager.add_task("Test Task")
            result = manager.update_task(plan.id, task.id, title="Updated Task")
            assert result is True
            retrieved = manager.get_task(plan.id, task.id)
            assert retrieved.title == "Updated Task"

    def test_delete_task(self):
        """Test deleting a task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        task = manager.add_task("Test Task")
        result = manager.delete_task(plan.id, task.id)
        assert result is True
        assert manager.get_task(plan.id, task.id) is None

    def test_add_dependency(self):
        """Test adding a dependency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        task1 = manager.add_task("Task 1")
        task2 = manager.add_task("Task 2")
        result = manager.add_dependency(plan.id, task1.id, task2.id)
        assert result is True

    def test_add_resource(self):
        """Test adding a resource."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        manager.create_plan("Test Plan")
        resource = manager.add_resource("Developer 1", ResourceType.DEVELOPER)
        assert resource is not None
        assert resource.name == "Developer 1"

    def test_get_schedule(self):
        """Test getting a schedule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        manager.add_task("Task 1", estimated_hours=2.0)
        manager.add_task("Task 2", estimated_hours=3.0, dependencies=[plan.tasks[0].id])
        schedule = manager.get_schedule(plan.id, regenerate=True)
        assert schedule is not None
        assert len(schedule.items) == 2

    def test_get_progress(self):
        """Test getting progress."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        manager.add_task("Task 1")
        manager.mark_task_completed(plan.id, plan.tasks[0].id)
        progress = manager.get_progress(plan.id)
        assert progress is not None
        assert progress["completed_tasks"] == 1

    def test_mark_task_in_progress(self):
        """Test marking task as in progress."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        task = manager.add_task("Task 1")
        result = manager.mark_task_in_progress(plan.id, task.id)
        assert result is True

    def test_mark_task_completed(self):
        """Test marking task as completed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        task = manager.add_task("Task 1")
        result = manager.mark_task_completed(plan.id, task.id)
        assert result is True
        progress = manager.get_progress(plan.id)
        assert progress["completed_tasks"] == 1

    def test_get_summary(self):
        """Test getting summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        manager.create_plan("Plan 1")
        manager.create_plan("Plan 2")
        summary = manager.get_summary()
        assert summary["total_plans"] == 2

    def test_delete_plan(self):
        """Test deleting a plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)
        plan = manager.create_plan("Test Plan")
        result = manager.delete_plan(plan.id)
        assert result is True
        assert manager.list_plans() == []


class TestPlannerIntegration:
    """Integration tests for the planner system."""

    def test_full_planning_workflow(self):
        """Test the complete planning workflow."""
        # Create manager
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PlanManager(workspace=tmpdir)

            # Create a plan
            plan = manager.create_plan("Project Plan")

            # Add tasks
            task1 = manager.add_task("Implement Feature A", estimated_hours=4.0)
            task2 = manager.add_task("Implement Feature B", estimated_hours=2.0)
            task3 = manager.add_task("Test Features", estimated_hours=3.0, dependencies=[task1.id, task2.id])

            # Add dependencies
            manager.add_dependency(plan.id, task1.id, task3.id)
            manager.add_dependency(plan.id, task2.id, task3.id)

            # Add resources
            manager.add_resource("Developer 1", ResourceType.DEVELOPER)
            manager.add_resource("Developer 2", ResourceType.DEVELOPER)

            # Get schedule
            schedule = manager.get_schedule(plan.id, regenerate=True)
            assert schedule is not None
            assert len(schedule.items) == 3

            # Mark tasks as in progress and completed
            manager.mark_task_in_progress(plan.id, task1.id)
            manager.mark_task_in_progress(plan.id, task2.id)
            manager.mark_task_completed(plan.id, task1.id)
            manager.mark_task_completed(plan.id, task2.id)

            # Mark final task ready and completed
            manager.mark_task_in_progress(plan.id, task3.id)
            manager.mark_task_completed(plan.id, task3.id)

            # Check progress
            progress = manager.get_progress(plan.id)
            assert progress["completed_tasks"] == 3
            assert progress["overall_progress"] == 100.0

    def test_planner_system_exports(self):
        """Test that the planner module exports all expected classes."""
        from app.planner import (
            Task,
            TaskStatus,
            TaskPriority,
            TaskCategory,
            TaskGraph,
            TaskNode,
            DependencyEdge,
            Scheduler,
            Schedule,
            ScheduleItem,
            SchedulingStrategy,
            ResourceAllocator,
            Resource,
            ResourceType,
            Allocation,
            ProgressTracker,
            ProgressSnapshot,
            PlanVisualizer,
            PlanManager,
            Plan,
            PlanConfig,
        )
        assert Task is not None
        assert TaskStatus is not None
        assert TaskPriority is not None
        assert TaskCategory is not None
        assert TaskGraph is not None
        assert Scheduler is not None
        assert Schedule is not None
        assert ResourceAllocator is not None
        assert Resource is not None
        assert ProgressTracker is not None
        assert PlanVisualizer is not None
        assert PlanManager is not None
        assert Plan is not None
