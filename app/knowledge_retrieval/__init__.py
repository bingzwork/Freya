"""Experimental retrieval research components for Freya AI.

Production retrieval is exclusively provided by ``app.memory.unified_retrieval``
through ``MemoryCoordinator``. This package is intentionally quarantined from
normal application routing: its calibration, adaptive ranking, analytics, and
retrieval-decision experiments are not production-supported until they can be
integrated behind that canonical contract.

This module provides a unified knowledge retrieval system that:
- Queries multiple knowledge sources (semantic memory, episodic memory, project memory, etc.)
- Calibrates confidence scores for better decision making
- Ranks results using a configurable multi-signal ranking engine
- Tracks usage analytics for continuous improvement
- Makes retrieval decisions (use, acquire more, ask user)

Core Components:
- KnowledgeRetrievalPipeline: Main orchestration class
- RankingEngine: Unified ranking with multiple signals
- CalibrationManager: Statistical confidence calibration
- UsageAnalytics: Real-time usage tracking and adaptation
- KnowledgeSourceAdapter: Interface for knowledge sources

Usage:
    from app.knowledge_retrieval import pipeline, RetrievalQuery
    from app.knowledge_retrieval.sources import create_adapters_from_agent

    # Create pipeline with adapters from agent
    retrieval_pipeline = create_pipeline_from_agent(agent)

    # Query
    query = RetrievalQuery(query="How to implement singleton pattern?")
    response = pipeline.retrieve(query)

    # Get top result
    if response.results:
        best = response.results[0]
        print(f"Score: {best.rank_score}, Confidence: {best.calibrated_confidence}")
        print(best.content)
"""

from typing import Optional, Union

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalDecision,
    KnowledgeSourceType,
    RankingSignal,
    RankingFactor,
    RankingExplanation,
    RankingConfig,
    UsageEvent,
    RetrievalStats,
)

from app.knowledge_retrieval.ranking import (
    RankingEngine,
    AdaptiveRankingEngine,
    create_ranking_engine,
)

from app.knowledge_retrieval.calibration import (
    CalibrationManager,
    CalibrationMethod,
    NoOpCalibrator,
)

from app.knowledge_retrieval.analytics import (
    UsageAnalytics,
    ResultUsageStats,
    SourceUsageStats,
)

from app.knowledge_retrieval.sources import (
    KnowledgeSourceAdapter,
    SemanticMemoryAdapter,
    EpisodicMemoryAdapter,
    ProjectMemoryAdapter,
    WorkingMemoryAdapter,
    LongTermMemoryAdapter,
    ExperienceMemoryAdapter,
    EngineeringLessonsAdapter,
    ExtractedKnowledgeAdapter,
    DocumentationAdapter,
    VectorSearchAdapter,
    ConversationMemoryAdapter,
    create_adapters_from_agent,
)

from app.knowledge_retrieval.pipeline import (
    KnowledgeRetrievalPipeline,
    PipelineStats,
    RetrievalContext,
    create_pipeline_from_agent,
    KnowledgeRetriever,
)

# Explicitly non-production: retained only for isolated research and legacy
# knowledge-acquisition callers. Normal application retrieval must use
# app.memory.unified_retrieval.UnifiedRetrieval.
EXPERIMENTAL_ONLY = True

# Global default pipeline (lazy initialization)
_default_pipeline: Optional[KnowledgeRetrievalPipeline] = None


def get_default_pipeline() -> KnowledgeRetrievalPipeline:
    """Get or create the default pipeline."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = KnowledgeRetrievalPipeline()
    return _default_pipeline


def retrieve_knowledge(
    query: Union[str, RetrievalQuery],
    pipeline: Optional[KnowledgeRetrievalPipeline] = None,
) -> RetrievalResponse:
    """Convenience function for quick retrieval."""
    p = pipeline or get_default_pipeline()
    return p.retrieve(query)


def register_knowledge_source(adapter: KnowledgeSourceAdapter) -> None:
    """Register a knowledge source with the default pipeline."""
    get_default_pipeline().register_adapter(adapter)


__all__ = [
    # Quarantine marker
    "EXPERIMENTAL_ONLY",

    # Models
    "KnowledgeRetrievalResult",
    "RetrievalQuery",
    "RetrievalResponse",
    "RetrievalDecision",
    "KnowledgeSourceType",
    "RankingSignal",
    "RankingFactor",
    "RankingExplanation",
    "RankingConfig",
    "UsageEvent",
    "RetrievalStats",

    # Ranking
    "RankingEngine",
    "AdaptiveRankingEngine",
    "create_ranking_engine",

    # Calibration
    "CalibrationManager",
    "CalibrationMethod",
    "NoOpCalibrator",

    # Analytics
    "UsageAnalytics",
    "ResultUsageStats",
    "SourceUsageStats",

    # Sources
    "KnowledgeSourceAdapter",
    "SemanticMemoryAdapter",
    "EpisodicMemoryAdapter",
    "ProjectMemoryAdapter",
    "WorkingMemoryAdapter",
    "LongTermMemoryAdapter",
    "ExperienceMemoryAdapter",
    "EngineeringLessonsAdapter",
    "ExtractedKnowledgeAdapter",
    "DocumentationAdapter",
    "VectorSearchAdapter",
    "ConversationMemoryAdapter",
    "create_adapters_from_agent",

    # Pipeline
    "KnowledgeRetrievalPipeline",
    "PipelineStats",
    "RetrievalContext",
    "create_pipeline_from_agent",
    "KnowledgeRetriever",

    # Convenience
    "get_default_pipeline",
    "retrieve_knowledge",
    "register_knowledge_source",
]