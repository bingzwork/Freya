"""Conversation Memory for Freya AI.

This module provides the working conversation memory that stores the current
user/assistant dialogue with automatic context windowing (minimum 20 turns).
It supports reference resolution for recent entities like "it", "that file",
"the previous function", etc.

Integrates with the agent's prompt construction to provide relevant conversation
context without unnecessary token growth.
"""

import json
import re
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


@dataclass
class ConversationTurn:
    """A single turn in the conversation (user or assistant message)."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entities: Dict[str, str] = field(default_factory=dict)  # Extracted entities for reference resolution

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Create from dictionary."""
        return cls(**data)


class ConversationMemory:
    """Stores conversation history with automatic context windowing.

    Features:
    - Minimum 20 turns retained (rolling window)
    - Automatic entity extraction for reference resolution
    - Reference resolution: "it", "that file", "the previous function", etc.
    - Integration with agent prompt construction
    - Token-aware trimming to avoid unnecessary growth
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/conversation_memory.json",
        min_turns: int = 20,
        max_turns: int = 50,
        max_characters: int = 16000,
        _bypass_min_turns: bool = False,  # Internal: allow <20 for backward compatibility
        _skip_auto_load: bool = False,  # Internal: skip automatic loading from disk
    ):
        """Initialize Conversation Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            min_turns: Minimum turns to retain (rolling window floor)
            max_turns: Maximum turns to retain (rolling window ceiling)
            max_characters: Maximum characters in context window
            _bypass_min_turns: (Internal) Skip minimum 20 turns enforcement for backward compat
            _skip_auto_load: (Internal) Skip automatic loading from disk for testing
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        if _bypass_min_turns:
            self.min_turns = min_turns
        else:
            self.min_turns = max(20, min_turns)  # Enforce minimum 20
        self.max_turns = max(max_turns, self.min_turns)
        self.max_characters = max_characters
        self._lock = threading.RLock()
        self._turns: List[ConversationTurn] = []
        self._entity_index: Dict[str, List[Tuple[int, str]]] = {}  # entity -> [(turn_index, entity_value)]
        if not _skip_auto_load:
            self._load()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _extract_entities(self, content: str, role: str) -> Dict[str, str]:
        """Extract referenceable entities from message content.

        Returns a mapping of reference keys to their values for later resolution.
        """
        entities = {}

        # File paths (with common extensions)
        file_pattern = r'\b([\w/\\.-]+\.(?:py|js|ts|jsx|tsx|java|cpp|cc|c|h|rs|go|rb|php|cs|kt|swift|scala|r|m|pl|sh|bash|zsh|fish|ps1|bat|cmd|dockerfile|makefile|cmake|gradle|xml|json|yaml|yml|toml|ini|cfg|conf|md|txt|html|css|scss|sass|less|vue|svelte))\b'
        files = re.findall(file_pattern, content, re.IGNORECASE)
        if files:
            entities["that file"] = files[-1]
            entities["the file"] = files[-1]
            for i, f in enumerate(files[-3:]):
                entities[f"file {i+1}"] = f

        # Function/method names (word followed by parentheses)
        func_pattern = r'\b(\w+)\s*\('
        funcs = re.findall(func_pattern, content)
        if funcs:
            entities["that function"] = funcs[-1]
            entities["the function"] = funcs[-1]
            entities["the previous function"] = funcs[-1]

        # Class names (capitalized words, possibly with dots)
        class_pattern = r'\b([A-Z][a-zA-Z0-9]*(?:\.[A-Z][a-zA-Z0-9]*)*)\b'
        classes = re.findall(class_pattern, content)
        if classes:
            entities["that class"] = classes[-1]
            entities["the class"] = classes[-1]

        # Variable names (snake_case or camelCase)
        var_pattern = r'\b([a-z_][a-z0-9_]*|[a-z]+[A-Z][a-zA-Z0-9]*)\b'
        vars_found = re.findall(var_pattern, content)
        if vars_found:
            entities["that variable"] = vars_found[-1]
            entities["the variable"] = vars_found[-1]

        # Error messages
        error_pattern = r'(?:Error|Exception|Failure|Traceback).*?(?:\n|$)'
        errors = re.findall(error_pattern, content, re.IGNORECASE | re.MULTILINE)
        if errors:
            entities["that error"] = errors[-1].strip()
            entities["the error"] = errors[-1].strip()

        # Code snippets in markdown
        code_pattern = r'```[\w]*\n(.*?)\n```'
        code_blocks = re.findall(code_pattern, content, re.DOTALL)
        if code_blocks:
            entities["that code"] = code_blocks[-1][:500]
            entities["the code"] = code_blocks[-1][:500]

        # Quoted strings (potential references)
        quote_pattern = r'"([^"]{3,100})"'
        quotes = re.findall(quote_pattern, content)
        if quotes:
            entities["that"] = quotes[-1]
            entities["the thing"] = quotes[-1]

        return entities

    def _update_entity_index(self, turn_index: int, entities: Dict[str, str]) -> None:
        """Update the entity index with new entities from a turn."""
        for key, value in entities.items():
            if key not in self._entity_index:
                self._entity_index[key] = []
            self._entity_index[key].append((turn_index, value))

    def _rebuild_entity_index(self) -> None:
        """Rebuild entity index from all turns."""
        self._entity_index = {}
        for i, turn in enumerate(self._turns):
            self._update_entity_index(i, turn.entities)

    def _load(self) -> None:
        """Load conversation history from disk."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._turns = [ConversationTurn.from_dict(t) for t in data.get("turns", [])]
            self._rebuild_entity_index()
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self._turns = []
            self._entity_index = {}

    def _save(self) -> None:
        """Save conversation history to disk."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        data = {
            "turns": [t.to_dict() for t in self._turns],
            "metadata": {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "turn_count": len(self._turns),
            }
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(self.storage_path)

    def add_message(self, role: str, content: str) -> ConversationTurn:
        """Add a message to the conversation history.

        Args:
            role: "user" or "assistant"
            content: Message content

        Returns:
            The created ConversationTurn
        """
        with self._lock:
            turn = ConversationTurn(
                role=role,
                content=content,
                entities=self._extract_entities(content, role)
            )
            self._turns.append(turn)
            self._update_entity_index(len(self._turns) - 1, turn.entities)
            self._trim()
            self._save()
            return turn

    def _trim(self) -> None:
        """Trim conversation history to stay within limits.

        Keeps at least min_turns, at most max_turns, and within max_characters.
        """
        if len(self._turns) <= self.min_turns:
            return

        # Trim by turn count first
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns:]
            self._rebuild_entity_index()

        # Then trim by character count
        total_chars = sum(len(t.content) for t in self._turns)
        while total_chars > self.max_characters and len(self._turns) > self.min_turns:
            removed = self._turns.pop(0)
            total_chars -= len(removed.content)
            self._rebuild_entity_index()

    def get_history(self, limit: Optional[int] = None) -> List[ConversationTurn]:
        """Get conversation history.

        Args:
            limit: Maximum number of recent turns to return (None = all)

        Returns:
            List of ConversationTurn objects
        """
        with self._lock:
            if limit is None:
                return self._turns.copy()
            return self._turns[-limit:].copy()

    def get_history_text(self, limit: Optional[int] = None, max_characters: Optional[int] = None) -> str:
        """Get formatted conversation history for prompt injection.

        Args:
            limit: Maximum number of recent turns
            max_characters: Maximum characters to return

        Returns:
            Formatted conversation text
        """
        with self._lock:
            turns = self._turns[-limit:] if limit else self._turns
            lines = []
            for turn in turns:
                role_label = "User" if turn.role == "user" else "Freya"
                lines.append(f"{role_label}: {turn.content}")
            result = "\n".join(lines)
            if max_characters and len(result) > max_characters:
                result = result[-max_characters:]
            return result

    def resolve_reference(self, reference: str) -> Optional[str]:
        """Resolve a reference like "it", "that file", "the previous function".

        Args:
            reference: The reference phrase to resolve

        Returns:
            The resolved entity value, or None if not found
        """
        with self._lock:
            reference_lower = reference.lower().strip()

            # Direct match in entity index
            if reference_lower in self._entity_index:
                entries = self._entity_index[reference_lower]
                if entries:
                    return entries[-1][1]

            # Fuzzy match for common references
            reference_map = {
                "it": ["that", "the thing", "that code", "the file", "that file", "the function", "that function", "the variable", "that variable", "the error", "that error"],
                "that": ["it", "the thing", "that code", "the file", "that file"],
                "this": ["that", "it"],
                "the previous": ["the previous function", "the previous file", "the previous error"],
                "last": ["the function", "the file", "that function", "that file", "the error", "that error"],
            }

            for key, synonyms in reference_map.items():
                if reference_lower in [key] + synonyms:
                    for syn in [key] + synonyms:
                        if syn in self._entity_index and self._entity_index[syn]:
                            return self._entity_index[syn][-1][1]

            return None

    def get_recent_entities(self, category: Optional[str] = None) -> Dict[str, str]:
        """Get recent entities, optionally filtered by category.

        Args:
            category: Optional category filter (e.g., "file", "function", "error")

        Returns:
            Dictionary of entity references to their values
        """
        with self._lock:
            if category is None:
                # Return most recent value for each entity key
                return {k: v[-1][1] for k, v in self._entity_index.items() if v}

            # Filter by category prefix
            result = {}
            for key, entries in self._entity_index.items():
                if key.startswith(category) or category in key:
                    if entries:
                        result[key] = entries[-1][1]
            return result

    def clear(self) -> None:
        """Clear all conversation history."""
        with self._lock:
            self._turns = []
            self._entity_index = {}
            if self.storage_path.exists():
                self.storage_path.unlink()

    def to_dict(self) -> List[Dict[str, Any]]:
        """Convert all turns to dictionaries for serialization."""
        with self._lock:
            return [t.to_dict() for t in self._turns]

    def __len__(self) -> int:
        return len(self._turns)

    def is_empty(self) -> bool:
        return len(self._turns) == 0

    def get_last_user_message(self) -> Optional[str]:
        """Get the most recent user message content."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "user":
                    return turn.content
            return None

    def get_last_assistant_message(self) -> Optional[str]:
        """Get the most recent assistant message content."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "assistant":
                    return turn.content
            return None

    def save(self, path: Optional[str] = None) -> None:
        """Save conversation to file."""
        # If a different path is provided, temporarily use it
        original_path = None
        if path is not None:
            original_path = self.storage_path
            self.storage_path = Path(path).resolve()
        try:
            self._save()
        finally:
            if original_path is not None:
                self.storage_path = original_path

    def load(self, path: str) -> None:
        """Load conversation from file."""
        self.storage_path = Path(path).resolve()
        self._load()

    def new_conversation(self) -> None:
        """Start a new conversation (clear history)."""
        self.clear()

    def clear_conversation(self) -> None:
        """Clear conversation history (alias for clear)."""
        self.clear()

    def get_conversation_history(self) -> List[ConversationTurn]:
        """Get the full conversation history."""
        return self.get_history()

    def get_conversation_length(self) -> int:
        """Get the number of turns in the conversation."""
        return len(self._turns)

    # Backward compatibility properties
    @property
    def max_history(self) -> int:
        """Max history size (backward compat with ConversationState)."""
        return self.max_turns

    @property
    def _persistence_path(self) -> Optional[str]:
        """Persistence path for backward compatibility."""
        return str(self.storage_path) if self.storage_path else None

    @_persistence_path.setter
    def _persistence_path(self, value: Optional[str]) -> None:
        if value:
            self.storage_path = Path(value).resolve()

    @max_history.setter
    def max_history(self, value: int) -> None:
        """Allow setting max_history for backward compatibility.

        Note: For backward compat with old ConversationState, we allow values < 20
        even though the new system enforces a minimum of 20 turns.
        """
        self.max_turns = value


# Backwards compatibility with existing ConversationState
def create_conversation_memory(
    workspace: str = ".",
    max_history: int = 20,
    persistence_path: Optional[str] = None,
) -> ConversationMemory:
    """Create a ConversationMemory instance compatible with existing ConversationState usage.

    Args:
        workspace: Project workspace directory
        max_history: Maximum conversation history (maps to max_turns)
        persistence_path: Optional custom persistence path

    Returns:
        Configured ConversationMemory instance
    """
    storage = persistence_path or "data/memory/conversation_memory.json"
    # For backward compatibility, allow max_history < 20 (old ConversationState allowed any value)
    min_turns = min(20, max_history)
    return ConversationMemory(
        workspace=workspace,
        storage_path=storage,
        min_turns=min_turns,
        max_turns=max_history,
        max_characters=16000,
        _bypass_min_turns=True,  # Allow < 20 turns for backward compat
    )