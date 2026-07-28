"""Tests for Freya's User Communication Principles.

These tests verify that user-facing replies never expose internal jargon
(intents, classifiers, capability names, control signals, etc.) during
normal conversation. See NATURAL_CONVERSATION.md "User Communication
Principles" for the contract these tests enforce.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.capabilities.formatter import format_capability_result
from app.capabilities.router import route_query


# Substrings that MUST NOT appear in user-facing replies during normal
# conversation. They are engine internals (signals, debug labels, internal
# field names) that the principles require Freya to hide.
PROHIBITED_SUBSTRINGS = (
    "control_command",
    "control_command:",
    "control_command=",
    "capability=",
    "capability:",
    "execution_time=",
    "execution_time:",
)


# ------------------------------------------------------------------ #
# Direct-format tests (formatter + handler integration, no LLM).
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("trigger,expected_text", [
    ("stop", "Stopped. What's next?"),
    ("cancel", "Cancelled."),
    ("undo", "Nothing to undo in this session."),
    ("redo", "Nothing to redo."),
    ("status", "Idle. Waiting for next request."),
])
def test_control_capability_reply_is_user_friendly(trigger, expected_text):
    """The formatted reply for each control command equals its friendly text."""
    result = route_query(trigger, intent_type="conversational_control")
    assert result is not None
    assert result.success is True
    formatted = format_capability_result(result)
    assert formatted == expected_text


@pytest.mark.parametrize("trigger", [
    "stop", "halt", "wait",
    "cancel", "nevermind", "abort",
    "undo", "revert",
    "redo",
    "status", "what are you doing?",
])
def test_control_reply_excludes_jargon(trigger):
    """None of the control-trigger phrases expose internal jargon to the user."""
    result = route_query(trigger, intent_type="conversational_control")
    assert result is not None
    formatted = format_capability_result(result)
    formatted_lower = formatted.lower()
    for needle in PROHIBITED_SUBSTRINGS:
        assert needle.lower() not in formatted_lower, (
            f"Control reply for '{trigger}' leaked internal jargon "
            f"'{needle}': {formatted!r}"
        )


def test_format_failure_hides_internal_phrases():
    """_format_failure strips internal terminology even when error text leaks."""
    from app.capabilities.formatter import ResponseFormatter
    from app.capabilities.router import CapabilityResult

    formatter = ResponseFormatter(debug_mode=False)
    leaky = CapabilityResult(
        success=False,
        message="FileNotFoundError: /tmp/foo. AttributeError: missing. "
                "Traceback (most recent call last).",
        capability_name="test_cap",
    )
    formatted = formatter.format(leaky)
    formatted_lower = formatted.lower()
    # Known exception class names and stack frame markers MUST be stripped.
    assert "filenotfounderror" not in formatted_lower
    assert "attributeerror" not in formatted_lower
    assert "traceback" not in formatted_lower


# ------------------------------------------------------------------ #
# Agent-level integration tests via FreyaAgent.run.
# ------------------------------------------------------------------ #


class MockLLM:
    """Mock LLM that returns whatever the code sent to it (echoes nothing)."""

    def __init__(self, response=""):
        self.response = response

    def ask(self, prompt):
        return self.response


@pytest.fixture
def agent_with_mock_llm(tmp_path: Path):
    """FreyaAgent wired with mocked components; LLM returns empty string."""
    with patch("app.agent.core_agent.LLM") as mock_llm_cls, \
         patch("app.agent.core_agent.ToolManager"), \
         patch("app.agent.core_agent.ProjectMemory"), \
         patch("app.agent.core_agent.Executor"), \
         patch("app.agent.core_agent.Planner") as mock_planner_cls, \
         patch("app.agent.core_agent.PatchEngine"), \
         patch("app.agent.core_agent.PatchGenerator"), \
         patch("app.agent.core_agent.VerificationRunner"), \
         patch("app.core.project_index.ProjectIndex") as mock_proj_cls, \
         patch("app.core.symbol_index.SymbolIndex") as mock_sym_cls, \
         patch("app.intelligence.file_locator.FileLocator"), \
         patch("app.intelligence.lexical_search.LexicalSearch"), \
         patch("app.intelligence.dependency_graph.DependencyGraph"), \
         patch("app.intelligence.context_builder.ContextBuilder"), \
         patch("app.rag.SimpleRetriever"), \
         patch("app.core.logger.logger"):

        mock_llm_cls.return_value = MockLLM()

        proj = MagicMock()
        proj.files = {}
        mock_proj_cls.return_value = proj

        sym = MagicMock()
        sym.files = {}
        sym.symbols = {}
        mock_sym_cls.return_value = sym

        planner = MagicMock()
        planner.create_plan.return_value = {"steps": []}
        mock_planner_cls.return_value = planner

        yield FreyaAgent_factory(tmp_path)


def FreyaAgent_factory(tmp_path):
    """Construct FreyaAgent with the active mocks."""
    from app.agent.core_agent import FreyaAgent
    return FreyaAgent(str(tmp_path))


def test_agent_run_stop_reply_is_friendly(agent_with_mock_llm):
    """`FreyaAgent.run('stop')` returns the user-facing acknowledgement."""
    reply = agent_with_mock_llm.run("stop")
    assert "Stopped" in reply
    assert "control_command" not in reply.lower()


def test_agent_run_cancel_reply_is_friendly(agent_with_mock_llm):
    """`FreyaAgent.run('cancel')` returns the user-facing acknowledgement."""
    reply = agent_with_mock_llm.run("cancel")
    assert "Cancelled" in reply
    assert "control_command" not in reply.lower()


def test_agent_run_status_reply_is_friendly(agent_with_mock_llm):
    """`FreyaAgent.run('status')` returns the user-facing acknowledgement."""
    reply = agent_with_mock_llm.run("status")
    assert reply == "Idle. Waiting for next request."


def test_agent_run_undo_is_friendly_when_no_mutations(agent_with_mock_llm):
    """`FreyaAgent.run('undo')` is a conversational reply, not a stack trace."""
    reply = agent_with_mock_llm.run("undo")
    assert "undo" in reply.lower()
    assert reply.startswith("Nothing to undo")


def test_control_reply_never_contains_caps_dump(agent_with_mock_llm):
    """A `key: value` dump pattern from _format_generic must not surface."""
    for trigger in ("stop", "cancel", "undo", "redo", "status"):
        reply = agent_with_mock_llm.run(trigger)
        # Pattern catches e.g. "control_command: stop" leaking from a dict dump.
        assert not re.search(r"\bcontrol_command\b\s*:", reply), (
            f"Reply for '{trigger}' exposed dict-dump: {reply!r}"
        )


# ------------------------------------------------------------------ #
# Documentation boundary — the principles must be written down.
# ------------------------------------------------------------------ #


def test_natual_conversation_doc_has_principles_section():
    """NATURAL_CONVERSATION.md MUST contain the User Communication Principles."""
    doc = Path("NATURAL_CONVERSATION.md").read_text(encoding="utf-8")
    assert "## User Communication Principles" in doc, (
        "NATURAL_CONVERSATION.md is missing the User Communication Principles section"
    )


def test_natual_conversation_doc_status_row_is_user_facing():
    """The `status` row in Conversational Control MUST NOT advertise developer output."""
    doc = Path("NATURAL_CONVERSATION.md").read_text(encoding="utf-8")
    # Old phrasing must be gone.
    assert "developer-friendly description" not in doc, (
        "NATURAL_CONVERSATION.md still describes the `status` reply as a "
        "'developer-friendly description' — this violates the user-comms "
        "principles."
    )
