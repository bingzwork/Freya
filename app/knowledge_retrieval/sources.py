"""Knowledge Source Adapters for Knowledge Retrieval.

This module provides adapters that convert various knowledge sources into
the unified KnowledgeRetrievalResult format for ranking.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.knowledge_retrieval.models import (
    KnowledgeRetrievalResult,
    RetrievalQuery,
    KnowledgeSourceType,
    RankingConfig,
)
from app.memory.conversation_memory import ConversationMemory

logger = logging.getLogger(__name__)


class KnowledgeSourceAdapter(ABC):
    """Abstract base class for knowledge source adapters."""

    @property
    @abstractmethod
    def source_type(self) -> KnowledgeSourceType:
        """Return the source type this adapter handles."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this source is available."""
        pass

    @abstractmethod
    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        """Retrieve raw candidates from the source (before ranking)."""
        pass

    @abstractmethod
    def get_source_quality(self) -> float:
        """Get the source quality score (0-1)."""
        pass


class SemanticMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Semantic Memory."""

    def __init__(self, semantic_memory):
        self.memory = semantic_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.SEMANTIC_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None and not self.memory.is_empty()

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            category = query.boost_category
            if query.context and query.context.get("category"):
                category = query.context["category"]

            language = query.boost_language
            if query.context and query.context.get("language"):
                language = query.context["language"]

            entries = self.memory.search(
                query=query.query if query.query else None,
                category=category,
                language=language,
                tags=None,
                min_confidence=0.0,
                limit=max_results,
            )

            results = []
            for entry in entries:
                result = KnowledgeRetrievalResult(
                    content=entry.content,
                    title=entry.title,
                    summary=entry.content[:200] if len(entry.content) > 200 else entry.content,
                    source_type=self.source_type,
                    source_id=entry.entry_id,
                    raw_confidence=entry.confidence,
                    calibrated_confidence=entry.confidence,  # Will be calibrated later
                    category=entry.category,
                    tags=entry.tags,
                    language=entry.language,
                    related_concepts=entry.related_concepts,
                    last_updated=entry.updated_at,
                    access_count=entry.access_count,
                    source_metadata={
                        "source": entry.source,
                        "examples_count": len(entry.examples),
                        "prerequisites": entry.prerequisites,
                    },
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Semantic memory retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.90


class EpisodicMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Episodic Memory."""

    def __init__(self, episodic_memory):
        self.memory = episodic_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.EPISODIC_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            days = query.context.get("days", 30) if query.context else 30
            hours = query.context.get("hours") if query.context else None

            events = self.memory.get_events_since(days=days, hours=hours)

            # Filter by event types if specified
            event_types = query.context.get("event_types") if query.context else None
            if event_types:
                events = [e for e in events if e.event_type in event_types]

            # Filter by outcomes if specified
            outcomes = query.context.get("outcomes") if query.context else None
            if outcomes:
                events = [e for e in events if e.outcome in outcomes]

            # Simple text search
            if query.query:
                query_lower = query.query.lower()
                events = [
                    e for e in events
                    if query_lower in e.title.lower() or query_lower in e.description.lower()
                ]

            results = []
            for event in events[:max_results]:
                content = f"Event [{event.event_type}] {event.title}"
                if event.description:
                    content += f": {event.description}"
                if event.outcome != "neutral":
                    content += f" (outcome: {event.outcome})"
                if event.tags:
                    content += f" [tags: {', '.join(event.tags)}]"

                # Score based on outcome
                outcome_scores = {"success": 0.8, "partial": 0.6, "neutral": 0.4, "failure": 0.3}
                raw_conf = outcome_scores.get(event.outcome, 0.5)

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=event.title,
                    summary=event.description[:200] if event.description else "",
                    source_type=self.source_type,
                    source_id=event.event_id,
                    raw_confidence=raw_conf,
                    calibrated_confidence=raw_conf,
                    category=event.event_type,
                    tags=event.tags,
                    last_updated=event.timestamp,
                    source_metadata={
                        "event_type": event.event_type,
                        "outcome": event.outcome,
                        "task_id": event.task_id,
                        "file_paths": event.file_paths,
                    },
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Episodic memory retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.70


class ProjectMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Project Memory."""

    def __init__(self, project_memory):
        self.memory = project_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.PROJECT_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = []

            # Use semantic search if available
            if hasattr(self.memory, 'similar_search') and callable(self.memory.similar_search):
                similar = self.memory.similar_search(query.query, limit=max_results)
                for entry in similar:
                    score = entry.get("_similarity_score", 0.5)
                    if score < query.min_score:
                        continue

                    kind = entry.get("kind", "unknown")
                    content = f"[{kind}] {entry.get('content', {})}"

                    result = KnowledgeRetrievalResult(
                        content=content,
                        title=f"Project {kind}",
                        summary=str(entry.get('content', {}))[:200],
                        source_type=self.source_type,
                        source_id=entry.get("timestamp", ""),
                        raw_confidence=score,
                        calibrated_confidence=score,
                        category=kind,
                        last_updated=entry.get("timestamp"),
                        source_metadata={"kind": kind, "content": entry.get("content", {})},
                    )
                    results.append(result)
            else:
                # Fallback to keyword search
                keyword_results = self.memory.search(query.query, limit=max_results)
                for entry in keyword_results:
                    kind = entry.get("kind", "unknown")
                    content = f"[{kind}] {entry.get('content', {})}"

                    result = KnowledgeRetrievalResult(
                        content=content,
                        title=f"Project {kind}",
                        summary=str(entry.get('content', {}))[:200],
                        source_type=self.source_type,
                        source_id=entry.get("timestamp", ""),
                        raw_confidence=0.5,
                        calibrated_confidence=0.5,
                        category=kind,
                        last_updated=entry.get("timestamp"),
                        source_metadata={"kind": kind, "content": entry.get("content", {})},
                    )
                    results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Project memory retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.80


class WorkingMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Working Memory."""

    def __init__(self, working_memory):
        self.memory = working_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.WORKING_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None and getattr(self.memory, 'is_active', False)

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        results = []

        try:
            # Get current plan
            plan = self.memory.get_plan()
            if plan:
                result = KnowledgeRetrievalResult(
                    content=f"Current Plan: {plan.description}",
                    title="Active Plan",
                    summary=plan.description[:200],
                    source_type=self.source_type,
                    source_id=plan.plan_id,
                    raw_confidence=0.9,
                    calibrated_confidence=0.9,
                    category="plan",
                    last_updated=plan.created_at,
                    source_metadata={"type": "plan", "steps_count": len(plan.steps)},
                )
                results.append(result)

            # Recent tool outputs
            tool_outputs = self.memory.get_recent_tool_outputs(limit=min(10, max_results))
            for i, output in enumerate(tool_outputs):
                content = f"Tool: {output.tool_name}({output.arguments}) -> {str(output.result)[:300]}"
                if not output.success:
                    content += f" [ERROR: {output.error}]"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=f"Tool: {output.tool_name}",
                    summary=content[:200],
                    source_type=self.source_type,
                    source_id=f"tool_{output.tool_name}_{i}",
                    raw_confidence=0.7 if output.success else 0.3,
                    calibrated_confidence=0.7 if output.success else 0.3,
                    category="tool_output",
                    last_updated=output.timestamp,
                    source_metadata={
                        "type": "tool_output",
                        "tool": output.tool_name,
                        "success": output.success,
                    },
                )
                results.append(result)

            # Recent reasoning
            reasoning = self.memory.get_reasoning_steps(limit=5)
            for i, step in enumerate(reasoning):
                content = f"Reasoning [{step.step_type}]: {step.content}"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=f"Reasoning: {step.step_type}",
                    summary=step.content[:200],
                    source_type=self.source_type,
                    source_id=f"reasoning_{step.step_type}_{i}",
                    raw_confidence=0.6,
                    calibrated_confidence=0.6,
                    category="reasoning",
                    last_updated=step.timestamp,
                    source_metadata={"type": "reasoning", "step_type": step.step_type},
                )
                results.append(result)

            # File references
            file_refs = self.memory.get_file_references()
            if file_refs:
                ref_list = "\n".join(f"  {fp}" for fp in list(file_refs.keys())[-10:])
                content = f"Referenced Files:\n{ref_list}"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title="Referenced Files",
                    summary=f"{len(file_refs)} files referenced",
                    source_type=self.source_type,
                    source_id="file_refs",
                    raw_confidence=0.5,
                    calibrated_confidence=0.5,
                    category="file_references",
                    source_metadata={"type": "file_references", "count": len(file_refs)},
                )
                results.append(result)

        except Exception as e:
            logger.warning(f"Working memory retrieval failed: {e}")

        return results[:max_results]

    def get_source_quality(self) -> float:
        return 0.75


class LongTermMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Long-Term Memory."""

    def __init__(self, long_term_memory):
        self.memory = long_term_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.LONG_TERM_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            category = query.boost_category or (query.context.get("category") if query.context else None)

            entries = self.memory.search(
                query=query.query if query.query else None,
                category=category,
                min_confidence=0.3,
                limit=max_results,
            )

            results = []
            for entry in entries:
                # Boost user-stated preferences
                score = entry.confidence
                if entry.source == "user":
                    score = min(score + 0.2, 1.0)

                content = f"Long-Term [{entry.category}] {entry.key}: {entry.value}"
                if entry.description:
                    content += f" — {entry.description}"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=f"LTM: {entry.key}",
                    summary=entry.value[:200],
                    source_type=self.source_type,
                    source_id=f"{entry.category}.{entry.key}",
                    raw_confidence=score,
                    calibrated_confidence=score,
                    category=entry.category,
                    tags=entry.tags,
                    last_updated=entry.updated_at,
                    source_metadata={
                        "category": entry.category,
                        "key": entry.key,
                        "value": entry.value,
                        "confidence": entry.confidence,
                        "source": entry.source,
                    },
                )
                results.append(result)

            return results[:max_results]

        except Exception as e:
            logger.warning(f"Long-term memory retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.85


class ExperienceMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Experience Memory."""

    def __init__(self, experience_memory):
        self.memory = experience_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.EXPERIENCE_MEMORY

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.count() > 0

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            category = query.boost_category or (query.context.get("category") if query.context else None)

            entries = self.memory.search(
                keyword=query.query if query.query else None,
                category=category,
                limit=max_results,
            )

            results = []
            for entry in entries:
                score = 0.6
                if entry.outcome == "positive":
                    score = 0.7
                elif entry.outcome == "negative":
                    score = 0.5
                score *= entry.confidence

                content = f"Experience [{entry.category}] {entry.title}: {entry.description}"
                if entry.outcome != "neutral":
                    content += f" (outcome: {entry.outcome})"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=f"Experience: {entry.title}",
                    summary=entry.description[:200],
                    source_type=self.source_type,
                    source_id=entry.id,
                    raw_confidence=score,
                    calibrated_confidence=score,
                    category=entry.category,
                    tags=entry.tags,
                    last_updated=entry.timestamp,
                    source_metadata={
                        "category": entry.category,
                        "tags": entry.tags,
                        "outcome": entry.outcome,
                        "confidence": entry.confidence,
                    },
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Experience memory retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.75


class EngineeringLessonsAdapter(KnowledgeSourceAdapter):
    """Adapter for Engineering Lessons."""

    def __init__(self, engineering_lessons):
        self.memory = engineering_lessons

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.ENGINEERING_LESSONS

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.count() > 0

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        try:
            category = query.boost_category or (query.context.get("category") if query.context else None)

            lessons = self.memory.search(
                keyword=query.query if query.query else None,
                category=category,
                limit=max_results,
            )

            results = []
            severity_rank = {"critical": 1.0, "important": 0.8, "recommended": 0.6, "info": 0.4}

            for lesson in lessons:
                score = severity_rank.get(lesson.severity, 0.5)
                if lesson.lesson_type == "anti_pattern":
                    score *= 0.8

                content = f"Lesson [{lesson.lesson_type}/{lesson.severity}] {lesson.title}: {lesson.description}"
                if lesson.rationale:
                    content += f" Rationale: {lesson.rationale}"

                result = KnowledgeRetrievalResult(
                    content=content,
                    title=f"Lesson: {lesson.title}",
                    summary=lesson.description[:200],
                    source_type=self.source_type,
                    source_id=lesson.id,
                    raw_confidence=min(score, 1.0),
                    calibrated_confidence=min(score, 1.0),
                    category=lesson.lesson_type,
                    tags=[lesson.category, lesson.severity] + lesson.tags,
                    last_updated=lesson.timestamp,
                    source_metadata={
                        "lesson_type": lesson.lesson_type,
                        "category": lesson.category,
                        "severity": lesson.severity,
                        "rationale": lesson.rationale,
                    },
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Engineering lessons retrieval failed: {e}")
            return []

    def get_source_quality(self) -> float:
        return 0.85


class ExtractedKnowledgeAdapter(KnowledgeSourceAdapter):
    """Adapter for Extracted Knowledge (from knowledge_extraction pipeline)."""

    def __init__(self, knowledge_objects: Optional[List[Any]] = None):
        self._knowledge_objects = knowledge_objects or []

    def add_knowledge_objects(self, objects: List[Any]) -> None:
        """Add extracted knowledge objects."""
        self._knowledge_objects.extend(objects)

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.EXTRACTED_KNOWLEDGE

    def is_available(self) -> bool:
        return len(self._knowledge_objects) > 0

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available() or not query.query:
            return []

        query_lower = query.query.lower()
        results = []

        for obj in self._knowledge_objects:
            if not hasattr(obj, 'content') or not hasattr(obj, 'title'):
                continue

            # Simple relevance check
            searchable = f"{obj.title} {obj.content} {' '.join(getattr(obj, 'tags', []))}".lower()
            if query_lower not in searchable:
                continue

            result = KnowledgeRetrievalResult(
                content=obj.content,
                title=obj.title,
                summary=getattr(obj, 'summary', obj.content[:200]),
                source_type=self.source_type,
                source_id=getattr(obj, 'id', ''),
                raw_confidence=getattr(obj, 'confidence', 0.5),
                calibrated_confidence=getattr(obj, 'confidence', 0.5),
                category=getattr(obj, 'category', None),
                tags=getattr(obj, 'tags', []),
                language=getattr(obj, 'language', None),
                related_concepts=getattr(obj, 'related_entities', []),
                last_updated=getattr(obj, 'extracted_at', None),
                source_metadata={
                    "source": getattr(obj, 'source', ''),
                    "source_type": getattr(obj, 'source_type', ''),
                    "extraction_method": "knowledge_extraction",
                },
            )
            results.append(result)

            if len(results) >= max_results:
                break

        return results

    def get_source_quality(self) -> float:
        return 0.80


class ConversationMemoryAdapter(KnowledgeSourceAdapter):
    """Adapter for Conversation Memory.

    Searches across conversation turns and summaries for relevant
    conversational content.
    """

    def __init__(self, conversation_memory: ConversationMemory):
        self.memory = conversation_memory

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.CONVERSATION_MEMORY

    def is_available(self) -> bool:
        if self.memory is None:
            return False
        # Check if we have any conversation turns or summaries
        history = self.memory.get_history()
        summaries = self.memory.get_summaries()
        return len(history) > 0 or len(summaries) > 0

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available() or not query.query:
            return []

        query_lower = query.query.lower()
        query_words = set(query_lower.split())
        results: List[KnowledgeRetrievalResult] = []

        # Search recent turns
        turns = self.memory.get_history()
        for idx, turn in enumerate(turns):
            content_lower = turn.content.lower()
            # Simple relevance: fraction of query words found in content
            if query_words:
                words_in_content = set(content_lower.split())
                matches = len(query_words & words_in_content)
                relevance = matches / len(query_words) if query_words else 0.0
            else:
                relevance = 0.0
            if relevance == 0.0:
                continue

            # Recency boost: more recent turns get higher boost
            recency_boost = 0.0
            if query.boost_recent and turns:
                # Normalize index to 0..1 where newest is 1.0
                recency_boost = (idx + 1) / len(turns)  # older->lower
                # We want newer to have higher score, so we keep as is
                # Combine with relevance: weighted average
                relevance = relevance * 0.7 + recency_boost * 0.3

            # Base confidence from relevance, scaled
            raw_confidence = min(0.9, 0.5 + relevance * 0.4)  # range 0.5-0.9
            # Ensure within bounds
            raw_confidence = max(0.0, min(1.0, raw_confidence))

            result = KnowledgeRetrievalResult(
                content=turn.content,
                title=turn.content[:100] + ("..." if len(turn.content) > 100 else ""),
                summary=turn.content[:200] + ("..." if len(turn.content) > 200 else ""),
                source_type=self.source_type,
                source_id=f"turn_{idx}",
                raw_confidence=raw_confidence,
                calibrated_confidence=raw_confidence,
                category="conversation",
                last_updated=turn.timestamp,
                source_metadata={
                    "turn_index": idx,
                    "role": turn.role,
                    "entities": turn.entities,
                },
            )
            results.append(result)

        # Search summaries
        summaries = self.memory.get_summaries()
        for summary in summaries:
            summary_lower = summary.summary_text.lower()
            if query_words:
                words_in_summary = set(summary_lower.split())
                matches = len(query_words & words_in_summary)
                relevance = matches / len(query_words) if query_words else 0.0
            else:
                relevance = 0.0
            if relevance == 0.0:
                continue

            # Recency based on summary timestamp
            recency_boost = 0.0
            if query.boost_recent and summaries:
                # We'll just use position in list (newer summaries appended later)
                idx = summaries.index(summary)  # O(n) but small list
                recency_boost = (idx + 1) / len(summaries)
                relevance = relevance * 0.7 + recency_boost * 0.3

            raw_confidence = min(0.9, 0.5 + relevance * 0.4)
            raw_confidence = max(0.0, min(1.0, raw_confidence))

            result = KnowledgeRetrievalResult(
                content=summary.summary_text,
                title=f"Summary: {summary.summary_id}",
                summary=summary.summary_text[:200] + ("..." if len(summary.summary_text) > 200 else ""),
                source_type=self.source_type,
                source_id=f"summary_{summary.summary_id}",
                raw_confidence=raw_confidence,
                calibrated_confidence=raw_confidence,
                category="conversation_summary",
                last_updated=summary.updated_at,
                source_metadata={
                    "summary_id": summary.summary_id,
                    "turn_count": summary.turn_count,
                    "key_topics": summary.key_topics,
                },
            )
            results.append(result)

        # Sort by raw_confidence descending
        results.sort(key=lambda r: r.raw_confidence, reverse=True)
        return results[:max_results]

    def get_source_quality(self) -> float:
        return 0.65  # matches RankingConfig default


class VectorSearchAdapter(KnowledgeSourceAdapter):
    """Adapter for Vector Search (FAISS-based semantic search)."""

    def __init__(self, vector_db):
        self.vector_db = vector_db

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.VECTOR_SEARCH

    def is_available(self) -> bool:
        return self.vector_db is not None and not self.vector_db.is_empty()

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available() or not query.query:
            return []

        # Perform vector search
        results = self.vector_db.search(query.query, limit=max_results)
        k_results: List[KnowledgeRetrievalResult] = []

        for item in results:
            # Assuming item is (id, score, metadata) as per test
            if len(item) >= 3:
                vec_id, score, metadata = item[0], item[1], item[2]
            else:
                # Fallback: treat as (id, score) with empty metadata
                vec_id, score = item[0], item[1]
                metadata = {}
            content = str(metadata.get("content", ""))
            title = str(metadata.get("title", ""))
            summary = content[:200] + ("..." if len(content) > 200 else "")
            # Ensure score is float between 0 and 1
            try:
                raw_conf = float(score)
            except (ValueError, TypeError):
                raw_conf = 0.0
            raw_conf = max(0.0, min(1.0, raw_conf))
            # Use raw_conf as calibrated (will be calibrated later)
            result_obj = KnowledgeRetrievalResult(
                content=content,
                title=title,
                summary=summary,
                source_type=self.source_type,
                source_id=str(vec_id),
                raw_confidence=raw_conf,
                calibrated_confidence=raw_conf,
                # Optionally set category, tags, etc. from metadata if available
                last_updated=metadata.get("updated_at") or metadata.get("timestamp"),
                source_metadata=metadata,
            )
            k_results.append(result_obj)

        return k_results

    def get_source_quality(self) -> float:
        return 0.85  # matches RankingConfig default


class DocumentationAdapter(KnowledgeSourceAdapter):
    """Adapter for Documentation (markdown, etc.)."""

    def __init__(self, docs_path: Union[str, Path] = "docs"):
        self.docs_path = Path(docs_path)
        self._cached_results: List[KnowledgeRetrievalResult] = []
        self._cache_fresh = False

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.DOCUMENTATION

    def is_available(self) -> bool:
        return self.docs_path.exists()

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available():
            return []

        if not query.query:
            return []

        # Build/refresh cache
        if not self._cache_fresh:
            self._build_cache()

        query_lower = query.query.lower()
        results = []

        for result in self._cached_results:
            searchable = f"{result.title} {result.content} {' '.join(result.tags)}".lower()
            if query_lower in searchable:
                results.append(result)
                if len(results) >= max_results:
                    break

        return results

    def _build_cache(self) -> None:
        """Build searchable cache from documentation files."""
        self._cached_results = []

        try:
            for md_file in self.docs_path.rglob("*.md"):
                if not md_file.is_file():
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")
                    # Simple section extraction
                    sections = self._extract_sections(content, md_file)

                    for section in sections:
                        result = KnowledgeRetrievalResult(
                            content=section["content"],
                            title=section["title"],
                            summary=section["content"][:200],
                            source_type=self.source_type,
                            source_id=f"{md_file.name}:{section['title']}",
                            raw_confidence=0.8,
                            calibrated_confidence=0.8,
                            category=section.get("category"),
                            tags=section.get("tags", []),
                            language=section.get("language"),
                            last_updated=datetime.now(timezone.utc).isoformat(),
                            source_metadata={
                                "file": str(md_file),
                                "section_level": section.get("level", 1),
                            },
                        )
                        self._cached_results.append(result)

                except Exception:
                    continue

            self._cache_fresh = True

        except Exception as e:
            logger.warning(f"Failed to build docs cache: {e}")

    def _extract_sections(self, content: str, file_path: Path) -> List[Dict[str, Any]]:
        """Extract sections from markdown content (simplified)."""
        lines = content.split('\n')
        sections = []
        current_section = None
        current_content = []

        for line in lines:
            if line.startswith('#'):
                # Save previous section
                if current_section:
                    sections.append({
                        "title": current_section,
                        "content": '\n'.join(current_content).strip(),
                        "level": len(current_section.split()[0]) if current_section.split()[0].startswith('#') else 1,
                        "category": self._infer_category(current_section),
                        "tags": self._extract_tags('\n'.join(current_content)),
                    })

                # Start new section
                current_section = line.strip()
                current_content = [line]
            else:
                if current_section:
                    current_content.append(line)

        # Don't forget last section
        if current_section:
            sections.append({
                "title": current_section,
                "content": '\n'.join(current_content).strip(),
                "level": len(current_section.split()[0]) if current_section.split()[0].startswith('#') else 1,
                "category": self._infer_category(current_section),
                "tags": self._extract_tags('\n'.join(current_content)),
            })

        return sections

    def _infer_category(self, heading: str) -> Optional[str]:
        """Infer category from heading."""
        heading_lower = heading.lower()
        if any(kw in heading_lower for kw in ["install", "setup", "getting started", "quickstart"]):
            return "procedure"
        elif any(kw in heading_lower for kw in ["api", "reference", "function", "class", "method"]):
            return "reference"
        elif any(kw in heading_lower for kw in ["example", "tutorial", "guide"]):
            return "example"
        elif any(kw in heading_lower for kw in ["troubleshoot", "error", "issue", "problem", "faq"]):
            return "troubleshooting"
        elif any(kw in heading_lower for kw in ["best practice", "recommend", "guideline", "tip"]):
            return "best_practice"
        elif any(kw in heading_lower for kw in ["architecture", "design", "overview", "concept"]):
            return "architecture"
        return "documentation"

    def _extract_tags(self, content: str) -> List[str]:
        """Extract tags from content."""
        # Simple keyword extraction
        keywords = [
            "python", "javascript", "typescript", "java", "go", "rust", "c++",
            "api", "rest", "graphql", "database", "sql", "nosql",
            "docker", "kubernetes", "aws", "gcp", "azure",
            "test", "testing", "pytest", "jest", "ci", "cd",
            "auth", "oauth", "jwt", "security", "encryption",
            "async", "await", "concurrency", "threading", "multiprocessing",
        ]
        content_lower = content.lower()
        return [kw for kw in keywords if kw in content_lower]

    def get_source_quality(self) -> float:
        return 0.85




class GraphTraversalAdapter(KnowledgeSourceAdapter):
    """Adapter for Knowledge Graph Traversal (cross-memory references)."""

    def __init__(
        self,
        cross_memory_references,
        memory_sources: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the graph traversal adapter.

        Args:
            cross_memory_references: CrossMemoryReferences instance
            memory_sources: Dict of memory_type -> memory instance for fetching content
        """
        self.cross_refs = cross_memory_references
        self.memory_sources = memory_sources or {}

    @property
    def source_type(self) -> KnowledgeSourceType:
        return KnowledgeSourceType.KNOWLEDGE_GRAPH

    def is_available(self) -> bool:
        return self.cross_refs is not None and self.cross_refs.graph.get_stats()["nodes"] > 0

    def retrieve_candidates(
        self,
        query: RetrievalQuery,
        max_results: int = 50,
    ) -> List[KnowledgeRetrievalResult]:
        if not self.is_available() or not query.query:
            return []

        try:
            # First, try to find relevant entry points via keyword matching
            entry_points = self._find_entry_points(query.query, max_results)

            if not entry_points:
                return []

            # Traverse graph from entry points
            all_results = []
            visited: Set[str] = set()

            for memory_type, entry_id, initial_score in entry_points:
                full_id = f"{memory_type}:{entry_id}"
                if full_id in visited:
                    continue
                visited.add(full_id)

                # Get the source entry
                source_entry = self._get_entry_content(memory_type, entry_id)
                if source_entry:
                    all_results.append(source_entry)

                # Traverse connected entries up to depth 2
                connected = self.cross_refs.get_connected_entries(
                    memory_type=memory_type,
                    entry_id=entry_id,
                    max_depth=2,
                )

                for ref, node in connected:
                    target_full = f"{node.memory_type}:{node.entry_id}"
                    if target_full in visited:
                        continue
                    visited.add(target_full)

                    # Score decays with distance from entry point
                    distance_score = initial_score / (1 + ref.metadata.get("depth", 1) * 0.3)

                    target_entry = self._get_entry_content(node.memory_type, node.entry_id)
                    if target_entry:
                        target_entry.raw_confidence *= distance_score
                        target_entry.calibrated_confidence *= distance_score
                        all_results.append(target_entry)

            # Sort by score and limit
            all_results.sort(key=lambda r: r.raw_confidence, reverse=True)
            return all_results[:max_results]

        except Exception as e:
            logger.warning(f"Graph traversal retrieval failed: {e}")
            return []

    def _find_entry_points(
        self,
        query: str,
        max_results: int,
    ) -> List[Tuple[str, str, float]]:
        """Find initial entry points by keyword matching node content."""
        entry_points = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for full_id, node in self.cross_refs.graph._nodes.items():
            if not node.title and not node.summary:
                continue

            # Simple keyword matching
            node_text = f"{node.title} {node.summary}".lower()
            node_words = set(node_text.split())
            intersection = query_words & node_words
            if intersection:
                # Score based on Jaccard similarity
                union = query_words | node_words
                similarity = len(intersection) / len(union) if union else 0
                if similarity > 0.05:  # Minimum threshold
                    entry_points.append((node.memory_type, node.entry_id, similarity))

        # Sort by similarity and limit
        entry_points.sort(key=lambda x: x[2], reverse=True)
        return entry_points[:max_results]

    def _get_entry_content(
        self,
        memory_type: str,
        entry_id: str,
    ) -> Optional[KnowledgeRetrievalResult]:
        """Fetch full content for a graph node from its memory source."""
        # Check if we have a direct memory source
        if memory_type in self.memory_sources:
            memory = self.memory_sources[memory_type]
            try:
                result = self._fetch_from_memory(memory, memory_type, entry_id)
                if result is not None:
                    return result
            except Exception:
                pass

        # Fallback: create result from graph node info
        node = self.cross_refs.graph._nodes.get(f"{memory_type}:{entry_id}")
        if node:
            return KnowledgeRetrievalResult(
                content=node.summary or node.title,
                title=node.title or f"{memory_type}:{entry_id}",
                summary=node.summary,
                source_type=self.source_type,
                source_id=entry_id,
                raw_confidence=0.5,
                calibrated_confidence=0.5,
                category=memory_type,
                last_updated=node.timestamp,
                source_metadata={
                    "graph_node": True,
                    "memory_type": memory_type,
                    "metadata": node.metadata,
                },
            )
        return None

    def _fetch_from_memory(
        self,
        memory: Any,
        memory_type: str,
        entry_id: str,
    ) -> Optional[KnowledgeRetrievalResult]:
        """Fetch content from a specific memory instance."""
        # This is a generic fallback - specific memory types would have specific fetch logic
        # For now, return a basic result
        return None

    def get_source_quality(self) -> float:
        return 0.80


# Factory function
def create_adapters_from_agent(agent) -> List[KnowledgeSourceAdapter]:
    """Create all available adapters from a Freya agent."""
    adapters = []

    # Memory adapters
    if hasattr(agent, 'semantic_memory') and agent.semantic_memory:
        adapters.append(SemanticMemoryAdapter(agent.semantic_memory))

    if hasattr(agent, 'episodic_memory') and agent.episodic_memory:
        adapters.append(EpisodicMemoryAdapter(agent.episodic_memory))

    if hasattr(agent, 'memory') and agent.memory:
        adapters.append(ProjectMemoryAdapter(agent.memory))

    if hasattr(agent, 'working_memory') and agent.working_memory:
        adapters.append(WorkingMemoryAdapter(agent.working_memory))

    if hasattr(agent, 'long_term_memory') and agent.long_term_memory:
        adapters.append(LongTermMemoryAdapter(agent.long_term_memory))

    if hasattr(agent, 'experience_memory') and agent.experience_memory:
        adapters.append(ExperienceMemoryAdapter(agent.experience_memory))

    if hasattr(agent, 'engineering_lessons') and agent.engineering_lessons:
        adapters.append(EngineeringLessonsAdapter(agent.engineering_lessons))

    # Vector Search adapter
    if hasattr(agent, 'vector_db') and agent.vector_db:
        from app.vector_db import VectorDB
        if isinstance(agent.vector_db, VectorDB):
            adapters.append(VectorSearchAdapter(agent.vector_db))
        else:
            # Try to get default vector DB
            try:
                from app.vector_db import get_vector_db
                vdb = get_vector_db()
                if vdb and not vdb.is_empty():
                    adapters.append(VectorSearchAdapter(vdb))
            except Exception:
                pass

    # Graph Traversal adapter
    if hasattr(agent, 'cross_memory_references') and agent.cross_memory_references:
        # Collect memory sources for content fetching
        memory_sources = {}
        for attr in ['semantic_memory', 'episodic_memory', 'memory', 'working_memory',
                     'long_term_memory', 'experience_memory', 'engineering_lessons',
                     'goal_storage']:
            if hasattr(agent, attr):
                memory_sources[attr] = getattr(agent, attr)
        adapters.append(GraphTraversalAdapter(
            agent.cross_memory_references,
            memory_sources=memory_sources,
        ))

    return adapters