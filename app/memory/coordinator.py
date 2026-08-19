
"""
MemoryCoordinator - Unified Memory Facade for Freya.

Single write path; transactional; cache invalidation for UnifiedRetrieval.
"""

import re
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.events import EventBus
from app.core.logger import logger

# Memory modules
from app.memory.working_memory import WorkingMemory, get_working_memory
from app.memory.task_memory import TaskMemory, create_task_memory
from app.memory.long_term_memory import LongTermMemory, create_long_term_memory
from app.memory.episodic_memory import EpisodicMemory, create_episodic_memory
from app.memory.semantic_memory import SemanticMemory, create_semantic_memory
from app.memory.project_memory import ProjectMemory
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.goals import GoalStorage
from app.memory.conversation_memory import ConversationMemory
from app.memory.unified_retrieval import UnifiedRetrieval, create_unified_retrieval
from app.memory.cross_references import CrossMemoryReferences

# Phase C: Memory Optimization
from app.memory.consolidation import ConsolidationEngine, create_consolidation_engine
from app.memory.forgetting import ForgettingEngine, create_forgetting_engine


class MemoryCoordinator:
    """
    Unified memory facade - single write path, transactional, cache invalidation.
    """

    def __init__(self, workspace: Path, event_bus: EventBus):
        self._workspace = workspace
        self._event_bus = event_bus
        self._lock = threading.RLock()

        # Initialize all memory modules
        self._working = get_working_memory()
        self._task = create_task_memory(workspace)
        self._long_term = create_long_term_memory(workspace)
        self._episodic = create_episodic_memory(workspace)
        self._semantic = create_semantic_memory(workspace)
        self._project = ProjectMemory(workspace)
        self._experience = ExperienceMemory(workspace)
        self._lessons = EngineeringLessonStorage(workspace)
        self._goals = GoalStorage(workspace)
        self._conversation = ConversationMemory(workspace)

        # Unified retrieval (read-only aggregation)
        self._retrieval = create_unified_retrieval(
            working_memory=self._working,
            task_memory=self._task,
            long_term_memory=self._long_term,
            episodic_memory=self._episodic,
            semantic_memory=self._semantic,
            project_memory=self._project,
            experience_memory=self._experience,
            engineering_lessons=self._lessons,
            goal_memory=self._goals,
            conversation_memory=self._conversation,
        )

        # Cross-memory references share the coordinator's workspace and event bus.
        # Inference is invoked synchronously from canonical writes; this class
        # remains the sole owner of graph serialization.
        self._cross_references = CrossMemoryReferences(
            storage_path=workspace / "data" / "memory" / "cross_references.json",
            event_bus=event_bus,
        )

        # Consolidation/Forgetting engines (background)
        self._consolidation = create_consolidation_engine(self)
        self._forgetting = create_forgetting_engine(self)
        logger.info("[MemoryCoordinator] Initialized all memory modules")

    def _cross_memory_candidates(self, source_memory: str) -> Dict[str, List[tuple[str, str]]]:
        """Build bounded durable candidates for coordinator-triggered inference."""
        candidates: Dict[str, List[tuple[str, str]]] = {}
        if source_memory != "long_term":
            candidates["long_term"] = [
                (
                    entry.entry_id,
                    f"{entry.category} {entry.key} {entry.value} {entry.description}",
                )
                for entry in self._long_term.get_all()[-100:]
            ]
        if source_memory != "episodic":
            candidates["episodic"] = [
                (
                    str(event["event_id"]),
                    " ".join(
                        str(part)
                        for part in (
                            event.get("title", ""),
                            event.get("description", ""),
                            " ".join(event.get("tags", [])),
                        )
                    ),
                )
                for event in self._episodic.export().get("events", [])[-100:]
            ]
        if source_memory != "semantic":
            candidates["semantic"] = [
                (
                    str(entry["entry_id"]),
                    " ".join(
                        str(part)
                        for part in (
                            entry.get("title", ""),
                            entry.get("content", ""),
                            " ".join(entry.get("tags", [])),
                        )
                    ),
                )
                for entry in self._semantic.export().get("entries", [])[-100:]
            ]
        if source_memory != "task":
            candidates["task"] = [
                (
                    str(task.task_id),
                    f"{task.description} {task.status} {task.metadata}",
                )
                for task in self._task.get_task_history(limit=100)
            ]
        return {memory_type: entries for memory_type, entries in candidates.items() if entries}

    def _infer_cross_memory_references(
        self, source_memory: str, source_id: str, source_content: str
    ) -> None:
        """Persist safe inferred links after a canonical durable memory write."""
        normalized_content = source_content.strip()
        if not normalized_content:
            return
        self._cross_references.add_node(
            source_memory, source_id, source_content[:160], normalized_content
        )
        self._cross_references.infer_references_from_content(
            source_memory=source_memory,
            source_id=source_id,
            source_content=normalized_content,
            target_memories=self._cross_memory_candidates(source_memory),
        )

    # ------------------------------------------------------------------
    # Single write entry points (transactional)
    # ------------------------------------------------------------------

    def record_conversation(self, turn: Any) -> None:
        """Persist and index a conversation turn through the canonical write path."""
        role = turn.get("role") if isinstance(turn, dict) else getattr(turn, "role", None)
        content = turn.get("content") if isinstance(turn, dict) else getattr(turn, "content", None)
        shopping_state = turn.get("shopping_state") if isinstance(turn, dict) else getattr(turn, "shopping_state", None)
        if not role or not content:
            raise ValueError("Conversation turns require non-empty role and content")

        with self._lock:
            persisted_turn = self._conversation.add_message(str(role), str(content), shopping_state=shopping_state if isinstance(shopping_state, dict) else {})
            self._infer_cross_memory_references(
                "conversation", persisted_turn.timestamp, persisted_turn.content
            )
            self._event_bus.emit(
                "memory.conversation.updated",
                {"turn_id": persisted_turn.timestamp},
            )

    def record_task_execution(self, task_id: str, result: Any) -> None:
        """Record a task execution result through the durable memory APIs."""
        with self._lock:
            if isinstance(result, dict):
                succeeded = bool(result.get("success", True))
                result_text = str(result.get("data", result))
            else:
                succeeded = bool(getattr(result, "success", True))
                result_text = str(result)

            if self._task.get_task(task_id) is not None:
                if succeeded:
                    self._task.complete_task(task_id)
                else:
                    self._task.fail_task(task_id, result_text)

            event = self._episodic.record(
                event_type="task_completed" if succeeded else "task_failed",
                title=f"Task execution: {task_id}",
                description=result_text,
                outcome="success" if succeeded else "failure",
                task_id=task_id,
            )
            self._infer_cross_memory_references(
                "episodic", event.event_id, f"{event.title} {event.description}"
            )

            lesson = result.get("lesson") if isinstance(result, dict) else getattr(result, "lesson", None)
            if lesson:
                self.add_lesson(lesson)
            self._event_bus.emit(
                "memory.task.completed" if succeeded else "memory.task.failed",
                {"task_id": task_id},
            )

    def add_fact(self, category: str, key: str, value: str, **meta) -> None:
        """Add or update a long-term fact through the canonical write path."""
        with self._lock:
            entry = self._long_term.set(category, key, value, **meta)
            self._infer_cross_memory_references(
                "long_term",
                entry.entry_id,
                f"{entry.category} {entry.key} {entry.value} {entry.description}",
            )

    @staticmethod
    def _normalize_learning_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    @classmethod
    def _equivalent_learning(
        cls, existing_title: str, existing_content: str, title: str, content: str
    ) -> bool:
        """Use conservative deterministic equivalence; similarity alone never crosses titles."""
        if cls._normalize_learning_text(existing_title) != cls._normalize_learning_text(title):
            return False
        existing_tokens = set(cls._normalize_learning_text(existing_content).split())
        incoming_tokens = set(cls._normalize_learning_text(content).split())
        if not existing_tokens or not incoming_tokens:
            return existing_tokens == incoming_tokens
        return len(existing_tokens & incoming_tokens) / len(existing_tokens | incoming_tokens) >= 0.88

    @staticmethod
    def _merge_learning_metadata(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(existing or {})
        merged.update(incoming or {})
        evidence = list((existing or {}).get("evidence_ids", [])) + list(
            (incoming or {}).get("evidence_ids", [])
        )
        merged["evidence_ids"] = list(dict.fromkeys(evidence))
        merged["evidence_count"] = len(merged["evidence_ids"])
        merged["reinforcement_count"] = int((existing or {}).get("reinforcement_count", 0)) + 1
        return merged

    def store_learned(self, learned: Any) -> str:
        """Route one normalized Better Knowledge & Skills result through existing memory stores.

        KNOWLEDGE is upserted into semantic memory, EXPERIENCE is appended or
        reinforced in experience memory, and SKILL is appended or reinforced in
        engineering lessons. All writes remain coordinated, indexed, and emitted
        through this facade.
        """
        item = learned.to_memory_item() if hasattr(learned, "to_memory_item") else dict(learned)
        learning_type = str(item.get("learning_type", "")).lower()
        title = str(item.get("title", "")).strip()
        content = str(item.get("content", "")).strip()
        category = str(item.get("category", "general")).strip() or "general"
        confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        metadata = dict(item.get("metadata") or {})
        metadata["learning_type"] = learning_type
        tags = list(dict.fromkeys(item.get("tags") or []))
        source = str(item.get("source", "learning_pipeline"))
        if not title or not content:
            raise ValueError("Normalized learned items require title and content")

        with self._lock:
            if learning_type == "knowledge":
                existing = self._semantic.get(category, title)
                incoming_is_user_correction = bool(
                    metadata.get("user_correction")
                    or metadata.get("authority") in {"user", "user_correction"}
                    or source.lower() in {"user", "user_input", "user_correction"}
                )
                if existing is not None:
                    metadata = self._merge_learning_metadata(existing.metadata, metadata)
                    if not incoming_is_user_correction and confidence < existing.confidence:
                        metadata["conflict_rejected"] = True
                        metadata["conflict_reason"] = "weaker evidence cannot replace stronger knowledge"
                        entry = self._semantic.set(
                            category=category,
                            title=title,
                            content=existing.content,
                            language=existing.language,
                            tags=existing.tags,
                            confidence=existing.confidence,
                            source=existing.source,
                            examples=existing.examples,
                            related_concepts=existing.related_concepts,
                            prerequisites=existing.prerequisites,
                            metadata=metadata,
                        )
                        return entry.entry_id
                    confidence = min(1.0, max(existing.confidence, confidence) + 0.05)
                entry = self._semantic.set(
                    category=category,
                    title=title,
                    content=content,
                    language=metadata.get("language"),
                    tags=tags,
                    confidence=confidence,
                    source=source,
                    examples=metadata.get("examples"),
                    related_concepts=metadata.get("related_concepts"),
                    prerequisites=metadata.get("prerequisites"),
                    metadata=metadata,
                )
                self._infer_cross_memory_references(
                    "semantic", entry.entry_id, f"{entry.title} {entry.content} {' '.join(entry.tags)}"
                )
                return entry.entry_id

            if learning_type == "experience":
                duplicate = next(
                    (
                        entry for entry in self._experience.all()
                        if entry.category == category and self._equivalent_learning(
                            entry.title, entry.description, title, content
                        )
                    ),
                    None,
                )
                if duplicate is not None:
                    entry = self._experience.reinforce(
                        duplicate.id, confidence=confidence, tags=tags, metadata=metadata
                    )
                    self._infer_cross_memory_references(
                        "experience", entry.id, f"{entry.title} {entry.description} {' '.join(entry.tags)}"
                    )
                    return entry.id
                from app.memory.experience_memory import ExperienceEntry
                entry = self.add_experience(ExperienceEntry(
                    id="",
                    title=title,
                    description=content,
                    category=category,
                    tags=tags,
                    outcome=str(metadata.get("outcome", "neutral")),
                    confidence=confidence,
                    metadata=metadata,
                    source=source,
                ))
                return entry.id

            if learning_type == "skill":
                duplicate = next(
                    (
                        lesson for lesson in self._lessons.all()
                        if lesson.context.get("learning_type") == "skill"
                        and self._equivalent_learning(lesson.title, lesson.description, title, content)
                    ),
                    None,
                )
                if duplicate is not None:
                    lesson = self._lessons.reinforce(
                        duplicate.id,
                        confidence=confidence,
                        tags=tags,
                        context=metadata,
                        rationale="Reinforced by additional validated learning evidence",
                    )
                    self._infer_cross_memory_references(
                        "lessons", lesson.id, f"{lesson.title} {lesson.description} {' '.join(lesson.tags)}"
                    )
                    return lesson.id
                from app.memory.engineering_lessons import EngineeringLesson, LessonSeverity, LessonType
                lesson = self.add_lesson(EngineeringLesson(
                    id="",
                    title=title,
                    description=content,
                    lesson_type=LessonType.PATTERN.value,
                    category=category,
                    severity=LessonSeverity.RECOMMENDED.value,
                    tags=tags,
                    context=metadata,
                    rationale="Reusable strategy distilled from validated learning evidence",
                    confidence=confidence,
                ))
                return lesson.id

        raise ValueError(f"Unsupported learned item type: {learning_type}")

    def add_task(self, task: Any) -> None:
        """Add a task to working memory."""
        with self._lock:
            self._working.add_task(task)

    def add_experience(self, exp: Any) -> None:
        """Persist an experience entry through the ExperienceMemory write contract."""
        with self._lock:
            entry = self._experience.store(
                title=exp.title,
                description=exp.description,
                category=exp.category,
                tags=exp.tags,
                outcome=exp.outcome,
                confidence=exp.confidence,
                metadata=exp.metadata,
                code_snippet=exp.code_snippet,
                source=exp.source,
            )
            self._infer_cross_memory_references(
                "experience", entry.id, f"{entry.title} {entry.description} {' '.join(entry.tags)}"
            )
            return entry

    def add_lesson(self, lesson: Any) -> None:
        """Add an engineering lesson through its durable storage contract."""
        with self._lock:
            stored = self._lessons.store(
                title=lesson.title,
                description=lesson.description,
                lesson_type=lesson.lesson_type,
                category=lesson.category,
                severity=lesson.severity,
                tags=lesson.tags,
                examples=lesson.examples,
                related_ids=lesson.related_ids,
                context=lesson.context,
                rationale=lesson.rationale,
                confidence=lesson.confidence,
                code_example=getattr(lesson, "code_example", None),
            )
            self._infer_cross_memory_references(
                "lessons", stored.id, f"{stored.title} {stored.description} {' '.join(stored.tags)}"
            )
            return stored

    def add_goal(self, goal: Any) -> None:
        """Add a goal through the durable goal-storage contract."""
        with self._lock:
            stored = self._goals.create(
                name=goal.name,
                description=goal.description,
                status=goal.status,
                priority=goal.priority,
                parent_goal_id=getattr(goal, "parent_goal_id", None),
                child_goal_ids=getattr(goal, "child_goal_ids", None),
                depends_on_ids=getattr(goal, "depends_on_ids", None),
            )
            self._infer_cross_memory_references(
                "goals", stored.id, f"{stored.name} {stored.description}"
            )

    # ------------------------------------------------------------------
    # Read access (delegated to unified retrieval where possible)
    # ------------------------------------------------------------------
    def get_status_snapshot(self) -> Dict[str, Any]:
        """Return safe operational memory metadata for status surfaces.

        Counts and readiness flags are exposed; conversation content, records,
        embeddings, and private summaries remain behind the existing memory APIs.
        """
        with self._lock:
            working = self._working.get_summary()
            try:
                conversation_items = len(self._conversation.get_history(limit=50))
            except Exception:
                conversation_items = None
            active_items = None
            if isinstance(working, dict):
                active_items = (
                    int(working.get("tool_outputs_count") or 0)
                    + int(working.get("file_references_count") or 0)
                    + int(working.get("task_state_keys") and len(working.get("task_state_keys")) or 0)
                    + int(working.get("plan_steps") or 0)
                ) if working.get("active") else 0
            return {
                "memory_system_ready": True,
                "working_memory_active": bool(working.get("active")) if isinstance(working, dict) else False,
                "working_memory_active_items": active_items,
                "conversation_context_items": conversation_items,
                "long_term_memory_available": self._long_term is not None,
                "knowledge_store_available": self._semantic is not None,
                "retrieval_status": "ready" if self._retrieval is not None else "unavailable",
                "recent_retrieval_count": None,
                "recent_storage_count": None,
                "last_memory_activity_at": None,
                "learning_pipeline_ready": None,
                "pending_learning_count": None,
                "accepted_learning_count": None,
                "rejected_learning_count": None,
                "last_learning_activity_at": None,
            }

    def retrieve_for_planning(self, query: str) -> str:
        """Retrieve relevant context for planning."""
        return self._retrieval.retrieve_for_planner(query)

    def retrieve_for_execution(self, query: str) -> str:
        """Retrieve relevant context for execution."""
        return self._retrieval.retrieve_for_execution(query)

    def get_conversation_context(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Return bounded recent conversation through the coordinator boundary."""
        history = self._conversation.get_history(limit=max(1, limit))
        return [
            {
                "role": turn.role,
                "content": turn.content,
                "timestamp": turn.timestamp,
                "shopping_state": dict(getattr(turn, "shopping_state", {}) or {}),
            }
            for turn in history
        ]

    def get_active_goal(self) -> Optional[Any]:
        return self._goals.active_goal()

    def get_working_memory_snapshot(self) -> Dict[str, Any]:
        return self._working.get_snapshot()

    # ------------------------------------------------------------------
    # Properties for direct memory access (for advanced use cases)
    # ------------------------------------------------------------------

    @property
    def conversation_memory(self):
        return self._conversation

    @property
    def working_memory(self):
        return self._working

    @property
    def goal_storage(self):
        return self._goals

    @property
    def task_memory(self):
        return self._task

    @property
    def episodic_memory(self):
        return self._episodic

    @property
    def long_term_memory(self):
        return self._long_term

    @property
    def project_memory(self):
        return self._project

    @property
    def experience_memory(self):
        return self._experience

    @property
    def engineering_lessons(self):
        return self._lessons

    @property
    def semantic_memory(self):
        return self._semantic

    @property
    def unified_retrieval(self):
        return self._retrieval

    @property
    def cross_memory_references(self):
        return self._cross_references

    @property
    def consolidation_engine(self):
        return self._consolidation

    @property
    def forgetting_engine(self):
        return self._forgetting


def create_memory_coordinator(workspace: Path, event_bus: EventBus) -> MemoryCoordinator:
    """Factory function for MemoryCoordinator."""
    return MemoryCoordinator(workspace, event_bus)
