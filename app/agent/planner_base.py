"""Planner Protocol - Abstract interface for LLM-driven planners.

This protocol defines the contract for planners that generate execution plans
from natural language task descriptions using an LLM.
"""

from __future__ import annotations
from typing import Protocol, Optional, Any, runtime_checkable

from app.planner.plan_manager import Plan, PlanManager


@runtime_checkable
class PlannerProtocol(Protocol):
    """Abstract interface for LLM-driven planners.
    
    Implementations generate execution plans from natural language task
    descriptions, optionally using memory context and engineering lessons
    to inform the planning process.
    """

    def __init__(
        self,
        llm: Any,
        memory: Optional[Any] = None,
        engineering_lessons: Optional[Any] = None,
        plan_manager: Optional[PlanManager] = None,
    ) -> None:
        """Initialize the planner.
        
        Args:
            llm: Language model for generating plans
            memory: Optional memory system for context retrieval
            engineering_lessons: Optional lesson storage for best practices
            plan_manager: Optional PlanManager for plan persistence
        """
        ...

    def create_plan(self, task: str, name: str = "Generated Plan") -> Plan:
        """Create an execution plan from a task description.
        
        Args:
            task: Natural language description of the task
            name: Optional name for the plan
            
        Returns:
            A Plan object with tasks, dependencies, and metadata
        """
        ...


# Re-export for convenience
__all__ = ["PlannerProtocol"]