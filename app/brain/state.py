from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import json
import os
from pathlib import Path

from app.memory.conversation_memory import ConversationMemory


@dataclass
class AgentState:
    goal: str = ""
    plan: list = field(default_factory=list)
    memory: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    current_step: int = 0
    finished: bool = False


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    intent: Optional[str] = None  # Intent type for context-aware follow-up classification

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**data)


class ConversationState:
    """Backward compatible ConversationState that delegates to ConversationMemory.

    This maintains the same interface as the original ConversationState for
    existing code while using the enhanced ConversationMemory internally.
    """

    def __init__(
        self,
        max_history: int = 20,
        persistence_path: Optional[str] = None,
        workspace: str = ".",
    ):
        self.max_history = max_history
        self._persistence_path = persistence_path
        self._last_intent: Optional[str] = None

        # Use ConversationMemory internally with bypass for backward compat
        # Only auto-load if persistence_path is explicitly provided (original behavior)
        storage_path = persistence_path or "data/memory/conversation_memory.json"
        self._memory = ConversationMemory(
            workspace=workspace,
            storage_path=storage_path,
            min_turns=min(20, max_history),
            max_turns=max_history,
            max_characters=16000,
            _bypass_min_turns=True,
            _skip_auto_load=True,
        )

        # Only load from file if persistence_path was explicitly provided
        # (matches original ConversationState behavior)
        if persistence_path and Path(persistence_path).exists():
            self._memory._load()

    def add_message(self, role: str, content: str, intent: Optional[str] = None) -> Message:
        """Add a message to the conversation."""
        turn = self._memory.add_message(role, content)
        if intent:
            self._last_intent = intent
        return Message(role=turn.role, content=turn.content, timestamp=turn.timestamp, intent=intent)

    def get_last_intent(self) -> Optional[str]:
        """Get the intent of the last assistant message, for follow-up classification."""
        return self._last_intent

    def get_history(self) -> list[Message]:
        """Get conversation history as list of Messages."""
        turns = self._memory.get_history()
        return [Message(role=t.role, content=t.content, timestamp=t.timestamp) for t in turns]

    def get_history_text(self, max_characters: int = 8000) -> str:
        """Get formatted conversation history."""
        return self._memory.get_history_text(max_characters=max_characters)

    def clear(self) -> None:
        """Clear all conversation history."""
        self._memory.clear()
        if self._persistence_path and os.path.exists(self._persistence_path):
            os.remove(self._persistence_path)

    def __len__(self) -> int:
        return len(self._memory)

    def is_empty(self) -> bool:
        return self._memory.is_empty()

    def get_last_user_message(self) -> Optional[str]:
        return self._memory.get_last_user_message()

    def get_last_assistant_message(self) -> Optional[str]:
        return self._memory.get_last_assistant_message()

    def to_dict(self) -> list[dict]:
        return self._memory.to_dict() if hasattr(self._memory, 'to_dict') else [t.to_dict() for t in self._memory._turns]

    def save(self, path: Optional[str] = None) -> None:
        """Save conversation to file."""
        save_path = path or self._persistence_path
        if save_path:
            # Temporarily change the memory's storage path and save
            original_path = self._memory.storage_path
            self._memory.storage_path = Path(save_path).resolve()
            try:
                self._memory._save()
            finally:
                self._memory.storage_path = original_path

    def _load(self) -> None:
        # Delegated to ConversationMemory
        pass

    def load(self, path: str) -> None:
        self._persistence_path = path
        self._memory.storage_path = Path(path).resolve()
        self._memory._load()

    @classmethod
    def from_dict(cls, data: list[dict], max_history: int = 20) -> "ConversationState":
        conversation = cls(max_history=max_history)
        # Add messages from data
        for msg_data in data:
            if "role" in msg_data and "content" in msg_data:
                conversation.add_message(msg_data["role"], msg_data["content"])
        return conversation


# Re-export for compatibility
# The ConversationTurn from memory is used internally