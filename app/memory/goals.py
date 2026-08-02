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

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType, HealthCheck, HealthResult, HealthStatus


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
        metadata: Free-form dictionary for lifecycle side-channel data
            owned by the storage layer (Phase 7: ``previous_status`` /
            ``pause_reason`` / ``stall_reason`` / ``recommend_reason``).
            Backwards compatible — pre-Phase-7 ``goals.json`` files
            load with an empty ``{}`` default.
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
    metadata: Dict[str, Any] = field(default_factory=dict)

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
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self._lock = threading.RLock()
        self._goals: Dict[str, Goal] = {}
        self._active_goal_id: Optional[str] = None

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        self._load()
        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="goal_storage_health",
                component="memory",
                check_func=self._health_check,
                interval_seconds=30.0,
            ))

            # Register component
            self.observability.register_component(ComponentInfo(
                name="GoalStorage",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Goal data model and persistence",
                metadata={"storage_path": str(self.storage_path)},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for GoalStorage."""
        try:
            return HealthResult(
                name="goal_storage_health",
                component="memory",
                status=HealthStatus.HEALTHY,
                message="GoalStorage operational",
                metadata={"goal_count": len(self._goals), "storage_exists": self.storage_path.exists()}
            )
        except Exception as e:
            return HealthResult(
                name="goal_storage_health",
                component="memory",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """Publish an event to the shared EventBus."""
        try:
            self.event_bus.emit(event_name, data)
        except Exception as e:
            from app.core.logger import logger
            logger.warning(f"Failed to publish event {event_name}: {e}")

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence."""
        # Check if job already exists to avoid duplicate scheduling
        existing_job = self.job_service.get_job("goal_storage_persist")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self.job_service.schedule(
            job_id="goal_storage_persist",
            func=self._save_file,
            trigger=trigger,
            name="Goal Storage Persistence",
            priority=JobPriority.LOW,
        )

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
            self._publish_event("goal.created", {"goal_id": goal.id, "name": goal.name, "status": goal.status, "priority": goal.priority})
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
            if changed:
                self._publish_event("goal.updated", {"goal_id": goal_id, "name": goal.name, "status": goal.status, "priority": goal.priority})
            return goal

    def delete(self, goal_id: str) -> bool:
        """Remove a goal from storage. Returns False if id was unknown."""
        with self._lock:
            if goal_id not in self._goals:
                return False
            goal_name = self._goals[goal_id].name
            del self._goals[goal_id]
            self._save_file()
            self._publish_event("goal.deleted", {"goal_id": goal_id, "name": goal_name})
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
            self._publish_event("goal.completed", {"goal_id": goal_id, "name": goal.name})

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
                    self._publish_event("goal.completed", {"goal_id": parent.id, "name": parent.name})
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
            eligible.sort(key=lambda g: self._priority_rank(g.priority))
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
                chosen.updated_at = self._now()
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

    # --- autonomous review (Phase 7) --------------------------------------

    # Statuses that are *terminal* from a review perspective — Phase 7
    # never transitions out of these and never flags them as stalled.
    _TERMINAL_STATUSES = ("completed", "cancelled")

    # Status values Phase 7 introduces / treats distinctly. ``paused``
    # means "the user (or the bulk-pauser) voluntarily stepped this one
    # aside"; a paused goal is otherwise treated like a normal goal for
    # scheduling — i.e. resumption restores whatever status lived in
    # ``metadata["previous_status"]``.
    _PAUSED_STATUS = "paused"

    # Reason text stored under ``metadata["stall_reason"]`` /
    # ``metadata["recommend_reason"]`` etc. — keys used by Phase 7
    # review bookkeeping. Kept here so tests and callers can refer to
    # them by name.
    _META_PREVIOUS_STATUS = "previous_status"
    _META_PAUSE_REASON = "pause_reason"
    _META_STALL_REASON = "stall_reason"
    _META_RECOMMEND_REASON = "recommend_reason"
    _META_ABANDON_REASON = "abandon_reason"

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
            goal.updated_at = self._now()
            self._save_file()
            self._publish_event("goal.paused", {"goal_id": goal_id, "name": goal.name, "reason": reason})
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
            goal.updated_at = self._now()
            self._save_file()
            self._publish_event("goal.resumed", {"goal_id": goal_id, "name": goal.name, "previous_status": previous})
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
            }

        Goals whose heuristic recommendation equals the current priority
        are NOT included — manual priorities are preserved unless there
        is a clear reason to flag a change (Phase 7 spec: "preserve
        manual priorities unless there is a clear reason to recommend a
        change"). The algorithm is intentionally simple and
        deterministic: bumps are stacked, then mapped to the priority
        rank.

        Heuristic rules (each adds ``+1`` to the bump count for non-
        -active goals; the active goal is left at its current priority
        so Phase 5's selection loop is not disturbed):

            * blocked (Phase 5 ``is_blocked`` returns True)
            * stalled (``_age_seconds`` exceeds the default threshold)
            * paused (this Phase's ``_PAUSED_STATUS``)
        """
        base = now or datetime.now(timezone.utc)
        default_stall = 7 * 24 * 3600  # one week
        # Rank-ordered priority buckets. Lower numeric = higher
        # priority. The +5 ceiling maps any deeply-buried goal to the
        # ``"optional"`` bucket rather than to a synthetic "unknown"
        # tier that the Phase 5 scheduler places at the bottom.
        rank_to_priority = (
            "critical",
            "high",
            "medium",
            "low",
            "optional",
        )
        with self._lock:
            snapshot = list(self._goals.values())
        recs: List[Dict[str, Any]] = []
        for goal in snapshot:
            if goal.status in self._TERMINAL_STATUSES:
                continue
            # Phase 5 active marker takes priority — do not recommend
            # bumping an active goal away from where Freya is currently
            # spending cycles.
            if goal.id == self._active_goal_id:
                continue
            bump = 0
            signals: List[str] = []
            if self.is_blocked(goal.id):
                bump += 1
                signals.append("blocked")
            age = self._age_seconds(goal, now=base)
            if age is not None and age >= default_stall:
                bump += 1
                signals.append("stalled")
            if goal.status == self._PAUSED_STATUS:
                bump += 1
                signals.append("paused")
            if bump == 0:
                continue
            current_idx = min(
                self._priority_rank(goal.priority),
                len(rank_to_priority) - 1,
            )
            recommended_idx = min(
                current_idx + bump,
                len(rank_to_priority) - 1,
            )
            current_priority = rank_to_priority[current_idx]
            recommended_priority = rank_to_priority[recommended_idx]
            if current_priority == recommended_priority:
                # Heuristic agrees with the manual priority — do not
                # emit a recommendation (Phase 7 spec).
                continue
            recs.append({
                "goal_id": goal.id,
                "name": goal.name,
                "current": current_priority,
                "recommended": recommended_priority,
                "reason": (
                    f"signals=[{', '.join(signals)}] → "
                    f"deprioritize by {bump} step(s)"
                ),
            })
        return recs


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
