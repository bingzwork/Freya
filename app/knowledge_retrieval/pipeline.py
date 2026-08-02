"""Knowledge Retrieval Pipeline.

This module provides the main retrieval pipeline that:
1. Queries all available knowledge sources
2. Applies confidence calibration
3. Ranks results using the unified ranking engine
4. Tracks usage analytics
5. Makes retrieval decisions
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalDecision,
    KnowledgeSourceType,
    RankingConfig,
)
from app.knowledge_retrieval.ranking import RankingEngine, AdaptiveRankingEngine, create_ranking_engine
from app.knowledge_retrieval.calibration import CalibrationManager, NoOpCalibrator
from app.knowledge_retrieval.analytics import UsageAnalytics
from app.knowledge_retrieval.sources import (
    KnowledgeSourceAdapter,
    create_adapters_from_agent,
)

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Statistics for the retrieval pipeline."""
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    avg_results_per_query: float = 0.0
    avg_retrieval_time: float = 0.0
    decision_distribution: Dict[str, int] = field(default_factory=dict)
    source_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "successful_queries": self.successful_queries,
            "failed_queries": self.failed_queries,
            "avg_results_per_query": self.avg_results_per_query,
            "avg_retrieval_time": self.avg_retrieval_time,
            "decision_distribution": self.decision_distribution,
            "source_distribution": self.source_distribution,
        }


class KnowledgeRetrievalPipeline:
    """Main knowledge retrieval pipeline.

    Orchestrates retrieval from multiple sources, calibration, ranking,
    analytics, and decision making.
    """

    def __init__(
        self,
        config: Optional[RankingConfig] = None,
        calibration_method: str = "isotonic",
        calibration_storage: Optional[Path] = None,
        analytics_storage: Optional[Path] = None,
        adaptive_ranking: bool = True,
        analytics_enabled: bool = True,
        # Shared infrastructure
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize the pipeline."""
        self.config = config or RankingConfig()
        self.config.adaptation_enabled = adaptive_ranking
        self.config.analytics_enabled = analytics_enabled

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        # Initialize components
        self.calibration = CalibrationManager(
            method=calibration_method,
            storage_path=calibration_storage,
        )

        self.ranking_engine = create_ranking_engine(self.config, adaptive=adaptive_ranking)

        self.analytics = UsageAnalytics(
            storage_path=analytics_storage,
        ) if analytics_enabled else None

        # Registered adapters
        self._adapters: List[KnowledgeSourceAdapter] = []
        self._adapter_map: Dict[KnowledgeSourceType, KnowledgeSourceAdapter] = {}

        # Statistics
        self._stats = PipelineStats()

        # Register with observability
        self._register_with_observability()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="knowledge_retrieval_pipeline_health",
                component="knowledge_retrieval",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self.observability.register_component(ComponentInfo(
                name="KnowledgeRetrievalPipeline",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Knowledge retrieval, calibration, and ranking pipeline",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for KnowledgeRetrievalPipeline."""
        try:
            success_rate = self._stats.successful_queries / max(1, self._stats.total_queries)
            return HealthResult(
                name="knowledge_retrieval_pipeline_health",
                component="knowledge_retrieval",
                status=HealthStatus.HEALTHY,
                message="KnowledgeRetrievalPipeline operational",
                metadata={
                    "total_queries": self._stats.total_queries,
                    "success_rate": success_rate,
                    "avg_retrieval_time": self._stats.avg_retrieval_time,
                    "registered_adapters": len(self._adapters),
                }
            )
        except Exception as e:
            return HealthResult(
                name="knowledge_retrieval_pipeline_health",
                component="knowledge_retrieval",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the shared EventBus."""
        try:
            self.event_bus.emit(event_type, data)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def register_adapter(self, adapter: KnowledgeSourceAdapter) -> None:
        """Register a knowledge source adapter."""
        self._adapters.append(adapter)
        self._adapter_map[adapter.source_type] = adapter
        logger.info(f"Registered knowledge source adapter: {adapter.source_type.value}")

    def register_adapters(self, adapters: List[KnowledgeSourceAdapter]) -> None:
        """Register multiple adapters."""
        for adapter in adapters:
            self.register_adapter(adapter)

    def retrieve(
        self,
        query: Union[str, RetrievalQuery],
    ) -> RetrievalResponse:
        """Main retrieval entry point.

        Args:
            query: Query string or RetrievalQuery object

        Returns:
            RetrievalResponse with ranked results and decision
        """
        start_time = time.time()

        # Normalize query
        if isinstance(query, str):
            query = RetrievalQuery(query=query)

        # Get candidate results from all available sources
        all_candidates = self._retrieve_candidates(query)

        if not all_candidates:
            return self._empty_response(query, start_time, "No knowledge found")

        # Apply confidence calibration
        if query.require_calibration:
            self._calibrate_results(all_candidates)

        # Rank results
        ranked_results = self.ranking_engine.rank(all_candidates, query, self.analytics)

        # Apply limits
        max_results = query.max_results or 10
        min_score = query.min_score if query.min_score is not None else 0.1
        ranked_results = [r for r in ranked_results if r.rank_score >= min_score][:max_results]

        # Make retrieval decision
        decision, decision_reason = self._make_decision(ranked_results)

        # Record analytics
        retrieval_time = time.time() - start_time
        self._record_retrieval_analytics(query, ranked_results, retrieval_time, decision)

        # Update stats
        self._update_stats(query, ranked_results, retrieval_time, decision)

        # Publish retrieval event
        self._publish_event("knowledge.retrieved", {
            "query": query.query,
            "total_candidates": len(all_candidates),
            "results_returned": len(ranked_results),
            "decision": decision.value,
            "retrieval_time": retrieval_time,
            "top_score": ranked_results[0].rank_score if ranked_results else 0,
        })

        return RetrievalResponse(
            results=ranked_results,
            decision=decision,
            decision_reason=decision_reason,
            query=query,
            total_candidates=len(all_candidates),
            retrieval_time=retrieval_time,
        )

    def _retrieve_candidates(self, query: RetrievalQuery) -> List[KnowledgeRetrievalResult]:
        """Retrieve candidates from all registered adapters."""
        all_candidates = []

        # Determine which sources to query
        target_sources = query.sources
        if not target_sources:
            target_sources = [a.source_type for a in self._adapters if a.is_available()]

        for adapter in self._adapters:
            if adapter.source_type not in target_sources:
                continue

            if not adapter.is_available():
                logger.debug(f"Adapter {adapter.source_type.value} not available")
                continue

            try:
                candidates = adapter.retrieve_candidates(
                    query,
                    max_results=query.max_results * 3,  # Get more for better ranking
                )
                all_candidates.extend(candidates)
                logger.debug(f"Retrieved {len(candidates)} candidates from {adapter.source_type.value}")
            except Exception as e:
                logger.warning(f"Adapter {adapter.source_type.value} failed: {e}")
                continue

        return all_candidates

    def _calibrate_results(self, results: List[KnowledgeRetrievalResult]) -> None:
        """Apply confidence calibration to results."""
        for result in results:
            calibrated = self.calibration.calibrate(
                result.raw_confidence,
                result.source_type.value,
            )
            result.calibrated_confidence = calibrated
            result.calibration_metadata = self.calibration.get_calibration_metadata(
                result.raw_confidence,
                result.source_type.value,
            )

    def _make_decision(
        self,
        results: List[KnowledgeRetrievalResult],
    ) -> Tuple[RetrievalDecision, str]:
        """Make retrieval decision based on top results."""
        if not results:
            return RetrievalDecision.NO_KNOWLEDGE, "No results found"

        top_result = results[0]
        top_score = top_result.calibrated_confidence

        # Check highest rank score as well
        rank_score = top_result.rank_score
        combined_score = (top_score + rank_score) / 2

        # Decision thresholds from config
        high_thresh = self.config.high_confidence_threshold
        min_thresh = self.config.min_confidence_threshold
        no_knowledge_thresh = self.config.no_knowledge_threshold

        if combined_score >= high_thresh:
            return RetrievalDecision.USE_DIRECTLY, f"High confidence ({combined_score:.2f}), using directly"

        if combined_score >= min_thresh:
            return RetrievalDecision.USE_WITH_CAUTION, f"Medium confidence ({combined_score:.2f}), use with caution"

        if combined_score <= no_knowledge_thresh:
            return RetrievalDecision.ACQUIRE_MORE, f"Low confidence ({combined_score:.2f}), acquiring more knowledge"

        return RetrievalDecision.ASK_USER, f"Ambiguous confidence ({combined_score:.2f}), need clarification"

    def _record_retrieval_analytics(
        self,
        query: RetrievalQuery,
        results: List[KnowledgeRetrievalResult],
        retrieval_time: float,
        decision: RetrievalDecision,
    ) -> None:
        """Record retrieval for analytics."""
        if not self.analytics:
            return

        try:
            # Prepare simplified results for session recording
            session_results = []
            for i, r in enumerate(results):
                session_results.append({
                    "result_id": r.retrieval_id,
                    "source_type": r.source_type.value,
                    "rank_position": i + 1,
                    "rank_score": r.rank_score,
                    "calibrated_confidence": r.calibrated_confidence,
                    "category": r.category,
                })

            self.analytics.record_retrieval(
                query=query.query,
                results=session_results,
                context=query.context,
                duration=retrieval_time,
            )
        except Exception as e:
            logger.warning(f"Failed to record analytics: {e}")

    def _update_stats(
        self,
        query: RetrievalQuery,
        results: List[KnowledgeRetrievalResult],
        retrieval_time: float,
        decision: RetrievalDecision,
    ) -> None:
        """Update pipeline statistics."""
        self._stats.total_queries += 1

        if results:
            self._stats.successful_queries += 1
        else:
            self._stats.failed_queries += 1

        # Update running averages
        n = self._stats.total_queries
        self._stats.avg_retrieval_time = (
            (self._stats.avg_retrieval_time * (n - 1) + retrieval_time) / n
        )
        self._stats.avg_results_per_query = (
            (self._stats.avg_results_per_query * (n - 1) + len(results)) / n
        )

        # Decision distribution
        self._stats.decision_distribution[decision.value] = \
            self._stats.decision_distribution.get(decision.value, 0) + 1

        # Source distribution
        for r in results[:5]:  # Top 5
            src = r.source_type.value
            self._stats.source_distribution[src] = \
                self._stats.source_distribution.get(src, 0) + 1

    def _empty_response(
        self,
        query: RetrievalQuery,
        start_time: float,
        reason: str,
    ) -> RetrievalResponse:
        """Create empty response when no candidates found."""
        self._stats.total_queries += 1
        self._stats.failed_queries += 1
        return RetrievalResponse(
            results=[],
            decision=RetrievalDecision.NO_KNOWLEDGE,
            decision_reason=reason,
            query=query,
            total_candidates=0,
            retrieval_time=time.time() - start_time,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        stats = self._stats.to_dict()
        if self.analytics:
            stats["analytics"] = self.analytics.get_summary()
        return stats

    def record_selection(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        rank_position: int,
        rank_score: float,
        query: str = "",
    ) -> None:
        """Record that a result was selected."""
        if self.analytics:
            self.analytics.record_selection(result_id, source_type, rank_position, rank_score, query)

        # Also provide feedback to adaptive ranking
        if hasattr(self.ranking_engine, 'record_feedback'):
            # We'd need the original result, so store reference
            pass

    def record_feedback(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        positive: bool,
        query: str = "",
    ) -> None:
        """Record user feedback on a result."""
        if self.analytics:
            self.analytics.record_feedback(result_id, source_type, positive, query)

        # Update calibration
        # We need the original calibrated confidence - would need to track it
        pass

    def record_task_outcome(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        success: bool,
    ) -> None:
        """Record task success/failure for a used result."""
        if self.analytics:
            self.analytics.record_task_outcome(result_id, source_type, success)

    def save_state(self) -> None:
        """Persist calibration and analytics."""
        self.calibration.save()
        if self.analytics:
            self.analytics.save()

    def schedule_state_persistence(self, interval_seconds: int = 300) -> str:
        """Schedule periodic state persistence using shared BackgroundJobService.

        Args:
            interval_seconds: Interval between saves (default 5 minutes)

        Returns:
            Job ID of the scheduled persistence job
        """
        job_id = "knowledge_retrieval_persist_state"
        self.job_service.schedule(
            job_id=job_id,
            func=self.save_state,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=interval_seconds),
            priority=JobPriority.LOW,
            max_retries=3,
            replace_existing=True,
        )
        logger.info(f"Scheduled knowledge retrieval state persistence (interval: {interval_seconds}s)")
        return job_id

    def get_available_sources(self) -> List[str]:
        """Get list of available source names."""
        return [a.source_type.value for a in self._adapters if a.is_available()]


class RetrievalContext:
    """Context manager for retrieval sessions with automatic cleanup."""

    def __init__(self, pipeline: KnowledgeRetrievalPipeline):
        self.pipeline = pipeline

    def __enter__(self):
        return self.pipeline

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.pipeline.save_state()


def create_pipeline_from_agent(
    agent,
    config: Optional[RankingConfig] = None,
    **kwargs,
) -> KnowledgeRetrievalPipeline:
    """Create a pipeline populated from a Freya agent."""
    pipeline = KnowledgeRetrievalPipeline(config, **kwargs)

    # Create and register adapters from agent
    adapters = create_adapters_from_agent(agent)
    pipeline.register_adapters(adapters)

    return pipeline


# Alias for backward compatibility
KnowledgeRetriever = KnowledgeRetrievalPipeline