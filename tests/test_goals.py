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


# ---------------------------------------------------------------------------
# GoalStorage — hierarchy / tree (Phase 3)
# ---------------------------------------------------------------------------


class TestGoalStorageHierarchy:
    """Goal tree reads + automatic upward completion propagation."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    # --- read helpers -----------------------------------------------------

    def test_parent_of_root_is_none(self, store):
        root = store.create(name="root")
        assert store.parent_of(root.id) is None

    def test_parent_of_child_returns_parent(self, store):
        parent = store.create(name="p")
        child = store.create(name="c", parent_goal_id=parent.id)
        assert store.parent_of(child.id).id == parent.id

    def test_parent_of_unknown_returns_none(self, store):
        assert store.parent_of("missing") is None

    def test_children_of(self, store):
        parent = store.create(name="p")
        c1 = store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id)
        unrelated = store.create(name="unrelated")
        ids = {g.id for g in store.children_of(parent.id)}
        assert ids == {c1.id, c2.id}
        assert store.children_of(unrelated.id) == []
        assert store.children_of("missing") == []

    def test_children_of_derived_from_parent_goal_id(self, store):
        """Phase 3 derives children by scan, not from the parent's
        self-reported list — re-parenting / ``child_goal_ids`` mismatches
        are ignored on the read side."""
        parent = store.create(name="p")
        child = store.create(name="c", parent_goal_id=parent.id)
        # Plant a phantom / wrong-side id on the parent's list and clear
        # the child's parent pointer (via direct write — ``update()`` treats
        # ``None`` as "leave unchanged" by Phase-1 design).
        store.update(parent.id, child_goal_ids=[child.id, "ghost"])
        store._goals[child.id].parent_goal_id = None
        assert store.children_of(parent.id) == []

    def test_descendants_of_includes_all_levels(self, store):
        root = store.create(name="root")
        mid = store.create(name="mid", parent_goal_id=root.id)
        leaf1 = store.create(name="leaf1", parent_goal_id=mid.id)
        leaf2 = store.create(name="leaf2", parent_goal_id=mid.id)
        another = store.create(name="another", parent_goal_id=root.id)
        ids = {g.id for g in store.descendants_of(root.id)}
        assert ids == {mid.id, leaf1.id, leaf2.id, another.id}

    def test_descendants_of_leaf_is_empty(self, store):
        leaf = store.create(name="leaf")
        assert store.descendants_of(leaf.id) == []

    def test_descendants_of_unknown_is_empty(self, store):
        assert store.descendants_of("missing") == []

    # --- completion propagation -------------------------------------------

    def test_complete_sets_leaf_status(self, store):
        goal = store.create(name="leaf")
        completed = store.complete(goal.id)
        assert completed.status == "completed"
        assert store.load(goal.id).status == "completed"

    def test_complete_unknown_returns_none(self, store):
        assert store.complete("missing") is None

    def test_complete_idempotent(self, store):
        goal = store.create(name="leaf", status="in_progress")
        store.complete(goal.id)
        # Second call should not raise and should still report "completed"
        assert store.complete(goal.id).status == "completed"

    def test_complete_propagates_when_all_children_done(self, store):
        parent = store.create(name="parent")
        c1 = store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id)
        store.complete(c1.id)
        # Parent should not yet be completed; one child still pending.
        assert store.load(parent.id).status != "completed"
        store.complete(c2.id)
        # Now both children are "completed" → parent auto-completes.
        assert store.load(parent.id).status == "completed"

    def test_complete_does_not_propagate_with_pending_child(self, store):
        parent = store.create(name="parent")
        store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id)
        # Mark c2 blocked first, then complete it
        store.update(c2.id, status="blocked")
        store.complete(c2.id)
        # c1 still pending → parent must NOT auto-complete even if all
        # other children are in whatever non-completed state.
        assert store.load(parent.id).status != "completed"

    def test_complete_propagates_through_nested_chain(self, store):
        root = store.create(name="root")
        mid = store.create(name="mid", parent_goal_id=root.id)
        leaf = store.create(name="leaf", parent_goal_id=mid.id)
        # Root has only one recorded child: mid. Mid has only: leaf.
        store.complete(leaf.id)
        assert store.load(mid.id).status == "completed"
        assert store.load(root.id).status == "completed"

    def test_complete_stops_at_first_incomplete_split(self, store):
        root = store.create(name="root")
        mid_a = store.create(name="mid_a", parent_goal_id=root.id)
        mid_b = store.create(name="mid_b", parent_goal_id=root.id)
        leaf = store.create(name="leaf_a", parent_goal_id=mid_a.id)
        # Complete only the leaf under mid_a → mid_a propagates, root does
        # not (mid_b has no completed children yet).
        store.complete(leaf.id)
        assert store.load(mid_a.id).status == "completed"
        assert store.load(mid_b.id).status != "completed"
        assert store.load(root.id).status != "completed"

    def test_complete_propagation_persists_to_disk(self, store, tmp_path):
        parent = store.create(name="parent")
        only = store.create(name="only", parent_goal_id=parent.id)
        store.complete(only.id)
        # Re-open storage from the same file; parent must already be "completed".
        reopened = GoalStorage(
            workspace=store.workspace,
            storage_path=str(store.storage_path.relative_to(store.workspace)),
        )
        assert reopened.load(parent.id).status == "completed"

    def test_complete_parent_with_no_observed_children_does_not_promote(self, store):
        """A parent with no goal pointing at it via ``parent_goal_id``
        must not auto-complete via propagation — there is nothing to
        propagate from.
        """
        orphan_parent = store.create(name="orphan_parent")
        leaf = store.create(name="leaf", status="completed")
        # ``leaf`` does NOT reference orphan_parent; orphan_parent has no
        # observed children. Completing leaf must not touch orphan_parent.
        store._goals[leaf.id].parent_goal_id = orphan_parent.id
        # Manually re-parent to a separate parent so orphan_parent has zero
        # observed children after this setup.
        store._goals[leaf.id].parent_goal_id = None
        store.complete(leaf.id)
        assert store.load(orphan_parent.id).status != "completed"

    def test_complete_parent_with_zero_observed_children_does_not_promote(self, store):
        """Clean repro of the "no observed children" semantic."""
        orphan_parent = store.create(name="orphan_parent")
        leaf = store.create(name="leaf", parent_goal_id=None)
        store.complete(leaf.id)
        assert store.load(orphan_parent.id).status != "completed"

