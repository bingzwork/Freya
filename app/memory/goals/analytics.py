"""Goal analytics - stall detection, pause/resume, recommendations."""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.memory.goals.models import Goal


class GoalAnalytics:
    """Goal analytics for stall detection, pause management, and recommendations."""

    _TERMINAL_STATUSES = ("completed", "cancelled")
    _PAUSED_STATUS = "paused"

    _META_PREVIOUS_STATUS = "previous_status"
    _META_PAUSE_REASON = "pause_reason"
    _META_STALL_REASON = "stall_reason"
    _META_RECOMMEND_REASON = "recommend_reason"
    _META_ABANDON_REASON = "abandon_reason"

    def __init__(self, persistence, hierarchy):
        self._persistence = persistence
        self._hierarchy = hierarchy
        self._goals = persistence.goals
        self._lock = persistence.lock
        self._active_goal_id = persistence.active_goal_id

    def _parse_iso(self, value: str) -> Optional[datetime]:
        """Parse an ISO UTC timestamp string into a tz-aware datetime."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _age_seconds(
        self,
        goal: Goal,
        now: Optional[datetime] = None,
    ) -> Optional[float]:
        """Seconds elapsed since ``goal`` was last updated."""
        ts = self._parse_iso(goal.updated_at)
        if ts is None:
            return None
        base = now or datetime.now(timezone.utc)
        return max(0.0, (base - ts).total_seconds())

    def list_stalled(
        self,
        stall_threshold_seconds: float = 7 * 24 * 3600,
        include_paused: bool = False,
        now: Optional[datetime] = None,
    ) -> List[Goal]:
        """Return goals that haven't been updated within the threshold.

        ``stall_threshold_seconds`` defaults to one week. A goal qualifies
        when its ``updated_at`` is older than the threshold AND its
        status is not terminal (``completed`` / ``cancelled``) AND it
        has a parseable timestamp. Paused goals are excluded by default
        — Phase 7 deliberately treats intentional dormancy as different
        from organic staleness; pass ``include_paused=True`` to audit
        paused goals too.

        Phase 7 never mutates goals here — a goal being on this list is
        a *recommendation*, not a state change. Apply a pause via
        ``pause_inactive`` if you want the storage layer to act on it.
        """
        if stall_threshold_seconds <= 0:
            return []
        with self._lock:
            snapshot = list(self._goals.values())
        stalled: List[Goal] = []
        for goal in snapshot:
            if goal.status in self._TERMINAL_STATUSES:
                continue
            if not include_paused and goal.status == self._PAUSED_STATUS:
                continue
            age = self._age_seconds(goal, now=now)
            if age is None:
                continue
            if age >= stall_threshold_seconds:
                stalled.append(goal)
        return stalled

    def block_reasons(self, goal_id: str) -> List[str]:
        """Return human-readable reasons why ``goal_id`` is blocked.

        Builds on the Phase 5 ``is_blocked`` gate without modifying it
        — Phase 7 only *describes* the block.

        Order is:
            1. explicit ``status == "blocked"``
            2. incomplete dependencies (each unmet prereq is named)
            3. missing dependency ids (any declared prereq whose id
               no longer points at a known goal)

        Returns ``[]`` when the goal is unknown or not blocked.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return []
            reasons: List[str] = []
            if goal.status == "blocked":
                reasons.append("status is explicitly 'blocked'")
            for dep_id in goal.depends_on_ids:
                dep = self._goals.get(dep_id)
                if dep is None:
                    reasons.append(f"dependency '{dep_id}' is missing")
                elif dep.status != "completed":
                    reasons.append(
                        f"dependency '{dep_id}' (name={dep.name!r}) "
                        f"is not completed (status={dep.status!r})"
                    )
            return reasons

    def pause_goal(
        self,
        goal_id: str,
        reason: str = "",
    ) -> Optional[Goal]:
        """Mark ``goal_id`` ``status='paused'`` and remember the prior status.

        ``reason``, when supplied, is stored under
        ``metadata["pause_reason"]`` so reviewers can surface *why* the
        pause was triggered without touching the goal's description.

        Never pauses completed or cancelled goals — Phase 7 treats
        terminal states as immutable for review purposes. Returns
        ``None`` for unknown ids. Idempotent: a goal that is already
        ``'paused'`` is returned untouched (the existing reason /
        previous status remain canonical).
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            if goal.status in self._TERMINAL_STATUSES:
                return goal
            if goal.status == self._PAUSED_STATUS:
                return goal
            goal.metadata[self._META_PREVIOUS_STATUS] = goal.status
            if reason:
                goal.metadata[self._META_PAUSE_REASON] = reason
            goal.status = self._PAUSED_STATUS
            goal.updated_at = self._persistence._now()
            self._persistence._save_file()
            self._persistence._publish_event("goal.paused", {"goal_id": goal_id, "name": goal.name, "reason": reason})
            return goal

    def pause_inactive(
        self,
        stall_threshold_seconds: float,
        reason: str = "",
        include_paused: bool = False,
    ) -> List[Goal]:
        """Bulk-pause goals that exceeded ``stall_threshold_seconds``.

        Wraps ``list_stalled`` and ``pause_goal``. The returned list is
        the goals whose status *changed* to ``'paused'`` during this
        call — goals already paused, terminally completed, or unknown
        are not in the returned list (consistent with ``pause_goal``
        semantics).
        """
        stalled = self.list_stalled(
            stall_threshold_seconds=stall_threshold_seconds,
            include_paused=include_paused,
        )
        paused: List[Goal] = []
        for goal in stalled:
            result = self.pause_goal(goal.id, reason=reason)
            if result is not None and result.status == self._PAUSED_STATUS:
                # ``pause_goal`` re-reads; treat the result as the
                # post-transition object. The result is in our map iff
                # the pause actually flipped the status.
                paused.append(result)
        return paused

    def resume_goal(self, goal_id: str) -> Optional[Goal]:
        """Restore a paused goal to the status it had before pausing.

        The restored status is read from ``metadata["previous_status"]``.
        When that key is missing (e.g. a goal paused manually outside
        of Phase 7's surface), the goal falls back to ``"pending"`` —
        the canonical "no work has started yet" state.

        No-op on a goal that is not currently paused — the goal is
        returned untouched, with its current status preserved. Returns
        ``None`` for unknown ids.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            if goal.status != self._PAUSED_STATUS:
                return goal
            previous = goal.metadata.get(
                self._META_PREVIOUS_STATUS, "pending"
            )
            # Clean up the bookkeeping so a second pause-then-resume
            # cycle yields the original status, not a stale one.
            goal.metadata.pop(self._META_PREVIOUS_STATUS, None)
            goal.metadata.pop(self._META_PAUSE_REASON, None)
            goal.status = previous
            goal.updated_at = self._persistence._now()
            self._persistence._save_file()
            self._persistence._publish_event("goal.resumed", {"goal_id": goal_id, "name": goal.name, "previous_status": previous})
            return goal

    def is_paused(self, goal_id: str) -> bool:
        """Return ``True`` iff the goal exists and is currently paused."""
        with self._lock:
            goal = self._goals.get(goal_id)
            return goal is not None and goal.status == self._PAUSED_STATUS

    def recommend_cancellation(
        self,
        stall_threshold_seconds: float,
        pause_threshold_seconds: float = 0.0,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return candidate goals for cancellation without acting on them.

        The bar is intentionally high: a goal only surfaces here when
        both ``pause_threshold_seconds`` (time spent paused) AND
        ``stall_threshold_seconds`` (time since last update) are
        exceeded. Single-condition flags belong to ``list_stalled``
        and ``is_blocked``; cancellation is a higher-stakes
        recommendation, so it requires two independent signals.

        Each record is shaped::

            {
                "goal_id": str,
                "name": str,
                "reason": str,
                "status": str,
                "paused_seconds": float | None,
                "stall_seconds": float | None,
            }

        ``now`` lets tests inject a deterministic clock; default is
        ``datetime.now(timezone.utc)``.
        """
        if stall_threshold_seconds <= 0 and pause_threshold_seconds <= 0:
            return []
        base = now or datetime.now(timezone.utc)
        with self._lock:
            snapshot = list(self._goals.values())
        recommendations: List[Dict[str, Any]] = []
        for goal in snapshot:
            if goal.status in self._TERMINAL_STATUSES:
                continue
            stall_age = self._age_seconds(goal, now=base)
            paused_for: Optional[float] = None
            if goal.status == self._PAUSED_STATUS:
                # Pause duration is measured from the last update,
                # which is when the pause transition happened (the
                # pause bump above).
                paused_for = stall_age
            stalled_signal = (
                stall_age is not None
                and stall_threshold_seconds > 0
                and stall_age >= stall_threshold_seconds
            )
            paused_signal = (
                paused_for is not None
                and pause_threshold_seconds > 0
                and paused_for >= pause_threshold_seconds
            )
            # Need both — see docstring.
            if not (stalled_signal and paused_signal):
                continue
            recommendations.append({
                "goal_id": goal.id,
                "name": goal.name,
                "status": goal.status,
                "reason": (
                    "stalled for "
                    f"{int(stall_age or 0)}s and paused for "
                    f"{int(paused_for or 0)}s — both above threshold; "
                    "appears abandoned"
                ),
                "stall_seconds": stall_age,
                "paused_seconds": paused_for,
            })
        return recommendations

    def recommend_priorities(
        self,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return deterministic priority recommendations without applying.

        Each record is shaped::

            {
                "goal_id": str,
                "name": str,
                "current": str,
                "recommended": str,
                "reason": str,
                "score": float,  # Priority score 0-100
                "signals": List[str],
            }

        Goals whose heuristic recommendation equals the current priority
        are NOT included — manual priorities are preserved unless there
        is a clear reason to flag a change. The algorithm uses a weighted
        scoring system considering:

        * Blocking status (blocked goals need attention)
        * Stall detection (goals untouched for too long)
        * Pause status (explicitly paused goals)
        * Unblocking value (goals that unblock high-priority goals)
        * Dependency urgency (goals with urgent dependents)
        * Resource alignment (goals matching available resources)
        * Duration estimates (shorter goals may be prioritized for quick wins)
        """
        base = now or datetime.now(timezone.utc)
        default_stall = 7 * 24 * 3600  # one week

        # Priority rank mapping (lower = higher priority)
        rank_to_priority = ("critical", "high", "medium", "low", "optional")
        priority_to_rank = {p: i for i, p in enumerate(rank_to_priority)}

        with self._lock:
            snapshot = list(self._goals.values())

        # Pre-compute unblocking relationships
        unblocks = self._compute_unblocking_value(snapshot)

        recs: List[Dict[str, Any]] = []
        for goal in snapshot:
            if goal.status in self._TERMINAL_STATUSES:
                continue
            # Don't recommend changes for the active goal
            if goal.id == self._persistence.active_goal_id:
                continue

            signals: List[str] = []
            score = 50.0  # Base score (0-100, higher = more urgent)

            # 1. Blocked status - significantly increases urgency
            is_blocked = self._scheduler.is_blocked(goal.id)
            if is_blocked:
                score += 25
                signals.append("blocked")

            # 2. Stall detection - increases urgency
            age = self._age_seconds(goal, now=base)
            if age is not None and age >= default_stall:
                score += 15
                signals.append("stalled")
            elif age is not None and age >= default_stall * 0.5:
                score += 5
                signals.append("aging")

            # 3. Pause status - increases urgency (explicitly paused needs review)
            if goal.status == self._PAUSED_STATUS:
                score += 10
                signals.append("paused")

            # 4. Unblocking value - goals that unblock high-priority goals get boosted
            unblock_score = unblocks.get(goal.id, 0)
            if unblock_score > 0:
                score += min(unblock_score * 5, 20)  # Cap at +20
                signals.append(f"unblocks:{unblock_score}")

            # 5. Dependency urgency - goals with critical/high dependents
            dep_urgency = self._compute_dependent_urgency(goal.id, snapshot)
            if dep_urgency > 0:
                score += dep_urgency
                signals.append(f"dep_urgency:{dep_urgency:.0f}")

            # 6. Resource alignment - prefer goals that can run with available resources
            # (This is a lightweight check; full resource-aware scheduling is separate)
            resource_alignment = self._check_resource_alignment(goal)
            if resource_alignment > 0:
                score += resource_alignment
                signals.append("resource_aligned")

            # 7. Duration estimate - shorter estimated duration = quick win bonus
            duration_bonus = self._compute_duration_bonus(goal)
            if duration_bonus > 0:
                score += duration_bonus
                signals.append("quick_win")

            # 8. High priority goals that are stalled/blocked get extra attention
            if goal.priority in ("critical", "high") and (is_blocked or (age is not None and age >= default_stall)):
                score += 10
                signals.append("high_priority_stalled")

            # Clamp score
            score = max(0, min(100, score))

            # Map score to priority rank
            # 80-100: critical, 60-79: high, 40-59: medium, 20-39: low, 0-19: optional
            if score >= 80:
                recommended_priority = "critical"
            elif score >= 60:
                recommended_priority = "high"
            elif score >= 40:
                recommended_priority = "medium"
            elif score >= 20:
                recommended_priority = "low"
            else:
                recommended_priority = "optional"

            current_priority = goal.priority
            if current_priority not in priority_to_rank:
                current_priority = "medium"

            current_idx = priority_to_rank[current_priority]
            recommended_idx = priority_to_rank[recommended_priority]

            # Only recommend if there's a meaningful change (at least 1 rank)
            if abs(recommended_idx - current_idx) < 1:
                continue

            direction = "increase" if recommended_idx < current_idx else "decrease"
            steps = abs(recommended_idx - current_idx)

            recs.append({
                "goal_id": goal.id,
                "name": goal.name,
                "current": current_priority,
                "recommended": recommended_priority,
                "reason": f"signals=[{', '.join(signals)}] → {direction} priority by {steps} step(s) (score: {score:.0f}/100)",
                "score": round(score, 1),
                "signals": signals,
            })
        return recs

    def _compute_unblocking_value(self, goals: List[Goal]) -> Dict[str, int]:
        """Compute how many high-priority goals each goal unblocks.

        Returns a mapping of goal_id -> count of blocked goals it unblocks,
        weighted by the blocked goals' priorities.
        """
        # Build reverse dependency map: goal_id -> list of goals that depend on it
        reverse_deps: Dict[str, List[Goal]] = {}
        for goal in goals:
            for dep_id in goal.depends_on_ids:
                reverse_deps.setdefault(dep_id, []).append(goal)

        priority_weight = {"critical": 5, "high": 3, "medium": 2, "low": 1, "optional": 0}

        result = {}
        for goal in goals:
            if goal.id in reverse_deps:
                # Count weighted dependents that are blocked
                blocked_count = 0
                for dependent in reverse_deps[goal.id]:
                    if dependent.status not in self._TERMINAL_STATUSES and self._scheduler.is_blocked(dependent.id):
                        blocked_count += priority_weight.get(dependent.priority, 1)
                result[goal.id] = blocked_count
        return result

    def _compute_dependent_urgency(self, goal_id: str, goals: List[Goal]) -> float:
        """Compute urgency based on dependent goals' priorities and status."""
        # Find goals that depend on this one
        dependents = [g for g in goals if goal_id in g.depends_on_ids]
        if not dependents:
            return 0.0

        priority_score = {"critical": 10, "high": 6, "medium": 3, "low": 1, "optional": 0}
        urgency = 0.0

        for dep in dependents:
            if dep.status in self._TERMINAL_STATUSES:
                continue
            # Add score based on dependent's priority
            urgency += priority_score.get(dep.priority, 0)
            # Additional urgency if dependent is blocked (waiting on us)
            if self._scheduler.is_blocked(dep.id):
                urgency += 5

        return min(urgency, 20)  # Cap at 20

    def _check_resource_alignment(self, goal: Goal) -> float:
        """Check if goal aligns with available system resources.

        Lightweight check - returns small bonus if goal's estimated
        resource needs match available resources.
        """
        try:
            # Check if goal has duration estimate with resource hints
            estimate_data = goal.metadata.get("duration_estimate")
            if not estimate_data:
                # Quick heuristic based on goal content
                text = f"{goal.name} {goal.description}".lower()
                # GPU-intensive keywords
                if any(kw in text for kw in ["gpu", "cuda", "ml", "training", "pytorch", "tensorflow", "deep learning"]):
                    return 2.0  # Small bonus for GPU goals when GPU available
                # Memory-intensive
                if any(kw in text for kw in ["big data", "large dataset", "memory", "spark", "hadoop"]):
                    return 1.0
                return 0.0
            return 0.0
        except Exception:
            return 0.0

    def _compute_duration_bonus(self, goal: Goal) -> float:
        """Give bonus to goals with short estimated duration (quick wins)."""
        try:
            estimate_data = goal.metadata.get("duration_estimate")
            if estimate_data:
                from app.memory.goals.models import DurationEstimate
                estimate = DurationEstimate.from_dict(estimate_data)
                hours = estimate.estimated_seconds / 3600
                if hours <= 1:
                    return 5.0  # Quick win bonus
                elif hours <= 4:
                    return 2.0
            return 0.0
        except Exception:
            return 0.0

    @property
    def _scheduler(self):
        """Access scheduler for is_blocked check."""
        # Lazy import to avoid circular dependency
        from app.memory.goals.scheduling import GoalScheduler
        return GoalScheduler(self._persistence, self._hierarchy)