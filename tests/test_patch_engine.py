from pathlib import Path

import pytest

from app.core.tool_manager import ToolManager
from app.editing.patch_engine import PatchEngine, PatchValidationError


class StubVerification:
    def __init__(self, success: bool):
        self.success = success

    def run_tests(self):
        return type("Result", (), {"success": self.success})()


def test_patch_engine_applies_replace_and_create(tmp_path: Path) -> None:
    (tmp_path / "existing.py").write_text("VALUE = 1\n", encoding="utf-8")
    engine = PatchEngine()
    operations = engine.parse(
        {
            "operations": [
                {
                    "action": "replace",
                    "path": "existing.py",
                    "old_text": "VALUE = 1",
                    "new_text": "VALUE = 2",
                },
                {
                    "action": "create",
                    "path": "new.py",
                    "new_text": "ENABLED = True\n",
                },
            ]
        }
    )

    results = engine.apply(ToolManager(tmp_path), operations)

    assert [item["path"] for item in results] == ["existing.py", "new.py"]
    assert (tmp_path / "existing.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "ENABLED = True\n"


def test_patch_engine_rejects_invalid_and_empty_operations() -> None:
    engine = PatchEngine()

    with pytest.raises(PatchValidationError, match="non-empty"):
        engine.parse({"operations": []})
    with pytest.raises(PatchValidationError, match="exact original"):
        engine.parse(
            {"operations": [{"action": "replace", "path": "a.py", "new_text": "x"}]}
        )


def test_patch_engine_does_not_overwrite_an_existing_created_file(tmp_path: Path) -> None:
    (tmp_path / "existing.py").write_text("keep", encoding="utf-8")
    engine = PatchEngine()
    operations = engine.parse(
        {"operations": [{"action": "create", "path": "existing.py", "new_text": "new"}]}
    )

    with pytest.raises(PatchValidationError, match="Refusing to overwrite"):
        engine.apply(ToolManager(tmp_path), operations)


def test_failed_verification_rolls_back_every_touched_file(tmp_path: Path) -> None:
    (tmp_path / "existing.py").write_text("VALUE = 1\n", encoding="utf-8")
    engine = PatchEngine()
    operations = engine.parse(
        {
            "operations": [
                {
                    "action": "replace",
                    "path": "existing.py",
                    "old_text": "VALUE = 1",
                    "new_text": "VALUE = 2",
                },
                {"action": "create", "path": "new.py", "new_text": "NEW = True\n"},
            ]
        }
    )

    result = engine.apply_and_verify(
        ToolManager(tmp_path), operations, StubVerification(success=False)
    )

    assert result["rolled_back"]
    assert (tmp_path / "existing.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (tmp_path / "new.py").exists()
