import io
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from app.agent.planner import Planner
from app.agent.executor import Executor
from app.agent.core_agent import FreyaAgent, _classify_engineering_category
from app.memory.engineering_lessons import LessonSeverity, LessonType
from app.planner.plan_manager import Plan
from app.planner.task import Task, TaskCategory, TaskStatus
from app.planner.task import Task, TaskStatus, TaskCategory
import uuid


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

    assert isinstance(plan, Plan)
    steps = [t.title for t in plan.tasks]
    assert steps == ["inspect files"]


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


def _make_lessons_storage():
    """Return an isolated EngineeringLessonStorage rooted in a tmp dir."""
    from app.memory.engineering_lessons import EngineeringLessonStorage

    tmp = tempfile.TemporaryDirectory()
    return EngineeringLessonStorage(workspace=tmp.name)



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

    def _make_plan(_task: str) -> Plan:
        t = Task(id=f"task_{uuid.uuid4().hex[:8]}", title=task, category=TaskCategory.IMPLEMENTATION)
        return Plan(tasks=[t])

    agent.planner.create_plan = _make_plan
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

    def _make_plan(_task: str) -> Plan:
        t = Task(id=f"task_{uuid.uuid4().hex[:8]}", title=task, category=TaskCategory.IMPLEMENTATION)
        return Plan(tasks=[t])

    agent.planner.create_plan = _make_plan
    agent.patch_generator.propose = _fake_propose
    agent.patch_engine.apply_and_verify = _fake_apply_and_verify


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


# --- Self-Learning Priority 3: engineered lesson retrieval in repair() ---


def test_repair_prepends_seeded_anti_pattern_on_retry() -> None:
    """After a failed attempt, the next propose() prompt must include past failures."""
    agent, temp = _make_isolated_agent()
    try:
        # Seed an anti-pattern lesson that matches the inferred category.
        agent.engineering_lessons.store(
            title="Do not silence failing tests",
            description="Commenting out the failing assertion hides the regression.",
            lesson_type=LessonType.ANTI_PATTERN,
            category="test",
            severity=LessonSeverity.IMPORTANT,
        )
        # Seed a builder-pattern lesson on the same category to make sure
        # the repair filter (ANTI_PATTERN only) excludes it.
        agent.engineering_lessons.store(
            title="Prefer pytest fixtures",
            description="Reuse fixtures to express shared state.",
            lesson_type=LessonType.PATTERN,
            category="test",
            severity=LessonSeverity.RECOMMENDED,
        )

        # Capture every propose() invocation so we can assert on the prompt.
        seen_prompts = []

        def _fake_propose(prompt, _context):
            seen_prompts.append(prompt)
            return {"operations": []}

        # First apply_and_verify fails, second succeeds.
        outcomes = [
            {
                "verification": _StubVerify(success=False, stdout="", stderr="boom", return_code=1),
                "rolled_back": False,
                "changes": [],
            },
            {
                "verification": _StubVerify(success=True),
                "rolled_back": False,
                "changes": [],
            },
        ]

        def _fake_apply_and_verify(_tools, _operations, _verifier):
            return outcomes.pop(0)

        agent.patch_generator.propose = _fake_propose
        agent.patch_engine.apply_and_verify = _fake_apply_and_verify
        agent.verifier.dry_run_verify = lambda: _StubVerify(success=True)

        # A task string that the keyword classifier resolves to ``"test"``
        # so the seeded lesson is in scope. "pytest" wins before any other
        # keyword class so we keep the task minimal.
        result = agent.repair("Run pytest this morning", allow_mutations=True, max_attempts=2)

        assert result["success"] is True
        # Two attempts: the first with empty feedback, the second after a failure.
        assert len(seen_prompts) == 2

        # The first attempt has no past-failures block (RepairLoop starts
        # with empty feedback, mirroring the real-world first attempt).
        assert "Past Similar Failures" not in seen_prompts[0]

        # The retry prompt must contain the seeded ANTI_PATTERN lesson, and
        # must NOT contain the PATTERN-only lesson (filter by lesson_type).
        retry_prompt = seen_prompts[1]
        assert "Past Similar Failures" in retry_prompt
        assert "Do not silence failing tests" in retry_prompt
        assert "Prefer pytest fixtures" not in retry_prompt
        # The original verification feedback still rides along at the end.
        assert "Previous verification failed" in retry_prompt
    finally:
        temp.cleanup()


def test_repair_omits_past_failures_when_nothing_matches() -> None:
    """If no ANTI_PATTERN lesson matches the category, the block is skipped."""
    agent, temp = _make_isolated_agent()
    try:
        # Seed an anti-pattern on a category that the task does NOT match.
        agent.engineering_lessons.store(
            title="Avoid global mutable state",
            description="Singletons make tests hard to isolate.",
            lesson_type=LessonType.ANTI_PATTERN,
            category="build",
            severity=LessonSeverity.CRITICAL,
        )

        seen_prompts = []

        def _fake_propose(prompt, _context):
            seen_prompts.append(prompt)
            return {"operations": []}

        outcomes = [
            {
                "verification": _StubVerify(success=False, stdout="", stderr="boom", return_code=1),
                "rolled_back": False,
                "changes": [],
            },
            {
                "verification": _StubVerify(success=True),
                "rolled_back": False,
                "changes": [],
            },
        ]

        def _fake_apply_and_verify(_tools, _operations, _verifier):
            return outcomes.pop(0)

        agent.patch_generator.propose = _fake_propose
        agent.patch_engine.apply_and_verify = _fake_apply_and_verify
        agent.verifier.dry_run_verify = lambda: _StubVerify(success=True)

        # "Refactor" task: the seeded lesson sits in "build" and must not match.
        result = agent.repair("Refactor the messy module", allow_mutations=True, max_attempts=2)
        assert result["success"] is True
        assert len(seen_prompts) == 2
        assert "Past Similar Failures" not in seen_prompts[1]
        # The retry still carries the verification feedback from RepairLoop.
        assert "Previous verification failed" in seen_prompts[1]
    finally:
        temp.cleanup()


# --- Self-Learning Priority 4: ExperienceMemory writes + run()/Executor integration ---


def test_solve_success_stores_experience_entry() -> None:
    agent, temp = _make_isolated_agent()
    try:
        _patch_solve_to_succeed(agent, "Read file app/main.py")
        before = agent.experience_memory.all()
        result = agent.solve(
            "Read file app/main.py", allow_mutations=True, max_iterations=1
        )
        after = agent.experience_memory.all()

        assert result["success"] is True
        # Exactly one new positive experience entry, classified by category.
        assert len(after) == len(before) + 1
        entry = after[-1]
        assert entry.outcome == "positive"
        assert entry.category == "task"
        assert entry.metadata.get("kind") == "solve"
    finally:
        temp.cleanup()


def test_solve_failure_stores_negative_experience_entry() -> None:
    agent, temp = _make_isolated_agent()
    try:
        _patch_solve_to_fail(agent, "Debug the import error in app/x.py", attempts=2)
        before = agent.experience_memory.all()
        result = agent.solve(
            "Debug the import error in app/x.py",
            allow_mutations=True,
            max_iterations=2,
        )
        after = agent.experience_memory.all()

        assert result["success"] is False
        assert len(after) == len(before) + 1
        entry = after[-1]
        assert entry.outcome == "negative"
        assert entry.category == "debug"
        assert entry.metadata.get("kind") == "solve"
    finally:
        temp.cleanup()


def test_repair_outcome_stores_experience_entry() -> None:
    agent, temp = _make_isolated_agent()
    try:
        def _fake_propose(*_args, **_kwargs):
            return {"operations": []}

        def _fake_apply_and_verify(_tools, _operations, _verifier):
            return {
                "verification": _StubVerify(success=True),
                "rolled_back": False,
                "changes": [],
            }

        agent.patch_generator.propose = _fake_propose
        agent.patch_engine.apply_and_verify = _fake_apply_and_verify
        agent.verifier.dry_run_verify = lambda: _StubVerify(success=True)

        before = agent.experience_memory.all()
        result = agent.repair(
            "Fix the failing test", allow_mutations=True, max_attempts=2
        )
        after = agent.experience_memory.all()

        assert result["success"] is True
        assert len(after) == len(before) + 1
        entry = after[-1]
        assert entry.outcome == "positive"
        assert entry.metadata.get("kind") == "repair"
    finally:
        temp.cleanup()


def test_run_engineering_task_includes_lesson_and_experience_blocks() -> None:
    """``run()`` engineering path must append seeded Engineering Lessons and
    ExperienceMemory hits to the post-execute LLM prompt.
    """
    agent, temp = _make_isolated_agent()
    try:
        agent.engineering_lessons.store(
            title="Reuse pytest fixtures",
            description="Fixtures express shared state more clearly.",
            lesson_type=LessonType.PATTERN,
            category="refactor",
            severity=LessonSeverity.CRITICAL,
        )
        agent.experience_memory.store(
            title="Solved flaky test earlier",
            description="Re-ran the suite after seeding the test fixtures.",
            category="refactor",
            tags=["refactor"],
            outcome="positive",
            confidence=0.9,
        )

        seen_prompts: list[str] = []

        def _fake_ask(prompt: str) -> str:
            seen_prompts.append(prompt)
            return ""

        agent.llm.ask = _fake_ask
        agent.build_context = lambda _task: ""  # type: ignore[assignment]
        agent.memory.context = lambda: ""  # type: ignore[assignment]
        # Stub out the executor so the engineering path completes without
        # touching real tools.
        agent.executor.execute_plan = lambda *_a, **_kw: []  # type: ignore[assignment]
        agent.planner.create_plan = lambda _task: {"steps": ["inspect"]}  # type: ignore[assignment]

        # ``Refactor app/foo.py`` routes to CODE_TASK and clears
        # _has_sufficient_context via has_action_with_file.
        agent.run("Refactor app/foo.py", allow_mutations=False)

        # The post-execute prompt must surface both seeded hooks.
        assert any(
            "Past Lessons (Engineering):" in p and "Reuse pytest fixtures" in p
            for p in seen_prompts
        )
        assert any(
            "Past Experiences:" in p and "Solved flaky test earlier" in p
            for p in seen_prompts
        )
    finally:
        temp.cleanup()


def test_executor_renders_pre_execute_pattern_block() -> None:
    """``Executor._build_pre_execute_lessons_block`` must surface seeded
    PATTERN lessons and exclude ANTI_PATTERN / INFO lessons.
    """
    llm_seen: list[str] = []

    class _CapturingLLM:
        def ask(self, prompt: str) -> str:
            llm_seen.append(prompt)
            return (
                '{"tool": "list_files", "args": {}, "reasoning": "seed prompt"}'
            )

    lessons = _make_lessons_storage()
    lessons.store(
        title="Read before edit",
        description="Always read the file before suggesting changes.",
        lesson_type=LessonType.PATTERN,
        category="task",
        severity=LessonSeverity.CRITICAL,
    )
    lessons.store(
        title="Do not skip failing tests",
        description="Skipping hides regressions.",
        lesson_type=LessonType.ANTI_PATTERN,
        category="task",
        severity=LessonSeverity.IMPORTANT,
    )
    lessons.store(
        title="Hint-only lesson",
        description="Informational hint that must not surface.",
        lesson_type=LessonType.PATTERN,
        category="task",
        severity=LessonSeverity.INFO,
    )

    executor = Executor(_CapturingLLM(), StubTools(), engineering_lessons=lessons)

    block = executor._build_pre_execute_lessons_block("inspect files")
    assert "Past Lessons (Engineering):" in block
    assert "Read before edit" in block
    assert "Do not skip failing tests" not in block
    assert "Hint-only lesson" not in block

    # Confirm the block is also injected into the LLM tool-selection prompt
    # when the executor falls back to the LLM path (no direct keyword match).
    executor.execute_step("describe some unguided step")
    assert any(
        "Past Lessons (Engineering):" in prompt and "Read before edit" in prompt
        for prompt in llm_seen
    )


def test_executor_logs_anti_pattern_hints_on_failed_tool_step() -> None:
    """Failed tool execution must trigger the ANTI_PATTERN hint log path
    without altering the execute_step return shape.
    """
    lessons = _make_lessons_storage()
    lessons.store(
        title="Don't trust exit code only",
        description="Inspect stderr when 本 command exits non-zero.",
        lesson_type=LessonType.ANTI_PATTERN,
        category="task",
        severity=LessonSeverity.IMPORTANT,
    )

    llm_seen: list[str] = []

    class _CapturingLLM:
        def ask(self, prompt: str) -> str:
            llm_seen.append(prompt)
            return '{"tool": "list_files", "args": {}}'

    class _FailingTools:
        def execute(self, name: str, **_kwargs: object) -> StubResult:
            return StubResult(success=False, output="", error="boom")

    executor = Executor(
        _CapturingLLM(), _FailingTools(), engineering_lessons=lessons
    )
    result = executor.execute_step("inspect files")

    # Result shape unchanged: still returns action + error string.
    assert result["action"]["tool"] == "list_files"
    assert result["result"] == "boom"

