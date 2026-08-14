"""Unified Retrieval Layer for Freya AI.

This module provides a single retrieval interface that queries all available
memory systems and returns merged, relevance-ranked results.

Retrieves from:
- Conversation Memory
- Working Memory
- Project Memory
- Experience Memory
- Engineering Lessons
- Goal Memory
- Knowledge Base (if available)

Features:
- Relevance ranking across memory types
- Merged results in single ordered list
- Graceful degradation when memory modules unavailable
- Backward compatibility with existing memory APIs
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Callable, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.project_memory import ProjectMemory
    from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
    from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
    from app.memory.goals import GoalStorage, Goal
    from app.memory.conversation_memory import ConversationMemory, ConversationTurn
    from app.memory.working_memory import WorkingMemory
    from app.intelligence.knowledge_base import KnowledgeBase
    from app.memory.task_memory import TaskMemory, TaskState
    from app.memory.long_term_memory import LongTermMemory, LongTermEntry
    from app.memory.episodic_memory import EpisodicMemory, EpisodicEvent
    from app.memory.semantic_memory import SemanticMemory, SemanticEntry


logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """A single result from unified retrieval."""
    content: str
    source: str  # Memory source: "conversation", "working", "project", "experience", "lessons", "goals", "knowledge"
    source_id: str  # Unique identifier within source
    score: float  # Relevance score (0.0 to 1.0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None  # Original timestamp if available

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "source_id": self.source_id,
            "score": self.score,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class RetrievalQuery:
    """Query for unified retrieval."""
    query: str
    context: Optional[Dict[str, Any]] = None  # e.g., {"task_type": "debug", "phase": "planning"}
    max_results: int = 20
    min_score: float = 0.1
    sources: Optional[List[str]] = None  # Specific sources to search (None = all)
    boost_recent: bool = True
    boost_category: Optional[str] = None  # Boost results matching this category


class MemoryRetriever(ABC):
    """Abstract base class for memory-specific retrievers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source name for this retriever."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this memory source is available."""
        pass

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        """Retrieve results for the given query."""
        pass


class ConversationMemoryRetriever(MemoryRetriever):
    """Retriever for Conversation Memory."""

    def __init__(self, memory: "ConversationMemory"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "conversation"

    def is_available(self) -> bool:
        # A fresh session can have no local turns while the shared persistent
        # vector store contains earlier conversations. Availability therefore
        # follows the configured memory backend, not this instance's history.
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        """Retrieve persisted semantic conversation matches through the canonical contract."""
        if not self.is_available() or not query.query.strip():
            return []

        try:
            matches = self.memory.search_conversations(
                query.query,
                max_results=query.max_results,
                min_similarity=max(0.0, query.min_score),
            )
        except Exception as exc:
            logger.warning("Conversation retrieval failed: %s", exc)
            return []

        results: List[RetrievalResult] = []
        for match in matches:
            content = str(match.get("content", ""))
            if not content:
                continue
            metadata = dict(match.get("metadata", {}))
            metadata.update({
                "type": match.get("type", "conversation_turn"),
                "role": match.get("role", ""),
                "similarity": float(match.get("similarity", 0.0)),
            })
            results.append(RetrievalResult(
                content=content,
                source=self.source_name,
                source_id=str(match.get("id", "")),
                score=float(match.get("similarity", 0.0)),
                metadata=metadata,
                timestamp=match.get("timestamp") or None,
            ))
        return results


class WorkingMemoryRetriever(MemoryRetriever):
    """Retriever for Working Memory."""

    def __init__(self, memory: "WorkingMemory"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "working"

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.is_active

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        results = []

        # Get current plan
        plan = self.memory.get_plan()
        if plan:
            # Plan description
            results.append(RetrievalResult(
                content=f"Current Plan: {plan.description}",
                source=self.source_name,
                source_id=plan.plan_id,
                score=0.9,
                metadata={"type": "plan", "steps_count": len(plan.steps)},
                timestamp=plan.created_at,
            ))
            # Current step
            if plan.current_step_index < len(plan.steps):
                step = plan.steps[plan.current_step_index]
                results.append(RetrievalResult(
                    content=f"Current Step: {step.get('title', step.get('description', str(step)))}",
                    source=self.source_name,
                    source_id=f"{plan.plan_id}_current",
                    score=0.85,
                    metadata={"type": "current_step", "step_index": plan.current_step_index},
                ))

        # Recent tool outputs
        tool_outputs = self.memory.get_recent_tool_outputs(limit=5)
        for i, output in enumerate(tool_outputs):
            score = 0.7 - (i * 0.1)
            content = f"Tool: {output.tool_name}({output.arguments}) -> {str(output.result)[:300]}"
            if not output.success:
                content += f" [ERROR: {output.error}]"
            results.append(RetrievalResult(
                content=content,
                source=self.source_name,
                source_id=f"tool_{output.tool_name}_{i}",
                score=score,
                metadata={
                    "type": "tool_output",
                    "tool": output.tool_name,
                    "success": output.success,
                },
                timestamp=output.timestamp,
            ))

        # Recent reasoning
        reasoning = self.memory.get_reasoning_steps(limit=3)
        for i, step in enumerate(reasoning):
            results.append(RetrievalResult(
                content=f"Reasoning [{step.step_type}]: {step.content}",
                source=self.source_name,
                source_id=f"reasoning_{step.step_type}_{i}",
                score=0.6 - (i * 0.1),
                metadata={"type": "reasoning", "step_type": step.step_type},
                timestamp=step.timestamp,
            ))

        # File references
        file_refs = self.memory.get_file_references()
        if file_refs:
            ref_list = "\n".join(f"  {fp}" for fp in list(file_refs.keys())[-10:])
            results.append(RetrievalResult(
                content=f"Referenced Files:\n{ref_list}",
                source=self.source_name,
                source_id="file_refs",
                score=0.5,
                metadata={"type": "file_references", "count": len(file_refs)},
            ))

        return results


class ProjectMemoryRetriever(MemoryRetriever):
    """Retriever for Project Memory."""

    def __init__(self, memory: "ProjectMemory"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "project"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        results = []

        # Use semantic search if available (via similar_search)
        if hasattr(self.memory, 'similar_search') and callable(self.memory.similar_search):
            similar = self.memory.similar_search(query.query, limit=query.max_results)
            for entry in similar:
                score = entry.get("_similarity_score", 0.5)
                if score >= query.min_score:
                    kind = entry.get("kind", "unknown")
                    content = f"[{kind}] {entry.get('content', {})}"
                    results.append(RetrievalResult(
                        content=content,
                        source=self.source_name,
                        source_id=entry.get("timestamp", ""),
                        score=score,
                        metadata={"kind": kind, "content": entry.get("content", {})},
                        timestamp=entry.get("timestamp"),
                    ))
        else:
            # Fallback to keyword search
            keyword_results = self.memory.search(query.query, limit=query.max_results)
            for entry in keyword_results:
                kind = entry.get("kind", "unknown")
                content = f"[{kind}] {entry.get('content', {})}"
                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=entry.get("timestamp", ""),
                    score=0.5,
                    metadata={"kind": kind, "content": entry.get("content", {})},
                    timestamp=entry.get("timestamp"),
                ))

        return results


class ExperienceMemoryRetriever(MemoryRetriever):
    """Retriever for Experience Memory."""

    def __init__(self, memory: "ExperienceMemory"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "experience"

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.count() > 0

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        results = []
        category = query.boost_category or query.context.get("category") if query.context else None

        entries = self.memory.search(
            keyword=query.query if query.query else None,
            category=category,
            limit=query.max_results,
        )

        for entry in entries:
            score = 0.6
            if entry.outcome == "positive":
                score = 0.7
            elif entry.outcome == "negative":
                score = 0.5
            score *= entry.confidence

            # Boost recent
            if query.boost_recent:
                score += 0.1

            if score >= query.min_score:
                content = f"Experience [{entry.category}] {entry.title}: {entry.description}"
                if entry.outcome != "neutral":
                    content += f" (outcome: {entry.outcome})"
                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=entry.id,
                    score=min(score, 1.0),
                    metadata={
                        "category": entry.category,
                        "tags": entry.tags,
                        "outcome": entry.outcome,
                        "confidence": entry.confidence,
                    },
                    timestamp=entry.timestamp,
                ))

        return results


class EngineeringLessonsRetriever(MemoryRetriever):
    """Retriever for Engineering Lessons."""

    def __init__(self, memory: "EngineeringLessonStorage"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "lessons"

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.count() > 0

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        results = []
        category = query.boost_category or query.context.get("category") if query.context else None

        # Search for patterns (positive lessons) by default
        lessons = self.memory.search(
            keyword=query.query if query.query else None,
            category=category,
            limit=query.max_results,
        )

        severity_rank = {"critical": 1.0, "important": 0.8, "recommended": 0.6, "info": 0.4}

        for lesson in lessons:
            score = severity_rank.get(lesson.severity, 0.5)
            if lesson.lesson_type == "anti_pattern":
                score *= 0.8  # Slightly lower for anti-patterns unless specifically looking for failures

            if query.boost_recent:
                score += 0.1

            if score >= query.min_score:
                content = f"Lesson [{lesson.lesson_type}/{lesson.severity}] {lesson.title}: {lesson.description}"
                if lesson.rationale:
                    content += f" Rationale: {lesson.rationale}"
                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=lesson.id,
                    score=min(score, 1.0),
                    metadata={
                        "lesson_type": lesson.lesson_type,
                        "category": lesson.category,
                        "severity": lesson.severity,
                        "tags": lesson.tags,
                        "rationale": lesson.rationale,
                    },
                    timestamp=lesson.timestamp,
                ))

        return results


class GoalMemoryRetriever(MemoryRetriever):
    """Retriever for Goal Memory."""

    def __init__(self, memory: "GoalStorage"):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "goals"

    def is_available(self) -> bool:
        return self.memory is not None and self.memory.count() > 0

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        results = []

        # Active goal takes priority
        active = self.memory.active_goal()
        if active:
            progress = self.memory.progress(active.id)
            results.append(RetrievalResult(
                content=f"Active Goal: {active.name} - {active.description}",
                source=self.source_name,
                source_id=active.id,
                score=0.9,
                metadata={
                    "type": "active_goal",
                    "progress": progress,
                    "status": active.status,
                },
                timestamp=active.updated_at,
            ))

        # Upcoming queue
        queue = self.memory.queue()
        for i, goal in enumerate(queue[:5]):
            score = 0.7 - (i * 0.1)
            results.append(RetrievalResult(
                content=f"Queued Goal: {goal.name} - {goal.description} (priority: {goal.priority})",
                source=self.source_name,
                source_id=goal.id,
                score=score,
                metadata={"type": "queued_goal", "priority": goal.priority, "status": goal.status},
                timestamp=goal.updated_at,
            ))

        # Stalled goals (if context suggests review)
        if query.context and query.context.get("review_stalled"):
            stalled = self.memory.list_stalled()
            for goal in stalled[:3]:
                results.append(RetrievalResult(
                    content=f"Stalled Goal: {goal.name} - {goal.description}",
                    source=self.source_name,
                    source_id=goal.id,
                    score=0.5,
                    metadata={"type": "stalled_goal", "status": goal.status},
                    timestamp=goal.updated_at,
                ))

        return results


class KnowledgeBaseRetriever(MemoryRetriever):
    """Retriever for Knowledge Base (if available)."""

    def __init__(self, memory: Optional["KnowledgeBase"] = None):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "knowledge"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = self.memory.search(query.query, limit=query.max_results)
            retrieval_results = []
            for i, result in enumerate(results):
                score = 0.7 - (i * 0.05)
                retrieval_results.append(RetrievalResult(
                    content=result.get("content", str(result)),
                    source=self.source_name,
                    source_id=result.get("id", f"kb_{i}"),
                    score=score,
                    metadata={"type": "knowledge_base", "source_info": result.get("metadata", {})},
                ))
            return retrieval_results
        except Exception as e:
            logger.warning(f"Knowledge base retrieval failed: {e}")
            return []


class TaskMemoryRetriever(MemoryRetriever):
    """Retriever for Task Memory."""

    def __init__(self, memory: Optional["TaskMemory"] = None):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "task"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = []
            # Get active task
            active_task = self.memory.get_active_task()
            if active_task:
                progress = active_task.get_progress()
                content = f"Active Task: {active_task.description}\nProgress: {progress['completed']}/{progress['total']} completed ({progress['percentage']:.1f}%)"
                if progress['blocked'] > 0:
                    content += f"\nBlocked: {progress['blocked']}"
                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=f"active_{active_task.task_id}",
                    score=0.9,
                    metadata={"type": "active_task", "status": active_task.status, "progress": progress},
                    timestamp=active_task.updated_at,
                ))

            # Get recent tasks
            recent_tasks = self.memory.get_task_history(limit=5)
            for task in recent_tasks:
                if task == active_task:
                    continue
                progress = task.get_progress()
                content = f"Task: {task.description}\nStatus: {task.status}\nProgress: {progress['completed']}/{progress['total']} ({progress['percentage']:.1f}%)"
                score = 0.6 if task.status == "active" else 0.4
                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=task.task_id,
                    score=score,
                    metadata={"type": "task", "status": task.status, "progress": progress},
                    timestamp=task.updated_at,
                ))

            return results[:query.max_results]
        except Exception as e:
            logger.warning(f"Task memory retrieval failed: {e}")
            return []


class LongTermMemoryRetriever(MemoryRetriever):
    """Retriever for Long-Term Memory."""

    def __init__(self, memory: Optional["LongTermMemory"] = None):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "long_term"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = []
            category = query.boost_category or query.context.get("category") if query.context else None

            entries = self.memory.search(
                query=query.query if query.query else None,
                category=category,
                min_confidence=0.3,
                limit=query.max_results,
            )

            for entry in entries:
                score = entry.confidence
                if entry.source == "user":
                    score = min(score + 0.2, 1.0)  # Boost user-stated preferences

                content = f"Long-Term [{entry.category}] {entry.key}: {entry.value}"
                if entry.description:
                    content += f" â€” {entry.description}"

                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=f"{entry.category}.{entry.key}",
                    score=score,
                    metadata={
                        "category": entry.category,
                        "key": entry.key,
                        "value": entry.value,
                        "confidence": entry.confidence,
                        "source": entry.source,
                        "tags": entry.tags,
                    },
                    timestamp=entry.updated_at,
                ))

            return results[:query.max_results]
        except Exception as e:
            logger.warning(f"Long-term memory retrieval failed: {e}")
            return []


class EpisodicMemoryRetriever(MemoryRetriever):
    """Retriever for Episodic Memory."""

    def __init__(self, memory: Optional["EpisodicMemory"] = None):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "episodic"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = []

            # Use search with time filter for recent events
            days = query.context.get("days", 7) if query.context else 7
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

            for event in events[:query.max_results]:
                # Score based on recency and outcome
                score = 0.5
                if event.outcome == "success":
                    score = 0.7
                elif event.outcome == "failure":
                    score = 0.6

                # Boost recent
                if query.boost_recent:
                    score += 0.1

                content = f"Event [{event.event_type}] {event.title}"
                if event.description:
                    content += f": {event.description}"
                if event.outcome != "neutral":
                    content += f" (outcome: {event.outcome})"
                if event.tags:
                    content += f" [tags: {', '.join(event.tags)}]"

                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=event.event_id,
                    score=min(score, 1.0),
                    metadata={
                        "event_type": event.event_type,
                        "outcome": event.outcome,
                        "tags": event.tags,
                        "task_id": event.task_id,
                        "file_paths": event.file_paths,
                    },
                    timestamp=event.timestamp,
                ))

            return results
        except Exception as e:
            logger.warning(f"Episodic memory retrieval failed: {e}")
            return []


class SemanticMemoryRetriever(MemoryRetriever):
    """Retriever for Semantic Memory."""

    def __init__(self, memory: Optional["SemanticMemory"] = None):
        self.memory = memory

    @property
    def source_name(self) -> str:
        return "semantic"

    def is_available(self) -> bool:
        return self.memory is not None

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalResult]:
        if not self.is_available():
            return []

        try:
            results = []
            # Search semantic memory
            entries = self.memory.search(
                query=query.query if query.query else None,
                category=None,
                language=query.context.get("language") if query.context else None,
                tags=None,
                min_confidence=0.5,
                limit=query.max_results,
            )

            for entry in entries:
                # Higher confidence = higher score
                score = min(0.5 + entry.confidence * 0.5, 1.0)

                content = f"[{entry.category}] {entry.title}: {entry.content[:300]}"
                if entry.language:
                    content += f" (language: {entry.language})"
                if entry.examples:
                    content += f"\nExample: {entry.examples[0].get('code', '')[:100]}"

                results.append(RetrievalResult(
                    content=content,
                    source=self.source_name,
                    source_id=entry.entry_id,
                    score=score,
                    metadata={
                        "category": entry.category,
                        "language": entry.language,
                        "tags": entry.tags,
                        "confidence": entry.confidence,
                        "source": entry.source,
                        "examples_count": len(entry.examples),
                    },
                    timestamp=entry.updated_at,
                ))

            return results[:query.max_results]
        except Exception as e:
            logger.warning(f"Semantic memory retrieval failed: {e}")
            return []


class UnifiedRetrieval:
    """Unified retrieval layer for all memory systems.

    Provides a single entry point to query all available memory modules,
    with relevance ranking and merged results.
    """

    def __init__(
        self,
        conversation_memory: Optional["ConversationMemory"] = None,
        working_memory: Optional["WorkingMemory"] = None,
        project_memory: Optional["ProjectMemory"] = None,
        experience_memory: Optional["ExperienceMemory"] = None,
        engineering_lessons: Optional["EngineeringLessonStorage"] = None,
        goal_memory: Optional["GoalStorage"] = None,
        knowledge_base: Optional["KnowledgeBase"] = None,
        task_memory: Optional["TaskMemory"] = None,
        long_term_memory: Optional["LongTermMemory"] = None,
        episodic_memory: Optional["EpisodicMemory"] = None,
        semantic_memory: Optional["SemanticMemory"] = None,
    ):
        """Initialize the unified retrieval layer.

        All memory modules are optional - the layer gracefully handles unavailable modules.
        """
        self._retrievers: List[MemoryRetriever] = []

        # Add retrievers in priority order (higher priority = added first)
        if conversation_memory is not None:
            self._retrievers.append(ConversationMemoryRetriever(conversation_memory))
        if working_memory is not None:
            self._retrievers.append(WorkingMemoryRetriever(working_memory))
        if project_memory is not None:
            self._retrievers.append(ProjectMemoryRetriever(project_memory))
        if experience_memory is not None:
            self._retrievers.append(ExperienceMemoryRetriever(experience_memory))
        if engineering_lessons is not None:
            self._retrievers.append(EngineeringLessonsRetriever(engineering_lessons))
        if goal_memory is not None:
            self._retrievers.append(GoalMemoryRetriever(goal_memory))
        if knowledge_base is not None:
            self._retrievers.append(KnowledgeBaseRetriever(knowledge_base))
        # Phase B: Extended Memory
        if task_memory is not None:
            self._retrievers.append(TaskMemoryRetriever(task_memory))
        if long_term_memory is not None:
            self._retrievers.append(LongTermMemoryRetriever(long_term_memory))
        if episodic_memory is not None:
            self._retrievers.append(EpisodicMemoryRetriever(episodic_memory))
        if semantic_memory is not None:
            self._retrievers.append(SemanticMemoryRetriever(semantic_memory))

        self._default_max_results = 20
        self._default_min_score = 0.1

    def add_retriever(self, retriever: MemoryRetriever) -> None:
        """Add a custom memory retriever."""
        self._retrievers.append(retriever)

    def retrieve(self, query: Union[str, RetrievalQuery]) -> List[RetrievalResult]:
        """Retrieve merged, ranked results from all available memory sources.

        Args:
            query: Either a query string or a RetrievalQuery object

        Returns:
            List of RetrievalResult objects, sorted by relevance score (descending)
        """
        if isinstance(query, str):
            query = RetrievalQuery(query=query)

        all_results: List[RetrievalResult] = []

        # Query each available retriever
        for retriever in self._retrievers:
            if not retriever.is_available():
                continue

            try:
                # Filter by requested sources if specified
                if query.sources and retriever.source_name not in query.sources:
                    continue

                results = retriever.retrieve(query)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Retriever {retriever.source_name} failed: {e}")
                continue

        # Deduplicate by content similarity (simple approach)
        all_results = self._deduplicate(all_results)

        # Sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)

        # Apply limits
        max_results = query.max_results or self._default_max_results
        min_score = query.min_score if query.min_score is not None else self._default_min_score

        filtered = [r for r in all_results if r.score >= min_score]
        return filtered[:max_results]

    def _deduplicate(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """Remove near-duplicate results based on content similarity."""
        if len(results) <= 1:
            return results

        unique = []
        seen_content = set()

        for result in results:
            # Simple deduplication: hash first 200 chars
            content_hash = hash(result.content[:200])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique.append(result)

        return unique

    def retrieve_for_planner(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Retrieve and format context specifically for the planner.

        Returns a formatted string suitable for injection into planner prompts.
        """
        query = RetrievalQuery(
            query=task,
            context=context or {},
            max_results=15,
            min_score=0.2,
            boost_category=context.get("category") if context else None,
        )

        results = self.retrieve(query)

        if not results:
            return ""

        # Group by source
        by_source: Dict[str, List[RetrievalResult]] = {}
        for r in results:
            by_source.setdefault(r.source, []).append(r)

        # Build formatted context
        sections = []

        source_labels = {
            "conversation": "Recent Conversation",
            "working": "Working Memory (Current Execution)",
            "project": "Project Memory",
            "experience": "Past Experiences",
            "lessons": "Engineering Lessons",
            "goals": "Active/Queued Goals",
            "knowledge": "Knowledge Base",
            "task": "Task Memory",
            "long_term": "Long-Term Memory",
            "episodic": "Episodic Memory",
            "semantic": "Semantic Memory",
        }

        for source, src_results in by_source.items():
            label = source_labels.get(source, source.capitalize())
            section_lines = [f"=== {label} ==="]
            for r in src_results[:5]:  # Top 5 per source
                section_lines.append(f"- {r.content}")
            sections.append("\n".join(section_lines))

        return "\n\n".join(sections)

    def retrieve_for_execution(self, task: str) -> str:
        """Retrieve context specifically for execution phase.

        Focuses on working memory, recent conversation, and relevant lessons.
        """
        query = RetrievalQuery(
            query=task,
            context={"phase": "execution"},
            max_results=15,
            min_score=0.2,
            sources=["working", "conversation", "lessons", "project"],
        )

        results = self.retrieve(query)

        if not results:
            return ""

        sections = []
        for r in results:
            if r.source == "working":
                sections.append(r.content)

        if len(sections) == 0:
            for r in results:
                if r.source == "conversation":
                    sections.append(r.content[:500])
                    break

        return "\n\n".join(sections)

    def get_available_sources(self) -> List[str]:
        """Get list of available memory source names."""
        return [r.source_name for r in self._retrievers if r.is_available()]


# Convenience function to create unified retrieval from FreyaAgent or memory modules
def create_unified_retrieval(
    agent=None,
    *,
    conversation_memory=None,
    working_memory=None,
    project_memory=None,
    experience_memory=None,
    engineering_lessons=None,
    goal_memory=None,
    knowledge_base=None,
    task_memory=None,
    long_term_memory=None,
    episodic_memory=None,
    semantic_memory=None,
) -> UnifiedRetrieval:
    """Create a UnifiedRetrieval instance from a FreyaAgent or individual memory modules.

    Can be called in two ways:
    1. create_unified_retrieval(agent) - automatically detects memory modules from agent
    2. create_unified_retrieval(working_memory=..., task_memory=..., ...) - explicit keyword args

    All memory modules are optional.
    """
    # If agent is provided, extract memory modules from it
    if agent is not None:
        if any(arg is not None for arg in [conversation_memory, working_memory, project_memory,
                                            experience_memory, engineering_lessons, goal_memory,
                                            knowledge_base, task_memory, long_term_memory,
                                            episodic_memory, semantic_memory]):
            raise ValueError("Cannot specify both agent and individual memory modules")
        return UnifiedRetrieval(
            conversation_memory=getattr(
                getattr(agent, 'conversation', None),
                '_memory',
                getattr(agent, 'conversation', None),
            ),
            working_memory=getattr(agent, 'working_memory', None),
            project_memory=getattr(agent, 'memory', None),
            experience_memory=getattr(agent, 'experience_memory', None),
            engineering_lessons=getattr(agent, 'engineering_lessons', None),
            goal_memory=getattr(agent, 'goal_storage', None),
            knowledge_base=getattr(agent, 'knowledge_base', None),
            # Phase B: Extended Memory
            task_memory=getattr(agent, 'task_memory', None),
            long_term_memory=getattr(agent, 'long_term_memory', None),
            episodic_memory=getattr(agent, 'episodic_memory', None),
            semantic_memory=getattr(agent, 'semantic_memory', None),
        )

    # Otherwise use explicitly provided keyword arguments
    return UnifiedRetrieval(
        conversation_memory=conversation_memory,
        working_memory=working_memory,
        project_memory=project_memory,
        experience_memory=experience_memory,
        engineering_lessons=engineering_lessons,
        goal_memory=goal_memory,
        knowledge_base=knowledge_base,
        task_memory=task_memory,
        long_term_memory=long_term_memory,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
    )
