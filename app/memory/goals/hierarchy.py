"""Goal hierarchy, progress tracking, and active goal management."""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.memory.goals.models import Goal


class GoalHierarchy:
    """Goal tree operations, progress tracking, and active goal management."""

    # Terminal statuses
    _TERMINAL_STATUSES = ("completed", "cancelled")
    _PAUSED_STATUS = "paused"

    # Metadata keys
    _META_PREVIOUS_STATUS = "previous_status"
    _META_PAUSE_REASON = "pause_reason"
    _META_STALL_REASON = "stall_reason"
    _META_RECOMMEND_REASON = "recommend_reason"
    _META_ABANDON_REASON = "abandon_reason"

    def __init__(self, persistence):
        self._persistence = persistence  # GoalPersistence instance
        self._goals = persistence.goals
        self._lock = persistence.lock
        self._active_goal_id = persistence.active_goal_id

    # --- hierarchy / tree (Phase 3) --------------------------------------

    def parent_of(self, goal_id: str) -> Optional[Goal]:
        """Return the parent goal of ``goal_id``, or ``None`` if root / unknown."""
        with self._lock:
            child = self._goals.get(goal_id)
            if child is None or child.parent_goal_id is None:
                return None
            return self._goals.get(child.parent_goal_id)

    def _children_ids_of(self, goal_id: str) -> List[str]:
        """Return ids of goals whose ``parent_goal_id == goal_id``.

        The scan is the source of truth for "children of X" — independent of
        each parent's self-reported ``child_goal_ids``. This avoids
        hierarchy-invariant management on ``create`` / ``update``: setting
        ``parent_goal_id`` on a child is sufficient for the tree to be
        navigable.
        """
        return [
            g.id for g in self._goals.values()
            if g.parent_goal_id == goal_id
        ]

    def children_of(self, goal_id: str) -> List[Goal]:
        """Return the direct children of ``goal_id`` in insertion order."""
        with self._lock:
            if goal_id not in self._goals:
                return []
            return [
                self._goals[cid] for cid in self._children_ids_of(goal_id)
            ]

    def descendants_of(self, goal_id: str) -> List[Goal]:
        """Return every descendant of ``goal_id`` (BFS, parents before children)."""
        with self._lock:
            visited: List[Goal] = []
            seen: set = set()
            frontier: List[str] = self._children_ids_of(goal_id) if goal_id in self._goals else []
            while frontier:
                cid = frontier.pop(0)
                if cid in seen:
                    continue
                seen.add(cid)
                child = self._goals.get(cid)
                if child is None:
                    continue
                visited.append(child)
                frontier.extend(self._children_ids_of(cid))
            return visited

    def complete(self, goal_id: str) -> Optional[Goal]:
        """Mark ``goal_id`` ``status="completed"`` and propagate upward.

        Propagation rule: a parent is auto-completed **iff** it currently
        has at least one child and every observed child has
        ``status == "completed"``. Propagation is recursive up the parent
        chain; it stops at the first ancestor that still has a
        non-completed child.

        Children are discovered by scanning for ``parent_goal_id`` (see
        ``_children_ids_of``); the parent's self-reported ``child_goal_ids``
        list is not consulted for propagation, so ``create(parent_goal_id=...)``
        is sufficient to wire a child into the tree.

        Returns the originally-completed goal, or ``None`` if the id is
        unknown. Idempotent: re-completing an already-completed leaf is a
        no-op aside from the disk flush.
        """
        from datetime import datetime, timezone

        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None

            # Calculate actual duration if started_at is tracked
            started_at_str = goal.metadata.get("started_at")
            if started_at_str:
                try:
                    started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    actual_seconds = (now - started_at).total_seconds()
                    # Update duration estimate with actual (if GoalStorage has the method)
                    if hasattr(self._persistence, 'update_duration_estimate_on_completion'):
                        self._persistence.update_duration_estimate_on_completion(goal_id, actual_seconds)
                except Exception:
                    pass  # Ignore errors in duration tracking

            goal.status = "completed"
            # Clear started_at since goal is complete
            goal.metadata.pop("started_at", None)
            self._persistence._save_file()
            self._persistence._publish_event("goal.completed", {"goal_id": goal_id, "name": goal.name})

            current = goal
            while current.parent_goal_id:
                parent = self._goals.get(current.parent_goal_id)
                if parent is None:
                    break
                if parent.status == "completed":
                    current = parent
                    continue
                child_ids = self._children_ids_of(parent.id)
                if not child_ids:
                    # Parent has no observed children — do not auto-promote.
                    break
                if all(
                    self._goals.get(cid) is not None
                    and self._goals[cid].status == "completed"
                    for cid in child_ids
                ):
                    parent.status = "completed"
                    # Clear started_at for parent too
                    parent.metadata.pop("started_at", None)
                    self._persistence._save_file()
                    self._persistence._publish_event("goal.completed", {"goal_id": parent.id, "name": parent.name})
                    current = parent
                else:
                    break

            return goal

    # --- progress / timestamps / active indicator (Phase 4) ---------------------------

    def _parse_iso(self, value: str) -> Optional[datetime]:
        """Parse an ISO UTC timestamp string into a tz-aware datetime.

        Returns ``None`` for empty / malformed strings so callers can
        treat "no timestamp" uniformly. Naive datetimes are tagged
        UTC — they always were produced in UTC by the Phase 4 + 5 +
        6 surface, but older test fixtures occasionally strip tzinfo.
        """
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
        """Seconds elapsed since ``goal`` was last updated.

        Returns ``None`` when ``updated_at`` is empty / unparseable —
        Phase 7 cannot age a goal whose clock is unknown, and treats
        "unknown age" the same way it treats terminal goals: not stalled.
        """
        ts = self._parse_iso(goal.updated_at)
        if ts is None:
            return None
        base = now or datetime.now(timezone.utc)
        return max(0.0, (base - ts).total_seconds())

    def progress(self, goal_id: str) -> Dict[str, Any]:
        """Return progress metrics for a goal derived from its observed children.

        Shape::

            {"total_children": int, "completed_children": int, "percentage": float}

        The values are computed at call time from the live in-memory map, so
        they update automatically as children are added, removed, or marked
        completed — and as ``complete()`` propagation promotes ancestors. A
        leaf goal (no observed children) reports ``0 / 0 / 0.0``; an unknown
        goal id reports the same zero triple rather than raising.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return {"total_children": 0, "completed_children": 0, "percentage": 0.0}
            child_ids = self._children_ids_of(goal_id)
            total = len(child_ids)
            completed = sum(
                1 for cid in child_ids
                if cid in self._goals and self._goals[cid].status == "completed"
            )
            pct = (100.0 * completed / total) if total else 0.0
            return {
                "total_children": total,
                "completed_children": completed,
                "percentage": pct,
            }

    def is_completed(self, goal_id: str) -> bool:
        """Return ``True`` iff the goal exists and has ``status == "completed"``."""
        with self._lock:
            g = self._goals.get(goal_id)
            return g is not None and g.status == "completed"

    def set_active(self, goal_id: str) -> bool:
        """Mark ``goal_id`` as the currently-active goal.

        The active flag is single-tenant and persisted inside the same
        ``data/memory/goals.json`` file (under the storage ``metadata``
        block) so it survives restarts. Unknown ids return ``False``.
        """
        with self._lock:
            if goal_id not in self._goals:
                return False
            self._persistence.active_goal_id = goal_id
            return True

    def active_goal(self) -> Optional[Goal]:
        """Return the currently-active goal, or ``None`` if none is set."""
        with self._lock:
            if self._persistence.active_goal_id is None:
                return None
            return self._goals.get(self._persistence.active_goal_id)

    def clear_active(self) -> None:
        """Drop the active goal marker. No-op if nothing is set."""
        with self._lock:
            if self._persistence.active_goal_id is None:
                return
            self._persistence.active_goal_id = None