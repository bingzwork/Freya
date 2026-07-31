"""Real-Time Usage Analytics for Knowledge Retrieval.

This module tracks how retrieved knowledge is used over time to continuously
improve ranking weights and quality.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque

from app.knowledge_retrieval.models import (
    UsageEvent,
    KnowledgeSourceType,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievalSession:
    """A single retrieval session with multiple results."""
    session_id: str
    query: str
    context: Dict[str, Any]
    results: List[Dict[str, Any]]  # Simplified result info
    timestamp: str
    duration: float


@dataclass
class ResultUsageStats:
    """Aggregated usage statistics for a specific result."""
    result_id: str
    source_type: KnowledgeSourceType
    total_retrievals: int = 0
    total_selections: int = 0
    total_ignores: int = 0
    positive_feedback: int = 0
    negative_feedback: int = 0
    task_successes: int = 0
    task_failures: int = 0
    last_accessed: Optional[str] = None
    avg_rank_position: float = 0.0
    avg_rank_score: float = 0.0

    @property
    def selection_rate(self) -> float:
        if self.total_retrievals == 0:
            return 0.0
        return self.total_selections / self.total_retrievals

    @property
    def success_rate(self) -> float:
        total = self.task_successes + self.task_failures
        if total == 0:
            return 0.5
        return self.task_successes / total

    @property
    def usefulness_score(self) -> float:
        """Combined usefulness score (0-1)."""
        # Weighted combination of selection, feedback, and task success
        selection_weight = 0.3
        feedback_weight = 0.4
        task_weight = 0.3

        feedback_score = 0.5
        if self.positive_feedback + self.negative_feedback > 0:
            feedback_score = self.positive_feedback / (self.positive_feedback + self.negative_feedback)

        return (
            selection_weight * self.selection_rate +
            feedback_weight * feedback_score +
            task_weight * self.success_rate
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        data["selection_rate"] = self.selection_rate
        data["success_rate"] = self.success_rate
        data["usefulness_score"] = self.usefulness_score
        return data


@dataclass
class SourceUsageStats:
    """Aggregated usage statistics for a knowledge source type."""
    source_type: KnowledgeSourceType
    total_queries: int = 0
    total_results_retrieved: int = 0
    unique_results_accessed: int = 0
    avg_results_per_query: float = 0.0
    top_result_selection_rate: float = 0.0
    task_success_contribution: float = 0.0
    avg_calibrated_confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        return data


class UsageAnalytics:
    """Tracks and analyzes knowledge retrieval usage patterns."""

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        max_events: int = 100000,
        persistence_interval: int = 100,
    ):
        self.storage_path = storage_path or Path("data/knowledge_retrieval/usage_analytics.json")
        self.max_events = max_events
        self.persistence_interval = persistence_interval

        # In-memory storage (bounded)
        self._events: deque = deque(maxlen=max_events)
        self._result_stats: Dict[str, ResultUsageStats] = {}
        self._source_stats: Dict[KnowledgeSourceType, SourceUsageStats] = defaultdict(
            lambda: SourceUsageStats(source_type=KnowledgeSourceType.UNKNOWN)
        )
        self._session_history: List[RetrievalSession] = []

        # Session tracking
        self._current_session: Optional[RetrievalSession] = None
        self._event_counter = 0
        self._lock = threading.RLock()

        # Load existing data
        self._load()

    def record_retrieval(
        self,
        query: str,
        results: List[Dict[str, Any]],  # List of {result_id, source_type, rank_position, rank_score, ...}
        context: Optional[Dict[str, Any]] = None,
        duration: float = 0.0,
    ) -> str:
        """Record a retrieval event."""
        with self._lock:
            session_id = f"sess_{int(time.time() * 1000)}"
            session = RetrievalSession(
                session_id=session_id,
                query=query,
                context=context or {},
                results=results,
                timestamp=datetime.now(timezone.utc).isoformat(),
                duration=duration,
            )
            self._session_history.append(session)
            if len(self._session_history) > 1000:
                self._session_history = self._session_history[-1000:]

            # Record individual result retrievals
            for i, result in enumerate(results):
                result_id = result.get("result_id", f"unknown_{i}")
                source_type_str = result.get("source_type", "unknown")
                source_type = KnowledgeSourceType(source_type_str) if source_type_str != "unknown" else KnowledgeSourceType.UNKNOWN
                rank_position = result.get("rank_position", i + 1)
                rank_score = result.get("rank_score", 0.0)

                event = UsageEvent(
                    retrieval_id=session_id,
                    query=query,
                    result_id=result_id,
                    source_type=source_type,
                    action="retrieved",
                    rank_position=rank_position,
                    rank_score=rank_score,
                    metadata={"session_id": session_id},
                )
                self._record_event(event)

                # Update result stats
                self._update_result_stats(result_id, source_type, "retrieved", rank_position, rank_score)

                # Update source stats
                src_stat = self._source_stats[source_type]
                if src_stat.source_type == KnowledgeSourceType.UNKNOWN:
                    src_stat.source_type = source_type
                src_stat.total_queries += 1
                src_stat.total_results_retrieved += 1

            # Update source stats averages
            for src_type, stats in self._source_stats.items():
                if stats.total_queries > 0:
                    stats.avg_results_per_query = stats.total_results_retrieved / stats.total_queries

            self._maybe_persist()
            return session_id

    def record_selection(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        rank_position: int,
        rank_score: float,
        query: str = "",
    ) -> None:
        """Record that a result was selected/used."""
        with self._lock:
            event = UsageEvent(
                retrieval_id=f"sel_{int(time.time() * 1000)}",
                query=query,
                result_id=result_id,
                source_type=source_type,
                action="selected",
                rank_position=rank_position,
                rank_score=rank_score,
            )
            self._record_event(event)
            self._update_result_stats(result_id, source_type, "selected", rank_position, rank_score)
            self._maybe_persist()

    def record_ignore(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        rank_position: int,
        rank_score: float,
        query: str = "",
    ) -> None:
        """Record that a result was ignored."""
        with self._lock:
            event = UsageEvent(
                retrieval_id=f"ign_{int(time.time() * 1000)}",
                query=query,
                result_id=result_id,
                source_type=source_type,
                action="ignored",
                rank_position=rank_position,
                rank_score=rank_score,
            )
            self._record_event(event)
            self._update_result_stats(result_id, source_type, "ignored", rank_position, rank_score)
            self._maybe_persist()

    def record_feedback(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        positive: bool,
        query: str = "",
    ) -> None:
        """Record user feedback (positive/negative)."""
        with self._lock:
            action = "feedback_positive" if positive else "feedback_negative"
            event = UsageEvent(
                retrieval_id=f"fb_{int(time.time() * 1000)}",
                query=query,
                result_id=result_id,
                source_type=source_type,
                action=action,
                rank_position=0,
                rank_score=0.0,
            )
            self._record_event(event)
            self._update_result_stats(result_id, source_type, action, 0, 0.0)
            self._maybe_persist()

    def record_task_outcome(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        success: bool,
    ) -> None:
        """Record task success/failure associated with a result."""
        with self._lock:
            self._update_result_stats(result_id, source_type, "task_success" if success else "task_failure", 0, 0.0)
            self._maybe_persist()

    def _record_event(self, event: UsageEvent) -> None:
        self._events.append(event)
        self._event_counter += 1

    def _update_result_stats(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
        action: str,
        rank_position: int,
        rank_score: float,
    ) -> None:
        key = f"{source_type.value}:{result_id}"
        stats = self._result_stats.get(key)
        if not stats:
            stats = ResultUsageStats(result_id=result_id, source_type=source_type)
            self._result_stats[key] = stats

        stats.last_accessed = datetime.now(timezone.utc).isoformat()

        if action == "retrieved":
            stats.total_retrievals += 1
            # Moving average for rank position and score
            n = stats.total_retrievals
            stats.avg_rank_position = ((n - 1) * stats.avg_rank_position + rank_position) / n
            stats.avg_rank_score = ((n - 1) * stats.avg_rank_score + rank_score) / n

        elif action == "selected":
            stats.total_selections += 1
        elif action == "ignored":
            stats.total_ignores += 1
        elif action == "feedback_positive":
            stats.positive_feedback += 1
        elif action == "feedback_negative":
            stats.negative_feedback += 1
        elif action == "task_success":
            stats.task_successes += 1
        elif action == "task_failure":
            stats.task_failures += 1

    def get_result_usage_stats(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
    ) -> Optional[Dict[str, Any]]:
        """Get usage statistics for a specific result."""
        with self._lock:
            key = f"{source_type.value}:{result_id}"
            stats = self._result_stats.get(key)
            return stats.to_dict() if stats else None

    def get_result_usefulness(
        self,
        result_id: str,
        source_type: KnowledgeSourceType,
    ) -> Optional[float]:
        """Get usefulness score for a result."""
        stats = self.get_result_usage_stats(result_id, source_type)
        return stats.get("usefulness_score") if stats else None

    def get_source_reliability(self, source_type: KnowledgeSourceType) -> Optional[float]:
        """Get reliability score for a source type based on historical performance."""
        with self._lock:
            stats = self._source_stats.get(source_type)
            if not stats or stats.total_queries == 0:
                return None

            # Reliability based on top-result selection rate and task contribution
            return (stats.top_result_selection_rate + stats.task_success_contribution) / 2

    def get_source_stats(self, source_type: KnowledgeSourceType) -> Optional[Dict[str, Any]]:
        """Get statistics for a source type."""
        with self._lock:
            stats = self._source_stats.get(source_type)
            return stats.to_dict() if stats else None

    def get_all_source_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all source types."""
        with self._lock:
            return {k.value: v.to_dict() for k, v in self._source_stats.items()}

    def get_recent_events(
        self,
        limit: int = 100,
        source_type: Optional[KnowledgeSourceType] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent usage events."""
        with self._lock:
            events = list(self._events)
            if source_type:
                events = [e for e in events if e.source_type == source_type]
            if action:
                events = [e for e in events if e.action == action]
            return [e.to_dict() for e in events[-limit:]]

    def get_query_analytics(
        self,
        query: Optional[str] = None,
        time_window_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get analytics for queries matching criteria."""
        with self._lock:
            events = list(self._events)
            cutoff = None
            if time_window_hours:
                cutoff = time.time() - time_window_hours * 3600

            filtered = []
            for e in events:
                if query and query.lower() not in e.query.lower():
                    continue
                if cutoff:
                    try:
                        event_time = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00")).timestamp()
                        if event_time < cutoff:
                            continue
                    except Exception:
                        pass
                filtered.append(e)

            return {
                "total_events": len(filtered),
                "by_action": self._count_by(filtered, "action"),
                "by_source": self._count_by(filtered, "source_type"),
                "avg_rank_position": self._avg(filtered, "rank_position") if filtered else 0,
                "avg_rank_score": self._avg(filtered, "rank_score") if filtered else 0,
            }

    def _count_by(self, events: List[UsageEvent], attr: str) -> Dict[str, int]:
        counts = defaultdict(int)
        for e in events:
            val = getattr(e, attr)
            if isinstance(val, KnowledgeSourceType):
                val = val.value
            counts[str(val)] += 1
        return dict(counts)

    def _avg(self, events: List[UsageEvent], attr: str) -> float:
        vals = [getattr(e, attr) for e in events if getattr(e, attr) > 0]
        return sum(vals) / len(vals) if vals else 0.0

    def _maybe_persist(self) -> None:
        if self._event_counter % self.persistence_interval == 0:
            self.save()

    def save(self) -> None:
        """Persist analytics data to disk."""
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)

                data = {
                    "events": [e.to_dict() for e in list(self._events)[-1000:]],  # Save last 1000
                    "result_stats": {k: v.to_dict() for k, v in self._result_stats.items()},
                    "source_stats": {k.value: v.to_dict() for k, v in self._source_stats.items()},
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }

                temp_path = self.storage_path.with_suffix(".tmp")
                with open(temp_path, "w") as f:
                    json.dump(data, f, indent=2)
                temp_path.replace(self.storage_path)

            except Exception as e:
                logger.warning(f"Failed to save analytics: {e}")

    def _load(self) -> None:
        """Load analytics data from disk."""
        try:
            if not self.storage_path.exists():
                return

            with open(self.storage_path, "r") as f:
                data = json.load(f)

            with self._lock:
                # Load result stats
                for k, v in data.get("result_stats", {}).items():
                    stats = ResultUsageStats(
                        result_id=v["result_id"],
                        source_type=KnowledgeSourceType(v["source_type"]),
                        total_retrievals=v["total_retrievals"],
                        total_selections=v["total_selections"],
                        total_ignores=v["total_ignores"],
                        positive_feedback=v["positive_feedback"],
                        negative_feedback=v["negative_feedback"],
                        task_successes=v["task_successes"],
                        task_failures=v["task_failures"],
                        last_accessed=v.get("last_accessed"),
                        avg_rank_position=v["avg_rank_position"],
                        avg_rank_score=v["avg_rank_score"],
                    )
                    self._result_stats[k] = stats

                # Load source stats
                for k, v in data.get("source_stats", {}).items():
                    stats = SourceUsageStats(
                        source_type=KnowledgeSourceType(k),
                        total_queries=v["total_queries"],
                        total_results_retrieved=v["total_results_retrieved"],
                        unique_results_accessed=v["unique_results_accessed"],
                        avg_results_per_query=v["avg_results_per_query"],
                        top_result_selection_rate=v["top_result_selection_rate"],
                        task_success_contribution=v["task_success_contribution"],
                        avg_calibrated_confidence=v.get("avg_calibrated_confidence", 0.5),
                    )
                    self._source_stats[KnowledgeSourceType(k)] = stats

            logger.info(f"Loaded usage analytics: {len(self._result_stats)} results, {len(self._source_stats)} sources")

        except Exception as e:
            logger.warning(f"Failed to load analytics: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all analytics."""
        with self._lock:
            total_retrievals = sum(s.total_retrievals for s in self._result_stats.values())
            total_selections = sum(s.total_selections for s in self._result_stats.values())

            return {
                "total_events": len(self._events),
                "total_unique_results": len(self._result_stats),
                "total_retrievals": total_retrievals,
                "total_selections": total_selections,
                "overall_selection_rate": total_selections / total_retrievals if total_retrievals > 0 else 0,
                "source_coverage": len(self._source_stats),
                "session_count": len(self._session_history),
            }

    def clear(self) -> None:
        """Clear all analytics data."""
        with self._lock:
            self._events.clear()
            self._result_stats.clear()
            self._source_stats.clear()
            self._session_history.clear()
            self._event_counter = 0
            self.save()