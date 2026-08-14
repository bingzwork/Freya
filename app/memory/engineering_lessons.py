"""Engineering Lesson Storage for Freya AI.

This module stores engineering lessons, patterns, and anti-patterns learned
throughout the project's development. It provides categorized storage for
architectural decisions, coding patterns, testing strategies, and more.

Capabilities:
- Store lessons with categorization (pattern, anti-pattern, decision, guideline)
- Search by category, tags, or keywords
- Persistent JSON storage
- Cross-referencing between related lessons
- Thread-safe operations
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

from app.core.file_allowlist import FileAllowlist, get_file_allowlist, FileOperation, AccessRule

# Shared infrastructure imports
from app.core.events import get_event_bus
from app.core.background_jobs import get_job_service
from app.core.background_jobs import JobTriggerConfig, JobTriggerType, JobPriority
from app.core.observability import get_observability_hub
from app.core.observability import HealthStatus, HealthResult, HealthCheck, ComponentInfo, ComponentType


class LessonType(Enum):
    """Types of engineering lessons."""
    PATTERN = "pattern"           # Recommended way of doing something
    ANTI_PATTERN = "anti_pattern" # What to avoid
    DECISION = "decision"         # Architectural or design decision
    GUIDELINE = "guideline"       # General best practice
    STANDARD = "standard"         # Team or project standard


class LessonSeverity(Enum):
    """Severity/impact level of a lesson."""
    INFO = "info"                 # Good to know
    RECOMMENDED = "recommended"   # Should follow
    IMPORTANT = "important"       # Strongly recommended
    CRITICAL = "critical"         # Must follow


@dataclass
class EngineeringLesson:
    """A single engineering lesson entry."""
    id: str
    title: str
    description: str
    lesson_type: str = LessonType.PATTERN.value
    category: str = "general"     # e.g., "architecture", "testing", "performance", "security"
    severity: str = LessonSeverity.RECOMMENDED.value
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    related_ids: List[str] = field(default_factory=list)  # IDs of related lessons
    context: Dict[str, Any] = field(default_factory=dict)  # When this applies
    rationale: str = ""           # Why this lesson exists
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0
    # Fields needed by ConsolidationEngine
    confidence: float = 0.0
    access_count: int = 0
    code_example: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert lesson to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringLesson":
        """Create lesson from dictionary."""
        return cls(**data)

    @property
    def is_pattern(self) -> bool:
        """Check if this is a pattern."""
        return self.lesson_type == LessonType.PATTERN.value

    @property
    def is_anti_pattern(self) -> bool:
        """Check if this is an anti-pattern."""
        return self.lesson_type == LessonType.ANTI_PATTERN.value

    @property
    def is_decision(self) -> bool:
        """Check if this is a decision."""
        return self.lesson_type == LessonType.DECISION.value


class EngineeringLessonStorage:
    """Storage for engineering lessons, patterns, and anti-patterns.

    This class provides categorized storage for engineering knowledge that
    accumulates throughout a project's lifecycle. Lessons can be retrieved
    by category, type, tags, or keywords to inform current and future work.

    Example usage:
        lessons = EngineeringLessonStorage(workspace=".")

        # Store a new pattern
        lessons.store(
            title="Use dataclasses for state",
            description="Dataclasses provide automatic __init__, __repr__, and serialization",
            lesson_type=LessonType.PATTERN,
            category="architecture",
            tags=["python", "oop", "best-practice"],
            severity=LessonSeverity.RECOMMENDED,
            examples=["@dataclass\\nclass Config:\\n    host: str\\n    port: int"]
        )

        # Store an anti-pattern
        lessons.store(
            title="Avoid global mutable state",
            description="Global mutable state makes code hard to test and reason about",
            lesson_type=LessonType.ANTI_PATTERN,
            category="architecture",
            severity=LessonSeverity.CRITICAL
        )

        # Search for lessons
        patterns = lessons.search(category="architecture", lesson_type="pattern")
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/engineering_lessons.json",
        max_lessons: int = 1000,
        file_allowlist: Optional[FileAllowlist] = None,
        event_bus: Optional[object] = None,
        job_service: Optional[object] = None,
        observability: Optional[object] = None,
    ):
        """Initialize Engineering Lesson Storage.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_lessons: Maximum number of lessons to keep (oldest removed first)
            file_allowlist: Optional FileAllowlist for access validation
            event_bus: Optional EventBus instance (uses global if not provided)
            job_service: Optional BackgroundJobService instance (uses global if not provided)
            observability: Optional ObservabilityHub instance (uses global if not provided)
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_lessons = max_lessons
        self.file_allowlist = file_allowlist or get_file_allowlist()
        self._lock = threading.RLock()
        self._lessons: Dict[str, EngineeringLesson] = {}
        self._index: Dict[str, List[str]] = {
            "category": [],
            "tags": [],
            "type": [],
            "severity": [],
        }
        self._sequence_counter = 0

        # Shared infrastructure
        self._event_bus = event_bus or get_event_bus()
        self._job_service = job_service or get_job_service()
        self._observability = observability or get_observability_hub()

        # Configure allowlist for this workspace
        self._configure_allowlist_for_workspace()

        self._load()

        self._register_with_observability()

        # Schedule periodic persistence
        self._schedule_persistence()

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self._observability:
            self._observability.add_health_check(HealthCheck(
                name="engineering_lessons_health",
                component="memory.lessons",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

            # Register component
            self._observability.register_component(ComponentInfo(
                name="EngineeringLessonStorage",
                component_type=ComponentType.SERVICE,
                version="1.0.0",
                description="Engineering lessons, patterns, and anti-patterns storage",
                metadata={},
            ))

    def _health_check(self) -> HealthResult:
        """Health check for EngineeringLessonStorage."""
        lesson_count = len(self._lessons)
        categories = len(set(self._index["category"]))
        tags = len(set(self._index["tags"]))

        return HealthResult(
            name="engineering_lessons_health",
            component="memory.lessons",
            status=HealthStatus.HEALTHY,
            message=f"{lesson_count} lessons, {categories} categories, {tags} tags",
            details={
                "lesson_count": lesson_count,
                "categories": categories,
                "tags": tags,
            },
        )

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to the EventBus."""
        try:
            self._event_bus.emit(event_type, data)
        except Exception:
            # Don't let event publishing break the system
            pass

    def _schedule_persistence(self, interval_seconds: int = 300) -> None:
        """Schedule periodic persistence."""
        # Check if job already exists to avoid duplicate scheduling
        existing_job = self._job_service.get_job("engineering_lessons_persist")
        if existing_job:
            return

        trigger = JobTriggerConfig(
            type=JobTriggerType.RECURRING,
            interval_seconds=interval_seconds,
        )
        self._job_service.schedule(
            job_id="engineering_lessons_persist",
            func=self._save,
            trigger=trigger,
            name="Engineering Lessons Persistence",
            priority=JobPriority.LOW,
        )

    def _configure_allowlist_for_workspace(self):
        """Configure the file allowlist with workspace-specific rules."""
        workspace_str = str(self.workspace)

        # Add rule for workspace root directory
        self.file_allowlist.add_rule(AccessRule(
            pattern=workspace_str,
            operations={FileOperation.LIST, FileOperation.READ},
            description=f"Workspace root directory: {workspace_str}",
            tags={"type": "workspace_root", "workspace": workspace_str},
        ))

        # Add rules for workspace directory contents
        self.file_allowlist.add_rule(AccessRule(
            pattern=f"{workspace_str}/**",
            operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
            description=f"Full access to workspace contents: {workspace_str}",
            tags={"type": "workspace", "workspace": workspace_str},
        ))

        # Add rules for common project directories
        common_dirs = [
            "data/**",
            "logs/**",
            "cache/**",
            "tmp/**",
            "temp/**",
            ".freya/**",
        ]
        for dir_pattern in common_dirs:
            full_pattern = f"{workspace_str}/{dir_pattern}"
            self.file_allowlist.add_rule(AccessRule(
                pattern=full_pattern,
                operations={FileOperation.READ, FileOperation.WRITE, FileOperation.CREATE, FileOperation.MODIFY, FileOperation.DELETE, FileOperation.LIST},
                description=f"Project directory: {dir_pattern}",
                tags={"type": "project_dir", "workspace": workspace_str},
            ))

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_id(self) -> str:
        """Generate a unique ID for a new lesson."""
        import uuid
        return f"lesson_{uuid.uuid4().hex[:12]}"

    def _load(self) -> None:
        """Load lessons from storage file."""
        # Validate read access
        self.file_allowlist.require_allowed(self.storage_path, FileOperation.READ, "EngineeringLessonStorage._load")

        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for lesson_data in data.get("lessons", []):
                lesson = EngineeringLesson.from_dict(lesson_data)
                self._lessons[lesson.id] = lesson

                # Update sequence counter
                self._sequence_counter = max(self._sequence_counter, lesson.sequence + 1)

                # Update indexes
                self._index["category"].append(lesson.category)
                self._index["tags"].extend(lesson.tags)
                self._index["type"].append(lesson.lesson_type)
                self._index["severity"].append(lesson.severity)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # If loading fails, start fresh
            self._lessons = {}
            self._index = {"category": [], "tags": [], "type": [], "severity": []}
            self._sequence_counter = 0

    def _save(self) -> None:
        """Save lessons to storage file."""
        # Validate write access
        self.file_allowlist.require_allowed(self.storage_path, FileOperation.WRITE, "EngineeringLessonStorage._save")

        self._ensure_storage_dir()

        # Write to temporary file first, then rename for atomicity
        temp_path = self.storage_path.with_suffix(".tmp")

        data = {
            "lessons": [lesson.to_dict() for lesson in self._lessons.values()],
            "metadata": {
                "count": len(self._lessons),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "categories": list(set(self._index["category"])),
                "tags": list(set(self._index["tags"])),
            }
        }

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(self.storage_path)

    def store(
        self,
        title: str,
        description: str,
        lesson_type: Union[LessonType, str] = LessonType.PATTERN,
        category: str = "general",
        severity: Union[LessonSeverity, str] = LessonSeverity.RECOMMENDED,
        tags: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        related_ids: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        confidence: float = 0.0,
        code_example: Optional[str] = None,
    ) -> EngineeringLesson:
        """Store a new engineering lesson.

        Args:
            title: Short title for the lesson
            description: Detailed description of the lesson
            lesson_type: Type of lesson (PATTERN, ANTI_PATTERN, DECISION, GUIDELINE, STANDARD)
            category: Category (e.g., "architecture", "testing", "performance")
            severity: Importance level
            tags: List of tags for easier searching
            examples: Code examples or illustrations
            related_ids: IDs of related lessons
            context: Context in which this lesson applies
            rationale: Why this lesson exists
            confidence: Confidence level (0.0 to 1.0)
            code_example: Optional single code example (for consolidation engine)

        Returns:
            The created EngineeringLesson
        """
        with self._lock:
            # Convert enums to strings if needed
            type_str = lesson_type.value if isinstance(lesson_type, LessonType) else lesson_type
            severity_str = severity.value if isinstance(severity, LessonSeverity) else severity

            now = datetime.now(timezone.utc).isoformat()
            self._sequence_counter += 1

            lesson = EngineeringLesson(
                id=self._generate_id(),
                title=title,
                description=description,
                lesson_type=type_str,
                category=category,
                severity=severity_str,
                tags=tags or [],
                examples=examples or [],
                related_ids=related_ids or [],
                context=context or {},
                rationale=rationale,
                timestamp=now,
                updated_at=now,
                sequence=self._sequence_counter,
                confidence=max(0.0, min(1.0, confidence)),
                code_example=code_example,
            )

            # Add to storage
            self._lessons[lesson.id] = lesson

            # Update indexes
            self._index["category"].append(lesson.category)
            self._index["tags"].extend(lesson.tags)
            self._index["type"].append(lesson.lesson_type)
            self._index["severity"].append(lesson.severity)

            # Trim if over limit (remove oldest first)
            if len(self._lessons) > self.max_lessons:
                sorted_ids = sorted(self._lessons.keys(),
                                   key=lambda x: (self._lessons[x].timestamp, self._lessons[x].sequence))
                ids_to_remove = sorted_ids[:len(self._lessons) - self.max_lessons]
                for idx in ids_to_remove:
                    del self._lessons[idx]

            # Save to disk
            self._save()

            # Publish event
            self._publish_event("memory.lesson_stored", {
                "lesson_id": lesson.id,
                "title": lesson.title,
                "lesson_type": lesson.lesson_type,
                "category": lesson.category,
                "severity": lesson.severity,
            })

            return lesson

    def reinforce(
        self,
        lesson_id: str,
        *,
        confidence: float,
        tags: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        rationale: Optional[str] = None,
    ) -> EngineeringLesson:
        """Reinforce an equivalent skill/lesson without creating another durable entry."""
        with self._lock:
            lesson = self._lessons.get(lesson_id)
            if lesson is None:
                raise KeyError(f"Unknown engineering lesson: {lesson_id}")
            lesson.confidence = min(1.0, max(lesson.confidence, confidence) + 0.05)
            if tags:
                lesson.tags = sorted(set(lesson.tags).union(tags))
            if context:
                existing_evidence = list(lesson.context.get("evidence_ids", []))
                incoming_evidence = list(context.get("evidence_ids", []))
                merged_evidence = list(dict.fromkeys([*existing_evidence, *incoming_evidence]))
                lesson.context.update(context)
                lesson.context["evidence_ids"] = merged_evidence
                lesson.context["evidence_count"] = len(merged_evidence)
                lesson.context["reinforcement_count"] = int(
                    lesson.context.get("reinforcement_count", 0)
                ) + 1
            if rationale:
                lesson.rationale = rationale
            lesson.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._publish_event("memory.lesson_reinforced", {
                "lesson_id": lesson.id,
                "title": lesson.title,
                "confidence": lesson.confidence,
            })
            return lesson

    def get(self, lesson_id: str) -> Optional[EngineeringLesson]:
        """Get a specific lesson by ID.

        Args:
            lesson_id: The unique ID of the lesson

        Returns:
            The EngineeringLesson or None if not found
        """
        with self._lock:
            return self._lessons.get(lesson_id)

    def all(self) -> List[EngineeringLesson]:
        """Get all engineering lessons.

        Returns:
            List of all EngineeringLesson objects
        """
        with self._lock:
            return list(self._lessons.values())

    def recent(self, limit: int = 10) -> List[EngineeringLesson]:
        """Get the most recent lessons.

        Args:
            limit: Maximum number of lessons to return

        Returns:
            List of recent EngineeringLesson objects (newest first)
        """
        with self._lock:
            sorted_lessons = sorted(
                self._lessons.values(),
                key=lambda x: (x.timestamp, x.sequence),
                reverse=True
            )
            return sorted_lessons[:limit]

    def search(
        self,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        lesson_type: Optional[Union[LessonType, str]] = None,
        severity: Optional[Union[LessonSeverity, str]] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[EngineeringLesson]:
        """Search lessons by various criteria.

        Args:
            keyword: Search in title, description, and rationale (case-insensitive)
            category: Filter by category
            lesson_type: Filter by lesson type (PATTERN, ANTI_PATTERN, etc.)
            severity: Filter by severity level
            tags: Filter by tags (all tags must match)
            limit: Maximum number of results to return

        Returns:
            List of matching EngineeringLesson objects (newest first)
        """
        with self._lock:
            results = []

            # Convert enums to strings if needed
            type_filter = (lesson_type.value if isinstance(lesson_type, LessonType)
                          else lesson_type if lesson_type else None)
            severity_filter = (severity.value if isinstance(severity, LessonSeverity)
                              else severity if severity else None)

            for lesson in self._lessons.values():
                # Keyword search
                if keyword:
                    keyword_lower = keyword.lower()
                    searchable_text = f"{lesson.title} {lesson.description} {lesson.rationale}".lower()
                    if keyword_lower not in searchable_text:
                        continue

                # Category filter
                if category and lesson.category != category:
                    continue

                # Lesson type filter
                if type_filter and lesson.lesson_type != type_filter:
                    continue

                # Severity filter
                if severity_filter and lesson.severity != severity_filter:
                    continue

                # Tags filter (all tags must match)
                if tags:
                    if not all(tag in lesson.tags for tag in tags):
                        continue

                results.append(lesson)

            # Sort by timestamp (newest first), then by sequence (newest first)
            results.sort(key=lambda x: (x.timestamp, x.sequence), reverse=True)

            return results[:limit]

    def get_patterns(self, category: Optional[str] = None, limit: int = 20) -> List[EngineeringLesson]:
        """Get all pattern lessons.

        Args:
            category: Optional category filter
            limit: Maximum number of results

        Returns:
            List of pattern lessons
        """
        return self.search(
            lesson_type=LessonType.PATTERN,
            category=category,
            limit=limit
        )

    def get_anti_patterns(self, category: Optional[str] = None, limit: int = 20) -> List[EngineeringLesson]:
        """Get all anti-pattern lessons.

        Args:
            category: Optional category filter
            limit: Maximum number of results

        Returns:
            List of anti-pattern lessons
        """
        return self.search(
            lesson_type=LessonType.ANTI_PATTERN,
            category=category,
            limit=limit
        )

    def get_decisions(self, category: Optional[str] = None, limit: int = 20) -> List[EngineeringLesson]:
        """Get all decision lessons.

        Args:
            category: Optional category filter
            limit: Maximum number of results

        Returns:
            List of decision lessons
        """
        return self.search(
            lesson_type=LessonType.DECISION,
            category=category,
            limit=limit
        )

    def count(self) -> int:
        """Get the total number of lessons.

        Returns:
            Number of lessons stored
        """
        with self._lock:
            return len(self._lessons)

    def categories(self) -> List[str]:
        """Get all unique categories.

        Returns:
            List of unique category names
        """
        with self._lock:
            return list(set(self._index["category"]))

    def tags(self) -> List[str]:
        """Get all unique tags.

        Returns:
            List of unique tag names
        """
        with self._lock:
            return list(set(self._index["tags"]))

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the lesson storage.

        Returns:
            Dictionary with summary statistics
        """
        with self._lock:
            by_type = {}
            by_category = {}
            by_severity = {}

            for lesson in self._lessons.values():
                by_type[lesson.lesson_type] = by_type.get(lesson.lesson_type, 0) + 1
                by_category[lesson.category] = by_category.get(lesson.category, 0) + 1
                by_severity[lesson.severity] = by_severity.get(lesson.severity, 0) + 1

            return {
                "total_lessons": len(self._lessons),
                "by_type": by_type,
                "by_category": by_category,
                "by_severity": by_severity,
                "all_tags": list(set(self._index["tags"])),
            }

    def export_json(self, path: Optional[Union[str, Path]] = None) -> str:
        """Export all lessons as JSON.

        Args:
            path: Optional path to save the JSON (defaults to storage path)

        Returns:
            JSON string representation
        """
        with self._lock:
            data = {
                "lessons": [lesson.to_dict() for lesson in self._lessons.values()],
                "summary": self.get_summary(),
            }
            json_str = json.dumps(data, indent=2, ensure_ascii=False)

            if path:
                export_path = Path(path) if isinstance(path, str) else path
                export_path.parent.mkdir(parents=True, exist_ok=True)
                export_path.write_text(json_str, encoding="utf-8")

            return json_str

    def get_related(self, lesson_id: str, limit: int = 10) -> List[EngineeringLesson]:
        """Get lessons related to a specific lesson.

        Args:
            lesson_id: The ID of the lesson to find related lessons for
            limit: Maximum number of related lessons to return

        Returns:
            List of related EngineeringLesson objects
        """
        with self._lock:
            lesson = self._lessons.get(lesson_id)
            if not lesson:
                return []

            results = []
            for related_id in lesson.related_ids:
                related_lesson = self._lessons.get(related_id)
                if related_lesson:
                    results.append(related_lesson)

            # Also find lessons that reference this lesson
            for other_lesson in self._lessons.values():
                if other_lesson.id != lesson_id and lesson_id in other_lesson.related_ids:
                    if other_lesson not in results:
                        results.append(other_lesson)

            return results[:limit]
