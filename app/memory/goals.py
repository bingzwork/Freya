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
    """

    id: str
    name: str
    description: str = ""
    status: str = "pending"
    priority: str = "medium"
    parent_goal_id: Optional[str] = None
    child_goal_ids: List[str] = field(default_factory=list)

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

    def _save_file(self) -> None:
        """Atomic write of the in-memory map to disk."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        payload = {
            "goals": [g.to_dict() for g in self._goals.values()],
            "metadata": {
                "count": len(self._goals),
                "last_updated": self._now(),
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
    ) -> Goal:
        """Create a new goal with a generated id and persist it.

        ``id`` is allocated via ``uuid4().hex[:12]`` (matches the
        ``goal_<12hex>`` shape used elsewhere — see ``uuid.uuid4``).
        """
        with self._lock:
            import uuid

            goal = Goal(
                id=f"goal_{uuid.uuid4().hex[:12]}",
                name=name,
                description=description,
                status=status,
                priority=priority,
                parent_goal_id=parent_goal_id,
                child_goal_ids=list(child_goal_ids) if child_goal_ids else [],
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
    ) -> Optional[Goal]:
        """Patch mutable fields on an existing goal and persist it.

        Only the fields explicitly passed (i.e. not ``None``) are written;
        passing ``child_goal_ids=[]`` explicitly clears the list. Returns
        the updated ``Goal`` or ``None`` if ``goal_id`` does not exist.
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            if name is not None:
                goal.name = name
            if description is not None:
                goal.description = description
            if status is not None:
                goal.status = status
            if priority is not None:
                goal.priority = priority
            if parent_goal_id is not None:
                goal.parent_goal_id = parent_goal_id
            if child_goal_ids is not None:
                goal.child_goal_ids = list(child_goal_ids)
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

