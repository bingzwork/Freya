"""Duration Estimation System for intelligent task execution time prediction.

This module provides:
- Task-type aware duration estimation
- Complexity-aware estimates
- Historical learning from actual execution times
- Confidence scoring
- Integration with planner scheduler and resource allocator
- Refinement after execution
"""

import json
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple, Callable
from collections import defaultdict
from pathlib import Path

from app.planner.task import Task, TaskCategory, TaskPriority
from app.planner.resource_allocator import ResourceType

# Try to import from goals for integration
try:
    from app.memory.goals.models import DurationEstimate, TaskType, GoalComplexity, ComplexityLevel
    GOALS_AVAILABLE = True
except ImportError:
    GOALS_AVAILABLE = False
    # Define minimal local types
    from enum import Enum

    class TaskType(Enum):
        IMPLEMENTATION = "implementation"
        RESEARCH = "research"
        DEBUGGING = "debugging"
        DOCUMENTATION = "documentation"
        TESTING = "testing"
        REFACTORING = "refactoring"
        INTEGRATION = "integration"
        DEPLOYMENT = "deployment"
        MAINTENANCE = "maintenance"
        UNKNOWN = "unknown"

    class ComplexityLevel(Enum):
        TRIVIAL = "trivial"
        SIMPLE = "simple"
        MODERATE = "moderate"
        COMPLEX = "complex"
        VERY_COMPLEX = "very_complex"


@dataclass
class DurationEstimationConfig:
    """Configuration for duration estimation."""
    # Base hours per task category (historical averages)
    BASE_HOURS_BY_CATEGORY: Dict[TaskCategory, float] = field(default_factory=lambda: {
        TaskCategory.IMPLEMENTATION: 4.0,
        TaskCategory.TESTING: 2.0,
        TaskCategory.DOCUMENTATION: 1.5,
        TaskCategory.REVIEW: 1.0,
        TaskCategory.REFACTORING: 3.0,
        TaskCategory.BUG_FIX: 2.5,
        TaskCategory.FEATURE: 5.0,
        TaskCategory.MAINTENANCE: 1.5,
        TaskCategory.RESEARCH: 3.0,
        TaskCategory.OTHER: 2.0,
    })

    # Multipliers by priority
    PRIORITY_MULTIPLIERS: Dict[TaskPriority, float] = field(default_factory=lambda: {
        TaskPriority.CRITICAL: 0.7,   # Rush job - less thorough
        TaskPriority.HIGH: 0.85,
        TaskPriority.MEDIUM: 1.0,
        TaskPriority.LOW: 1.2,        # More thorough when time permits
    })

    # Complexity multipliers
    COMPLEXITY_MULTIPLIERS: Dict[ComplexityLevel, float] = field(default_factory=lambda: {
        ComplexityLevel.TRIVIAL: 0.25,
        ComplexityLevel.SIMPLE: 0.5,
        ComplexityLevel.MODERATE: 1.0,
        ComplexityLevel.COMPLEX: 2.0,
        ComplexityLevel.VERY_COMPLEX: 4.0,
    })

    # Resource constraint multipliers
    RESOURCE_CONSTRAINT_MULTIPLIER = 1.5  # When resources are constrained

    # Confidence base
    BASE_CONFIDENCE: float = 0.5
    MAX_CONFIDENCE: float = 0.95
    CONFIDENCE_PER_HISTORICAL_POINT: float = 0.1

    # Historical data
    MIN_HISTORICAL_SAMPLES: int = 3
    HISTORICAL_WEIGHT: float = 0.3  # Weight of historical vs model

    # Storage
    STORAGE_PATH: str = "data/planner/duration_history.json"


class DurationEstimator:
    """Intelligent duration estimation with historical learning."""

    def __init__(
        self,
        config: Optional[DurationEstimationConfig] = None,
        storage_path: Optional[str] = None,
    ):
        self.config = config or DurationEstimationConfig()
        if storage_path:
            self.config.STORAGE_PATH = storage_path
        self.storage_path = Path(self.config.STORAGE_PATH)
        self._historical_data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._load_history()

    def _load_history(self) -> None:
        """Load historical execution data from disk."""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, entries in data.items():
                    self._historical_data[key] = entries
        except Exception:
            pass

    def _save_history(self) -> None:
        """Save historical execution data to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(dict(self._historical_data), f, indent=2)
        except Exception:
            pass

    def _get_history_key(self, category: TaskCategory, complexity: ComplexityLevel) -> str:
        """Generate a key for historical data lookup."""
        return f"{category.value}_{complexity.value}"

    def estimate_task_duration(
        self,
        task: Task,
        complexity: Optional[ComplexityLevel] = None,
        resource_constraints: Optional[Dict[ResourceType, float]] = None,
    ) -> "DurationEstimate":
        """Estimate duration for a planner Task.

        Args:
            task: The task to estimate
            complexity: Optional complexity level (inferred from task if not provided)
            resource_constraints: Optional dict of resource type -> available fraction (0-1)

        Returns:
            DurationEstimate with estimated_seconds, min/max, confidence
        """
        # Determine task type
        task_type = self._map_category_to_task_type(task.category)

        # Determine complexity
        if complexity is None:
            complexity = self._infer_complexity(task)

        # Get base hours for category
        base_hours = self.config.BASE_HOURS_BY_CATEGORY.get(task.category, 2.0)

        # Apply priority multiplier
        priority_mult = self.config.PRIORITY_MULTIPLIERS.get(task.priority, 1.0)

        # Apply complexity multiplier
        complexity_mult = self.config.COMPLEXITY_MULTIPLIERS.get(complexity, 1.0)

        # Check resource constraints
        resource_mult = 1.0
        if resource_constraints:
            for rtype, available in resource_constraints.items():
                if available < 0.5:  # Less than 50% available
                    resource_mult *= self.config.RESOURCE_CONSTRAINT_MULTIPLIER

        # Check historical data
        history_key = self._get_history_key(task.category, complexity)
        historical_entries = self._historical_data.get(history_key, [])

        if len(historical_entries) >= self.config.MIN_HISTORICAL_SAMPLES:
            # Use historical data
            historical_hours = statistics.mean([e["actual_hours"] for e in historical_entries])
            model_hours = base_hours * priority_mult * complexity_mult * resource_mult
            estimated_hours = (
                (1 - self.config.HISTORICAL_WEIGHT) * model_hours +
                self.config.HISTORICAL_WEIGHT * historical_hours
            )
            source = "historical"
            confidence = min(
                self.config.MAX_CONFIDENCE,
                self.config.BASE_CONFIDENCE +
                self.config.CONFIDENCE_PER_HISTORICAL_POINT * len(historical_entries)
            )
        else:
            # Use model only
            estimated_hours = base_hours * priority_mult * complexity_mult * resource_mult
            source = "model"
            confidence = self.config.BASE_CONFIDENCE

        # Calculate min/max (optimistic/pessimistic)
        # Min: 70% of estimate for historical, 50% for model
        # Max: 150% of estimate for historical, 200% for model
        if source == "historical":
            min_hours = estimated_hours * 0.7
            max_hours = estimated_hours * 1.5
        else:
            min_hours = estimated_hours * 0.5
            max_hours = estimated_hours * 2.0

        # Convert to seconds
        estimated_seconds = estimated_hours * 3600
        min_seconds = min_hours * 3600
        max_seconds = max_hours * 3600

        # Use Goals DurationEstimate if available, otherwise create local
        if GOALS_AVAILABLE:
            return DurationEstimate(
                estimated_seconds=estimated_seconds,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                confidence=confidence,
                task_type=task_type,
                complexity_score=self._complexity_to_score(complexity),
                source=source,
                refinable=True,
                last_updated=datetime.now(timezone.utc).isoformat(),
                metadata={
                    "task_id": task.id,
                    "task_title": task.title,
                    "category": task.category.value,
                    "priority": task.priority.value,
                    "complexity": complexity.value,
                    "base_hours": base_hours,
                    "priority_mult": priority_mult,
                    "complexity_mult": complexity_mult,
                    "resource_mult": resource_mult,
                    "historical_samples": len(historical_entries),
                }
            )
        else:
            return {
                "estimated_seconds": estimated_seconds,
                "min_seconds": min_seconds,
                "max_seconds": max_seconds,
                "confidence": confidence,
                "task_type": task_type.value,
                "complexity_score": self._complexity_to_score(complexity),
                "source": source,
                "refinable": True,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "task_id": task.id,
                    "task_title": task.title,
                    "category": task.category.value,
                    "priority": task.priority.value,
                    "complexity": complexity.value,
                    "base_hours": base_hours,
                    "priority_mult": priority_mult,
                    "complexity_mult": complexity_mult,
                    "resource_mult": resource_mult,
                    "historical_samples": len(historical_entries),
                }
            }

    def estimate_goal_duration(
        self,
        goal_id: str,
        goal_name: str,
        goal_description: str,
        task_type: TaskType,
        complexity: ComplexityLevel,
        existing_subtasks: Optional[int] = None,
    ) -> "DurationEstimate":
        """Estimate duration for a goal based on its decomposition."""
        # Base hours by task type
        base_by_type = {
            TaskType.IMPLEMENTATION: 8.0,
            TaskType.RESEARCH: 4.0,
            TaskType.DEBUGGING: 3.0,
            TaskType.DOCUMENTATION: 2.0,
            TaskType.TESTING: 3.0,
            TaskType.REFACTORING: 5.0,
            TaskType.INTEGRATION: 6.0,
            TaskType.DEPLOYMENT: 2.0,
            TaskType.MAINTENANCE: 1.5,
            TaskType.UNKNOWN: 3.0,
        }

        base_hours = base_by_type.get(task_type, 4.0)
        complexity_mult = self.config.COMPLEXITY_MULTIPLIERS.get(complexity, 1.0)

        # Adjust for existing subtasks (already partially decomposed)
        if existing_subtasks and existing_subtasks > 0:
            # More subtasks = more work, but decomposition helps
            subtask_factor = 1.0 + (existing_subtasks * 0.1)
        else:
            subtask_factor = 1.0

        estimated_hours = base_hours * complexity_mult * subtask_factor

        # Confidence based on how well we know the task type
        confidence = self.config.BASE_CONFIDENCE
        if task_type != TaskType.UNKNOWN:
            confidence += 0.1
        if existing_subtasks and existing_subtasks > 3:
            confidence += 0.1

        min_hours = estimated_hours * 0.5
        max_hours = estimated_hours * 2.0

        if GOALS_AVAILABLE:
            return DurationEstimate(
                estimated_seconds=estimated_hours * 3600,
                min_seconds=min_hours * 3600,
                max_seconds=max_hours * 3600,
                confidence=min(confidence, self.config.MAX_CONFIDENCE),
                task_type=task_type,
                complexity_score=self._complexity_to_score(complexity),
                source="goal_model",
                refinable=True,
                last_updated=datetime.now(timezone.utc).isoformat(),
                metadata={
                    "goal_id": goal_id,
                    "goal_name": goal_name,
                    "subtask_count": existing_subtasks or 0,
                }
            )
        else:
            return {
                "estimated_seconds": estimated_hours * 3600,
                "min_seconds": min_hours * 3600,
                "max_seconds": max_hours * 3600,
                "confidence": min(confidence, self.config.MAX_CONFIDENCE),
                "task_type": task_type.value,
                "complexity_score": self._complexity_to_score(complexity),
                "source": "goal_model",
                "refinable": True,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "goal_id": goal_id,
                    "goal_name": goal_name,
                    "subtask_count": existing_subtasks or 0,
                }
            }

    def _map_category_to_task_type(self, category: TaskCategory) -> TaskType:
        """Map planner TaskCategory to goals TaskType."""
        mapping = {
            TaskCategory.IMPLEMENTATION: TaskType.IMPLEMENTATION,
            TaskCategory.TESTING: TaskType.TESTING,
            TaskCategory.DOCUMENTATION: TaskType.DOCUMENTATION,
            TaskCategory.REVIEW: TaskType.MAINTENANCE,
            TaskCategory.REFACTORING: TaskType.REFACTORING,
            TaskCategory.BUG_FIX: TaskType.DEBUGGING,
            TaskCategory.FEATURE: TaskType.IMPLEMENTATION,
            TaskCategory.MAINTENANCE: TaskType.MAINTENANCE,
            TaskCategory.RESEARCH: TaskType.RESEARCH,
            TaskCategory.OTHER: TaskType.UNKNOWN,
        }
        return mapping.get(category, TaskType.UNKNOWN)

    def _infer_complexity(self, task: Task) -> ComplexityLevel:
        """Infer complexity from task properties."""
        # Base on estimated_hours if set
        if task.estimated_hours > 0:
            if task.estimated_hours <= 0.5:
                return ComplexityLevel.TRIVIAL
            elif task.estimated_hours <= 1.5:
                return ComplexityLevel.SIMPLE
            elif task.estimated_hours <= 4.0:
                return ComplexityLevel.MODERATE
            elif task.estimated_hours <= 10.0:
                return ComplexityLevel.COMPLEX
            else:
                return ComplexityLevel.VERY_COMPLEX

        # Infer from title/description keywords
        text = f"{task.title} {task.description}".lower()

        complex_keywords = ["refactor", "architect", "system", "pipeline", "framework",
                           "distributed", "scalable", "migration", "integration"]
        moderate_keywords = ["implement", "create", "build", "develop", "feature",
                            "test", "debug", "fix", "optimize"]

        complex_count = sum(1 for kw in complex_keywords if kw in text)
        moderate_count = sum(1 for kw in moderate_keywords if kw in text)

        if complex_count >= 2:
            return ComplexityLevel.COMPLEX
        elif complex_count >= 1 or moderate_count >= 2:
            return ComplexityLevel.MODERATE
        elif moderate_count >= 1:
            return ComplexityLevel.SIMPLE
        else:
            return ComplexityLevel.TRIVIAL

    def _complexity_to_score(self, complexity: ComplexityLevel) -> float:
        """Convert complexity level to numeric score 0-1."""
        mapping = {
            ComplexityLevel.TRIVIAL: 0.05,
            ComplexityLevel.SIMPLE: 0.2,
            ComplexityLevel.MODERATE: 0.45,
            ComplexityLevel.COMPLEX: 0.75,
            ComplexityLevel.VERY_COMPLEX: 0.95,
        }
        return mapping.get(complexity, 0.5)

    def record_actual_duration(
        self,
        task: Task,
        actual_seconds: float,
    ) -> "DurationEstimate":
        """Record actual duration and update historical data.

        Args:
            task: The completed task
            actual_seconds: Actual time taken in seconds

        Returns:
            Updated DurationEstimate
        """
        actual_hours = actual_seconds / 3600

        # Get current estimate
        if hasattr(task, 'duration_estimate') and task.duration_estimate:
            current_estimate = task.duration_estimate
            if GOALS_AVAILABLE:
                updated = current_estimate.apply_historical_actual(actual_seconds)
            else:
                # Manual update
                metadata = current_estimate.get("metadata", {})
                update_count = metadata.get("update_count", 0) + 1
                alpha = 0.3 if update_count > 1 else 0.3

                old_est = current_estimate["estimated_seconds"]
                new_est = (1 - alpha) * old_est + alpha * actual_seconds
                new_min = min(current_estimate.get("min_seconds", actual_seconds * 0.8), actual_seconds * 0.8)
                new_max = max(current_estimate.get("max_seconds", actual_seconds * 1.5), actual_seconds * 1.5)
                confidence = min(self.config.MAX_CONFIDENCE,
                               self.config.BASE_CONFIDENCE + 0.1 * update_count)

                updated = {
                    **current_estimate,
                    "estimated_seconds": new_est,
                    "min_seconds": new_min,
                    "max_seconds": new_max,
                    "confidence": confidence,
                    "source": "historical",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "metadata": {
                        **metadata,
                        "update_count": update_count,
                        "last_actual_hours": actual_hours,
                    }
                }
        else:
            # No previous estimate
            complexity = self._infer_complexity(task)
            history_key = self._get_history_key(task.category, complexity)
            historical_entries = self._historical_data.get(history_key, [])

            # Use the most recent estimate from similar tasks
            if historical_entries:
                estimated_hours = statistics.mean([e["actual_hours"] for e in historical_entries])
                source = "historical"
                confidence = min(self.config.MAX_CONFIDENCE,
                               self.config.BASE_CONFIDENCE +
                               self.config.CONFIDENCE_PER_HISTORICAL_POINT * len(historical_entries))
            else:
                estimated_hours = actual_hours
                source = "single_observation"
                confidence = self.config.BASE_CONFIDENCE

            if GOALS_AVAILABLE:
                updated = DurationEstimate(
                    estimated_seconds=estimated_hours * 3600,
                    min_seconds=estimated_hours * 3600 * 0.7,
                    max_seconds=estimated_hours * 3600 * 1.5,
                    confidence=confidence,
                    task_type=self._map_category_to_task_type(task.category),
                    complexity_score=self._complexity_to_score(complexity),
                    source=source,
                    refinable=True,
                    last_updated=datetime.now(timezone.utc).isoformat(),
                    metadata={"update_count": 1, "last_actual_hours": actual_hours}
                )
            else:
                updated = {
                    "estimated_seconds": estimated_hours * 3600,
                    "min_seconds": estimated_hours * 3600 * 0.7,
                    "max_seconds": estimated_hours * 3600 * 1.5,
                    "confidence": confidence,
                    "task_type": self._map_category_to_task_type(task.category).value,
                    "complexity_score": self._complexity_to_score(complexity),
                    "source": source,
                    "refinable": True,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "metadata": {"update_count": 1, "last_actual_hours": actual_hours}
                }

        # Store in historical data
        history_key = self._get_history_key(task.category, self._infer_complexity(task))
        entry = {
            "task_id": task.id,
            "task_title": task.title,
            "actual_hours": actual_hours,
            "actual_seconds": actual_seconds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": task.category.value,
            "priority": task.priority.value,
            "complexity": self._infer_complexity(task).value,
        }
        self._historical_data[history_key].append(entry)

        # Keep only recent history (last 100 entries per key)
        if len(self._historical_data[history_key]) > 100:
            self._historical_data[history_key] = self._historical_data[history_key][-100:]

        self._save_history()

        return updated

    def get_historical_stats(
        self,
        category: Optional[TaskCategory] = None,
        complexity: Optional[ComplexityLevel] = None,
    ) -> Dict[str, Any]:
        """Get statistics from historical data."""
        stats = {}

        if category and complexity:
            key = self._get_history_key(category, complexity)
            entries = self._historical_data.get(key, [])
            if entries:
                hours = [e["actual_hours"] for e in entries]
                stats[key] = {
                    "count": len(hours),
                    "mean_hours": statistics.mean(hours),
                    "median_hours": statistics.median(hours),
                    "stdev_hours": statistics.stdev(hours) if len(hours) > 1 else 0,
                    "min_hours": min(hours),
                    "max_hours": max(hours),
                }
        else:
            # Aggregate across all
            all_hours = []
            for entries in self._historical_data.values():
                all_hours.extend([e["actual_hours"] for e in entries])

            if all_hours:
                stats["overall"] = {
                    "total_samples": len(all_hours),
                    "mean_hours": statistics.mean(all_hours),
                    "median_hours": statistics.median(all_hours),
                    "stdev_hours": statistics.stdev(all_hours) if len(all_hours) > 1 else 0,
                    "by_category": {},
                }
                for cat in TaskCategory:
                    cat_hours = [e["actual_hours"] for entries in self._historical_data.values()
                                for e in entries if e.get("category") == cat.value]
                    if cat_hours:
                        stats["overall"]["by_category"][cat.value] = {
                            "count": len(cat_hours),
                            "mean_hours": statistics.mean(cat_hours),
                        }

        return stats

    def clear_history(self, category: Optional[TaskCategory] = None,
                      complexity: Optional[ComplexityLevel] = None) -> int:
        """Clear historical data, optionally filtered."""
        if category and complexity:
            key = self._get_history_key(category, complexity)
            count = len(self._historical_data.get(key, []))
            self._historical_data.pop(key, None)
            self._save_history()
            return count
        else:
            total = sum(len(v) for v in self._historical_data.values())
            self._historical_data.clear()
            self._save_history()
            return total


class PlanDurationEstimator:
    """Estimate total plan duration including dependencies and resource constraints."""

    def __init__(self, duration_estimator: DurationEstimator):
        self.estimator = duration_estimator

    def estimate_plan_duration(
        self,
        tasks: List[Task],
        resource_constraints: Optional[Dict[ResourceType, float]] = None,
    ) -> Dict[str, Any]:
        """Estimate total plan duration considering dependencies and parallelism."""
        if not tasks:
            return {
                "total_estimated_seconds": 0,
                "critical_path_seconds": 0,
                "total_estimated_hours": 0,
                "critical_path_hours": 0,
                "confidence": 0.5,
                "task_estimates": [],
            }

        # Estimate each task
        task_estimates = []
        for task in tasks:
            estimate = self.estimator.estimate_task_duration(task, resource_constraints=resource_constraints)
            task_estimates.append({
                "task_id": task.id,
                "task_title": task.title,
                "estimate": estimate,
            })

        # Calculate critical path duration
        # Build dependency graph
        task_by_id = {t.id: t for t in tasks}
        estimate_by_id = {te["task_id"]: te["estimate"] for te in task_estimates}

        # Topological sort to find critical path
        from collections import defaultdict, deque

        # Build adjacency
        adj = defaultdict(list)
        in_degree = defaultdict(int)

        for task in tasks:
            in_degree[task.id] = len(task.dependencies)
            for dep_id in task.dependencies:
                adj[dep_id].append(task.id)

        # Kahn's algorithm for topological order
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        topo_order = []

        while queue:
            current = queue.popleft()
            topo_order.append(current)
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Handle any remaining (cycles)
        remaining = [tid for tid in task_by_id if tid not in topo_order]
        topo_order.extend(remaining)

        # Forward pass: earliest start/finish
        earliest_start = {}
        earliest_finish = {}

        for task_id in topo_order:
            task = task_by_id[task_id]
            estimate = estimate_by_id.get(task_id)

            if estimate:
                if GOALS_AVAILABLE:
                    duration = estimate.estimated_seconds
                else:
                    duration = estimate.get("estimated_seconds", 0)
            else:
                duration = task.estimated_hours * 3600 if task.estimated_hours else 0

            if task.dependencies:
                start = max(earliest_finish.get(dep, 0) for dep in task.dependencies)
            else:
                start = 0

            earliest_start[task_id] = start
            earliest_finish[task_id] = start + duration

        # Critical path is max of earliest_finish
        critical_path_seconds = max(earliest_finish.values()) if earliest_finish else 0

        # Total sequential (if no parallelism)
        total_seconds = sum(
            (te["estimate"].estimated_seconds if GOALS_AVAILABLE
             else te["estimate"].get("estimated_seconds", 0))
            for te in task_estimates
        )

        # Overall confidence = average of task confidences
        confidences = [
            te["estimate"].confidence if GOALS_AVAILABLE
            else te["estimate"].get("confidence", 0.5)
            for te in task_estimates
        ]
        avg_confidence = statistics.mean(confidences) if confidences else 0.5

        return {
            "total_estimated_seconds": total_seconds,
            "critical_path_seconds": critical_path_seconds,
            "total_estimated_hours": round(total_seconds / 3600, 1),
            "critical_path_hours": round(critical_path_seconds / 3600, 1),
            "confidence": round(avg_confidence, 2),
            "task_estimates": task_estimates,
            "earliest_start": earliest_start,
            "earliest_finish": earliest_finish,
        }


# Convenience function for quick estimation
def quick_estimate(
    task_title: str,
    category: str = "implementation",
    priority: str = "medium",
    complexity: str = "moderate",
) -> Dict[str, Any]:
    """Quick duration estimate without full setup."""
    estimator = DurationEstimator()

    # Create a dummy task
    task = Task(
        title=task_title,
        category=TaskCategory(category),
        priority=TaskPriority(priority),
    )

    comp = ComplexityLevel(complexity)
    estimate = estimator.estimate_task_duration(task, complexity=comp)

    if GOALS_AVAILABLE:
        return {
            "estimated_hours": round(estimate.estimated_seconds / 3600, 1),
            "min_hours": round(estimate.min_seconds / 3600, 1),
            "max_hours": round(estimate.max_seconds / 3600, 1),
            "confidence": estimate.confidence,
            "source": estimate.source,
        }
    else:
        return {
            "estimated_hours": round(estimate["estimated_seconds"] / 3600, 1),
            "min_hours": round(estimate["min_seconds"] / 3600, 1),
            "max_hours": round(estimate["max_seconds"] / 3600, 1),
            "confidence": estimate["confidence"],
            "source": estimate["source"],
        }