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


def test_execute_task_graph(tmp_path: Path) -> None:
    tools = ToolManager(tmp_path)
    # Register a mock tool for testing
    def mock_tool(name: str, value: int) -> int:
        return value * 2

    tools.register("mock_tool", mock_tool)

    # Create a task graph
    from app.planner.task import Task
    from app.planner.task_graph import TaskGraph

    tg = TaskGraph()
    t1 = Task(id="t1", title="Task 1", metadata={"tool": "mock_tool", "kwargs": {"name": "t1", "value": 5}})
    t2 = Task(id="t2", title="Task 2", metadata={"tool": "mock_tool", "kwargs": {"name": "t2", "value": 10}})
    t3 = Task(id="t3", title="Task 3", metadata={"tool": "mock_tool", "kwargs": {"name": "t3", "value": 20}})
    tg.add_task(t1)
    tg.add_task(t2)
    tg.add_task(t3)
    # t2 and t3 depend on t1
    tg.add_dependency("t1", "t2")
    tg.add_dependency("t1", "t3")

    # Execute the graph
    results = tools.execute_task_graph(tg)

    # Check results
    assert results["t1"].success
    assert results["t1"].output == 10  # 5 * 2
    assert results["t2"].success
    assert results["t2"].output == 20  # 10 * 2
    assert results["t3"].success
    assert results["t3"].output == 40  # 20 * 2
