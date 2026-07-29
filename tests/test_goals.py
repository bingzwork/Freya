"""Tests for the Goal Management module (Phase 1).

Covers the Goal dataclass and GoalStorage save/load/CRUD surface.
"""

import pytest

from app.memory.goals import Goal, GoalStorage


# ---------------------------------------------------------------------------
# Goal dataclass
# ---------------------------------------------------------------------------


class TestGoalDataclass:
    """Tests for the Goal dataclass and serialization helpers."""

    def test_create_minimal(self):
        goal = Goal(id="g1", name="Ship Phase 1")
        assert goal.id == "g1"
        assert goal.name == "Ship Phase 1"
        assert goal.description == ""
        assert goal.status == "pending"
        assert goal.priority == "medium"
        assert goal.parent_goal_id is None
        assert goal.child_goal_ids == []

    def test_create_full(self):
        goal = Goal(
            id="g2",
            name="Finish tests",
            description="All Phase 1 tests pass",
            status="in_progress",
            priority="high",
            parent_goal_id="g1",
            child_goal_ids=["g3", "g4"],
        )
        assert goal.description == "All Phase 1 tests pass"
        assert goal.status == "in_progress"
        assert goal.priority == "high"
        assert goal.parent_goal_id == "g1"
        assert goal.child_goal_ids == ["g3", "g4"]

    def test_child_goal_ids_default_is_independent(self):
        """``field(default_factory=list)`` must not share a list across instances."""
        a = Goal(id="a", name="A")
        b = Goal(id="b", name="B")
        a.child_goal_ids.append("x")
        assert b.child_goal_ids == []

    def test_to_dict_roundtrip(self):
        roundtripped = Goal.from_dict(
            Goal(
                id="g5",
                name="Roundtrip",
                description="back-and-forth",
                status="ready",
                priority="critical",
                parent_goal_id="g0",
                child_goal_ids=["g6"],
            ).to_dict()
        )
        assert roundtripped.id == "g5"
        assert roundtripped.name == "Roundtrip"
        assert roundtripped.description == "back-and-forth"
        assert roundtripped.status == "ready"
        assert roundtripped.priority == "critical"
        assert roundtripped.parent_goal_id == "g0"
        assert roundtripped.child_goal_ids == ["g6"]


# ---------------------------------------------------------------------------
# GoalStorage — fixtures + persistence
# ---------------------------------------------------------------------------


class TestGoalStoragePersistence:
    """Persistence (save / load) across storage instances."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_init_creates_empty_storage(self, store):
        assert store.count() == 0
        assert store.all() == []

    def test_save_writes_file(self, store, tmp_path):
        goal = Goal(id="g1", name="Persist")
        store.save(goal)
        assert (tmp_path / "memory" / "goals.json").exists()

    def test_save_then_load_returns_same_goal(self, store):
        goal = Goal(
            id="g1",
            name="Roundtrip",
            description="persisted",
            status="ready",
            priority="high",
            parent_goal_id="root",
            child_goal_ids=["g2"],
        )
        store.save(goal)

        loaded = store.load("g1")
        assert loaded is not None
        assert loaded.id == "g1"
        assert loaded.name == "Roundtrip"
        assert loaded.description == "persisted"
        assert loaded.status == "ready"
        assert loaded.priority == "high"
        assert loaded.parent_goal_id == "root"
        assert loaded.child_goal_ids == ["g2"]

    def test_load_unknown_id_returns_none(self, store):
        assert store.load("does-not-exist") is None

    def test_save_is_upsert(self, store):
        store.save(Goal(id="g1", name="first"))
        store.save(Goal(id="g1", name="renamed"))
        assert store.count() == 1
        assert store.load("g1").name == "renamed"

    def test_persistence_across_instances(self, tmp_path):
        workspace = str(tmp_path)
        first = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        first.save(Goal(id="g1", name="survives restart"))

        second = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        assert second.count() == 1
        assert second.load("g1").name == "survives restart"

    def test_load_corrupt_file_starts_empty(self, tmp_path):
        workspace = tmp_path
        storage_dir = workspace / "memory"
        storage_dir.mkdir(parents=True)
        (storage_dir / "goals.json").write_text("not valid json", encoding="utf-8")

        store = GoalStorage(workspace=str(workspace), storage_path="memory/goals.json")
        assert store.count() == 0


# ---------------------------------------------------------------------------
# GoalStorage — CRUD verbs
# ---------------------------------------------------------------------------


class TestGoalStorageCRUD:
    """Create / update / delete / list verbs on top of persistence."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_create_assigns_id(self, store):
        goal = store.create(name="Ship Phase 1")
        assert goal.id.startswith("goal_")
        assert goal.name == "Ship Phase 1"
        assert store.count() == 1
        assert store.load(goal.id) is goal

    def test_create_unique_ids(self, store):
        ids = {store.create(name=f"g{i}").id for i in range(20)}
        assert len(ids) == 20

    def test_create_with_all_fields(self, store):
        goal = store.create(
            name="Subgoal",
            description="a child",
            status="in_progress",
            priority="high",
            parent_goal_id="root",
            child_goal_ids=["child-a", "child-b"],
        )
        assert goal.status == "in_progress"
        assert goal.priority == "high"
        assert goal.parent_goal_id == "root"
        assert goal.child_goal_ids == ["child-a", "child-b"]

    def test_list_returns_all(self, store):
        store.create(name="a")
        store.create(name="b")
        store.create(name="c")
        listed = store.list()
        assert {g.name for g in listed} == {"a", "b", "c"}
        assert len(listed) == 3

    def test_list_empty(self, store):
        assert store.list() == []

    def test_update_patches_fields(self, store):
        goal = store.create(name="original", description="d", status="pending", priority="low")
        updated = store.update(
            goal.id,
            name="renamed",
            status="in_progress",
            priority="critical",
        )
        assert updated is not None
        assert updated.name == "renamed"
        assert updated.status == "in_progress"
        assert updated.priority == "critical"
        assert updated.description == "d"  # untouched

        # And the change is on disk
        reloaded = GoalStorage(
            workspace=store.workspace,
            storage_path=str(store.storage_path.relative_to(store.workspace)),
        )
        assert reloaded.load(goal.id).name == "renamed"

    def test_update_unknown_id_returns_none(self, store):
        assert store.update("missing", name="x") is None

    def test_update_child_goal_ids_clears_when_empty_list(self, store):
        goal = store.create(name="g", child_goal_ids=["a", "b"])
        updated = store.update(goal.id, child_goal_ids=[])
        assert updated.child_goal_ids == []

    def test_update_parent_goal_id(self, store):
        goal = store.create(name="g", parent_goal_id="old")
        updated = store.update(goal.id, parent_goal_id="new")
        assert updated.parent_goal_id == "new"

    def test_delete_removes_goal(self, store):
        goal = store.create(name="g")
        assert store.delete(goal.id) is True
        assert store.load(goal.id) is None
        assert store.count() == 0

    def test_delete_unknown_id_returns_false(self, store):
        assert store.delete("missing") is False

    def test_delete_is_persisted(self, store):
        goal = store.create(name="ephemeral")
        store.delete(goal.id)
        reloaded = GoalStorage(
            workspace=store.workspace,
            storage_path=str(store.storage_path.relative_to(store.workspace)),
        )
        assert reloaded.load(goal.id) is None

    def test_crud_roundtrip(self, store):
        """End-to-end smoke: create -> list -> update -> delete -> list."""
        a = store.create(name="alpha")
        b = store.create(name="beta", parent_goal_id=a.id)
        assert {g.name for g in store.list()} == {"alpha", "beta"}

        store.update(b.id, status="blocked")
        assert store.load(b.id).status == "blocked"

        assert store.delete(a.id) is True
        # beta's parent_goal_id still references the deleted alpha by string;
        # Phase 1 does not repair dangling references (left for later phases).
        assert store.load(b.id).parent_goal_id == a.id
        assert sorted(g.name for g in store.list()) == ["beta"]
