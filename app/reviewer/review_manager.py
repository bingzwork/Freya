"""Review Manager module for managing the complete review workflow."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from app.reviewer.review_request import ReviewRequest, ReviewStatus, ReviewPriority, ReviewType
from app.reviewer.review import Review, ReviewComment, ReviewDecision
from app.reviewer.reviewer_assigner import ReviewerAssigner, ReviewerPool, Reviewer, AssignmentStrategy
from app.reviewer.review_tracker import ReviewTracker
from app.reviewer.checklist import ReviewChecklist, ChecklistItem


@dataclass
class ReviewConfig:
    """Configuration for the review system."""
    default_assoc: int = 1
    min_reviewers: int = 1
    max_reviewers: int = 3
    default_priority: ReviewPriority = ReviewPriority.MEDIUM
    default_review_type: ReviewType = ReviewType.CODE_REVIEW
    assignment_strategy: AssignmentStrategy = AssignmentStrategy.ROUND_ROBIN
    due_date_days: int = 7

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "default_assoc": self.default_assoc,
            "min_reviewers": self.min_reviewers,
            "max_reviewers": self.max_reviewers,
            "default_priority": self.default_priority.value,
            "default_review_type": self.default_review_type.value,
            "assignment_strategy": self.assignment_strategy.value,
            "due_date_days": self.due_date_days,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewConfig":
        """Create from dictionary."""
        return cls(
            default_assoc=data.get("default_assoc", 1),
            min_reviewers=data.get("min_reviewers", 1),
            max_reviewers=data.get("max_reviewers", 3),
            default_priority=ReviewPriority(data.get("default_priority", "medium")),
            default_review_type=ReviewType(data.get("default_review_type", "code_review")),
            assignment_strategy=AssignmentStrategy(data.get("assignment_strategy", "round_robin")),
            due_date_days=data.get("due_date_days", 7),
        )


class ReviewManager:
    """Manages the complete review workflow."""

    def __init__(self, workspace: str = ".", config: Optional[ReviewConfig] = None):
        """Initialize the review manager."""
        self.workspace = Path(workspace).resolve()
        self.reviews_dir = self.workspace / ".reviews"
        self.reviews_dir.mkdir(parents=True, exist_ok=True)

        self.config = config or ReviewConfig()
        self._reviewer_pool = ReviewerPool()
        self._assigner = ReviewerAssigner(self._reviewer_pool)
        self._tracker = ReviewTracker()

        # Review requests: request_id -> ReviewRequest
        self._requests: Dict[str, ReviewRequest] = {}

        # Reviews: review_id -> Review
        self._reviews: Dict[str, Review] = {}

        # Checklists: checklist_id -> ReviewChecklist
        self._checklists: Dict[str, ReviewChecklist] = {}

        # Load existing data
        self._load_reviews()

    def _load_reviews(self) -> None:
        """Load review data from disk."""
        for review_file in self.reviews_dir.glob("*.json"):
            try:
                with open(review_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "request" in data:
                        request = ReviewRequest.from_dict(data["request"])
                        self._requests[request.id] = request
                        self._tracker.add_request(request)
                    if "reviews" in data:
                        for review_data in data["reviews"]:
                            review = Review.from_dict(review_data)
                            self._reviews[review.id] = review
                    if "checklists" in data:
                        for checklist_data in data["checklists"]:
                            checklist = ReviewChecklist.from_dict(checklist_data)
                            self._checklists[checklist.id] = checklist
            except Exception as e:
                print(f"Error loading review {review_file}: {e}")

    def _save_data(self) -> None:
        """Save all data to disk."""
        data = {
            "requests": [r.to_dict() for r in self._requests.values()],
            "reviews": [r.to_dict() for r in self._reviews.values()],
            "checklists": [c.to_dict() for c in self._checklists.values()],
            "config": self.config.to_dict(),
        }
        review_file = self.reviews_dir / "reviews.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _save_request(self, request: ReviewRequest) -> None:
        """Save a single request to disk."""
        self._requests[request.id] = request
        self._tracker.update_request(request)
        data = {
            "request": request.to_dict(),
            "reviews": [r.to_dict() for r in self._reviews.values() if r.request_id == request.id],
            "checklists": [c.to_dict() for c in self._checklists.values() if c.review_id == request.id],
        }
        review_file = self.reviews_dir / f"{request.id}.json"
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # Review Request operations

    def create_request(
        self,
        title: str,
        author: str,
        repository: str = "",
        branch: str = "",
        description: str = "",
        files: Optional[List[str]] = None,
        priority: Optional[ReviewPriority] = None,
        review_type: Optional[ReviewType] = None,
        pull_request_id: Optional[str] = None,
    ) -> ReviewRequest:
        """Create a new review request."""
        request = ReviewRequest(
            title=title,
            author=author,
            repository=repository,
            branch=branch,
            description=description,
            files=files or [],
            priority=priority or self.config.default_priority,
            review_type=review_type or self.config.default_review_type,
            pull_request_id=pull_request_id,
            due_date=(datetime.now(timezone.utc) + timedelta(days=self.config.due_date_days)).isoformat(),
        )
        self._save_request(request)
        return request

    def get_request(self, request_id: str) -> Optional[ReviewRequest]:
        """Get a review request by ID."""
        return self._requests.get(request_id)

    def list_requests(self) -> List[ReviewRequest]:
        """List all review requests."""
        return list(self._requests.values())

    def update_request(self, request_id: str, **kwargs) -> bool:
        """Update a review request."""
        request = self._requests.get(request_id)
        if not request:
            return False
        for key, value in kwargs.items():
            if hasattr(request, key):
                setattr(request, key, value)
        self._save_request(request)
        return True

    def delete_request(self, request_id: str) -> bool:
        """Delete a review request."""
        if request_id in self._requests:
            request = self._requests[request_id]
            # Delete associated reviews and checklists
            reviews_to_delete = [rid for rid, r in self._reviews.items() if r.request_id == request_id]
            for rid in reviews_to_delete:
                del self._reviews[rid]
            checklists_to_delete = [cid for cid, c in self._checklists.items() if c.review_id == request_id]
            for cid in checklists_to_delete:
                del self._checklists[cid]
            # Delete from tracker
            self._tracker.remove_request(request_id)
            # Delete from requests
            del self._requests[request_id]
            # Delete file
            review_file = self.reviews_dir / f"{request_id}.json"
            if review_file.exists():
                review_file.unlink()
            return True
        return False

    def set_request_status(self, request_id: str, status: ReviewStatus) -> bool:
        """Set the status of a review request."""
        request = self._requests.get(request_id)
        if not request:
            return False
        request.set_status(status)
        self._save_request(request)
        return True

    # Reviewer operations

    def add_reviewer(
        self,
        name: str,
        email: str = "",
        expertise: Optional[List[str]] = None,
        max_capacity: int = 5,
    ) -> Reviewer:
        """Add a reviewer to the pool."""
        reviewer = Reviewer(
            name=name,
            email=email,
            expertise=expertise or [],
            max_capacity=max_capacity,
        )
        self._reviewer_pool.add_reviewer(reviewer)
        return reviewer

    def remove_reviewer(self, reviewer_id: str) -> bool:
        """Remove a reviewer from the pool."""
        return self._reviewer_pool.remove_reviewer(reviewer_id)

    def list_reviewers(self) -> List[Reviewer]:
        """List all reviewers."""
        return self._reviewer_pool.list_reviewers()

    def assign_reviewers(
        self,
        request_id: str,
        num_reviewers: int = 1,
        strategy: Optional[AssignmentStrategy] = None,
        expertise: Optional[List[str]] = None,
    ) -> List[str]:
        """Assign reviewers to a review request."""
        request = self._requests.get(request_id)
        if not request:
            return []

        strategy = strategy or self.config.assignment_strategy
        assigned = self._assigner.assign_reviewers(
            request_id,
            num_reviewers=min(num_reviewers, self.config.max_reviewers),
            strategy=strategy,
            expertise=expertise,
        )

        # Update request with assigned reviewers
        for reviewer_id in assigned:
            request.assign_reviewer(reviewer_id)
            self._tracker.assign_reviewer(request_id, reviewer_id)

        self._save_request(request)
        return assigned

    def unassign_reviewer(self, request_id: str, reviewer_id: str) -> bool:
        """Unassign a reviewer from a review request."""
        request = self._requests.get(request_id)
        if not request:
            return False
        if request.unassign_reviewer(reviewer_id):
            self._assigner.unassign_reviewer(request_id, reviewer_id)
            self._tracker.unassign_reviewer(request_id, reviewer_id)
            self._save_request(request)
            return True
        return False

    # Review operations

    def start_review(self, request_id: str, reviewer_id: str) -> Optional[Review]:
        """Start a review for a request."""
        request = self._requests.get(request_id)
        if not request:
            return None
        if reviewer_id not in request.assigned_reviewers:
            return None

        review = Review(
            request_id=request_id,
            reviewer=reviewer_id,
        )
        self._reviews[review.id] = review

        # Create a default checklist
        checklist = ReviewChecklist(
            name=f"Review Checklist for {request.title}",
            review_id=review.id,
        )
        # Add common checklist items
        self._add_default_checklist_items(checklist)
        self._checklists[checklist.id] = checklist

        return review

    def _add_default_checklist_items(self, checklist: ReviewChecklist) -> None:
        """Add default checklist items."""
        default_items = [
            ("Code Quality", "Review code for quality and best practices", "code_quality", True),
            ("Functionality", "Verify the code works as intended", "functionality", True),
            ("Performance", "Check for performance issues", "performance", True),
            ("Security", "Review for security vulnerabilities", "security", True),
            ("Testing", "Verify tests are comprehensive", "testing", True),
            ("Documentation", "Check documentation is complete", "documentation", True),
        ]
        for title, description, category, required in default_items:
            checklist.add_item(title, description, category, required)

    def get_review(self, review_id: str) -> Optional[Review]:
        """Get a review by ID."""
        return self._reviews.get(review_id)

    def list_reviews(self, request_id: Optional[str] = None) -> List[Review]:
        """List reviews, optionally filtered by request."""
        if request_id:
            return [r for r in self._reviews.values() if r.request_id == request_id]
        return list(self._reviews.values())

    def submit_review(
        self,
        review_id: str,
        decision: ReviewDecision,
        summary: str = "",
    ) -> bool:
        """Submit a review with a decision."""
        review = self._reviews.get(review_id)
        if not review:
            return False
        review.set_decision(decision, summary)
        self._save_data()
        return True

    def add_comment(
        self,
        review_id: str,
        content: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        severity: str = "info",
    ) -> Optional[ReviewComment]:
        """Add a comment to a review."""
        review = self._reviews.get(review_id)
        if not review:
            return None
        comment = review.add_comment(content, file_path, line_number, severity)
        self._save_data()
        return comment

    # Checklist operations

    def get_checklist(self, checklist_id: str) -> Optional[ReviewChecklist]:
        """Get a checklist by ID."""
        return self._checklists.get(checklist_id)

    def list_checklists(self, review_id: Optional[str] = None) -> List[ReviewChecklist]:
        """List checklists, optionally filtered by review."""
        if review_id:
            return [c for c in self._checklists.values() if c.review_id == review_id]
        return list(self._checklists.values())

    def create_checklist(
        self,
        name: str,
        review_id: str,
        description: str = "",
    ) -> Optional[ReviewChecklist]:
        """Create a new checklist for a review."""
        review = self._reviews.get(review_id)
        if not review:
            return None
        checklist = ReviewChecklist(
            name=name,
            description=description,
            review_id=review_id,
        )
        self._checklists[checklist.id] = checklist
        self._save_data()
        return checklist

    def delete_checklist(self, checklist_id: str) -> bool:
        """Delete a checklist."""
        if checklist_id in self._checklists:
            del self._checklists[checklist_id]
            self._save_data()
            return True
        return False

    # Metrics and tracking

    def get_metrics(self) -> Dict[str, Any]:
        """Get overall review metrics."""
        metrics = self._tracker.get_metrics()
        return metrics.to_dict()

    def get_reviewer_metrics(self, reviewer_id: str) -> Dict[str, Any]:
        """Get metrics for a specific reviewer."""
        metrics = self._tracker.get_reviewer_metrics(reviewer_id)
        return metrics.to_dict()

    def get_team_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all reviewers."""
        team_metrics = self._tracker.get_team_metrics()
        return {reviewer_id: m.to_dict() for reviewer_id, m in team_metrics.items()}

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the review system."""
        open_requests = len(self._tracker.get_open_requests())
        closed_requests = len(self._tracker.get_closed_requests())
        overdue_requests = len(self._tracker.get_overdue_requests())
        total_reviewers = len(self._reviewer_pool.reviewers)

        return {
            "total_requests": len(self._requests),
            "open_requests": open_requests,
            "closed_requests": closed_requests,
            "overdue_requests": overdue_requests,
            "total_reviewers": total_reviewers,
            "active_reviews": len([r for r in self._reviews.values() if r.status == "in_progress"]),
            "completed_reviews": len([r for r in self._reviews.values() if r.status == "completed"]),
            "metrics": self.get_metrics(),
        }

    def save_all(self) -> None:
        """Save all data to disk."""
        self._save_data()
