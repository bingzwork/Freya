"""Review Request module for managing code review requests."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Any, Optional
import uuid


class ReviewStatus(Enum):
    """Status of a review request."""
    DRAFT = "draft"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    CANCELLED = "cancelled"


class ReviewPriority(Enum):
    """Priority of a review request."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def score(self) -> int:
        """Get numeric score for priority."""
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}[self.value]


class ReviewType(Enum):
    """Type of review."""
    CODE_REVIEW = "code_review"
    ARCHITECTURE_REVIEW = "architecture_review"
    SECURITY_REVIEW = "security_review"
    DESIGN_REVIEW = "design_review"
    DOCUMENTATION_REVIEW = "documentation_review"
    PEER_REVIEW = "peer_review"
    PAIR_PROGRAMMING = "pair_programming"


@dataclass
class ReviewRequest:
    """Represents a request for code review."""
    # Required fields first
    title: str
    author: str

    # Optional fields with defaults
    id: str = field(default_factory=lambda: f"review_{uuid.uuid4().hex[:8]}")
    description: str = ""
    status: ReviewStatus = ReviewStatus.DRAFT
    priority: ReviewPriority = ReviewPriority.MEDIUM
    review_type: ReviewType = ReviewType.CODE_REVIEW

    # References
    repository: str = ""
    branch: str = ""
    commit_hash: str = ""
    pull_request_id: Optional[str] = None

    # Files to review
    files: List[str] = field(default_factory=list)

    # Metadata
    assigned_reviewers: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    due_date: Optional[str] = None

    # Additional metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.priority, str):
            self.priority = ReviewPriority(self.priority)
        if isinstance(self.status, str):
            self.status = ReviewStatus(self.status)
        if isinstance(self.review_type, str):
            self.review_type = ReviewType(self.review_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "review_type": self.review_type.value,
            "repository": self.repository,
            "branch": self.branch,
            "commit_hash": self.commit_hash,
            "pull_request_id": self.pull_request_id,
            "files": self.files,
            "author": self.author,
            "assigned_reviewers": self.assigned_reviewers,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "due_date": self.due_date,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewRequest":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"review_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", ReviewStatus.DRAFT.value),
            priority=data.get("priority", ReviewPriority.MEDIUM.value),
            review_type=data.get("review_type", ReviewType.CODE_REVIEW.value),
            repository=data.get("repository", ""),
            branch=data.get("branch", ""),
            commit_hash=data.get("commit_hash", ""),
            pull_request_id=data.get("pull_request_id"),
            files=data.get("files", []),
            author=data.get("author", ""),
            assigned_reviewers=data.get("assigned_reviewers", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            due_date=data.get("due_date"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    def set_status(self, status: ReviewStatus) -> None:
        """Set the review status."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def assign_reviewer(self, reviewer: str) -> None:
        """Assign a reviewer."""
        if reviewer not in self.assigned_reviewers:
            self.assigned_reviewers.append(reviewer)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def unassign_reviewer(self, reviewer: str) -> bool:
        """Unassign a reviewer."""
        if reviewer in self.assigned_reviewers:
            self.assigned_reviewers.remove(reviewer)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    @property
    def is_open(self) -> bool:
        """Check if the review is still open."""
        return self.status in [
            ReviewStatus.DRAFT,
            ReviewStatus.PENDING,
            ReviewStatus.IN_REVIEW,
            ReviewStatus.CHANGES_REQUESTED,
        ]

    @property
    def is_closed(self) -> bool:
        """Check if the review is closed."""
        return self.status in [
            ReviewStatus.APPROVED,
            ReviewStatus.REJECTED,
            ReviewStatus.CANCELLED,
        ]
