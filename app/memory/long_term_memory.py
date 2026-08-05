"""Long-Term Memory for Freya AI.

This module provides persistent storage for user preferences, permanent facts,
coding standards, and cross-project knowledge that persists across sessions.
"""

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.core.file_allowlist import FileAllowlist, get_file_allowlist, FileOperation, AccessRule

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub
from app.core.observability import HealthStatus, HealthResult, HealthCheck, ComponentInfo, ComponentType


def _get_default_storage_path() -> Path:
    """Get the default storage path for long-term memory.

    Uses a platform-appropriate user config directory.
    """
    # Use XDG_CONFIG_HOME on Linux, AppData on Windows, ~/.config on macOS
    if os.name == 'nt':  # Windows
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'freya' / 'memory' / 'long_term_memory.json'


@dataclass
class LongTermEntry:
    """A single entry in long-term memory."""
    entry_id: str
    category: str  # preference, fact, standard, convention, pattern, knowledge
    key: str  # e.g., "indent_style", "preferred_test_framework"
    value: Any  # The stored value (str, int, bool, dict, list)
    confidence: float = 1.0  # 0-1 confidence in this entry
    source: str = "user"  # user, inferred, project, documentation
    tags: List[str] = field(default_factory=list)
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    last_accessed: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LongTermEntry":
        return cls(**data)


class LongTermMemory:
    """Persistent long-term memory for user preferences and cross-project knowledge.

    Features:
    - Key-value storage with categories (preference, fact, standard, convention, pattern, knowledge)
    - Confidence scoring for inferred vs explicitly stated knowledge
    - Source tracking (user-stated, inferred from behavior, from project config, from docs)
    - Tag-based organization and search
    - Access tracking for importance estimation
    - Thread-safe atomic JSON persistence
    - Configurable limits with LRU-like eviction

    Example usage:
        ltm = LongTermMemory(workspace=".")

        # Store user preference
        ltm.set("preference", "indent_style", 4,
                source="user", description="User prefers 4-space indentation")

        # Store coding standard
        ltm.set("standard", "max_line_length", 100, source="project",
                description="Project-specific line length limit")

        # Store learned fact
        ltm.set("fact", "pytest_asyncio_mode", "auto", source="inferred",
                description="Detected pytest-asyncio auto mode from test runs")

        # Retrieve
        indent = ltm.get("preference", "indent_style")  # Returns 4
        all_prefs = ltm.get_category("preference")
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/long_term_memory.json",
        max_entries: int = 5000,
        file_allowlist: Optional[FileAllowlist] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize Long-Term Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_entries: Maximum number of entries to keep in history
            file_allowlist: Optional FileAllowlist for access validation
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_entries = max_entries
        self.file_allowlist = file_allowlist or get_file_allowlist()
        self._lock = threading.RLock()
        self._entries: Dict[str, LongTermEntry] = {}  # key -> entry (key is category.key)

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Configure allowlist for this workspace
        self._configure_allowlist_for_workspace()

        self._load()

        # Register with observability
        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="long_term_memory_health",
                component="memory.long_term",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="LongTermMemory",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Long-term memory for user preferences and cross-project knowledge",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for LongTermMemory."""
        entry_count = len(self._entries)
        categories = len(self.get_all_categories())
        sources = len(self.get_all_sources())

        return HealthResult(
            name="long_term_memory_health",
            component="memory.long_term",
            status=HealthStatus.HEALTHY,
            message=f"{entry_count} entries, {categories} categories, {sources} sources",
            details={
                "entry_count": entry_count,
                "categories": categories,
                "sources": sources,
            },
        )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception:
            # Don't let event publishing break the system
            pass

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence."""
        # Check if job already exists to avoid duplicate scheduling
        existing_job = self._job_service.get_job("long_term_memory_persist")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="long_term_memory_persist",
            func=self._save,
            trigger=trigger,
            name="Long-Term Memory Persistence",
            priority=JobPriority.LOW,
        )

    def _configure_allowlist_for_workspace(self):
        """Configure the file allowlist with workspace-specific rules."""
        workspace_str = str(self.workspace)

        # Add rule for workspace root directory
        self.file_allowlist.add_rule(AccessRule(
            pattern=workspace_str,
            operations={FileOperation.LIST, FileOperation.READ},
            description=f"Workspace root directory: {workspace_str}",
            tags={"type": "workspace_root", "workspace": workspace_str},
        ))

        # Add rules for workspace directory contents
        self.file_allowlist.add_rule(AccessRule(
            pattern=f"{workspace_str}/**",
            operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
            description=f"Full access to workspace contents: {workspace_str}",
            tags={"type": "workspace", "workspace": workspace_str},
        ))

        # Add rules for common project directories
        common_dirs = [
            "data/**",
            "logs/**",
            "cache/**",
            "tmp/**",
            "temp/**",
            ".freya/**",
        ]
        for dir_pattern in common_dirs:
            full_pattern = f"{workspace_str}/{dir_pattern}"
            self.file_allowlist.add_rule(AccessRule(
                pattern=full_pattern,
                operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
                description=f"Project directory: {dir_pattern}",
                tags={"type": "project_dir", "workspace": workspace_str},
            ))

    def _make_key(self, category: str, key: str) -> str:
        """Create composite key for storage."""
        return f"{category}.{key}"

    def _generate_timestamp(self) -> str:
        """Generate a timestamp with timezone."""
        return datetime.now(timezone.utc).isoformat()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        """Save all entries to storage (atomic write)."""
        # Validate write access
        self.file_allowlist.require_allowed(self.storage_path, FileOperation.WRITE, "LongTermMemory._save")

        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "entries": [e.to_dict() for e in self._entries.values()],
                "version": 1,
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _load(self) -> None:
        """Load entries from storage file."""
        # Validate read access
        self.file_allowlist.require_allowed(self.storage_path, FileOperation.READ, "LongTermMemory._load")

        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._entries = {}
            for entry_data in data.get("entries", []):
                entry = LongTermEntry.from_dict(entry_data)
                key = self._make_key(entry.category, entry.key)
                self._entries[key] = entry
        except Exception:
            self._entries = {}

    def _enforce_limit(self) -> None:
        """Enforce maximum entries by removing least recently/least used."""
        if len(self._entries) <= self.max_entries:
            return

        # Sort by access_count (asc) then last_accessed (asc), remove oldest/least accessed
        sorted_entries = sorted(
            self._entries.items(),
            key=lambda x: (x[1].access_count, x[1].last_accessed or x[1].created_at)
        )

        # Remove excess
        to_remove = len(self._entries) - self.max_entries
        for key, _ in sorted_entries[:to_remove]:
            del self._entries[key]

    def set(
        self,
        category: str,
        key: str,
        value: Any,
        confidence: float = 1.0,
        source: str = "user",
        tags: Optional[List[str]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LongTermEntry:
        """Set a value in long-term memory.

        Args:
            category: Category (preference, fact, standard, convention, pattern, knowledge)
            key: The key to store under
            value: The value to store
            confidence: Confidence level (0-1)
            source: Source of the knowledge (user, inferred, project, documentation)
            tags: Optional tags for organization
            description: Human-readable description
            metadata: Additional metadata

        Returns:
            The created/updated LongTermEntry
        """
        with self._lock:
            composite_key = self._make_key(category, key)
            now = self._generate_timestamp()

            if composite_key in self._entries:
                # Update existing
                entry = self._entries[composite_key]
                entry.value = value
                entry.confidence = confidence
                entry.source = source
                if tags:
                    entry.tags = tags
                if description:
                    entry.description = description
                if metadata:
                    entry.metadata.update(metadata)
                entry.updated_at = now

                # Publish event for update
                self._publish_event("memory.long_term_set", {
                    "category": category,
                    "key": key,
                    "value": value,
                    "confidence": confidence,
                    "source": source,
                    "is_new": False,
                })
            else:
                # Create new
                entry = LongTermEntry(
                    entry_id=composite_key,
                    category=category,
                    key=key,
                    value=value,
                    confidence=confidence,
                    source=source,
                    tags=tags or [],
                    description=description,
                    created_at=now,
                    updated_at=now,
                    metadata=metadata or {},
                )
                self._entries[composite_key] = entry

            self._enforce_limit()
            self._save()

            # Publish event
            self._publish_event("memory.long_term_set", {
                "category": category,
                "key": key,
                "value": value,
                "confidence": confidence,
                "source": source,
                "is_new": True,
            })

            return entry

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Get a value from long-term memory.

        Args:
            category: Category to search in
            key: The key to retrieve
            default: Default value if not found

        Returns:
            The stored value or default
        """
        with self._lock:
            composite_key = self._make_key(category, key)
            entry = self._entries.get(composite_key)
            if entry:
                entry.access_count += 1
                entry.last_accessed = self._generate_timestamp()
                # Don't save on every access to avoid excessive writes
                return entry.value
            return default

    def get_entry(self, category: str, key: str) -> Optional[LongTermEntry]:
        """Get the full entry object."""
        with self._lock:
            composite_key = self._make_key(category, key)
            entry = self._entries.get(composite_key)
            if entry:
                entry.access_count += 1
                entry.last_accessed = self._generate_timestamp()
            return entry

    def get_category(self, category: str) -> Dict[str, LongTermEntry]:
        """Get all entries in a category."""
        with self._lock:
            return {
                entry.key: entry
                for entry in self._entries.values()
                if entry.category == category
            }

    def get_category_values(self, category: str) -> Dict[str, Any]:
        """Get all values in a category as a simple dict."""
        with self._lock:
            return {
                entry.key: entry.value
                for entry in self._entries.values()
                if entry.category == category
            }

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> List[LongTermEntry]:
        """Search entries with various filters.

        Args:
            query: Search in key, description, tags
            category: Filter by category
            tags: Filter by tags (all must match)
            source: Filter by source
            min_confidence: Minimum confidence threshold
            limit: Maximum results to return

        Returns:
            List of matching entries
        """
        with self._lock:
            results = []

            for entry in self._entries.values():
                # Category filter
                if category and entry.category != category:
                    continue

                # Source filter
                if source and entry.source != source:
                    continue

                # Confidence filter
                if entry.confidence < min_confidence:
                    continue

                # Tags filter (all must match)
                if tags and not all(tag in entry.tags for tag in tags):
                    continue

                # Query filter
                if query:
                    query_lower = query.lower()
                    searchable = f"{entry.key} {entry.description} {' '.join(entry.tags)}".lower()
                    if query_lower not in searchable:
                        continue

                results.append(entry)

            # Sort by relevance: confidence desc, access_count desc, last_accessed desc
            results.sort(
                key=lambda e: (e.confidence, e.access_count, e.last_accessed or e.created_at),
                reverse=True
            )

            return results[:limit]

    def update_metadata(self, category: str, key: str, metadata: Dict[str, Any]) -> bool:
        """Update metadata for an existing entry."""
        with self._lock:
            composite_key = self._make_key(category, key)
            entry = self._entries.get(composite_key)
            if not entry:
                return False
            entry.metadata.update(metadata)
            entry.updated_at = self._generate_timestamp()
            self._save()
            return True

    def add_tags(self, category: str, key: str, tags: List[str]) -> bool:
        """Add tags to an existing entry."""
        with self._lock:
            composite_key = self._make_key(category, key)
            entry = self._entries.get(composite_key)
            if not entry:
                return False
            for tag in tags:
                if tag not in entry.tags:
                    entry.tags.append(tag)
            entry.updated_at = self._generate_timestamp()
            self._save()
            return True

    def delete(self, category: str, key: str) -> bool:
        """Delete an entry."""
        with self._lock:
            composite_key = self._make_key(category, key)
            if composite_key in self._entries:
                entry = self._entries[composite_key]
                del self._entries[composite_key]
                self._save()

                # Publish event
                self._publish_event("memory.long_term_deleted", {
                    "category": category,
                    "key": key,
                })
                return True
            return False

    def delete_category(self, category: str) -> int:
        """Delete all entries in a category."""
        with self._lock:
            to_remove = []
            for k, v in self._entries.items():
                if v.category == category:
                    to_remove.append((k, v))

            for key, entry in to_remove:
                del self._entries[key]

            if to_remove:
                self._save()

                # Publish event
                self._publish_event("memory.long_term_category_deleted", {
                    "category": category,
                    "count": len(to_remove),
                })
            return len(to_remove)

    def get_all_categories(self) -> List[str]:
        """Get all unique categories."""
        with self._lock:
            return sorted(set(e.category for e in self._entries.values()))

    def get_all_sources(self) -> List[str]:
        """Get all unique sources."""
        with self._lock:
            return sorted(set(e.source for e in self._entries.values()))

    def get_all_tags(self) -> List[str]:
        """Get all unique tags."""
        with self._lock:
            tags = set()
            for entry in self._entries.values():
                tags.update(entry.tags)
            return sorted(tags)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about long-term memory."""
        with self._lock:
            categories: Dict[str, int] = {}
            sources: Dict[str, int] = {}
            total_confidence = 0

            for entry in self._entries.values():
                categories[entry.category] = categories.get(entry.category, 0) + 1
                sources[entry.source] = sources.get(entry.source, 0) + 1
                total_confidence += entry.confidence

            return {
                "total_entries": len(self._entries),
                "categories": categories,
                "sources": sources,
                "avg_confidence": total_confidence / len(self._entries) if self._entries else 0,
                "max_entries": self.max_entries,
            }

    def export(self) -> Dict[str, Any]:
        """Export all entries for backup or transfer."""
        with self._lock:
            return {
                "entries": [e.to_dict() for e in self._entries.values()],
                "version": 1,
                "exported_at": self._generate_timestamp(),
            }

    def import_data(self, data: Dict[str, Any], merge: bool = True) -> int:
        """Import entries from exported data."""
        with self._lock:
            if not merge:
                self._entries = {}

            imported = 0
            for entry_data in data.get("entries", []):
                try:
                    entry = LongTermEntry.from_dict(entry_data)
                    key = self._make_key(entry.category, entry.key)
                    self._entries[key] = entry
                    imported += 1
                except Exception:
                    pass

            self._enforce_limit()
            self._save()
            return imported

    def get_all(self) -> List[LongTermEntry]:
        """Get all entries as a list.

        Returns:
            List of all LongTermEntry objects
        """
        with self._lock:
            return list(self._entries.values())

    def set_entry(self, entry: LongTermEntry) -> LongTermEntry:
        """Set a LongTermEntry directly (for promotion from other memory systems).

        Args:
            entry: The LongTermEntry to store

        Returns:
            The stored LongTermEntry
        """
        with self._lock:
            composite_key = self._make_key(entry.category, entry.key)
            entry.entry_id = composite_key  # Ensure entry_id matches composite key
            self._entries[composite_key] = entry
            self._enforce_limit()
            self._save()
            return entry

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def count(self) -> int:
        """Get the total number of entries."""
        with self._lock:
            return len(self._entries)


def create_long_term_memory(
    workspace: Optional[str] = None,
    storage_path: Optional[str] = None,
    max_entries: int = 5000,
    file_allowlist: Optional[FileAllowlist] = None,
) -> LongTermMemory:
    """Factory function to create LongTermMemory with sensible defaults.

    If no workspace or storage_path is provided, uses a platform-appropriate
    user configuration directory (e.g., ~/.config/freya/ on Linux,
    %APPDATA%/Freya/ on Windows).
    """
    if storage_path is None:
        if workspace is None:
            storage_path = str(_get_default_storage_path())
        else:
            storage_path = "data/memory/long_term_memory.json"
    return LongTermMemory(
        workspace=workspace or ".",
        storage_path=storage_path,
        max_entries=max_entries,
        file_allowlist=file_allowlist,
    )