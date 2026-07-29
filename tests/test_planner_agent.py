"""Tests for the LLM-driven Planner used by FreyaAgent (`app/agent/planner.py`).

Covers Phase 1 (planning behaviour) and Phase 4 (bracket logging).
"""

import json
import tempfile

import pytest

from app.agent.planner import Planner
from app.planner.plan_manager import Plan
from app.memory.engineering_lessons import (
    EngineeringLessonStorage,
    LessonSeverity,
    LessonType,
)


class StubLLM:
    """Minimal stand-in for `app.core.llm.LLM` used in prompts/exec tests."""

    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def ask(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class StubMemory:
    """Per-keyword memory stub for the optional memory path."""

    def __init__(self, entries=None, raises: bool = False):
        self.entries = entries or []
        self.raises = raises

    def search(self, task: str, limit: int = 3):
        if self.raises:
            raise RuntimeError("memory down")
        return list(self.entries)


# ---------- JSON contract ----------


def test_planner_parses_clean_json_plan():
    plan = Planner(StubLLM('{"steps": ["Read main.py", "Run pytest"]}')).create_plan("build")
    assert isinstance(plan, Plan)
    steps = [t.title for t in plan.tasks]
    assert steps == ["Read main.py", "Run pytest"]


def test_planner_strips_markdown_fences():
    plan = Planner(StubLLM('```json\n{"steps": ["Run pytest"]}\n```')).create_plan("test")
    assert isinstance(plan, Plan)
    steps = [t.title for t in plan.tasks]
    assert steps == ["Run pytest"]


def test_planner_returns_empty_steps_for_non_engineering_task():
    plan = Planner(StubLLM('{"steps": []}')).create_plan("What is Python?")
    assert isinstance(plan, Plan)
    assert plan.tasks == []


def test_planner_caps_steps_at_five():
    raw = json.dumps({"steps": [f"step {i}" for i in range(10)]})
    plan = Planner(StubLLM(raw)).create_plan("build a lot")
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 5
    assert plan.tasks[0].title == "step 0"


def test_planner_wraps_garbage_response_in_fallback_step():
    plan = Planner(StubLLM("not json at all")).create_plan("do thing")
    # Garbage is wrapped into a single string step rather than blowing up.
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 1
    assert isinstance(plan.tasks[0].title, str)
    assert plan.tasks[0].title == "not json at all"


def test_planner_handles_dict_response_without_steps_key():
    plan = Planner(StubLLM('{"foo": "bar"}')).create_plan("weird output")
    # Falls back to wrapping the whole decoded object as a string step.
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 1
    assert "foo" in plan.tasks[0].title


# ---------- Prompt construction ----------


def test_planner_prompt_includes_task_and_step_examples():
    llm = StubLLM('{"steps": []}')
    Planner(llm).create_plan("build my project")
    # The single prompt sent to the LLM should contain the task and the
    # Phase-3 tightened step-examples block.
    assert len(llm.calls) == 1
    prompt = llm.calls[0]
    assert "build my project" in prompt
    assert "Max 5 steps" in prompt or "Max" in prompt
    assert "{\\\"steps\\\": " in prompt or '{"steps":' in prompt
    # JSON-only contract (no markdown fences in the prompt)
    assert "no markdown fences" in prompt.lower()


def test_planner_injects_memory_context_when_available():
    entries = [
        {"kind": "task", "content": {"request": "build", "outcome": "ok"}},
        {"kind": "decision", "content": {"decision": "use pypy"}},
    ]
    llm = StubLLM('{"steps": ["Run pytest"]}')
    Planner(llm, memory=StubMemory(entries)).create_plan("build")
    prompt = llm.calls[0]
    assert "Relevant past experience:" in prompt
    assert "task:" in prompt
    assert "decision:" in prompt


def test_planner_skips_memory_context_when_memory_disabled():
    llm = StubLLM('{"steps": []}')
    Planner(llm, memory=None).create_plan("chat")
    assert "Relevant past experience:" not in llm.calls[0]


def test_planner_swallows_memory_errors():
    """Memory failures must not crash planning; the planner logs no experience."""
    llm = StubLLM('{"steps": []}')
    Planner(llm, memory=StubMemory(raises=True)).create_plan("build")
    # No exception propagated; the prompt still works.
    assert "Relevant past experience:" not in llm.calls[0]


# ---------- Stage-bracket logging ----------


def test_planner_emits_started_and_finished_stage_logs(caplog):
    llm = StubLLM('{"steps": ["Read main.py"]}')
    caplog.set_level("INFO", logger="Freya")
    Planner(llm).create_plan("build")

    info_messages = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    # Two "Started" / "Finished" pairs sandwich one planning call.
    assert "[Planner]" in info_messages
    assert "Started" in info_messages
    assert "Finished" in info_messages
    # Exactly one Started and one Finished per invocation.
    assert info_messages.count("Started") == 1
    assert info_messages.count("Finished") == 1
    # The two [Planner] headers bracket the inner Started/Finished call.
    p_idx = [i for i, m in enumerate(info_messages) if m == "[Planner]"]
    assert len(p_idx) == 2
    assert info_messages[p_idx[0] + 1] == "Started"
    assert info_messages[p_idx[1] + 1] == "Finished"


# ---------- Self-Learning Priority 3: Engineering Lesson retrieval ----------


def _seeded_lessons() -> tuple:
    """Return a fully-populated EngineeringLessonStorage in an isolated workspace."""
    storage = EngineeringLessonStorage(workspace=tempfile.mkdtemp())
    storage.store(
        title="Traceback triage",
        description="Read the traceback first, then locate the failing line.",
        lesson_type=LessonType.PATTERN,
        category="debug",
        severity=LessonSeverity.RECOMMENDED,
    )
    storage.store(
        title="Skip failing test",
        description="Disable the test instead of fixing.",
        lesson_type=LessonType.ANTI_PATTERN,
        category="debug",
        severity=LessonSeverity.IMPORTANT,
    )
    storage.store(
        title="Soft hint",
        description="A nice-to-know tip.",
        lesson_type=LessonType.PATTERN,
        category="debug",
        severity=LessonSeverity.INFO,
    )
    storage.store(
        title="Build tip",
        description="Use --no-cache.",
        lesson_type=LessonType.PATTERN,
        category="build",
        severity=LessonSeverity.RECOMMENDED,
    )
    return storage


def test_planner_prompt_includes_seeded_pattern_lesson():
    """A seeded PATTERN lesson that matches the task category is surfaced."""
    storage = _seeded_lessons()
    llm = StubLLM('{"steps": ["Debug the failing test"]}')
    Planner(llm, engineering_lessons=storage).create_plan("Debug the failing import")
    prompt = llm.calls[0]
    assert "Past Engineering Lessons:" in prompt
    assert "Traceback triage" in prompt
    # The pattern lesson should be tagged with its severity.
    assert "[recommended]" in prompt


def test_planner_prompt_excludes_anti_pattern_lesson():
    """ANTI_PATTERN lessons must not appear in the planner prompt."""
    storage = _seeded_lessons()
    llm = StubLLM('{"steps": []}')
    Planner(llm, engineering_lessons=storage).create_plan("Debug the failing import")
    prompt = llm.calls[0]
    assert "Skip failing test" not in prompt


def test_planner_prompt_excludes_info_severity():
    """INFO-severity lessons are filtered out of the planner prompt."""
    storage = _seeded_lessons()
    llm = StubLLM('{"steps": []}')
    Planner(llm, engineering_lessons=storage).create_plan("Debug the failing import")
    assert "Soft hint" not in llm.calls[0]


def test_planner_prompt_excludes_other_categories():
    """Only lessons whose category matches the inferred task category are surfaced."""
    storage = _seeded_lessons()
    llm = StubLLM('{"steps": []}')
    Planner(llm, engineering_lessons=storage).create_plan("Debug the failing import")
    assert "Build tip" not in llm.calls[0]


def test_planner_prompt_scopes_lesson_section_with_severity_and_recency():
    """Up to three lessons are surfaced, ordered CRITICAL > IMPORTANT > RECOMMENDED."""
    storage = EngineeringLessonStorage(workspace=tempfile.mkdtemp())
    storage.store(
        title="R1", description="r1",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.RECOMMENDED,
    )
    storage.store(
        title="I1", description="i1",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.IMPORTANT,
    )
    storage.store(
        title="C1", description="c1",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.CRITICAL,
    )
    storage.store(
        title="R2", description="r2",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.RECOMMENDED,
    )
    storage.store(
        title="C2", description="c2",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.CRITICAL,
    )
    storage.store(
        title="I2", description="i2",
        lesson_type=LessonType.PATTERN, category="debug",
        severity=LessonSeverity.IMPORTANT,
    )

    llm = StubLLM('{"steps": []}')
    # Task explicitly avoids "test" / "build" keywords so it classifies as "debug".
    Planner(llm, engineering_lessons=storage).create_plan("Fix this bug")
    prompt = llm.calls[0]

    section = prompt[prompt.index("Past Engineering Lessons:"):]
    # Only the lines formatted as lesson bullets share the ``[severity]`` prefix.
    listed = [
        line for line in section.splitlines()
        if line.startswith("- [") and "]" in line
    ]
    # Section is capped at three lessons, in the expected severity order.
    assert len(listed) == 3
    assert "C2" in listed[0]
    assert "[critical]" in listed[0]
    assert "C1" in listed[1]
    assert "[critical]" in listed[1]
    assert "I2" in listed[2]
    assert "[important]" in listed[2]
    # Lower-severity lessons are dropped at the cap.
    assert "R1" not in section
    assert "R2" not in section
    assert "I1" not in section


def test_planner_omits_lesson_section_when_no_engineering_lessons():
    """Passing ``engineering_lessons=None`` leaves the prompt unchanged."""
    llm = StubLLM('{"steps": []}')
    Planner(llm).create_plan("Debug a thing")
    assert "Past Engineering Lessons:" not in llm.calls[0]


def test_planner_omits_lesson_section_when_nothing_matches():
    """When no lesson matches the inferred category the section is silently skipped."""
    storage = _seeded_lessons()
    llm = StubLLM('{"steps": []}')
    Planner(llm, engineering_lessons=storage).create_plan("Refactor the messy module")
    # Only "Build tip" matches "build"; the request does not.
    assert "Past Engineering Lessons:" not in llm.calls[0]
