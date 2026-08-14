"""
File Allowlists - Centralized file permission system for Freya.

Provides a standardized file access validation layer with:
- Allowed directories management
- Allowed file types/extensions
- Allowed operations (read, write, execute, delete)
- File validation and safe path resolution
- Path normalization and traversal prevention
- Shared allowlist configuration
- Reusable validation APIs
- Audit logging for access attempts
"""

import os
import tempfile
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Union
from fnmatch import fnmatch

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority


class FileOperation(Enum):
    """File operations that can be allowed/denied."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    LIST = "list"
    CREATE = "create"
    MODIFY = "modify"


class PathType(Enum):
    """Types of paths for validation."""
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    ANY = "any"


class AccessDecision(Enum):
    """Result of an access check."""
    ALLOWED = "allowed"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass
class AccessRule:
    """A single access rule for the allowlist."""
    pattern: str  # Glob pattern for path matching
    operations: Set[FileOperation] = field(default_factory=set)
    path_types: Set[PathType] = field(default_factory=lambda: {PathType.ANY})
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)

    def matches(self, path: Path, operation: FileOperation, path_type: PathType) -> bool:
        """Check if this rule matches the given access request."""
        # Check operation
        if operation not in self.operations:
            return False

        # Check path type
        if PathType.ANY not in self.path_types and path_type not in self.path_types:
            return False

        # Check pattern match
        path_str = str(path)
        return fnmatch(path_str, self.pattern) or fnmatch(path.name, self.pattern)

    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern,
            "operations": [op.value for op in self.operations],
            "path_types": [pt.value for pt in self.path_types],
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AccessRule":
        return cls(
            pattern=data["pattern"],
            operations={FileOperation(op) for op in data.get("operations", [])},
            path_types={PathType(pt) for pt in data.get("path_types", ["any"])},
            description=data.get("description", ""),
            tags=data.get("tags", {}),
        )


@dataclass
class FileAllowlistConfig:
    """Configuration for the file allowlist system."""
    # Default behavior
    default_deny: bool = True  # Deny by default, allow only explicit rules
    allow_current_directory: bool = True
    allow_temp_directory: bool = True
    allow_home_directory: bool = False

    # Security
    follow_symlinks: bool = False
    resolve_paths: bool = True  # Resolve paths to absolute before checking
    prevent_traversal: bool = True  # Block ../ and similar

    # Validation
    validate_extensions: bool = True
    allowed_extensions: Set[str] = field(default_factory=lambda: {
        ".py", ".json", ".yaml", ".yml", ".toml", ".txt", ".md", ".rst",
        ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
        ".sql", ".sh", ".bash", ".zsh", ".fish",
        ".dockerfile", ".dockerignore", ".gitignore",
        ".cfg", ".conf", ".ini", ".env",
        ".csv", ".tsv", ".xml", ".yml",
        # Passive document, image, audio, and video artifacts. Execution-capable
        # binaries remain blocked below; specialized capabilities own processing.
        ".pdf", ".doc", ".docx", ".odt", ".rtf",
        ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff",
        ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac",
        ".mp4", ".mov", ".mkv", ".avi", ".webm",
    })
    blocked_extensions: Set[str] = field(default_factory=lambda: {
        ".exe", ".dll", ".so", ".dylib", ".bin",
        ".pyc", ".pyo", ".pyd",
        ".class", ".jar", ".war",
        ".msi", ".deb", ".rpm",
        ".app", ".ipa",
    })

    # Auditing
    log_allowed: bool = True
    log_denied: bool = True
    log_details: bool = True

    def to_dict(self) -> Dict:
        return {
            "default_deny": self.default_deny,
            "allow_current_directory": self.allow_current_directory,
            "allow_temp_directory": self.allow_temp_directory,
            "allow_home_directory": self.allow_home_directory,
            "follow_symlinks": self.follow_symlinks,
            "resolve_paths": self.resolve_paths,
            "prevent_traversal": self.prevent_traversal,
            "validate_extensions": self.validate_extensions,
            "allowed_extensions": list(self.allowed_extensions),
            "blocked_extensions": list(self.blocked_extensions),
            "log_allowed": self.log_allowed,
            "log_denied": self.log_denied,
            "log_details": self.log_details,
        }


@dataclass
class AccessContext:
    """Context for an access check."""
    operation: FileOperation
    path: Path
    path_type: PathType = PathType.ANY
    source: str = ""  # Component requesting access
    metadata: Dict[str, any] = field(default_factory=dict)


@dataclass
class AccessResult:
    """Result of an access check."""
    decision: AccessDecision
    path: Path
    operation: FileOperation
    matched_rule: Optional[AccessRule] = None
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision.value,
            "path": str(self.path),
            "operation": self.operation.value,
            "matched_rule": self.matched_rule.to_dict() if self.matched_rule else None,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class FileAllowlist:
    """
    Centralized file permission system.

    Manages allowlist rules and validates file access requests
    against those rules.
    """

    def __init__(
        self,
        config: Optional[FileAllowlistConfig] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the file allowlist.

        Args:
            config: Allowlist configuration
            event_bus: Optional event bus for audit events
        """
        self.config = config or FileAllowlistConfig()
        self._event_bus = event_bus or get_event_bus()
        self._rules: List[AccessRule] = []
        self._lock = threading.RLock()
        self._initialized = False

        # Statistics
        self._stats = {
            "allowed": 0,
            "denied": 0,
            "requires_approval": 0,
            "errors": 0,
        }
        self._stats_lock = threading.Lock()

        # Default rules
        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Set up default allowlist rules based on config."""
        base_dirs = []

        if self.config.allow_current_directory:
            base_dirs.append(Path.cwd())

        if self.config.allow_temp_directory:
            base_dirs.append(Path(tempfile.gettempdir()))

        if self.config.allow_home_directory:
            base_dirs.append(Path.home())

        for base_dir in base_dirs:
            # Allow read access to base directory
            self.add_rule(AccessRule(
                pattern=str(base_dir / "**"),
                operations={FileOperation.READ, FileOperation.LIST},
                description=f"Default read access to {base_dir}",
                tags={"type": "default", "base_dir": str(base_dir)},
            ))

        self._initialized = True

    def add_rule(self, rule: AccessRule, index: Optional[int] = None) -> int:
        """
        Add an access rule.

        Args:
            rule: The access rule to add
            index: Optional position to insert (default: append)

        Returns:
            Index of the added rule
        """
        with self._lock:
            if index is not None:
                self._rules.insert(index, rule)
                return index
            self._rules.append(rule)
            return len(self._rules) - 1

    def remove_rule(self, index: int) -> bool:
        """Remove a rule by index."""
        with self._lock:
            if 0 <= index < len(self._rules):
                self._rules.pop(index)
                return True
        return False

    def remove_rules_by_tag(self, tag_key: str, tag_value: str) -> int:
        """Remove all rules matching a tag."""
        with self._lock:
            original_len = len(self._rules)
            self._rules = [
                r for r in self._rules
                if r.tags.get(tag_key) != tag_value
            ]
            return original_len - len(self._rules)

    def get_rules(self) -> List[AccessRule]:
        """Get all rules."""
        with self._lock:
            return list(self._rules)

    def clear_rules(self) -> None:
        """Clear all rules (except defaults if re-initialized)."""
        with self._lock:
            self._rules.clear()

    def check_access(self, context: AccessContext) -> AccessResult:
        """
        Check if an access request is allowed.

        Args:
            context: The access context to check

        Returns:
            AccessResult with the decision
        """
        path = context.path

        # Security checks first
        security_check = self._security_checks(path, context)
        if security_check:
            return security_check

        # Resolve path if configured
        if self.config.resolve_paths:
            try:
                path = path.resolve()
            except Exception:
                pass

        # Determine path type
        path_type = context.path_type
        if path_type == PathType.ANY:
            try:
                if path.is_dir():
                    path_type = PathType.DIRECTORY
                elif path.is_file():
                    path_type = PathType.FILE
                elif path.is_symlink():
                    path_type = PathType.SYMLINK
            except Exception:
                path_type = PathType.ANY

        # Check file extension if validating (also for CREATE/WRITE where file may not exist yet)
        if self.config.validate_extensions:
            # For CREATE/WRITE/MODIFY, check extension even if file doesn't exist
            check_extension = path_type == PathType.FILE or context.operation in (
                FileOperation.CREATE, FileOperation.WRITE, FileOperation.MODIFY
            )
            if check_extension:
                ext_check = self._check_extension(path, context.operation)
                if ext_check:
                    return ext_check

        # Check rules in order (first match wins)
        matched_rule = None
        for rule in self._rules:
            if rule.matches(path, context.operation, path_type):
                matched_rule = rule
                break

        # Determine decision
        if matched_rule:
            decision = AccessDecision.ALLOWED
            reason = f"Matched rule: {matched_rule.pattern}"
        else:
            if self.config.default_deny:
                decision = AccessDecision.DENIED
                reason = "No matching allow rule (default deny)"
            else:
                decision = AccessDecision.ALLOWED
                reason = "No matching deny rule (default allow)"

        # Create result
        result = AccessResult(
            decision=decision,
            path=path,
            operation=context.operation,
            matched_rule=matched_rule,
            reason=reason,
        )

        # Update stats
        self._update_stats(decision)

        # Log if configured
        self._log_access(result, context)

        # Emit event
        self._emit_access_event(result, context)

        return result

    def _security_checks(self, path: Path, context: AccessContext) -> Optional[AccessResult]:
        """Perform security checks on the path."""
        path_str = str(path)

        # Prevent path traversal
        if self.config.prevent_traversal:
            if ".." in path.parts or path_str.startswith(".."):
                return AccessResult(
                    decision=AccessDecision.DENIED,
                    path=path,
                    operation=context.operation,
                    reason="Path traversal detected (..)",
                )

        # Check for absolute paths that escape allowed directories
        if path.is_absolute():
            # Additional checks could go here
            pass

        # Check symlinks
        if not self.config.follow_symlinks:
            try:
                if path.is_symlink():
                    return AccessResult(
                        decision=AccessDecision.DENIED,
                        path=path,
                        operation=context.operation,
                        reason="Symlinks not allowed",
                    )
            except Exception:
                pass

        return None

    def _check_extension(self, path: Path, operation: FileOperation) -> Optional[AccessResult]:
        """Check file extension against allowed/blocked lists."""
        ext = path.suffix.lower()

        # Check blocked extensions first
        if ext in self.config.blocked_extensions:
            return AccessResult(
                decision=AccessDecision.DENIED,
                path=path,
                operation=operation,
                reason=f"Blocked extension: {ext}",
            )

        # Check allowed extensions
        if ext not in self.config.allowed_extensions:
            return AccessResult(
                decision=AccessDecision.DENIED,
                path=path,
                operation=operation,
                reason=f"Extension not in allowed list: {ext}",
            )

        return None

    def _update_stats(self, decision: AccessDecision) -> None:
        """Update access statistics."""
        with self._stats_lock:
            if decision == AccessDecision.ALLOWED:
                self._stats["allowed"] += 1
            elif decision == AccessDecision.DENIED:
                self._stats["denied"] += 1
            elif decision == AccessDecision.REQUIRES_APPROVAL:
                self._stats["requires_approval"] += 1

    def _log_access(self, result: AccessResult, context: AccessContext) -> None:
        """Log access attempt (only denials and approvals, not allowed accesses)."""
        should_log = (
            (result.decision == AccessDecision.DENIED and self.config.log_denied)
            or (result.decision == AccessDecision.REQUIRES_APPROVAL)
        )

        if not should_log:
            return

        if self.config.log_details:
            logger.info(
                f"File access {result.decision.value}: "
                f"{context.operation.value} {result.path} "
                f"(source: {context.source or 'unknown'})"
            )
        else:
            logger.debug(f"File access {result.decision.value}: {context.operation.value} {result.path}")

    def _emit_access_event(self, result: AccessResult, context: AccessContext) -> None:
        """Emit access event for audit trail."""
        event_name = f"file.access.{result.decision.value}"
        self._event_bus.emit(
            event_name,
            data={
                "path": str(result.path),
                "operation": result.operation.value,
                "decision": result.decision.value,
                "reason": result.reason,
                "source": context.source,
                "matched_rule": result.matched_rule.to_dict() if result.matched_rule else None,
            },
            source=f"FileAllowlist:{context.source}" if context.source else "FileAllowlist",
            priority=EventPriority.HIGH if result.decision == AccessDecision.DENIED else EventPriority.NORMAL,
            tags={"operation": context.operation.value, "decision": result.decision.value},
        )

    def validate_path(
        self,
        path: Union[str, Path],
        operation: FileOperation,
        source: str = "",
        path_type: PathType = PathType.ANY,
    ) -> AccessResult:
        """
        Convenience method to validate a path.

        Args:
            path: Path to validate
            operation: Operation to check
            source: Requesting component
            path_type: Type of path expected

        Returns:
            AccessResult with the decision
        """
        path_obj = Path(path) if isinstance(path, str) else path
        context = AccessContext(
            operation=operation,
            path=path_obj,
            path_type=path_type,
            source=source,
        )
        return self.check_access(context)

    def require_allowed(
        self,
        path: Union[str, Path],
        operation: FileOperation,
        source: str = "",
        path_type: PathType = PathType.ANY,
    ) -> Path:
        """
        Validate path and raise if not allowed.

        Args:
            path: Path to validate
            operation: Operation to check
            source: Requesting component
            path_type: Type of path expected

        Returns:
            Resolved Path object if allowed

        Raises:
            PermissionError: If access is denied
        """
        result = self.validate_path(path, operation, source, path_type)
        if result.decision == AccessDecision.DENIED:
            raise PermissionError(f"Access denied: {result.reason}")
        if result.decision == AccessDecision.REQUIRES_APPROVAL:
            raise PermissionError(f"Access requires approval: {result.reason}")
        return Path(path)

    def get_stats(self) -> Dict[str, any]:
        """Get access statistics."""
        with self._stats_lock:
            return dict(self._stats)

    def get_config(self) -> FileAllowlistConfig:
        """Get current configuration."""
        return self.config

    def update_config(self, **kwargs) -> None:
        """Update configuration."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def export_rules(self) -> List[Dict]:
        """Export all rules as dictionaries."""
        with self._lock:
            return [r.to_dict() for r in self._rules]

    def import_rules(self, rules_data: List[Dict]) -> int:
        """Import rules from dictionaries."""
        with self._lock:
            self._rules = [AccessRule.from_dict(r) for r in rules_data]
            return len(self._rules)

    def reset_to_defaults(self) -> None:
        """Reset to default rules."""
        with self._lock:
            self._rules.clear()
            self._setup_default_rules()

    def get_allowed_directories(self) -> List[Path]:
        """Get list of explicitly allowed root directories."""
        dirs = set()
        for rule in self._rules:
            # Extract base directory from pattern
            pattern = rule.pattern
            if "**" in pattern:
                base = pattern.split("**")[0].rstrip("/\\")
                if base:
                    dirs.add(Path(base))
        return sorted(dirs)

    def is_path_allowed(
        self,
        path: Union[str, Path],
        operation: FileOperation = FileOperation.READ,
    ) -> bool:
        """Quick boolean check if path is allowed."""
        result = self.validate_path(path, operation)
        return result.decision == AccessDecision.ALLOWED


# === Path utilities ===

def normalize_path(path: Union[str, Path], resolve: bool = True) -> Path:
    """Normalize a path for consistent handling."""
    p = Path(path)
    if resolve:
        try:
            return p.resolve()
        except Exception:
            return p.absolute()
    return p.absolute()


def is_safe_path(path: Union[str, Path], base: Union[str, Path]) -> bool:
    """Check if path is within base directory (no traversal)."""
    try:
        path_obj = Path(path).resolve()
        base_obj = Path(base).resolve()
        return path_obj.is_relative_to(base_obj)
    except Exception:
        return False


def get_relative_path(path: Union[str, Path], base: Union[str, Path]) -> Optional[Path]:
    """Get relative path from base, or None if not within base."""
    try:
        path_obj = Path(path).resolve()
        base_obj = Path(base).resolve()
        return path_obj.relative_to(base_obj)
    except Exception:
        return None


def sanitize_path(path: Union[str, Path]) -> Path:
    """Sanitize path by removing dangerous components."""
    p = Path(path)
    safe_parts = []
    for part in p.parts:
        if part not in ("..", "."):
            safe_parts.append(part)
    return Path(*safe_parts) if safe_parts else Path(".")


# === File type detection ===

class FileTypeDetector:
    """Detect file types for validation."""

    # Magic bytes for common file types
    MAGIC_BYTES = {
        b'\x89PNG\r\n\x1a\n': 'png',
        b'\xff\xd8\xff': 'jpg',
        b'GIF87a': 'gif',
        b'GIF89a': 'gif',
        b'PK\x03\x04': 'zip',
        b'%PDF': 'pdf',
        b'\x7fELF': 'elf',
        b'MZ': 'exe',
        b'\xca\xfe\xba\xbe': 'java_class',
        b'#!/bin/': 'script',
        b'#!/usr/bin/': 'script',
        b'<?xml': 'xml',
        b'{': 'json',
        b'[': 'json_array',
    }

    TEXT_EXTENSIONS = {'.txt', '.md', '.rst', '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.csv', '.tsv', '.xml', '.html', '.css', '.scss', '.sql', '.sh', '.bash', '.zsh', '.fish', '.dockerfile', '.gitignore'}

    @classmethod
    def detect_type(cls, path: Path) -> str:
        """Detect file type by extension and magic bytes."""
        ext = path.suffix.lower()
        if ext in cls.TEXT_EXTENSIONS:
            return 'text'

        try:
            with open(path, 'rb') as f:
                header = f.read(16)
            for magic, ftype in cls.MAGIC_BYTES.items():
                if header.startswith(magic):
                    return ftype
        except Exception:
            pass

        return 'unknown'

    @classmethod
    def is_text_file(cls, path: Path) -> bool:
        """Quick check if file is likely text."""
        return cls.detect_type(path) in ('text', 'json', 'json_array', 'xml', 'script')


# === Global allowlist management ===

_default_allowlist: Optional[FileAllowlist] = None
_allowlist_lock = threading.Lock()


def get_file_allowlist(config: Optional[FileAllowlistConfig] = None) -> FileAllowlist:
    """Get or create the global default file allowlist."""
    global _default_allowlist
    with _allowlist_lock:
        if _default_allowlist is None:
            _default_allowlist = FileAllowlist(config)
        return _default_allowlist


def set_file_allowlist(allowlist: FileAllowlist) -> None:
    """Set the global default file allowlist."""
    global _default_allowlist
    with _allowlist_lock:
        _default_allowlist = allowlist


# === Convenience functions ===

def validate_file_access(
    path: Union[str, Path],
    operation: FileOperation,
    source: str = "",
) -> AccessResult:
    """Validate file access using global allowlist."""
    return get_file_allowlist().validate_path(path, operation, source)


def require_file_access(
    path: Union[str, Path],
    operation: FileOperation,
    source: str = "",
) -> Path:
    """Require file access using global allowlist."""
    return get_file_allowlist().require_allowed(path, operation, source)


def is_file_allowed(path: Union[str, Path], operation: FileOperation = FileOperation.READ) -> bool:
    """Quick check if file is allowed using global allowlist."""
    return get_file_allowlist().is_path_allowed(path, operation)