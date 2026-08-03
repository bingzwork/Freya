"""
Safe Modification Boundaries.

Defines and enforces boundaries for self-improvement modifications:
- Maximum files per improvement
- Maximum lines per modification
- Maximum total modifications per session
- File type restrictions
- Size limits
"""

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
class BoundaryRule:
    """A single boundary rule."""

    name: str
    description: str
    check_func: callable
    severity: str = "error"  # error, warning
    enabled: bool = True

    def check(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Run the boundary check."""
        if not self.enabled:
            return True, ""
        try:
            return self.check_func(candidate)
        except Exception as e:
            logger.error(f"[BoundaryManager] Rule '{self.name}' error: {e}")
            return False, f"Boundary check error: {e}"


@dataclass
class ModificationBoundary:
    """
    Represents a boundary for modifications.

    Boundaries define limits on what modifications can be made.
    """

    # File count limits
    max_files_per_improvement: int = 10
    max_files_per_session: int = 50

    # Size limits
    max_lines_per_modification: int = 500
    max_total_lines_per_improvement: int = 2000
    max_file_size_bytes: int = 1024 * 1024  # 1MB

    # Modification type restrictions
    allowed_modification_types: Set[ModificationType] = field(
        default_factory=lambda: {
            ModificationType.CREATE,
            ModificationType.MODIFY,
            ModificationType.RENAME,
        }
    )
    allow_delete: bool = False
    allow_move: bool = False

    # File type restrictions
    allowed_extensions: Set[str] = field(
        default_factory=lambda: {
            ".py",
            ".js",
            ".ts",
            ".java",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".cfg",
            ".ini",
            ".html",
            ".css",
            ".scss",
            ".sql",
            ".sh",
            ".bash",
            ".ps1",
            ".dockerfile",
            ".dockerignore",
            ".gitignore",
        }
    )
    forbidden_extensions: Set[str] = field(
        default_factory=lambda: {
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".dat",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".pkl",
            ".pickle",
            ".onnx",
            ".pt",
            ".pth",
            ".h5",
            ".pb",
            ".model",
            ".weights",
            ".key",
            ".pem",
            ".crt",
            ".csr",
            ".pfx",
            ".p12",
        }
    )

    # Path restrictions
    forbidden_paths: Set[str] = field(
        default_factory=lambda: {
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            ".mypy_cache",
            "data/memory",
            "data/vector_db",
            "data/checkpoints",
            "secrets",
            "credentials",
            "logs",
            "output",
            "dist",
            "build",
            ".github",
            ".gitlab",
        }
    )
    forbidden_patterns: List[str] = field(
        default_factory=lambda: [
            "*.key",
            "*.pem",
            "*.crt",
            "*.csr",
            "*.env*",
            "config/secrets.*",
            "*.sqlite*",
            "*.db",
        ]
    )

    # Content restrictions
    forbidden_content_patterns: List[str] = field(
        default_factory=lambda: [
            r"password\s*=\s*[\"']",
            r"api_key\s*=\s*[\"']",
            r"secret\s*=\s*[\"']",
            r"token\s*=\s*[\"']",
            r"private_key",
        ]
    )

    # Risk limits
    max_risk_level: RiskLevel = RiskLevel.MEDIUM

    # Session tracking
    session_modifications: int = 0
    session_start: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BoundaryManager:
    """
    Manages and enforces modification boundaries.

    Tracks session state and validates candidates against boundaries.
    """

    def __init__(
        self,
        boundary: Optional[ModificationBoundary] = None,
        storage_path: Optional[str] = None,
    ):
        self.boundary = boundary or ModificationBoundary()
        self._storage_path = storage_path
        self._lock = threading.RLock()
        self._session_modifications = 0
        self._session_start = datetime.now(timezone.utc).isoformat()
        self._rules: List[BoundaryRule] = []
        self._violations: List[Dict[str, Any]] = []
        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Set up default boundary rules."""
        self._rules = [
            BoundaryRule(
                name="max_files",
                description="Maximum files per improvement",
                check_func=self._check_max_files,
            ),
            BoundaryRule(
                name="max_lines_per_mod",
                description="Maximum lines per modification",
                check_func=self._check_max_lines_per_mod,
            ),
            BoundaryRule(
                name="max_total_lines",
                description="Maximum total lines per improvement",
                check_func=self._check_max_total_lines,
            ),
            BoundaryRule(
                name="modification_types",
                description="Allowed modification types",
                check_func=self._check_modification_types,
            ),
            BoundaryRule(
                name="file_extensions",
                description="Allowed file extensions",
                check_func=self._check_file_extensions,
            ),
            BoundaryRule(
                name="forbidden_paths",
                description="Forbidden paths",
                check_func=self._check_forbidden_paths,
            ),
            BoundaryRule(
                name="forbidden_patterns",
                description="Forbidden file patterns",
                check_func=self._check_forbidden_patterns,
            ),
            BoundaryRule(
                name="forbidden_content",
                description="Forbidden content patterns",
                check_func=self._check_forbidden_content,
                severity="warning",
            ),
            BoundaryRule(
                name="max_risk",
                description="Maximum risk level",
                check_func=self._check_max_risk,
            ),
            BoundaryRule(
                name="session_limit",
                description="Session modification limit",
                check_func=self._check_session_limit,
            ),
            BoundaryRule(
                name="file_size",
                description="Maximum file size",
                check_func=self._check_file_size,
            ),
        ]

    def validate_candidate(
        self, candidate: ImprovementCandidate
    ) -> tuple[bool, List[str]]:
        """
        Validate an improvement candidate against all boundaries.

        Returns:
            tuple: (is_valid, list_of_violations)
        """
        with self._lock:
            violations = []

            for rule in self._rules:
                if not rule.enabled:
                    continue
                valid, message = rule.check(candidate)
                if not valid:
                    violation_msg = f"{rule.name}: {message}"
                    violations.append(violation_msg)
                    self._record_violation(rule.name, candidate.id, violation_msg)

            # Update session tracking
            if not violations:
                self._session_modifications += len(candidate.modifications)

            return len(violations) == 0, violations

    def validate_modification(
        self, modification: FileModification
    ) -> tuple[bool, str]:
        """Validate a single modification."""
        # Create a minimal candidate for checking
        from app.safe_self_improvement.models import ImprovementCandidate

        candidate = ImprovementCandidate(
            id="temp",
            modifications=[modification],
            affected_files=[modification.file_path],
        )
        valid, violations = self.validate_candidate(candidate)
        return valid, violations[0] if violations else ""

    def _check_max_files(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check maximum files per improvement."""
        if len(candidate.modifications) > self.boundary.max_files_per_improvement:
            return (
                False,
                f"Too many files: {len(candidate.modifications)} > "
                f"{self.boundary.max_files_per_improvement}",
            )
        return True, ""

    def _check_max_lines_per_mod(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check maximum lines per modification."""
        for mod in candidate.modifications:
            lines = self._count_lines(mod)
            if lines > self.boundary.max_lines_per_modification:
                return (
                    False,
                    f"Modification {mod.file_path} has {lines} lines "
                    f"(max: {self.boundary.max_lines_per_modification})",
                )
        return True, ""

    def _check_max_total_lines(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check maximum total lines per improvement."""
        total_lines = sum(self._count_lines(mod) for mod in candidate.modifications)
        if total_lines > self.boundary.max_total_lines_per_improvement:
            return (
                False,
                f"Total lines {total_lines} exceeds limit "
                f"({self.boundary.max_total_lines_per_improvement})",
            )
        return True, ""

    def _check_modification_types(
        self, candidate: ImprovementCandidate
    ) -> tuple[bool, str]:
        """Check allowed modification types."""
        for mod in candidate.modifications:
            if mod.modification_type == ModificationType.DELETE and not self.boundary.allow_delete:
                return False, f"DELETE not allowed: {mod.file_path}"
            if mod.modification_type == ModificationType.MOVE and not self.boundary.allow_move:
                return False, f"MOVE not allowed: {mod.file_path}"
            if mod.modification_type not in self.boundary.allowed_modification_types:
                return False, f"Modification type {mod.modification_type.value} not allowed"
        return True, ""

    def _check_file_extensions(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check allowed file extensions."""
        for mod in candidate.modifications:
            ext = Path(mod.file_path).suffix.lower()
            if ext in self.boundary.forbidden_extensions:
                return False, f"Forbidden extension: {ext} for {mod.file_path}"
            if self.boundary.allowed_extensions and ext not in self.boundary.allowed_extensions:
                # Only warn for unknown extensions, don't block
                pass
        return True, ""

    def _check_forbidden_paths(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check forbidden paths."""
        import fnmatch

        for mod in candidate.modifications:
            normalized = mod.file_path.replace("\\", "/")
            parts = normalized.split("/")
            for part in parts:
                if part in self.boundary.forbidden_paths:
                    return False, f"Forbidden path component: {part} in {mod.file_path}"
        return True, ""

    def _check_forbidden_patterns(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check forbidden file patterns."""
        import fnmatch

        for mod in candidate.modifications:
            normalized = mod.file_path.replace("\\", "/")
            for pattern in self.boundary.forbidden_patterns:
                if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
                    Path(normalized).name, pattern
                ):
                    return False, f"Forbidden pattern {pattern} matches {mod.file_path}"
        return True, ""

    def _check_forbidden_content(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check for forbidden content patterns."""
        import re

        for mod in candidate.modifications:
            content = mod.new_content or ""
            for pattern in self.boundary.forbidden_content_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    return False, f"Forbidden content pattern '{pattern}' in {mod.file_path}"
        return True, ""

    def _check_max_risk(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check maximum risk level."""
        if candidate.estimated_risk > self.boundary.max_risk_level:
            return (
                False,
                f"Risk level {candidate.estimated_risk.value} exceeds maximum "
                f"{self.boundary.max_risk_level.value}",
            )
        return True, ""

    def _check_session_limit(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check session modification limit."""
        projected = self._session_modifications + len(candidate.modifications)
        if projected > self.boundary.max_files_per_session:
            return (
                False,
                f"Session limit exceeded: {projected} > "
                f"{self.boundary.max_files_per_session}",
            )
        return True, ""

    def _check_file_size(self, candidate: ImprovementCandidate) -> tuple[bool, str]:
        """Check file size limits."""
        for mod in candidate.modifications:
            content = mod.new_content or ""
            size = len(content.encode("utf-8"))
            if size > self.boundary.max_file_size_bytes:
                return (
                    False,
                    f"File {mod.file_path} size {size} bytes exceeds limit "
                    f"({self.boundary.max_file_size_bytes} bytes)",
                )
        return True, ""

    def _count_lines(self, modification: FileModification) -> int:
        """Count lines in a modification."""
        content = modification.new_content or ""
        if not content:
            return 0
        return len(content.splitlines())

    def _record_violation(self, rule_name: str, candidate_id: str, message: str) -> None:
        """Record a boundary violation."""
        import uuid

        violation = {
            "id": f"viol_{uuid.uuid4().hex[:8]}",
            "rule": rule_name,
            "candidate_id": candidate_id,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._violations.append(violation)
        # Keep last 1000 violations
        if len(self._violations) > 1000:
            self._violations = self._violations[-1000:]

    def get_violations(
        self, limit: int = 100, candidate_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent violations."""
        with self._lock:
            violations = self._violations
            if candidate_id:
                violations = [v for v in violations if v["candidate_id"] == candidate_id]
            violations.sort(key=lambda v: v["timestamp"], reverse=True)
            return violations[:limit]

    def reset_session(self) -> None:
        """Reset session counters."""
        with self._lock:
            self._session_modifications = 0
            self._session_start = datetime.now(timezone.utc).isoformat()
            self.boundary.session_modifications = 0
            self.boundary.session_start = self._session_start

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        with self._lock:
            return {
                "session_modifications": self._session_modifications,
                "session_start": self._session_start,
                "max_files_per_session": self.boundary.max_files_per_session,
                "remaining": self.boundary.max_files_per_session - self._session_modifications,
            }

    def add_rule(self, rule: BoundaryRule) -> None:
        """Add a custom boundary rule."""
        with self._lock:
            self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a boundary rule by name."""
        with self._lock:
            for i, rule in enumerate(self._rules):
                if rule.name == name:
                    self._rules.pop(i)
                    return True
            return False

    def enable_rule(self, name: str) -> bool:
        """Enable a boundary rule."""
        with self._lock:
            for rule in self._rules:
                if rule.name == name:
                    rule.enabled = True
                    return True
            return False

    def disable_rule(self, name: str) -> bool:
        """Disable a boundary rule."""
        with self._lock:
            for rule in self._rules:
                if rule.name == name:
                    rule.enabled = False
                    return True
            return False

    def get_rules(self) -> List[Dict[str, Any]]:
        """Get all boundary rules."""
        with self._lock:
            return [
                {
                    "name": r.name,
                    "description": r.description,
                    "severity": r.severity,
                    "enabled": r.enabled,
                }
                for r in self._rules
            ]


def create_default_boundary_manager(
    storage_path: Optional[str] = None,
    strict_mode: bool = False,
) -> BoundaryManager:
    """Create a BoundaryManager with sensible defaults."""
    boundary = ModificationBoundary()

    if strict_mode:
        boundary.max_files_per_improvement = 5
        boundary.max_lines_per_modification = 200
        boundary.max_total_lines_per_improvement = 1000
        boundary.max_files_per_session = 20
        boundary.max_risk_level = RiskLevel.LOW
        boundary.allow_delete = False
        boundary.allow_move = False

    return BoundaryManager(boundary=boundary, storage_path=storage_path)