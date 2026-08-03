"""
Improvement Prioritization.

Ranks and prioritizes improvement candidates based on impact, effort,
risk, confidence, and other criteria.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from app.safe_self_improvement.models import (
    ImprovementCandidate,
    ImprovementCategory,
    RiskLevel,
)
from app.core.logger import logger


class PrioritizationCriteria:
    """Criteria and weights for prioritization."""

    def __init__(
        self,
        impact_weight: float = 0.4,
        effort_weight: float = 0.2,       # Lower effort = higher priority
        risk_weight: float = 0.2,         # Lower risk = higher priority
        confidence_weight: float = 0.2,
        category_weights: Optional[Dict[str, float]] = None,
        source_weights: Optional[Dict[str, float]] = None,
        min_score_threshold: float = 0.0,
    ):
        self.impact_weight = impact_weight
        self.effort_weight = effort_weight
        self.risk_weight = risk_weight
        self.confidence_weight = confidence_weight
        self.category_weights = category_weights or self._default_category_weights()
        self.source_weights = source_weights or self._default_source_weights()
        self.min_score_threshold = min_score_threshold

    def _default_category_weights(self) -> Dict[str, float]:
        """Default weights by improvement category."""
        return {
            ImprovementCategory.SECURITY.value: 1.5,
            ImprovementCategory.CORRECTNESS.value: 1.3,
            ImprovementCategory.PERFORMANCE.value: 1.2,
            ImprovementCategory.DEPRECATION.value: 1.1,
            ImprovementCategory.ARCHITECTURE.value: 1.1,
            ImprovementCategory.COMPLEXITY.value: 1.0,
            ImprovementCategory.TESTS.value: 1.0,
            ImprovementCategory.DOCUMENTATION.value: 0.8,
            ImprovementCategory.STYLE.value: 0.7,
            ImprovementCategory.DEPENDENCY.value: 0.9,
        }

    def _default_source_weights(self) -> Dict[str, float]:
        """Default weights by source."""
        return {
            "diagnostics": 1.0,
            "evaluation": 1.1,
            "manual": 1.2,
            "autonomous": 0.9,
            "security_scan": 1.3,
            "performance_profile": 1.2,
        }


@dataclass
class PrioritizationResult:
    """Result of prioritization for a single candidate."""

    candidate: ImprovementCandidate
    score: float
    rank: int
    breakdown: Dict[str, float]
    reasons: List[str]
    meets_threshold: bool


class ImprovementPrioritizer:
    """
    Prioritizes improvement candidates based on configurable criteria.

    Supports multiple prioritization strategies and custom scoring functions.
    """

    def __init__(
        self,
        criteria: Optional[PrioritizationCriteria] = None,
        custom_scorers: Optional[List[Callable[[ImprovementCandidate], float]]] = None,
    ):
        self.criteria = criteria or PrioritizationCriteria()
        self.custom_scorers = custom_scorers or []
        self._lock = threading.RLock()
        self._prioritization_history: List[Dict[str, Any]] = []

    def prioritize(
        self,
        candidates: List[ImprovementCandidate],
        limit: Optional[int] = None,
    ) -> List[PrioritizationResult]:
        """
        Prioritize a list of candidates.

        Returns sorted list (highest priority first).
        """
        with self._lock:
            results = []

            for candidate in candidates:
                result = self._score_candidate(candidate)
                results.append(result)

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)

            # Assign ranks
            for i, result in enumerate(results):
                result.rank = i + 1

            # Apply limit
            if limit:
                results = results[:limit]

            # Record history
            self._prioritization_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidate_count": len(candidates),
                "top_candidate": results[0].candidate.id if results else None,
                "top_score": results[0].score if results else 0,
            })
            if len(self._prioritization_history) > 1000:
                self._prioritization_history = self._prioritization_history[-1000:]

            return results

    def _score_candidate(self, candidate: ImprovementCandidate) -> PrioritizationResult:
        """Score a single candidate."""
        breakdown = {}
        reasons = []

        # Impact score (0-1, higher is better)
        impact_score = candidate.estimated_impact
        breakdown["impact"] = impact_score * self.criteria.impact_weight
        reasons.append(f"Impact: {impact_score:.2f}")

        # Effort score (0-1, lower is better -> invert)
        effort_score = 1.0 - candidate.estimated_effort
        breakdown["effort"] = effort_score * self.criteria.effort_weight
        reasons.append(f"Effort (inverted): {effort_score:.2f}")

        # Risk score (0-1, lower is better -> invert)
        risk_order = {
            RiskLevel.NONE: 1.0,
            RiskLevel.LOW: 0.8,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.2,
            RiskLevel.CRITICAL: 0.0,
        }
        risk_score = risk_order.get(candidate.estimated_risk, 0.5)
        breakdown["risk"] = risk_score * self.criteria.risk_weight
        reasons.append(f"Risk (inverted): {risk_score:.2f}")

        # Confidence score (0-1, higher is better)
        confidence_score = candidate.confidence
        breakdown["confidence"] = confidence_score * self.criteria.confidence_weight
        reasons.append(f"Confidence: {confidence_score:.2f}")

        # Category multiplier
        category_mult = self.criteria.category_weights.get(
            candidate.category.value, 1.0
        )
        breakdown["category_multiplier"] = category_mult
        if category_mult != 1.0:
            reasons.append(f"Category multiplier ({candidate.category.value}): {category_mult:.2f}")

        # Source multiplier
        source_mult = self.criteria.source_weights.get(
            candidate.source, 1.0
        )
        breakdown["source_multiplier"] = source_mult
        if source_mult != 1.0:
            reasons.append(f"Source multiplier ({candidate.source}): {source_mult:.2f}")

        # Custom scorers
        custom_total = 0.0
        for i, scorer in enumerate(self.custom_scorers):
            try:
                custom_score = scorer(candidate)
                custom_total += custom_score
                breakdown[f"custom_{i}"] = custom_score
            except Exception as e:
                logger.warning(f"[ImprovementPrioritizer] Custom scorer {i} error: {e}")

        # Calculate final score
        base_score = sum(breakdown.get(k, 0) for k in ["impact", "effort", "risk", "confidence"])
        final_score = base_score * category_mult * source_mult + custom_total

        # Check threshold
        meets_threshold = final_score >= self.criteria.min_score_threshold

        return PrioritizationResult(
            candidate=candidate,
            score=final_score,
            rank=0,
            breakdown=breakdown,
            reasons=reasons,
            meets_threshold=meets_threshold,
        )

    def get_top_candidate(
        self, candidates: List[ImprovementCandidate]
    ) -> Optional[PrioritizationResult]:
        """Get the highest priority candidate."""
        results = self.prioritize(candidates, limit=1)
        return results[0] if results else None

    def filter_by_threshold(
        self, candidates: List[ImprovementCandidate]
    ) -> List[PrioritizationResult]:
        """Filter candidates that meet the minimum score threshold."""
        results = self.prioritize(candidates)
        return [r for r in results if r.meets_threshold]

    def get_prioritization_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get prioritization history."""
        with self._lock:
            return self._prioritization_history[-limit:]

    def add_custom_scorer(self, scorer: Callable[[ImprovementCandidate], float]) -> None:
        """Add a custom scoring function."""
        with self._lock:
            self.custom_scorers.append(scorer)

    def update_criteria(self, **kwargs) -> None:
        """Update prioritization criteria."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.criteria, key):
                    setattr(self.criteria, key, value)

    def get_criteria(self) -> Dict[str, Any]:
        """Get current criteria."""
        with self._lock:
            return {
                "impact_weight": self.criteria.impact_weight,
                "effort_weight": self.criteria.effort_weight,
                "risk_weight": self.criteria.risk_weight,
                "confidence_weight": self.criteria.confidence_weight,
                "category_weights": self.criteria.category_weights,
                "source_weights": self.criteria.source_weights,
                "min_score_threshold": self.criteria.min_score_threshold,
            }


# Predefined prioritization strategies
def create_security_focused_prioritizer() -> ImprovementPrioritizer:
    """Prioritize security improvements."""
    criteria = PrioritizationCriteria(
        impact_weight=0.3,
        effort_weight=0.1,
        risk_weight=0.3,
        confidence_weight=0.3,
        category_weights={
            ImprovementCategory.SECURITY.value: 2.0,
            ImprovementCategory.CORRECTNESS.value: 1.2,
        },
    )
    return ImprovementPrioritizer(criteria)


def create_performance_focused_prioritizer() -> ImprovementPrioritizer:
    """Prioritize performance improvements."""
    criteria = PrioritizationCriteria(
        impact_weight=0.5,
        effort_weight=0.2,
        risk_weight=0.1,
        confidence_weight=0.2,
        category_weights={
            ImprovementCategory.PERFORMANCE.value: 2.0,
            ImprovementCategory.COMPLEXITY.value: 1.3,
        },
    )
    return ImprovementPrioritizer(criteria)


def create_maintenance_prioritizer() -> ImprovementPrioritizer:
    """Prioritize maintenance improvements (tests, docs, deprecation)."""
    criteria = PrioritizationCriteria(
        impact_weight=0.3,
        effort_weight=0.3,
        risk_weight=0.2,
        confidence_weight=0.2,
        category_weights={
            ImprovementCategory.TESTS.value: 1.5,
            ImprovementCategory.DEPRECATION.value: 1.3,
            ImprovementCategory.DOCUMENTATION.value: 1.0,
            ImprovementCategory.STYLE.value: 1.0,
            ImprovementCategory.DEPENDENCY.value: 1.2,
        },
    )
    return ImprovementPrioritizer(criteria)


def create_balanced_prioritizer() -> ImprovementPrioritizer:
    """Create a balanced prioritizer (default)."""
    return ImprovementPrioritizer()