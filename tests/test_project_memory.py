import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.memory.project_memory import ProjectMemory


@pytest.fixture(autouse=True)
def mock_sentence_transformers(monkeypatch):
    """Mock sentence_transformers to avoid slow model loading in tests."""
    mock_st = MagicMock()
    mock_st.SentenceTransformer = MagicMock(return_value=MagicMock(
        get_sentence_embedding_dimension=MagicMock(return_value=384),
        encode=MagicMock(return_value=[[0.0] * 384]),
    ))
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
    monkeypatch.setattr("app.memory.project_memory.SENTENCE_TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr("app.memory.project_memory.SentenceTransformer", mock_st.SentenceTransformer)


def test_project_memory_persists_entries_and_builds_bounded_context(tmp_path: Path) -> None:
    memory = ProjectMemory(tmp_path, limit=2)
    memory.record("decision", {"choice": "use local models"})
    memory.record("task", {"request": "add tests"})
    memory.record("task", {"request": "add memory"})

    reloaded = ProjectMemory(tmp_path, limit=2)

    assert [item["content"]["request"] for item in reloaded.recent()] == [
        "add tests",
        "add memory",
    ]
    assert "add memory" in reloaded.context(limit=1)


def test_project_memory_recovers_from_invalid_memory_file(tmp_path: Path) -> None:
    path = tmp_path / "data" / "memory" / "freya_memory.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert ProjectMemory(tmp_path).recent() == []
