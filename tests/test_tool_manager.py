from pathlib import Path

from app.core.tool_manager import ToolManager


def test_read_write_and_replace_file_are_workspace_scoped(tmp_path: Path) -> None:
    tools = ToolManager(tmp_path)

    assert tools.execute("write_file", path="notes.txt", content="first").success
    result = tools.execute(
        "replace_in_file", path="notes.txt", old_text="first", new_text="second"
    )

    assert result.success
    assert tools.execute("read_file", path="notes.txt").output == "second"


def test_replace_rejects_ambiguous_text(tmp_path: Path) -> None:
    tools = ToolManager(tmp_path)
    tools.execute("write_file", path="notes.txt", content="repeat repeat")

    result = tools.execute(
        "replace_in_file", path="notes.txt", old_text="repeat", new_text="done"
    )

    assert not result.success
    assert "exactly once" in result.error


def test_workspace_boundary_cannot_be_bypassed_by_similar_prefix(tmp_path: Path) -> None:
    tools = ToolManager(tmp_path / "project")

    result = tools.execute("read_file", path="../project-other/secret.txt")

    assert not result.success
    assert "Access denied" in result.error


def test_unknown_tool_returns_structured_error(tmp_path: Path) -> None:
    result = ToolManager(tmp_path).execute("not_a_tool")

    assert not result.success
    assert result.error == "Tool not found: not_a_tool"
