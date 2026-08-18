"""
AgentFacade - Public API Protocol for Freya.

Sole public interface; orchestrates internal components.
"""

from typing import Any, Dict, Optional, Protocol
from dataclasses import dataclass


@dataclass
class AgentStatus:
     """Status information for the agent."""
     is_executing: bool
     is_paused: bool
     active_plan_id: Optional[str]
     current_task: Optional[str]
     completed_tasks: int
     total_tasks: int
     chat_active: bool
     uptime_seconds: float


class AgentFacade(Protocol):
     """Public API for Freya agent."""

     def chat(self, user_input: str, context: Optional[Dict[str, Any]] = None) -> str: ...
     def execute_task(self, task: str, allow_mutations: bool = True) -> str: ...
     def get_status(self) -> AgentStatus: ...
     def shutdown(self) -> None: ...
