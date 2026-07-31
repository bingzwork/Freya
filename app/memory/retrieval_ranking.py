"""Retrieval Ranking for Freya AI.

This module implements advanced relevance ranking for the unified retrieval layer,
providing learning-to-rank signals, context-aware boosting, and personalization.

Features:
- BM25-style lexical scoring
- Semantic similarity scoring (when embeddings available)
- Recency boosting with decay functions
- Source reliability weighting
- User feedback learning (implicit/explicit)
- Context-aware query expansion
- Result diversification (MMR)
- Personalization from LongTermMemory preferences
"""

import json
import threading
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple, Callable
from enum import Enum
from collections import defaultdict, Counter
import hashlib


class RankingSignal(Enum):
    """Types of ranking signals."""
    LEXICAL = "lexical"           # BM25/keyword match
    SEMANTIC = "semantic"         # Embedding similarity
    RECENCY = "recency"           # Time decay
    POPULARITY = "popularity"     # Access count
    AUTHORITY = "authority"       # Source reliability
    CONTEXT = "context"           # Query context match
    PERSONAL = "personal"         # User preference match
    DIVERSITY = "diversity"       # MMR diversity penalty


@dataclass
class RankingConfig:
    """Configuration for ranking weights and parameters."""
    # Signal weights (must sum to ~1.0 for normalized scores)
    weight_lexical: float = 0.25
    weight_semantic: float = 0.25
    weight_recency: float = 0.15
    weight_popularity: float = 0.10
    weight_authority: float = 0.10
    weight_context: float = 0.10
    weight_personal: float = 0.05

    # Recency decay
    recency_half_life_days: float = 7.0  # Score halves every 7 days
    recency_min_score: float = 0.1

    # Popularity (access count)
    popularity_saturation: int = 50  # Access count for max score

    # Source authority (per memory type)
    source_authority: Dict[str, float] = field(default_factory=lambda: {
        "working": 0.9,       # Current execution context - highest
        "conversation": 0.8,  # Recent conversation
        "lessons": 0.85,      # Validated engineering lessons
        "semantic": 0.8,      # Verified knowledge
        "long_term": 0.75,    # User preferences/facts
        "project": 0.7,       # Project history
        "experience": 0.65,   # Past experiences
        "episodic": 0.6,      # Event log
        "task": 0.7,          # Task history
        "goals": 0.7,         # Goal context
        "knowledge": 0.75,    # Knowledge base
    })

    # Diversification (MMR)
    mmr_lambda: float = 0.7  # 0.7 = favor relevance, 0.3 = favor diversity
    mmr_k: int = 20          # Pool size for MMR selection

    # Context boosting
    context_boost_factor: float = 1.5
    task_type_boost: Dict[str, List[str]] = field(default_factory=lambda: {
        "debug": ["debugging", "error", "failure", "exception"],
        "refactor": ["refactoring", "pattern", "architecture", "clean_code"],
        "test": ["testing", "test", "coverage", "mock"],
        "security": ["security", "vulnerability", "injection", "auth"],
        "performance": ["performance", "optimization", "profiling", "bottleneck"],
        "feature": ["pattern", "best_practice", "design_pattern", "api"],
    })

    # Personalization
    personal_boost_factor: float = 1.3

    # Minimum scores
    min_final_score: float = 0.05

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RankingConfig":
        return cls(**data)


@dataclass
class RankedResult:
    """A retrieval result with ranking details."""
    content: str
    source: str
    source_id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None

    # Ranking breakdown
    signal_scores: Dict[str, float] = field(default_factory=dict)
    rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LexicalScorer:
    """BM25-style lexical scoring."""

    def __init__(self):
        self._doc_freq: Dict[str, int] = defaultdict(int)
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_length = 0
        self._total_docs = 0
        self._k1 = 1.5
        self._b = 0.75

    def build_index(self, documents: List[Tuple[str, str]]) -> None:
        """Build index from (doc_id, content) pairs."""
        self._doc_freq.clear()
        self._doc_lengths.clear()
        self._total_docs = len(documents)

        for doc_id, content in documents:
            words = self._tokenize(content)
            self._doc_lengths[doc_id] = len(words)
            unique_words = set(words)
            for word in unique_words:
                self._doc_freq[word] += 1

        if self._doc_lengths:
            self._avg_doc_length = sum(self._doc_lengths.values()) / len(self._doc_lengths)

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        import re
        return [w.lower() for w in re.findall(r'\w+', text) if len(w) > 1]

    def score(self, query: str, doc_id: str, content: str) -> float:
        """Calculate BM25 score for query against document."""
        if not query or doc_id not in self._doc_lengths:
            return 0.0

        query_words = self._tokenize(query)
        if not query_words:
            return 0.0

        doc_words = self._tokenize(content)
        doc_length = self._doc_lengths[doc_id]
        word_counts = Counter(doc_words)

        score = 0.0
        for word in query_words:
            if word not in self._doc_freq:
                continue

            # IDF
            idf = math.log((self._total_docs - self._doc_freq[word] + 0.5) /
                          (self._doc_freq[word] + 0.5) + 1)

            # TF with saturation
            tf = word_counts.get(word, 0)
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (1 - self._b + self._b * doc_length / self._avg_doc_length)
            score += idf * (numerator / denominator)

        return score


class SemanticScorer:
    """Semantic similarity scoring using embeddings (placeholder for FAISS integration)."""

    def __init__(self, vector_db=None):
        self.vector_db = vector_db
        self._cache: Dict[str, List[float]] = {}

    def score(self, query: str, content: str, doc_id: str) -> float:
        """Score semantic similarity.

        If vector_db is available, use embeddings.
        Otherwise, return a simple word-overlap heuristic.
        """
        if self.vector_db and hasattr(self.vector_db, 'similar_search'):
            try:
                results = self.vector_db.similar_search(query, limit=1)
                if results and results[0].get('_id') == doc_id:
                    return results[0].get('_similarity_score', 0.0)
            except Exception:
                pass

        # Fallback: Jaccard similarity on tokens
        query_tokens = set(query.lower().split())
        content_tokens = set(content.lower().split())
        if not query_tokens or not content_tokens:
            return 0.0

        intersection = query_tokens & content_tokens
        union = query_tokens | content_tokens
        return len(intersection) / len(union) if union else 0.0


class RecencyScorer:
    """Time-decay scoring."""

    def __init__(self, half_life_days: float = 7.0, min_score: float = 0.1):
        self.half_life = half_life_days * 86400  # seconds
        self.min_score = min_score

    def score(self, timestamp: Optional[str], now: Optional[datetime] = None) -> float:
        """Score based on age."""
        if not timestamp:
            return self.min_score

        try:
            then = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now = now or datetime.now(timezone.utc)
            age_seconds = (now - then).total_seconds()

            if age_seconds <= 0:
                return 1.0

            # Exponential decay
            score = math.exp(-math.log(2) * age_seconds / self.half_life)
            return max(score, self.min_score)
        except Exception:
            return self.min_score


class PopularityScorer:
    """Popularity/access frequency scoring."""

    def __init__(self, saturation: int = 50):
        self.saturation = saturation

    def score(self, access_count: int) -> float:
        """Logarithmic popularity score."""
        if access_count <= 0:
            return 0.0
        return min(math.log1p(access_count) / math.log1p(self.saturation), 1.0)


class AuthorityScorer:
    """Source authority scoring."""

    def __init__(self, source_weights: Dict[str, float]):
        self.source_weights = source_weights
        self.default_weight = 0.5

    def score(self, source: str, metadata: Dict[str, Any] = None) -> float:
        """Get authority score for a source."""
        base = self.source_weights.get(source, self.default_weight)

        # Boost for verified/user-confirmed sources
        if metadata:
            if metadata.get("source") == "user":
                base = min(base + 0.15, 1.0)
            elif metadata.get("source") == "verified":
                base = min(base + 0.1, 1.0)
            elif metadata.get("promoted"):
                base = min(base + 0.05, 1.0)

        return base


class ContextScorer:
    """Context-aware scoring based on query context."""

    def __init__(self, config: RankingConfig):
        self.config = config

    def score(
        self,
        result: RankedResult,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score based on context match."""
        score = 1.0

        if not context:
            return score

        metadata = result.metadata

        # Task type boost
        task_type = context.get("task_type")
        if task_type and task_type in self.config.task_type_boost:
            boost_tags = self.config.task_type_boost[task_type]
            entry_tags = metadata.get("tags", [])
            if isinstance(entry_tags, str):
                entry_tags = [entry_tags]
            matches = sum(1 for tag in boost_tags if tag in entry_tags)
            if matches > 0:
                score *= (1.0 + self.config.context_boost_factor * 0.1 * matches)

        # Phase boost
        phase = context.get("phase")
        if phase:
            phase_keywords = {
                "planning": ["plan", "design", "architecture", "pattern"],
                "execution": ["implement", "code", "function", "class"],
                "debugging": ["error", "fix", "debug", "exception", "failure"],
                "review": ["review", "refactor", "improve", "clean"],
                "testing": ["test", "mock", "assert", "coverage"],
            }
            keywords = phase_keywords.get(phase, [])
            content = f"{result.content} {' '.join(entry_tags)}".lower()
            matches = sum(1 for kw in keywords if kw in content)
            if matches > 0:
                score *= (1.0 + self.config.context_boost_factor * 0.05 * matches)

        # Category boost
        boost_category = context.get("boost_category")
        if boost_category and metadata.get("category") == boost_category:
            score *= self.config.context_boost_factor

        # Language match
        language = context.get("language")
        if language and metadata.get("language") == language:
            score *= 1.2

        return min(score, 2.0)  # Cap context boost


class PersonalizationScorer:
    """Personalization based on user preferences from LongTermMemory."""

    def __init__(self, long_term_memory=None, boost_factor: float = 1.3):
        self.long_term_memory = long_term_memory
        self.boost_factor = boost_factor
        self._preference_cache: Optional[Dict[str, float]] = None
        self._cache_time: Optional[datetime] = None

    def _load_preferences(self) -> Dict[str, float]:
        """Load preferences from long-term memory."""
        prefs = {}
        if self.long_term_memory:
            try:
                entries = self.long_term_memory.get_all()
                for entry in entries:
                    if entry.category == "preference":
                        # Store preference weight by key
                        prefs[entry.key] = entry.confidence
            except Exception:
                pass
        return prefs

    def get_preferences(self) -> Dict[str, float]:
        """Get preferences with caching."""
        now = datetime.now(timezone.utc)
        if (self._preference_cache is None or
            self._cache_time is None or
            (now - self._cache_time).total_seconds() > 300):  # 5 min cache
            self._preference_cache = self._load_preferences()
            self._cache_time = now
        return self._preference_cache

    def score(self, result: RankedResult) -> float:
        """Score based on user preferences."""
        prefs = self.get_preferences()
        if not prefs:
            return 1.0

        score = 1.0
        metadata = result.metadata
        content = result.content.lower()

        # Check tags
        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            if tag in prefs:
                score *= self.boost_factor ** prefs[tag]

        # Check category
        category = metadata.get("category", "")
        if category in prefs:
            score *= self.boost_factor ** prefs[category]

        # Check language preference
        language = metadata.get("language", "")
        if language and language in prefs:
            score *= self.boost_factor ** prefs[language]

        # Check source preference
        source = metadata.get("source", "")
        if source and source in prefs:
            score *= self.boost_factor ** prefs[source]

        return min(score, 3.0)  # Cap personalization


class RankingEngine:
    """Main ranking engine combining all signals."""

    def __init__(
        self,
        config: Optional[RankingConfig] = None,
        vector_db=None,
        long_term_memory=None,
    ):
        self.config = config or RankingConfig()
        self._lock = threading.RLock()

        # Scorers
        self.lexical = LexicalScorer()
        self.semantic = SemanticScorer(vector_db)
        self.recency = RecencyScorer(
            self.config.recency_half_life_days,
            self.config.recency_min_score
        )
        self.popularity = PopularityScorer(self.config.popularity_saturation)
        self.authority = AuthorityScorer(self.config.source_authority)
        self.context = ContextScorer(self.config)
        self.personal = PersonalizationScorer(long_term_memory, self.config.personal_boost_factor)

        # Learning signals
        self._click_history: Dict[str, int] = defaultdict(int)  # result_id -> clicks
        self._dwell_history: Dict[str, float] = defaultdict(float)  # result_id -> dwell time

    def rank(
        self,
        query: str,
        results: List[RankedResult],
        context: Optional[Dict[str, Any]] = None,
        apply_mmr: bool = True,
    ) -> List[RankedResult]:
        """Rank results using all signals."""
        with self._lock:
            if not results:
                return []

            now = datetime.now(timezone.utc)

            # Build lexical index
            doc_pairs = [(f"{r.source}:{r.source_id}", r.content) for r in results]
            self.lexical.build_index(doc_pairs)

            # Score each result
            for i, result in enumerate(results):
                doc_id = f"{result.source}:{result.source_id}"

                # Lexical score
                lexical_score = self.lexical.score(query, doc_id, result.content)

                # Semantic score
                semantic_score = self.semantic.score(query, result.content, doc_id)

                # Recency score
                recency_score = self.recency.score(result.timestamp, now)

                # Popularity score
                access_count = result.metadata.get("access_count", 0)
                popularity_score = self.popularity.score(access_count)

                # Authority score
                authority_score = self.authority.score(result.source, result.metadata)

                # Context score
                context_score = self.context.score(result, query, context)

                # Personalization score
                personal_score = self.personal.score(result)

                # Combine signals (normalized weighted sum)
                weights = {
                    RankingSignal.LEXICAL.value: self.config.weight_lexical,
                    RankingSignal.SEMANTIC.value: self.config.weight_semantic,
                    RankingSignal.RECENCY.value: self.config.weight_recency,
                    RankingSignal.POPULARITY.value: self.config.weight_popularity,
                    RankingSignal.AUTHORITY.value: self.config.weight_authority,
                    RankingSignal.CONTEXT.value: self.config.weight_context,
                    RankingSignal.PERSONAL.value: self.config.weight_personal,
                }

                signal_scores = {
                    RankingSignal.LEXICAL.value: lexical_score,
                    RankingSignal.SEMANTIC.value: semantic_score,
                    RankingSignal.RECENCY.value: recency_score,
                    RankingSignal.POPULARITY.value: popularity_score,
                    RankingSignal.AUTHORITY.value: authority_score,
                    RankingSignal.CONTEXT.value: context_score,
                    RankingSignal.PERSONAL.value: personal_score,
                }

                # Weighted sum
                final_score = sum(
                    weights.get(k, 0) * v for k, v in signal_scores.items()
                )

                # Apply learned signals (clicks, dwell)
                click_boost = 1.0 + math.log1p(self._click_history.get(doc_id, 0)) * 0.05
                dwell_boost = 1.0 + min(self._dwell_history.get(doc_id, 0) / 60.0, 1.0) * 0.1
                final_score *= click_boost * dwell_boost

                # Store breakdown
                result.signal_scores = signal_scores
                result.score = max(final_score, self.config.min_final_score)

            # Sort by score descending
            results.sort(key=lambda r: r.score, reverse=True)

            # Apply MMR diversification
            if apply_mmr and len(results) > 1:
                results = self._apply_mmr(results, query)

            # Assign ranks
            for i, result in enumerate(results):
                result.rank = i + 1

            return results

    def _apply_mmr(self, results: List[RankedResult], query: str) -> List[RankedResult]:
        """Apply Maximal Marginal Relevance for diversification."""
        if len(results) <= 1:
            return results

        # Select from top-k pool
        pool = results[:self.config.mmr_k]
        selected = []
        remaining = pool.copy()

        # Start with top result
        selected.append(remaining.pop(0))

        while remaining and len(selected) < len(pool):
            best_score = -1
            best_idx = -1

            for idx, candidate in enumerate(remaining):
                # Relevance score
                relevance = candidate.score

                # Max similarity to already selected
                max_sim = 0.0
                for sel in selected:
                    sim = self._content_similarity(candidate.content, sel.content)
                    max_sim = max(max_sim, sim)

                # MMR score
                mmr_score = (self.config.mmr_lambda * relevance -
                            (1 - self.config.mmr_lambda) * max_sim)

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx

            if best_idx >= 0:
                selected.append(remaining.pop(best_idx))
            else:
                break

        # Append remaining non-pool results
        selected.extend(results[self.config.mmr_k:])
        return selected

    def _content_similarity(self, content1: str, content2: str) -> float:
        """Calculate Jaccard similarity between two contents."""
        tokens1 = set(content1.lower().split())
        tokens2 = set(content2.lower().split())
        if not tokens1 or not tokens2:
            return 0.0
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        return len(intersection) / len(union) if union else 0.0

    def record_click(self, source: str, source_id: str) -> None:
        """Record a click/selection for learning."""
        with self._lock:
            doc_id = f"{source}:{source_id}"
            self._click_history[doc_id] += 1

    def record_dwell(self, source: str, source_id: str, seconds: float) -> None:
        """Record dwell time for learning."""
        with self._lock:
            doc_id = f"{source}:{source_id}"
            # Exponential moving average
            current = self._dwell_history.get(doc_id, 0.0)
            self._dwell_history[doc_id] = 0.7 * current + 0.3 * seconds

    def update_config(self, config: RankingConfig) -> None:
        """Update ranking configuration."""
        with self._lock:
            self.config = config
            self.authority = AuthorityScorer(config.source_authority)
            self.context = ContextScorer(config)
            self.personal = PersonalizationScorer(
                self.personal.long_term_memory,
                config.personal_boost_factor
            )
            self.recency = RecencyScorer(
                config.recency_half_life_days,
                config.recency_min_score
            )
            self.popularity = PopularityScorer(config.popularity_saturation)

    def get_stats(self) -> Dict[str, Any]:
        """Get ranking engine statistics."""
        with self._lock:
            return {
                "config": self.config.to_dict(),
                "click_tracking": len(self._click_history),
                "dwell_tracking": len(self._dwell_history),
                "total_clicks": sum(self._click_history.values()),
            }


def create_ranking_engine(
    config: Optional[RankingConfig] = None,
    vector_db=None,
    long_term_memory=None,
) -> RankingEngine:
    """Factory function to create RankingEngine."""
    return RankingEngine(config=config, vector_db=vector_db, long_term_memory=long_term_memory)


# Integration with UnifiedRetrieval
class RankedUnifiedRetrieval:
    """UnifiedRetrieval enhanced with advanced ranking."""

    def __init__(self, base_retrieval, ranking_engine: RankingEngine):
        self.base_retrieval = base_retrieval
        self.ranking_engine = ranking_engine

    def retrieve(self, query, context=None, max_results=20, min_score=0.1):
        """Retrieve and rank results."""
        # Get raw results from base retrieval
        if isinstance(query, str):
            from app.memory.unified_retrieval import RetrievalQuery
            query_obj = RetrievalQuery(query=query, context=context, max_results=max_results * 2, min_score=0.0)
        else:
            query_obj = query
            query_obj.max_results = max_results * 2
            query_obj.min_score = 0.0

        raw_results = self.base_retrieval.retrieve(query_obj)

        # Convert to RankedResult
        ranked_results = []
        for r in raw_results:
            ranked = RankedResult(
                content=r.content,
                source=r.source,
                source_id=r.source_id,
                score=r.score,
                metadata=r.metadata,
                timestamp=r.timestamp,
            )
            ranked_results.append(ranked)

        # Apply advanced ranking
        final_results = self.ranking_engine.rank(
            query=query_obj.query if hasattr(query_obj, 'query') else str(query),
            results=ranked_results,
            context=context or getattr(query_obj, 'context', None),
            apply_mmr=True,
        )

        # Apply final limits
        final_results = [r for r in final_results if r.score >= min_score]
        return final_results[:max_results]

    def retrieve_for_planner(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Retrieve formatted context for planner with ranking."""
        results = self.retrieve(task, context, max_results=15, min_score=0.15)
        return self.base_retrieval.retrieve_for_planner(task, context)

    def record_feedback(self, source: str, source_id: str, action: str, dwell_seconds: float = 0):
        """Record user feedback for learning."""
        if action in ("click", "select", "use"):
            self.ranking_engine.record_click(source, source_id)
        if dwell_seconds > 0:
            self.ranking_engine.record_dwell(source, source_id, dwell_seconds)