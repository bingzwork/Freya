"""Tests for the Experience Memory module.

This module provides comprehensive tests for ExperienceMemory and ExperienceEntry.
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from app.memory.experience_memory import ExperienceMemory, ExperienceEntry


class TestExperienceEntry:
    """Tests for ExperienceEntry dataclass."""

    def test_create_entry(self):
        """Test creating an experience entry."""
        entry = ExperienceEntry(
            id="test_id",
            title="Test Title",
            description="Test Description",
            category="test_category",
            tags=["tag1", "tag2"],
            outcome="positive",
            confidence=0.8,
            metadata={"key": "value"},
        )

        assert entry.id == "test_id"
        assert entry.title == "Test Title"
        assert entry.description == "Test Description"
        assert entry.category == "test_category"
        assert entry.tags == ["tag1", "tag2"]
        assert entry.outcome == "positive"
        assert entry.confidence == 0.8
        assert entry.metadata == {"key": "value"}
        assert entry.timestamp is not None

    def test_entry_to_dict(self):
        """Test converting entry to dictionary."""
        entry = ExperienceEntry(
            id="test_id",
            title="Test",
            description="Desc",
        )
        data = entry.to_dict()

        assert data["id"] == "test_id"
        assert data["title"] == "Test"
        assert data["description"] == "Desc"

    def test_entry_from_dict(self):
        """Test creating entry from dictionary."""
        data = {
            "id": "from_dict_id",
            "title": "From Dict",
            "description": "From Dict Desc",
            "category": "category",
            "tags": ["a", "b"],
            "outcome": "neutral",
            "confidence": 0.5,
            "metadata": {},
            "timestamp": "2026-07-20T00:00:00+00:00",
        }
        entry = ExperienceEntry.from_dict(data)

        assert entry.id == "from_dict_id"
        assert entry.title == "From Dict"
        assert entry.category == "category"
        assert entry.tags == ["a", "b"]


class TestExperienceMemory:
    """Tests for ExperienceMemory class."""

    @pytest.fixture
    def temp_memory(self, tmp_path):
        """Create a temporary ExperienceMemory instance."""
        workspace = str(tmp_path)
        storage_path = "memory/experience.json"
        memory = ExperienceMemory(workspace=workspace, storage_path=storage_path)
        return memory

    def test_init_defaults(self, temp_memory):
        """Test default initialization."""
        assert temp_memory.workspace.exists()
        assert temp_memory.max_entries == 1000
        assert temp_memory.count() == 0

    def test_store_and_get(self, temp_memory):
        """Test storing and retrieving an experience."""
        entry = temp_memory.store(
            title="Test Experience",
            description="This is a test",
            category="testing",
        )

        assert entry.id is not None
        assert entry.title == "Test Experience"

        retrieved = temp_memory.get(entry.id)
        assert retrieved is not None
        assert retrieved.id == entry.id
        assert retrieved.title == "Test Experience"

    def test_store_with_all_fields(self, temp_memory):
        """Test storing with all optional fields."""
        entry = temp_memory.store(
            title="Full Experience",
            description="Full description",
            category="architecture",
            tags=["python", "best-practice"],
            outcome="positive",
            confidence=0.95,
            metadata={"source": "test"},
        )

        assert entry.outcome == "positive"
        assert entry.confidence == 0.95
        assert entry.tags == ["python", "best-practice"]

    def test_store_confidence_clamping(self, temp_memory):
        """Test that confidence is clamped between 0 and 1."""
        # Test above 1
        entry1 = temp_memory.store(
            title="High Confidence",
            description="Test",
            confidence=1.5,
        )
        assert entry1.confidence == 1.0

        # Test below 0
        entry2 = temp_memory.store(
            title="Low Confidence",
            description="Test",
            confidence=-0.5,
        )
        assert entry2.confidence == 0.0

    def test_all_entries(self, temp_memory):
        """Test getting all entries."""
        temp_memory.store(title="Entry 1", description="Desc 1")
        temp_memory.store(title="Entry 2", description="Desc 2")
        temp_memory.store(title="Entry 3", description="Desc 3")

        all_entries = temp_memory.all()
        assert len(all_entries) == 3

    def test_recent_entries(self, temp_memory):
        """Test getting recent entries."""
        for i in range(5):
            temp_memory.store(title=f"Entry {i}", description=f"Desc {i}")

        recent = temp_memory.recent(limit=3)
        assert len(recent) == 3
        # Should be in reverse order (newest first)
        assert recent[0].title == "Entry 4"
        assert recent[1].title == "Entry 3"
        assert recent[2].title == "Entry 2"

    def test_search_by_keyword(self, temp_memory):
        """Test searching by keyword."""
        temp_memory.store(title="Test Title", description="This is a test", category="test")
        temp_memory.store(title="Other Entry", description="Not related", category="other")

        results = temp_memory.search(keyword="test")
        assert len(results) >= 1
        assert any(entry.title == "Test Title" for entry in results)

    def test_search_by_category(self, temp_memory):
        """Test searching by category."""
        temp_memory.store(title="Arch 1", description="Desc", category="architecture")
        temp_memory.store(title="Test 1", description="Desc", category="testing")

        arch_results = temp_memory.search(category="architecture")
        assert len(arch_results) == 1
        assert arch_results[0].category == "architecture"

    def test_search_by_outcome(self, temp_memory):
        """Test searching by outcome."""
        temp_memory.store(title="Good", description="Desc", outcome="positive")
        temp_memory.store(title="Bad", description="Desc", outcome="negative")
        temp_memory.store(title="Neutral", description="Desc", outcome="neutral")

        positive_results = temp_memory.search(outcome="positive")
        assert len(positive_results) == 1

    def test_search_by_tags(self, temp_memory):
        """Test searching by tags."""
        temp_memory.store(title="Tagged", description="Desc", tags=["python", "testing"])
        temp_memory.store(title="Other", description="Desc", tags=["javascript"])

        python_results = temp_memory.search(tags=["python"])
        assert len(python_results) == 1

        # Multiple tags (AND logic)
        python_test_results = temp_memory.search(tags=["python", "testing"])
        assert len(python_test_results) == 1

    def test_search_by_min_confidence(self, temp_memory):
        """Test searching by minimum confidence."""
        temp_memory.store(title="High", description="Desc", confidence=0.8)
        temp_memory.store(title="High2", description="Desc", confidence=0.7)
        temp_memory.store(title="Medium", description="Desc", confidence=0.5)
        temp_memory.store(title="Low", description="Desc", confidence=0.2)

        high_results = temp_memory.search(min_confidence=0.6)
        assert len(high_results) == 2

    def test_count(self, temp_memory):
        """Test count method."""
        assert temp_memory.count() == 0

        temp_memory.store(title="Entry 1", description="Desc")
        assert temp_memory.count() == 1

        temp_memory.store(title="Entry 2", description="Desc")
        assert temp_memory.count() == 2

    def test_categories(self, temp_memory):
        """Test getting all categories."""
        temp_memory.store(title="A", description="Desc", category="cat1")
        temp_memory.store(title="B", description="Desc", category="cat2")
        temp_memory.store(title="C", description="Desc", category="cat1")

        categories = temp_memory.categories()
        assert "cat1" in categories
        assert "cat2" in categories

    def test_tags(self, temp_memory):
        """Test getting all tags."""
        temp_memory.store(title="A", description="Desc", tags=["tag1", "tag2"])
        temp_memory.store(title="B", description="Desc", tags=["tag3"])

        all_tags = temp_memory.tags()
        assert "tag1" in all_tags
        assert "tag2" in all_tags
        assert "tag3" in all_tags

    def test_get_summary(self, temp_memory):
        """Test get_summary method."""
        temp_memory.store(title="A", description="Desc", category="cat1", outcome="positive")
        temp_memory.store(title="B", description="Desc", category="cat2", outcome="negative")
        temp_memory.store(title="C", description="Desc", category="cat1", outcome="positive")

        summary = temp_memory.get_summary()
        assert summary["total_entries"] == 3
        assert summary["categories"]["cat1"] == 2
        assert summary["categories"]["cat2"] == 1
        assert summary["outcomes"]["positive"] == 2
        assert summary["outcomes"]["negative"] == 1

    def test_persistence(self, tmp_path):
        """Test that entries persist to disk."""
        workspace = str(tmp_path)
        storage_path = "memory/experience.json"

        # Create and store entries
        memory1 = ExperienceMemory(workspace=workspace, storage_path=storage_path)
        memory1.store(title="Persistent Entry", description="Should persist")
        memory1.store(title="Another Entry", description="Also persistent")

        # Create new instance and verify entries are loaded
        memory2 = ExperienceMemory(workspace=workspace, storage_path=storage_path)
        all_entries = memory2.all()

        assert len(all_entries) == 2
        assert any(e.title == "Persistent Entry" for e in all_entries)

    def test_max_entries_limit(self, tmp_path):
        """Test that max_entries limit is enforced."""
        workspace = str(tmp_path)
        storage_path = "memory/experience.json"

        memory = ExperienceMemory(workspace=workspace, storage_path=storage_path, max_entries=3)

        # Store 5 entries
        for i in range(5):
            memory.store(title=f"Entry {i}", description=f"Desc {i}")

        # Should only have 3 entries (oldest removed)
        assert memory.count() == 3

        # Should have the 3 newest
        all_entries = memory.all()
        titles = [e.title for e in all_entries]
        assert "Entry 2" in titles
        assert "Entry 3" in titles
        assert "Entry 4" in titles
        assert "Entry 0" not in titles
        assert "Entry 1" not in titles

    def test_export_json(self, temp_memory):
        """Test JSON export."""
        temp_memory.store(title="Export Test", description="Desc")

        json_str = temp_memory.export_json()
        data = json.loads(json_str)

        assert "entries" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["title"] == "Export Test"

    def test_get_nonexistent_entry(self, temp_memory):
        """Test getting a non-existent entry returns None."""
        result = temp_memory.get("nonexistent_id")
        assert result is None

    def test_search_no_results(self, temp_memory):
        """Test search with no matches returns empty list."""
        temp_memory.store(title="Test", description="Desc")
        results = temp_memory.search(keyword="nonexistent")
        assert results == []

    def test_thread_safety(self, temp_memory):
        """Test thread-safe operations."""
        import threading

        def store_entry(i):
            temp_memory.store(title=f"Thread {i}", description=f"Desc {i}")

        threads = [threading.Thread(target=store_entry, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert temp_memory.count() == 10
