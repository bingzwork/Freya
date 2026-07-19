"""Review module for managing individual reviews."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Any, Optional
import uuid


class ReviewDecision(Enum):
    """Decision for a review."""
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


@dataclass
class ReviewComment:
    """Represents a comment in a review."""
    content: str
    review_id: str = ""
    reviewer: str = ""
    id: str = field(default_factory=lambda: f"comment_{uuid.uuid4().hex[:8]}")
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    severity: str = "info"  # info, warning, error, suggestion
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "review_id": self.review_id,
            "reviewer": self.reviewer,
            "content": self.content,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "severity": self.severity,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewComment":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"comment_{uuid.uuid4().hex[:8]}"),
            review_id=data.get("review_id", ""),
            reviewer=data.get("reviewer", ""),
            content=data.get("content", ""),
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            severity=data.get("severity", "info"),
            created_at=data.get("created_at", ""),
            resolved=data.get("resolved", False),
            resolved_at=data.get("resolved_at"),
        )

    def resolve(self) -> None:
        """Mark comment as resolved."""
        self.resolved = True
        self.resolved_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Review:
    """Represents a review of a code change."""
    request_id: str
    reviewer: str
    id: str = field(default_factory=lambda: f"review_{uuid.uuid4().hex[:8]}")
    status: str = "in_progress"  # in_progress, completed, abandoned
    decision: Optional[ReviewDecision] = None
    summary: str = ""
    comments: List[ReviewComment] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    time_spent_minutes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "reviewer": self.reviewer,
            "status": self.status,
            "decision": self.decision.value if self.decision else None,
            "summary": self.summary,
            "comments": [c.to_dict() for c in self.comments],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "time_spent_minutes": self.time_spent_minutes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Review":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"review_{uuid.uuid4().hex[:8]}"),
            request_id=data.get("request_id", ""),
            reviewer=data.get("reviewer", ""),
            status=data.get("status", "in_progress"),
            decision=data.get("decision"),
            summary=data.get("summary", ""),
            comments=[ReviewComment.from_dict(c) for c in data.get("comments", [])],
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at"),
            time_spent_minutes=data.get("time_spent_minutes", 0),
        )

    def add_comment(
        self,
        content: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        severity: str = "info",
    ) -> ReviewComment:
        """Add a comment to the review."""
        comment = ReviewComment(
            review_id=self.id,
            reviewer=self.reviewer,
            content=content,
            file_path=file_path,
            line_number=line_number,
            severity=severity,
        )
        self.comments.append(comment)
        return comment

    def set_decision(self, decision: ReviewDecision, summary: str = "") -> None:
        """Set the review decision."""
        self.decision = decision
        self.summary = summary
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def complete(self) -> None:
        """Mark the review as completed."""
        if self.status != "completed":
            self.status = "completed"
            self.completed_at = datetime.now(timezone.utc).isoformat()

    @property
    def open_comments(self) -> List[ReviewComment]:
        """Get all open (unresolved) comments."""
        return [c for c in self.comments if not c.resolved]

    @property
    def is_approved(self) -> bool:
        """Check if the review is approved."""
        return self.decision == ReviewDecision.APPROVE

    @property
    def is_changes_requested(self) -> bool:
        """Check if changes are requested."""
        return self.decision == ReviewDecision.REQUEST_CHANGES
