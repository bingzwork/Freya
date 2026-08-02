"""
Improvement Prioritization - Shared prioritization framework for Freya.

Provides a standardized prioritization system with:
- Priority scoring algorithms
- Cost vs benefit evaluation
- Risk scoring
- Impact assessment
- Dependency awareness
- Improvement ranking
- Execution priority
- Recommendation generation
- Shared prioritization interfaces for all autonomous improvement systems
"""

import threading
import math
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Set, TypeVar, Union
from uuid import uuid4

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub


T = TypeVar("T")


class PriorityAlgorithm(Enum):
    """Available prioritization algorithms."""
    WEIGHTED_SCORE = "weighted_score"          # Weighted composite score
    RICE = "rice"                              # Reach, Impact, Confidence, Effort
    WSJF = "wsjf"                              # Weighted Shortest Job First
    KANO = "kano"                              # Kano model (basic, performance, excitement)
    MOSCOW = "moscow"                          # Must, Should, Could, Won't
    CUSTOM = "custom"                          # Custom algorithm


class ImpactLevel(Enum):
    """Impact levels for improvements."""
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def score(self) -> float:
        scores = {
            ImpactLevel.NEGLIGIBLE: 0.1,
            ImpactLevel.LOW: 0.3,
            ImpactLevel.MEDIUM: 0.5,
            ImpactLevel.HIGH: 0.8,
            ImpactLevel.CRITICAL: 1.0,
        }
        return scores[self]


class UrgencyLevel(Enum):
    """Urgency levels."""
    NO_RUSH = "no_rush"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def score(self) -> float:
        scores = {
            UrgencyLevel.NO_RUSH: 0.1,
            UrgencyLevel.LOW: 0.3,
            UrgencyLevel.MEDIUM: 0.5,
            UrgencyLevel.HIGH: 0.8,
            UrgencyLevel.CRITICAL: 1.0,
        }
        return scores[self]


class EffortLevel(Enum):
    """Effort levels."""
    TRIVIAL = "trivial"      # < 1 hour
    SMALL = "small"          # 1-4 hours
    MEDIUM = "medium"        # 4-16 hours
    LARGE = "large"          # 16-40 hours
    XLARGE = "xlarge"        # 40+ hours

    @property
    def hours_estimate(self) -> float:
        estimates = {
            EffortLevel.TRIVIAL: 0.5,
            EffortLevel.SMALL: 2.5,
            EffortLevel.MEDIUM: 10,
            EffortLevel.LARGE: 28,
            EffortLevel.XLARGE: 60,
        }
        return estimates[self]


@dataclass
class ImprovementCandidate(Generic[T]):
    """A candidate improvement to be prioritized."""
    id: str = field(default_factory=lambda: f"imp_{uuid4().hex[:12]}")
    title: str = ""
    description: str = ""
    improvement_type: str = ""
    category: str = ""

    # Core attributes for prioritization
    impact: ImpactLevel = ImpactLevel.MEDIUM
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM
    effort: EffortLevel = EffortLevel.MEDIUM
    confidence: float = 0.8  # 0-1 confidence in estimates

    # Cost/benefit
    estimated_cost: float = 0.0      # Monetary or resource cost
    estimated_benefit: float = 0.0   # Monetary or value benefit
    roi: float = 0.0                 # Calculated ROI

    # Risk
    risk_score: float = 0.0          # 0-1 risk level
    risk_factors: List[str] = field(default_factory=list)

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # IDs of dependencies
    blocks: List[str] = field(default_factory=list)     # IDs of items this blocks

    # Metadata
    source: str = ""                 # Where this came from
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Computed
    priority_score: float = 0.0
    rank: int = 0
    algorithm_used: PriorityAlgorithm = PriorityAlgorithm.WEIGHTED_SCORE

    # Status
    status: str = "proposed"         # proposed, approved, in_progress, done, rejected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "improvement_type": self.improvement_type,
            "category": self.category,
            "impact": self.impact.value,
            "urgency": self.urgency.value,
            "effort": self.effort.value,
            "confidence": self.confidence,
            "estimated_cost": self.estimated_cost,
            "estimated_benefit": self.estimated_benefit,
            "roi": self.roi,
            "risk_score": self.risk_score,
            "risk_factors": self.risk_factors,
            "depends_on": self.depends_on,
            "blocks": self.blocks,
            "source": self.source,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "priority_score": self.priority_score,
            "rank": self.rank,
            "algorithm_used": self.algorithm_used.value,
            "status": self.status,
        }


@dataclass
class PrioritizationConfig:
    """Configuration for prioritization behavior."""
    # Algorithm
    default_algorithm: PriorityAlgorithm = PriorityAlgorithm.WEIGHTED_SCORE

    # Weighted score weights (must sum to 1.0)
    weight_impact: float = 0.30
    weight_urgency: float = 0.20
    weight_effort: float = 0.15       # Negative weight (lower effort = higher score)
    weight_confidence: float = 0.10
    weight_risk: float = 0.10         # Negative weight (lower risk = higher score)
    weight_roi: float = 0.10
    weight_dependencies: float = 0.05  # Bonus for unblocking others

    # RICE weights
    rice_reach_weight: float = 1.0
    rice_impact_weight: float = 1.0
    rice_confidence_weight: float = 1.0
    rice_effort_weight: float = 1.0

    # WSJF
    wsjf_cost_of_delay_weight: float = 1.0
    wsjf_job_size_weight: float = 1.0

    # Thresholds
    min_priority_score: float = 0.0
    auto_approve_threshold: float = 0.8
    require_review_threshold: float = 0.5

    # Dependency handling
    boost_unblockers: bool = True
    penalty_blocked: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_algorithm": self.default_algorithm.value,
            "weight_impact": self.weight_impact,
            "weight_urgency": self.weight_urgency,
            "weight_effort": self.weight_effort,
            "weight_confidence": self.weight_confidence,
            "weight_risk": self.weight_risk,
            "weight_roi": self.weight_roi,
            "weight_dependencies": self.weight_dependencies,
            "rice_reach_weight": self.rice_reach_weight,
            "rice_impact_weight": self.rice_impact_weight,
            "rice_confidence_weight": self.rice_confidence_weight,
            "rice_effort_weight": self.rice_effort_weight,
            "wsjf_cost_of_delay_weight": self.wsjf_cost_of_delay_weight,
            "wsjf_job_size_weight": self.wsjf_job_size_weight,
            "min_priority_score": self.min_priority_score,
            "auto_approve_threshold": self.auto_approve_threshold,
            "require_review_threshold": self.require_review_threshold,
            "boost_unblockers": self.boost_unblockers,
            "penalty_blocked": self.penalty_blocked,
        }


@dataclass
class PrioritizationResult:
    """Result of a prioritization run."""
    candidates: List[ImprovementCandidate]
    algorithm_used: PriorityAlgorithm
    ranked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_candidates: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    needs_review_count: int = 0

    # Statistics
    score_distribution: Dict[str, int] = field(default_factory=dict)
    category_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "algorithm_used": self.algorithm_used.value,
            "ranked_at": self.ranked_at,
            "total_candidates": self.total_candidates,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "needs_review_count": self.needs_review_count,
            "score_distribution": self.score_distribution,
            "category_distribution": self.category_distribution,
        }


class PrioritizationAlgorithm(ABC):
    """Abstract base for prioritization algorithms."""

    @abstractmethod
    def calculate_score(self, candidate: ImprovementCandidate, config: PrioritizationConfig, all_candidates: List[ImprovementCandidate]) -> float:
        """Calculate priority score for a candidate."""
        pass

    @property
    @abstractmethod
    def name(self) -> PriorityAlgorithm:
        pass


class WeightedScoreAlgorithm(PrioritizationAlgorithm):
    """Weighted composite score algorithm."""

    @property
    def name(self) -> PriorityAlgorithm:
        return PriorityAlgorithm.WEIGHTED_SCORE

    def calculate_score(
        self,
        candidate: ImprovementCandidate,
        config: PrioritizationConfig,
        all_candidates: List[ImprovementCandidate],
    ) -> float:
        # Normalize effort (lower is better)
        max_effort = max(c.effort.hours_estimate for c in all_candidates) or 1
        effort_score = 1.0 - (candidate.effort.hours_estimate / max_effort)

        # Normalize risk (lower is better)
        risk_score = 1.0 - candidate.risk_score

        # Normalize ROI
        max_roi = max(c.roi for c in all_candidates) if any(c.roi > 0 for c in all_candidates) else 1
        roi_score = candidate.roi / max_roi if max_roi > 0 else 0

        # Dependency bonus
        dep_bonus = 0.0
        if config.boost_unblockers:
            unblock_count = sum(1 for c in all_candidates if candidate.id in c.depends_on)
            dep_bonus = min(0.2, unblock_count * 0.05)

        # Blocked penalty
        blocked_penalty = 0.0
        if config.penalty_blocked and candidate.depends_on:
            unresolved = sum(1 for dep_id in candidate.depends_on
                            if any(c.id == dep_id and c.status != "done" for c in all_candidates))
            blocked_penalty = min(0.3, unresolved * 0.1)

        score = (
            config.weight_impact * candidate.impact.score +
            config.weight_urgency * candidate.urgency.score +
            config.weight_effort * effort_score +
            config.weight_confidence * candidate.confidence +
            config.weight_risk * risk_score +
            config.weight_roi * roi_score +
            config.weight_dependencies * dep_bonus -
            blocked_penalty
        )

        return max(0.0, min(1.0, score))


class RICEAlgorithm(PrioritizationAlgorithm):
    """RICE scoring algorithm (Reach, Impact, Confidence, Effort)."""

    @property
    def name(self) -> PriorityAlgorithm:
        return PriorityAlgorithm.RICE

    def calculate_score(
        self,
        candidate: ImprovementCandidate,
        config: PrioritizationConfig,
        all_candidates: List[ImprovementCandidate],
    ) -> float:
        # Reach: estimated number of users/systems affected (from metadata)
        reach = candidate.metadata.get("reach", 100)

        # Impact: 0.25 to 3 scale (using impact score * 3)
        impact = candidate.impact.score * 3

        # Confidence: 0-1
        confidence = candidate.confidence

        # Effort: person-months
        effort = candidate.effort.hours_estimate / 160  # 160 hours = 1 person-month

        if effort == 0:
            effort = 0.1

        score = (reach * impact * confidence) / effort
        return min(1.0, score / 10000)  # Normalize


class WSJFAlgorithm(PrioritizationAlgorithm):
    """Weighted Shortest Job First algorithm."""

    @property
    def name(self) -> PriorityAlgorithm:
        return PriorityAlgorithm.WSJF

    def calculate_score(
        self,
        candidate: ImprovementCandidate,
        config: PrioritizationConfig,
        all_candidates: List[ImprovementCandidate],
    ) -> float:
        # Cost of Delay = User/Business Value + Time Criticality + Risk Reduction
        user_value = candidate.impact.score * 10
        time_criticality = candidate.urgency.score * 10
        risk_reduction = (1.0 - candidate.risk_score) * 10

        cost_of_delay = user_value + time_criticality + risk_reduction

        # Job Size = Effort
        job_size = candidate.effort.hours_estimate

        if job_size == 0:
            job_size = 0.1

        wsjf = cost_of_delay / job_size
        return min(1.0, wsjf / 100)  # Normalize


class KanoAlgorithm(PrioritizationAlgorithm):
    """Kano model algorithm (categorizes into basic, performance, excitement)."""

    @property
    def name(self) -> PriorityAlgorithm:
        return PriorityAlgorithm.KANO

    def calculate_score(
        self,
        candidate: ImprovementCandidate,
        config: PrioritizationConfig,
        all_candidates: List[ImprovementCandidate],
    ) -> float:
        kano_type = candidate.metadata.get("kano_type", "performance")

        # Basic: must have, low excitement, high penalty if missing
        # Performance: linear satisfaction
        # Excitement: high delight, not expected

        if kano_type == "basic":
            # High priority if not done, lower if already implemented
            base_score = 0.8
            if candidate.status == "done":
                base_score = 0.3
        elif kano_type == "excitement":
            base_score = 0.7
        else:  # performance
            base_score = 0.5

        # Adjust by impact and urgency
        score = base_score * (candidate.impact.score + candidate.urgency.score) / 2
        return score


class MoSCoWAlgorithm(PrioritizationAlgorithm):
    """MoSCoW prioritization (Must, Should, Could, Won't)."""

    @property
    def name(self) -> PriorityAlgorithm:
        return PriorityAlgorithm.MOSCOW

    def calculate_score(
        self,
        candidate: ImprovementCandidate,
        config: PrioritizationConfig,
        all_candidates: List[ImprovementCandidate],
    ) -> float:
        moscow = candidate.metadata.get("moscow", "could").lower()

        base_scores = {
            "must": 1.0,
            "should": 0.7,
            "could": 0.4,
            "wont": 0.1,
        }

        base_score = base_scores.get(moscow, 0.4)

        # Boost must-haves with high urgency
        if moscow == "must" and candidate.urgency == UrgencyLevel.CRITICAL:
            base_score = 1.0

        return base_score


class ImprovementPrioritizer:
    """
    Shared prioritization framework for improvement candidates.

    Supports multiple algorithms, dependency-aware ranking,
    cost-benefit analysis, and generates actionable recommendations.
    """

    def __init__(
        self,
        config: Optional[PrioritizationConfig] = None,
        event_bus: Optional[EventBus] = None,
        observability: Optional[Any] = None,
    ):
        """
        Initialize the prioritizer.

        Args:
            config: Prioritization configuration
            event_bus: Optional event bus for events
            observability: Optional observability hub for metrics
        """
        self.config = config or PrioritizationConfig()
        self._event_bus = event_bus or get_event_bus()
        self._observability = observability or get_observability_hub()

        # Algorithms
        self._algorithms: Dict[PriorityAlgorithm, PrioritizationAlgorithm] = {
            PriorityAlgorithm.WEIGHTED_SCORE: WeightedScoreAlgorithm(),
            PriorityAlgorithm.RICE: RICEAlgorithm(),
            PriorityAlgorithm.WSJF: WSJFAlgorithm(),
            PriorityAlgorithm.KANO: KanoAlgorithm(),
            PriorityAlgorithm.MOSCOW: MoSCoWAlgorithm(),
        }

        # Candidates
        self._candidates: Dict[str, ImprovementCandidate] = {}
        self._candidates_lock = threading.RLock()

        # History
        self._history: List[PrioritizationResult] = []
        self._history_lock = threading.RLock()
        self._max_history = 100

        # Statistics
        self._stats = defaultdict(int)
        self._stats_lock = threading.Lock()

        logger.info("ImprovementPrioritizer initialized")

    def register_algorithm(self, algorithm: PrioritizationAlgorithm) -> None:
        """Register a custom prioritization algorithm."""
        self._algorithms[algorithm.name] = algorithm

    def add_candidate(self, candidate: ImprovementCandidate) -> ImprovementCandidate:
        """Add an improvement candidate."""
        with self._candidates_lock:
            # Calculate ROI if cost and benefit provided
            if candidate.estimated_cost > 0:
                candidate.roi = candidate.estimated_benefit / candidate.estimated_cost

            self._candidates[candidate.id] = candidate
            logger.debug(f"Added candidate: {candidate.id} - {candidate.title}")

        return candidate

    def add_candidates(self, candidates: List[ImprovementCandidate]) -> List[ImprovementCandidate]:
        """Add multiple candidates."""
        return [self.add_candidate(c) for c in candidates]

    def remove_candidate(self, candidate_id: str) -> bool:
        """Remove a candidate."""
        with self._candidates_lock:
            if candidate_id in self._candidates:
                del self._candidates[candidate_id]
                return True
        return False

    def get_candidate(self, candidate_id: str) -> Optional[ImprovementCandidate]:
        """Get a candidate by ID."""
        with self._candidates_lock:
            return self._candidates.get(candidate_id)

    def update_candidate(self, candidate_id: str, **kwargs) -> bool:
        """Update candidate attributes."""
        with self._candidates_lock:
            candidate = self._candidates.get(candidate_id)
            if not candidate:
                return False

            for key, value in kwargs.items():
                if hasattr(candidate, key):
                    setattr(candidate, key, value)

            # Recalculate ROI if cost/benefit changed
            if "estimated_cost" in kwargs or "estimated_benefit" in kwargs:
                if candidate.estimated_cost > 0:
                    candidate.roi = candidate.estimated_benefit / candidate.estimated_cost

            return True

    def prioritize(
        self,
        algorithm: Optional[PriorityAlgorithm] = None,
        candidates: Optional[List[ImprovementCandidate]] = None,
        filter_status: Optional[List[str]] = None,
    ) -> PrioritizationResult:
        """
        Run prioritization on candidates.

        Args:
            algorithm: Algorithm to use (default from config)
            candidates: Specific candidates to prioritize (default: all)
            filter_status: Filter by status

        Returns:
            PrioritizationResult with ranked candidates
        """
        algo = algorithm or self.config.default_algorithm
        algorithm_impl = self._algorithms.get(algo)

        if not algorithm_impl:
            raise ValueError(f"Algorithm {algo} not registered")

        with self._candidates_lock:
            candidate_list = candidates or list(self._candidates.values())

        if filter_status:
            candidate_list = [c for c in candidate_list if c.status in filter_status]

        # Calculate scores
        for candidate in candidate_list:
            candidate.priority_score = algorithm_impl.calculate_score(
                candidate, self.config, candidate_list
            )
            candidate.algorithm_used = algo

        # Sort by score (descending)
        candidate_list.sort(key=lambda c: c.priority_score, reverse=True)

        # Assign ranks
        for rank, candidate in enumerate(candidate_list, 1):
            candidate.rank = rank

            # Determine status based on thresholds
            if candidate.priority_score >= self.config.auto_approve_threshold:
                candidate.status = "approved"
            elif candidate.priority_score < self.config.require_review_threshold:
                candidate.status = "rejected"
            elif candidate.status == "proposed":
                candidate.status = "needs_review"

        # Build result
        result = PrioritizationResult(
            candidates=candidate_list,
            algorithm_used=algo,
            total_candidates=len(candidate_list),
            approved_count=sum(1 for c in candidate_list if c.status == "approved"),
            rejected_count=sum(1 for c in candidate_list if c.status == "rejected"),
            needs_review_count=sum(1 for c in candidate_list if c.status == "needs_review"),
        )

        # Calculate distributions
        result.score_distribution = self._calculate_score_distribution(candidate_list)
        result.category_distribution = self._calculate_category_distribution(candidate_list)

        # Record history
        with self._history_lock:
            self._history.append(result)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        # Update stats
        with self._stats_lock:
            self._stats[f"algorithm_{algo.value}"] += 1
            self._stats["total_runs"] += 1

        # Emit event
        self._event_bus.emit(
            "prioritization.completed",
            data={
                "algorithm": algo.value,
                "total": len(candidate_list),
                "approved": result.approved_count,
                "rejected": result.rejected_count,
            },
            source="ImprovementPrioritizer",
        )

        logger.info(
            f"Prioritization complete: {len(candidate_list)} candidates, "
            f"{result.approved_count} approved, {result.rejected_count} rejected, "
            f"{result.needs_review_count} need review (algorithm: {algo.value})"
        )

        return result

    def _calculate_score_distribution(self, candidates: List[ImprovementCandidate]) -> Dict[str, int]:
        """Calculate score distribution buckets."""
        buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for c in candidates:
            score = c.priority_score
            if score < 0.2:
                buckets["0.0-0.2"] += 1
            elif score < 0.4:
                buckets["0.2-0.4"] += 1
            elif score < 0.6:
                buckets["0.4-0.6"] += 1
            elif score < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1
        return buckets

    def _calculate_category_distribution(self, candidates: List[ImprovementCandidate]) -> Dict[str, int]:
        """Calculate category distribution."""
        dist = defaultdict(int)
        for c in candidates:
            dist[c.category or "uncategorized"] += 1
        return dict(dist)

    def get_top_candidates(
        self,
        n: int = 10,
        algorithm: Optional[PriorityAlgorithm] = None,
        status: Optional[str] = None,
    ) -> List[ImprovementCandidate]:
        """Get top N candidates."""
        result = self.prioritize(algorithm=algorithm)
        candidates = result.candidates

        if status:
            candidates = [c for c in candidates if c.status == status]

        return candidates[:n]

    def get_candidates_by_category(self, category: str) -> List[ImprovementCandidate]:
        """Get all candidates in a category."""
        with self._candidates_lock:
            return [c for c in self._candidates.values() if c.category == category]

    def get_blocked_candidates(self) -> List[ImprovementCandidate]:
        """Get candidates that are blocked by unresolved dependencies."""
        with self._candidates_lock:
            candidates = list(self._candidates.values())

        # Build dependency map
        done_ids = {c.id for c in candidates if c.status == "done"}

        blocked = []
        for c in candidates:
            if c.depends_on:
                unresolved = [d for d in c.depends_on if d not in done_ids]
                if unresolved:
                    c.metadata["blocked_by"] = unresolved
                    blocked.append(c)

        return blocked

    def get_unblockers(self) -> List[ImprovementCandidate]:
        """Get candidates that unblock the most other candidates."""
        with self._candidates_lock:
            candidates = list(self._candidates.values())

        # Count how many candidates each one unblocks
        unblock_counts = defaultdict(int)
        for c in candidates:
            for dep in c.depends_on:
                unblock_counts[dep] += 1

        # Sort candidates by unblock count
        candidates.sort(key=lambda c: unblock_counts.get(c.id, 0), reverse=True)
        return candidates

    def get_recommendations(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Generate actionable recommendations."""
        result = self.prioritize()
        recommendations = []

        # Top approved candidates
        approved = [c for c in result.candidates if c.status == "approved"]
        for c in approved[:limit]:
            recommendations.append({
                "type": "execute",
                "candidate_id": c.id,
                "title": c.title,
                "reason": f"High priority score: {c.priority_score:.2f}",
                "effort_hours": c.effort.hours_estimate,
                "impact": c.impact.value,
            })

        # Blocked candidates that could be unblocked
        blocked = self.get_blocked_candidates()
        for c in blocked[:3]:
            recommendations.append({
                "type": "unblock",
                "candidate_id": c.id,
                "title": c.title,
                "reason": f"Blocked by: {c.metadata.get('blocked_by', [])}",
                "action": "Resolve dependencies first",
            })

        # High ROI candidates
        with self._candidates_lock:
            high_roi = sorted(
                [c for c in self._candidates.values() if c.roi > 1.0],
                key=lambda c: c.roi,
                reverse=True,
            )
        for c in high_roi[:3]:
            if c.status != "approved":  # Don't duplicate
                recommendations.append({
                    "type": "high_roi",
                    "candidate_id": c.id,
                    "title": c.title,
                    "reason": f"High ROI: {c.roi:.1f}x",
                    "cost": c.estimated_cost,
                    "benefit": c.estimated_benefit,
                })

        return recommendations[:limit]

    def compare_algorithms(self, candidate_ids: List[str]) -> Dict[str, Dict[str, float]]:
        """Compare how different algorithms rank specific candidates."""
        with self._candidates_lock:
            candidates = [self._candidates[cid] for cid in candidate_ids if cid in self._candidates]

        if not candidates:
            return {}

        comparison = {}
        for algo_name, algo_impl in self._algorithms.items():
            scores = {}
            for c in candidates:
                score = algo_impl.calculate_score(c, self.config, candidates)
                scores[c.id] = round(score, 3)
            comparison[algo_name.value] = scores

        return comparison

    def get_history(self, limit: int = 10) -> List[PrioritizationResult]:
        """Get prioritization history."""
        with self._history_lock:
            history = list(self._history)
            history.sort(key=lambda r: r.ranked_at, reverse=True)
            return history[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get prioritization statistics."""
        with self._candidates_lock:
            by_status = defaultdict(int)
            by_category = defaultdict(int)
            by_impact = defaultdict(int)
            total_roi = 0.0
            roi_count = 0

            for c in self._candidates.values():
                by_status[c.status] += 1
                by_category[c.category or "uncategorized"] += 1
                by_impact[c.impact.value] += 1
                if c.roi > 0:
                    total_roi += c.roi
                    roi_count += 1

        with self._stats_lock:
            stats = dict(self._stats)

        stats.update({
            "total_candidates": len(self._candidates),
            "by_status": dict(by_status),
            "by_category": dict(by_category),
            "by_impact": dict(by_impact),
            "avg_roi": total_roi / roi_count if roi_count > 0 else 0,
            "algorithms_registered": list(self._algorithms.keys()),
        })

        return stats

    def export_candidates(self) -> List[Dict[str, Any]]:
        """Export all candidates."""
        with self._candidates_lock:
            return [c.to_dict() for c in self._candidates.values()]

    def import_candidates(self, data: List[Dict[str, Any]]) -> int:
        """Import candidates from data."""
        count = 0
        for item in data:
            candidate = ImprovementCandidate(**item)
            self.add_candidate(candidate)
            count += 1
        return count


# === Utility functions ===

def create_candidate(
    title: str,
    description: str = "",
    impact: ImpactLevel = ImpactLevel.MEDIUM,
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM,
    effort: EffortLevel = EffortLevel.MEDIUM,
    confidence: float = 0.8,
    category: str = "",
    improvement_type: str = "",
    estimated_cost: float = 0.0,
    estimated_benefit: float = 0.0,
    risk_score: float = 0.0,
    depends_on: Optional[List[str]] = None,
    **metadata,
) -> ImprovementCandidate:
    """Factory function to create an improvement candidate."""
    candidate = ImprovementCandidate(
        title=title,
        description=description,
        impact=impact,
        urgency=urgency,
        effort=effort,
        confidence=confidence,
        category=category,
        improvement_type=improvement_type,
        estimated_cost=estimated_cost,
        estimated_benefit=estimated_benefit,
        risk_score=risk_score,
        depends_on=depends_on or [],
        metadata=metadata,
    )

    if candidate.estimated_cost > 0:
        candidate.roi = candidate.estimated_benefit / candidate.estimated_cost

    return candidate


def calculate_cost_benefit(
    cost: float,
    benefit: float,
    time_horizon_months: int = 12,
    discount_rate: float = 0.1,
) -> Dict[str, float]:
    """Calculate cost-benefit metrics including NPV and payback period."""
    if cost <= 0:
        return {"error": "Cost must be positive"}

    roi = benefit / cost
    npv = benefit / (1 + discount_rate) ** (time_horizon_months / 12) - cost
    payback_years = cost / (benefit / time_horizon_months * 12) if benefit > 0 else float('inf')
    irr = (benefit / cost) ** (12 / time_horizon_months) - 1 if benefit > cost else -1

    return {
        "roi": roi,
        "npv": npv,
        "payback_period_months": min(payback_years * 12, time_horizon_months),
        "irr": irr,
        "profitable": npv > 0,
    }


# === Global instance ===

_default_prioritizer: Optional[ImprovementPrioritizer] = None
_prioritizer_lock = threading.Lock()


def get_prioritizer(config: Optional[PrioritizationConfig] = None) -> ImprovementPrioritizer:
    """Get or create the global improvement prioritizer."""
    global _default_prioritizer
    with _prioritizer_lock:
        if _default_prioritizer is None:
            _default_prioritizer = ImprovementPrioritizer(config)
        return _default_prioritizer


def set_prioritizer(prioritizer: ImprovementPrioritizer) -> None:
    """Set the global improvement prioritizer."""
    global _default_prioritizer
    with _prioritizer_lock:
        _default_prioritizer = prioritizer