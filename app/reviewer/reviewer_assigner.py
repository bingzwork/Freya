"""Reviewer Assigner module for assigning reviewers to review requests."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict
from datetime import datetime, timezone
import random
import uuid


@dataclass
class Reviewer:
    """Represents a reviewer."""
    name: str
    email: str = ""
    id: str = field(default_factory=lambda: f"reviewer_{uuid.uuid4().hex[:8]}")
    expertise: List[str] = field(default_factory=list)
    availability: float = 1.0  # 0.0 to 1.0
    current_load: int = 0  # Number of active review assignments
    max_capacity: int = 5  # Maximum number of concurrent reviews
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "expertise": self.expertise,
            "availability": self.availability,
            "current_load": self.current_load,
            "max_capacity": self.max_capacity,
            "last_active_at": self.last_active_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reviewer":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"reviewer_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            email=data.get("email", ""),
            expertise=data.get("expertise", []),
            availability=data.get("availability", 1.0),
            current_load=data.get("current_load", 0),
            max_capacity=data.get("max_capacity", 5),
            last_active_at=data.get("last_active_at", ""),
            metadata=data.get("metadata", {}),
        )

    @property
    def is_available(self) -> bool:
        """Check if the reviewer is available for more reviews."""
        return self.current_load < self.max_capacity and self.availability > 0

    @property
    def utilization(self) -> float:
        """Get the current utilization percentage."""
        if self.max_capacity <= 0:
            return 0.0
        return (self.current_load / self.max_capacity) * 100


@dataclass
class ReviewerPool:
    """Pool of reviewers."""
    reviewers: Dict[str, Reviewer] = field(default_factory=dict)

    def add_reviewer(self, reviewer: Reviewer) -> None:
        """Add a reviewer to the pool."""
        self.reviewers[reviewer.id] = reviewer

    def remove_reviewer(self, reviewer_id: str) -> bool:
        """Remove a reviewer from the pool."""
        if reviewer_id in self.reviewers:
            del self.reviewers[reviewer_id]
            return True
        return False

    def get_reviewer(self, reviewer_id: str) -> Optional[Reviewer]:
        """Get a reviewer by ID."""
        return self.reviewers.get(reviewer_id)

    def list_reviewers(self) -> List[Reviewer]:
        """List all reviewers."""
        return list(self.reviewers.values())

    def get_available_reviewers(self) -> List[Reviewer]:
        """Get all available reviewers."""
        return [r for r in self.reviewers.values() if r.is_available]

    def get_reviewers_by_expertise(self, expertise: str) -> List[Reviewer]:
        """Get reviewers with specific expertise."""
        return [r for r in self.reviewers.values() if expertise in r.expertise]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "reviewers": [r.to_dict() for r in self.reviewers.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewerPool":
        """Create from dictionary."""
        pool = cls()
        for reviewer_data in data.get("reviewers", []):
            pool.add_reviewer(Reviewer.from_dict(reviewer_data))
        return pool


class AssignmentStrategy(Enum):
    """Strategy for assigning reviewers."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LOAD_BALANCED = "load_balanced"
    EXPERTISE_BASED = "expertise_based"
    LEAST_RECENTLY_USED = "least_recently_used"


class ReviewerAssigner:
    """Assigns reviewers to review requests using various strategies."""

    def __init__(self, pool: Optional[ReviewerPool] = None):
        """Initialize the reviewer assigner."""
        self.pool = pool or ReviewerPool()
        self._last_assignment_index = 0
        self._recent_assignments: Dict[str, int] = defaultdict(int)  # reviewer_id -> count

    def assign_reviewers(
        self,
        request_id: str,
        num_reviewers: int = 1,
        strategy: AssignmentStrategy = AssignmentStrategy.ROUND_ROBIN,
        expertise: Optional[List[str]] = None,
    ) -> List[str]:
        """Assign reviewers to a review request.

        Args:
            request_id: The ID of the review request
            num_reviewers: Number of reviewers to assign
            strategy: Strategy to use for assignment
            expertise: Optional list of expertise areas to match

        Returns:
            List of reviewer IDs assigned
        """
        available_reviewers = self._get_candidate_reviewers(expertise)

        if not available_reviewers:
            return []

        selected = []

        if strategy == AssignmentStrategy.ROUND_ROBIN:
            for _ in range(min(num_reviewers, len(available_reviewers))):
                reviewer = available_reviewers[self._last_assignment_index % len(available_reviewers)]
                selected.append(reviewer.id)
                self._last_assignment_index += 1

        elif strategy == AssignmentStrategy.RANDOM:
            candidates = list(available_reviewers)
            random.shuffle(candidates)
            selected = [r.id for r in candidates[:num_reviewers]]

        elif strategy == AssignmentStrategy.LOAD_BALANCED:
            # Sort by current load (ascending)
            sorted_reviewers = sorted(available_reviewers, key=lambda r: r.current_load)
            selected = [r.id for r in sorted_reviewers[:num_reviewers]]

        elif strategy == AssignmentStrategy.EXPERTISE_BASED:
            # Filter by expertise and sort by matching expertise count
            if expertise:
                def expertise_match_score(reviewer: Reviewer) -> int:
                    return len(set(expertise) & set(reviewer.expertise))
                sorted_reviewers = sorted(available_reviewers, key=expertise_match_score, reverse=True)
                selected = [r.id for r in sorted_reviewers[:num_reviewers]]
            else:
                # Fall back to random
                candidates = list(available_reviewers)
                random.shuffle(candidates)
                selected = [r.id for r in candidates[:num_reviewers]]

        elif strategy == AssignmentStrategy.LEAST_RECENTLY_USED:
            # Sort by least recently used (AssignmentStrategy.LEAST_RECENTLY_USED)
            sorted_reviewers = sorted(
                available_reviewers,
                key=lambda r: self._recent_assignments[r.id],
            )
            selected = [r.id for r in sorted_reviewers[:num_reviewers]]

        # Update assignment counts and load
        for reviewer_id in selected:
            self._recent_assignments[reviewer_id] += 1
            if reviewer_id in self.pool.reviewers:
                self.pool.reviewers[reviewer_id].current_load += 1
                self.pool.reviewers[reviewer_id].last_active_at = datetime.now(timezone.utc).isoformat()

        return selected

    def unassign_reviewer(self, request_id: str, reviewer_id: str) -> None:
        """Unassign a reviewer from a review request."""
        if reviewer_id in self.pool.reviewers:
            self.pool.reviewers[reviewer_id].current_load = max(
                0, self.pool.reviewers[reviewer_id].current_load - 1
            )

    def _get_candidate_reviewers(self, expertise: Optional[List[str]] = None) -> List[Reviewer]:
        """Get candidate reviewers based on availability and expertise."""
        candidates = []
        for reviewer in self.pool.reviewers.values():
            if not reviewer.is_available:
                continue
            if expertise:
                # At least one matching expertise
                if not set(expertise) & set(reviewer.expertise):
                    continue
            candidates.append(reviewer)
        return candidates

    def add_reviewer(self, reviewer: Reviewer) -> None:
        """Add a reviewer to the pool."""
        self.pool.add_reviewer(reviewer)

    def remove_reviewer(self, reviewer_id: str) -> bool:
        """Remove a reviewer from the pool."""
        return self.pool.remove_reviewer(reviewer_id)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the reviewer pool."""
        total = len(self.pool.reviewers)
        available = len(self._get_candidate_reviewers())
        return {
            "total_reviewers": total,
            "available_reviewers": available,
            "unavailable_reviewers": total - available,
            "recent_assignments": dict(self._recent_assignments),
        }
