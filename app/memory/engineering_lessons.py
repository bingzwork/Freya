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
    ):
        """Initialize Engineering Lesson Storage.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            max_lessons: Maximum number of lessons to keep (oldest removed first)
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        self.max_lessons = max_lessons
        self._lock = threading.RLock()
        self._lessons: Dict[str, EngineeringLesson] = {}
        self._index: Dict[str, List[str]] = {
            "category": [],
            "tags": [],
            "type": [],
            "severity": [],
        }
        self._sequence_counter = 0
        self._load()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _generate_id(self) -> str:
        """Generate a unique ID for a new lesson."""
        import uuid
        return f"lesson_{uuid.uuid4().hex[:12]}"

    def _load(self) -> None:
        """Load lessons from storage file."""
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
