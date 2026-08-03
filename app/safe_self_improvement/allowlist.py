"""
File Allowlist and Denylist Management.

Controls which files can be modified by autonomous self-improvement operations.
"""

import fnmatch
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json

from app.safe_self_improvement.models import (
    FileModification,
    ImprovementCandidate,
    ModificationType,
    RiskLevel,
)
from app.core.logger import logger


@dataclass
class AllowlistEntry:
    """An entry in the file allowlist."""

    pattern: str
    description: str = ""
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    added_by: str = "system"
    tags: List[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.NONE  # Override default risk for this pattern

    def matches(self, file_path: str) -> bool:
        """Check if a file path matches this allowlist pattern."""
        # Normalize path
        normalized = file_path.replace("\\", "/")
        return fnmatch.fnmatch(normalized, self.pattern) or fnmatch.fnmatch(
            Path(normalized).name, self.pattern
        )


@dataclass
class DenylistEntry:
    """An entry in the file denylist."""

    pattern: str
    description: str = ""
    reason: str = ""  # Why this is denied
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    added_by: str = "system"
    severity: str = "error"  # error, warning

    def matches(self, file_path: str) -> bool:
        """Check if a file path matches this denylist pattern."""
        normalized = file_path.replace("\\", "/")
        return fnmatch.fnmatch(normalized, self.pattern) or fnmatch.fnmatch(
            Path(normalized).name, self.pattern
        )


class AllowlistManager:
    """
    Manages file allowlists and denylists for safe self-improvement.

    The allowlist defines which files CAN be modified.
    The denylist defines which files CANNOT be modified (takes precedence).
    """

    def __init__(
        self,
        enable_allowlist: bool = True,
        enable_denylist: bool = True,
        default_allowlist_paths: Optional[List[str]] = None,
        default_denylist_paths: Optional[List[str]] = None,
        storage_path: Optional[str] = None,
    ):
        self.enable_allowlist = enable_allowlist
        self.enable_denylist = enable_denylist
        self._allowlist: Dict[str, AllowlistEntry] = {}
        self._denylist: Dict[str, DenylistEntry] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._stats = {
            "allowlist_checks": 0,
            "denylist_blocks": 0,
            "allowlist_allows": 0,
        }

        # Load defaults
        if default_allowlist_paths:
            for path in default_allowlist_paths:
                self.add_allowlist(path, "Default allowlist entry")

        if default_denylist_paths:
            for path in default_denylist_paths:
                self.add_denylist(path, "Default denylist entry", "System protection")

        # Load from storage if provided
        if self._storage_path:
            self._load()

    def add_allowlist(
        self,
        pattern: str,
        description: str = "",
        added_by: str = "system",
        tags: Optional[List[str]] = None,
        risk_level: RiskLevel = RiskLevel.NONE,
    ) -> str:
        """Add a pattern to the allowlist."""
        with self._lock:
            entry_id = f"allow_{len(self._allowlist)}_{abs(hash(pattern)) % 10000:04d}"
            entry = AllowlistEntry(
                pattern=pattern,
                description=description,
                added_by=added_by,
                tags=tags or [],
                risk_level=risk_level,
            )
            self._allowlist[entry_id] = entry
            self._save()
            logger.info(f"[AllowlistManager] Added allowlist pattern: {pattern}")
            return entry_id

    def add_denylist(
        self,
        pattern: str,
        description: str = "",
        reason: str = "",
        added_by: str = "system",
        severity: str = "error",
    ) -> str:
        """Add a pattern to the denylist."""
        with self._lock:
            entry_id = f"deny_{len(self._denylist)}_{abs(hash(pattern)) % 10000:04d}"
            entry = DenylistEntry(
                pattern=pattern,
                description=description,
                reason=reason,
                added_by=added_by,
                severity=severity,
            )
            self._denylist[entry_id] = entry
            self._save()
            logger.info(f"[AllowlistManager] Added denylist pattern: {pattern}")
            return entry_id

    def remove_allowlist(self, entry_id: str) -> bool:
        """Remove an entry from the allowlist."""
        with self._lock:
            if entry_id in self._allowlist:
                del self._allowlist[entry_id]
                self._save()
                return True
            return False

    def remove_denylist(self, entry_id: str) -> bool:
        """Remove an entry from the denylist."""
        with self._lock:
            if entry_id in self._denylist:
                del self._denylist[entry_id]
                self._save()
                return True
            return False

    def check_file_allowed(self, file_path: str) -> tuple[bool, str]:
        """
        Check if a file is allowed to be modified.

        Returns:
            tuple: (allowed, reason)
        """
        with self._lock:
            self._stats["allowlist_checks"] += 1

            # Check denylist first (takes precedence)
            if self.enable_denylist:
                for entry in self._denylist.values():
                    if entry.matches(file_path):
                        self._stats["denylist_blocks"] += 1
                        return (
                            False,
                            f"File blocked by denylist: {entry.pattern} ({entry.reason})",
                        )

            # If allowlist is disabled, all non-denied files are allowed
            if not self.enable_allowlist:
                self._stats["allowlist_allows"] += 1
                return True, "Allowlist disabled, file not in denylist"

            # Check allowlist
            for entry in self._allowlist.values():
                if entry.matches(file_path):
                    self._stats["allowlist_allows"] += 1
                    return True, f"File allowed by allowlist: {entry.pattern}"

            # Not in allowlist
            return False, "File not in allowlist"

    def check_modification_allowed(
        self, modification: FileModification
    ) -> tuple[bool, str]:
        """Check if a specific modification is allowed."""
        return self.check_file_allowed(modification.file_path)

    def check_candidate_allowed(
        self, candidate: ImprovementCandidate
    ) -> tuple[bool, List[str]]:
        """Check if all modifications in a candidate are allowed."""
        reasons = []
        for mod in candidate.modifications:
            allowed, reason = self.check_modification_allowed(mod)
            if not allowed:
                reasons.append(f"{mod.file_path}: {reason}")
        return len(reasons) == 0, reasons

    def get_allowlist_entries(self) -> List[AllowlistEntry]:
        """Get all allowlist entries."""
        with self._lock:
            return list(self._allowlist.values())

    def get_denylist_entries(self) -> List[DenylistEntry]:
        """Get all denylist entries."""
        with self._lock:
            return list(self._denylist.values())

    def get_matching_allowlist(self, file_path: str) -> Optional[AllowlistEntry]:
        """Get the allowlist entry that matches a file path."""
        with self._lock:
            for entry in self._allowlist.values():
                if entry.matches(file_path):
                    return entry
            return None

    def get_matching_denylist(self, file_path: str) -> Optional[DenylistEntry]:
        """Get the denylist entry that matches a file path."""
        with self._lock:
            for entry in self._denylist.values():
                if entry.matches(file_path):
                    return entry
            return None

    def _save(self) -> None:
        """Save allowlist/denylist to storage."""
        if not self._storage_path:
            return

        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "allowlist": [
                    {
                        "id": eid,
                        "pattern": e.pattern,
                        "description": e.description,
                        "added_at": e.added_at,
                        "added_by": e.added_by,
                        "tags": e.tags,
                        "risk_level": e.risk_level.value,
                    }
                    for eid, e in self._allowlist.items()
                ],
                "denylist": [
                    {
                        "id": eid,
                        "pattern": e.pattern,
                        "description": e.description,
                        "reason": e.reason,
                        "added_at": e.added_at,
                        "added_by": e.added_by,
                        "severity": e.severity,
                    }
                    for eid, e in self._denylist.items()
                ],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            temp_path = path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(path)
        except Exception as e:
            logger.error(f"[AllowlistManager] Failed to save: {e}")

    def _load(self) -> None:
        """Load allowlist/denylist from storage."""
        if not self._storage_path:
            return

        try:
            path = Path(self._storage_path)
            if not path.exists():
                return

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data.get("allowlist", []):
                entry = AllowlistEntry(
                    pattern=item["pattern"],
                    description=item.get("description", ""),
                    added_at=item.get("added_at", datetime.now(timezone.utc).isoformat()),
                    added_by=item.get("added_by", "system"),
                    tags=item.get("tags", []),
                    risk_level=RiskLevel(item.get("risk_level", "none")),
                )
                self._allowlist[item["id"]] = entry

            for item in data.get("denylist", []):
                entry = DenylistEntry(
                    pattern=item["pattern"],
                    description=item.get("description", ""),
                    reason=item.get("reason", ""),
                    added_at=item.get("added_at", datetime.now(timezone.utc).isoformat()),
                    added_by=item.get("added_by", "system"),
                    severity=item.get("severity", "error"),
                )
                self._denylist[item["id"]] = entry

            logger.info(
                f"[AllowlistManager] Loaded {len(self._allowlist)} allowlist and "
                f"{len(self._denylist)} denylist entries"
            )
        except Exception as e:
            logger.error(f"[AllowlistManager] Failed to load: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics."""
        with self._lock:
            return {
                **self._stats,
                "allowlist_size": len(self._allowlist),
                "denylist_size": len(self._denylist),
                "allowlist_enabled": self.enable_allowlist,
                "denylist_enabled": self.enable_denylist,
            }

    def clear(self) -> None:
        """Clear all entries (use with caution)."""
        with self._lock:
            self._allowlist.clear()
            self._denylist.clear()
            self._save()


# Convenience functions
def create_default_allowlist_manager(storage_path: Optional[str] = None) -> AllowlistManager:
    """Create an AllowlistManager with sensible defaults."""
    default_allowlist = [
        "app/**/*.py",
        "tests/**/*.py",
        "scripts/**/*.py",
        "*.py",
        "*.md",
        "*.txt",
        "*.json",
        "*.yaml",
        "*.yml",
        "*.toml",
        "*.cfg",
        "*.ini",
    ]

    default_denylist = [
        "**/__pycache__/**",
        "**/.git/**",
        "**/.venv/**",
        "**/venv/**",
        "**/node_modules/**",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.pyd",
        "**/.pytest_cache/**",
        "**/.mypy_cache/**",
        "**/data/memory/**",
        "**/data/vector_db/**",
        "**/data/checkpoints/**",
        "*.key",
        "*.pem",
        "*.crt",
        "*.csr",
        "**/secrets/**",
        "**/credentials/**",
        "**/.env*",
        "**/.env.*",
        "**/config/secrets.*",
        "**/*.sqlite*",
        "**/*.db",
        "**/logs/**",
        "**/output/**",
        "**/dist/**",
        "**/build/**",
    ]

    return AllowlistManager(
        enable_allowlist=True,
        enable_denylist=True,
        default_allowlist_paths=default_allowlist,
        default_denylist_paths=default_denylist,
        storage_path=storage_path,
    )