"""Change log for tracking project changes.

This module provides change logging functionality for tracking
the evolution of the Freya project over time.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid


class ChangeType(Enum):
    """Type of a change entry."""
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    DOCUMENTATION = "documentation"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"
    SECURITY = "security"
    BREAKING = "breaking"
    DEPRECATION = "deprecation"
    TEST = "test"
    BUILD = "build"
    CI = "ci"
    OTHER = "other"


class ChangeScope(Enum):
    """Scope of a change entry."""
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


@dataclass
class ChangeEntry:
    """Represents a single change in the change log."""
    entry_id: str = field(default_factory=lambda: f"change_{uuid.uuid4().hex[:8]}")
    title: str = ""
    description: str = ""
    change_type: ChangeType = ChangeType.OTHER
    scope: ChangeScope = ChangeScope.PATCH
    module: str = ""
    files_changed: List[str] = field(default_factory=list)
    author: str = "system"
    version: str = ""
    related_pr: Optional[str] = None
    related_issue: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "description": self.description,
            "change_type": self.change_type.value,
            "scope": self.scope.value,
            "module": self.module,
            "files_changed": self.files_changed,
            "author": self.author,
            "version": self.version,
            "related_pr": self.related_pr,
            "related_issue": self.related_issue,
            "tags": self.tags,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChangeEntry":
        """Create from dictionary."""
        entry = cls(
            entry_id=data.get("entry_id", f"change_{uuid.uuid4().hex[:8]}"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            module=data.get("module", ""),
            files_changed=data.get("files_changed", []),
            author=data.get("author", "system"),
            version=data.get("version", ""),
            related_pr=data.get("related_pr"),
            related_issue=data.get("related_issue"),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )

        if isinstance(data.get("change_type"), str):
            entry.change_type = ChangeType(data["change_type"])
        if isinstance(data.get("scope"), str):
            entry.scope = ChangeScope(data["scope"])

        return entry

    def __str__(self) -> str:
        type_label = self.change_type.value.upper()
        scope_label = self.scope.value.upper()
        return f"[{type_label}] [{scope_label}] {self.title} ({self.version})"


@dataclass
class ChangeLog:
    """Manages the change log for the project."""

    workspace: Optional[str] = None
    storage_file: str = "CHANGELOG.json"
    markdown_file: str = "CHANGELOG.md"

    def __post_init__(self):
        self._workspace_path = Path(self.workspace) if self.workspace else Path(".")
        self._storage_path = self._workspace_path / self.storage_file
        self._markdown_path = self._workspace_path / self.markdown_file
        self._entries: List[ChangeEntry] = []
        self._version_index: Dict[str, List[str]] = {}
        self._type_index: Dict[str, List[str]] = {}
        self._module_index: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        """Load change entries from storage."""
        if not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._entries = []
            self._version_index = {}
            self._type_index = {}
            self._module_index = {}

            for entry_data in data.get("entries", []):
                try:
                    entry = ChangeEntry.from_dict(entry_data)
                    self._entries.append(entry)

                    # Update indexes
                    if entry.version:
                        if entry.version not in self._version_index:
                            self._version_index[entry.version] = []
                        self._version_index[entry.version].append(entry.entry_id)

                    type_key = entry.change_type.value
                    if type_key not in self._type_index:
                        self._type_index[type_key] = []
                    self._type_index[type_key].append(entry.entry_id)

                    if entry.module:
                        if entry.module not in self._module_index:
                            self._module_index[entry.module] = []
                        self._module_index[entry.module].append(entry.entry_id)

                except Exception as e:
                    print(f"Error loading change entry: {e}")

            # Sort by date (newest first)
            self._entries.sort(key=lambda e: e.created_at, reverse=True)

        except Exception as e:
            print(f"Error loading change log: {e}")

    def _save(self) -> None:
        """Save change entries to storage."""
        self._workspace_path.mkdir(parents=True, exist_ok=True)

        data = {
            "entries": [e.to_dict() for e in self._entries],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_summary(),
        }

        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving change log: {e}")

    def add_entry(self, entry: ChangeEntry) -> None:
        """Add a change entry to the log.

        Args:
            entry: The change entry to add
        """
        self._entries.append(entry)

        # Update indexes
        if entry.version:
            if entry.version not in self._version_index:
                self._version_index[entry.version] = []
            self._version_index[entry.version].append(entry.entry_id)

        type_key = entry.change_type.value
        if type_key not in self._type_index:
            self._type_index[type_key] = []
        self._type_index[type_key].append(entry.entry_id)

        if entry.module:
            if entry.module not in self._module_index:
                self._module_index[entry.module] = []
            self._module_index[entry.module].append(entry.entry_id)

        # Sort by date (newest first)
        self._entries.sort(key=lambda e: e.created_at, reverse=True)

        self._save()
        self._update_markdown()

    def remove_entry(self, entry_id: str) -> bool:
        """Remove a change entry from the log.

        Args:
            entry_id: The ID of the entry to remove

        Returns:
            True if the entry was found and removed, False otherwise
        """
        for i, entry in enumerate(self._entries):
            if entry.entry_id == entry_id:
                # Remove from indexes
                if entry.version and entry.version in self._version_index:
                    self._version_index[entry.version] = [
                        eid for eid in self._version_index[entry.version] if eid != entry_id
                    ]

                type_key = entry.change_type.value
                if type_key in self._type_index:
                    self._type_index[type_key] = [
                        eid for eid in self._type_index[type_key] if eid != entry_id
                    ]

                if entry.module and entry.module in self._module_index:
                    self._module_index[entry.module] = [
                        eid for eid in self._module_index[entry.module] if eid != entry_id
                    ]

                self._entries.pop(i)
                self._save()
                self._update_markdown()
                return True

        return False

    def get_entry(self, entry_id: str) -> Optional[ChangeEntry]:
        """Get a change entry by ID.

        Args:
            entry_id: The ID of the entry

        Returns:
            The ChangeEntry if found, None otherwise
        """
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    def list_entries(
        self,
        change_type: Optional[ChangeType] = None,
        scope: Optional[ChangeScope] = None,
        version: Optional[str] = None,
        module: Optional[str] = None,
        author: Optional[str] = None,
        limit: Optional[int] = None,
        since: Optional[str] = None,
    ) -> List[ChangeEntry]:
        """List change entries with optional filters.

        Args:
            change_type: Filter by change type
            scope: Filter by scope
            version: Filter by version
            module: Filter by module
            author: Filter by author
            limit: Maximum number of results
            since: Filter by date (ISO format)

        Returns:
            List of matching ChangeEntry objects
        """
        entries = list(self._entries)

        if change_type:
            entries = [e for e in entries if e.change_type == change_type]

        if scope:
            entries = [e for e in entries if e.scope == scope]

        if version:
            if version in self._version_index:
                version_entry_ids = set(self._version_index[version])
                entries = [e for e in entries if e.entry_id in version_entry_ids]

        if module:
            if module in self._module_index:
                module_entry_ids = set(self._module_index[module])
                entries = [e for e in entries if e.entry_id in module_entry_ids]

        if author:
            entries = [e for e in entries if e.author == author]

        if since:
            entries = [e for e in entries if e.created_at >= since]

        if limit:
            entries = entries[:limit]

        return entries

    def get_entries_by_version(self, version: str) -> List[ChangeEntry]:
        """Get all entries for a specific version.

        Args:
            version: The version string

        Returns:
            List of ChangeEntry objects
        """
        if version not in self._version_index:
            return []

        entry_ids = set(self._version_index[version])
        return [e for e in self._entries if e.entry_id in entry_ids]

    def get_latest_version(self) -> Optional[str]:
        """Get the latest version from the change log.

        Returns:
            The latest version string, or None if no versions exist
        """
        if not self._version_index:
            return None

        # Get all versions and find the highest
        versions = list(self._version_index.keys())
        # Simple semantic version comparison (for basic version strings like "1.0.0")
        versions.sort(reverse=True)
        return versions[0] if versions else None

    def get_versions(self) -> List[str]:
        """Get all unique versions from the change log.

        Returns:
            List of version strings (sorted newest first)
        """
        return sorted(self._version_index.keys(), reverse=True)

    @property
    def count(self) -> int:
        """Get the total number of entries."""
        return len(self._entries)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the change log.

        Returns:
            Summary dictionary
        """
        by_type: Dict[str, int] = {}
        by_scope: Dict[str, int] = {}
        by_author: Dict[str, int] = {}

        for entry in self._entries:
            # By type
            type_key = entry.change_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

            # By scope
            scope_key = entry.scope.value
            by_scope[scope_key] = by_scope.get(scope_key, 0) + 1

            # By author
            by_author[entry.author] = by_author.get(entry.author, 0) + 1

        return {
            "total_entries": self.count,
            "by_type": by_type,
            "by_scope": by_scope,
            "by_author": by_author,
            "total_versions": len(self._version_index),
            "latest_version": self.get_latest_version(),
        }

    def _update_markdown(self) -> None:
        """Update the markdown change log file."""
        lines = [
            f"# {self._workspace_path.name or 'Freya'} Change Log",
            "",
            "All notable changes to this project will be documented in this file.",
            "",
        ]

        # Group by version
        versions = sorted(self._version_index.keys(), reverse=True)

        for version in versions:
            if not version:
                version = "Unreleased"

            lines.append(f"## [{version}]")
            lines.append("")

            entries = self.get_entries_by_version(version)

            # Group by type
            type_groups: Dict[str, List[ChangeEntry]] = {}
            for entry in entries:
                type_key = entry.change_type.value
                if type_key not in type_groups:
                    type_groups[type_key] = []
                type_groups[type_key].append(entry)

            for type_key, type_entries in type_groups.items():
                type_label = type_key.replace("_", " ").title()
                lines.append(f"### {type_label}")
                lines.append("")

                for entry in type_entries:
                    scope_label = entry.scope.value.upper()
                    lines.append(f"- **{scope_label}**: {entry.title}")
                    if entry.description:
                        # Wrap description
                        for desc_line in entry.description.split("\n"):
                            lines.append(f"  {desc_line.strip()}")
                    if entry.related_pr:
                        lines.append(f"  (PR: #{entry.related_pr})")
                    if entry.related_issue:
                        lines.append(f"  (Issue: #{entry.related_issue})")
                    lines.append("")

            lines.append("")

        # Write to file
        try:
            self._workspace_path.mkdir(parents=True, exist_ok=True)
            with open(self._markdown_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            print(f"Error updating markdown change log: {e}")

    def clear(self) -> None:
        """Clear all change entries."""
        self._entries = []
        self._version_index = {}
        self._type_index = {}
        self._module_index = {}
        try:
            self._storage_path.unlink()
            self._markdown_path.unlink()
        except FileNotFoundError:
            pass

    def export_to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary."""
        return {
            "entries": [e.to_dict() for e in self._entries],
            "summary": self.get_summary(),
            "versions": self.get_versions(),
        }

    def import_from_dict(self, data: Dict[str, Any]) -> None:
        """Import data from a dictionary."""
        self._entries = []
        self._version_index = {}
        self._type_index = {}
        self._module_index = {}

        for entry_data in data.get("entries", []):
            try:
                entry = ChangeEntry.from_dict(entry_data)
                self._entries.append(entry)

                # Update indexes
                if entry.version:
                    if entry.version not in self._version_index:
                        self._version_index[entry.version] = []
                    self._version_index[entry.version].append(entry.entry_id)

                type_key = entry.change_type.value
                if type_key not in self._type_index:
                    self._type_index[type_key] = []
                self._type_index[type_key].append(entry.entry_id)

                if entry.module:
                    if entry.module not in self._module_index:
                        self._module_index[entry.module] = []
                    self._module_index[entry.module].append(entry.entry_id)

            except Exception as e:
                print(f"Error importing change entry: {e}")

        # Sort by date (newest first)
        self._entries.sort(key=lambda e: e.created_at, reverse=True)

        self._save()
        self._update_markdown()

    def log_feature(
        self,
        title: str,
        description: str = "",
        module: str = "",
        files_changed: Optional[List[str]] = None,
        author: str = "system",
        version: str = "",
        scope: ChangeScope = ChangeScope.MINOR,
        **kwargs,
    ) -> ChangeEntry:
        """Convenience method to log a feature addition.

        Args:
            title: Title of the feature
            description: Description of the feature
            module: Module affected
            files_changed: List of files changed
            author: Author of the change
            version: Version this change applies to
            scope: Scope of the change
            **kwargs: Additional metadata

        Returns:
            The created ChangeEntry
        """
        entry = ChangeEntry(
            title=title,
            description=description,
            change_type=ChangeType.FEATURE,
            scope=scope,
            module=module,
            files_changed=files_changed or [],
            author=author,
            version=version,
            metadata=kwargs.get("metadata", {}),
        )
        self.add_entry(entry)
        return entry

    def log_bug_fix(
        self,
        title: str,
        description: str = "",
        module: str = "",
        files_changed: Optional[List[str]] = None,
        author: str = "system",
        version: str = "",
        related_issue: Optional[str] = None,
        **kwargs,
    ) -> ChangeEntry:
        """Convenience method to log a bug fix.

        Args:
            title: Title of the bug fix
            description: Description of the bug fix
            module: Module affected
            files_changed: List of files changed
            author: Author of the change
            version: Version this change applies to
            related_issue: Related issue number
            **kwargs: Additional metadata

        Returns:
            The created ChangeEntry
        """
        entry = ChangeEntry(
            title=title,
            description=description,
            change_type=ChangeType.BUG_FIX,
            scope=ChangeScope.PATCH,
            module=module,
            files_changed=files_changed or [],
            author=author,
            version=version,
            related_issue=related_issue,
            metadata=kwargs.get("metadata", {}),
        )
        self.add_entry(entry)
        return entry

    def log_refactor(
        self,
        title: str,
        description: str = "",
        module: str = "",
        files_changed: Optional[List[str]] = None,
        author: str = "system",
        version: str = "",
        **kwargs,
    ) -> ChangeEntry:
        """Convenience method to log a refactoring.

        Args:
            title: Title of the refactoring
            description: Description of the refactoring
            module: Module affected
            files_changed: List of files changed
            author: Author of the change
            version: Version this change applies to
            **kwargs: Additional metadata

        Returns:
            The created ChangeEntry
        """
        entry = ChangeEntry(
            title=title,
            description=description,
            change_type=ChangeType.REFACTOR,
            scope=ChangeScope.MINOR,
            module=module,
            files_changed=files_changed or [],
            author=author,
            version=version,
            metadata=kwargs.get("metadata", {}),
        )
        self.add_entry(entry)
        return entry
