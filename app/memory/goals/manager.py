"""GoalStorage facade - composes Persistence, Hierarchy, Scheduling, Analytics, and Decomposition."""

import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.memory.goals.models import Goal, SubtaskSuggestion, DurationEstimate
from app.memory.goals.persistence import GoalPersistence
from app.memory.goals.hierarchy import GoalHierarchy
from app.memory.goals.scheduling import GoalScheduler
from app.memory.goals.analytics import GoalAnalytics
from app.memory.goals.decomposition import _DecompositionMixin
from app.planner.duration_estimation import DurationEstimator
from app.planner.task import TaskCategory, TaskPriority


class GoalStorage(
    GoalPersistence,
    GoalHierarchy,
    GoalScheduler,
    GoalAnalytics,
    _DecompositionMixin,
):
    """Unified goal storage with hierarchy, scheduling, analytics, and decomposition.

    This class composes all goal-related functionality through multiple
    inheritance. The mixin order follows the MRO to ensure correct
    method resolution:

    1. GoalPersistence - JSON file storage, CRUD, EventBus, BackgroundJobService
    2. GoalHierarchy - tree operations, progress, completion propagation
    3. GoalScheduler - queue, selection, dependencies, blocking detection
    4. GoalAnalytics - stall detection, pause/resume, recommendations
    5. _DecompositionMixin - semantic work items, decomposition, milestones

    This preserves the exact public API of the original monolithic
    GoalStorage class while separating concerns into maintainable modules.
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/goals.json",
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        # Initialize persistence first (provides the shared lock, goals dict, etc.)
        GoalPersistence.__init__(
            self,
            workspace=workspace,
            storage_path=storage_path,
            event_bus=event_bus,
            job_service=job_service,
            observability=observability,
        )
        # Initialize the mixin that adds decomposition capabilities
        _DecompositionMixin.__init__(self)
        # Initialize hierarchy (requires persistence for self._goals, self._lock)
        GoalHierarchy.__init__(self, self)
        # Initialize scheduler (requires persistence for self._goals, self._lock, active_goal_id)
        GoalScheduler.__init__(self, self, self)
        # Initialize analytics (requires persistence and hierarchy)
        GoalAnalytics.__init__(self, self, self)
        # Initialize duration estimator for goal timing estimates
        self._duration_estimator = DurationEstimator()

    def _infer_task_category(self, goal: Goal) -> TaskCategory:
        """Infer planner TaskCategory from goal properties."""
        text = f"{goal.name} {goal.description}".lower()
        if any(kw in text for kw in ["bug", "fix", "debug", "repair", "troubleshoot"]):
            return TaskCategory.BUG_FIX
        elif any(kw in text for kw in ["refactor", "rewrite", "restructure", "clean up", "cleanup"]):
            return TaskCategory.REFACTORING
        elif any(kw in text for kw in ["research", "investigate", "explore", "survey", "study"]):
            return TaskCategory.RESEARCH
        elif any(kw in text for kw in ["document", "documentation", "readme", "tutorial", "guide"]):
            return TaskCategory.DOCUMENTATION
        elif any(kw in text for kw in ["test", "testing", "qa", "verify", "validate", "acceptance"]):
            return TaskCategory.TESTING
        elif any(kw in text for kw in ["integrat", "connect", "wire", "bridge", "adaptor", "adapter"]):
            return TaskCategory.FEATURE
        elif any(kw in text for kw in ["deploy", "release", "publish", "ship", "launch"]):
            return TaskCategory.MAINTENANCE
        elif any(kw in text for kw in ["maintain", "maintenance", "patch", "upgrade", "update"]):
            return TaskCategory.MAINTENANCE
        elif any(kw in text for kw in ["implement", "build", "create", "develop", "add", "code", "write"]):
            return TaskCategory.IMPLEMENTATION
        return TaskCategory.OTHER

    def _infer_task_priority(self, goal: Goal) -> TaskPriority:
        """Map goal priority string to planner TaskPriority."""
        mapping = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
            "optional": TaskPriority.LOW,
        }
        return mapping.get(goal.priority, TaskPriority.MEDIUM)

    def estimate_goal_duration(self, goal_id: str) -> Optional[DurationEstimate]:
        """Estimate duration for a goal using the planner's DurationEstimator.

        Creates a temporary Task from the goal and uses the existing
        DurationEstimator to generate an intelligent estimate with
        historical learning capability.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return None

        # Create a temporary task-like object for estimation
        from app.planner.task import Task
        temp_task = Task(
            id=goal_id,
            title=goal.name,
            description=goal.description,
            category=self._infer_task_category(goal),
            priority=self._infer_task_priority(goal),
        )

        # Get complexity assessment
        complexity = self.assess_complexity(goal_id)
        complexity_level = complexity.level if complexity else None

        # Estimate using the planner's estimator
        estimate = self._duration_estimator.estimate_task_duration(temp_task, complexity=complexity_level)

        # Convert to our DurationEstimate model if needed
        if hasattr(estimate, 'estimated_seconds'):
            # Already a DurationEstimate from goals model
            return estimate
        else:
            # Convert from dict
            return DurationEstimate.from_dict(estimate)

    def get_goal_duration_estimate(self, goal_id: str) -> Optional[DurationEstimate]:
        """Get stored duration estimate for a goal, or compute if not present."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return None

            # Check if we have a stored estimate
            estimate_data = goal.metadata.get("duration_estimate")
            if estimate_data:
                return DurationEstimate.from_dict(estimate_data)

        # Compute and store if not present
        estimate = self.estimate_goal_duration(goal_id)
        if estimate:
            self._store_duration_estimate(goal_id, estimate)
        return estimate

    def _store_duration_estimate(self, goal_id: str, estimate: DurationEstimate) -> None:
        """Store duration estimate in goal metadata."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal:
                goal.metadata["duration_estimate"] = estimate.to_dict()
                goal.updated_at = self._persistence._now()
                self._persistence._save_file()

    def update_duration_estimate_on_completion(self, goal_id: str, actual_seconds: float) -> Optional[DurationEstimate]:
        """Update duration estimate with actual completion time for historical learning."""
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return None

            estimate_data = goal.metadata.get("duration_estimate")
            if not estimate_data:
                return None

            estimate = DurationEstimate.from_dict(estimate_data)
            updated = estimate.apply_historical_actual(actual_seconds)

            # Store updated estimate
            goal.metadata["duration_estimate"] = updated.to_dict()
            goal.updated_at = self._persistence._now()
            self._persistence._save_file()

            return updated