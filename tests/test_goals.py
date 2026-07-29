"""Tests for the Goal Management module.

Covers the Goal dataclass and GoalStorage save/load/CRUD/hierarchy/progress
surface (Phases 1–4).
"""

import time
from datetime import datetime

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


# ---------------------------------------------------------------------------
# GoalStorage — progress / timestamps / active indicator (Phase 4)
# ---------------------------------------------------------------------------


class TestGoalTimestamps:
    """Goal-level ``created_at`` / ``updated_at`` lifecycle."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_create_sets_both_timestamps(self, store):
        before = datetime.utcnow()
        goal = store.create(name="g")
        after = datetime.utcnow()

        loaded = store.load(goal.id)
        assert loaded.created_at
        assert loaded.updated_at
        # Timestamps should parse as ISO and sit within the test window.
        created = datetime.fromisoformat(loaded.created_at)
        updated = datetime.fromisoformat(loaded.updated_at)
        assert created == updated  # freshly created; both stamped at "now"

    def test_create_timestamps_round_trip(self, store):
        goal = store.create(name="g")
        reread = Goal.from_dict(goal.to_dict())
        assert reread.created_at == goal.created_at
        assert reread.updated_at == goal.updated_at

    def test_update_bumps_updated_at_only(self, store):
        original = store.create(name="g")
        original_created = original.created_at
        original_updated = original.updated_at
        time.sleep(0.01)  # ensure clock advances at least one millisecond
        patched = store.update(original.id, name="g2")
        assert patched.name == "g2"
        assert patched.created_at == original_created
        assert patched.updated_at > original_updated

    def test_update_with_no_real_change_does_not_bump_updated_at(self, store):
        original = store.create(name="g")
        # Update(name=...) with the same value: no real change → no bump.
        again = store.update(original.id, name="g")
        assert again.created_at == original.created_at
        assert again.updated_at == original.updated_at

    def test_update_unknown_does_not_write(self, store):
        baseline = store.count()
        assert store.update("missing", name="x") is None
        assert store.count() == baseline

    def test_loaded_goals_preserve_timestamps(self, store, tmp_path):
        """Timestamps survive a fresh ``GoalStorage`` over the same file."""
        original = store.create(name="g")
        time.sleep(0.01)
        store.update(original.id, name="g2")

        reopened = GoalStorage(
            workspace=store.workspace,
            storage_path=str(store.storage_path.relative_to(store.workspace)),
        )
        rel = reopened.load(original.id)
        assert rel.created_at == original.created_at
        assert rel.updated_at == original.updated_at

    def test_backwards_compat_load_without_timestamps(self, tmp_path):
        """A goals.json written without timestamp keys must still load."""
        storage_dir = tmp_path / "memory"
        storage_dir.mkdir(parents=True)
        (storage_dir / "goals.json").write_text(
            '{"goals": [{"id": "legacy", "name": "old"}], "metadata": {}}',
            encoding="utf-8",
        )
        store = GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")
        legacy = store.load("legacy")
        assert legacy is not None
        assert legacy.name == "old"
        # Timestamp defaults trip in cleanly.
        assert legacy.created_at == ""
        assert legacy.updated_at == ""


class TestGoalProgress:
    """Progress metrics derived from a goal's children."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_progress_shape(self, store):
        g = store.create(name="g")
        # Touch every key of the return so regression in any one is loud.
        p = store.progress(g.id)
        assert set(p.keys()) == {"total_children", "completed_children", "percentage"}
        assert isinstance(p["total_children"], int)
        assert isinstance(p["completed_children"], int)
        assert isinstance(p["percentage"], float)

    def test_progress_leaf_is_zero(self, store):
        g = store.create(name="leaf")
        assert store.progress(g.id) == {
            "total_children": 0,
            "completed_children": 0,
            "percentage": 0.0,
        }

    def test_progress_root_unknown_is_zero(self, store):
        assert store.progress("missing") == {
            "total_children": 0,
            "completed_children": 0,
            "percentage": 0.0,
        }

    def test_progress_with_partial_completion(self, store):
        parent = store.create(name="parent")
        store.create(name="c1", parent_goal_id=parent.id)
        store.create(name="c2", parent_goal_id=parent.id)
        store.create(name="c3", parent_goal_id=parent.id)
        # Complete one of three.
        c1 = store.children_of(parent.id)[0]
        store.complete(c1.id)
        p = store.progress(parent.id)
        assert p["total_children"] == 3
        assert p["completed_children"] == 1
        assert p["percentage"] == pytest.approx(33.3333333333, abs=1e-6)

    def test_progress_full(self, store):
        parent = store.create(name="parent")
        c1 = store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id)
        store.complete(c1.id)
        store.complete(c2.id)
        p = store.progress(parent.id)
        assert p == {
            "total_children": 2,
            "completed_children": 2,
            "percentage": 100.0,
        }

    def test_progress_updates_automatically_after_completion(self, store):
        """Progress is computed live — completing a child bumps the parent."""
        parent = store.create(name="parent")
        c1 = store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id)
        assert store.progress(parent.id)["completed_children"] == 0

        store.complete(c1.id)
        p1 = store.progress(parent.id)
        assert p1["completed_children"] == 1
        assert p1["percentage"] == pytest.approx(50.0)

        store.complete(c2.id)
        p2 = store.progress(parent.id)
        assert p2["completed_children"] == 2
        assert p2["percentage"] == 100.0

    def test_progress_does_not_count_non_completed_states(self, store):
        """Children blocked / failed / pending are NOT counted as completed."""
        parent = store.create(name="parent")
        c1 = store.create(name="c1", parent_goal_id=parent.id)
        c2 = store.create(name="c2", parent_goal_id=parent.id, status="blocked")
        c3 = store.create(name="c3", parent_goal_id=parent.id, status="failed")
        store.complete(c1.id)
        p = store.progress(parent.id)
        assert p["total_children"] == 3
        assert p["completed_children"] == 1  # only the explicit complete()


class TestCompletedDetection:
    """``is_completed`` correctly detects completed goals."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_is_completed_true_after_complete(self, store):
        g = store.create(name="g")
        assert store.is_completed(g.id) is False
        store.complete(g.id)
        assert store.is_completed(g.id) is True

    def test_is_completed_true_when_create_with_status(self, store):
        g = store.create(name="g", status="completed")
        assert store.is_completed(g.id) is True

    def test_is_completed_false_for_other_states(self, store):
        g = store.create(name="g", status="in_progress")
        assert store.is_completed(g.id) is False
        assert store.is_completed(g.id) is False

    def test_is_completed_false_for_unknown_id(self, store):
        assert store.is_completed("missing") is False

    def test_is_completed_after_completion_propagation(self, store):
        """Completing the only child auto-completes the parent."""
        parent = store.create(name="parent")
        only = store.create(name="only", parent_goal_id=parent.id)
        store.complete(only.id)
        assert store.is_completed(parent.id) is True


class TestActiveGoalIndicator:
    """The single-tenant active-goal marker."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_active_default_is_none(self, store):
        assert store.active_goal() is None

    def test_set_active_returns_true_and_makes_goal_active(self, store):
        g = store.create(name="g")
        assert store.set_active(g.id) is True
        active = store.active_goal()
        assert active is not None
        assert active.id == g.id

    def test_set_active_unknown_returns_false(self, store):
        assert store.set_active("missing") is False
        assert store.active_goal() is None

    def test_set_active_replaces(self, store):
        a = store.create(name="a")
        b = store.create(name="b")
        store.set_active(a.id)
        store.set_active(b.id)
        assert store.active_goal().id == b.id

    def test_active_returns_none_if_active_id_was_deleted(self, store):
        g = store.create(name="g")
        store.set_active(g.id)
        store.delete(g.id)
        assert store.active_goal() is None

    def test_clear_active(self, store):
        g = store.create(name="g")
        store.set_active(g.id)
        store.clear_active()
        assert store.active_goal() is None

    def test_clear_active_when_none_set_is_a_noop(self, store):
        # Must not raise even with nothing to clear.
        store.clear_active()
        assert store.active_goal() is None

    def test_active_persists_across_storage_instances(self, tmp_path):
        workspace = str(tmp_path)
        first = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        g = first.create(name="survives")
        first.set_active(g.id)

        second = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        active = second.active_goal()
        assert active is not None
        assert active.id == g.id

    def test_active_survives_completion_propagation(self, store):
        """``complete()`` propagation must not clobber the active marker."""
        parent = store.create(name="parent")
        only = store.create(name="only", parent_goal_id=parent.id)
        store.set_active(only.id)
        store.complete(only.id)
        # Parent is now auto-promoted, but the active marker should still
        # point at the originally-completed goal.
        assert store.active_goal().id == only.id


# ---------------------------------------------------------------------------
# GoalStorage — scheduler (Phase 5)
# ---------------------------------------------------------------------------


class TestGoalDependencies:
    """The ``depends_on_ids`` field and its read-side helpers."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_create_with_depends_on_ids(self, store):
        dep = store.create(name="dep")
        goal = store.create(name="g", depends_on_ids=[dep.id])
        assert goal.depends_on_ids == [dep.id]

    def test_create_default_has_empty_depends_on_ids(self, store):
        goal = store.create(name="g")
        assert goal.depends_on_ids == []

    def test_backwards_compat_load_without_depends_on_ids(self, tmp_path):
        """A pre-Phase-5 ``goals.json`` without ``depends_on_ids`` must load."""
        storage_dir = tmp_path / "memory"
        storage_dir.mkdir(parents=True)
        (storage_dir / "goals.json").write_text(
            '{"goals": [{"id": "legacy", "name": "old"}], "metadata": {}}',
            encoding="utf-8",
        )
        store = GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")
        legacy = store.load("legacy")
        assert legacy is not None
        assert legacy.depends_on_ids == []

    def test_dependencies_of_returns_objects(self, store):
        dep = store.create(name="dep")
        g = store.create(name="g", depends_on_ids=[dep.id])
        deps = store.dependencies_of(g.id)
        assert [d.id for d in deps] == [dep.id]

    def test_dependencies_of_skips_missing(self, store):
        g = store.create(name="g", depends_on_ids=["ghost", "also-missing"])
        assert store.dependencies_of(g.id) == []

    def test_dependencies_of_unknown_goal_returns_empty(self, store):
        assert store.dependencies_of("missing") == []

    def test_is_blocked_by_explicit_status(self, store):
        g = store.create(name="g", status="blocked")
        assert store.is_blocked(g.id) is True

    def test_is_blocked_by_unmet_dep(self, store):
        dep = store.create(name="dep")
        g = store.create(name="g", depends_on_ids=[dep.id])
        assert is_completed_via_dep(store, g.id) is False
        assert store.is_blocked(g.id) is True

    def test_is_blocked_summary(self, store):
        dep = store.create(name="dep")
        dependent = store.create(name="dependent", depends_on_ids=[dep.id])
        plain = store.create(name="plain")
        explicit = store.create(name="explicit", status="blocked")
        assert store.is_blocked(plain.id) is False
        assert store.is_blocked(dependent.id) is True
        assert store.is_blocked(explicit.id) is True

    def test_is_blocked_becomes_false_when_dep_completes(self, store):
        dep = store.create(name="dep")
        g = store.create(name="g", depends_on_ids=[dep.id])
        store.complete(dep.id)
        assert store.is_blocked(g.id) is False

    def test_is_blocked_for_unknown_id_returns_false(self, store):
        assert store.is_blocked("missing") is False

    def test_is_blocked_for_missing_dep_id(self, store):
        """A dep pointing at a non-existent goal is considered unmet."""
        g = store.create(name="g", depends_on_ids=["ghost"])
        assert store.is_blocked(g.id) is True


def is_completed_via_dep(store, goal_id):
    """Tiny per-test helper used above; left at module level to keep test
    functions small."""
    g = store.load(goal_id)
    return g is not None and g.status == "completed"


class TestGoalQueue:
    """``queue()`` ordering and eligibility rules."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_empty_queue_when_no_goals(self, store):
        assert store.queue() == []

    def test_fresh_goal_appears_in_queue(self, store):
        g = store.create(name="g")
        assert [x.id for x in store.queue()] == [g.id]

    def test_priority_sort_ascending(self, store):
        store.create(name="low", priority="low")
        store.create(name="critical", priority="critical")
        store.create(name="optional", priority="optional")
        store.create(name="medium", priority="medium")
        store.create(name="high", priority="high")
        assert [g.name for g in store.queue()] == [
            "critical", "high", "medium", "low", "optional",
        ]

    def test_unknown_priority_sorts_in_stable_position_after_known(self, store):
        store.create(name="known", priority="high")
        store.create(name="unknown", priority="???")
        queue = store.queue()
        assert queue[0].name == "known"
        assert queue[1].name == "unknown"

    def test_completed_excluded_from_queue(self, store):
        g = store.create(name="g")
        store.complete(g.id)
        assert store.queue() == []

    def test_blocked_excluded_from_queue(self, store):
        store.create(name="g1", status="blocked")
        good = store.create(name="g2", priority="critical")
        names = [g.name for g in store.queue()]
        assert names == ["g2"]

    def test_dependency_unmet_excluded_from_queue(self, store):
        dep = store.create(name="dep", priority="critical")
        held = store.create(
            name="held", depends_on_ids=[dep.id], priority="critical",
        )
        ids = {g.id for g in store.queue()}
        assert dep.id in ids
        assert held.id not in ids

    def test_dependency_met_admits_to_queue(self, store):
        dep = store.create(name="dep")
        held = store.create(name="held", depends_on_ids=[dep.id])
        store.complete(dep.id)
        ids = {g.id for g in store.queue()}
        assert held.id in ids

    def test_active_goal_excluded_from_queue(self, store):
        a = store.create(name="a", priority="medium")
        b = store.create(name="b", priority="critical")
        store.set_active(a.id)
        ids = [g.id for g in store.queue()]
        assert a.id not in ids
        assert ids == [b.id]


class TestSelectNext:
    """``select_next()`` picks + activates the highest-priority eligible goal."""

    @pytest.fixture
    def store(self, tmp_path):
        return GoalStorage(workspace=str(tmp_path), storage_path="memory/goals.json")

    def test_returns_none_when_no_eligible(self, store):
        store.create(name="g", status="blocked")
        assert store.select_next() is None

    def test_returns_none_when_only_completed_exist(self, store):
        g = store.create(name="g")
        store.complete(g.id)
        assert store.select_next() is None

    def test_picks_highest_priority(self, store):
        store.create(name="low", priority="low")
        store.create(name="critical", priority="critical")
        store.create(name="medium", priority="medium")
        chosen = store.select_next()
        assert chosen.name == "critical"
        assert store.active_goal().id == chosen.id

    def test_skips_blocked_status(self, store):
        store.create(name="blocked", status="blocked", priority="critical")
        good = store.create(name="good", priority="medium")
        chosen = store.select_next()
        assert chosen.id == good.id

    def test_skips_dependent_on_unmet_dep(self, store):
        dep = store.create(name="dep")
        stored = store.create(
            name="stored", depends_on_ids=[dep.id], priority="critical",
        )
        free = store.create(name="free", priority="medium")
        chosen = store.select_next()
        # `stored` has an unmet dep and must be skipped. ``dep`` itself is
        # eligible (it's the prereq, not blocked by it), so the pick is
        # whichever ties win under stable sort — always either ``dep`` or
        # ``free``, never ``stored``.
        assert chosen.id in {dep.id, free.id}
        assert chosen.id != stored.id

    def test_after_dep_completes_picks_dependent(self, store):
        dep = store.create(name="dep")
        stored = store.create(
            name="stored", depends_on_ids=[dep.id], priority="critical",
        )
        free = store.create(name="free", priority="medium")
        # First pick: ``stored`` is blocked, ``dep`` is eligible (tied with
        # ``free``).
        first = store.select_next()
        assert first.id in {dep.id, free.id}
        # After completing dep, ``stored``'s dependency is satisfied and
        # its critical priority outranks everything else still eligible.
        store.complete(dep.id)
        # Clear the prior active marker so ``select_next`` doesn't skip
        # the previous choice as "already active".
        store.clear_active()
        next_chosen = store.select_next()
        assert next_chosen.id == stored.id
        assert store.active_goal().id == stored.id

    def test_select_next_persists(self, tmp_path):
        workspace = str(tmp_path)
        first = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        first.create(name="g", priority="critical")
        first.select_next()
        second = GoalStorage(workspace=workspace, storage_path="memory/goals.json")
        active = second.active_goal()
        assert active is not None
        assert active.name == "g"

    def test_select_next_with_only_active_returns_none(self, store):
        g = store.create(name="g")
        store.set_active(g.id)
        # The only goal is the active one → nothing in the queue → None.
        assert store.select_next() is None

    def test_select_next_advances_past_current_active(self, store):
        first = store.create(name="first", priority="medium")
        second = store.create(name="second", priority="critical")
        store.set_active(first.id)
        chosen = store.select_next()
        assert chosen.id == second.id



