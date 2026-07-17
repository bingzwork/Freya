import io
import sys
from unittest.mock import patch

from app.agent.planner import Planner
from app.agent.executor import Executor


class StubLLM:
    def __init__(self, response: str):
        self.response = response

    def ask(self, prompt: str) -> str:
        return self.response


class StubResult:
    def __init__(self, success: bool = True, output: str = "ok", error: str = ""):
        self.success = success
        self.output = output
        self.error = error


class StubTools:
    def execute(self, name: str, **kwargs: object) -> StubResult:
        return StubResult(output={"tool": name, "args": kwargs})


def test_planner_parses_json_plan() -> None:
    plan = Planner(StubLLM('{"steps": ["inspect files"]}')).create_plan("inspect")

    assert plan == {"steps": ["inspect files"]}


def test_executor_selects_and_executes_action() -> None:
    executor = Executor(StubLLM('{"tool": "list_files", "args": {}}'), StubTools())

    result = executor.execute_step("inspect files")

    assert result == {
        "action": {"tool": "list_files", "args": {}},
        "result": {"tool": "list_files", "args": {}},
    }


def test_executor_blocks_mutating_tool_without_approval() -> None:
    executor = Executor(
        StubLLM('{"tool": "write_file", "args": {"path": "x.py", "content": "x"}}'),
        StubTools(),
    )
    # Mock stdin to provide "2" (No) to the interactive prompt
    with patch("sys.stdin", io.StringIO("2\n")):
        result = executor.execute_step("change a file")

    assert result["error"] == "User denied permission for write_file."
