"""Documentation store for managing generated documentation.

This module provides storage and retrieval of generated documentation
with versioning and metadata tracking.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid


class DocStatus(Enum):
    """Status of a documentation entry."""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


@dataclass
class DocumentationEntry:
    """Represents a single documentation entry."""
    entry_id: str = field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:8]}")
    title: str = ""
    content: str = ""
    content_hash: str = ""
    module: str = ""
    doc_type: str = "module"
    status: DocStatus = DocStatus.DRAFT
    version: str = "1.0"
    author: str = "system"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]

    def update_content(self, new_content: str) -> None:
        """Update the content and recalculate hash."""
        self.content = new_content
        self.content_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]
        self.updated_at = datetime.now(timezone.utc).isoformat()
        # Increment version
        try:
            major, minor = self.version.split(".")
            self.version = f"{major}.{int(minor) + 1}"
        except (ValueError, AttributeError):
            self.version = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "content": self.content,
            "content_hash": self.content_hash,
            "module": self.module,
            "doc_type": self.doc_type,
            "status": self.status.value,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentationEntry":
        """Create from dictionary."""
        entry = cls(
            entry_id=data.get("entry_id", f"doc_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_hash=data.get("content_hash", ""),
            module=data.get("module", ""),
            doc_type=data.get("doc_type", "module"),
            version=data.get("version", "1.0"),
            author=data.get("author", "system"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )
        if isinstance(data.get("status"), str):
            entry.status = DocStatus(data["status"])
        return entry


@dataclass
class DocumentationStore:
    """Stores and manages generated documentation."""

    workspace: Optional[str] = None
    storage_file: str = ".documentation.json"
    _workspace_path: Path = field(init=False, default=Path("."))
    _entries: Dict[str, DocumentationEntry] = field(default_factory=dict)
    _tags_index: Dict[str, List[str]] = field(default_factory=dict)  # tag -> entry_ids
    _module_index: Dict[str, List[str]] = field(default_factory=dict)  # module -> entry_ids

    def __post_init__(self):
        if self.workspace:
            object.__setattr__(self, '_workspace_path', Path(self.workspace))
        self._storage_path = self._workspace_path / self.storage_file
        self._load()

    def _load(self) -> None:
        """Load documentation entries from storage."""
        if not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            object.__setattr__(self, '_entries', {})
            object.__setattr__(self, '_tags_index', {})
            object.__setattr__(self, '_module_index', {})

            for entry_data in data.get("entries", []):
                try:
                    entry = DocumentationEntry.from_dict(entry_data)
                    self._entries[entry.entry_id] = entry

                    # Update indexes
                    for tag in entry.tags:
                        if tag not in self._tags_index:
                            self._tags_index[tag] = []
                        self._tags_index[tag].append(entry.entry_id)

                    if entry.module:
                        if entry.module not in self._module_index:
                            self._module_index[entry.module] = []
                        self._module_index[entry.module].append(entry.entry_id)

                except Exception as e:
                    print(f"Error loading documentation entry: {e}")

        except Exception as e:
            print(f"Error loading documentation store: {e}")

    def _save(self) -> None:
        """Save documentation entries to storage."""
        self._workspace_path.mkdir(parents=True, exist_ok=True)

        data = {
            "entries": [e.to_dict() for e in self._entries.values()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_summary(),
        }

        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving documentation store: {e}")

    def add_entry(self, entry: DocumentationEntry) -> None:
        """Add a documentation entry to the store.

        Args:
            entry: The documentation entry to add
        """
        self._entries[entry.entry_id] = entry

        # Update indexes
        for tag in entry.tags:
            if tag not in self._tags_index:
                self._tags_index[tag] = []
            if entry.entry_id not in self._tags_index[tag]:
                self._tags_index[tag].append(entry.entry_id)

        if entry.module:
            if entry.module not in self._module_index:
                self._module_index[entry.module] = []
            if entry.entry_id not in self._module_index[entry.module]:
                self._module_index[entry.module].append(entry.entry_id)

        self._save()

    def remove_entry(self, entry_id: str) -> bool:
        """Remove a documentation entry from the store.

        Args:
            entry_id: The ID of the entry to remove

        Returns:
            True if the entry was found and removed, False otherwise
        """
        if entry_id not in self._entries:
            return False

        entry = self._entries[entry_id]

        # Remove from indexes
        for tag in entry.tags:
            if tag in self._tags_index:
                self._tags_index[tag] = [eid for eid in self._tags_index[tag] if eid != entry_id]

        if entry.module and entry.module in self._module_index:
            self._module_index[entry.module] = [
                eid for eid in self._module_index[entry.module] if eid != entry_id
            ]

        del self._entries[entry_id]
        self._save()
        return True

    def get_entry(self, entry_id: str) -> Optional[DocumentationEntry]:
        """Get a documentation entry by ID.

        Args:
            entry_id: The ID of the entry

        Returns:
            The DocumentationEntry if found, None otherwise
        """
        return self._entries.get(entry_id)

    def list_entries(
        self,
        status: Optional[DocStatus] = None,
        module: Optional[str] = None,
        doc_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[DocumentationEntry]:
        """List documentation entries with optional filters.

        Args:
            status: Filter by status
            module: Filter by module
            doc_type: Filter by doc type
            tag: Filter by tag
            limit: Maximum number of results

        Returns:
            List of matching DocumentationEntry objects
        """
        entries = list(self._entries.values())

        if status:
            entries = [e for e in entries if e.status == status]

        if module:
            entries = [e for e in entries if e.module == module]

        if doc_type:
            entries = [e for e in entries if e.doc_type == doc_type]

        if tag:
            if tag in self._tags_index:
                tag_entry_ids = set(self._tags_index[tag])
                entries = [e for e in entries if e.entry_id in tag_entry_ids]

        # Sort by updated_at (newest first)
        entries.sort(key=lambda e: e.updated_at, reverse=True)

        if limit:
            entries = entries[:limit]

        return entries

    def get_entries_by_module(self, module: str) -> List[DocumentationEntry]:
        """Get all entries for a specific module.

        Args:
            module: The module name

        Returns:
            List of DocumentationEntry objects
        """
        if module not in self._module_index:
            return []

        return [
            self._entries[eid] for eid in self._module_index[module]
            if eid in self._entries
        ]

    def search(self, query: str, limit: int = 10) -> List[DocumentationEntry]:
        """Search documentation entries by content.

        Args:
            query: The search query
            limit: Maximum number of results

        Returns:
            List of matching DocumentationEntry objects
        """
        query_lower = query.lower()
        results = []

        for entry in self._entries.values():
            if query_lower in entry.title.lower():
                results.append(entry)
            elif query_lower in entry.content.lower():
                results.append(entry)
            elif query_lower in entry.module.lower():
                results.append(entry)

        # Sort by relevance (simple: count matches)
        def relevance(e: DocumentationEntry) -> int:
            count = 0
            if query_lower in e.title.lower():
                count += 3
            if query_lower in e.module.lower():
                count += 2
            if query_lower in e.content.lower():
                count += 1
            return count

        results.sort(key=relevance, reverse=True)

        return results[:limit]

    @property
    def count(self) -> int:
        """Get the total number of entries."""
        return len(self._entries)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the documentation store.

        Returns:
            Summary dictionary
        """
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_module: Dict[str, int] = {}

        for entry in self._entries.values():
            # By status
            status_key = entry.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # By type
            doc_type = entry.doc_type or "unknown"
            by_type[doc_type] = by_type.get(doc_type, 0) + 1

            # By module
            if entry.module:
                by_module[entry.module] = by_module.get(entry.module, 0) + 1

        return {
            "total_entries": self.count,
            "by_status": by_status,
            "by_type": by_type,
            "by_module": by_module,
            "total_tags": len(self._tags_index),
            "total_modules": len(self._module_index),
        }

    def clear(self) -> None:
        """Clear all documentation entries."""
        object.__setattr__(self, '_entries', {})
        object.__setattr__(self, '_tags_index', {})
        object.__setattr__(self, '_module_index', {})
        try:
            self._storage_path.unlink()
        except FileNotFoundError:
            pass

    def export_to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary."""
        return {
            "entries": [e.to_dict() for e in self._entries.values()],
            "summary": self.get_summary(),
            "tags": list(self._tags_index.keys()),
            "modules": list(self._module_index.keys()),
        }

    def import_from_dict(self, data: Dict[str, Any]) -> None:
        """Import data from a dictionary."""
        self._entries = {}
        self._tags_index = {}
        self._module_index = {}

        for entry_data in data.get("entries", []):
            try:
                entry = DocumentationEntry.from_dict(entry_data)
                self._entries[entry.entry_id] = entry

                # Update indexes
                for tag in entry.tags:
                    if tag not in self._tags_index:
                        self._tags_index[tag] = []
                    self._tags_index[tag].append(entry.entry_id)

                if entry.module:
                    if entry.module not in self._module_index:
                        self._module_index[entry.module] = []
                    self._module_index[entry.module].append(entry.entry_id)

            except Exception as e:
                print(f"Error importing documentation entry: {e}")

        self._save()
