"""File System Watcher for Freya Event System.

This module provides cross-platform file system monitoring using watchdog,
integrated with the Freya EventBus for real-time event emission on
file system changes.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Any
from uuid import uuid4

from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
)
from watchdog.observers import Observer

from app.core.events import EventBus, Event, EventPriority
from app.core.logger import logger


class FileEventType(Enum):
    """Types of file system events."""
    CREATED = "created"
    DELETED = "deleted"
    MODIFIED = "modified"
    MOVED = "moved"


@dataclass
class FileEvent:
    """Represents a file system event."""
    event_type: FileEventType
    path: str
    is_directory: bool = False
    destination_path: Optional[str] = None  # For move events
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "file_watcher"

    def to_event(self) -> Event:
        """Convert to EventBus Event."""
        event_name = f"file.{self.event_type.value}"
        if self.is_directory:
            event_name = f"dir.{self.event_type.value}"

        data = {
            "path": self.path,
            "is_directory": self.is_directory,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }
        if self.destination_path:
            data["destination_path"] = self.destination_path

        tags = {
            "event_type": self.event_type.value,
            "is_directory": str(self.is_directory).lower(),
        }

        return Event(
            name=event_name,
            data=data,
            source=self.source,
            priority=EventPriority.NORMAL,
            tags=tags,
            metadata={"file_event": self},
        )


class FileSystemEventHandler(FileSystemEventHandler):
    """Watchdog event handler that converts to FileEvent and emits to EventBus."""

    def __init__(
        self,
        event_bus: EventBus,
        watched_paths: List[str],
        ignore_patterns: Optional[List[str]] = None,
        debounce_ms: int = 100,
    ):
        """
        Initialize the handler.

        Args:
            event_bus: EventBus to emit events to
            watched_paths: List of paths being watched (for context)
            ignore_patterns: List of glob patterns to ignore
            debounce_ms: Debounce time in milliseconds for rapid events
        """
        self.event_bus = event_bus
        self.watched_paths = [Path(p).resolve() for p in watched_paths]
        self.ignore_patterns = ignore_patterns or []
        self.debounce_ms = debounce_ms

        # Debounce tracking
        self._last_events: Dict[str, tuple] = {}  # path -> (type, timestamp)
        self._debounce_lock = threading.Lock()

    def _should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        import fnmatch
        path_str = str(path)
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(os.path.basename(path_str), pattern):
                return True
        return False

    def _debounce(self, event_type: FileEventType, path: str, is_directory: bool) -> bool:
        """
        Check if event should be debounced.

        Returns True if event should be processed, False if debounced.
        """
        key = f"{event_type.value}:{path}"
        now = time.time() * 1000  # milliseconds

        with self._debounce_lock:
            last = self._last_events.get(key)
            if last:
                last_type, last_time = last
                if last_type == event_type.value and (now - last_time) < self.debounce_ms:
                    return False  # Debounced
            self._last_events[key] = (event_type.value, now)
            return True

    def _emit(self, event_type: FileEventType, path: str, is_directory: bool, dest_path: Optional[str] = None):
        """Emit a file system event."""
        if self._should_ignore(path):
            return

        if not self._debounce(event_type, path, is_directory):
            return

        file_event = FileEvent(
            event_type=event_type,
            path=path,
            is_directory=is_directory,
            destination_path=dest_path,
        )
        event = file_event.to_event()
        self.event_bus.emit(event.name, event.data, source=event.source, priority=event.priority, tags=event.tags, metadata=event.metadata)

    def on_created(self, event):
        """Handle file/directory creation."""
        if event.is_directory:
            self._emit(FileEventType.CREATED, event.src_path, True)
        else:
            self._emit(FileEventType.CREATED, event.src_path, False)

    def on_deleted(self, event):
        """Handle file/directory deletion."""
        if event.is_directory:
            self._emit(FileEventType.DELETED, event.src_path, True)
        else:
            self._emit(FileEventType.DELETED, event.src_path, False)

    def on_modified(self, event):
        """Handle file/directory modification."""
        if event.is_directory:
            self._emit(FileEventType.MODIFIED, event.src_path, True)
        else:
            self._emit(FileEventType.MODIFIED, event.src_path, False)

    def on_moved(self, event):
        """Handle file/directory move/rename."""
        if event.is_directory:
            self._emit(FileEventType.MOVED, event.src_path, True, event.dest_path)
        else:
            self._emit(FileEventType.MOVED, event.src_path, False, event.dest_path)


class FileWatcher:
    """
    File system watcher integrated with Freya EventBus.

    Monitors specified paths for file system changes and emits
    corresponding events to the EventBus.

    Events emitted:
        - file.created / dir.created
        - file.deleted / dir.deleted
        - file.modified / dir.modified
        - file.moved / dir.moved

    Usage:
        watcher = FileWatcher(event_bus, [".", "src"])
        watcher.start()
        # ... do work ...
        watcher.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        paths: List[str] = None,
        recursive: bool = True,
        ignore_patterns: Optional[List[str]] = None,
        debounce_ms: int = 100,
    ):
        """
        Initialize the file watcher.

        Args:
            event_bus: EventBus instance to emit events to
            paths: List of paths to watch (default: current directory)
            recursive: Whether to watch recursively
            ignore_patterns: Glob patterns to ignore (e.g., ["*.pyc", "__pycache__/*", ".git/*"])
            debounce_ms: Debounce time for rapid events
        """
        self.event_bus = event_bus
        self.paths = [Path(p).resolve() for p in (paths or ["."])]
        self.recursive = recursive
        self.ignore_patterns = ignore_patterns or self._default_ignore_patterns()
        self.debounce_ms = debounce_ms

        self._observer: Optional[Observer] = None
        self._handler: Optional[FileSystemEventHandler] = None
        self._running = False
        self._lock = threading.RLock()

        # Statistics
        self._stats = {
            "events_emitted": 0,
            "files_created": 0,
            "files_deleted": 0,
            "files_modified": 0,
            "files_moved": 0,
            "dirs_created": 0,
            "dirs_deleted": 0,
            "dirs_modified": 0,
            "dirs_moved": 0,
        }
        self._stats_lock = threading.Lock()

    @staticmethod
    def _default_ignore_patterns() -> List[str]:
        """Default ignore patterns for common noise."""
        return [
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "__pycache__/*",
            ".git/*",
            ".hg/*",
            ".svn/*",
            ".idea/*",
            ".vscode/*",
            "*.swp",
            "*.swo",
            "*~",
            ".DS_Store",
            "Thumbs.db",
            "*.tmp",
            "*.temp",
            "*.log",
            "node_modules/*",
            "venv/*",
            "env/*",
            ".venv/*",
            ".env/*",
            "dist/*",
            "build/*",
            "*.egg-info/*",
        ]

    def start(self) -> None:
        """Start watching the file system."""
        with self._lock:
            if self._running:
                logger.warning("FileWatcher already running")
                return

            # Create handler
            self._handler = FileSystemEventHandler(
                event_bus=self.event_bus,
                watched_paths=[str(p) for p in self.paths],
                ignore_patterns=self.ignore_patterns,
                debounce_ms=self.debounce_ms,
            )

            # Create observer
            self._observer = Observer()

            # Schedule watches for each path
            for path in self.paths:
                if path.exists():
                    self._observer.schedule(self._handler, str(path), recursive=self.recursive)
                    logger.info(f"FileWatcher watching: {path} (recursive={self.recursive})")
                else:
                    logger.warning(f"FileWatcher path does not exist: {path}")

            # Start observer
            self._observer.start()
            self._running = True
            logger.info("FileWatcher started")

    def stop(self) -> None:
        """Stop watching the file system."""
        with self._lock:
            if not self._running:
                return

            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=5.0)
                self._observer = None

            self._handler = None
            self._running = False
            logger.info("FileWatcher stopped")

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    def add_path(self, path: str) -> bool:
        """Add a path to watch."""
        path_obj = Path(path).resolve()
        if path_obj not in self.paths and path_obj.exists():
            self.paths.append(path_obj)
            if self._running and self._observer:
                self._observer.schedule(self._handler, str(path_obj), recursive=self.recursive)
                logger.info(f"FileWatcher added path: {path_obj}")
            return True
        return False

    def remove_path(self, path: str) -> bool:
        """Remove a path from watching."""
        path_obj = Path(path).resolve()
        if path_obj in self.paths:
            self.paths.remove(path_obj)
            # Note: watchdog doesn't support unscheduling by path easily
            # Would need to restart observer
            logger.info(f"FileWatcher removed path: {path_obj} (restart required)")
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get watcher statistics."""
        with self._stats_lock:
            return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._stats_lock:
            for key in self._stats:
                self._stats[key] = 0


class FileEventBusIntegration:
    """
    High-level integration between FileWatcher and EventBus.

    Provides convenient subscription methods for file events.
    """

    # Standard event names
    FILE_CREATED = "file.created"
    FILE_DELETED = "file.deleted"
    FILE_MODIFIED = "file.modified"
    FILE_MOVED = "file.moved"
    DIR_CREATED = "dir.created"
    DIR_DELETED = "dir.deleted"
    DIR_MODIFIED = "dir.modified"
    DIR_MOVED = "dir.moved"

    # Wildcard patterns
    ALL_FILE_EVENTS = "file.*"
    ALL_DIR_EVENTS = "dir.*"
    ALL_EVENTS = "*.*"

    def __init__(self, event_bus: EventBus, watcher: FileWatcher):
        self.event_bus = event_bus
        self.watcher = watcher

    def on_file_created(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to file creation events."""
        return self.event_bus.subscribe(self.FILE_CREATED, callback, **kwargs)

    def on_file_deleted(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to file deletion events."""
        return self.event_bus.subscribe(self.FILE_DELETED, callback, **kwargs)

    def on_file_modified(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to file modification events."""
        return self.event_bus.subscribe(self.FILE_MODIFIED, callback, **kwargs)

    def on_file_moved(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to file move/rename events."""
        return self.event_bus.subscribe(self.FILE_MOVED, callback, **kwargs)

    def on_file_any(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to all file events."""
        return self.event_bus.subscribe(self.ALL_FILE_EVENTS, callback, **kwargs)

    def on_dir_created(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to directory creation events."""
        return self.event_bus.subscribe(self.DIR_CREATED, callback, **kwargs)

    def on_dir_deleted(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to directory deletion events."""
        return self.event_bus.subscribe(self.DIR_DELETED, callback, **kwargs)

    def on_dir_modified(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to directory modification events."""
        return self.event_bus.subscribe(self.DIR_MODIFIED, callback, **kwargs)

    def on_dir_moved(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to directory move/rename events."""
        return self.event_bus.subscribe(self.DIR_MOVED, callback, **kwargs)

    def on_dir_any(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to all directory events."""
        return self.event_bus.subscribe(self.ALL_DIR_EVENTS, callback, **kwargs)

    def on_any_fs_event(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to all file system events."""
        return self.event_bus.subscribe(self.ALL_EVENTS, callback, **kwargs)

    # Filtered subscriptions

    def on_python_file_changed(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to Python file changes (.py files)."""
        def filter_func(event: Event) -> bool:
            path = event.data.get("path", "")
            return path.endswith(".py")
        return self.event_bus.subscribe(self.ALL_FILE_EVENTS, callback, filter_func=filter_func, **kwargs)

    def on_config_file_changed(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to configuration file changes."""
        config_patterns = [
            "*.toml", "*.json", "*.yaml", "*.yml",
            "*.ini", "*.cfg", "*.conf",
            "requirements*.txt", "Pipfile*", "pyproject.toml",
            "package*.json", "yarn.lock", "pnpm-lock.yaml",
            "Cargo.toml", "Cargo.lock",
            "go.mod", "go.sum",
            "pom.xml", "build.gradle*", "settings.gradle*",
        ]
        import fnmatch
        def filter_func(event: Event) -> bool:
            path = event.data.get("path", "")
            name = os.path.basename(path)
            return any(fnmatch.fnmatch(name, pat) for pat in config_patterns)
        return self.event_bus.subscribe(self.ALL_FILE_EVENTS, callback, filter_func=filter_func, **kwargs)

    def on_test_file_changed(self, callback: Callable[[Event], Any], **kwargs) -> str:
        """Subscribe to test file changes."""
        def filter_func(event: Event) -> bool:
            path = event.data.get("path", "")
            name = os.path.basename(path)
            return (
                name.startswith("test_") and name.endswith(".py") or
                name.endswith("_test.py") or
                name.endswith(".spec.py") or
                name.endswith(".test.py") or
                "test" in path.lower() and name.endswith(".py")
            )
        return self.event_bus.subscribe(self.ALL_FILE_EVENTS, callback, filter_func=filter_func, **kwargs)


def create_file_watcher(
    event_bus: EventBus,
    paths: List[str] = None,
    **kwargs
) -> FileWatcher:
    """Factory function to create a FileWatcher."""
    return FileWatcher(event_bus, paths, **kwargs)


def create_file_event_integration(
    event_bus: EventBus,
    watcher: FileWatcher
) -> FileEventBusIntegration:
    """Factory function to create FileEventBusIntegration."""
    return FileEventBusIntegration(event_bus, watcher)


# Singleton instance for global access
_file_watcher_instance: Optional[FileWatcher] = None


def get_file_watcher(workspace: str = ".", **kwargs) -> FileWatcher:
    """Get or create the singleton FileWatcher instance.

    Args:
        workspace: The workspace directory to watch
        **kwargs: Additional arguments passed to FileWatcher constructor

    Returns:
        The singleton FileWatcher instance
    """
    global _file_watcher_instance
    if _file_watcher_instance is None:
        from app.core.events import get_event_bus
        event_bus = get_event_bus()
        _file_watcher_instance = create_file_watcher(event_bus, [workspace], **kwargs)
    return _file_watcher_instance


def reset_file_watcher() -> None:
    """Reset the singleton FileWatcher instance (useful for testing)."""
    global _file_watcher_instance
    if _file_watcher_instance is not None:
        _file_watcher_instance.stop()
        _file_watcher_instance = None