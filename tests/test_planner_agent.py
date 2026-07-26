"""Tests for the LLM-driven Planner used by FreyaAgent (`app/agent/planner.py`).

Covers Phase 1 (planning behaviour) and Phase 4 (bracket logging).
"""

import json

import pytest

from app.agent.planner import Planner


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
    assert plan == {"steps": ["Read main.py", "Run pytest"]}


def test_planner_strips_markdown_fences():
    plan = Planner(StubLLM('```json\n{"steps": ["Run pytest"]}\n```')).create_plan("test")
    assert plan == {"steps": ["Run pytest"]}


def test_planner_returns_empty_steps_for_non_engineering_task():
    plan = Planner(StubLLM('{"steps": []}')).create_plan("What is Python?")
    assert plan == {"steps": []}


def test_planner_caps_steps_at_five():
    raw = json.dumps({"steps": [f"step {i}" for i in range(10)]})
    plan = Planner(StubLLM(raw)).create_plan("build a lot")
    assert len(plan["steps"]) == 5
    assert plan["steps"][0] == "step 0"


def test_planner_wraps_garbage_response_in_fallback_step():
    plan = Planner(StubLLM("not json at all")).create_plan("do thing")
    # Garbage is wrapped into a single string step rather than blowing up.
    assert "steps" in plan
    assert len(plan["steps"]) == 1
    assert isinstance(plan["steps"][0], str)
    assert plan["steps"][0] == "not json at all"


def test_planner_handles_dict_response_without_steps_key():
    plan = Planner(StubLLM('{"foo": "bar"}')).create_plan("weird output")
    # Falls back to wrapping the whole decoded object as a string step.
    assert len(plan["steps"]) == 1
    assert "foo" in plan["steps"][0]


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
