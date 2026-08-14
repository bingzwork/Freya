"""Focused safety contracts for bounded PriorityLLMProvider outcomes."""

from __future__ import annotations

import time

from app.core.priority_llm import LLMOutcomeKind, LLMPriority, PriorityLLMProvider


class ScriptedLLM:
    """Small deterministic provider boundary used by priority-provider tests."""

    def __init__(self, outcome):
        self.outcome = outcome

    def ask(self, prompt, system, timeout=None):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome()
        return self.outcome

    def get_provider_health(self):
        return {}


def test_priority_llm_returns_structured_unavailable_provider_outcome():
    provider = PriorityLLMProvider(ScriptedLLM(ConnectionError("local service offline")))
    try:
        outcome = provider.ask_outcome("Explain the architecture.", priority=LLMPriority.CHAT)
    finally:
        provider.shutdown()

    assert outcome.kind is LLMOutcomeKind.UNAVAILABLE
    assert outcome.is_success is False
    assert "offline" in outcome.reason


def test_priority_llm_returns_structured_malformed_output_outcome():
    provider = PriorityLLMProvider(ScriptedLLM({"unexpected": "payload"}))
    try:
        outcome = provider.ask_outcome("Explain the architecture.", priority=LLMPriority.CHAT)
    finally:
        provider.shutdown()

    assert outcome.kind is LLMOutcomeKind.MALFORMED_OUTPUT
    assert outcome.is_success is False


def test_priority_llm_bounds_timeout_and_shuts_down_cleanly():
    provider = PriorityLLMProvider(ScriptedLLM(lambda: (time.sleep(0.05), "late response")[1]))
    try:
        outcome = provider.ask_outcome(
            "Explain the architecture.",
            priority=LLMPriority.CHAT,
            timeout=0.01,
        )
    finally:
        provider.shutdown()

    assert outcome.kind is LLMOutcomeKind.TIMEOUT
    assert outcome.is_success is False


def test_priority_llm_marks_post_shutdown_requests_without_calling_provider():
    provider = PriorityLLMProvider(ScriptedLLM("unused"))
    provider.shutdown()

    outcome = provider.ask_outcome("Explain the architecture.", priority=LLMPriority.CHAT)

    assert outcome.kind is LLMOutcomeKind.SHUTDOWN
    assert outcome.is_success is False
