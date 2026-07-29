"""Goal data model for Freya AI.

Phase 1 defines the foundational Goal dataclass plus minimal JSON-file
persistence (`save` / `load`). CRUD, hierarchy logic, progress tracking,
scheduling, and planner integration land in later phases.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class Goal:
    """A single goal entry.

    Attributes:
        id: Unique goal identifier.
        name: Short human-readable name.
        description: Longer description of the goal's intent.
        status: Lifecycle status (string-typed; standardized values land
            in a later phase).
        priority: Priority level (string-typed; standardized values land
            in a later phase).
        parent_goal_id: ID of this goal's parent, or None for top-level.
        child_goal_ids: IDs of this goal's children.
        depends_on_ids: IDs of goals that must ``status == "completed"``
            before this one becomes eligible for selection.
        created_at: ISO timestamp captured on creation (UTC).
        updated_at: ISO timestamp of the most recent write (UTC).
    """

    id: str
    name: str
    description: str = ""
    status: str = "pending"
    priority: str = "medium"
    parent_goal_id: Optional[str] = None
    child_goal_ids: List[str] = field(default_factory=list)
    depends_on_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert goal to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        """Create goal from dictionary."""
        return cls(**data)


class GoalStorage:
    """JSON-file persistence for Goal objects.

    Follows the same pattern as `EngineeringLessonStorage` /
    `ExperienceMemory`: atomic temp-file write, thread-safe, file lives at
    ``<workspace>/data/memory/goals.json``.

    Phase 1 surface is intentionally minimal: ``save`` / ``load`` plus
    inspection helpers (``all``, ``count``). CRUD verbs
    (create / edit / delete) are explicitly out of scope and belong to a
    later phase.
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/goals.json",
    ):
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self._lock = threading.RLock()
        self._goals: Dict[str, Goal] = {}
        self._active_goal_id: Optional[str] = None
        self._load()

    # --- internals -------------------------------------------------------

    def _ensure_storage_dir(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        """Load goals from disk into the in-memory map."""
        with self._lock:
            if not self.storage_path.exists():
                return
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                return

            self._goals = {
                goal_data["id"]: Goal.from_dict(goal_data)
                for goal_data in data.get("goals", [])
                if "id" in goal_data
            }
            self._active_goal_id = (data.get("metadata") or {}).get("active_goal_id")

    def _save_file(self) -> None:
        """Atomic write of the in-memory map to disk."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        payload = {
            "goals": [g.to_dict() for g in self._goals.values()],
            "metadata": {
                "count": len(self._goals),
                "last_updated": self._now(),
                "active_goal_id": self._active_goal_id,
            },
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        temp_path.replace(self.storage_path)

    # --- save / load -----------------------------------------------------

    def save(self, goal: Goal) -> Goal:
        """Persist a Goal to disk (upsert by id)."""
        with self._lock:
            self._goals[goal.id] = goal
            self._save_file()
            return goal

    def load(self, goal_id: str) -> Optional[Goal]:
        """Load a single Goal by id from the in-memory map."""
        with self._lock:
            return self._goals.get(goal_id)

    # --- inspection helpers (non-CRUD) ------------------------------------

    def all(self) -> List[Goal]:
        """Return all currently loaded goals."""
        with self._lock:
            return list(self._goals.values())

    def count(self) -> int:
        """Return the number of loaded goals."""
        with self._lock:
            return len(self._goals)

    # --- CRUD -------------------------------------------------------------

    def create(
        self,
        name: str,
        description: str = "",
        status: str = "pending",
        priority: str = "medium",
        parent_goal_id: Optional[str] = None,
        child_goal_ids: Optional[List[str]] = None,
        depends_on_ids: Optional[List[str]] = None,
    ) -> Goal:
        """Create a new goal with a generated id and persist it.

        ``id`` is allocated via ``uuid4().hex[:12]`` (matches the
        ``goal_<12hex>`` shape used elsewhere — see ``uuid.uuid4``).
        ``created_at`` and ``updated_at`` are stamped with the current
        UTC ISO timestamp.
        """
        with self._lock:
            import uuid

            now = self._now()
            goal = Goal(
                id=f"goal_{uuid.uuid4().hex[:12]}",
                name=name,
                description=description,
                status=status,
                priority=priority,
                parent_goal_id=parent_goal_id,
                child_goal_ids=list(child_goal_ids) if child_goal_ids else [],
                depends_on_ids=list(depends_on_ids) if depends_on_ids else [],
                created_at=now,
                updated_at=now,
            )
            self._goals[goal.id] = goal
            self._save_file()
            return goal

    def update(
        self,
        goal_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        parent_goal_id: Optional[str] = None,
        child_goal_ids: Optional[List[str]] = None,
        depends_on_ids: Optional[List[str]] = None,
    ) -> Optional[Goal]:
        """Patch mutable fields on an existing goal and persist it.

        Only the fields explicitly passed (i.e. not ``None``) are written;
        passing ``child_goal_ids=[]`` or ``depends_on_ids=[]`` explicitly
        clears the respective list. Returns the updated ``Goal`` or
        ``None`` if ``goal_id`` does not exist. When at least one field
        actually changes, ``updated_at`` is bumped to the current UTC ISO
        timestamp; ``created_at`` is preserved.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            changed = False
            if name is not None and goal.name != name:
                goal.name = name; changed = True
            if description is not None and goal.description != description:
                goal.description = description; changed = True
            if status is not None and goal.status != status:
                goal.status = status; changed = True
            if priority is not None and goal.priority != priority:
                goal.priority = priority; changed = True
            if parent_goal_id is not None and goal.parent_goal_id != parent_goal_id:
                goal.parent_goal_id = parent_goal_id; changed = True
            if child_goal_ids is not None and goal.child_goal_ids != list(child_goal_ids):
                goal.child_goal_ids = list(child_goal_ids); changed = True
            if depends_on_ids is not None and goal.depends_on_ids != list(depends_on_ids):
                goal.depends_on_ids = list(depends_on_ids); changed = True
            if changed:
                goal.updated_at = self._now()
            self._save_file()
            return goal

    def delete(self, goal_id: str) -> bool:
        """Remove a goal from storage. Returns False if id was unknown."""
        with self._lock:
            if goal_id not in self._goals:
                return False
            del self._goals[goal_id]
            self._save_file()
            return True

    def list(self) -> List[Goal]:
        """Return a snapshot of all goals (insertion order)."""
        return self.all()

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
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None

            goal.status = "completed"
            self._save_file()

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
                    self._save_file()
                    current = parent
                else:
                    break

            return goal

    # --- progress / active indicator (Phase 4) ---------------------------

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
            self._active_goal_id = goal_id
            self._save_file()
            return True

    def active_goal(self) -> Optional[Goal]:
        """Return the currently-active goal, or ``None`` if none is set."""
        with self._lock:
            if self._active_goal_id is None:
                return None
            return self._goals.get(self._active_goal_id)

    def clear_active(self) -> None:
        """Drop the active goal marker. No-op if nothing is set."""
        with self._lock:
            if self._active_goal_id is None:
                return
            self._active_goal_id = None
            self._save_file()

    # --- scheduler (Phase 5) ---------------------------------------------

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
        if goal.id == self._active_goal_id:
            return False
        return True

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

    def select_next(self) -> Optional[Goal]:
        """Pick the next eligible goal by priority and mark it active.

        Returns the chosen ``Goal`` and persists the active marker; returns
        ``None`` when no goal is eligible (everything is completed,
        blocked, or the active goal is the only one left).
        """
        with self._lock:
            eligible = [g for g in self._goals.values() if self._is_eligible(g)]
            if not eligible:
                return None
            eligible.sort(key=lambda g: self._priority_rank(g.priority))
            chosen = eligible[0]
            self._active_goal_id = chosen.id
            self._save_file()
            return chosen

    # --- decomposition (Phase 6) -----------------------------------------

    # Deterministic, template-based expansion used by ``GoalDecomposer``.
    # Phase 6 ships a non-LLM expander so the surface is testable without
    # a provider; the order is the priority order — earliest-first wins
    # under ``max_subtasks`` truncation.
    _DECOMPOSE_PHASES = (
        ("Plan", "Plan and break down the work for the parent goal."),
        ("Implement", "Implement the core functionality of the parent goal."),
        ("Test", "Verify behaviour end-to-end against the parent goal."),
        ("Document", "Document the changes delivered for the parent goal."),
        ("Review", "Review and finalize the work for the parent goal."),
    )

    def decompose_goal(
        self,
        goal_id: str,
        max_subtasks: int = 5,
    ) -> List["SubtaskSuggestion"]:
        """Return suggested child-goal drafts for ``goal_id``.

        This is the **non-mutating** read-side of Phase 6: callers receive
        a list of ``SubtaskSuggestion`` objects representing candidate
        child goals but **nothing is written to disk**. Use
        ``apply_decomposition`` to materialise approved suggestions.

        Returns an empty list when ``goal_id`` does not exist. The number
        of returned suggestions is ``min(max_subtasks, len(_DECOMPOSE_PHASES))``
        and is capped at ``0`` when ``max_subtasks`` is non-positive.
        Subtask priorities default to the parent goal's priority so the
        scheduler (Phase 5) treats them as a coherent group until the user
        edits them.
        """
        with self._lock:
            parent = self._goals.get(goal_id)
            if parent is None:
                return []
            inherited_priority = parent.priority
            parent_name = parent.name
            parent_description = parent.description

        if max_subtasks <= 0:
            return []
        phase_count = min(max_subtasks, len(self._DECOMPOSE_PHASES))
        suggestions: List["SubtaskSuggestion"] = []
        for index in range(phase_count):
            phase_name, phase_desc = self._DECOMPOSE_PHASES[index]
            suggestions.append(
                SubtaskSuggestion(
                    name=f"{phase_name}: {parent_name}",
                    description=phase_desc,
                    priority=inherited_priority,
                )
            )
        # Attach parent context to the first suggestion so reviewers can
        # surface the linkage without re-resolving the parent goal.
        if suggestions and parent_description:
            suggestions[0].description = (
                f"{suggestions[0].description}\n\n"
                f"Parent goal context: {parent_description}"
            )
        return suggestions

    def apply_decomposition(
        self,
        goal_id: str,
        suggestions: List["SubtaskSuggestion"],
        plan_manager: Optional[Any] = None,
    ) -> List[Goal]:
        """Persist ``suggestions`` as child goals of ``goal_id``.

        This is the **mutating** write-side of Phase 6 — the explicit
        manual-approval step. Each suggestion produces a child ``Goal``
        via the existing ``create(..., parent_goal_id=...)`` path, so the
        standard hierarchy invariants (Phase 3) apply automatically.

        When ``plan_manager`` is supplied, each accepted suggestion is
        also mirrored as a ``Task`` in the manager's active plan via the
        existing ``PlanManager.add_task(...)`` surface (no new planner
        surface is added in Phase 6 — the goal side is the source of
        truth and the planner side is a parallel projection). This is
        the **Planner integration** hook for Phase 6.

        ``suggestions`` referencing unknown parent id (``None`` /
        invalid / empty list) are ignored — the call returns ``[]`` rather
        than raising. Suggestions are applied in order, so callers that
        want ``depends_on_ids`` between siblings can post-edit the created
        goals via the Phase 1 ``update()`` verb after approval.
        """
        if not suggestions:
            return []
        with self._lock:
            if goal_id not in self._goals:
                return []
            created: List[Goal] = []
            for suggestion in suggestions:
                child = self.create(
                    name=suggestion.name,
                    description=suggestion.description,
                    priority=suggestion.priority,
                    parent_goal_id=goal_id,
                )
                created.append(child)

        # Planner integration happens after the goal-side persistence so
        # a planner failure can't roll back the goal tree. Errors are
        # swallowed (logged via the standard logger) — the goal side
        # remains the source of truth and surviving child count is
        # returned either way.
        if plan_manager is not None:
            try:
                for suggestion in suggestions:
                    kwargs = {}
                    if suggestion.planner_category is not None:
                        kwargs["category"] = suggestion.planner_category
                    if suggestion.estimated_hours is not None:
                        kwargs["estimated_hours"] = suggestion.estimated_hours
                    plan_manager.add_task(
                        title=suggestion.name,
                        description=suggestion.description,
                        **kwargs,
                    )
            except Exception as exc:  # noqa: BLE001
                from app.core.logger import logger
                logger.warning(
                    "[goals] planner side of decomposition failed: %s", exc
                )

        return created


@dataclass
class SubtaskSuggestion:
    """A draft child-goal proposal produced by ``GoalStorage.decompose_goal``.

    Suggestions are deliberately inert: they are returned to the caller by
    ``decompose_goal`` and only materialise as real ``Goal`` records when
    passed to ``apply_decomposition``. This is the manual-approval gate
    for Phase 6 — users can review, edit, or drop suggestions before they
    become persistent child goals.

    Attributes:
        name: Human-readable name for the proposed child goal.
        description: Longer description of the proposed child goal
            (default mirrors the decompose-template description, with the
            parent context appended on the first suggestion).
        priority: Inherited from the parent goal by default; callers may
            override per-suggestion before calling
            ``apply_decomposition``.
        planner_category: Optional planner ``TaskCategory`` (or any value
            accepted by ``PlanManager.add_task``) — when set and a
            ``plan_manager`` is supplied to ``apply_decomposition``, the
            parallel planner ``Task`` is created with this category.
        estimated_hours: Optional forwarded estimate for the parallel
            planner ``Task``; defaults to ``None`` (planner uses its own
            default).
    """

    name: str
    description: str = ""
    priority: str = "medium"
    planner_category: Optional[Any] = None
    estimated_hours: Optional[float] = None
