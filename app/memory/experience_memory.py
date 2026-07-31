"""Experience Memory for Freya AI.

This module provides read-only storage for lessons learned and historical context.
It captures past experiences, decisions, and their outcomes to inform future actions.

Capabilities:
- Store experiences with metadata (timestamp, category, tags)
- Read/search experiences by keywords, categories, or time ranges
- Persistent JSON storage
- Thread-safe operations
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Union


@dataclass
class ExperienceEntry:
    """A single experience entry stored in memory."""
    id: str
    title: str
    description: str
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    outcome: str = "neutral"  # positive, negative, neutral
    confidence: float = 0.0  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0  # Monotonically increasing sequence number for ordering
    # Fields needed by ConsolidationEngine
    access_count: int = 0
    code_snippet: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceEntry":
        """Create entry from dictionary."""
        return cls(**data)


class ExperienceMemory:
    """Read-only storage for lessons learned and historical context.

    This class provides a simple, persistent storage for capturing experiences
    that can be used to inform future decisions. The storage is read-only in the
    sense that existing entries are immutable - new entries can be added but
    existing ones cannot be modified (only retrieved).

    Example usage:
        memory = ExperienceMemory(workspace=".")

        # Store a new experience
        memory.store(
            title="Used dataclasses for state management",
            description="Dataclasses provided clean serialization and type hints",
            category="architecture",
            tags=["python", "best-practice"],
            outcome="positive",
            confidence=0.9
        )

        # Search for experiences
        results = memory.search(keyword="dataclass", category="architecture")

        # Get recent experiences
        recent = memory.recent(limit=10)
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/experience_memory.json",
        max_entries: int = 1000,
    ):
        """Initialize Experience Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_entries: Maximum number of entries to keep (oldest removed first)
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._entries: Dict[str, ExperienceEntry] = {}
        self._index: Dict[str, List[str]] = {
            "category": [],
            "tags": [],
            "outcome": [],
        }
        self._sequence_counter = 0
        self._load()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_id(self) -> str:
        """Generate a unique ID for a new entry."""
        import uuid
        return f"exp_{uuid.uuid4().hex[:12]}"

    def _generate_timestamp(self) -> str:
        """Generate a timestamp with microsecond precision."""
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        """Load entries from storage file."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for entry_data in data.get("entries", []):
                entry = ExperienceEntry.from_dict(entry_data)
                self._entries[entry.id] = entry

                # Update sequence counter
                self._sequence_counter = max(self._sequence_counter, entry.sequence + 1)

                # Update indexes
                self._index["category"].append(entry.category)
                self._index["tags"].extend(entry.tags)
                self._index["outcome"].append(entry.outcome)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # If loading fails, start fresh
            self._entries = {}
            self._index = {"category": [], "tags": [], "outcome": []}
            self._sequence_counter = 0

    def _save(self) -> None:
        """Save entries to storage file."""
        self._ensure_storage_dir()

        # Write to temporary file first, then rename for atomicity
        temp_path = self.storage_path.with_suffix(".tmp")

        data = {
            "entries": [entry.to_dict() for entry in self._entries.values()],
            "metadata": {
                "count": len(self._entries),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        }

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(self.storage_path)

    def store(
        self,
        title: str,
        description: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        outcome: str = "neutral",
        confidence: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        code_snippet: Optional[str] = None,
        source: Optional[str] = None,
    ) -> ExperienceEntry:
        """Store a new experience entry.

        Args:
            title: Short title for the experience
            description: Detailed description of what happened
            category: Category (e.g., "architecture", "bugfix", "performance", "testing")
            tags: List of tags for easier searching
            outcome: Outcome classification ("positive", "negative", "neutral")
            confidence: Confidence level (0.0 to 1.0)
            metadata: Additional metadata to store with the experience
            code_snippet: Optional code snippet related to the experience
            source: Optional source identifier (e.g., "consolidation", "user", "agent")

        Returns:
            The created ExperienceEntry
        """
        with self._lock:
            self._sequence_counter += 1
            entry = ExperienceEntry(
                id=self._generate_id(),
                title=title,
                description=description,
                category=category,
                tags=tags or [],
                outcome=outcome,
                confidence=max(0.0, min(1.0, confidence)),
                metadata=metadata or {},
                sequence=self._sequence_counter,
                code_snippet=code_snippet,
                source=source,
            )

            # Add to storage
            self._entries[entry.id] = entry

            # Update indexes
            self._index["category"].append(entry.category)
            self._index["tags"].extend(entry.tags)
            self._index["outcome"].append(entry.outcome)

            # Trim if over limit (remove oldest first)
            if len(self._entries) > self.max_entries:
                sorted_ids = sorted(self._entries.keys(),
                                   key=lambda x: (self._entries[x].timestamp, self._entries[x].sequence))
                ids_to_remove = sorted_ids[:len(self._entries) - self.max_entries]
                for idx in ids_to_remove:
                    del self._entries[idx]

            # Save to disk
            self._save()

            return entry

    def get(self, entry_id: str) -> Optional[ExperienceEntry]:
        """Get a specific experience entry by ID.

        Args:
            entry_id: The unique ID of the entry

        Returns:
            The ExperienceEntry or None if not found
        """
        with self._lock:
            return self._entries.get(entry_id)

    def all(self) -> List[ExperienceEntry]:
        """Get all experience entries.

        Returns:
            List of all ExperienceEntry objects
        """
        with self._lock:
            return list(self._entries.values())

    def recent(self, limit: int = 10) -> List[ExperienceEntry]:
        """Get the most recent experience entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of recent ExperienceEntry objects (newest first)
        """
        with self._lock:
            # Sort by timestamp descending, then by sequence descending
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda x: (x.timestamp, x.sequence),
                reverse=True
            )
            return sorted_entries[:limit]

    def search(
        self,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        outcome: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: int = 20,
    ) -> List[ExperienceEntry]:
        """Search experience entries by various criteria.

        Args:
            keyword: Search in title and description (case-insensitive)
            category: Filter by category
            tags: Filter by tags (all tags must match)
            outcome: Filter by outcome
            min_confidence: Minimum confidence score (0.0 to 1.0)
            limit: Maximum number of results to return

        Returns:
            List of matching ExperienceEntry objects (newest first)
        """
        with self._lock:
            results = []

            for entry in self._entries.values():
                # Keyword search
                if keyword:
                    keyword_lower = keyword.lower()
                    if (keyword_lower not in entry.title.lower() and
                        keyword_lower not in entry.description.lower()):
                        continue

                # Category filter
                if category and entry.category != category:
                    continue

                # Tags filter (all tags must match)
                if tags:
                    if not all(tag in entry.tags for tag in tags):
                        continue

                # Outcome filter
                if outcome and entry.outcome != outcome:
                    continue

                # Confidence filter
                if min_confidence is not None and entry.confidence < min_confidence:
                    continue

                results.append(entry)

            # Sort by timestamp (newest first), then by sequence (newest first)
            results.sort(key=lambda x: (x.timestamp, x.sequence), reverse=True)

            return results[:limit]

    def count(self) -> int:
        """Get the total number of experience entries.

        Returns:
            Number of entries stored
        """
        with self._lock:
            return len(self._entries)

    def categories(self) -> List[str]:
        """Get all unique categories.

        Returns:
            List of unique category names
        """
        with self._lock:
            return list(set(self._index["category"]))

    def tags(self) -> List[str]:
        """Get all unique tags.

        Returns:
            List of unique tag names
        """
        with self._lock:
            return list(set(self._index["tags"]))

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the experience memory.

        Returns:
            Dictionary with summary statistics
        """
        with self._lock:
            outcomes = {}
            categories = {}

            for entry in self._entries.values():
                # Count by outcome
                outcomes[entry.outcome] = outcomes.get(entry.outcome, 0) + 1

                # Count by category
                categories[entry.category] = categories.get(entry.category, 0) + 1

            return {
                "total_entries": len(self._entries),
                "categories": categories,
                "outcomes": outcomes,
                "all_tags": list(set(self._index["tags"])),
            }

    def export_json(self, path: Optional[Union[str, Path]] = None) -> str:
        """Export all experiences as JSON.

        Args:
            path: Optional path to save the JSON (defaults to storage path)

        Returns:
            JSON string representation
        """
        with self._lock:
            data = {
                "entries": [entry.to_dict() for entry in self._entries.values()],
                "summary": self.get_summary(),
            }
            json_str = json.dumps(data, indent=2, ensure_ascii=False)

            if path:
                export_path = Path(path) if isinstance(path, str) else path
                export_path.parent.mkdir(parents=True, exist_ok=True)
                export_path.write_text(json_str, encoding="utf-8")

            return json_str
