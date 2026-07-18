"""Issue representation for diagnostics.

This module defines the data structures for representing diagnostic issues.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Any, Optional


class IssueSeverity(Enum):
    """Severity levels for diagnostic issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IssueType(Enum):
    """Types of diagnostic issues."""
    BUG = "bug"
    PERFORMANCE = "performance"
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    ARCHITECTURAL = "architectural"
    DEPRECATION = "deprecation"
    TEST = "test"
    DOCUMENTATION = "documentation"
    MAINTENANCE = "maintenance"


@dataclass
class Issue:
    """Represents a diagnostic issue found in the codebase."""
    id: str
    title: str
    description: str
    severity: IssueSeverity
    issue_type: IssueType
    location: str  # file:line format
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    column: Optional[int] = None
    code_snippet: Optional[str] = None
    fix_suggestion: Optional[str] = None
    related_issues: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    resolution_notes: Optional[str] = None
    resolved_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert issue to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "type": self.issue_type.value,
            "location": self.location,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "column": self.column,
            "code_snippet": self.code_snippet,
            "fix_suggestion": self.fix_suggestion,
            "related_issues": self.related_issues,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolution_notes": self.resolution_notes,
            "resolved_timestamp": self.resolved_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Issue":
        """Create issue from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            severity=IssueSeverity(data["severity"]),
            issue_type=IssueType(data.get("type", "bug")),
            location=data["location"],
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            column=data.get("column"),
            code_snippet=data.get("code_snippet"),
            fix_suggestion=data.get("fix_suggestion"),
            related_issues=data.get("related_issues", []),
            tags=data.get("tags", []),
            timestamp=data.get("timestamp", ""),
            resolved=data.get("resolved", False),
            resolution_notes=data.get("resolution_notes"),
            resolved_timestamp=data.get("resolved_timestamp"),
        )

    def resolve(self, notes: str = "") -> None:
        """Mark the issue as resolved."""
        self.resolved = True
        self.resolution_notes = notes
        self.resolved_timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def severity_score(self) -> int:
        """Get numeric severity score (higher is worse)."""
        scores = {
            IssueSeverity.INFO: 0,
            IssueSeverity.WARNING: 1,
            IssueSeverity.ERROR: 2,
            IssueSeverity.CRITICAL: 3,
        }
        return scores.get(self.severity, 0)

    def __lt__(self, other: "Issue") -> bool:
        """Compare issues by severity (critical first)."""
        return self.severity_score > other.severity_score


@dataclass
class IssueCollection:
    """Collection of issues with filtering and aggregation."""
    issues: List[Issue] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        """Add an issue to the collection."""
        self.issues.append(issue)

    def filter_by_severity(self, severity: IssueSeverity) -> List[Issue]:
        """Filter issues by severity."""
        return [i for i in self.issues if i.severity == severity]

    def filter_by_type(self, issue_type: IssueType) -> List[Issue]:
        """Filter issues by type."""
        return [i for i in self.issues if i.issue_type == issue_type]

    def filter_by_file(self, file_path: str) -> List[Issue]:
        """Filter issues by file path."""
        return [i for i in self.issues if i.file_path == file_path]

    def filter_unresolved(self) -> List[Issue]:
        """Get all unresolved issues."""
        return [i for i in self.issues if not i.resolved]

    def filter_resolved(self) -> List[Issue]:
        """Get all resolved issues."""
        return [i for i in self.issues if i.resolved]

    def count_by_severity(self) -> Dict[str, int]:
        """Count issues by severity."""
        counts: Dict[str, int] = {}
        for severity in IssueSeverity:
            counts[severity.value] = len(self.filter_by_severity(severity))
        return counts

    def count_by_type(self) -> Dict[str, int]:
        """Count issues by type."""
        counts: Dict[str, int] = {}
        for issue_type in IssueType:
            counts[issue_type.value] = len(self.filter_by_type(issue_type))
        return counts

    def sorted_by_severity(self) -> List[Issue]:
        """Sort issues by severity (critical first)."""
        return sorted(self.issues, key=lambda i: i.severity_score, reverse=True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert collection to dictionary."""
        return {
            "total": len(self.issues),
            "unresolved": len(self.filter_unresolved()),
            "resolved": len(self.filter_resolved()),
            "by_severity": self.count_by_severity(),
            "by_type": self.count_by_type(),
            "issues": [i.to_dict() for i in self.issues],
        }
