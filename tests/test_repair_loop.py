from pathlib import Path

from app.core.tool_manager import ToolManager
from app.editing.patch_engine import PatchEngine
from app.verification.repair_loop import RepairLoop


class VerificationResult:
    def __init__(self, success, command=None, stdout="", stderr="", return_code=1):
        self.success = success
        self.command = command or []
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code


class SequenceVerifier:
    def __init__(self):
        self.results = [
            VerificationResult(False, ["test"], "", "", 1),
            VerificationResult(True, ["test"], "passed", "", 0),
        ]

    def run_tests(self):
        return self.results.pop(0)

    def dry_run_verify(self):
        # For the purpose of this test, assume dry-run passes
        return VerificationResult(True, ["verify", "tests+lint"], "dry-run ok", "", 0)


def test_repair_loop_retries_after_rollback_and_keeps_verified_change(tmp_path: Path) -> None:
    (tmp_path / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    engine = PatchEngine()
    proposals = [
        engine.parse(
            {"operations": [{"action": "replace", "path": "value.py", "old_text": "VALUE = 1", "new_text": "VALUE = 2"}]}
        ),
        engine.parse(
            {"operations": [{"action": "replace", "path": "value.py", "old_text": "VALUE = 1", "new_text": "VALUE = 3"}]}
        ),
    ]
    feedback = []

    def propose(previous_feedback):
        feedback.append(previous_feedback)
        return proposals.pop(0)

    result = RepairLoop(engine, ToolManager(tmp_path), SequenceVerifier()).run(propose)

    assert result["success"]
    assert len(result["attempts"]) == 2
    assert "Previous verification failed" in feedback[1]
    assert (tmp_path / "value.py").read_text(encoding="utf-8") == "VALUE = 3\n"
