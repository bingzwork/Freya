"""MemoryManager - Abstract interface for memory operations.

This protocol defines the contract for memory managers, enabling
dependency inversion so components depend on abstractions rather
than concrete implementations.
"""

from __future__ import annotations
from typing import Protocol, Optional, Any, Dict, List, runtime_checkable


@runtime_checkable
class MemoryManager(Protocol):
    """Abstract interface for memory operations.
    
    Implementations provide unified access to all memory subsystems
    (working, task, long-term, episodic, semantic, conversation, etc.)
    through a single facade with transactional writes and cached reads.
    """

    # ------------------------------------------------------------------
    # Single write entry points (transactional)
    # ------------------------------------------------------------------

    def record_conversation(self, turn: Any) -> None:
        """Record a conversation turn."""
        ...

    def record_task_execution(self, task_id: str, result: Any) -> None:
        """Record a task execution result."""
        ...

    def add_fact(self, category: str, key: str, value: str, **meta) -> None:
        """Add a fact to long-term memory."""
        ...

    def add_task(self, task: Any) -> None:
        """Add a task to working memory."""
        ...

    def add_experience(self, exp: Any) -> None:
        """Add an experience entry."""
        ...

    def add_lesson(self, lesson: Any) -> None:
        """Add an engineering lesson."""
        ...

    def add_goal(self, goal: Any) -> None:
        """Add a goal."""
        ...

    # ------------------------------------------------------------------
    # Read access (delegated to unified retrieval where possible)
    # ------------------------------------------------------------------

    def retrieve_for_planning(self, query: str) -> str:
        """Retrieve relevant context for planning."""
        ...

    def retrieve_for_execution(self, query: str) -> str:
        """Retrieve relevant context for execution."""
        ...

    def get_active_goal(self) -> Optional[Any]:
        """Get the currently active goal."""
        ...

    def get_working_memory_snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of working memory state."""
        ...

    # ------------------------------------------------------------------
    # Properties for direct memory access (for advanced use cases)
    # ------------------------------------------------------------------

    @property
    def conversation_memory(self) -> Any:
        """Direct access to conversation memory."""
        ...

    @property
    def working_memory(self) -> Any:
        """Direct access to working memory."""
        ...

    @property
    def goal_storage(self) -> Any:
        """Direct access to goal storage."""
        ...

    @property
    def task_memory(self) -> Any:
        """Direct access to task memory."""
        ...

    @property
    def episodic_memory(self) -> Any:
        """Direct access to episodic memory."""
        ...

    @property
    def long_term_memory(self) -> Any:
        """Direct access to long-term memory."""
        ...

    @property
    def project_memory(self) -> Any:
        """Direct access to project memory."""
        ...

    @property
    def experience_memory(self) -> Any:
        """Direct access to experience memory."""
        ...

    @property
    def engineering_lessons(self) -> Any:
        """Direct access to engineering lessons storage."""
        ...

    @property
    def semantic_memory(self) -> Any:
        """Direct access to semantic memory."""
        ...

    @property
    def unified_retrieval(self) -> Any:
        """Direct access to unified retrieval layer."""
        ...

    @property
    def consolidation_engine(self) -> Any:
        """Direct access to consolidation engine."""
        ...

    @property
    def forgetting_engine(self) -> Any:
        """Direct access to forgetting engine."""
        ...


# Re-export factory function
def create_memory_manager(workspace, event_bus) -> MemoryManager:
    """Factory function for creating a MemoryManager implementation.
    
    This is the canonical way to create a memory manager. The actual
    implementation (MemoryCoordinator) is hidden behind the interface.
    """
    from app.memory.coordinator import create_memory_coordinator
    return create_memory_coordinator(workspace, event_bus)