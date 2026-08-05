"""Goal persistence layer - JSON file storage with EventBus integration."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, ComponentInfo, ComponentType, HealthCheck, HealthResult, HealthStatus

from app.memory.goals.models import Goal


class GoalPersistence:
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
        self._job_service = job_service or get_job_service()
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
                component="memory.goals",
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
                component="memory.goals",
                status=HealthStatus.HEALTHY,
                message="GoalStorage operational",
                metadata={"goal_count": len(self._goals), "storage_exists": self.storage_path.exists()}
            )
        except Exception as e:
            return HealthResult(
                name="goal_storage_health",
                component="memory.goals",
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
        existing_job = self._job_service.get_job("goal_storage_persist")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
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

    @property
    def goals(self) -> Dict[str, Goal]:
        """Access to internal goals dict (for mixins)."""
        return self._goals

    @property
    def active_goal_id(self) -> Optional[str]:
        """Access to active goal id (for mixins)."""
        return self._active_goal_id

    @active_goal_id.setter
    def active_goal_id(self, value: Optional[str]) -> None:
        with self._lock:
            self._active_goal_id = value
            self._save_file()

    @property
    def lock(self) -> threading.RLock:
        """Lock for thread safety (for mixins)."""
        return self._lock