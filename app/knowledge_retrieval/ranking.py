"""Unified Ranking Engine for Knowledge Retrieval.

This module provides the core ranking logic that combines multiple signals
into a single relevance score for knowledge retrieval results.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Tuple
from collections import defaultdict

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    KnowledgeSourceType,
    RankingSignal,
    RankingFactor,
    RankingExplanation,
    RankingConfig,
)

logger = logging.getLogger(__name__)


class RankingEngine:
    """Unified ranking engine that combines multiple signals into a single score.

    The engine is designed to be:
    - Configurable: weights and source quality scores can be adjusted
    - Extensible: new signals can be added via plugin functions
    - Transparent: provides detailed explanations for each ranking decision
    """

    def __init__(self, config: Optional[RankingConfig] = None):
        """Initialize the ranking engine with configuration."""
        self.config = config or RankingConfig()
        self._signal_calculators: Dict[RankingSignal, Callable] = {}
        self._register_default_calculators()

    def _register_default_calculators(self) -> None:
        """Register default signal calculation functions."""
        self._signal_calculators = {
            RankingSignal.RELEVANCE: self._calculate_relevance,
            RankingSignal.CONFIDENCE: self._calculate_confidence,
            RankingSignal.SOURCE_QUALITY: self._calculate_source_quality,
            RankingSignal.USAGE_FREQUENCY: self._calculate_usage_frequency,
            RankingSignal.RECENCY: self._calculate_recency,
            RankingSignal.COMPLETENESS: self._calculate_completeness,
            RankingSignal.RELIABILITY: self._calculate_reliability,
            RankingSignal.FRESHNESS: self._calculate_freshness,
            RankingSignal.HISTORICAL_USEFULNESS: self._calculate_historical_usefulness,
        }

    def register_calculator(self, signal: RankingSignal, calculator: Callable) -> None:
        """Register a custom signal calculator."""
        self._signal_calculators[signal] = calculator

    def rank(
        self,
        results: List[KnowledgeRetrievalResult],
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> List[KnowledgeRetrievalResult]:
        """Rank a list of results for a query.

        Args:
            results: List of retrieval results to rank
            query: The original retrieval query
            analytics: Optional analytics instance for historical data

        Returns:
            Results sorted by rank_score (descending)
        """
        if not results:
            return []

        # Calculate rank score for each result
        for result in results:
            explanation = self._compute_rank_score(result, query, analytics)
            result.rank_score = explanation.total_score
            result.ranking_explanation = explanation

        # Sort by score descending
        results.sort(key=lambda r: r.rank_score, reverse=True)

        return results

    def _compute_rank_score(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> RankingExplanation:
        """Compute the composite rank score for a single result."""
        factors = []
        total_score = 0.0

        for signal, weight in self.config.weights.items():
            if weight <= 0:
                continue

            calculator = self._signal_calculators.get(signal)
            if calculator:
                try:
                    value, metadata = calculator(result, query, analytics)
                except Exception as e:
                    logger.warning(f"Signal {signal.value} calculation failed: {e}")
                    value, metadata = 0.0, {"error": str(e)}
            else:
                value, metadata = 0.0, {"error": "no_calculator"}

            # Clamp value to [0, 1]
            value = max(0.0, min(1.0, value))

            factor = RankingFactor(
                signal=signal,
                value=value,
                weight=weight,
                metadata=metadata,
            )
            factors.append(factor)
            total_score += factor.weighted_value

        # Normalize by total weight (in case weights don't sum to 1)
        total_weight = sum(self.config.weights.values())
        if total_weight > 0:
            total_score /= total_weight

        return RankingExplanation(
            factors=factors,
            total_score=total_score,
            query=query.query,
            source_type=result.source_type,
        )

    # --- Signal Calculators ---

    def _calculate_relevance(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate relevance score based on text matching."""
        query_lower = query.query.lower()

        # Build searchable text from result
        searchable = " ".join([
            result.title.lower(),
            result.summary.lower(),
            result.content.lower(),
            " ".join(result.tags).lower(),
        ])

        # Simple keyword overlap scoring
        query_terms = set(query_lower.split())
        searchable_terms = set(searchable.split())

        if not query_terms:
            return 0.5, {"method": "empty_query"}

        # Jaccard similarity
        intersection = query_terms & searchable_terms
        union = query_terms | searchable_terms

        if not union:
            return 0.0, {"method": "jaccard", "intersection": 0, "union": 0}

        jaccard = len(intersection) / len(union)

        # Also check for phrase matches
        phrase_bonus = 0.0
        if query_lower in searchable:
            phrase_bonus = 0.3

        score = min(jaccard + phrase_bonus, 1.0)

        return score, {
            "method": "jaccard+phrase",
            "jaccard": jaccard,
            "phrase_match": phrase_bonus > 0,
            "matched_terms": len(intersection),
            "query_terms": len(query_terms),
        }

    def _calculate_confidence(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Use the calibrated confidence as confidence signal."""
        return result.calibrated_confidence, {
            "raw_confidence": result.raw_confidence,
            "calibrated_confidence": result.calibrated_confidence,
            "calibration_applied": result.calibrated_confidence != result.raw_confidence,
        }

    def _calculate_source_quality(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Get the source quality score for the result's source type."""
        quality = self.config.source_quality_scores.get(result.source_type, 0.5)
        return quality, {
            "source_type": result.source_type.value,
            "base_quality": quality,
        }

    def _calculate_usage_frequency(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate usage frequency score from access count and analytics."""
        # Base score from access count (logarithmic scaling)
        base_score = min(math.log1p(result.access_count) / 10.0, 1.0)

        # Enhancement from analytics if available
        analytics_boost = 0.0
        if analytics:
            usage_stats = analytics.get_result_usage_stats(result.source_id, result.source_type)
            if usage_stats:
                # Boost based on successful retrievals
                success_rate = usage_stats.get("success_rate", 0.5)
                analytics_boost = success_rate * 0.2

        score = min(base_score + analytics_boost, 1.0)
        return score, {
            "access_count": result.access_count,
            "base_score": base_score,
            "analytics_boost": analytics_boost,
        }

    def _calculate_recency(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate recency score based on last update time."""
        if not result.last_updated:
            return 0.5, {"reason": "no_timestamp"}

        try:
            updated = datetime.fromisoformat(result.last_updated.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = (now - updated).total_seconds() / 86400

            # Exponential decay: score = exp(-age_days / half_life)
            half_life = 365.0  # 1 year half-life
            score = math.exp(-age_days / half_life)

            return score, {
                "age_days": age_days,
                "half_life": half_life,
                "last_updated": result.last_updated,
            }
        except Exception:
            return 0.5, {"reason": "parse_error"}

    def _calculate_completeness(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Estimate completeness based on content richness."""
        score = 0.0
        factors = []

        # Has summary
        if result.summary:
            score += 0.2
            factors.append("summary")

        # Has tags
        if result.tags:
            score += 0.15
            factors.append("tags")

        # Has related concepts
        if result.related_concepts:
            score += 0.15
            factors.append("related_concepts")

        # Content length (richer content = more complete)
        content_len = len(result.content)
        if content_len > 500:
            score += 0.25
            factors.append("long_content")
        elif content_len > 200:
            score += 0.15
            factors.append("medium_content")
        elif content_len > 50:
            score += 0.1
            factors.append("short_content")

        # Has category
        if result.category:
            score += 0.1
            factors.append("category")

        # Has language
        if result.language:
            score += 0.05
            factors.append("language")

        return min(score, 1.0), {"factors": factors}

    def _calculate_reliability(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate reliability based on source and historical accuracy."""
        # Base reliability from source type
        source_reliability = {
            KnowledgeSourceType.KNOWLEDGE_BASE: 0.95,
            KnowledgeSourceType.SEMANTIC_MEMORY: 0.85,
            KnowledgeSourceType.ENGINEERING_LESSONS: 0.90,
            KnowledgeSourceType.USER_KNOWLEDGE: 0.80,
            KnowledgeSourceType.DOCUMENTATION: 0.85,
            KnowledgeSourceType.EXTRACTED_KNOWLEDGE: 0.75,
            KnowledgeSourceType.EXPERIENCE_MEMORY: 0.70,
            KnowledgeSourceType.PROJECT_MEMORY: 0.75,
            KnowledgeSourceType.LONG_TERM_MEMORY: 0.85,
            KnowledgeSourceType.EPISODIC_MEMORY: 0.65,
            KnowledgeSourceType.CONVERSATION_MEMORY: 0.60,
            KnowledgeSourceType.WORKING_MEMORY: 0.70,
            KnowledgeSourceType.EXTERNAL_KNOWLEDGE: 0.55,
            KnowledgeSourceType.UNKNOWN: 0.50,
        }

        base = source_reliability.get(result.source_type, 0.5)

        # Adjust based on confidence (high confidence = more reliable)
        confidence_boost = result.calibrated_confidence * 0.1

        # Analytics adjustment
        analytics_adj = 0.0
        if analytics:
            hist = analytics.get_source_reliability(result.source_type)
            if hist is not None:
                analytics_adj = (hist - 0.5) * 0.2  # +/- 10% based on history

        score = min(max(base + confidence_boost + analytics_adj, 0.0), 1.0)
        return score, {
            "base_reliability": base,
            "confidence_boost": confidence_boost,
            "analytics_adjustment": analytics_adj,
        }

    def _calculate_freshness(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate freshness - similar to recency but focused on update frequency."""
        # Freshness considers both age and whether the knowledge is likely current
        if not result.last_updated:
            return 0.5, {"reason": "no_timestamp"}

        try:
            updated = datetime.fromisoformat(result.last_updated.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = (now - updated).total_seconds() / 86400

            # Freshness decays faster than recency
            # Very recent = 1.0, 1 week = 0.8, 1 month = 0.5, 6 months = 0.2
            if age_days <= 1:
                score = 1.0
            elif age_days <= 7:
                score = 0.9 - (age_days / 7) * 0.1
            elif age_days <= 30:
                score = 0.8 - ((age_days - 7) / 23) * 0.3
            elif age_days <= 180:
                score = 0.5 - ((age_days - 30) / 150) * 0.3
            else:
                score = 0.2

            return max(0.0, score), {
                "age_days": age_days,
                "updated": result.last_updated,
            }
        except Exception:
            return 0.5, {"reason": "parse_error"}

    def _calculate_historical_usefulness(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        analytics: Optional["UsageAnalytics"] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate historical usefulness from analytics."""
        if not analytics:
            return 0.5, {"reason": "no_analytics"}

        usefulness = analytics.get_result_usefulness(result.source_id, result.source_type)
        if usefulness is None:
            return 0.5, {"reason": "no_history"}

        return usefulness, {"historical_usefulness": usefulness}


class AdaptiveRankingEngine(RankingEngine):
    """Ranking engine that adapts weights based on usage analytics."""

    def __init__(self, config: Optional[RankingConfig] = None):
        super().__init__(config)
        self._feedback_buffer: List[Dict[str, Any]] = []
        self._adaptation_interval = 100  # Adapt after this many feedback events

    def record_feedback(
        self,
        result: KnowledgeRetrievalResult,
        query: RetrievalQuery,
        feedback: str,  # "positive", "negative", "ignored"
    ) -> None:
        """Record user/system feedback for adaptive ranking."""
        self._feedback_buffer.append({
            "result": result,
            "query": query,
            "feedback": feedback,
            "timestamp": time.time(),
        })

        if len(self._feedback_buffer) >= self._adaptation_interval:
            self._adapt_weights()

    def _adapt_weights(self) -> None:
        """Adapt ranking weights based on feedback history."""
        if not self.config.adaptation_enabled or not self._feedback_buffer:
            return

        # Simple adaptation: increase weights of signals that correlate with positive feedback
        signal_feedback = defaultdict(lambda: {"positive": 0, "total": 0})

        for item in self._feedback_buffer:
            result = item["result"]
            feedback = item["feedback"]
            if not result.ranking_explanation:
                continue

            for factor in result.ranking_explanation.factors:
                signal_feedback[factor.signal]["total"] += 1
                if feedback == "positive":
                    signal_feedback[factor.signal]["positive"] += 1

        # Adjust weights
        rate = self.config.adaptation_rate
        for signal, stats in signal_feedback.items():
            if stats["total"] < 5:  # Need minimum samples
                continue

            positive_rate = stats["positive"] / stats["total"]
            current_weight = self.config.weights.get(signal, 0)

            # Adjust toward positive_rate (target ~0.5 is neutral)
            if positive_rate > 0.6:
                # Signal correlates with success, increase weight
                new_weight = current_weight * (1 + rate)
            elif positive_rate < 0.4:
                # Signal correlates with failure, decrease weight
                new_weight = current_weight * (1 - rate)
            else:
                new_weight = current_weight

            # Clamp and update
            new_weight = max(0.01, min(1.0, new_weight))
            self.config.weights[signal] = new_weight

        # Renormalize weights
        total = sum(self.config.weights.values())
        if total > 0:
            for signal in self.config.weights:
                self.config.weights[signal] /= total

        logger.info(f"Adapted ranking weights: {self.config.weights}")
        self._feedback_buffer.clear()

    def get_weight_history(self) -> Dict[str, float]:
        """Get current weights."""
        return {s.value: w for s, w in self.config.weights.items()}


# Convenience function
def create_ranking_engine(config: Optional[RankingConfig] = None, adaptive: bool = True):
    """Create a ranking engine instance."""
    if adaptive:
        return AdaptiveRankingEngine(config)
    return RankingEngine(config)


# Import for type hints
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge_retrieval.analytics import UsageAnalytics