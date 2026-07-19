"""Tests for the Reviewer System."""

from datetime import datetime, timezone, timedelta
from typing import Optional

import pytest
import tempfile

from app.reviewer.review_request import (
    ReviewRequest,
    ReviewStatus,
    ReviewPriority,
    ReviewType,
)
from app.reviewer.review import (
    Review,
    ReviewComment,
    ReviewDecision,
)
from app.reviewer.reviewer_assigner import (
    ReviewerAssigner,
    ReviewerPool,
    Reviewer,
    AssignmentStrategy,
)
from app.reviewer.review_tracker import (
    ReviewTracker,
    ReviewMetrics,
)
from app.reviewer.checklist import (
    ReviewChecklist,
    ChecklistItem,
)
from app.reviewer.review_manager import (
    ReviewManager,
    ReviewConfig,
)


class TestReviewRequest:
    """Tests for ReviewRequest."""

    def test_request_creation(self):
        """Test creating a review request."""
        request = ReviewRequest(
            title="Review my PR",
            author="testuser",
        )
        assert request.title == "Review my PR"
        assert request.author == "testuser"
        assert request.id.startswith("review_")

    def test_request_with_all_fields(self):
        """Test creating a request with all fields."""
        request = ReviewRequest(
            title="Review PR",
            author="testuser",
            description="Please review my changes",
            status=ReviewStatus.PENDING,
            priority=ReviewPriority.HIGH,
            review_type=ReviewType.CODE_REVIEW,
            repository="myrepo",
            branch="feature-branch",
            commit_hash="abc123",
            pull_request_id="123",
            files=["file1.py", "file2.py"],
        )
        assert request.repository == "myrepo"
        assert request.branch == "feature-branch"
        assert request.priority == ReviewPriority.HIGH

    def test_request_from_dict(self):
        """Test creating request from dictionary."""
        data = {
            "id": "test-001",
            "title": "Test Request",
            "author": "testuser",
            "status": "pending",
            "priority": "high",
            "review_type": "code_review",
        }
        request = ReviewRequest.from_dict(data)
        assert request.id == "test-001"
        assert request.title == "Test Request"
        assert request.status == ReviewStatus.PENDING

    def test_request_to_dict(self):
        """Test converting request to dictionary."""
        request = ReviewRequest(
            id="test-001",
            title="Test",
            author="testuser",
        )
        data = request.to_dict()
        assert data["id"] == "test-001"
        assert data["title"] == "Test"

    def test_set_status(self):
        """Test setting request status."""
        request = ReviewRequest(title="Test", author="user")
        request.set_status(ReviewStatus.IN_REVIEW)
        assert request.status == ReviewStatus.IN_REVIEW

    def test_assign_reviewer(self):
        """Test assigning a reviewer."""
        request = ReviewRequest(title="Test", author="user")
        request.assign_reviewer("reviewer1")
        assert "reviewer1" in request.assigned_reviewers
        # Test duplicate assignment
        request.assign_reviewer("reviewer1")
        assert request.assigned_reviewers.count("reviewer1") == 1

    def test_unassign_reviewer(self):
        """Test unassigning a reviewer."""
        request = ReviewRequest(title="Test", author="user")
        request.assign_reviewer("reviewer1")
        result = request.unassign_reviewer("reviewer1")
        assert result is True
        assert "reviewer1" not in request.assigned_reviewers

    def test_is_open(self):
        """Test checking if request is open."""
        request = ReviewRequest(title="Test", author="user")
        assert request.is_open is True

        request.set_status(ReviewStatus.APPROVED)
        assert request.is_open is False

    def test_is_closed(self):
        """Test checking if request is closed."""
        request = ReviewRequest(title="Test", author="user")
        assert request.is_closed is False

        request.set_status(ReviewStatus.APPROVED)
        assert request.is_closed is True


class TestReviewStatus:
    """Tests for ReviewStatus."""

    def test_all_statuses(self):
        """Test all status values."""
        statuses = [
            ReviewStatus.DRAFT,
            ReviewStatus.PENDING,
            ReviewStatus.IN_REVIEW,
            ReviewStatus.APPROVED,
            ReviewStatus.REJECTED,
            ReviewStatus.CHANGES_REQUESTED,
            ReviewStatus.CANCELLED,
        ]
        for status in statuses:
            assert isinstance(status, ReviewStatus)


class TestReviewPriority:
    """Tests for ReviewPriority."""

    def test_priority_scores(self):
        """Test priority scores."""
        assert ReviewPriority.CRITICAL.score == 4
        assert ReviewPriority.HIGH.score == 3
        assert ReviewPriority.MEDIUM.score == 2
        assert ReviewPriority.LOW.score == 1


class TestReviewType:
    """Tests for ReviewType."""

    def test_all_types(self):
        """Test all review type values."""
        types = [
            ReviewType.CODE_REVIEW,
            ReviewType.ARCHITECTURE_REVIEW,
            ReviewType.SECURITY_REVIEW,
            ReviewType.DESIGN_REVIEW,
            ReviewType.DOCUMENTATION_REVIEW,
            ReviewType.PEER_REVIEW,
            ReviewType.PAIR_PROGRAMMING,
        ]
        for review_type in types:
            assert isinstance(review_type, ReviewType)


class TestReviewComment:
    """Tests for ReviewComment."""

    def test_comment_creation(self):
        """Test creating a comment."""
        comment = ReviewComment(
            content="This looks good",
            review_id="review-001",
            reviewer="reviewer1",
        )
        assert comment.content == "This looks good"
        assert comment.reviewer == "reviewer1"

    def test_comment_from_dict(self):
        """Test creating comment from dictionary."""
        data = {
            "id": "comment-001",
            "content": "Test comment",
            "reviewer": "reviewer1",
        }
        comment = ReviewComment.from_dict(data)
        assert comment.content == "Test comment"

    def test_comment_to_dict(self):
        """Test converting comment to dictionary."""
        comment = ReviewComment(
            id="comment-001",
            content="Test",
            reviewer="reviewer1",
        )
        data = comment.to_dict()
        assert data["id"] == "comment-001"
        assert data["content"] == "Test"

    def test_resolve_comment(self):
        """Test resolving a comment."""
        comment = ReviewComment(content="Test")
        assert comment.resolved is False
        comment.resolve()
        assert comment.resolved is True
        assert comment.resolved_at is not None


class TestReview:
    """Tests for Review."""

    def test_review_creation(self):
        """Test creating a review."""
        review = Review(
            request_id="request-001",
            reviewer="reviewer1",
        )
        assert review.request_id == "request-001"
        assert review.reviewer == "reviewer1"

    def test_review_from_dict(self):
        """Test creating review from dictionary."""
        data = {
            "id": "review-001",
            "request_id": "request-001",
            "reviewer": "reviewer1",
            "status": "in_progress",
            "comments": [],
        }
        review = Review.from_dict(data)
        assert review.request_id == "request-001"

    def test_review_to_dict(self):
        """Test converting review to dictionary."""
        review = Review(
            request_id="request-001",
            reviewer="reviewer1",
        )
        data = review.to_dict()
        assert data["request_id"] == "request-001"

    def test_add_comment(self):
        """Test adding a comment to a review."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        comment = review.add_comment("Test comment")
        assert len(review.comments) == 1
        assert comment.content == "Test comment"

    def test_set_decision(self):
        """Test setting review decision."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        review.set_decision(ReviewDecision.APPROVE, "Looks good")
        assert review.decision == ReviewDecision.APPROVE
        assert review.summary == "Looks good"
        assert review.status == "completed"

    def test_complete_review(self):
        """Test completing a review."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        review.complete()
        assert review.status == "completed"

    def test_open_comments(self):
        """Test getting open comments."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        review.add_comment("Comment 1")
        review.add_comment("Comment 2")
        review.comments[0].resolve()
        open_comments = review.open_comments
        assert len(open_comments) == 1
        assert open_comments[0].content == "Comment 2"

    def test_is_approved(self):
        """Test checking if review is approved."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        assert review.is_approved is False
        review.set_decision(ReviewDecision.APPROVE)
        assert review.is_approved is True

    def test_is_changes_requested(self):
        """Test checking if changes are requested."""
        review = Review(request_id="request-001", reviewer="reviewer1")
        assert review.is_changes_requested is False
        review.set_decision(ReviewDecision.REQUEST_CHANGES)
        assert review.is_changes_requested is True


class TestReviewDecision:
    """Tests for ReviewDecision."""

    def test_all_decisions(self):
        """Test all decision values."""
        decisions = [
            ReviewDecision.APPROVE,
            ReviewDecision.REJECT,
            ReviewDecision.REQUEST_CHANGES,
            ReviewDecision.COMMENT,
        ]
        for decision in decisions:
            assert isinstance(decision, ReviewDecision)


class TestReviewer:
    """Tests for Reviewer."""

    def test_reviewer_creation(self):
        """Test creating a reviewer."""
        reviewer = Reviewer(
            name="John Doe",
            email="john@example.com",
            expertise=["python", "django"],
        )
        assert reviewer.name == "John Doe"
        assert reviewer.email == "john@example.com"

    def test_reviewer_to_dict(self):
        """Test converting reviewer to dictionary."""
        reviewer = Reviewer(name="John Doe", email="john@example.com")
        data = reviewer.to_dict()
        assert data["name"] == "John Doe"

    def test_reviewer_from_dict(self):
        """Test creating reviewer from dictionary."""
        data = {
            "id": "reviewer-001",
            "name": "John Doe",
            "email": "john@example.com",
        }
        reviewer = Reviewer.from_dict(data)
        assert reviewer.name == "John Doe"

    def test_is_available(self):
        """Test checking reviewer availability."""
        reviewer = Reviewer(name="John Doe", max_capacity=5, current_load=3)
        assert reviewer.is_available is True

        reviewer.current_load = 5
        assert reviewer.is_available is False

    def test_utilization(self):
        """Test utilization calculation."""
        reviewer = Reviewer(name="John Doe", max_capacity=5, current_load=2)
        assert reviewer.utilization == 40.0


class TestReviewerPool:
    """Tests for ReviewerPool."""

    def test_pool_creation(self):
        """Test creating a reviewer pool."""
        pool = ReviewerPool()
        assert len(pool.list_reviewers()) == 0

    def test_add_reviewer(self):
        """Test adding a reviewer to the pool."""
        pool = ReviewerPool()
        reviewer = Reviewer(name="John Doe")
        pool.add_reviewer(reviewer)
        assert len(pool.list_reviewers()) == 1

    def test_remove_reviewer(self):
        """Test removing a reviewer from the pool."""
        pool = ReviewerPool()
        reviewer = Reviewer(name="John Doe")
        pool.add_reviewer(reviewer)
        result = pool.remove_reviewer(reviewer.id)
        assert result is True
        assert len(pool.list_reviewers()) == 0

    def test_get_reviewer(self):
        """Test getting a reviewer by ID."""
        pool = ReviewerPool()
        reviewer = Reviewer(name="John Doe")
        pool.add_reviewer(reviewer)
        retrieved = pool.get_reviewer(reviewer.id)
        assert retrieved is not None
        assert retrieved.name == "John Doe"

    def test_get_available_reviewers(self):
        """Test getting available reviewers."""
        pool = ReviewerPool()
        reviewer1 = Reviewer(name="John", max_capacity=2, current_load=2)
        reviewer2 = Reviewer(name="Jane", max_capacity=5, current_load=0)
        pool.add_reviewer(reviewer1)
        pool.add_reviewer(reviewer2)
        available = pool.get_available_reviewers()
        assert len(available) == 1
        assert available[0].name == "Jane"

    def test_to_dict(self):
        """Test converting pool to dictionary."""
        pool = ReviewerPool()
        pool.add_reviewer(Reviewer(name="John Doe"))
        data = pool.to_dict()
        assert "reviewers" in data
        assert len(data["reviewers"]) == 1


class TestReviewerAssigner:
    """Tests for ReviewerAssigner."""

    def test_assigner_creation(self):
        """Test creating a reviewer assigner."""
        pool = ReviewerPool()
        assigner = ReviewerAssigner(pool)
        assert assigner.pool is pool

    def test_add_reviewer(self):
        """Test adding a reviewer to the assigner."""
        assigner = ReviewerAssigner()
        reviewer = Reviewer(name="John Doe")
        assigner.add_reviewer(reviewer)
        assert len(assigner.pool.list_reviewers()) == 1

    def test_assign_reviewers_round_robin(self):
        """Test round robin assignment."""
        assigner = ReviewerAssigner()
        assigner.add_reviewer(Reviewer(name="John", id="rev1"))
        assigner.add_reviewer(Reviewer(name="Jane", id="rev2"))
        assigner.add_reviewer(Reviewer(name="Bob", id="rev3"))

        # First assignment
        assigned = assigner.assign_reviewers("request-001", num_reviewers=1)
        assert len(assigned) == 1

        # Second assignment should go to next reviewer
        assigned2 = assigner.assign_reviewers("request-002", num_reviewers=1)
        assert len(assigned2) == 1

    def test_assign_reviewers_random(self):
        """Test random assignment."""
        assigner = ReviewerAssigner()
        assigner.add_reviewer(Reviewer(name="John", id="rev1"))
        assigner.add_reviewer(Reviewer(name="Jane", id="rev2"))

        assigned = assigner.assign_reviewers(
            "request-001",
            num_reviewers=1,
            strategy=AssignmentStrategy.RANDOM,
        )
        assert len(assigned) == 1

    def test_assign_reviewers_expertise(self):
        """Test expertise-based assignment."""
        assigner = ReviewerAssigner()
        assigner.add_reviewer(Reviewer(name="John", id="rev1", expertise=["python"]))
        assigner.add_reviewer(Reviewer(name="Jane", id="rev2", expertise=["javascript"]))

        assigned = assigner.assign_reviewers(
            "request-001",
            num_reviewers=1,
            strategy=AssignmentStrategy.EXPERTISE_BASED,
            expertise=["python"],
        )
        assert len(assigned) == 1
        assert assigned[0] == "rev1"

    def test_assign_reviewers_load_balanced(self):
        """Test load-balanced assignment."""
        assigner = ReviewerAssigner()
        reviewer1 = Reviewer(name="John", id="rev1", current_load=0, max_capacity=5)
        reviewer2 = Reviewer(name="Jane", id="rev2", current_load=3, max_capacity=5)
        assigner.add_reviewer(reviewer1)
        assigner.add_reviewer(reviewer2)

        assigned = assigner.assign_reviewers(
            "request-001",
            num_reviewers=1,
            strategy=AssignmentStrategy.LOAD_BALANCED,
        )
        assert len(assigned) == 1
        # Should prefer the reviewer with lower load
        assert assigned[0] == "rev1"

    def test_get_summary(self):
        """Test getting summary."""
        assigner = ReviewerAssigner()
        assigner.add_reviewer(Reviewer(name="John", id="rev1"))
        assigner.add_reviewer(Reviewer(name="Jane", id="rev2"))
        summary = assigner.get_summary()
        assert summary["total_reviewers"] == 2


class TestReviewTracker:
    """Tests for ReviewTracker."""

    def test_tracker_creation(self):
        """Test creating a tracker."""
        tracker = ReviewTracker()
        assert len(tracker.get_all_requests()) == 0

    def test_add_request(self):
        """Test adding a request."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        tracker.add_request(request)
        assert len(tracker.get_all_requests()) == 1

    def test_update_request(self):
        """Test updating a request."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        tracker.add_request(request)
        request.set_status(ReviewStatus.IN_REVIEW)
        tracker.update_request(request)
        retrieved = tracker.get_request(request.id)
        assert retrieved.status == ReviewStatus.IN_REVIEW

    def test_remove_request(self):
        """Test removing a request."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        tracker.add_request(request)
        result = tracker.remove_request(request.id)
        assert result is True
        assert tracker.get_request(request.id) is None

    def test_assign_reviewer(self):
        """Test assigning a reviewer."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        tracker.add_request(request)
        tracker.assign_reviewer(request.id, "reviewer1")
        assigned = tracker.get_requests_by_reviewer("reviewer1")
        assert len(assigned) == 1

    def test_get_open_requests(self):
        """Test getting open requests."""
        tracker = ReviewTracker()
        request1 = ReviewRequest(title="Test1", author="user")
        request2 = ReviewRequest(title="Test2", author="user")
        request2.set_status(ReviewStatus.APPROVED)
        tracker.add_request(request1)
        tracker.add_request(request2)
        open_requests = tracker.get_open_requests()
        assert len(open_requests) == 1

    def test_get_closed_requests(self):
        """Test getting closed requests."""
        tracker = ReviewTracker()
        request1 = ReviewRequest(title="Test1", author="user")
        request2 = ReviewRequest(title="Test2", author="user")
        request2.set_status(ReviewStatus.APPROVED)
        tracker.add_request(request1)
        tracker.add_request(request2)
        closed_requests = tracker.get_closed_requests()
        assert len(closed_requests) == 1

    def test_get_metrics(self):
        """Test getting metrics."""
        tracker = ReviewTracker()
        request1 = ReviewRequest(title="Test1", author="user")
        request2 = ReviewRequest(title="Test2", author="user")
        request2.set_status(ReviewStatus.APPROVED)
        tracker.add_request(request1)
        tracker.add_request(request2)
        metrics = tracker.get_metrics()
        assert metrics.total_reviews == 2
        assert metrics.completed_reviews == 1

    def test_get_reviewer_metrics(self):
        """Test getting reviewer metrics."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        request.assign_reviewer("reviewer1")
        tracker.add_request(request)
        tracker.assign_reviewer(request.id, "reviewer1")
        metrics = tracker.get_reviewer_metrics("reviewer1")
        assert metrics.total_reviews == 1

    def test_take_snapshot(self):
        """Test taking a snapshot."""
        tracker = ReviewTracker()
        request = ReviewRequest(title="Test", author="user")
        tracker.add_request(request)
        snapshot = tracker.take_snapshot()
        assert "timestamp" in snapshot
        assert "metrics" in snapshot

    def test_clear(self):
        """Test clearing the tracker."""
        tracker = ReviewTracker()
        tracker.add_request(ReviewRequest(title="Test", author="user"))
        tracker.clear()
        assert len(tracker.get_all_requests()) == 0


class TestReviewMetrics:
    """Tests for ReviewMetrics."""

    def test_metrics_creation(self):
        """Test creating metrics."""
        metrics = ReviewMetrics(
            total_reviews=10,
            completed_reviews=5,
        )
        assert metrics.total_reviews == 10

    def test_approval_rate(self):
        """Test approval rate calculation."""
        metrics = ReviewMetrics(
            completed_reviews=4,
            approved_reviews=2,
        )
        assert metrics.approval_rate == 50.0

    def test_completion_rate(self):
        """Test completion rate calculation."""
        metrics = ReviewMetrics(
            total_reviews=10,
            completed_reviews=5,
        )
        assert metrics.completion_rate == 50.0


class TestChecklistItem:
    """Tests for ChecklistItem."""

    def test_item_creation(self):
        """Test creating a checklist item."""
        item = ChecklistItem(
            title="Code Quality",
            description="Review code for quality",
        )
        assert item.title == "Code Quality"

    def test_item_from_dict(self):
        """Test creating item from dictionary."""
        data = {"title": "Test Item", "required": True}
        item = ChecklistItem.from_dict(data)
        assert item.title == "Test Item"

    def test_item_to_dict(self):
        """Test converting item to dictionary."""
        item = ChecklistItem(title="Test")
        data = item.to_dict()
        assert data["title"] == "Test"

    def test_status(self):
        """Test item status."""
        item = ChecklistItem(title="Test", required=True)
        assert item.status == "failed"

        item.passed = True
        assert item.status == "passed"

        item.skipped = True
        item.passed = False
        assert item.status == "skipped"


class TestReviewChecklist:
    """Tests for ReviewChecklist."""

    def test_checklist_creation(self):
        """Test creating a checklist."""
        checklist = ReviewChecklist(
            name="Code Review Checklist",
            review_id="review-001",
        )
        assert checklist.name == "Code Review Checklist"

    def test_checklist_from_dict(self):
        """Test creating checklist from dictionary."""
        data = {
            "id": "checklist-001",
            "name": "Test Checklist",
            "items": [],
        }
        checklist = ReviewChecklist.from_dict(data)
        assert checklist.name == "Test Checklist"

    def test_checklist_to_dict(self):
        """Test converting checklist to dictionary."""
        checklist = ReviewChecklist(name="Test")
        data = checklist.to_dict()
        assert data["name"] == "Test"

    def test_add_item(self):
        """Test adding an item to the checklist."""
        checklist = ReviewChecklist(name="Test")
        item = checklist.add_item("Test Item")
        assert len(checklist.items) == 1
        assert item.title == "Test Item"

    def test_remove_item(self):
        """Test removing an item from the checklist."""
        checklist = ReviewChecklist(name="Test")
        item = checklist.add_item("Test Item")
        result = checklist.remove_item(item.id)
        assert result is True
        assert len(checklist.items) == 0

    def test_mark_passed(self):
        """Test marking an item as passed."""
        checklist = ReviewChecklist(name="Test")
        item = checklist.add_item("Test Item")
        result = checklist.mark_passed(item.id)
        assert result is True
        assert checklist.items[0].passed is True

    def test_mark_failed(self):
        """Test marking an item as failed."""
        checklist = ReviewChecklist(name="Test")
        item = checklist.add_item("Test Item")
        result = checklist.mark_failed(item.id, "Needs improvement")
        assert result is True
        assert checklist.items[0].comments == "Needs improvement"

    def test_mark_skipped(self):
        """Test marking an item as skipped."""
        checklist = ReviewChecklist(name="Test")
        item = checklist.add_item("Test Item")
        result = checklist.mark_skipped(item.id)
        assert result is True
        assert checklist.items[0].skipped is True

    def test_completion_percentage(self):
        """Test completion percentage calculation."""
        checklist = ReviewChecklist(name="Test")
        checklist.add_item("Item 1", required=True)
        checklist.add_item("Item 2", required=True)
        checklist.mark_passed(checklist.items[0].id)
        assert checklist.completion_percentage == 50.0

    def test_all_passed(self):
        """Test checking if all items are passed."""
        checklist = ReviewChecklist(name="Test")
        checklist.add_item("Item 1", required=True)
        checklist.add_item("Item 2", required=True)
        checklist.mark_passed(checklist.items[0].id)
        assert checklist.all_passed is False

        checklist.mark_passed(checklist.items[1].id)
        assert checklist.all_passed is True

    def test_summary(self):
        """Test getting checklist summary."""
        checklist = ReviewChecklist(name="Test")
        checklist.add_item("Item 1", required=True)
        checklist.add_item("Item 2", required=True)
        checklist.mark_passed(checklist.items[0].id)
        summary = checklist.summary
        assert summary["total_items"] == 2
        assert summary["passed"] == 1


class TestReviewConfig:
    """Tests for ReviewConfig."""

    def test_config_creation(self):
        """Test creating a config."""
        config = ReviewConfig(
            default_assoc=2,
            min_reviewers=1,
            max_reviewers=3,
        )
        assert config.default_assoc == 2

    def test_config_to_dict(self):
        """Test converting config to dictionary."""
        config = ReviewConfig()
        data = config.to_dict()
        assert "default_assoc" in data

    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "default_assoc": 2,
            "min_reviewers": 1,
            "max_reviewers": 5,
        }
        config = ReviewConfig.from_dict(data)
        assert config.default_assoc == 2


class TestReviewManager:
    """Tests for ReviewManager."""

    def test_manager_initialization(self):
        """Test manager initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            assert manager.workspace.exists()

    def test_create_request(self):
        """Test creating a review request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(
                title="Review my PR",
                author="testuser",
            )
            assert request is not None
            assert request.title == "Review my PR"

    def test_get_request(self):
        """Test getting a request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            retrieved = manager.get_request(request.id)
            assert retrieved is not None
            assert retrieved.id == request.id

    def test_list_requests(self):
        """Test listing requests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            manager.create_request(title="Test1", author="user")
            manager.create_request(title="Test2", author="user")
            requests = manager.list_requests()
            assert len(requests) == 2

    def test_add_reviewer(self):
        """Test adding a reviewer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            reviewer = manager.add_reviewer(name="John Doe", email="john@example.com")
            assert reviewer is not None
            assert reviewer.name == "John Doe"

    def test_assign_reviewers(self):
        """Test assigning reviewers to a request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            manager.add_reviewer(name="John")
            manager.add_reviewer(name="Jane")
            assigned = manager.assign_reviewers(request.id, num_reviewers=1)
            assert len(assigned) == 1

    def test_start_review(self):
        """Test starting a review."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            manager.add_reviewer(name="John")
            assigned = manager.assign_reviewers(request.id, num_reviewers=1)
            review = manager.start_review(request.id, assigned[0])
            assert review is not None
            assert review.request_id == request.id

    def test_submit_review(self):
        """Test submitting a review."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            manager.add_reviewer(name="John")
            assigned = manager.assign_reviewers(request.id, num_reviewers=1)
            review = manager.start_review(request.id, assigned[0])
            result = manager.submit_review(review.id, ReviewDecision.APPROVE, "Good work")
            assert result is True

    def test_add_comment(self):
        """Test adding a comment to a review."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            manager.add_reviewer(name="John")
            assigned = manager.assign_reviewers(request.id, num_reviewers=1)
            review = manager.start_review(request.id, assigned[0])
            comment = manager.add_comment(review.id, "This looks good")
            assert comment is not None

    def test_get_summary(self):
        """Test getting summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            manager.create_request(title="Test", author="user")
            summary = manager.get_summary()
            assert "total_requests" in summary
            assert summary["total_requests"] == 1

    def test_get_metrics(self):
        """Test getting metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            manager.create_request(title="Test", author="user")
            metrics = manager.get_metrics()
            assert "total_reviews" in metrics

    def test_delete_request(self):
        """Test deleting a request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)
            request = manager.create_request(title="Test", author="user")
            result = manager.delete_request(request.id)
            assert result is True
            assert manager.get_request(request.id) is None


class TestReviewerSystemIntegration:
    """Integration tests for the Reviewer System."""

    def test_full_review_workflow(self):
        """Test the complete review workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ReviewManager(workspace=tmpdir)

            # Create reviewers
            manager.add_reviewer(name="John Doe", expertise=["python", "django"])
            manager.add_reviewer(name="Jane Smith", expertise=["javascript", "react"])

            # Get reviewer IDs from the pool
            reviewers = manager.list_reviewers()
            rev1_id = reviewers[0].id
            rev2_id = reviewers[1].id

            # Create a review request
            request = manager.create_request(
                title="Review Feature X",
                author="developer1",
                repository="myrepo",
                branch="feature-x",
                description="Please review the new feature implementation",
                files=["feature.py", "tests.py"],
                priority=ReviewPriority.HIGH,
            )

            # Assign reviewers
            assigned = manager.assign_reviewers(
                request.id,
                num_reviewers=2,
                strategy=AssignmentStrategy.ROUND_ROBIN,
            )
            assert len(assigned) == 2

            # Start reviews
            review1 = manager.start_review(request.id, assigned[0])
            review2 = manager.start_review(request.id, assigned[1])

            # Add comments
            manager.add_comment(review1.id, "Code looks good", file_path="feature.py")
            manager.add_comment(review1.id, "Consider adding more tests", severity="warning")
            manager.add_comment(review2.id, "LGTM!", file_path="feature.py")

            # Submit reviews
            manager.submit_review(review1.id, ReviewDecision.APPROVE, "Excellent work")
            manager.submit_review(review2.id, ReviewDecision.APPROVE, "Looks great")

            # Mark request as approved
            manager.set_request_status(request.id, ReviewStatus.APPROVED)

            # Check metrics
            summary = manager.get_summary()
            assert summary["total_requests"] == 1
            assert summary["completed_reviews"] == 2

    def test_reviewer_system_exports(self):
        """Test that the reviewer module exports all expected classes."""
        from app.reviewer import (
            ReviewRequest,
            ReviewStatus,
            ReviewPriority,
            ReviewType,
            Review,
            ReviewComment,
            ReviewDecision,
            ReviewerAssigner,
            ReviewerPool,
            Reviewer,
            ReviewTracker,
            ReviewMetrics,
            ReviewManager,
            ReviewChecklist,
            ChecklistItem,
        )
        assert ReviewRequest is not None
        assert ReviewStatus is not None
        assert Review is not None
        assert ReviewerAssigner is not None
        assert ReviewerPool is not None
        assert Reviewer is not None
        assert ReviewTracker is not None
        assert ReviewChecklist is not None
