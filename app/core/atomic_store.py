"""
AtomicJsonStore - Reusable JSON storage foundation for Freya.

Provides a standardized JSON persistence layer with:
- Atomic read/write operations via temp file + rename
- Automatic directory creation
- File locking for thread-safe access
- Corruption protection with backup/recovery
- Safe serialization/deserialization with custom encoders
- Version compatibility and migration support
- Common storage interface for all JSON-based stores
- Thread-safe operations throughout
"""

import json
import threading
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar, Union
from uuid import uuid4

from app.core.logger import logger
from app.core.events import EventBus, get_event_bus, Event, EventPriority


T = TypeVar("T")


class AtomicJsonStoreError(Exception):
    """Base exception for AtomicJsonStore errors."""
    pass


class CorruptionError(AtomicJsonStoreError):
    """Raised when data corruption is detected and cannot be recovered."""
    pass


class LockError(AtomicJsonStoreError):
    """Raised when file locking fails."""
    pass


class MigrationError(AtomicJsonStoreError):
    """Raised when version migration fails."""
    pass


@dataclass
class StorageConfig:
    """Configuration for AtomicJsonStore behavior."""
    # Backup settings
    enable_backups: bool = True
    max_backups: int = 10
    backup_on_write: bool = True

    # Locking settings
    use_file_locking: bool = True
    lock_timeout_seconds: float = 30.0

    # Corruption handling
    auto_recover: bool = True
    verify_on_load: bool = True

    # Serialization
    json_indent: int = 2
    ensure_ascii: bool = False
    custom_encoder: Optional[Type[json.JSONEncoder]] = None
    custom_decoder: Optional[Callable[[Dict], Any]] = None

    # Version handling
    current_version: int = 1
    enable_migrations: bool = True

    # Performance
    batch_writes: bool = False
    batch_interval_seconds: float = 1.0


@dataclass
class StorageMetadata:
    """Metadata stored alongside the data."""
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    item_count: int = 0
    schema: str = ""
    checksum: str = ""
    migrations_applied: List[int] = field(default_factory=list)


class FileLock:
    """Cross-platform file locking using lock files."""

    def __init__(self, lock_path: Path, timeout: float = 30.0):
        self.lock_path = lock_path
        self.timeout = timeout
        self._acquired = False
        self._lock_file = None

    def acquire(self) -> bool:
        """Acquire the lock. Returns True if successful."""
        start_time = datetime.now().timestamp()
        while True:
            try:
                # Create lock file exclusively
                self._lock_file = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.write(self._lock_file, f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}".encode())
                self._acquired = True
                return True
            except FileExistsError:
                # Check if stale lock (older than timeout)
                if self._is_stale():
                    self._break_stale_lock()
                    continue
                if (datetime.now().timestamp() - start_time) >= self.timeout:
                    raise LockError(f"Could not acquire lock on {self.lock_path} within {self.timeout}s")
                threading.Event().wait(0.1)

    def _is_stale(self) -> bool:
        """Check if lock file is stale."""
        try:
            with open(self.lock_path, "r") as f:
                content = f.read().strip()
                if not content:
                    return True
                lines = content.split("\n")
                if len(lines) >= 2:
                    lock_time = datetime.fromisoformat(lines[1].replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - lock_time).total_seconds()
                    return age > self.timeout
        except Exception:
            return True
        return False

    def _break_stale_lock(self) -> None:
        """Remove stale lock file."""
        try:
            self.lock_path.unlink()
        except Exception:
            pass

    def release(self) -> None:
        """Release the lock."""
        if self._acquired:
            try:
                if self._lock_file:
                    os.close(self._lock_file)
                self.lock_path.unlink(missing_ok=True)
            except Exception:
                pass
            self._acquired = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class AtomicJsonStore(Generic[T], MutableMapping):
    """
    Base class for atomic JSON storage.

    Provides a thread-safe, corruption-resistant JSON storage layer
    with atomic writes, backups, and version management.
    """

    def __init__(
        self,
        storage_path: Union[str, Path],
        item_type: Type[T],
        config: Optional[StorageConfig] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the atomic JSON store.

        Args:
            storage_path: Path to the JSON file (directory will be created)
            item_type: Type of items stored (for deserialization)
            config: Storage configuration
            event_bus: Optional event bus for lifecycle events
        """
        self.storage_path = Path(storage_path)
        self.item_type = item_type
        self.config = config or StorageConfig()
        self._event_bus = event_bus or get_event_bus()

        # Ensure storage directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Internal state
        self._data: Dict[str, T] = {}
        self._metadata = StorageMetadata()
        self._lock = threading.RLock()
        self._file_lock_path = self.storage_path.with_suffix(".lock")
        self._dirty = False
        self._batch_timer: Optional[threading.Timer] = None

        # Migration handlers
        self._migrations: Dict[int, Callable[[Dict], Dict]] = {}

        # Load existing data
        self._load()

        logger.info(f"AtomicJsonStore initialized at {self.storage_path} ({len(self._data)} items)")

    def _load(self) -> None:
        """Load data from disk with corruption recovery."""
        if not self.storage_path.exists():
            self._save_metadata()
            return

        # Try loading with file lock if enabled
        if self.config.use_file_locking:
            lock = FileLock(self._file_lock_path, self.config.lock_timeout_seconds)
            lock.acquire()
            try:
                self._load_unlocked()
            finally:
                lock.release()
        else:
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        """Load data without locking (internal)."""
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            # Handle both old format (just list) and new format (with metadata)
            if isinstance(raw_data, list):
                # Legacy format
                self._metadata = StorageMetadata(version=self.config.current_version)
                self._data = self._deserialize_list(raw_data)
            elif isinstance(raw_data, dict):
                # New format with metadata
                self._metadata = self._deserialize_metadata(raw_data.get("metadata", {}))
                items_data = raw_data.get("items", [])
                self._data = self._deserialize_list(items_data)

                # Verify checksum if present
                if self._metadata.checksum and self.config.verify_on_load:
                    if not self._verify_checksum(self._data, self._metadata.checksum):
                        raise CorruptionError("Checksum verification failed")
            else:
                raise CorruptionError("Invalid storage format")

            # Run migrations if needed
            if self.config.enable_migrations and self._metadata.version < self.config.current_version:
                self._run_migrations()

        except json.JSONDecodeError as e:
            if self.config.auto_recover:
                logger.warning(f"JSON decode error, attempting recovery: {e}")
                self._recover_from_backup()
            else:
                raise CorruptionError(f"Failed to parse JSON: {e}")
        except CorruptionError:
            if self.config.auto_recover:
                logger.warning("Corruption detected, attempting recovery")
                self._recover_from_backup()
            else:
                raise
        except Exception as e:
            logger.error(f"Unexpected error loading storage: {e}")
            if self.config.auto_recover:
                self._recover_from_backup()
            else:
                raise CorruptionError(f"Failed to load storage: {e}")

    def _recover_from_backup(self) -> None:
        """Attempt to recover from the latest backup."""
        backup_dir = self.storage_path.parent / "backups"
        if not backup_dir.exists():
            logger.warning("No backup directory found, starting fresh")
            self._data = {}
            self._metadata = StorageMetadata(version=self.config.current_version)
            return

        backups = sorted(backup_dir.glob(f"{self.storage_path.stem}_*.json"), reverse=True)
        for backup in backups:
            try:
                with open(backup, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                if isinstance(raw_data, dict) and "items" in raw_data:
                    self._metadata = self._deserialize_metadata(raw_data.get("metadata", {}))
                    self._data = self._deserialize_list(raw_data["items"])
                    logger.info(f"Recovered from backup: {backup.name}")
                    self._save()  # Save recovered data
                    return
            except Exception:
                continue

        logger.warning("All backups failed, starting fresh")
        self._data = {}
        self._metadata = StorageMetadata(version=self.config.current_version)

    def _save(self) -> None:
        """Save data to disk atomically."""
        if self.config.use_file_locking:
            lock = FileLock(self._file_lock_path, self.config.lock_timeout_seconds)
            lock.acquire()
            try:
                self._save_unlocked()
            finally:
                lock.release()
        else:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Save data without locking (internal)."""
        # Create backup if enabled
        if self.config.enable_backups and self.config.backup_on_write and self.storage_path.exists():
            self._create_backup()

        # Prepare data for serialization
        self._metadata.updated_at = datetime.now(timezone.utc).isoformat()
        self._metadata.item_count = len(self._data)
        self._metadata.checksum = self._calculate_checksum(self._data)

        serialized_items = self._serialize_items(self._data)
        serialized_metadata = self._serialize_metadata(self._metadata)

        output = {
            "metadata": serialized_metadata,
            "items": serialized_items,
        }

        # Atomic write via temp file + rename
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    output,
                    f,
                    indent=self.config.json_indent,
                    ensure_ascii=self.config.ensure_ascii,
                    cls=self.config.custom_encoder,
                    default=self._json_default,
                )
            temp_path.replace(self.storage_path)
            self._dirty = False

            # Clean old backups
            self._cleanup_backups()

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise AtomicJsonStoreError(f"Failed to save storage: {e}")

        # Emit event
        self._emit_event("store.saved", {"item_count": len(self._data), "path": str(self.storage_path)})

    def _create_backup(self) -> None:
        """Create a timestamped backup."""
        backup_dir = self.storage_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.storage_path.stem}_{timestamp}{self.storage_path.suffix}"
        backup_path = backup_dir / backup_name

        try:
            shutil.copy2(self.storage_path, backup_path)
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")

    def _cleanup_backups(self) -> None:
        """Remove old backups beyond max_backups limit."""
        if not self.config.enable_backups:
            return

        backup_dir = self.storage_path.parent / "backups"
        if not backup_dir.exists():
            return

        backups = sorted(backup_dir.glob(f"{self.storage_path.stem}_*{self.storage_path.suffix}"))
        for old_backup in backups[:-self.config.max_backups]:
            try:
                old_backup.unlink()
            except Exception:
                pass

    # === Serialization/deserialization ===

    def _serialize_items(self, items: Dict[str, T]) -> List[Dict]:
        """Serialize items to list of dicts."""
        if self.config.custom_encoder:
            return [self._to_dict(item) for item in items.values()]

        serialized = []
        for item in items.values():
            if hasattr(item, "to_dict"):
                serialized.append(item.to_dict())
            elif hasattr(item, "__dict__"):
                serialized.append(item.__dict__)
            else:
                serialized.append(item)  # Assume already serializable
        return serialized

    def _deserialize_list(self, data: List[Dict]) -> Dict[str, T]:
        """Deserialize list of dicts to items dict."""
        items = {}
        for item_data in data:
            try:
                if self.config.custom_decoder:
                    item = self.config.custom_decoder(item_data)
                elif hasattr(self.item_type, "from_dict"):
                    item = self.item_type.from_dict(item_data)
                else:
                    item = self.item_type(**item_data)

                # Use item's ID as key if available
                key = getattr(item, "id", None) or getattr(item, "entry_id", None) or getattr(item, "item_id", None)
                if not key:
                    key = f"item_{uuid4().hex[:8]}"
                items[key] = item
            except Exception as e:
                logger.warning(f"Failed to deserialize item: {e}")
        return items

    def _serialize_metadata(self, metadata: StorageMetadata) -> Dict:
        """Serialize metadata to dict."""
        return {
            "version": metadata.version,
            "created_at": metadata.created_at,
            "updated_at": metadata.updated_at,
            "item_count": metadata.item_count,
            "schema": metadata.schema,
            "checksum": metadata.checksum,
            "migrations_applied": metadata.migrations_applied,
        }

    def _deserialize_metadata(self, data: Dict) -> StorageMetadata:
        """Deserialize metadata from dict."""
        return StorageMetadata(
            version=data.get("version", 1),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            item_count=data.get("item_count", 0),
            schema=data.get("schema", ""),
            checksum=data.get("checksum", ""),
            migrations_applied=data.get("migrations_applied", []),
        )

    def _to_dict(self, obj: Any) -> Dict:
        """Convert object to dict using custom encoder or default."""
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return obj.__dict__

    def _json_default(self, obj: Any) -> Any:
        """Default JSON serializer for non-serializable objects."""
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    # === Checksum ===

    def _calculate_checksum(self, items: Dict[str, T]) -> str:
        """Calculate SHA256 checksum of items."""
        import hashlib
        content = json.dumps(
            self._serialize_items(items),
            sort_keys=True,
            separators=(",", ":"),
            default=self._json_default,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _verify_checksum(self, items: Dict[str, T], expected: str) -> bool:
        """Verify checksum of items."""
        return self._calculate_checksum(items) == expected

    # === Migration ===

    def register_migration(self, from_version: int, migration_func: Callable[[Dict], Dict]) -> None:
        """Register a migration function for a specific version."""
        self._migrations[from_version] = migration_func

    def _run_migrations(self) -> None:
        """Run all pending migrations."""
        current = self._metadata.version
        target = self.config.current_version

        for version in range(current, target):
            if version in self._migrations:
                logger.info(f"Running migration from v{version} to v{version + 1}")
                try:
                    # Convert items to dict format for migration
                    items_dict = {k: self._to_dict(v) for k, v in self._data.items()}
                    migrated = self._migrations[version](items_dict)
                    self._data = self._deserialize_list(list(migrated.values()))
                    self._metadata.migrations_applied.append(version)
                    self._metadata.version = version + 1
                except Exception as e:
                    raise MigrationError(f"Migration from v{version} failed: {e}")
            else:
                logger.warning(f"No migration registered from v{version} to v{version + 1}")
                self._metadata.version = target
                break

        if self._metadata.version > current:
            self._save_metadata()

    def _save_metadata(self) -> None:
        """Save only metadata (no items)."""
        self._metadata.updated_at = datetime.now(timezone.utc).isoformat()
        self._metadata.item_count = len(self._data)
        self._metadata.checksum = self._calculate_checksum(self._data)

        serialized_metadata = self._serialize_metadata(self._metadata)
        output = {"metadata": serialized_metadata, "items": []}

        temp_path = self.storage_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=self.config.json_indent, cls=self.config.custom_encoder)
        temp_path.replace(self.storage_path)

    # === Events ===

    def _emit_event(self, name: str, data: Dict) -> None:
        """Emit a lifecycle event."""
        self._event_bus.emit(
            name,
            data=data,
            source=f"AtomicJsonStore:{self.storage_path.name}",
            priority=EventPriority.NORMAL,
        )

    # === MutableMapping interface ===

    def __getitem__(self, key: str) -> T:
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value: T) -> None:
        with self._lock:
            self._data[key] = value
            self._mark_dirty()

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._data[key]
            self._mark_dirty()

    def __iter__(self):
        with self._lock:
            return iter(self._data)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    # === Public API ===

    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """Get item by key with default."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: T) -> T:
        """Set item by key."""
        with self._lock:
            self._data[key] = value
            self._mark_dirty()
            return value

    def delete(self, key: str) -> bool:
        """Delete item by key."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._mark_dirty()
                return True
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        with self._lock:
            return key in self._data

    def keys(self) -> List[str]:
        """Get all keys."""
        with self._lock:
            return list(self._data.keys())

    def values(self) -> List[T]:
        """Get all values."""
        with self._lock:
            return list(self._data.values())

    def items(self) -> List[tuple]:
        """Get all key-value pairs."""
        with self._lock:
            return list(self._data.items())

    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._data.clear()
            self._mark_dirty()

    def _mark_dirty(self) -> None:
        """Mark store as dirty for batch writing."""
        self._dirty = True
        if self.config.batch_writes:
            self._schedule_batch_write()
        else:
            self._save()

    def _schedule_batch_write(self) -> None:
        """Schedule a batch write."""
        if self._batch_timer:
            self._batch_timer.cancel()
        self._batch_timer = threading.Timer(
            self.config.batch_interval_seconds,
            self._save
        )
        self._batch_timer.daemon = True
        self._batch_timer.start()

    def flush(self) -> None:
        """Force write any pending changes."""
        with self._lock:
            if self._dirty:
                self._save()
            if self._batch_timer:
                self._batch_timer.cancel()
                self._batch_timer = None

    def get_metadata(self) -> StorageMetadata:
        """Get storage metadata."""
        with self._lock:
            return StorageMetadata(
                version=self._metadata.version,
                created_at=self._metadata.created_at,
                updated_at=self._metadata.updated_at,
                item_count=self._metadata.item_count,
                schema=self._metadata.schema,
                checksum=self._metadata.checksum,
                migrations_applied=list(self._metadata.migrations_applied),
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with self._lock:
            size = self.storage_path.stat().st_size if self.storage_path.exists() else 0
            backup_dir = self.storage_path.parent / "backups"
            backup_count = len(list(backup_dir.glob(f"{self.storage_path.stem}_*{self.storage_path.suffix}"))) if backup_dir.exists() else 0

            return {
                "path": str(self.storage_path),
                "item_count": len(self._data),
                "file_size_bytes": size,
                "version": self._metadata.version,
                "created_at": self._metadata.created_at,
                "updated_at": self._metadata.updated_at,
                "backup_count": backup_count,
                "dirty": self._dirty,
                "migrations_applied": list(self._metadata.migrations_applied),
            }

    def backup_now(self) -> Path:
        """Force create a backup now."""
        self._create_backup()
        return self.storage_path.parent / "backups" / f"{self.storage_path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{self.storage_path.suffix}"

    def close(self) -> None:
        """Close the store, flushing any pending writes."""
        self.flush()
        logger.info(f"AtomicJsonStore closed: {self.storage_path}")

    def __enter__(self) -> "AtomicJsonStore[T]":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# === Convenience functions ===

def create_store(
    path: Union[str, Path],
    item_type: Type[T],
    config: Optional[StorageConfig] = None,
) -> AtomicJsonStore[T]:
    """Create a new AtomicJsonStore instance."""
    return AtomicJsonStore(path, item_type, config)