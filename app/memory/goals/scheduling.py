"""Goal scheduler - queue, selection, dependencies, and blocking logic."""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from app.memory.goals.models import Goal, DurationEstimate


class GoalScheduler:
    """Goal scheduling with priority queue, dependency resolution, and blocking detection."""

    # Priority ranking used by ``queue`` / ``select_next``. Lower rank sorts
    # first (i.e. runs sooner). Unknown priorities sort to the bottom on
    # purpose: an unrecognised value is treated as "least important" so it
    # never preempts a goal that was named explicitly.
    _PRIORITY_RANK: Dict[str, int] = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "optional": 4,
    }
    _DEFAULT_PRIORITY_RANK = 99

    _TERMINAL_STATUSES = ("completed", "cancelled")
    _PAUSED_STATUS = "paused"
    _META_PREVIOUS_STATUS = "previous_status"
    _META_PAUSE_REASON = "pause_reason"

    def __init__(self, persistence, hierarchy):
        self._persistence = persistence
        self._hierarchy = hierarchy
        self._goals = persistence.goals
        self._lock = persistence.lock
        self._active_goal_id = persistence.active_goal_id

    def _priority_rank(self, priority: str) -> int:
        return self._PRIORITY_RANK.get(priority, self._DEFAULT_PRIORITY_RANK)

    def dependencies_of(self, goal_id: str) -> List[Goal]:
        """Return the goals this one depends on, in stored order.

        Missing dependency ids (pointers to goals that no longer exist) are
        silently skipped, mirroring the "dangling id" handling elsewhere
        in the storage layer.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return []
            return [
                self._goals[did]
                for did in goal.depends_on_ids
                if did in self._goals
            ]

    def is_blocked(self, goal_id: str) -> bool:
        """Return True iff the goal exists and is currently blocked.

        A goal is considered blocked when **any** of the following hold:

        * its explicit ``status == "blocked"``;
        * at least one of its declared ``depends_on_ids`` refers to a goal
          that does not exist (``"Completed"`` is the only way to satisfy a
          dependency — a missing dep is therefore unsatisfied); or
        * at least one of its declared ``depends_on_ids`` refers to a goal
          whose ``status != "completed"``.

        Unknown ``goal_id`` resolves to ``False`` rather than raising — that
        way callers like ``queue`` can coalesce the "missing" and
        "excluded" cases without an extra branch.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return False
            if goal.status == "blocked":
                return True
            for did in goal.depends_on_ids:
                dep = self._goals.get(did)
                if dep is None:
                    return True
                if dep.status != "completed":
                    return True
            return False

    def _is_eligible(self, goal: Goal) -> bool:
        """Internal: a goal is eligible for the queue when it has not been
        completed, is not blocked, and is not the currently-active goal.
        """
        if goal.status == "completed":
            return False
        if self.is_blocked(goal.id):
            return False
        if goal.id == self._persistence.active_goal_id:
            return False
        return True

    def _get_duration_estimate(self, goal: Goal) -> Optional[DurationEstimate]:
        """Get duration estimate for a goal from metadata."""
        estimate_data = goal.metadata.get("duration_estimate")
        if estimate_data:
            return DurationEstimate.from_dict(estimate_data)
        return None

    def _compute_scheduling_score(self, goal: Goal) -> Tuple[int, float]:
        """Compute a composite scheduling score for a goal.

        Returns (priority_rank, secondary_score) where lower priority_rank
        is better, and higher secondary_score is better (used as tiebreaker).

        Secondary score considers:
        - Duration estimate (shorter = higher score for quick wins)
        - Unblocking value (goals that unblock others)
        - Confidence in estimate
        """
        priority_rank = self._priority_rank(goal.priority)

        # Secondary scoring for tiebreaking
        secondary = 0.0

        estimate = self._get_duration_estimate(goal)
        if estimate:
            hours = estimate.estimated_seconds / 3600
            # Prefer shorter tasks (quick wins) as tiebreaker
            if hours <= 1:
                secondary += 10
            elif hours <= 4:
                secondary += 5
            elif hours <= 8:
                secondary += 2

            # Higher confidence estimates are more reliable
            secondary += estimate.confidence * 5

        return (priority_rank, -secondary)  # Negative so higher secondary sorts first

    def queue(self) -> List[Goal]:
        """Return the upcoming queue: eligible goals sorted by priority.

        Ordering is by ``_priority_rank`` ascending (lower rank = higher
        priority); ties preserve insertion order because Python's ``sort``
        is stable. The currently-active goal is excluded so the queue is
        always "what's next", not "the in-flight one too".
        """
        with self._lock:
            eligible = [g for g in self._goals.values() if self._is_eligible(g)]
            eligible.sort(key=lambda g: self._priority_rank(g.priority))
            return eligible

    def queue_with_estimates(self) -> List[Tuple[Goal, Optional[DurationEstimate]]]:
        """Return queue with duration estimates for each goal.

        Returns list of (Goal, DurationEstimate|None) tuples sorted by priority.
        """
        with self._lock:
            eligible = [g for g in self._goals.values() if self._is_eligible(g)]
            eligible.sort(key=lambda g: self._priority_rank(g.priority))
            return [(g, self._get_duration_estimate(g)) for g in eligible]

    def select_next(self) -> Optional[Goal]:
        """Pick the next eligible goal by priority and mark it active.

        Returns the chosen ``Goal`` and persists the active marker; returns
        ``None`` when no goal is eligible (everything is completed,
        blocked, or the active goal is the only one left).

        Phase 7 (autonomous goal review) integration: when a paused
        goal is the highest-priority eligible candidate, it is
        implicitly ``resume_goal``-ed before being marked active.
        Callers therefore don't need to call ``resume_goal`` by hand
        before ``select_next`` — the loop just works.
        """
        with self._lock:
            eligible = [g for g in self._goals.values() if self._is_eligible(g)]
            if not eligible:
                return None
            # Use composite scoring for better selection
            eligible.sort(key=lambda g: self._compute_scheduling_score(g))
            chosen = eligible[0]
            # Phase 7: auto-resume. Done inline (rather than via the
            # public ``resume_goal``) so we don't take the storage lock
            # twice. Mirrors ``resume_goal``'s precedence: ``paused``
            # → ``metadata["previous_status"]``; fallback ``"pending"``.
            if chosen.status == self._PAUSED_STATUS:
                chosen.status = chosen.metadata.get(
                    self._META_PREVIOUS_STATUS, "pending"
                )
                chosen.metadata.pop(self._META_PREVIOUS_STATUS, None)
                chosen.metadata.pop(self._META_PAUSE_REASON, None)
                chosen.updated_at = self._persistence._now()
            # Track start time for duration estimation
            chosen.metadata["started_at"] = self._persistence._now()
            self._persistence.active_goal_id = chosen.id
            self._persistence._save_file()
            return chosen

    def select_next_resource_aware(self, resource_constraints: Optional[Dict[str, float]] = None) -> Optional[Goal]:
        """Select next goal considering resource availability.

        Args:
            resource_constraints: Optional dict of resource -> available fraction (0-1)

        Returns:
            Selected goal or None
        """
        with self._lock:
            eligible = [g for g in self._goals.values() if self._is_eligible(g)]
            if not eligible:
                return None

            # Filter by resource constraints if provided
            if resource_constraints:
                # Simple filter: check if goal has resource hints in metadata
                # This is a lightweight check - full resource-aware scheduling
                # is handled by the planner's ResourceAwareScheduler
                filtered = []
                for g in eligible:
                    estimate = self._get_duration_estimate(g)
                    if estimate and estimate.metadata.get("resource_mult", 1.0) > 1.0:
                        # This goal needs constrained resources, deprioritize
                        continue
                    filtered.append(g)
                eligible = filtered if filtered else eligible

            eligible.sort(key=lambda g: self._compute_scheduling_score(g))
            chosen = eligible[0]

            if chosen.status == self._PAUSED_STATUS:
                chosen.status = chosen.metadata.get(
                    self._META_PREVIOUS_STATUS, "pending"
                )
                chosen.metadata.pop(self._META_PREVIOUS_STATUS, None)
                chosen.metadata.pop(self._META_PAUSE_REASON, None)
                chosen.updated_at = self._persistence._now()

            chosen.metadata["started_at"] = self._persistence._now()
            self._persistence.active_goal_id = chosen.id
            self._persistence._save_file()
            return chosen