"""Tests for Freya's user-facing conversational-control behavior.

The supported runtime routes control requests through ``AgentFacadeImpl`` and
``ConversationControlHandler``. These tests verify the public replies emitted
by that path rather than an obsolete documentation contract or legacy agent
construction.
"""

from unittest.mock import ANY, MagicMock

import pytest

from app.agent.facade_impl import AgentFacadeImpl
from app.conversational_control import ConversationControlHandler, ControlCommand
from app.intent import IntentType
from app.routing.unified_router import ControlCommandParser, RouteResult


# Substrings that MUST NOT appear in user-facing replies during normal
# conversation. They are engine internals (signals, debug labels, internal
# field names) that Freya must hide from users.
PROHIBITED_SUBSTRINGS = (
    "control_command",
    "control_command:",
    "control_command=",
    "capability=",
    "capability:",
    "execution_time=",
    "execution_time:",
)


CONTROL_CASES = (
    ("stop", ControlCommand.STOP, "handle_stop", "Stopped. What's next?"),
    ("cancel", ControlCommand.CANCEL, "handle_cancel", "Cancelled."),
    ("undo", ControlCommand.UNDO, "handle_undo", "Nothing to undo in this session."),
    ("redo", ControlCommand.REDO, "handle_redo", "Nothing to redo."),
    ("status", ControlCommand.STATUS, "handle_status", "Idle. Waiting for next request."),
)


# ------------------------------------------------------------------ #
# Canonical control parsing and handler behavior.
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "trigger,expected_command",
    [
        ("stop", ControlCommand.STOP),
        ("halt", ControlCommand.STOP),
        ("wait", ControlCommand.STOP),
        ("cancel", ControlCommand.CANCEL),
        ("nevermind", ControlCommand.CANCEL),
        ("abort", ControlCommand.CANCEL),
        ("undo", ControlCommand.UNDO),
        ("redo", ControlCommand.REDO),
        ("status", ControlCommand.STATUS),
        ("what are you doing?", ControlCommand.STATUS),
    ],
)
def test_canonical_control_parser_routes_supported_phrases(trigger, expected_command):
    """The production router recognizes each supported conversational-control phrase."""
    assert ControlCommandParser().parse(trigger) is expected_command


@pytest.fixture
def control_handler(tmp_path):
    """A real control handler with isolated infrastructure collaborators."""
    return ConversationControlHandler(
        plan_manager=MagicMock(),
        executor=MagicMock(),
        workspace=str(tmp_path),
        event_bus=MagicMock(),
        job_service=MagicMock(),
        observability=MagicMock(),
    )


@pytest.mark.parametrize("_trigger,_command,method_name,expected_text", CONTROL_CASES)
def test_control_handler_reply_is_user_friendly(
    control_handler,
    _trigger,
    _command,
    method_name,
    expected_text,
):
    """The canonical control handler returns its supported friendly reply."""
    result = getattr(control_handler, method_name)()

    assert result["success"] is True
    assert result["message"] == expected_text
    formatted_lower = result["message"].lower()
    for needle in PROHIBITED_SUBSTRINGS:
        assert needle.lower() not in formatted_lower, (
            f"Control reply for '{method_name}' leaked internal jargon "
            f"'{needle}': {result['message']!r}"
        )


# ------------------------------------------------------------------ #
# Production facade integration (no legacy FreyaAgent construction).
# ------------------------------------------------------------------ #


@pytest.fixture
def facade_with_mocked_components():
    """Build the supported facade with controlled router and handler collaborators."""
    router = MagicMock()
    control = MagicMock()
    chat_activity = MagicMock()
    execution = MagicMock()
    priority_llm = MagicMock()

    control.handle_stop.return_value = {"message": "Stopped. What's next?"}
    control.handle_cancel.return_value = {"message": "Cancelled."}
    control.handle_undo.return_value = {"message": "Nothing to undo in this session."}
    control.handle_redo.return_value = {"message": "Nothing to redo."}
    control.handle_status.return_value = {"message": "Idle. Waiting for next request."}

    route_by_trigger = {
        trigger: RouteResult(
            intent=IntentType.CONVERSATIONAL_CONTROL,
            confidence=1.0,
            reason="Control command",
            is_control=True,
            control_command=command,
        )
        for trigger, command, _method_name, _expected_text in CONTROL_CASES
    }
    control.route_question.side_effect = lambda trigger, **_: route_by_trigger[trigger]

    facade = AgentFacadeImpl(
        router=router,
        execution=execution,
        control=control,
        chat_activity=chat_activity,
        priority_llm=priority_llm,
        memory=MagicMock(),
    )
    return facade, router, control, chat_activity, execution, priority_llm


@pytest.mark.parametrize("trigger,_command,method_name,expected_text", CONTROL_CASES)
def test_canonical_facade_returns_control_reply_without_internal_jargon(
    facade_with_mocked_components,
    trigger,
    _command,
    method_name,
    expected_text,
):
    """Public chat delegates control to the current facade's control handler."""
    facade, router, control, chat_activity, execution, priority_llm = facade_with_mocked_components

    reply = facade.chat(trigger)

    assert reply == expected_text
    control.route_question.assert_called_once_with(trigger, correlation_id=ANY)
    getattr(control, method_name).assert_called_once_with()
    control.record_question_exchange.assert_called_once_with(
        trigger,
        expected_text,
        correlation_id=ANY,
    )
    control.finish_question.assert_called_once_with()
    router.route.assert_not_called()
    priority_llm.ask.assert_not_called()
    execution.execute_plan.assert_not_called()
    chat_activity.chat_started.assert_not_called()
    chat_activity.chat_ended.assert_not_called()
    assert not any(needle in reply.lower() for needle in PROHIBITED_SUBSTRINGS)
