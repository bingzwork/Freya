"""Controlled Forgetting for Freya AI.

This module implements TTL-based expiration and archival for memory entries
to prevent unbounded storage growth and keep retrieval relevant.

Features:
- TTL (Time-To-Live) for Working/Conversation memory
- Archival of old Project/Experience/Lesson entries
- Configurable retention policies per memory type
- Automatic cleanup with safety checks
- Storage size monitoring and enforcement
"""

import json
import threading
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Callable, Tuple
from enum import Enum
from abc import ABC, abstractmethod

# Import memory modules
from app.memory.conversation_memory import ConversationMemory
from app.memory.working_memory import WorkingMemory
from app.memory.project_memory import ProjectMemory
from app.memory.experience_memory import ExperienceMemory, ExperienceEntry
from app.memory.engineering_lessons import EngineeringLessonStorage, EngineeringLesson
from app.memory.task_memory import TaskMemory, TaskState
from app.memory.episodic_memory import EpisodicMemory, EpisodicEvent
from app.memory.semantic_memory import SemanticMemory, SemanticEntry
from app.memory.long_term_memory import LongTermMemory, LongTermEntry


class RetentionPolicy(Enum):
    """Retention policy types."""
    TTL = "ttl"                    # Time-based expiration
    SIZE_LIMIT = "size_limit"      # Size-based eviction (LRU)
    ACCESS_BASED = "access_based"  # Keep frequently accessed
    NEVER = "never"                # Permanent retention


@dataclass
class MemoryRetentionConfig:
    """Retention configuration for a specific memory type."""
    memory_type: str
    policy: RetentionPolicy = RetentionPolicy.TTL
    ttl_days: int = 30              # Time-to-live in days
    max_entries: int = 10000        # Maximum entries (for size limit)
    max_size_mb: float = 50.0       # Maximum size in MB
    min_access_count: int = 0       # Minimum accesses to keep (for access-based)
    archive_before_delete: bool = True  # Archive to file before deleting
    protected_tags: List[str] = field(default_factory=list)  # Tags that prevent deletion
    protected_categories: List[str] = field(default_factory=list)  # Categories that prevent deletion

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRetentionConfig":
        # Handle enum conversion
        if "policy" in data and isinstance(data["policy"], str):
            data["policy"] = RetentionPolicy(data["policy"])
        return cls(**data)


@dataclass
class ForgettingStats:
    """Statistics from a forgetting/cleanup run."""
    run_id: str
    started_at: str
    completed_at: str
    duration_seconds: float

    # Per-memory stats
    conversation_deleted: int = 0
    conversation_archived: int = 0
    working_deleted: int = 0
    working_archived: int = 0
    project_deleted: int = 0
    project_archived: int = 0
    experience_deleted: int = 0
    experience_archived: int = 0
    lesson_deleted: int = 0
    lesson_archived: int = 0
    task_deleted: int = 0
    task_archived: int = 0
    episodic_deleted: int = 0
    episodic_archived: int = 0
    semantic_deleted: int = 0
    semantic_archived: int = 0
    long_term_deleted: int = 0
    long_term_archived: int = 0

    # Storage
    bytes_freed: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def total_deleted(self) -> int:
        return (
            self.conversation_deleted + self.working_deleted + self.project_deleted +
            self.experience_deleted + self.lesson_deleted + self.task_deleted +
            self.episodic_deleted + self.semantic_deleted + self.long_term_deleted
        )

    @property
    def total_archived(self) -> int:
        return (
            self.conversation_archived + self.working_archived + self.project_archived +
            self.experience_archived + self.lesson_archived + self.task_archived +
            self.episodic_archived + self.semantic_archived + self.long_term_archived
        )


class ArchivalStorage:
    """Handles archival of memory entries to compressed files."""

    def __init__(self, archive_dir: str = "data/memory/archive"):
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def archive_entries(self, memory_type: str, entries: List[Dict[str, Any]]) -> str:
        """Archive entries to a timestamped file."""
        if not entries:
            return ""

        with self._lock:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"{memory_type}_{timestamp}.json"
            filepath = self.archive_dir / filename

            # Compress if large
            import gzip
            data = {
                "memory_type": memory_type,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "count": len(entries),
                "entries": entries,
            }

            with gzip.open(f"{filepath}.gz", "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

            return str(filepath)

    def load_archive(self, filepath: str) -> List[Dict[str, Any]]:
        """Load entries from an archive file."""
        import gzip
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", [])

    def list_archives(self, memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available archives."""
        archives = []
        for f in self.archive_dir.glob("*.gz"):
            if memory_type and not f.name.startswith(memory_type):
                continue
            stat = f.stat()
            archives.append({
                "file": str(f),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return sorted(archives, key=lambda x: x["modified"], reverse=True)

    def get_total_archive_size(self) -> int:
        """Get total size of all archives in bytes."""
        total = 0
        for f in self.archive_dir.glob("*.gz"):
            total += f.stat().st_size
        return total


class MemoryCleaner(ABC):
    """Abstract base class for memory-specific cleaners."""

    def __init__(self, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        self.config = config
        self.archive = archive

    @abstractmethod
    def get_entries(self) -> List[Tuple[str, Any, datetime]]:
        """Get all entries with (id, entry, timestamp)."""
        pass

    @abstractmethod
    def delete_entry(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        pass

    @abstractmethod
    def get_entry_size(self, entry: Any) -> int:
        """Estimate entry size in bytes."""
        pass

    def is_protected(self, entry: Any) -> bool:
        """Check if entry is protected from deletion."""
        # Check tags
        tags = getattr(entry, "tags", [])
        if any(tag in self.config.protected_tags for tag in tags):
            return True

        # Check categories
        category = getattr(entry, "category", None)
        if category and category in self.config.protected_categories:
            return True

        return False


class ConversationMemoryCleaner(MemoryCleaner):
    """Cleaner for Conversation Memory."""

    def __init__(self, memory: ConversationMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, Any, datetime]]:
        """Get conversation turns with timestamps."""
        entries = []
        history = self.memory.get_history(limit=10000)
        for turn in history:
            try:
                entry_id = f"turn_{turn.turn_id}"
                timestamp = datetime.fromisoformat(turn.timestamp.replace('Z', '+00:00'))
                entries.append((entry_id, turn, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        """Conversation memory doesn't support individual deletion easily."""
        # Would need to rebuild history without the turn
        return False

    def get_entry_size(self, entry: Any) -> int:
        import sys
        return sys.getsizeof(str(entry))


class WorkingMemoryCleaner(MemoryCleaner):
    """Cleaner for Working Memory."""

    def __init__(self, memory: WorkingMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, Any, datetime]]:
        """Working memory is ephemeral - clear on task end."""
        return []

    def delete_entry(self, entry_id: str) -> bool:
        return False

    def get_entry_size(self, entry: Any) -> int:
        return 0

    def clear_if_inactive(self, max_inactive_hours: float = 24.0) -> bool:
        """Clear working memory if no active task for specified hours."""
        if not self.memory.is_active:
            return True
        # Working memory is cleared by end_task() call
        return False


class ProjectMemoryCleaner(MemoryCleaner):
    """Cleaner for Project Memory."""

    def __init__(self, memory: ProjectMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, Any, datetime]]:
        """Get project memory entries."""
        entries = []
        try:
            results = self.memory.search("", limit=50000)
            for entry in results:
                try:
                    entry_id = entry.get("timestamp", "")
                    timestamp = datetime.fromisoformat(entry_id.replace('Z', '+00:00'))
                    entries.append((entry_id, entry, timestamp))
                except Exception:
                    continue
        except Exception:
            pass
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        """Project memory doesn't support direct deletion easily."""
        return False

    def get_entry_size(self, entry: Dict[str, Any]) -> int:
        import sys
        return sys.getsizeof(json.dumps(entry))


class ExperienceMemoryCleaner(MemoryCleaner):
    """Cleaner for Experience Memory."""

    def __init__(self, memory: ExperienceMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, ExperienceEntry, datetime]]:
        entries = []
        all_entries = self.memory.all()
        for entry in all_entries:
            try:
                timestamp = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
                entries.append((entry.id, entry, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        return self.memory.delete(entry_id)

    def get_entry_size(self, entry: ExperienceEntry) -> int:
        import sys
        return sys.getsizeof(entry.description) + sys.getsizeof(entry.code_snippet or "")


class EngineeringLessonsCleaner(MemoryCleaner):
    """Cleaner for Engineering Lessons."""

    def __init__(self, memory: EngineeringLessonStorage, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, EngineeringLesson, datetime]]:
        entries = []
        all_lessons = self.memory.all()
        for lesson in all_lessons:
            try:
                timestamp = datetime.fromisoformat(lesson.timestamp.replace('Z', '+00:00'))
                entries.append((lesson.id, lesson, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        return self.memory.delete(entry_id)

    def get_entry_size(self, entry: EngineeringLesson) -> int:
        import sys
        return sys.getsizeof(entry.description) + sys.getsizeof(entry.code_example or "") + sys.getsizeof(entry.rationale or "")


class TaskMemoryCleaner(MemoryCleaner):
    """Cleaner for Task Memory."""

    def __init__(self, memory: TaskMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, TaskState, datetime]]:
        entries = []
        history = self.memory.get_task_history(limit=10000)
        for task in history:
            try:
                timestamp = datetime.fromisoformat(task.updated_at.replace('Z', '+00:00'))
                entries.append((task.task_id, task, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        return self.memory.delete_task(entry_id)

    def get_entry_size(self, entry: TaskState) -> int:
        import sys
        size = sys.getsizeof(entry.description)
        for step in entry.steps:
            size += sys.getsizeof(step.title) + sys.getsizeof(step.description or "")
        return size


class EpisodicMemoryCleaner(MemoryCleaner):
    """Cleaner for Episodic Memory."""

    def __init__(self, memory: EpisodicMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, EpisodicEvent, datetime]]:
        entries = []
        # Get all events (episodic memory has rotation built-in)
        events = self.memory.get_events_since(days=3650)  # 10 years
        for event in events:
            try:
                timestamp = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                entries.append((event.event_id, event, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        # Episodic memory is append-only, but we can mark for archival
        return False

    def get_entry_size(self, entry: EpisodicEvent) -> int:
        import sys
        return sys.getsizeof(entry.title) + sys.getsizeof(entry.description) + sys.getsizeof(str(entry.metadata))


class SemanticMemoryCleaner(MemoryCleaner):
    """Cleaner for Semantic Memory."""

    def __init__(self, memory: SemanticMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, SemanticEntry, datetime]]:
        entries = []
        for entry in self.memory._entries.values():
            try:
                timestamp = datetime.fromisoformat(entry.updated_at.replace('Z', '+00:00'))
                entries.append((entry.entry_id, entry, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        return self.memory.delete(entry_id)

    def get_entry_size(self, entry: SemanticEntry) -> int:
        import sys
        size = sys.getsizeof(entry.content)
        for ex in entry.examples:
            size += sys.getsizeof(ex.get("code", "")) + sys.getsizeof(ex.get("explanation", ""))
        return size


class LongTermMemoryCleaner(MemoryCleaner):
    """Cleaner for Long-Term Memory."""

    def __init__(self, memory: LongTermMemory, config: MemoryRetentionConfig, archive: Optional[ArchivalStorage] = None):
        super().__init__(config, archive)
        self.memory = memory

    def get_entries(self) -> List[Tuple[str, LongTermEntry, datetime]]:
        entries = []
        for entry in self.memory.get_all():
            try:
                timestamp = datetime.fromisoformat(entry.updated_at.replace('Z', '+00:00'))
                key = f"{entry.category}.{entry.key}"
                entries.append((key, entry, timestamp))
            except Exception:
                continue
        return entries

    def delete_entry(self, entry_id: str) -> bool:
        # Parse category.key
        if "." in entry_id:
            category, key = entry_id.split(".", 1)
            return self.memory.delete(category, key)
        return False

    def get_entry_size(self, entry: LongTermEntry) -> int:
        import sys
        return sys.getsizeof(entry.value) + sys.getsizeof(entry.description or "")


class ForgettingEngine:
    """Main engine for controlled forgetting across all memory types."""

    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        working_memory: Optional[WorkingMemory] = None,
        project_memory: Optional[ProjectMemory] = None,
        experience_memory: Optional[ExperienceMemory] = None,
        engineering_lessons: Optional[EngineeringLessonStorage] = None,
        task_memory: Optional[TaskMemory] = None,
        episodic_memory: Optional[EpisodicMemory] = None,
        semantic_memory: Optional[SemanticMemory] = None,
        long_term_memory: Optional[LongTermMemory] = None,
        configs: Optional[Dict[str, MemoryRetentionConfig]] = None,
        archive_dir: str = "data/memory/archive",
        state_path: str = "data/memory/forgetting_state.json",
    ):
        """Initialize the forgetting engine.

        Args:
            conversation_memory: ConversationMemory instance
            working_memory: WorkingMemory instance
            project_memory: ProjectMemory instance
            experience_memory: ExperienceMemory instance
            engineering_lessons: EngineeringLessonStorage instance
            task_memory: TaskMemory instance
            episodic_memory: EpisodicMemory instance
            semantic_memory: SemanticMemory instance
            long_term_memory: LongTermMemory instance
            configs: Per-memory retention configs
            archive_dir: Directory for archived entries
            state_path: Path to persist forgetting state
        """
        self.archive = ArchivalStorage(archive_dir)
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

        # Default configs
        self.configs = configs or self._default_configs()

        # Initialize cleaners
        self.cleaners: Dict[str, MemoryCleaner] = {}

        if conversation_memory:
            self.cleaners["conversation"] = ConversationMemoryCleaner(
                conversation_memory, self.configs.get("conversation", self.configs["conversation"]), self.archive
            )
        if working_memory:
            self.cleaners["working"] = WorkingMemoryCleaner(
                working_memory, self.configs.get("working", self.configs["working"]), self.archive
            )
        if project_memory:
            self.cleaners["project"] = ProjectMemoryCleaner(
                project_memory, self.configs.get("project", self.configs["project"]), self.archive
            )
        if experience_memory:
            self.cleaners["experience"] = ExperienceMemoryCleaner(
                experience_memory, self.configs.get("experience", self.configs["experience"]), self.archive
            )
        if engineering_lessons:
            self.cleaners["lessons"] = EngineeringLessonsCleaner(
                engineering_lessons, self.configs.get("lessons", self.configs["lessons"]), self.archive
            )
        if task_memory:
            self.cleaners["task"] = TaskMemoryCleaner(
                task_memory, self.configs.get("task", self.configs["task"]), self.archive
            )
        if episodic_memory:
            self.cleaners["episodic"] = EpisodicMemoryCleaner(
                episodic_memory, self.configs.get("episodic", self.configs["episodic"]), self.archive
            )
        if semantic_memory:
            self.cleaners["semantic"] = SemanticMemoryCleaner(
                semantic_memory, self.configs.get("semantic", self.configs["semantic"]), self.archive
            )
        if long_term_memory:
            self.cleaners["long_term"] = LongTermMemoryCleaner(
                long_term_memory, self.configs.get("long_term", self.configs["long_term"]), self.archive
            )

        # State
        self._last_run: Optional[datetime] = None
        self._run_history: List[ForgettingStats] = []
        self._load_state()

    def _default_configs(self) -> Dict[str, MemoryRetentionConfig]:
        """Create default retention configs for each memory type."""
        return {
            "conversation": MemoryRetentionConfig(
                memory_type="conversation",
                policy=RetentionPolicy.TTL,
                ttl_days=30,
                max_entries=1000,
                protected_tags=["important", "reference", "decision"],
            ),
            "working": MemoryRetentionConfig(
                memory_type="working",
                policy=RetentionPolicy.TTL,
                ttl_days=1,  # Working memory should be cleared per task
                max_entries=100,
            ),
            "project": MemoryRetentionConfig(
                memory_type="project",
                policy=RetentionPolicy.SIZE_LIMIT,
                ttl_days=365,
                max_entries=50000,
                max_size_mb=100.0,
                protected_tags=["milestone", "release", "architecture"],
            ),
            "experience": MemoryRetentionConfig(
                memory_type="experience",
                policy=RetentionPolicy.ACCESS_BASED,
                ttl_days=90,
                max_entries=10000,
                min_access_count=1,
                protected_tags=["pattern", "best_practice", "critical", "security"],
                protected_categories=["pattern", "best_practice", "architecture", "security"],
            ),
            "lessons": MemoryRetentionConfig(
                memory_type="lessons",
                policy=RetentionPolicy.ACCESS_BASED,
                ttl_days=180,
                max_entries=5000,
                min_access_count=1,
                protected_tags=["critical", "security", "architecture"],
                protected_categories=["pattern", "anti_pattern"],
            ),
            "task": MemoryRetentionConfig(
                memory_type="task",
                policy=RetentionPolicy.TTL,
                ttl_days=30,
                max_entries=1000,
                protected_tags=["active", "blocked", "important"],
            ),
            "episodic": MemoryRetentionConfig(
                memory_type="episodic",
                policy=RetentionPolicy.SIZE_LIMIT,
                ttl_days=90,
                max_entries=10000,
                max_size_mb=50.0,
                protected_tags=["milestone", "release", "critical_failure"],
            ),
            "semantic": MemoryRetentionConfig(
                memory_type="semantic",
                policy=RetentionPolicy.NEVER,  # Semantic knowledge is permanent
                ttl_days=3650,
                max_entries=5000,
                protected_tags=["verified", "fundamental", "core"],
            ),
            "long_term": MemoryRetentionConfig(
                memory_type="long_term",
                policy=RetentionPolicy.NEVER,  # Long-term memory is permanent
                ttl_days=3650,
                max_entries=10000,
                protected_tags=["user", "verified", "preference", "standard"],
            ),
        }

    def _load_state(self) -> None:
        """Load forgetting state from disk."""
        if not self.state_path.exists():
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "last_run" in data:
                self._last_run = datetime.fromisoformat(data["last_run"])

            for run_data in data.get("run_history", [])[-100:]:
                self._run_history.append(ForgettingStats(**run_data))
        except Exception:
            pass

    def _save_state(self) -> None:
        """Save forgetting state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        try:
            data = {
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "run_history": [r.to_dict() for r in self._run_history[-100:]],
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.state_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def run_forgetting(self, force: bool = False, specific_memory: Optional[str] = None) -> ForgettingStats:
        """Run the forgetting/cleanup process across all memories.

        Args:
            force: Run even if not due
            specific_memory: Run only for a specific memory type

        Returns:
            ForgettingStats with results
        """
        with self._lock:
            run_id = f"forgetting_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            started_at = datetime.now(timezone.utc)

            stats = ForgettingStats(
                run_id=run_id,
                started_at=started_at.isoformat(),
                completed_at="",
                duration_seconds=0.0,
            )

            # Determine which memories to clean
            memories_to_clean = [specific_memory] if specific_memory else list(self.cleaners.keys())

            for memory_type in memories_to_clean:
                if memory_type not in self.cleaners:
                    continue

                try:
                    cleaner = self.cleaners[memory_type]
                    memory_stats = self._clean_memory(memory_type, cleaner)
                    # Update stats object
                    for attr, value in memory_stats.items():
                        if hasattr(stats, attr):
                            setattr(stats, attr, getattr(stats, attr) + value)
                except Exception as e:
                    stats.errors.append(f"{memory_type}: {e}")

            completed_at = datetime.now(timezone.utc)
            stats.completed_at = completed_at.isoformat()
            stats.duration_seconds = (completed_at - started_at).total_seconds()

            # Update state
            self._last_run = completed_at
            self._run_history.append(stats)
            self._save_state()

            return stats

    def _clean_memory(self, memory_type: str, cleaner: MemoryCleaner) -> Dict[str, int]:
        """Clean a single memory type based on its retention policy."""
        config = cleaner.config
        stats = {
            f"{memory_type}_deleted": 0,
            f"{memory_type}_archived": 0,
        }

        now = datetime.now(timezone.utc)
        entries = cleaner.get_entries()

        # Collect entries to archive/delete
        to_archive = []
        to_delete = []
        bytes_freed = 0

        for entry_id, entry, timestamp in entries:
            # Check protection
            if cleaner.is_protected(entry):
                continue

            # Apply policy
            should_remove = False
            age_days = (now - timestamp).total_seconds() / 86400

            if config.policy == RetentionPolicy.TTL:
                if age_days > config.ttl_days:
                    should_remove = True

            elif config.policy == RetentionPolicy.SIZE_LIMIT:
                # Handled at the end by sorting and truncating
                pass

            elif config.policy == RetentionPolicy.ACCESS_BASED:
                access_count = getattr(entry, "access_count", 0)
                if age_days > config.ttl_days and access_count < config.min_access_count:
                    should_remove = True

            elif config.policy == RetentionPolicy.NEVER:
                should_remove = False

            if should_remove:
                entry_size = cleaner.get_entry_size(entry)
                bytes_freed += entry_size

                if config.archive_before_delete:
                    # Archive the entry
                    entry_dict = self._entry_to_dict(entry)
                    entry_dict["_original_id"] = entry_id
                    entry_dict["_memory_type"] = memory_type
                    entry_dict["_archived_at"] = now.isoformat()
                    to_archive.append(entry_dict)

                to_delete.append(entry_id)

        # Handle size-based policy
        if config.policy == RetentionPolicy.SIZE_LIMIT and not config.policy == RetentionPolicy.NEVER:
            # Sort by access count (ascending) then age (ascending) - least used/oldest first
            sorted_entries = sorted(
                entries,
                key=lambda x: (
                    getattr(x[1], "access_count", 0),
                    x[2]
                )
            )

            # Calculate current size
            current_size = sum(cleaner.get_entry_size(e[1]) for e in entries)
            max_bytes = config.max_size_mb * 1024 * 1024

            for entry_id, entry, timestamp in sorted_entries:
                if current_size <= max_bytes:
                    break
                if cleaner.is_protected(entry):
                    continue

                entry_size = cleaner.get_entry_size(entry)
                current_size -= entry_size
                bytes_freed += entry_size

                if config.archive_before_delete:
                    entry_dict = self._entry_to_dict(entry)
                    entry_dict["_original_id"] = entry_id
                    entry_dict["_memory_type"] = memory_type
                    entry_dict["_archived_at"] = now.isoformat()
                    to_archive.append(entry_dict)

                to_delete.append(entry_id)

        # Perform archival
        if to_archive:
            archive_path = self.archive.archive_entries(memory_type, to_archive)
            if archive_path:
                stats[f"{memory_type}_archived"] = len(to_archive)

        # Perform deletion
        for entry_id in to_delete:
            if cleaner.delete_entry(entry_id):
                stats[f"{memory_type}_deleted"] += 1

        if "bytes_freed" not in stats:
            stats["bytes_freed"] = 0
        stats["bytes_freed"] = bytes_freed

        return stats

    def _entry_to_dict(self, entry: Any) -> Dict[str, Any]:
        """Convert entry to dict for archival."""
        if hasattr(entry, "to_dict"):
            return entry.to_dict()
        elif hasattr(entry, "__dict__"):
            return entry.__dict__
        else:
            return {"raw": str(entry)}

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics across all memories."""
        with self._lock:
            stats = {
                "archive_size_bytes": self.archive.get_total_archive_size(),
                "archive_count": len(self.archive.list_archives()),
                "memories": {},
            }

            for memory_type, cleaner in self.cleaners.items():
                try:
                    entries = cleaner.get_entries()
                    config = cleaner.config

                    total_size = sum(cleaner.get_entry_size(e[1]) for e in entries)
                    protected = sum(1 for e in entries if cleaner.is_protected(e[1]))

                    stats["memories"][memory_type] = {
                        "entry_count": len(entries),
                        "estimated_size_bytes": total_size,
                        "protected_count": protected,
                        "policy": config.policy.value,
                        "ttl_days": config.ttl_days,
                        "max_entries": config.max_entries,
                        "max_size_mb": config.max_size_mb,
                    }
                except Exception as e:
                    stats["memories"][memory_type] = {"error": str(e)}

            return stats

    def get_run_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent forgetting run history."""
        with self._lock:
            return [r.to_dict() for r in self._run_history[-limit:]]

    def estimate_cleanup_impact(self) -> Dict[str, Any]:
        """Estimate what would be cleaned without actually doing it."""
        with self._lock:
            now = datetime.now(timezone.utc)
            impact = {}

            for memory_type, cleaner in self.cleaners.items():
                config = cleaner.config
                entries = cleaner.get_entries()

                to_remove = 0
                bytes_to_free = 0
                protected = 0

                for entry_id, entry, timestamp in entries:
                    if cleaner.is_protected(entry):
                        protected += 1
                        continue

                    should_remove = False
                    age_days = (now - timestamp).total_seconds() / 86400

                    if config.policy == RetentionPolicy.TTL:
                        if age_days > config.ttl_days:
                            should_remove = True
                    elif config.policy == RetentionPolicy.ACCESS_BASED:
                        access_count = getattr(entry, "access_count", 0)
                        if age_days > config.ttl_days and access_count < config.min_access_count:
                            should_remove = True

                    if should_remove:
                        to_remove += 1
                        bytes_to_free += cleaner.get_entry_size(entry)

                # Size-based estimation
                if config.policy == RetentionPolicy.SIZE_LIMIT:
                    current_size = sum(cleaner.get_entry_size(e[1]) for e in entries)
                    max_bytes = config.max_size_mb * 1024 * 1024
                    if current_size > max_bytes:
                        # Estimate how many would be removed
                        sorted_entries = sorted(
                            entries,
                            key=lambda x: (getattr(x[1], "access_count", 0), x[2])
                        )
                        remaining = current_size
                        for entry_id, entry, timestamp in sorted_entries:
                            if remaining <= max_bytes:
                                break
                            if cleaner.is_protected(entry):
                                continue
                            remaining -= cleaner.get_entry_size(entry)
                            to_remove += 1
                            bytes_to_free += cleaner.get_entry_size(entry)

                impact[memory_type] = {
                    "would_delete": to_remove,
                    "bytes_to_free": bytes_to_free,
                    "protected": protected,
                    "total_entries": len(entries),
                }

            return impact

    def reset_state(self) -> None:
        """Reset forgetting state (for testing)."""
        with self._lock:
            self._last_run = None
            self._run_history = []
            self._save_state()


def create_forgetting_engine(
    conversation_memory: Optional[ConversationMemory] = None,
    working_memory: Optional[WorkingMemory] = None,
    project_memory: Optional[ProjectMemory] = None,
    experience_memory: Optional[ExperienceMemory] = None,
    engineering_lessons: Optional[EngineeringLessonStorage] = None,
    task_memory: Optional[TaskMemory] = None,
    episodic_memory: Optional[EpisodicMemory] = None,
    semantic_memory: Optional[SemanticMemory] = None,
    long_term_memory: Optional[LongTermMemory] = None,
    configs: Optional[Dict[str, MemoryRetentionConfig]] = None,
    archive_dir: str = "data/memory/archive",
    state_path: str = "data/memory/forgetting_state.json",
) -> ForgettingEngine:
    """Factory function to create ForgettingEngine with sensible defaults."""
    return ForgettingEngine(
        conversation_memory=conversation_memory,
        working_memory=working_memory,
        project_memory=project_memory,
        experience_memory=experience_memory,
        engineering_lessons=engineering_lessons,
        task_memory=task_memory,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        long_term_memory=long_term_memory,
        configs=configs,
        archive_dir=archive_dir,
        state_path=state_path,
    )