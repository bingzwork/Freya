"""Tests for the Engineering Lesson Storage module.

This module provides comprehensive tests for EngineeringLessonStorage,
EngineeringLesson, LessonType, and LessonSeverity.
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from app.memory.engineering_lessons import (
    EngineeringLessonStorage,
    EngineeringLesson,
    LessonType,
    LessonSeverity,
)


class TestLessonType:
    """Tests for LessonType enum."""

    def test_all_types_exist(self):
        """Test all lesson types exist."""
        assert LessonType.PATTERN.value == "pattern"
        assert LessonType.ANTI_PATTERN.value == "anti_pattern"
        assert LessonType.DECISION.value == "decision"
        assert LessonType.GUIDELINE.value == "guideline"
        assert LessonType.STANDARD.value == "standard"


class TestLessonSeverity:
    """Tests for LessonSeverity enum."""

    def test_all_severities_exist(self):
        """Test all severity levels exist."""
        assert LessonSeverity.INFO.value == "info"
        assert LessonSeverity.RECOMMENDED.value == "recommended"
        assert LessonSeverity.IMPORTANT.value == "important"
        assert LessonSeverity.CRITICAL.value == "critical"


class TestEngineeringLesson:
    """Tests for EngineeringLesson dataclass."""

    def test_create_lesson(self):
        """Test creating an engineering lesson."""
        lesson = EngineeringLesson(
            id="test_id",
            title="Test Lesson",
            description="Test Description",
            lesson_type=LessonType.PATTERN.value,
            category="architecture",
            severity=LessonSeverity.RECOMMENDED.value,
            tags=["python", "oop"],
            examples=["example 1"],
            related_ids=["related_id"],
            context={"framework": "django"},
            rationale="Because it works better",
        )

        assert lesson.id == "test_id"
        assert lesson.title == "Test Lesson"
        assert lesson.description == "Test Description"
        assert lesson.lesson_type == "pattern"
        assert lesson.category == "architecture"
        assert lesson.severity == "recommended"
        assert lesson.tags == ["python", "oop"]
        assert lesson.examples == ["example 1"]
        assert lesson.related_ids == ["related_id"]
        assert lesson.context == {"framework": "django"}
        assert lesson.rationale == "Because it works better"
        assert lesson.timestamp is not None

    def test_lesson_to_dict(self):
        """Test converting lesson to dictionary."""
        lesson = EngineeringLesson(
            id="test_id",
            title="Test",
            description="Desc",
        )
        data = lesson.to_dict()

        assert data["id"] == "test_id"
        assert data["title"] == "Test"
        assert data["description"] == "Desc"

    def test_lesson_from_dict(self):
        """Test creating lesson from dictionary."""
        data = {
            "id": "from_dict_id",
            "title": "From Dict",
            "description": "From Dict Desc",
            "lesson_type": "pattern",
            "category": "testing",
            "severity": "important",
            "tags": ["test"],
            "examples": [],
            "related_ids": [],
            "context": {},
            "rationale": "",
            "timestamp": "2026-07-20T00:00:00+00:00",
            "updated_at": "2026-07-20T00:00:00+00:00",
        }
        lesson = EngineeringLesson.from_dict(data)

        assert lesson.id == "from_dict_id"
        assert lesson.title == "From Dict"
        assert lesson.lesson_type == "pattern"
        assert lesson.category == "testing"

    def test_is_pattern(self):
        """Test is_pattern property."""
        pattern = EngineeringLesson(
            id="1", title="P", description="D", lesson_type=LessonType.PATTERN.value
        )
        anti_pattern = EngineeringLesson(
            id="2", title="AP", description="D", lesson_type=LessonType.ANTI_PATTERN.value
        )

        assert pattern.is_pattern is True
        assert anti_pattern.is_pattern is False

    def test_is_anti_pattern(self):
        """Test is_anti_pattern property."""
        anti_pattern = EngineeringLesson(
            id="1", title="AP", description="D", lesson_type=LessonType.ANTI_PATTERN.value
        )
        pattern = EngineeringLesson(
            id="2", title="P", description="D", lesson_type=LessonType.PATTERN.value
        )

        assert anti_pattern.is_anti_pattern is True
        assert pattern.is_anti_pattern is False

    def test_is_decision(self):
        """Test is_decision property."""
        decision = EngineeringLesson(
            id="1", title="D", description="D", lesson_type=LessonType.DECISION.value
        )
        pattern = EngineeringLesson(
            id="2", title="P", description="D", lesson_type=LessonType.PATTERN.value
        )

        assert decision.is_decision is True
        assert pattern.is_decision is False


class TestEngineeringLessonStorage:
    """Tests for EngineeringLessonStorage class."""

    @pytest.fixture
    def temp_lessons(self, tmp_path):
        """Create a temporary EngineeringLessonStorage instance."""
        workspace = str(tmp_path)
        storage_path = "memory/engineering_lessons.json"
        storage = EngineeringLessonStorage(workspace=workspace, storage_path=storage_path)
        return storage

    def test_init_defaults(self, temp_lessons):
        """Test default initialization."""
        assert temp_lessons.workspace.exists()
        assert temp_lessons.max_lessons == 1000
        assert temp_lessons.count() == 0

    def test_store_and_get(self, temp_lessons):
        """Test storing and retrieving a lesson."""
        lesson = temp_lessons.store(
            title="Test Lesson",
            description="This is a test lesson",
        )

        assert lesson.id is not None
        assert lesson.title == "Test Lesson"

        retrieved = temp_lessons.get(lesson.id)
        assert retrieved is not None
        assert retrieved.id == lesson.id
        assert retrieved.title == "Test Lesson"

    def test_store_with_enum_types(self, temp_lessons):
        """Test storing with enum types."""
        lesson = temp_lessons.store(
            title="Pattern",
            description="Desc",
            lesson_type=LessonType.PATTERN,
            severity=LessonSeverity.CRITICAL,
        )

        assert lesson.lesson_type == "pattern"
        assert lesson.severity == "critical"

    def test_store_with_string_types(self, temp_lessons):
        """Test storing with string types."""
        lesson = temp_lessons.store(
            title="Pattern",
            description="Desc",
            lesson_type="pattern",
            severity="critical",
        )

        assert lesson.lesson_type == "pattern"
        assert lesson.severity == "critical"

    def test_store_with_all_fields(self, temp_lessons):
        """Test storing with all optional fields."""
        lesson = temp_lessons.store(
            title="Complete Lesson",
            description="Full description",
            lesson_type=LessonType.ANTI_PATTERN,
            category="architecture",
            severity=LessonSeverity.CRITICAL,
            tags=["python", "anti-pattern"],
            examples=["# Bad code\nprint('hello')"],
            related_ids=["related_1", "related_2"],
            context={"language": "python"},
            rationale="Because it causes issues",
        )

        assert lesson.category == "architecture"
        assert lesson.tags == ["python", "anti-pattern"]
        assert len(lesson.examples) == 1
        assert len(lesson.related_ids) == 2
        assert lesson.rationale == "Because it causes issues"

    def test_all_lessons(self, temp_lessons):
        """Test getting all lessons."""
        temp_lessons.store(title="Lesson 1", description="Desc 1")
        temp_lessons.store(title="Lesson 2", description="Desc 2")
        temp_lessons.store(title="Lesson 3", description="Desc 3")

        all_lessons = temp_lessons.all()
        assert len(all_lessons) == 3

    def test_recent_lessons(self, temp_lessons):
        """Test getting recent lessons."""
        for i in range(5):
            temp_lessons.store(title=f"Lesson {i}", description=f"Desc {i}")

        recent = temp_lessons.recent(limit=3)
        assert len(recent) == 3
        # Should be in reverse order (newest first)
        assert recent[0].title == "Lesson 4"
        assert recent[1].title == "Lesson 3"
        assert recent[2].title == "Lesson 2"

    def test_search_by_keyword(self, temp_lessons):
        """Test searching by keyword."""
        temp_lessons.store(
            title="Use Dataclasses",
            description="Dataclasses are great for state management",
            rationale="They provide automatic methods",
        )
        temp_lessons.store(
            title="Other Lesson",
            description="Not related to dataclasses",
        )

        results = temp_lessons.search(keyword="dataclass")
        assert len(results) >= 1
        assert any(entry.title == "Use Dataclasses" for entry in results)

    def test_search_by_category(self, temp_lessons):
        """Test searching by category."""
        temp_lessons.store(title="Arch 1", description="Desc", category="architecture")
        temp_lessons.store(title="Test 1", description="Desc", category="testing")

        arch_results = temp_lessons.search(category="architecture")
        assert len(arch_results) == 1
        assert arch_results[0].category == "architecture"

    def test_search_by_lesson_type(self, temp_lessons):
        """Test searching by lesson type."""
        temp_lessons.store(title="Pattern", description="Desc", lesson_type=LessonType.PATTERN)
        temp_lessons.store(title="Anti-pattern", description="Desc", lesson_type=LessonType.ANTI_PATTERN)

        pattern_results = temp_lessons.search(lesson_type=LessonType.PATTERN)
        assert len(pattern_results) == 1

        # Also test with string
        pattern_results2 = temp_lessons.search(lesson_type="pattern")
        assert len(pattern_results2) == 1

    def test_search_by_severity(self, temp_lessons):
        """Test searching by severity."""
        temp_lessons.store(title="Critical", description="Desc", severity=LessonSeverity.CRITICAL)
        temp_lessons.store(title="Important", description="Desc", severity=LessonSeverity.IMPORTANT)

        critical_results = temp_lessons.search(severity=LessonSeverity.CRITICAL)
        assert len(critical_results) == 1

    def test_search_by_tags(self, temp_lessons):
        """Test searching by tags."""
        temp_lessons.store(title="Tagged", description="Desc", tags=["python", "testing"])
        temp_lessons.store(title="Other", description="Desc", tags=["javascript"])

        python_results = temp_lessons.search(tags=["python"])
        assert len(python_results) == 1

        # Multiple tags (AND logic)
        python_test_results = temp_lessons.search(tags=["python", "testing"])
        assert len(python_test_results) == 1

    def test_get_patterns(self, temp_lessons):
        """Test get_patterns method."""
        temp_lessons.store(title="Pattern 1", description="Desc", lesson_type=LessonType.PATTERN)
        temp_lessons.store(title="Pattern 2", description="Desc", lesson_type=LessonType.PATTERN)
        temp_lessons.store(title="Anti-pattern", description="Desc", lesson_type=LessonType.ANTI_PATTERN)

        patterns = temp_lessons.get_patterns()
        assert len(patterns) == 2
        assert all(p.is_pattern for p in patterns)

    def test_get_anti_patterns(self, temp_lessons):
        """Test get_anti_patterns method."""
        temp_lessons.store(title="Pattern", description="Desc", lesson_type=LessonType.PATTERN)
        temp_lessons.store(title="Anti-pattern 1", description="Desc", lesson_type=LessonType.ANTI_PATTERN)
        temp_lessons.store(title="Anti-pattern 2", description="Desc", lesson_type=LessonType.ANTI_PATTERN)

        anti_patterns = temp_lessons.get_anti_patterns()
        assert len(anti_patterns) == 2
        assert all(ap.is_anti_pattern for ap in anti_patterns)

    def test_get_decisions(self, temp_lessons):
        """Test get_decisions method."""
        temp_lessons.store(title="Decision 1", description="Desc", lesson_type=LessonType.DECISION)
        temp_lessons.store(title="Pattern", description="Desc", lesson_type=LessonType.PATTERN)

        decisions = temp_lessons.get_decisions()
        assert len(decisions) == 1
        assert all(d.is_decision for d in decisions)

    def test_count(self, temp_lessons):
        """Test count method."""
        assert temp_lessons.count() == 0

        temp_lessons.store(title="Lesson 1", description="Desc")
        assert temp_lessons.count() == 1

        temp_lessons.store(title="Lesson 2", description="Desc")
        assert temp_lessons.count() == 2

    def test_categories(self, temp_lessons):
        """Test getting all categories."""
        temp_lessons.store(title="A", description="Desc", category="cat1")
        temp_lessons.store(title="B", description="Desc", category="cat2")
        temp_lessons.store(title="C", description="Desc", category="cat1")

        categories = temp_lessons.categories()
        assert "cat1" in categories
        assert "cat2" in categories

    def test_tags(self, temp_lessons):
        """Test getting all tags."""
        temp_lessons.store(title="A", description="Desc", tags=["tag1", "tag2"])
        temp_lessons.store(title="B", description="Desc", tags=["tag3"])

        all_tags = temp_lessons.tags()
        assert "tag1" in all_tags
        assert "tag2" in all_tags
        assert "tag3" in all_tags

    def test_get_summary(self, temp_lessons):
        """Test get_summary method."""
        temp_lessons.store(
            title="Pattern",
            description="Desc",
            lesson_type=LessonType.PATTERN,
            category="architecture",
            severity=LessonSeverity.RECOMMENDED,
        )
        temp_lessons.store(
            title="Anti-pattern",
            description="Desc",
            lesson_type=LessonType.ANTI_PATTERN,
            category="architecture",
            severity=LessonSeverity.CRITICAL,
        )

        summary = temp_lessons.get_summary()
        assert summary["total_lessons"] == 2
        assert summary["by_type"]["pattern"] == 1
        assert summary["by_type"]["anti_pattern"] == 1
        assert summary["by_category"]["architecture"] == 2
        assert summary["by_severity"]["recommended"] == 1

    def test_persistence(self, tmp_path):
        """Test that lessons persist to disk."""
        workspace = str(tmp_path)
        storage_path = "memory/engineering_lessons.json"

        # Create and store entries
        storage1 = EngineeringLessonStorage(workspace=workspace, storage_path=storage_path)
        storage1.store(title="Persistent Lesson", description="Should persist")
        storage1.store(title="Another Lesson", description="Also persistent")

        # Create new instance and verify entries are loaded
        storage2 = EngineeringLessonStorage(workspace=workspace, storage_path=storage_path)
        all_lessons = storage2.all()

        assert len(all_lessons) == 2
        assert any(l.title == "Persistent Lesson" for l in all_lessons)

    def test_max_lessons_limit(self, tmp_path):
        """Test that max_lessons limit is enforced."""
        workspace = str(tmp_path)
        storage_path = "memory/engineering_lessons.json"

        storage = EngineeringLessonStorage(workspace=workspace, storage_path=storage_path, max_lessons=3)

        # Store 5 lessons
        for i in range(5):
            storage.store(title=f"Lesson {i}", description=f"Desc {i}")

        # Should only have 3 lessons (oldest removed)
        assert storage.count() == 3

        # Should have the 3 newest
        all_lessons = storage.all()
        titles = [l.title for l in all_lessons]
        assert "Lesson 2" in titles
        assert "Lesson 3" in titles
        assert "Lesson 4" in titles
        assert "Lesson 0" not in titles
        assert "Lesson 1" not in titles

    def test_export_json(self, temp_lessons):
        """Test JSON export."""
        temp_lessons.store(title="Export Test", description="Desc")

        json_str = temp_lessons.export_json()
        data = json.loads(json_str)

        assert "lessons" in data
        assert len(data["lessons"]) == 1
        assert data["lessons"][0]["title"] == "Export Test"

    def test_get_nonexistent_lesson(self, temp_lessons):
        """Test getting a non-existent lesson returns None."""
        result = temp_lessons.get("nonexistent_id")
        assert result is None

    def test_search_no_results(self, temp_lessons):
        """Test search with no matches returns empty list."""
        temp_lessons.store(title="Test", description="Desc")
        results = temp_lessons.search(keyword="nonexistent")
        assert results == []

    def test_get_related(self, temp_lessons):
        """Test get_related method."""
        # Store the related lesson first
        related_lesson = temp_lessons.store(
            title="Related Lesson",
            description="Related desc",
        )

        # Store a lesson with related IDs referencing the related lesson
        lesson1 = temp_lessons.store(
            title="Lesson 1",
            description="Desc",
            related_ids=[related_lesson.id],
        )

        # Store another lesson that references lesson1
        temp_lessons.store(
            title="Lesson 2",
            description="Desc",
            related_ids=[lesson1.id],
        )

        # Get related lessons for lesson1
        related = temp_lessons.get_related(lesson1.id)
        assert len(related) >= 1
        assert any(l.id == related_lesson.id for l in related)

        # Also check bidirectional: get related for related_lesson
        related_to_related = temp_lessons.get_related(related_lesson.id)
        assert len(related_to_related) >= 1
        assert any(l.id == lesson1.id for l in related_to_related)

    def test_thread_safety(self, temp_lessons):
        """Test thread-safe operations."""
        import threading

        def store_lesson(i):
            temp_lessons.store(title=f"Thread {i}", description=f"Desc {i}")

        threads = [threading.Thread(target=store_lesson, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert temp_lessons.count() == 10
