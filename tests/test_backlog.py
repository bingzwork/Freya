"""Tests for the Improvement Backlog System."""

import pytest
from datetime import datetime, timezone, timedelta

from app.backlog.improvement_backlog import (
    ImprovementItem,
    ImprovementPriority,
    ImprovementStatus,
    ImprovementType,
    ImprovementBacklog,
)


class TestImprovementPriority:
    """Tests for ImprovementPriority enum."""

    def test_all_priorities(self):
        """Test all priority levels exist."""
        priorities = [
            ImprovementPriority.CRITICAL,
            ImprovementPriority.HIGH,
            ImprovementPriority.MEDIUM,
            ImprovementPriority.LOW,
            ImprovementPriority.BACKLOG,
        ]
        for priority in priorities:
            assert isinstance(priority, ImprovementPriority)

    def test_priority_weights(self):
        """Test priority weights."""
        assert ImprovementPriority.CRITICAL.weight == 100
        assert ImprovementPriority.HIGH.weight == 80
        assert ImprovementPriority.MEDIUM.weight == 50
        assert ImprovementPriority.LOW.weight == 20
        assert ImprovementPriority.BACKLOG.weight == 0

    def test_priority_colors(self):
        """Test priority colors."""
        assert ImprovementPriority.CRITICAL.color == "red"
        assert ImprovementPriority.HIGH.color == "orange"
        assert ImprovementPriority.MEDIUM.color == "yellow"
        assert ImprovementPriority.LOW.color == "light_blue"
        assert ImprovementPriority.BACKLOG.color == "gray"


class TestImprovementStatus:
    """Tests for ImprovementStatus enum."""

    def test_all_statuses(self):
        """Test all status values exist."""
        statuses = [
            ImprovementStatus.PROPOSED,
            ImprovementStatus.APPROVED,
            ImprovementStatus.IN_PROGRESS,
            ImprovementStatus.BLOCKED,
            ImprovementStatus.COMPLETED,
            ImprovementStatus.REJECTED,
            ImprovementStatus.DEFERRED,
        ]
        for status in statuses:
            assert isinstance(status, ImprovementStatus)


class TestImprovementType:
    """Tests for ImprovementType enum."""

    def test_all_types(self):
        """Test all type values exist."""
        types = [
            ImprovementType.BUG_FIX,
            ImprovementType.FEATURE,
            ImprovementType.ENHANCEMENT,
            ImprovementType.REFACTORING,
            ImprovementType.PERFORMANCE,
            ImprovementType.SECURITY,
            ImprovementType.DOCUMENTATION,
            ImprovementType.TESTING,
            ImprovementType.ARCHITECTURE,
            ImprovementType.TECHNICAL_DEBT,
            ImprovementType.USABILITY,
            ImprovementType.COMPLIANCE,
        ]
        for t in types:
            assert isinstance(t, ImprovementType)


class TestImprovementItem:
    """Tests for ImprovementItem."""

    def test_item_creation(self):
        """Test creating an improvement item."""
        item = ImprovementItem(
            title="Fix memory leak",
            description="Fix memory leak in cache module",
            improvement_type=ImprovementType.BUG_FIX,
            priority=ImprovementPriority.HIGH,
            status=ImprovementStatus.PROPOSED,
        )
        assert item.title == "Fix memory leak"
        assert item.improvement_type == ImprovementType.BUG_FIX
        assert item.priority == ImprovementPriority.HIGH
        assert item.item_id.startswith("improvement_")

    def test_item_with_all_fields(self):
        """Test creating an item with all fields."""
        item = ImprovementItem(
            title="Implement caching",
            description="Add Redis caching for performance",
            improvement_type=ImprovementType.PERFORMANCE,
            priority=ImprovementPriority.HIGH,
            estimated_effort=16.0,
            complexity="high",
            impact="high",
            assignee="developer1",
            created_by="manager",
        )
        assert item.estimated_effort == 16.0
        assert item.complexity == "high"
        assert item.assignee == "developer1"

    def test_item_is_active(self):
        """Test checking if item is active."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
            status=ImprovementStatus.PROPOSED,
        )
        assert item.is_active is True

        item.status = ImprovementStatus.COMPLETED
        assert item.is_active is False

    def test_item_is_completed(self):
        """Test checking if item is completed."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
            status=ImprovementStatus.IN_PROGRESS,
        )
        assert item.is_completed is False

        item.status = ImprovementStatus.COMPLETED
        assert item.is_completed is True

    def test_item_is_blocked(self):
        """Test checking if item is blocked."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
            status=ImprovementStatus.PROPOSED,
            blocked_by=["other_item"],
        )
        assert item.is_blocked is True

        item.blocked_by = []
        assert item.is_blocked is False

    def test_item_age_days(self):
        """Test calculating item age."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
            created_at=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        )
        assert item.age_days == 5

    def test_item_score(self):
        """Test calculating item score."""
        # High priority, high impact, low complexity = high score
        item1 = ImprovementItem(
            title="Critical fix",
            improvement_type=ImprovementType.BUG_FIX,
            priority=ImprovementPriority.CRITICAL,
            complexity="low",
            impact="high",
        )

        # Low priority, low impact, high complexity = low score
        item2 = ImprovementItem(
            title="Minor improvement",
            improvement_type=ImprovementType.ENHANCEMENT,
            priority=ImprovementPriority.LOW,
            complexity="high",
            impact="low",
        )

        assert item1.score > item2.score

    def test_item_update_status(self):
        """Test updating item status."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
        )
        item.update_status(ImprovementStatus.IN_PROGRESS)
        assert item.status == ImprovementStatus.IN_PROGRESS

    def test_item_assign(self):
        """Test assigning item to someone."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
        )
        item.assign("developer1")
        assert item.assignee == "developer1"

    def test_item_add_dependency(self):
        """Test adding a dependency."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
        )
        item.add_dependency("other_item")
        assert "other_item" in item.dependencies

    def test_item_add_blocker(self):
        """Test adding a blocker."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
        )
        item.add_blocker("blocking_item")
        assert "blocking_item" in item.blocked_by

    def test_item_add_tag(self):
        """Test adding a tag."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
        )
        item.add_tag("frontend")
        assert "frontend" in item.tags

    def test_item_to_dict(self):
        """Test converting item to dictionary."""
        item = ImprovementItem(
            title="Test",
            improvement_type=ImprovementType.FEATURE,
            priority=ImprovementPriority.HIGH,
        )
        data = item.to_dict()
        assert data["title"] == "Test"
        assert data["improvement_type"] == "feature"
        assert data["priority"] == "high"

    def test_item_from_dict(self):
        """Test creating item from dictionary."""
        data = {
            "item_id": "test_001",
            "title": "Test Item",
            "improvement_type": "bug_fix",
            "priority": "critical",
            "status": "proposed",
        }
        item = ImprovementItem.from_dict(data)
        assert item.item_id == "test_001"
        assert item.title == "Test Item"
        assert item.improvement_type == ImprovementType.BUG_FIX
        assert item.priority == ImprovementPriority.CRITICAL

    def test_item_sorting(self):
        """Test sorting items by score."""
        item1 = ImprovementItem(
            title="High priority",
            improvement_type=ImprovementType.BUG_FIX,
            priority=ImprovementPriority.CRITICAL,
        )
        item2 = ImprovementItem(
            title="Low priority",
            improvement_type=ImprovementType.ENHANCEMENT,
            priority=ImprovementPriority.LOW,
        )

        items = [item2, item1]
        items.sort()  # Uses __lt__ which compares by score

        assert items[0].priority == ImprovementPriority.CRITICAL
        assert items[1].priority == ImprovementPriority.LOW


class TestImprovementBacklog:
    """Tests for ImprovementBacklog."""

    def test_backlog_creation(self):
        """Test creating a backlog."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            assert backlog.count == 0

    def test_add_item(self):
        """Test adding an item."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            item = backlog.add_item(
                title="Fix bug",
                improvement_type=ImprovementType.BUG_FIX,
                priority=ImprovementPriority.HIGH,
            )
            assert item is not None
            assert backlog.count == 1

    def test_get_item(self):
        """Test getting an item by ID."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            item = backlog.add_item(title="Test", improvement_type=ImprovementType.FEATURE)
            retrieved = backlog.get_item(item.item_id)
            assert retrieved is not None
            assert retrieved.title == "Test"

    def test_update_item(self):
        """Test updating an item."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            item = backlog.add_item(title="Test", improvement_type=ImprovementType.FEATURE)
            result = backlog.update_item(item.item_id, priority=ImprovementPriority.CRITICAL)
            assert result is True
            updated = backlog.get_item(item.item_id)
            assert updated.priority == ImprovementPriority.CRITICAL

    def test_remove_item(self):
        """Test removing an item."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            item = backlog.add_item(title="Test", improvement_type=ImprovementType.FEATURE)
            result = backlog.remove_item(item.item_id)
            assert result is True
            assert backlog.count == 0

    def test_list_items(self):
        """Test listing items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(title="Item 1", improvement_type=ImprovementType.FEATURE)
            backlog.add_item(title="Item 2", improvement_type=ImprovementType.BUG_FIX)
            items = backlog.list_items()
            assert len(items) == 2

    def test_list_items_by_status(self):
        """Test listing items by status."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Active",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.PROPOSED,
            )
            backlog.add_item(
                title="Completed",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.COMPLETED,
            )
            active = backlog.list_items(status=ImprovementStatus.PROPOSED)
            assert len(active) == 1
            assert active[0].status == ImprovementStatus.PROPOSED

    def test_list_items_by_priority(self):
        """Test listing items by priority."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="High",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.HIGH,
            )
            backlog.add_item(
                title="Low",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.LOW,
            )
            high = backlog.list_items(priority=ImprovementPriority.HIGH)
            assert len(high) == 1

    def test_list_items_by_type(self):
        """Test listing items by type."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(title="Bug", improvement_type=ImprovementType.BUG_FIX)
            backlog.add_item(title="Feature", improvement_type=ImprovementType.FEATURE)
            bugs = backlog.list_items(improvement_type=ImprovementType.BUG_FIX)
            assert len(bugs) == 1

    def test_list_active(self):
        """Test listing active items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Active",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.PROPOSED,
            )
            backlog.add_item(
                title="Completed",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.COMPLETED,
            )
            active = backlog.list_active()
            assert len(active) == 1

    def test_list_completed(self):
        """Test listing completed items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Active",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.PROPOSED,
            )
            backlog.add_item(
                title="Completed",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.COMPLETED,
            )
            completed = backlog.list_completed()
            assert len(completed) == 1

    def test_list_by_assignee(self):
        """Test listing items by assignee."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Task 1",
                improvement_type=ImprovementType.FEATURE,
                assignee="developer1",
            )
            backlog.add_item(
                title="Task 2",
                improvement_type=ImprovementType.FEATURE,
                assignee="developer2",
            )
            dev1_tasks = backlog.list_by_assignee("developer1")
            assert len(dev1_tasks) == 1

    def test_get_next_item(self):
        """Test getting the next item to work on."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Ready",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.HIGH,
                status=ImprovementStatus.PROPOSED,
            )
            backlog.add_item(
                title="In Progress",
                improvement_type=ImprovementType.FEATURE,
                status=ImprovementStatus.IN_PROGRESS,
            )
            next_item = backlog.get_next_item()
            assert next_item is not None
            assert next_item.title == "Ready"

    def test_get_high_priority_items(self):
        """Test getting high priority items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="High 1",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.HIGH,
            )
            backlog.add_item(
                title="High 2",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.HIGH,
            )
            backlog.add_item(
                title="Low",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.LOW,
            )
            high = backlog.get_high_priority_items()
            assert len(high) == 2

    def test_get_critical_items(self):
        """Test getting critical items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Critical",
                improvement_type=ImprovementType.BUG_FIX,
                priority=ImprovementPriority.CRITICAL,
            )
            backlog.add_item(
                title="High",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.HIGH,
            )
            critical = backlog.get_critical_items()
            assert len(critical) == 1

    def test_get_summary(self):
        """Test getting backlog summary."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Bug",
                improvement_type=ImprovementType.BUG_FIX,
                priority=ImprovementPriority.HIGH,
                status=ImprovementStatus.PROPOSED,
            )
            backlog.add_item(
                title="Feature",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.MEDIUM,
                status=ImprovementStatus.IN_PROGRESS,
            )
            summary = backlog.get_summary()
            assert summary["total_items"] == 2
            assert summary["active_items"] == 2
            assert "by_status" in summary
            assert "by_priority" in summary
            assert "by_type" in summary

    def test_get_distribution(self):
        """Test getting backlog distribution."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Bug",
                improvement_type=ImprovementType.BUG_FIX,
                priority=ImprovementPriority.HIGH,
            )
            backlog.add_item(
                title="Feature",
                improvement_type=ImprovementType.FEATURE,
                priority=ImprovementPriority.MEDIUM,
            )
            distribution = backlog.get_distribution()
            assert "by_status" in distribution
            assert "by_priority" in distribution
            assert "by_type" in distribution

    def test_clear(self):
        """Test clearing the backlog."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(title="Test", improvement_type=ImprovementType.FEATURE)
            assert backlog.count == 1
            backlog.clear()
            assert backlog.count == 0

    def test_search(self):
        """Test searching items."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Fix cache bug",
                description="Memory leak in cache module",
                improvement_type=ImprovementType.BUG_FIX,
            )
            backlog.add_item(
                title="Add feature",
                description="New user interface",
                improvement_type=ImprovementType.FEATURE,
            )
            results = backlog.list_items(search="cache")
            assert len(results) == 1
            assert "cache" in results[0].title.lower() or "cache" in results[0].description.lower()

    def test_limit(self):
        """Test limiting results."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            for i in range(10):
                backlog.add_item(
                    title=f"Item {i}",
                    improvement_type=ImprovementType.FEATURE,
                )
            results = backlog.list_items(limit=5)
            assert len(results) == 5

    def test_tags_filter(self):
        """Test filtering by tags."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(
                title="Frontend task",
                improvement_type=ImprovementType.FEATURE,
                tags=["frontend", "ui"],
            )
            backlog.add_item(
                title="Backend task",
                improvement_type=ImprovementType.FEATURE,
                tags=["backend", "api"],
            )
            frontend = backlog.list_items(tags=["frontend"])
            assert len(frontend) == 1

    def test_persistence(self):
        """Test that backlog persists to disk."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog1 = ImprovementBacklog(workspace=tmpdir)
            backlog1.add_item(title="Test", improvement_type=ImprovementType.FEATURE)

            # Create a new backlog pointing to the same workspace
            backlog2 = ImprovementBacklog(workspace=tmpdir)
            assert backlog2.count == 1

    def test_export_import(self):
        """Test exporting and importing data."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)
            backlog.add_item(title="Test", improvement_type=ImprovementType.FEATURE)

            # Export
            data = backlog.export_to_dict()
            assert "items" in data
            assert "summary" in data

            # Create new backlog and import
            backlog.clear()
            assert backlog.count == 0

            backlog.import_from_dict(data)
            assert backlog.count == 1


class TestImprovementBacklogIntegration:
    """Integration tests for the improvement backlog system."""

    def test_full_workflow(self):
        """Test a complete backlog workflow."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            backlog = ImprovementBacklog(workspace=tmpdir)

            # Step 1: Add items
            bug = backlog.add_item(
                title="Fix SQL injection vulnerability",
                description="Sanitize user input in login endpoint",
                improvement_type=ImprovementType.SECURITY,
                priority=ImprovementPriority.CRITICAL,
                complexity="medium",
                impact="high",
                estimated_effort=8.0,
                created_by="security_auditor",
            )

            feature = backlog.add_item(
                title="Add caching layer",
                description="Implement Redis caching for API endpoints",
                improvement_type=ImprovementType.PERFORMANCE,
                priority=ImprovementPriority.HIGH,
                complexity="high",
                impact="high",
                estimated_effort=16.0,
                dependencies=[bug.item_id],  # Depends on security fix
            )

            # Step 2: Update items
            backlog.update_item(bug.item_id, status=ImprovementStatus.APPROVED)
            backlog.update_item(bug.item_id, assignee="developer1")

            # Step 3: List and filter
            active = backlog.list_active()
            assert len(active) == 2

            high_priority = backlog.list_items(priority=ImprovementPriority.HIGH)
            assert len(high_priority) == 1

            # Step 4: Get summary
            summary = backlog.get_summary()
            assert summary["total_items"] == 2
            assert summary["total_estimated_effort_hours"] == 24.0

            # Step 5: Complete an item
            backlog.update_item(bug.item_id, status=ImprovementStatus.COMPLETED)
            backlog.update_item(bug.item_id, actual_effort=6.0)

            completed = backlog.list_completed()
            assert len(completed) == 1

            # Step 6: Verify item properties
            updated_bug = backlog.get_item(bug.item_id)
            assert updated_bug.is_completed
            assert updated_bug.actual_effort == 6.0

            # Step 7: Get next item
            next_item = backlog.get_next_item()
            assert next_item is not None
            assert next_item.title == "Add caching layer"
