
"""
MemoryCoordinator - Unified Memory Facade for Freya.

Single write path; transactional; cache invalidation for UnifiedRetrieval.
"""

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

        # Consolidation/Forgetting engines (background)
        self._consolidation = create_consolidation_engine(self)
        self._forgetting = create_forgetting_engine(self)

        logger.info("[MemoryCoordinator] Initialized all memory modules")

    # ------------------------------------------------------------------
    # Single write entry points (transactional)
    # ------------------------------------------------------------------

    def record_conversation(self, turn: Any) -> None:
        """Record a conversation turn."""
        with self._lock:
            self._conversation.add_turn(turn)
            self._event_bus.emit("memory.conversation.updated", {"turn_id": getattr(turn, "id", None)})

    def record_task_execution(self, task_id: str, result: Any) -> None:
        """Record a task execution result."""
        with self._lock:
            self._task.record_result(task_id, result)
            self._episodic.append({
                "type": "task_execution",
                "task_id": task_id,
                "data": result,
            })
            if getattr(result, "lesson", None):
                self._lessons.add(result.lesson)
            self._event_bus.emit("memory.task.completed", {"task_id": task_id})

    def add_fact(self, category: str, key: str, value: str, **meta) -> None:
        """Add a fact to long-term memory."""
        with self._lock:
            self._long_term.add(category, key, value, **meta)

    def add_task(self, task: Any) -> None:
        """Add a task to working memory."""
        with self._lock:
            self._working.add_task(task)

    def add_experience(self, exp: Any) -> None:
        """Add an experience entry."""
        with self._lock:
            self._experience.add(exp)

    def add_lesson(self, lesson: Any) -> None:
        """Add an engineering lesson."""
        with self._lock:
            self._lessons.add(lesson)

    def add_goal(self, goal: Any) -> None:
        """Add a goal."""
        with self._lock:
            self._goals.add(goal)

    # ------------------------------------------------------------------
    # Read access (delegated to unified retrieval where possible)
    # ------------------------------------------------------------------

    def retrieve_for_planning(self, query: str) -> str:
        """Retrieve relevant context for planning."""
        return self._retrieval.retrieve_for_planning(query)

    def retrieve_for_execution(self, query: str) -> str:
        """Retrieve relevant context for execution."""
        return self._retrieval.retrieve_for_execution(query)

    def get_active_goal(self) -> Optional[Any]:
        return self._goals.get_active()

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
    def consolidation_engine(self):
        return self._consolidation

    @property
    def forgetting_engine(self):
        return self._forgetting


def create_memory_coordinator(workspace: Path, event_bus: EventBus) -> MemoryCoordinator:
    """Factory function for MemoryCoordinator."""
    return MemoryCoordinator(workspace, event_bus)
