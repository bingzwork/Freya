import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.agent.planner import Planner
from app.agent.executor import Executor
from app.agent.core_agent import FreyaAgent, _classify_engineering_category


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


# --- Self-Learning Priority 2: Engineering Lesson capture from solve()/repair() ---


class _StubVerify(dict):
    """Minimal verification result used by solve()/repair() tests.

    Modeled after the real ``VerificationResult`` (app.verification.runner)
    but with an extra ``stderr`` field that the lesson capture reads when
    the verification fails. Subclassing ``dict`` keeps the test stub
    JSON-serializable (the real frozen dataclass is not, but that is a
    pre-existing limitation of the project memory serializer rather than
    something this test should reproduce).
    """

    def __init__(self, success: bool, stdout: str = "", stderr: str = "", return_code: int = 0):
        super().__init__(success=success, stdout=stdout, stderr=stderr, return_code=return_code)

    def __getattr__(self, key: str):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def test_classify_engineering_category_uses_shared_vocabulary() -> None:
    """The classifier maps tasks to the shared category set with ``task`` as fallback."""
    assert _classify_engineering_category("Run pytest this morning") == "test"
    assert _classify_engineering_category("Build the wheel") == "build"
    assert _classify_engineering_category("Refactor this mess") == "refactor"
    assert _classify_engineering_category("Debug this import error") == "debug"
    assert _classify_engineering_category("Explain this function") == "understand"
    # Fallback
    assert _classify_engineering_category("") == "task"
    assert _classify_engineering_category("Read the file") == "task"


def _make_isolated_agent() -> FreyaAgent:
    """Construct a FreyaAgent with a fully isolated workspace + module patches."""
    temp = tempfile.TemporaryDirectory()
    return FreyaAgent(workspace=temp.name), temp


def _patch_solve_to_succeed(agent: FreyaAgent, task: str) -> None:
    """Make ``agent.solve()`` succeed on the first iteration."""
    iteration_result = {
        "verification": _StubVerify(success=True),
        "rolled_back": False,
        "changes": [],
    }

    def _fake_propose(*_args, **_kwargs):
        return {"operations": []}

    def _fake_apply_and_verify(_tools, _operations, _verifier):
        return iteration_result

    agent.planner.create_plan = lambda _task: {"steps": [task]}
    agent.patch_generator.propose = _fake_propose
    agent.patch_engine.apply_and_verify = _fake_apply_and_verify


def _patch_solve_to_fail(agent: FreyaAgent, task: str, attempts: int = 2) -> None:
    """Make ``agent.solve()`` fail by hitting the verifier.

    ``max_iterations`` is set to the requested number of attempts. The agent
    will iterate ``attempts`` times and then fall through to the failure path.
    """
    iteration_result = {
        "verification": _StubVerify(success=False, stdout="", stderr="boom", return_code=1),
        "rolled_back": False,
        "changes": [],
    }

    def _fake_propose(*_args, **_kwargs):
        return {"operations": []}

    def _fake_apply_and_verify(_tools, _operations, _verifier):
        return iteration_result

    agent.planner.create_plan = lambda _task: {"steps": [task]}
    agent.patch_generator.propose = _fake_propose
    agent.patch_engine.apply_and_verify = _fake_apply_and_verify
    agent.solve.__globals__["_task_iterations"] = attempts  # no-op, kept for clarity


def test_solve_success_stores_pattern_lesson() -> None:
    agent, temp = _make_isolated_agent()
    try:
        _patch_solve_to_succeed(agent, "Read file app/main.py")
        before = agent.engineering_lessons.count()
        result = agent.solve("Read file app/main.py", allow_mutations=True, max_iterations=1)
        after = agent.engineering_lessons.count()

        assert result["success"] is True
        # Exactly one new lesson, classified as PATTERN / RECOMMENDED.
        lessons = agent.engineering_lessons.recent(limit=1)
        assert lessons
        assert lessons[-1].lesson_type == "pattern"
        assert lessons[-1].severity == "recommended"
        assert lessons[-1].category == "task"
        assert after == before + 1
    finally:
        temp.cleanup()


def test_solve_failure_stores_anti_pattern_lesson() -> None:
    agent, temp = _make_isolated_agent()
    try:
        _patch_solve_to_fail(agent, "Debug the import error in app/x.py", attempts=2)
        before = agent.engineering_lessons.count()
        result = agent.solve("Debug the import error in app/x.py", allow_mutations=True, max_iterations=2)
        after = agent.engineering_lessons.count()

        assert result["success"] is False
        # Exactly one new lesson, classified as ANTI_PATTERN / IMPORTANT and the
        # verification reason is preserved in ``examples``.
        lessons = agent.engineering_lessons.recent(limit=1)
        assert lessons
        assert lessons[-1].lesson_type == "anti_pattern"
        assert lessons[-1].severity == "important"
        assert lessons[-1].category == "debug"
        assert "boom" in (lessons[-1].examples or [""])[0]
        assert after == before + 1
    finally:
        temp.cleanup()


def test_repair_outcome_stores_lesson() -> None:
    agent, temp = _make_isolated_agent()
    try:
        iteration_result = {
            "verification": _StubVerify(success=True),
            "rolled_back": False,
            "changes": [],
        }

        def _fake_propose(*_args, **_kwargs):
            return {"operations": []}

        def _fake_apply_and_verify(_tools, _operations, _verifier):
            return iteration_result

        agent.patch_generator.propose = _fake_propose
        agent.patch_engine.apply_and_verify = _fake_apply_and_verify
        agent.verifier.dry_run_verify = lambda: _StubVerify(success=True)

        before = agent.engineering_lessons.count()
        result = agent.repair("Fix the failing test", allow_mutations=True, max_attempts=2)
        after = agent.engineering_lessons.count()

        assert result["success"] is True
        assert after == before + 1
        lessons = agent.engineering_lessons.recent(limit=1)
        assert lessons[-1].lesson_type == "pattern"
        assert lessons[-1].severity == "recommended"
    finally:
        temp.cleanup()
