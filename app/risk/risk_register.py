"""Risk Register module for managing a registry of all risks."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import json
from pathlib import Path

from app.risk.risk_item import RiskItem, RiskSeverity, RiskProbability, RiskStatus, RiskCategory
from app.risk.risk_assessment import RiskAssessment, RiskAssessmentResult


@dataclass
class RiskRegister:
    """Registry for managing all identified risks."""

    # Storage
    risk_items: Dict[str, RiskItem] = field(default_factory=dict)
    assessments: Dict[str, RiskAssessment] = field(default_factory=dict)
    assessment_results: Dict[str, RiskAssessmentResult] = field(default_factory=dict)

    # Configuration
    workspace: Path = field(default_factory=lambda: Path("."))
    register_file: str = ".risk_register.json"

    def __post_init__(self):
        if isinstance(self.workspace, str):
            self.workspace = Path(self.workspace)
        self._ensure_workspace()
        self._load_register()

    def _ensure_workspace(self) -> None:
        """Ensure the workspace directory exists."""
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _get_register_path(self) -> Path:
        """Get the path to the register file."""
        return self.workspace / self.register_file

    def _load_register(self) -> None:
        """Load the register from disk."""
        register_path = self._get_register_path()
        if not register_path.exists():
            return
        try:
            with open(register_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.risk_items = {
                    r["id"]: RiskItem.from_dict(r) for r in data.get("risk_items", [])
                }
                self.assessments = {
                    a["id"]: RiskAssessment.from_dict(a) for a in data.get("assessments", [])
                }
                self.assessment_results = {
                    r["assessment_id"]: RiskAssessmentResult.from_dict(r)
                    for r in data.get("assessment_results", [])
                }
        except Exception as e:
            print(f"Error loading risk register: {e}")

    def _save_register(self) -> None:
        """Save the register to disk."""
        register_path = self._get_register_path()
        data = {
            "risk_items": [r.to_dict() for r in self.risk_items.values()],
            "assessments": [a.to_dict() for a in self.assessments.values()],
            "assessment_results": [r.to_dict() for r in self.assessment_results.values()],
        }
        try:
            with open(register_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving risk register: {e}")

    def add_risk(
        self,
        title: str,
        category: RiskCategory,
        description: str = "",
        severity: RiskSeverity = RiskSeverity.MEDIUM,
        probability: RiskProbability = RiskProbability.POSSIBLE,
        status: RiskStatus = RiskStatus.IDENTIFIED,
        impact: str = "",
        likely_hood: float = 0.5,
        owner: str = "",
        tags: Optional[List[str]] = None,
        related_components: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RiskItem:
        """Add a new risk to the register."""
        risk = RiskItem(
            title=title,
            category=category,
            description=description,
            severity=severity,
            probability=probability,
            status=status,
            impact=impact,
            likely_hood=likely_hood,
            owner=owner,
            tags=tags or [],
            related_components=related_components or [],
            metadata=metadata or {},
        )
        self.risk_items[risk.id] = risk
        self._save_register()
        return risk

    def update_risk(self, risk_id: str, **kwargs) -> bool:
        """Update an existing risk."""
        risk = self.risk_items.get(risk_id)
        if not risk:
            return False
        for key, value in kwargs.items():
            if hasattr(risk, key):
                setattr(risk, key, value)
        risk.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_register()
        return True

    def remove_risk(self, risk_id: str) -> bool:
        """Remove a risk from the register."""
        if risk_id in self.risk_items:
            del self.risk_items[risk_id]
            self._save_register()
            return True
        return False

    def get_risk(self, risk_id: str) -> Optional[RiskItem]:
        """Get a risk by ID."""
        return self.risk_items.get(risk_id)

    def list_risks(
        self,
        category: Optional[RiskCategory] = None,
        severity: Optional[RiskSeverity] = None,
        status: Optional[RiskStatus] = None,
        owner: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[RiskItem]:
        """List risks with optional filters."""
        risks = list(self.risk_items.values())

        if category:
            risks = [r for r in risks if r.category == category]
        if severity:
            risks = [r for r in risks if r.severity == severity]
        if status:
            risks = [r for r in risks if r.status == status]
        if owner:
            risks = [r for r in risks if r.owner == owner]
        if tags:
            risks = [r for r in risks if any(t in r.tags for t in tags)]

        return risks

    def list_active_risks(self) -> List[RiskItem]:
        """List all active (non-closed) risks."""
        return [r for r in self.risk_items.values() if r.is_active]

    def list_closed_risks(self) -> List[RiskItem]:
        """List all closed risks."""
        return [r for r in self.risk_items.values() if r.is_closed]

    def list_risks_by_level(self, level: str) -> List[RiskItem]:
        """List risks by risk level."""
        return [r for r in self.risk_items.values() if r.risk_level == level]

    def list_critical_risks(self) -> List[RiskItem]:
        """List all critical risks."""
        return self.list_risks_by_level("critical")

    def list_high_risks(self) -> List[RiskItem]:
        """List all high risks."""
        return self.list_risks_by_level("high")

    def add_assessment(self, assessment: RiskAssessment) -> None:
        """Add a risk assessment."""
        self.assessments[assessment.id] = assessment
        self._save_register()

    def get_assessment(self, assessment_id: str) -> Optional[RiskAssessment]:
        """Get an assessment by ID."""
        return self.assessments.get(assessment_id)

    def list_assessments(self) -> List[RiskAssessment]:
        """List all assessments."""
        return list(self.assessments.values())

    def add_assessment_result(self, result: RiskAssessmentResult) -> None:
        """Add an assessment result."""
        self.assessment_results[result.assessment_id] = result
        self._save_register()

    def get_assessment_result(self, assessment_id: str) -> Optional[RiskAssessmentResult]:
        """Get an assessment result by ID."""
        return self.assessment_results.get(assessment_id)

    def clear(self) -> None:
        """Clear all data from the register."""
        self.risk_items = {}
        self.assessments = {}
        self.assessment_results = {}
        self._save_register()

    @property
    def count(self) -> int:
        """Get the total number of risks."""
        return len(self.risk_items)

    @property
    def active_count(self) -> int:
        """Get the number of active risks."""
        return len(self.list_active_risks())

    @property
    def closed_count(self) -> int:
        """Get the number of closed risks."""
        return len(self.list_closed_risks())

    @property
    def critical_count(self) -> int:
        """Get the number of critical risks."""
        return len(self.list_critical_risks())

    @property
    def high_count(self) -> int:
        """Get the number of high risks."""
        return len(self.list_high_risks())

    @property
    def total_risk_score(self) -> float:
        """Get the total risk score for all active risks."""
        return sum(r.risk_score for r in self.list_active_risks())

    @property
    def average_risk_score(self) -> float:
        """Get the average risk score for all active risks."""
        active = self.list_active_risks()
        if not active:
            return 0.0
        return self.total_risk_score / len(active)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the risk register."""
        return {
            "total_risks": self.count,
            "active_risks": self.active_count,
            "closed_risks": self.closed_count,
            "critical_risks": self.critical_count,
            "high_risks": self.high_count,
            "medium_risks": len(self.list_risks_by_level("medium")),
            "low_risks": len(self.list_risks_by_level("low")),
            "info_risks": len(self.list_risks_by_level("info")),
            "total_risk_score": self.total_risk_score,
            "average_risk_score": self.average_risk_score,
            "total_assessments": len(self.assessments),
        }

    def get_risk_distribution(self) -> Dict[str, int]:
        """Get the distribution of risks by level."""
        return {
            "critical": self.critical_count,
            "high": self.high_count,
            "medium": len(self.list_risks_by_level("medium")),
            "low": len(self.list_risks_by_level("low")),
            "info": len(self.list_risks_by_level("info")),
        }

    def get_category_distribution(self) -> Dict[str, int]:
        """Get the distribution of risks by category."""
        distribution = {}
        for risk in self.risk_items.values():
            category = risk.category.value
            distribution[category] = distribution.get(category, 0) + 1
        return distribution

    def export_to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary."""
        return {
            "risk_items": [r.to_dict() for r in self.risk_items.values()],
            "assessments": [a.to_dict() for a in self.assessments.values()],
            "assessment_results": [r.to_dict() for r in self.assessment_results.values()],
            "summary": self.get_summary(),
        }

    def import_from_dict(self, data: Dict[str, Any]) -> None:
        """Import data from a dictionary."""
        self.risk_items = {
            r["id"]: RiskItem.from_dict(r) for r in data.get("risk_items", [])
        }
        self.assessments = {
            a["id"]: RiskAssessment.from_dict(a) for a in data.get("assessments", [])
        }
        self.assessment_results = {
            r["assessment_id"]: RiskAssessmentResult.from_dict(r)
            for r in data.get("assessment_results", [])
        }
        self._save_register()
