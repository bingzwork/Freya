"""Review Tracker module for tracking review metrics and progress."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from app.reviewer.review_request import ReviewRequest, ReviewStatus


@dataclass
class ReviewMetrics:
    """Metrics for a review or reviewer."""
    total_reviews: int = 0
    completed_reviews: int = 0
    pending_reviews: int = 0
    approved_reviews: int = 0
    rejected_reviews: int = 0
    changes_requested: int = 0
    average_review_time_minutes: float = 0.0
    average_comments_per_review: float = 0.0
    average_time_to_first_comment: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_reviews": self.total_reviews,
            "completed_reviews": self.completed_reviews,
            "pending_reviews": self.pending_reviews,
            "approved_reviews": self.approved_reviews,
            "rejected_reviews": self.rejected_reviews,
            "changes_requested": self.changes_requested,
            "average_review_time_minutes": self.average_review_time_minutes,
            "average_comments_per_review": self.average_comments_per_review,
            "average_time_to_first_comment": self.average_time_to_first_comment,
        }

    @property
    def approval_rate(self) -> float:
        """Get the approval rate percentage."""
        if self.completed_reviews == 0:
            return 0.0
        return (self.approved_reviews / self.completed_reviews) * 100

    @property
    def completion_rate(self) -> float:
        """Get the completion rate percentage."""
        if self.total_reviews == 0:
            return 0.0
        return (self.completed_reviews / self.total_reviews) * 100


class ReviewTracker:
    """Tracks review metrics and progress over time."""

    def __init__(self):
        """Initialize the review tracker."""
        # Review request ID -> ReviewRequest
        self._requests: Dict[str, ReviewRequest] = {}

        # Reviewer ID -> List of assigned review request IDs
        self._reviewer_assignments: Dict[str, List[str]] = defaultdict(list)

        # History of review events
        self._events: List[Dict[str, Any]] = []

        # Metrics history for trend analysis
        self._metrics_history: List[Dict[str, Any]] = []

    def add_request(self, request: ReviewRequest) -> None:
        """Add a review request to the tracker."""
        self._requests[request.id] = request
        self._record_event("request_created", request.id, {"status": request.status.value})

    def update_request(self, request: ReviewRequest) -> None:
        """Update a review request."""
        if request.id in self._requests:
            old_status = self._requests[request.id].status
            self._requests[request.id] = request
            if old_status != request.status:
                self._record_event("status_changed", request.id, {
                    "old_status": old_status.value,
                    "new_status": request.status.value,
                })

    def remove_request(self, request_id: str) -> bool:
        """Remove a review request."""
        if request_id in self._requests:
            del self._requests[request_id]
            self._record_event("request_removed", request_id, {})
            return True
        return False

    def assign_reviewer(self, request_id: str, reviewer_id: str) -> None:
        """Assign a reviewer to a request."""
        if request_id in self._requests:
            self._reviewer_assignments[reviewer_id].append(request_id)
            self._record_event("reviewer_assigned", request_id, {
                "reviewer_id": reviewer_id,
            })

    def unassign_reviewer(self, request_id: str, reviewer_id: str) -> None:
        """Unassign a reviewer from a request."""
        if reviewer_id in self._reviewer_assignments:
            if request_id in self._reviewer_assignments[reviewer_id]:
                self._reviewer_assignments[reviewer_id].remove(request_id)
                self._record_event("reviewer_unassigned", request_id, {
                    "reviewer_id": reviewer_id,
                })

    def _record_event(self, event_type: str, request_id: str, data: Dict[str, Any]) -> None:
        """Record an event."""
        event = {
            "type": event_type,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        self._events.append(event)

    def get_request(self, request_id: str) -> Optional[ReviewRequest]:
        """Get a review request."""
        return self._requests.get(request_id)

    def get_all_requests(self) -> List[ReviewRequest]:
        """Get all review requests."""
        return list(self._requests.values())

    def get_requests_by_status(self, status: ReviewStatus) -> List[ReviewRequest]:
        """Get review requests by status."""
        return [r for r in self._requests.values() if r.status == status]

    def get_requests_by_reviewer(self, reviewer_id: str) -> List[ReviewRequest]:
        """Get review requests assigned to a reviewer."""
        request_ids = self._reviewer_assignments.get(reviewer_id, [])
        return [self._requests[rid] for rid in request_ids if rid in self._requests]

    def get_open_requests(self) -> List[ReviewRequest]:
        """Get all open review requests."""
        return [r for r in self._requests.values() if r.is_open]

    def get_closed_requests(self) -> List[ReviewRequest]:
        """Get all closed review requests."""
        return [r for r in self._requests.values() if r.is_closed]

    def get_overdue_requests(self) -> List[ReviewRequest]:
        """Get overdue review requests."""
        now = datetime.now(timezone.utc)
        overdue = []
        for request in self._requests.values():
            if request.due_date:
                due = datetime.fromisoformat(request.due_date)
                if now > due and request.is_open:
                    overdue.append(request)
        return overdue

    def get_metrics(self) -> ReviewMetrics:
        """Get overall metrics."""
        metrics = ReviewMetrics()
        metrics.total_reviews = len(self._requests)

        for request in self._requests.values():
            if request.status == ReviewStatus.APPROVED:
                metrics.approved_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.REJECTED:
                metrics.rejected_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.CHANGES_REQUESTED:
                metrics.changes_requested += 1
                metrics.completed_reviews += 1
            elif request.is_open:
                metrics.pending_reviews += 1

        return metrics

    def get_reviewer_metrics(self, reviewer_id: str) -> ReviewMetrics:
        """Get metrics for a specific reviewer."""
        metrics = ReviewMetrics()
        request_ids = self._reviewer_assignments.get(reviewer_id, [])
        assigned_requests = [self._requests[rid] for rid in request_ids if rid in self._requests]

        metrics.total_reviews = len(assigned_requests)

        for request in assigned_requests:
            if request.status == ReviewStatus.APPROVED:
                metrics.approved_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.REJECTED:
                metrics.rejected_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.CHANGES_REQUESTED:
                metrics.changes_requested += 1
                metrics.completed_reviews += 1
            elif request.is_open:
                metrics.pending_reviews += 1

        return metrics

    def get_team_metrics(self) -> Dict[str, ReviewMetrics]:
        """Get metrics for all reviewers."""
        team_metrics = {}
        all_reviewers: Set[str] = set()
        for request in self._requests.values():
            all_reviewers.update(request.assigned_reviewers)

        for reviewer_id in all_reviewers:
            team_metrics[reviewer_id] = self.get_reviewer_metrics(reviewer_id)

        return team_metrics

    def get_average_review_time(self) -> float:
        """Get average review completion time in minutes."""
        total_time = 0.0
        count = 0

        for request in self._requests.values():
            if not request.is_closed:
                continue
            if not request.created_at:
                continue
            if request.updated_at:
                created = datetime.fromisoformat(request.created_at)
                updated = datetime.fromisoformat(request.updated_at)
                total_time += (updated - created).total_seconds() / 60
                count += 1

        return total_time / count if count > 0 else 0.0

    def get_trending_metrics(self, days: int = 7) -> Dict[str, Any]:
        """Get trending metrics over the last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent_requests = [
            r for r in self._requests.values()
            if datetime.fromisoformat(r.created_at) >= cutoff
        ]

        metrics = ReviewMetrics()
        metrics.total_reviews = len(recent_requests)

        for request in recent_requests:
            if request.status == ReviewStatus.APPROVED:
                metrics.approved_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.REJECTED:
                metrics.rejected_reviews += 1
                metrics.completed_reviews += 1
            elif request.status == ReviewStatus.CHANGES_REQUESTED:
                metrics.changes_requested += 1
                metrics.completed_reviews += 1
            elif request.is_open:
                metrics.pending_reviews += 1

        return {
            "metrics": metrics.to_dict(),
            "period_days": days,
            "requests_created": len(recent_requests),
        }

    def take_snapshot(self) -> Dict[str, Any]:
        """Take a snapshot of current metrics."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": self.get_metrics().to_dict(),
            "total_requests": len(self._requests),
            "open_requests": len(self.get_open_requests()),
            "closed_requests": len(self.get_closed_requests()),
            "overdue_requests": len(self.get_overdue_requests()),
        }
        self._metrics_history.append(snapshot)
        return snapshot

    def get_snapshots(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get metric snapshots."""
        if count is None:
            return list(self._metrics_history)
        return list(self._metrics_history[-count:])

    def clear(self) -> None:
        """Clear all tracked data."""
        self._requests.clear()
        self._reviewer_assignments.clear()
        self._events.clear()
        self._metrics_history.clear()
