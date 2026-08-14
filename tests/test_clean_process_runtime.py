"""Clean-process integration coverage for the canonical Freya runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_canonical_runtime_starts_exercises_safe_paths_and_shuts_down_in_a_clean_process(tmp_path: Path):
    """Prove the default production graph has no surviving owned workers after shutdown."""
    repository_root = Path(__file__).resolve().parents[1]
    probe = repository_root / "tests" / "clean_runtime_probe.py"
    workspace = tmp_path / "clean-process-workspace"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root)

    completed = subprocess.run(
        [sys.executable, str(probe), str(workspace)],
        cwd=repository_root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["success"] is True
    assert payload["known_memory"] == "freya-clean-process-known-memory-marker"
