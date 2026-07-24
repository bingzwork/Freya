"""Risk Metrics module for tracking and calculating risk metrics."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from app.risk.risk_item import RiskItem, RiskSeverity, RiskProbability, RiskStatus, RiskCategory
from app.risk.risk_assessment import RiskAssessment
from app.risk.risk_mitigation import RiskMitigationStrategy, RiskMitigationPlan, MitigationStatus


@dataclass
class RiskScoreCalculator:
    """Calculates risk scores using various methodologies."""

    # Weighting factors for different calculation methods
    severity_weight: float = 1.0
    probability_weight: float = 1.0
    likelihood_weight: float = 1.0
    impact_weight: float = 0.5

    def calculate_basic_score(
        self,
        severity: RiskSeverity,
        probability: RiskProbability,
        likelihood: float = 0.5,
    ) -> float:
        """Calculate a basic risk score.

        Formula: score = (severity_score * probability_score * likelihood) / max_possible * 100
        """
        severity_score = severity.score
        probability_score = probability.score
        max_possible = 5.0 * 5.0  # Max severity * max probability

        return (severity_score * probability_score * likelihood / max_possible) * 100

    def calculate_weighted_score(
        self,
        risk: RiskItem,
    ) -> float:
        """Calculate a weighted risk score considering multiple factors."""
        severity_score = risk.severity.score * self.severity_weight
        probability_score = risk.probability.score * self.probability_weight
        likelihood_factor = risk.likely_hood * self.likelihood_weight

        # Normalize and calculate
        max_possible = (5.0 * self.severity_weight) * (5.0 * self.probability_weight)
        base_score = (severity_score * probability_score * likelihood_factor / max_possible) * 100

        # Add impact factor if available
        impact_factor = 0.0
        if risk.impact:
            # Estimate impact score based on description length and keywords
            impact_factor = min(len(risk.impact) / 100.0, 1.0) * self.impact_weight * 10

        return min(base_score + impact_factor, 100.0)

    def calculate_fmea_score(
        self,
        severity: int,
        occurrence: int,
        detection: int,
    ) -> int:
        """Calculate FMEA (Failure Mode and Effects Analysis) score.

        RPN = Severity * Occurrence * Detection
        All values are from 1-10.
        """
        return severity * occurrence * detection

    def calculate_dread_score(
        self,
        damage: int,
        reproducibility: int,
        exploitability: int,
        affected_users: int,
        discoverability: int,
    ) -> int:
        """Calculate DREAD (Microsoft) risk score.

        DREAD = (Damage + Reproducibility + Exploitability + Affected + Discoverability)
        All values are from 1-10.
        """
        return damage + reproducibility + exploitability + affected_users + discoverability

    def classify_score(self, score: float) -> str:
        """Classify a score into a risk level."""
        if score >= 80:
            return "critical"
        elif score >= 60:
            return "high"
        elif score >= 40:
            return "medium"
        elif score >= 20:
            return "low"
        return "info"


@dataclass
class RiskMetrics:
    """Tracks and reports risk metrics over time."""

    # Current metrics
    total_risks: int = 0
    active_risks: int = 0
    closed_risks: int = 0
    critical_risks: int = 0
    high_risks: int = 0
    medium_risks: int = 0
    low_risks: int = 0
    info_risks: int = 0

    # Historical metrics
    metrics_history: List[Dict[str, Any]] = field(default_factory=list)

    # Mitigation metrics
    total_mitigations: int = 0
    completed_mitigations: int = 0
    in_progress_mitigations: int = 0
    planned_mitigations: int = 0

    # Score metrics
    total_risk_score: float = 0.0
    average_risk_score: float = 0.0
    highest_risk_score: float = 0.0

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_risks": self.total_risks,
            "active_risks": self.active_risks,
            "closed_risks": self.closed_risks,
            "critical_risks": self.critical_risks,
            "high_risks": self.high_risks,
            "medium_risks": self.medium_risks,
            "low_risks": self.low_risks,
            "info_risks": self.info_risks,
            "total_mitigations": self.total_mitigations,
            "completed_mitigations": self.completed_mitigations,
            "in_progress_mitigations": self.in_progress_mitigations,
            "planned_mitigations": self.planned_mitigations,
            "total_risk_score": self.total_risk_score,
            "average_risk_score": self.average_risk_score,
            "highest_risk_score": self.highest_risk_score,
            "created_at": self.created_at,
            "metrics_history": self.metrics_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskMetrics":
        """Create from dictionary."""
        return cls(
            total_risks=data.get("total_risks", 0),
            active_risks=data.get("active_risks", 0),
            closed_risks=data.get("closed_risks", 0),
            critical_risks=data.get("critical_risks", 0),
            high_risks=data.get("high_risks", 0),
            medium_risks=data.get("medium_risks", 0),
            low_risks=data.get("low_risks", 0),
            info_risks=data.get("info_risks", 0),
            total_mitigations=data.get("total_mitigations", 0),
            completed_mitigations=data.get("completed_mitigations", 0),
            in_progress_mitigations=data.get("in_progress_mitigations", 0),
            planned_mitigations=data.get("planned_mitigations", 0),
            total_risk_score=data.get("total_risk_score", 0.0),
            average_risk_score=data.get("average_risk_score", 0.0),
            highest_risk_score=data.get("highest_risk_score", 0.0),
            created_at=data.get("created_at", ""),
            metrics_history=data.get("metrics_history", []),
        )

    @classmethod
    def from_risk_items(
        cls,
        risk_items: List[RiskItem],
        mitigation_strategies: Optional[List[RiskMitigationStrategy]] = None,
    ) -> "RiskMetrics":
        """Create metrics from a list of risk items."""
        metrics = cls()

        metrics.total_risks = len(risk_items)
        metrics.active_risks = len([r for r in risk_items if r.is_active])
        metrics.closed_risks = len([r for r in risk_items if r.is_closed])
        metrics.critical_risks = len([r for r in risk_items if r.risk_level == "critical"])
        metrics.high_risks = len([r for r in risk_items if r.risk_level == "high"])
        metrics.medium_risks = len([r for r in risk_items if r.risk_level == "medium"])
        metrics.low_risks = len([r for r in risk_items if r.risk_level == "low"])
        metrics.info_risks = len([r for r in risk_items if r.risk_level == "info"])

        risk_scores = [r.risk_score for r in risk_items]
        metrics.total_risk_score = sum(risk_scores)
        metrics.average_risk_score = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
        metrics.highest_risk_score = max(risk_scores) if risk_scores else 0.0

        if mitigation_strategies:
            metrics.total_mitigations = len(mitigation_strategies)
            metrics.completed_mitigations = len([s for s in mitigation_strategies if s.status == MitigationStatus.COMPLETED])
            metrics.in_progress_mitigations = len([s for s in mitigation_strategies if s.status == MitigationStatus.IN_PROGRESS])
            metrics.planned_mitigations = len([s for s in mitigation_strategies if s.status == MitigationStatus.PLANNED])

        return metrics

    def add_to_history(self) -> None:
        """Add current metrics to history."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_risks": self.total_risks,
            "active_risks": self.active_risks,
            "critical_risks": self.critical_risks,
            "high_risks": self.high_risks,
            "total_risk_score": self.total_risk_score,
            "average_risk_score": self.average_risk_score,
        }
        self.metrics_history.append(snapshot)
        # Keep only the last 100 entries
        if len(self.metrics_history) > 100:
            self.metrics_history = self.metrics_history[-100:]

    @property
    def risk_trend(self) -> str:
        """Determine the trend based on history."""
        if len(self.metrics_history) < 2:
            return "stable"

        recent = self.metrics_history[-1]
        past = self.metrics_history[-2]

        if recent["total_risks"] > past["total_risks"]:
            return "worsening"
        elif recent["total_risks"] < past["total_risks"]:
            return "improving"
        elif recent["average_risk_score"] > past["average_risk_score"]:
            return "worsening"
        elif recent["average_risk_score"] < past["average_risk_score"]:
            return "improving"
        return "stable"

    @property
    def mitigation_coverage(self) -> float:
        """Calculate mitigation coverage percentage."""
        if self.total_risks == 0:
            return 0.0
        return (self.completed_mitigations / self.total_risks) * 100

    @property
    def risk_reduction(self) -> float:
        """Calculate the risk reduction percentage (closed risks / total)."""
        if self.total_risks == 0:
            return 0.0
        return (self.closed_risks / self.total_risks) * 100

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the metrics."""
        return {
            "total_risks": self.total_risks,
            "active_risks": self.active_risks,
            "closed_risks": self.closed_risks,
            "risk_reduction_percentage": self.risk_reduction,
            "critical_risks": self.critical_risks,
            "high_risks": self.high_risks,
            "medium_risks": self.medium_risks,
            "low_risks": self.low_risks,
            "info_risks": self.info_risks,
            "total_risk_score": self.total_risk_score,
            "average_risk_score": self.average_risk_score,
            "highest_risk_score": self.highest_risk_score,
            "total_mitigations": self.total_mitigations,
            "completed_mitigations": self.completed_mitigations,
            "mitigation_coverage_percentage": self.mitigation_coverage,
            "risk_trend": self.risk_trend,
        }

    def get_distribution(self) -> Dict[str, Any]:
        """Get the distribution of risks."""
        return {
            "by_level": {
                "critical": self.critical_risks,
                "high": self.high_risks,
                "medium": self.medium_risks,
                "low": self.low_risks,
                "info": self.info_risks,
            },
            "by_status": {
                "active": self.active_risks,
                "closed": self.closed_risks,
            },
        }

    def get_time_series(self) -> List[Dict[str, Any]]:
        """Get time series data for metrics."""
        return self.metrics_history

    def get_category_metrics(
        self,
        risk_items: List[RiskItem],
    ) -> Dict[str, Dict[str, Any]]:
        """Get metrics grouped by category."""
        categories = defaultdict(lambda: {"count": 0, "total_score": 0.0, "risks": []})

        for risk in risk_items:
            category = risk.category.value
            categories[category]["count"] += 1
            categories[category]["total_score"] += risk.risk_score
            categories[category]["risks"].append(risk.to_dict())

        # Calculate averages
        for category, data in categories.items():
            if data["count"] > 0:
                data["average_score"] = data["total_score"] / data["count"]
            else:
                data["average_score"] = 0.0

        return dict(categories)
