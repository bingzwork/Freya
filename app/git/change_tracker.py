"""Change tracker for monitoring file changes.

This module provides functionality for tracking changes to files
in the repository, including detection of modifications, additions, and deletions.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid


class ChangeType(Enum):
    """Types of file changes."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    UNTRACKED = "untracked"


@dataclass
class FileChange:
    """Represents a change to a file."""
    file_path: str
    change_type: ChangeType
    old_path: Optional[str] = None
    hash_before: str = ""
    hash_after: str = ""
    size_before: int = 0
    size_after: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    committed: bool = False
    commit_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "change_type": self.change_type.value,
            "old_path": self.old_path,
            "hash_before": self.hash_before,
            "hash_after": self.hash_after,
            "size_before": self.size_before,
            "size_after": self.size_after,
            "timestamp": self.timestamp,
            "committed": self.committed,
            "commit_hash": self.commit_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileChange":
        """Create from dictionary."""
        change = cls(
            file_path=data.get("file_path", ""),
            change_type=ChangeType(data.get("change_type", "modified")),
            old_path=data.get("old_path"),
            hash_before=data.get("hash_before", ""),
            hash_after=data.get("hash_after", ""),
            size_before=data.get("size_before", 0),
            size_after=data.get("size_after", 0),
            timestamp=data.get("timestamp", ""),
            committed=data.get("committed", False),
            commit_hash=data.get("commit_hash", ""),
        )
        return change

    def __str__(self) -> str:
        change_label = self.change_type.value.upper()
        return f"[{change_label}] {self.file_path}"


@dataclass
class ChangeTracker:
    """Tracks changes to files in a directory."""

    workspace: Optional[str] = None
    storage_file: str = ".change_tracker.json"
    include_patterns: List[str] = field(default_factory=lambda: ["*.py", "*.md", "*.txt", "*.json", "*.yaml", "*.yml"])
    exclude_patterns: List[str] = field(default_factory=lambda: [".git", ".venv", "venv", "node_modules", ".mypy_cache", "__pycache__", ".pytest_cache", ".vscode"])
    polling_interval: float = 1.0

    def __post_init__(self):
        self._workspace_path = Path(self.workspace) if self.workspace else Path.cwd()
        self._storage_path = self._workspace_path / self.storage_file
        self._file_hashes: Dict[str, str] = {}
        self._changes: Dict[str, FileChange] = {}
        self._last_scan: float = 0
        self._load()

    def _is_excluded(self, path: Path) -> bool:
        """Check if a path should be excluded."""
        path_str = str(path)

        # Check exclude patterns
        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return True

        # Check if it's a hidden file (starts with .)
        if path.name.startswith(".") and path.name != ".change_tracker.json":
            return True

        return False

    def _is_included(self, path: Path) -> bool:
        """Check if a path should be included."""
        if self._is_excluded(path):
            return False

        # Check include patterns
        for pattern in self.include_patterns:
            if pattern.startswith("*") and pattern.endswith("*"):
                # Wildcard on both ends
                ext = pattern[1:]
                if path.name.endswith(ext):
                    return True
            elif pattern.startswith("*"):
                # Wildcard at start
                if path.name.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                # Wildcard at end
                if path.name.startswith(pattern[:-1]):
                    return True
            else:
                if path.name == pattern:
                    return True

        # If no patterns match but it's not excluded, include it
        return not self._is_excluded(path)

    def _compute_hash(self, file_path: Path) -> str:
        """Compute the hash of a file."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()
                return hashlib.sha256(content).hexdigest()[:16]
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    def _get_file_info(self, file_path: Path) -> Tuple[str, int]:
        """Get file hash and size."""
        try:
            stat = file_path.stat()
            file_hash = self._compute_hash(file_path)
            return file_hash, stat.st_size
        except (FileNotFoundError, PermissionError, OSError):
            return "", 0

    def scan(self, force: bool = False) -> List[FileChange]:
        """Scan for file changes.

        Args:
            force: If True, force a rescan even if interval hasn't passed

        Returns:
            List of detected FileChange objects
        """
        current_time = time.time()
        if not force and current_time - self._last_scan < self.polling_interval:
            return list(self._changes.values())

        self._last_scan = current_time

        # Get current state of files
        current_files: Dict[str, Tuple[str, int]] = {}
        new_changes: Dict[str, FileChange] = {}

        # Walk the directory
        for py_file in self._workspace_path.rglob("*"):
            if not self._is_included(py_file):
                continue

            file_str = str(py_file.resolve())
            file_hash, file_size = self._get_file_info(py_file)

            if file_hash:
                current_files[file_str] = (file_hash, file_size)

                # Check if this is a new file or modified
                if file_str not in self._file_hashes:
                    change = FileChange(
                        file_path=file_str,
                        change_type=ChangeType.CREATED if file_str not in self._changes else self._changes[file_str].change_type,
                        hash_after=file_hash,
                        size_after=file_size,
                    )
                    if file_str in self._changes:
                        old_change = self._changes[file_str]
                        change.hash_before = old_change.hash_after
                        change.size_before = old_change.size_after
                    new_changes[file_str] = change
                elif file_hash != self._file_hashes[file_str][0]:
                    old_hash, old_size = self._file_hashes[file_str]
                    change = FileChange(
                        file_path=file_str,
                        change_type=ChangeType.MODIFIED,
                        hash_before=old_hash,
                        hash_after=file_hash,
                        size_before=old_size,
                        size_after=file_size,
                    )
                    new_changes[file_str] = change

        # Check for deleted files
        for file_str in self._file_hashes:
            if file_str not in current_files:
                old_hash, old_size = self._file_hashes[file_str]
                change = FileChange(
                    file_path=file_str,
                    change_type=ChangeType.DELETED,
                    hash_before=old_hash,
                    size_before=old_size,
                )
                new_changes[file_str] = change

        # Update state
        self._file_hashes = current_files.copy()
        self._changes = new_changes.copy()
        self._save()

        return list(self._changes.values())

    def _load(self) -> None:
        """Load state from storage."""
        if not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._file_hashes = data.get("file_hashes", {})
                self._changes = {}
                for change_data in data.get("changes", []):
                    change = FileChange.from_dict(change_data)
                    self._changes[change.file_path] = change
        except Exception as e:
            print(f"Error loading change tracker: {e}")

    def _save(self) -> None:
        """Save state to storage."""
        self._workspace_path.mkdir(parents=True, exist_ok=True)

        data = {
            "file_hashes": self._file_hashes,
            "changes": [c.to_dict() for c in self._changes.values()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving change tracker: {e}")

    def get_changes(self) -> List[FileChange]:
        """Get all tracked changes.

        Returns:
            List of FileChange objects
        """
        return list(self._changes.values())

    def get_change(self, file_path: str) -> Optional[FileChange]:
        """Get a specific change by file path.

        Args:
            file_path: The file path

        Returns:
            FileChange if found, None otherwise
        """
        return self._changes.get(file_path)

    def get_changes_by_type(self, change_type: ChangeType) -> List[FileChange]:
        """Get changes filtered by type.

        Args:
            change_type: The type of change to filter by

        Returns:
            List of FileChange objects
        """
        return [c for c in self._changes.values() if c.change_type == change_type]

    def has_changes(self) -> bool:
        """Check if there are any tracked changes.

        Returns:
            True if there are changes, False otherwise
        """
        return len(self._changes) > 0

    def clear(self) -> None:
        """Clear all tracked changes."""
        self._file_hashes = {}
        self._changes = {}
        try:
            self._storage_path.unlink()
        except FileNotFoundError:
            pass

    def reset(self) -> None:
        """Reset the tracker, accepting current state as baseline."""
        self._file_hashes = {}
        self._changes = {}

        # Rescan to establish new baseline
        for py_file in self._workspace_path.rglob("*"):
            if not self._is_included(py_file):
                continue

            file_str = str(py_file.resolve())
            file_hash, file_size = self._get_file_info(py_file)
            if file_hash:
                self._file_hashes[file_str] = (file_hash, file_size)

        self._save()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of tracked changes.

        Returns:
            Summary dictionary
        """
        by_type: Dict[str, int] = {}
        for change in self._changes.values():
            type_key = change.change_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

        return {
            "total_changes": len(self._changes),
            "by_type": by_type,
            "files_added": by_type.get("created", 0),
            "files_modified": by_type.get("modified", 0),
            "files_deleted": by_type.get("deleted", 0),
            "files_renamed": by_type.get("renamed", 0),
        }

    def mark_committed(self, commit_hash: str = "") -> None:
        """Mark all changes as committed.

        Args:
            commit_hash: The commit hash for these changes
        """
        for change in self._changes.values():
            change.committed = True
            change.commit_hash = commit_hash
            change.timestamp = datetime.now(timezone.utc).isoformat()

        # Reset the changes
        self._changes = {}
        self._save()

    def export_changes(self) -> Dict[str, Any]:
        """Export changes to a dictionary.

        Returns:
            Dictionary with changes data
        """
        return {
            "changes": [c.to_dict() for c in self._changes.values()],
            "summary": self.get_summary(),
        }

    def import_changes(self, data: Dict[str, Any]) -> None:
        """Import changes from a dictionary.

        Args:
            data: Dictionary with changes data
        """
        self._changes = {}
        for change_data in data.get("changes", []):
            change = FileChange.from_dict(change_data)
            self._changes[change.file_path] = change

        self._save()
