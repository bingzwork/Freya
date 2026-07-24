"""Risk Assessment module for performing risk assessments."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import uuid

from app.risk.risk_item import RiskItem, RiskSeverity, RiskProbability, RiskStatus, RiskCategory


@dataclass
class RiskAssessmentResult:
    """Result of a risk assessment."""
    assessment_id: str
    risk_id: str
    assessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    severity: RiskSeverity = RiskSeverity.MEDIUM
    probability: RiskProbability = RiskProbability.POSSIBLE
    risk_score: float = 0.0
    findings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 0.0 to 1.0
    assessor: str = ""

    @property
    def risk_level(self) -> str:
        """Determine the risk level."""
        if self.risk_score >= 80:
            return "critical"
        elif self.risk_score >= 60:
            return "high"
        elif self.risk_score >= 40:
            return "medium"
        elif self.risk_score >= 20:
            return "low"
        return "info"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "assessment_id": self.assessment_id,
            "risk_id": self.risk_id,
            "assessed_at": self.assessed_at,
            "severity": self.severity.value,
            "probability": self.probability.value,
            "risk_score": self.risk_score,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "confidence": self.confidence,
            "assessor": self.assessor,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskAssessmentResult":
        """Create from dictionary."""
        return cls(
            assessment_id=data.get("assessment_id", ""),
            risk_id=data.get("risk_id", ""),
            assessed_at=data.get("assessed_at", ""),
            severity=RiskSeverity(data.get("severity", "medium")),
            probability=RiskProbability(data.get("probability", "possible")),
            risk_score=data.get("risk_score", 0.0),
            findings=data.get("findings", []),
            recommendations=data.get("recommendations", []),
            confidence=data.get("confidence", 1.0),
            assessor=data.get("assessor", ""),
        )


@dataclass
class RiskAssessment:
    """Represents a complete risk assessment session."""
    id: str = field(default_factory=lambda: f"assessment_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    scope: List[str] = field(default_factory=list)
    assessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assessor: str = ""
    status: str = "completed"  # pending, in_progress, completed, cancelled
    methodology: str = "qualitative"  # qualitative, quantitative, semi-quantitative

    # Results
    risk_items: List[RiskItem] = field(default_factory=list)
    assessment_results: List[RiskAssessmentResult] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "assessed_at": self.assessed_at,
            "assessor": self.assessor,
            "status": self.status,
            "methodology": self.methodology,
            "risk_items": [r.to_dict() for r in self.risk_items],
            "assessment_results": [r.to_dict() for r in self.assessment_results],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskAssessment":
        """Create from dictionary."""
        assessment = cls(
            id=data.get("id", f"assessment_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            scope=data.get("scope", []),
            assessed_at=data.get("assessed_at", ""),
            assessor=data.get("assessor", ""),
            status=data.get("status", "completed"),
            methodology=data.get("methodology", "qualitative"),
            metadata=data.get("metadata", {}),
        )
        assessment.risk_items = [
            RiskItem.from_dict(r) for r in data.get("risk_items", [])
        ]
        assessment.assessment_results = [
            RiskAssessmentResult.from_dict(r) for r in data.get("assessment_results", [])
        ]
        return assessment

    def add_risk_item(self, risk_item: RiskItem) -> None:
        """Add a risk item to the assessment."""
        self.risk_items.append(risk_item)

    def add_result(self, result: RiskAssessmentResult) -> None:
        """Add an assessment result."""
        self.assessment_results.append(result)

    @property
    def total_risk_score(self) -> float:
        """Calculate the total risk score for all items."""
        return sum(r.risk_score for r in self.risk_items)

    @property
    def average_risk_score(self) -> float:
        """Calculate the average risk score."""
        if not self.risk_items:
            return 0.0
        return self.total_risk_score / len(self.risk_items)

    @property
    def highest_risk(self) -> Optional[RiskItem]:
        """Get the highest risk item."""
        if not self.risk_items:
            return None
        return max(self.risk_items, key=lambda r: r.risk_score)

    @property
    def critical_count(self) -> int:
        """Count critical risks."""
        return len([r for r in self.risk_items if r.risk_level == "critical"])

    @property
    def high_count(self) -> int:
        """Count high risks."""
        return len([r for r in self.risk_items if r.risk_level == "high"])

    @property
    def summary(self) -> Dict[str, Any]:
        """Get a summary of the assessment."""
        return {
            "total_risk_items": len(self.risk_items),
            "total_risk_score": self.total_risk_score,
            "average_risk_score": self.average_risk_score,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": len([r for r in self.risk_items if r.risk_level == "medium"]),
            "low_count": len([r for r in self.risk_items if r.risk_level == "low"]),
            "info_count": len([r for r in self.risk_items if r.risk_level == "info"]),
            "highest_risk": self.highest_risk.to_dict() if self.highest_risk else None,
        }
