from pathlib import Path

from app.memory.project_memory import ProjectMemory


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
