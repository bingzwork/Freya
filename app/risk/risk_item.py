"""Risk Item module for defining individual risk items."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import total_ordering
from typing import Dict, List, Any, Optional
import uuid


@total_ordering
class RiskSeverity(Enum):
    """Severity levels for risks."""
    CRITICAL = "critical"      # System failure, data loss, security breach
    HIGH = "high"              # Major functionality impact, significant delays
    MEDIUM = "medium"          # Moderate impact, some delays or workarounds
    LOW = "low"                # Minor impact, minor delays
    INFO = "info"              # Informational, no significant impact

    @property
    def score(self) -> int:
        """Get numeric score for severity."""
        return {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "info": 1,
        }[self.value]

    def __lt__(self, other: "RiskSeverity") -> bool:
        if not isinstance(other, RiskSeverity):
            return NotImplemented
        return self.score < other.score


class RiskProbability(Enum):
    """Probability levels for risks."""
    CERTAIN = "certain"        # Will almost certainly occur (>90%)
    LIKELY = "likely"          # Likely to occur (60-90%)
    POSSIBLE = "possible"      # May occur (30-60%)
    UNLIKELY = "unlikely"      # Unlikely to occur (10-30%)
    RARE = "rare"              # Rare, unlikely to occur (<10%)

    @property
    def score(self) -> int:
        """Get numeric score for probability."""
        return {
            "certain": 5,
            "likely": 4,
            "possible": 3,
            "unlikely": 2,
            "rare": 1,
        }[self.value]


class RiskStatus(Enum):
    """Status of a risk item."""
    IDENTIFIED = "identified"      # Risk has been identified but not assessed
    ASSESSED = "assessed"          # Risk has been assessed
    MITIGATING = "mitigating"      # Mitigation is in progress
    MITIGATED = "mitigated"        # Risk has been mitigated
    ACCEPTED = "accepted"          # Risk has been accepted as-is
    CLOSED = "closed"              # Risk is no longer relevant
    MONITORING = "monitoring"      # Risk is being monitored


class RiskCategory(Enum):
    """Categories of risks."""
    TECHNICAL = "technical"        # Technical implementation risks
    SECURITY = "security"          # Security vulnerabilities
    PERFORMANCE = "performance"    # Performance issues
    RELIABILITY = "reliability"    # System reliability issues
    MAINTAINABILITY = "maintainability"  # Code maintainability issues
    SCALABILITY = "scalability"    # Scalability concerns
    COMPLIANCE = "compliance"      # Regulatory compliance issues
    BUSINESS = "business"          # Business continuity risks
    OPERATIONAL = "operational"    # Operational risks
    FINANCIAL = "financial"        # Financial/budget risks
    SCHEDULE = "schedule"          # Project schedule risks
    RESOURCE = "resource"          # Resource availability risks
    QUALITY = "quality"            # Quality assurance risks
    INTEGRATION = "integration"    # Integration risks
    DEPENDENCY = "dependency"      # Third-party dependency risks


@dataclass
class RiskItem:
    """Represents an individual risk item."""
    # Required fields
    title: str
    category: RiskCategory

    # Optional fields with defaults
    id: str = field(default_factory=lambda: f"risk_{uuid.uuid4().hex[:8]}")
    description: str = ""
    severity: RiskSeverity = RiskSeverity.MEDIUM
    probability: RiskProbability = RiskProbability.POSSIBLE
    status: RiskStatus = RiskStatus.IDENTIFIED
    impact: str = ""
    likely_hood: float = 0.5  # 0.0 to 1.0
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    related_components: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if isinstance(self.category, str):
            self.category = RiskCategory(self.category)
        if isinstance(self.severity, str):
            self.severity = RiskSeverity(self.severity)
        if isinstance(self.probability, str):
            self.probability = RiskProbability(self.probability)
        if isinstance(self.status, str):
            self.status = RiskStatus(self.status)

    @property
    def risk_score(self) -> float:
        """Calculate the risk score based on severity and probability.

        Formula: score = severity_score * probability_score * likelihood_factor
        """
        severity_score = self.severity.score
        probability_score = self.probability.score
        # Normalize likelihood to 0-1 range and adjust
        likelihood_factor = self.likely_hood
        return (severity_score * probability_score * likelihood_factor) / 25.0 * 100

    @property
    def risk_level(self) -> str:
        """Determine the overall risk level based on the score."""
        score = self.risk_score
        if score >= 80:
            return "critical"
        elif score >= 60:
            return "high"
        elif score >= 40:
            return "medium"
        elif score >= 20:
            return "low"
        return "info"

    @property
    def is_active(self) -> bool:
        """Check if the risk is still active."""
        return self.status in [
            RiskStatus.IDENTIFIED,
            RiskStatus.ASSESSED,
            RiskStatus.MITIGATING,
            RiskStatus.MONITORING,
        ]

    @property
    def is_closed(self) -> bool:
        """Check if the risk is closed."""
        return self.status in [
            RiskStatus.MITIGATED,
            RiskStatus.ACCEPTED,
            RiskStatus.CLOSED,
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "probability": self.probability.value,
            "status": self.status.value,
            "impact": self.impact,
            "likely_hood": self.likely_hood,
            "owner": self.owner,
            "tags": self.tags,
            "related_components": self.related_components,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskItem":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"risk_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", RiskCategory.TECHNICAL.value),
            severity=data.get("severity", RiskSeverity.MEDIUM.value),
            probability=data.get("probability", RiskProbability.POSSIBLE.value),
            status=data.get("status", RiskStatus.IDENTIFIED.value),
            impact=data.get("impact", ""),
            likely_hood=data.get("likely_hood", 0.5),
            owner=data.get("owner", ""),
            tags=data.get("tags", []),
            related_components=data.get("related_components", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def update_status(self, status: RiskStatus) -> None:
        """Update the risk status."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def update_severity(self, severity: RiskSeverity) -> None:
        """Update the risk severity."""
        self.severity = severity
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def update_probability(self, probability: RiskProbability) -> None:
        """Update the risk probability."""
        self.probability = probability
        self.updated_at = datetime.now(timezone.utc).isoformat()
