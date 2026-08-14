"""Episodic Memory for Freya AI.

This module provides an append-only event log for recording what happened,
when, and with what outcome. Supports chronological retrieval and queries.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from enum import Enum


class EventType(Enum):
    """Types of events that can be recorded."""
    USER_REQUEST = "user_request"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TOOL_EXECUTED = "tool_executed"
    DECISION_MADE = "decision_made"
    FILE_CHANGED = "file_changed"
    ERROR_OCCURRED = "error_occurred"
    MILESTONE = "milestone"
    AGENT_STATUS = "agent_status"
    CUSTOM = "custom"

    @classmethod
    def from_string(cls, value: str) -> "EventType":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.CUSTOM


@dataclass
class EpisodicEvent:
    """A single event in the episodic memory."""
    event_id: str
    event_type: str  # Use string to allow custom types
    timestamp: str
    title: str
    description: str = ""
    outcome: str = "neutral"  # success, failure, neutral, partial
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # References to other memory systems
    task_id: Optional[str] = None
    conversation_turn: Optional[int] = None
    file_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodicEvent":
        return cls(**data)

    def get_datetime(self) -> datetime:
        """Parse timestamp as datetime."""
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))


class EpisodicMemory:
    """Append-only episodic memory for event history.

    Features:
    - Immutable event log (append-only)
    - Timestamped events with type, outcome, tags
    - Chronological retrieval and time-range queries
    - Lightweight storage with automatic rotation
    - Thread-safe atomic persistence
    - Event referencing for cross-memory linking

    Example usage:
        episodic = EpisodicMemory(workspace=".")

        # Record events
        episodic.record(
            event_type=EventType.USER_REQUEST,
            title="User asked to add authentication",
            description="Implement JWT-based auth for API",
            task_id="task_001",
            tags=["auth", "api", "security"]
        )

        episodic.record(
            event_type=EventType.TASK_COMPLETED,
            title="Authentication implemented",
            outcome="success",
            metadata={"files_changed": 5, "tests_added": 10}
        )

        # Query recent events
        recent = episodic.recent(limit=20)
        last_week = episodic.get_events_since(days=7)
        errors = episodic.get_events_by_type(EventType.ERROR_OCCURRED)
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/episodic_memory.json",
        max_events: int = 10000,
        rotate_after_days: int = 90,
    ):
        """Initialize Episodic Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_events: Maximum events to keep in memory (oldest removed)
            rotate_after_days: Optional max age for events (cleanup)
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_events = max_events
        self.rotate_after_days = rotate_after_days
        self._lock = threading.RLock()
        self._events: List[EpisodicEvent] = []
        self._load()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_timestamp(self) -> str:
        """Generate a timestamp with timezone."""
        return datetime.now(timezone.utc).isoformat()

    def _generate_event_id(self) -> str:
        """Generate a unique event ID."""
        import uuid
        return f"evt_{uuid.uuid4().hex[:12]}"

    def _save(self) -> None:
        """Save all events to storage (atomic write)."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            data = {
                "events": [e.to_dict() for e in self._events],
                "version": 1,
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _load(self) -> None:
        """Load events from storage file."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._events = [EpisodicEvent.from_dict(e) for e in data.get("events", [])]
        except Exception:
            self._events = []

    def _enforce_limit(self) -> None:
        """Enforce max_events by removing oldest events."""
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events:]
            self._save()

    def record(
        self,
        event_type: Union[str, EventType],
        title: str,
        description: str = "",
        outcome: str = "neutral",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        conversation_turn: Optional[int] = None,
        file_paths: Optional[List[str]] = None,
    ) -> EpisodicEvent:
        """Record a new event.

        Args:
            event_type: Type of event (EventType enum or string)
            title: Brief title of the event
            description: Detailed description
            outcome: success, failure, neutral, partial
            tags: List of tags for categorization
            metadata: Additional structured data
            task_id: Optional link to task memory
            conversation_turn: Optional link to conversation turn
            file_paths: Optional list of related file paths

        Returns:
            The created EpisodicEvent
        """
        with self._lock:
            if isinstance(event_type, EventType):
                event_type_str = event_type.value
            else:
                event_type_str = str(event_type)

            event = EpisodicEvent(
                event_id=self._generate_event_id(),
                event_type=event_type_str,
                timestamp=self._generate_timestamp(),
                title=title,
                description=description,
                outcome=outcome,
                tags=tags or [],
                metadata=metadata or {},
                task_id=task_id,
                conversation_turn=conversation_turn,
                file_paths=file_paths or [],
            )

            self._events.append(event)
            self._enforce_limit()
            self._save()
            return event

    def record_batch(
        self,
        events: List[Dict[str, Any]],
    ) -> List[EpisodicEvent]:
        """Record multiple events at once (more efficient)."""
        with self._lock:
            created = []
            for evt_data in events:
                event = EpisodicEvent(
                    event_id=self._generate_event_id(),
                    event_type=evt_data.get("event_type", "custom"),
                    timestamp=evt_data.get("timestamp", self._generate_timestamp()),
                    title=evt_data["title"],
                    description=evt_data.get("description", ""),
                    outcome=evt_data.get("outcome", "neutral"),
                    tags=evt_data.get("tags", []),
                    metadata=evt_data.get("metadata", {}),
                    task_id=evt_data.get("task_id"),
                    conversation_turn=evt_data.get("conversation_turn"),
                    file_paths=evt_data.get("file_paths", []),
                )
                created.append(event)
                self._events.append(event)

            self._enforce_limit()
            self._save()
            return created

    def recent(self, limit: int = 20) -> List[EpisodicEvent]:
        """Get most recent events (newest first)."""
        with self._lock:
            return self._events[-limit:][::-1] if limit > 0 else self._events[::-1]

    def get_events_since(
        self,
        days: Optional[int] = None,
        hours: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[EpisodicEvent]:
        """Get events since a given time."""
        with self._lock:
            if since is None:
                if days:
                    since = datetime.now(timezone.utc) - timedelta(days=days)
                elif hours:
                    since = datetime.now(timezone.utc) - timedelta(hours=hours)
                else:
                    return []

            results = []
            for event in self._events:
                if event.get_datetime() >= since:
                    results.append(event)
            return results  # Already chronological

    def get_events_between(
        self,
        start: datetime,
        end: datetime,
    ) -> List[EpisodicEvent]:
        """Get events within a time range."""
        with self._lock:
            results = []
            for event in self._events:
                dt = event.get_datetime()
                if start <= dt <= end:
                    results.append(event)
            return results

    def get_events_by_type(
        self,
        event_type: Union[str, EventType],
        limit: Optional[int] = None,
    ) -> List[EpisodicEvent]:
        """Get events of a specific type."""
        with self._lock:
            if isinstance(event_type, EventType):
                event_type = event_type.value

            results = [e for e in self._events if e.event_type == event_type]
            if limit:
                results = results[-limit:] if limit > 0 else []
            return results

    def get_events_by_outcome(
        self,
        outcome: str,  # success, failure, neutral, partial
        limit: Optional[int] = None,
    ) -> List[EpisodicEvent]:
        """Get events by outcome."""
        with self._lock:
            results = [e for e in self._events if e.outcome == outcome]
            if limit:
                results = results[-limit:] if limit > 0 else []
            return results

    def get_events_by_tag(
        self,
        tag: str,
        limit: Optional[int] = None,
    ) -> List[EpisodicEvent]:
        """Get events containing a specific tag."""
        with self._lock:
            results = [e for e in self._events if tag in e.tags]
            if limit:
                results = results[-limit:] if limit > 0 else []
            return results

    def get_events_by_task(
        self,
        task_id: str,
    ) -> List[EpisodicEvent]:
        """Get all events linked to a specific task."""
        with self._lock:
            return [e for e in self._events if e.task_id == task_id]

    def get_events_by_file(
        self,
        file_path: str,
    ) -> List[EpisodicEvent]:
        """Get all events linked to a specific file."""
        with self._lock:
            return [e for e in self._events if file_path in e.file_paths]

    def search(
        self,
        query: str,
        event_types: Optional[List[str]] = None,
        outcomes: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[EpisodicEvent]:
        """Search events by text query and filters."""
        with self._lock:
            query_lower = query.lower()
            results = []

            for event in self._events:
                # Time filters
                if since or until:
                    dt = event.get_datetime()
                    if since and dt < since:
                        continue
                    if until and dt > until:
                        continue

                # Type filter
                if event_types and event.event_type not in event_types:
                    continue

                # Outcome filter
                if outcomes and event.outcome not in outcomes:
                    continue

                # Tag filter (any tag matches)
                if tags and not any(tag in event.tags for tag in tags):
                    continue

                # Text query
                searchable = f"{event.title} {event.description} {' '.join(event.tags)}".lower()
                if query_lower not in searchable:
                    continue

                results.append(event)

            # Sort by recency (newest first)
            results.sort(key=lambda e: e.timestamp, reverse=True)
            return results[:limit]

    def get_daily_summary(self, date: datetime) -> Dict[str, Any]:
        """Get summary of events for a specific day."""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        events = self.get_events_between(start, end)

        summary = {
            "date": date.date().isoformat(),
            "total_events": len(events),
            "by_type": {},
            "by_outcome": {},
            "tasks_involved": set(),
            "files_touched": set(),
        }

        for event in events:
            summary["by_type"][event.event_type] = summary["by_type"].get(event.event_type, 0) + 1
            summary["by_outcome"][event.outcome] = summary["by_outcome"].get(event.outcome, 0) + 1
            if event.task_id:
                summary["tasks_involved"].add(event.task_id)
            summary["files_touched"].update(event.file_paths)

        summary["tasks_involved"] = list(summary["tasks_involved"])
        summary["files_touched"] = list(summary["files_touched"])
        return summary

    def get_weekly_summary(self, end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get daily summaries for the past 7 days."""
        if end_date is None:
            end_date = datetime.now(timezone.utc)
        summaries = []
        for i in range(7):
            day = end_date - timedelta(days=i)
            summaries.append(self.get_daily_summary(day))
        return summaries[::-1]  # Chronological

    def cleanup_old_events(self, older_than_days: int = None) -> int:
        """Remove events older than specified days."""
        if older_than_days is None:
            older_than_days = self.rotate_after_days

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        with self._lock:
            original_count = len(self._events)
            self._events = [e for e in self._events if e.get_datetime() >= cutoff]
            removed = original_count - len(self._events)
            if removed:
                self._save()
            return removed

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the episodic memory."""
        with self._lock:
            by_type: Dict[str, int] = {}
            by_outcome: Dict[str, int] = {}
            by_tag: Dict[str, int] = {}

            for event in self._events:
                by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
                by_outcome[event.outcome] = by_outcome.get(event.outcome, 0) + 1
                for tag in event.tags:
                    by_tag[tag] = by_tag.get(tag, 0) + 1

            return {
                "total_events": len(self._events),
                "by_type": by_type,
                "by_outcome": by_outcome,
                "top_tags": dict(sorted(by_tag.items(), key=lambda x: x[1], reverse=True)[:20]),
                "oldest_event": self._events[0].timestamp if self._events else None,
                "newest_event": self._events[-1].timestamp if self._events else None,
                "max_events": self.max_events,
            }

    def export(self) -> Dict[str, Any]:
        """Export all events for backup or analysis."""
        with self._lock:
            return {
                "events": [e.to_dict() for e in self._events],
                "version": 1,
                "exported_at": self._generate_timestamp(),
            }

    def import_data(self, data: Dict[str, Any], merge: bool = True) -> int:
        """Import events from exported data."""
        with self._lock:
            if not merge:
                self._events = []

            imported = 0
            for event_data in data.get("events", []):
                try:
                    event = EpisodicEvent.from_dict(event_data)
                    self._events.append(event)
                    imported += 1
                except Exception:
                    pass

            # Sort by timestamp
            self._events.sort(key=lambda e: e.timestamp)
            self._enforce_limit()
            self._save()
            return imported

    def __len__(self) -> int:
        return len(self._events)

    def is_empty(self) -> bool:
        return len(self._events) == 0

    def __iter__(self):
        """Iterate over events chronologically."""
        return iter(self._events)

    def __reversed__(self):
        """Iterate over events in reverse chronological order."""
        return reversed(self._events)


def create_episodic_memory(
    workspace: str = ".",
    storage_path: Optional[str] = None,
    max_events: int = 10000,
    rotate_after_days: int = 90,
) -> EpisodicMemory:
    """Factory function to create EpisodicMemory with sensible defaults."""
    if storage_path is None:
        storage_path = "data/memory/episodic_memory.json"
    return EpisodicMemory(
        workspace=workspace,
        storage_path=storage_path,
        max_events=max_events,
        rotate_after_days=rotate_after_days,
    )