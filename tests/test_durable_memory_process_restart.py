"""Real process-boundary regression coverage for Freya durable memory."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.memory.working_memory import WorkingMemory


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPOSITORY_ROOT / "tests" / "durable_memory_restart_probe.py"


def run_probe(workspace: Path, phase: str) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(workspace), phase],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_supported_durable_memory_survives_complete_process_restart(tmp_path: Path) -> None:
    first = run_probe(tmp_path, "write")
    second = run_probe(tmp_path, "read")

    assert first["phase"] == "write"
    assert second["phase"] == "read"
    assert "CONV-731" in second["conversation"][0]
    assert "SEM-731" in second["semantic"]
    assert any("EPI-731" in title for title in second["episodic"])
    assert any("PROJ-731" in json.dumps(entry) for entry in second["project"])
    assert any("EXP-731" in title for title in second["experience"])
    assert any("ENG-731" in title for title in second["lessons"])
    assert any("GOAL-731" in name for name in second["goals"])
    assert any("TASK-731" in description for description in second["tasks"])


def test_vector_index_and_semantic_recall_survive_process_restart(tmp_path: Path) -> None:
    run_probe(tmp_path, "write")
    second = run_probe(tmp_path, "read")

    assert any("7319" in content for content in second["semantic_recall"])
    vector_files = list((tmp_path / "data" / "vector_db").glob("conversation_vectors.*"))
    assert any(path.suffix == ".faiss" for path in vector_files)
    assert any(path.name.endswith("metadata.json") for path in vector_files)


def test_cross_memory_references_survive_process_restart(tmp_path: Path) -> None:
    run_probe(tmp_path, "write")
    second = run_probe(tmp_path, "read")

    references = [reference for reference in second["references"] if reference["source_id"] == "semantic_marker"]
    assert len(references) == 1
    reference = references[0]
    assert reference["target_memory"] == "project"


def test_working_memory_remains_ephemeral() -> None:
    working = WorkingMemory()
    working.start_task("temporary-task")
    working.set_variable("temporary", "not durable")
    assert working.is_active
    assert working.get_variable("temporary") == "not durable"
    assert not hasattr(working, "storage_path")
