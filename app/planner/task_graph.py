"""Task Graph for representing dependencies between tasks.

This module provides graph structures for representing task dependencies
and performing graph operations like topological sorting.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict, deque

from app.planner.task import Task, TaskStatus


@dataclass
class TaskNode:
    """Node in a task graph."""
    task: Task
    children: List[str] = field(default_factory=list)  # Task IDs
    parents: List[str] = field(default_factory=list)  # Task IDs

    @property
    def task_id(self) -> str:
        return self.task.id


@dataclass
class DependencyEdge:
    """Edge in a task graph representing a dependency."""
    from_task_id: str
    to_task_id: str

    def __hash__(self) -> int:
        return hash((self.from_task_id, self.to_task_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DependencyEdge):
            return False
        return (self.from_task_id == other.from_task_id and
                self.to_task_id == other.to_task_id)


class CycleDetectedError(Exception):
    """Exception raised when a cycle is detected in the task graph."""
    pass


class TaskGraph:
    """Directed acyclic graph for representing task dependencies.

    This class provides operations for managing task dependencies,
    detecting cycles, and performing topological sorting.
    """

    def __init__(self):
        """Initialize the task graph."""
        # Task ID -> TaskNode
        self._nodes: Dict[str, TaskNode] = {}

        # Task ID -> Set of dependent task IDs
        self._dependencies: Dict[str, Set[str]] = defaultdict(set)

        # Task ID -> Set of tasks that depend on it
        self._dependents: Dict[str, Set[str]] = defaultdict(set)

        # All edges
        self._edges: Set[DependencyEdge] = set()

    def add_task(self, task: Task) -> None:
        """Add a task to the graph."""
        if task.id in self._nodes:
            # Update existing task
            self._nodes[task.id].task = task
            # Update dependencies
            self._dependencies[task.id] = set(task.dependencies)
        else:
            # Add new task
            self._nodes[task.id] = TaskNode(task=task)
            self._dependencies[task.id] = set(task.dependencies)

        # Ensure dependents dict has entries for all dependencies
        for dep_id in task.dependencies:
            if dep_id not in self._nodes:
                # Dependency task doesn't exist in graph yet - skip edge creation
                # The edge will be created when the dependency is added or via add_dependency
                continue
            self._dependents[dep_id].add(task.id)
            self._edges.add(DependencyEdge(from_task_id=dep_id, to_task_id=task.id))

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the graph."""
        if task_id not in self._nodes:
            return False

        # Remove all edges from and to this task
        deps = self._dependencies.get(task_id, set())
        dependents = self._dependents.get(task_id, set())

        for dep_id in deps:
            if dep_id in self._dependents:
                self._dependents[dep_id].discard(task_id)
            self._edges.discard(DependencyEdge(from_task_id=dep_id, to_task_id=task_id))

        for dep_id in dependents:
            if dep_id in self._dependencies:
                self._dependencies[dep_id].discard(task_id)
            self._edges.discard(DependencyEdge(from_task_id=task_id, to_task_id=dep_id))

        del self._nodes[task_id]
        if task_id in self._dependencies:
            del self._dependencies[task_id]
        if task_id in self._dependents:
            del self._dependents[task_id]

        return True

    def add_dependency(self, from_task_id: str, to_task_id: str) -> bool:
        """Add a dependency between two tasks.

        Args:
            from_task_id: The task that must be completed first
            to_task_id: The task that depends on from_task_id

        Returns:
            True if dependency was added successfully
        """
        if from_task_id not in self._nodes or to_task_id not in self._nodes:
            return False

        # Check for cycle
        if self._would_create_cycle(from_task_id, to_task_id):
            raise CycleDetectedError(
                f"Adding dependency from {from_task_id} to {to_task_id} would create a cycle"
            )

        self._dependencies[to_task_id].add(from_task_id)
        self._dependents[from_task_id].add(to_task_id)
        self._edges.add(DependencyEdge(from_task_id=from_task_id, to_task_id=to_task_id))

        return True

    def remove_dependency(self, from_task_id: str, to_task_id: str) -> bool:
        """Remove a dependency between two tasks."""
        if from_task_id not in self._dependencies[to_task_id]:
            return False

        self._dependencies[to_task_id].discard(from_task_id)
        self._dependents[from_task_id].discard(to_task_id)
        self._edges.discard(DependencyEdge(from_task_id=from_task_id, to_task_id=to_task_id))

        return True

    def _would_create_cycle(self, from_task_id: str, to_task_id: str) -> bool:
        """Check if adding a dependency would create a cycle.

        Adding from_task_id -> to_task_id means to_task_id depends on from_task_id.
        In the dependency graph, this adds an edge to_task_id -> from_task_id
        (because _dependencies[task] = set of tasks it depends on).

        This creates a cycle if there's already a path from from_task_id to to_task_id
        via the dependency graph. Because then we'd have:
        - from_task_id -> ... -> to_task_id (existing path)
        - to_task_id -> from_task_id (new edge)
        - Combined: from_task_id -> ... -> to_task_id -> from_task_id = cycle!
        """
        # Check if from_task_id can reach to_task_id via the dependency graph
        visited = set()
        stack = [from_task_id]
        while stack:
            node = stack.pop()
            if node == to_task_id:
                return True
            if node in visited:
                continue
            visited.add(node)
            # Follow dependencies (tasks that this node depends on)
            for dep in self._dependencies.get(node, set()):
                stack.append(dep)
        return False

    def has_cycle(self) -> bool:
        """Check if the graph contains any cycles."""
        try:
            self.topological_sort()
            return False
        except CycleDetectedError:
            return True

    def detect_cycles(self) -> List[List[str]]:
        """Detect all cycles in the graph.

        Returns:
            List of cycles, where each cycle is a list of task IDs.
        """
        cycles = []
        visited = set()
        on_stack = set()
        parent = {}

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            on_stack.add(node)
            path.append(node)

            for dep in self._dependencies.get(node, set()):
                if dep not in visited:
                    parent[dep] = node
                    dfs(dep, path)
                elif dep in on_stack:
                    # Found a cycle
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:]
                    cycles.append(cycle)

            path.pop()
            on_stack.discard(node)

        for node in self._nodes:
            if node not in visited:
                dfs(node, [])

        return cycles

    def get_roots(self) -> List[str]:
        """Get tasks with no dependencies (root tasks)."""
        return [task_id for task_id, deps in self._dependencies.items() if not deps]

    def get_leaves(self) -> List[str]:
        """Get tasks with no dependents (leaf tasks)."""
        # A task is a leaf if it's not a key in _dependents or its dependents set is empty
        all_tasks = set(self._nodes.keys())
        tasks_with_dependents = set(self._dependents.keys())
        leaves = []
        for task_id in all_tasks:
            if task_id not in tasks_with_dependents or not self._dependents[task_id]:
                leaves.append(task_id)
        return leaves

    def get_all_dependencies(self, task_id: str) -> Set[str]:
        """Get all transitive dependencies for a task."""
        visited = set()
        stack = list(self._dependencies.get(task_id, set()))

        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for dep in self._dependencies.get(node, set()):
                stack.append(dep)

        return visited

    def get_dependents(self, task_id: str) -> Set[str]:
        """Get all tasks that directly depend on this task."""
        return self._dependents.get(task_id, set())

    def get_all_dependents(self, task_id: str) -> Set[str]:
        """Get all transitive dependents for a task."""
        visited = set()
        stack = list(self._dependents.get(task_id, set()))

        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for dep in self._dependents.get(node, set()):
                stack.append(dep)

        return visited

    def topological_sort(self) -> List[str]:
        """Perform topological sort on the graph.

        Returns:
            List of task IDs in topological order.

        Raises:
            CycleDetectedError: If the graph contains a cycle.
        """
        # Kahn's algorithm
        in_degree = defaultdict(int)
        for node in self._nodes:
            in_degree[node] = len(self._dependencies.get(node, set()))

        queue = deque([node for node in self._nodes if in_degree[node] == 0])
        sorted_nodes = []

        while queue:
            node = queue.popleft()
            sorted_nodes.append(node)

            for dependent in self._dependents.get(node, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(sorted_nodes) != len(self._nodes):
            raise CycleDetectedError("Graph contains a cycle")

        return sorted_nodes

    def get_critical_path(self) -> List[str]:
        """Get the critical path (longest path through the graph).

        This gives the sequence of tasks that determines the minimum
        project duration.
        """
        # Simple implementation: find the longest path using topological sort
        try:
            topo_order = self.topological_sort()
        except CycleDetectedError:
            return []

        # Calculate longest path to each node
        longest_path = {node: 0 for node in self._nodes}
        predecessor = {node: None for node in self._nodes}

        for node in topo_order:
            for dep in self._dependencies.get(node, set()):
                if longest_path[dep] + 1 > longest_path[node]:
                    longest_path[node] = longest_path[dep] + 1
                    predecessor[node] = dep

        # Find the end of the longest path
        max_length = max(longest_path.values())
        end_node = [n for n, l in longest_path.items() if l == max_length][0]

        # Trace back the path
        path = []
        current = end_node
        while current is not None:
            path.append(current)
            current = predecessor.get(current)

        return list(reversed(path))

    def get_parallel_tasks(self) -> List[Set[str]]:
        """Get levels of tasks that can be executed in parallel.

        Returns:
            List of sets, where each set contains tasks that can run in parallel.
        """
        try:
            topo_order = self.topological_sort()
        except CycleDetectedError:
            return []

        in_degree = defaultdict(int)
        for node in self._nodes:
            in_degree[node] = len(self._dependencies.get(node, set()))

        levels = []
        current_level = set()

        for node in topo_order:
            if in_degree[node] == 0:
                current_level.add(node)

            # Check if all dependencies of dependent nodes are met
            all_deps_met = True
            for dependent in self._dependents.get(node, set()):
                if in_degree[dependent] > 0:
                    all_deps_met = False
                    break

        # Group tasks by their longest path distance from roots
        # Tasks at the same distance can be executed in parallel
        longest_path = {node: 0 for node in self._nodes}

        for node in topo_order:
            for dep in self._dependencies.get(node, set()):
                if longest_path[dep] + 1 > longest_path[node]:
                    longest_path[node] = longest_path[dep] + 1

        # Group by level
        levels_dict = defaultdict(set)
        for node, level in longest_path.items():
            levels_dict[level].add(node)

        # Return as list of sets in order
        return [level_set for _, level_set in sorted(levels_dict.items())]

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        node = self._nodes.get(task_id)
        return node.task if node else None

    def get_all_tasks(self) -> List[Task]:
        """Get all tasks in the graph."""
        return [node.task for node in self._nodes.values()]

    def get_edges(self) -> Set[DependencyEdge]:
        """Get all edges in the graph."""
        return set(self._edges)

    def count_tasks(self) -> int:
        """Count the number of tasks in the graph."""
        return len(self._nodes)

    def count_edges(self) -> int:
        """Count the number of dependencies in the graph."""
        return len(self._edges)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the graph to a dictionary."""
        return {
            "tasks": [task.to_dict() for task in self.get_all_tasks()],
            "dependencies": [
                {"from": e.from_task_id, "to": e.to_task_id}
                for e in self._edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskGraph":
        """Create a graph from a dictionary."""
        graph = cls()

        # First, add all tasks
        for task_data in data.get("tasks", []):
            task = Task.from_dict(task_data)
            graph.add_task(task)

        # Then add dependencies
        for dep_data in data.get("dependencies", []):
            graph.add_dependency(dep_data["from"], dep_data["to"])

        return graph

    def visualize(self) -> str:
        """Generate a simple text visualization of the graph."""
        lines = []
        try:
            topo_order = self.topological_sort()
        except CycleDetectedError:
            lines.append("Graph has cycles - cannot visualize")
            return "\n".join(lines)

        for task_id in topo_order:
            task = self.get_task(task_id)
            if task:
                deps = self._dependencies.get(task_id, set())
                dep_str = ", ".join(deps) if deps else "None"
                lines.append(f"{task.title} (ID: {task.id})")
                lines.append(f"  Dependencies: {dep_str}")
                lines.append(f"  Status: {task.status.value}")
                lines.append("")

        return "\n".join(lines)
