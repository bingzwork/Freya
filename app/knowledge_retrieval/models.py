"""Data models for Knowledge Retrieval.

Defines the structured knowledge retrieval result format, ranking signals,
confidence calibration, and usage analytics data structures.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class KnowledgeSourceType(Enum):
    """Supported knowledge source types for retrieval."""
    SEMANTIC_MEMORY = "semantic_memory"
    EPISODIC_MEMORY = "episodic_memory"
    PROJECT_MEMORY = "project_memory"
    WORKING_MEMORY = "working_memory"
    CONVERSATION_MEMORY = "conversation_memory"
    LONG_TERM_MEMORY = "long_term_memory"
    EXPERIENCE_MEMORY = "experience_memory"
    ENGINEERING_LESSONS = "engineering_lessons"
    KNOWLEDGE_BASE = "knowledge_base"
    EXTRACTED_KNOWLEDGE = "extracted_knowledge"
    DOCUMENTATION = "documentation"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    USER_KNOWLEDGE = "user_knowledge"
    UNKNOWN = "unknown"


class RetrievalDecision(Enum):
    """Decision about retrieved knowledge sufficiency."""
    USE_DIRECTLY = "use_directly"        # High confidence, use as-is
    USE_WITH_CAUTION = "use_with_caution"  # Medium confidence, add context
    ACQUIRE_MORE = "acquire_more"        # Low confidence, trigger acquisition
    ASK_USER = "ask_user"                # Ambiguous, need clarification
    NO_KNOWLEDGE = "no_knowledge"        # Nothing found


class RankingSignal(Enum):
    """Individual ranking signals that contribute to final score."""
    RELEVANCE = "relevance"              # Semantic/keyword match to query
    CONFIDENCE = "confidence"            # Stored confidence of the knowledge
    SOURCE_QUALITY = "source_quality"    # Trustworthiness of source
    USAGE_FREQUENCY = "usage_frequency"  # How often this knowledge is accessed
    RECENCY = "recency"                  # How recently knowledge was updated
    COMPLETENESS = "completeness"        # How complete/comprehensive the knowledge is
    RELIABILITY = "reliability"          # Historical accuracy of this source
    FRESHNESS = "freshness"              # How fresh/up-to-date the knowledge is
    HISTORICAL_USEFULNESS = "historical_usefulness"  # Past utility in solving problems


@dataclass
class RankingFactor:
    """A single ranking factor with its weight and computed value."""
    signal: RankingSignal
    value: float  # 0.0 to 1.0
    weight: float  # Configurable weight
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def weighted_value(self) -> float:
        """Get the weighted contribution to final score."""
        return self.value * self.weight


@dataclass
class RankingExplanation:
    """Detailed explanation of how a ranking score was computed."""
    factors: List[RankingFactor]
    total_score: float
    query: str
    source_type: KnowledgeSourceType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factors": [
                {
                    "signal": f.signal.value,
                    "value": f.value,
                    "weight": f.weight,
                    "weighted_value": f.weighted_value,
                    "metadata": f.metadata,
                }
                for f in self.factors
            ],
            "total_score": self.total_score,
            "query": self.query,
            "source_type": self.source_type.value,
        }

    def explain_simple(self) -> str:
        """Generate a human-readable explanation."""
        lines = [f"Total score: {self.total_score:.3f}"]
        for f in sorted(self.factors, key=lambda x: x.weighted_value, reverse=True):
            lines.append(f"  {f.signal.value}: {f.value:.2f} x {f.weight:.2f} = {f.weighted_value:.3f}")
        return "\n".join(lines)


@dataclass
class KnowledgeRetrievalResult:
    """A single result from knowledge retrieval with full ranking info."""
    # Core content
    content: str
    title: str = ""
    summary: str = ""

    # Source information
    source_type: KnowledgeSourceType = KnowledgeSourceType.UNKNOWN
    source_id: str = ""         # Unique ID within the source
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    # Ranking information
    rank_score: float = 0.0            # Final combined ranking score (0-1)
    ranking_explanation: Optional[RankingExplanation] = None

    # Confidence information
    raw_confidence: float = 0.5        # Original confidence from source
    calibrated_confidence: float = 0.5  # Calibrated confidence (after calibration)
    calibration_metadata: Dict[str, Any] = field(default_factory=dict)

    # Knowledge metadata
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    language: Optional[str] = None
    related_concepts: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    access_count: int = 0

    # Retrieval metadata
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retrieval_id: str = field(default_factory=lambda: f"retr_{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        if self.ranking_explanation:
            data["ranking_explanation"] = self.ranking_explanation.to_dict()
        return data


@dataclass
class RetrievalQuery:
    """Query for knowledge retrieval."""
    query: str
    context: Optional[Dict[str, Any]] = None
    max_results: int = 10
    min_score: float = 0.1
    sources: Optional[List[KnowledgeSourceType]] = None
    boost_recent: bool = True
    boost_category: Optional[str] = None
    boost_language: Optional[str] = None
    require_calibration: bool = True

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.sources:
            data["sources"] = [s.value for s in self.sources]
        return data


@dataclass
class RetrievalResponse:
    """Response from knowledge retrieval pipeline."""
    results: List[KnowledgeRetrievalResult]
    decision: RetrievalDecision
    decision_reason: str
    query: RetrievalQuery
    total_candidates: int
    retrieval_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "decision": self.decision.value,
            "decision_reason": self.decision_reason,
            "query": self.query.to_dict(),
            "total_candidates": self.total_candidates,
            "retrieval_time": self.retrieval_time,
            "metadata": self.metadata,
        }


@dataclass
class UsageEvent:
    """Record of a knowledge retrieval usage event."""
    event_id: str = field(default_factory=lambda: f"usage_{uuid.uuid4().hex[:8]}")
    retrieval_id: str = ""
    query: str = ""
    result_id: str = ""
    source_type: KnowledgeSourceType = KnowledgeSourceType.UNKNOWN
    action: str = ""  # "retrieved", "selected", "ignored", "feedback_positive", "feedback_negative"
    rank_position: int = 0
    rank_score: float = 0.0
    task_success: Optional[bool] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        return data


@dataclass
class RankingConfig:
    """Configuration for the unified ranking engine."""
    # Base weights for each ranking signal (sum should be 1.0 ideally)
    weights: Dict[RankingSignal, float] = field(default_factory=lambda: {
        RankingSignal.RELEVANCE: 0.30,
        RankingSignal.CONFIDENCE: 0.20,
        RankingSignal.SOURCE_QUALITY: 0.15,
        RankingSignal.USAGE_FREQUENCY: 0.10,
        RankingSignal.RECENCY: 0.10,
        RankingSignal.COMPLETENESS: 0.05,
        RankingSignal.RELIABILITY: 0.05,
        RankingSignal.FRESHNESS: 0.03,
        RankingSignal.HISTORICAL_USEFULNESS: 0.02,
    })

    # Source quality scores (0-1, higher = more trustworthy)
    source_quality_scores: Dict[KnowledgeSourceType, float] = field(default_factory=lambda: {
        KnowledgeSourceType.KNOWLEDGE_BASE: 0.95,
        KnowledgeSourceType.SEMANTIC_MEMORY: 0.90,
        KnowledgeSourceType.ENGINEERING_LESSONS: 0.85,
        KnowledgeSourceType.EXTRACTED_KNOWLEDGE: 0.80,
        KnowledgeSourceType.DOCUMENTATION: 0.85,
        KnowledgeSourceType.USER_KNOWLEDGE: 0.90,
        KnowledgeSourceType.EXPERIENCE_MEMORY: 0.75,
        KnowledgeSourceType.PROJECT_MEMORY: 0.80,
        KnowledgeSourceType.LONG_TERM_MEMORY: 0.85,
        KnowledgeSourceType.EPISODIC_MEMORY: 0.70,
        KnowledgeSourceType.CONVERSATION_MEMORY: 0.65,
        KnowledgeSourceType.WORKING_MEMORY: 0.75,
        KnowledgeSourceType.EXTERNAL_KNOWLEDGE: 0.60,
        KnowledgeSourceType.UNKNOWN: 0.50,
    })

    # Confidence calibration parameters
    calibration_enabled: bool = True
    calibration_method: str = "isotonic"  # "isotonic", "platt", "none"
    min_confidence_threshold: float = 0.70
    high_confidence_threshold: float = 0.90

    # Analytics config
    analytics_enabled: bool = True
    adaptation_enabled: bool = True
    adaptation_rate: float = 0.01  # How fast weights adapt

    # Decision thresholds
    use_directly_threshold: float = 0.90
    use_with_caution_threshold: float = 0.70
    no_knowledge_threshold: float = 0.10


@dataclass
class RetrievalStats:
    """Statistics about retrieval performance."""
    total_queries: int = 0
    successful_retrievals: int = 0
    failed_retrievals: int = 0
    avg_results_per_query: float = 0.0
    avg_retrieval_time: float = 0.0
    source_distribution: Dict[str, int] = field(default_factory=dict)
    decision_distribution: Dict[str, int] = field(default_factory=dict)
    calibration_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)