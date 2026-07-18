from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import json
import os


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
    role: str # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**data)


class ConversationState:
    def __init__(self, max_history: int = 20, persistence_path: Optional[str] = None):
        self.max_history = max_history
        self._messages: list[Message] = []
        self._persistence_path = persistence_path
        if self._persistence_path and os.path.exists(self._persistence_path):
            self._load()

    def add_message(self, role: str, content: str) -> Message:
        message = Message(role=role, content=content)
        self._messages.append(message)
        if len(self._messages) > self.max_history:
            self._messages = self._messages[-self.max_history :]
        return message

    def get_history(self) -> list[Message]:
        return self._messages.copy()

    def get_history_text(self, max_characters: int = 8000) -> str:
        lines = []
        for msg in self._messages:
            role_label = "User" if msg.role == "user" else "Freya"
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)[:max_characters]

    def clear(self) -> None:
        self._messages.clear()
        if self._persistence_path and os.path.exists(self._persistence_path):
            os.remove(self._persistence_path)

    def __len__(self) -> int:
        return len(self._messages)

    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def get_last_user_message(self) -> Optional[str]:
        for msg in reversed(self._messages):
            if msg.role == "user":
                return msg.content
        return None

    def get_last_assistant_message(self) -> Optional[str]:
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg.content
        return None

    def to_dict(self) -> list[dict]:
        return [msg.to_dict() for msg in self._messages]

    def save(self, path: Optional[str] = None) -> None:
        save_path = path or self._persistence_path
        if save_path:
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)

    def _load(self) -> None:
        if self._persistence_path and os.path.exists(self._persistence_path):
            try:
                with open(self._persistence_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._messages = [Message.from_dict(msg) for msg in data]
            except (json.JSONDecodeError, KeyError, TypeError):
                self._messages = []

    def load(self, path: str) -> None:
        self._persistence_path = path
        self._load()

    @classmethod
    def from_dict(cls, data: list[dict], max_history: int = 20) -> "ConversationState":
        conversation = cls(max_history=max_history)
        conversation._messages = [Message.from_dict(msg) for msg in data]
        return conversation
