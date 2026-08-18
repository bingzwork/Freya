from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.facade_impl import AgentFacadeImpl
from app.core.events import EventBus
from app.core.request_context import RequestContext
from app.intent.classifier import IntentType
from app.learning.models import LearningCandidate, LearningCandidateType, WorthRememberingDecision
from app.learning.pipeline import LearningPipeline
from app.orchestrator.safety_gate import SafetyGate, SafetyPolicy, SafetyAction, SafetyViolationError
from app.memory.coordinator import MemoryCoordinator
from app.verification.runner import VerificationResult, VerificationStatus


def _route_result(**overrides):
    values = {
        "is_control": False,
        "is_direct_answer": True,
        "is_clarification": False,
        "is_engineering": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_request_context_has_stable_trace_session_and_source_metadata():
    context = RequestContext.create(
        "Explain the request lifecycle",
        session_id="session-test",
        source="user",
        channel="cli",
        attachments=["notes.txt"],
    )
    payload = context.to_dict()

    assert payload["trace_id"].startswith("request_")
    assert payload["correlation_id"] == payload["trace_id"]
    assert payload["request_id"] == payload["trace_id"]
    assert payload["session_id"] == "session-test"
    assert payload["source"] == "user"
    assert payload["channel"] == "cli"
    assert payload["original_message"] == "Explain the request lifecycle"
    assert payload["attachments"] == ["notes.txt"]


def test_facade_propagates_request_context_and_finishes_chat_on_success():
    router = MagicMock()
    control = MagicMock()
    control.route_question.return_value = _route_result()
    execution = MagicMock()
    chat_activity = MagicMock()
    llm = MagicMock()
    facade = AgentFacadeImpl(
        router=router,
        execution=execution,
        control=control,
        chat_activity=chat_activity,
        priority_llm=llm,
        memory=MagicMock(),
    )
    facade._answer_directly = MagicMock(return_value="grounded response")
    context = RequestContext.create("What is Freya?", session_id="session-success").to_dict()

    assert facade.chat("What is Freya?", context=context) == "grounded response"
    route_kwargs = control.route_question.call_args.kwargs
    assert route_kwargs["request_context"]["session_id"] == "session-success"
    assert route_kwargs["request_context"]["trace_id"] == context["trace_id"]
    control.record_question_exchange.assert_called_once()
    assert control.record_question_exchange.call_args.kwargs["request_context"]["trace_id"] == context["trace_id"]
    control.finish_question.assert_called_once_with()


def test_facade_returns_safe_failure_and_finishes_chat_when_routing_raises():
    router = MagicMock()
    control = MagicMock()
    control.route_question.side_effect = RuntimeError("router unavailable")
    facade = AgentFacadeImpl(
        router=router,
        execution=MagicMock(),
        control=control,
        chat_activity=MagicMock(),
        priority_llm=MagicMock(),
        memory=MagicMock(),
    )

    response = facade.chat("Please do the task", context=RequestContext.create("Please do the task").to_dict())

    assert "couldn't complete" in response.lower()
    assert "router unavailable" not in response.lower()
    control.record_question_exchange.assert_called_once()
    control.finish_question.assert_called_once_with()


def test_verification_result_marks_timeout_as_unknown():
    result = VerificationResult(False, ["verify"], "", "timed out", -1)
    assert result.status is VerificationStatus.UNKNOWN


def test_learning_pipeline_suppresses_unverified_execution_outcome(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = LearningCandidate(
        candidate_type=LearningCandidateType.EXECUTION_OUTCOME,
        timestamp=datetime.now(timezone.utc),
        source_component="ExecutionVerifier",
        raw_observation={
            "task": "run bounded command",
            "execution_success": False,
            "verification_status": "unknown",
            "verification": None,
        },
        context={"verification_status": "unknown"},
        metadata={"outcome": "failed", "verification_success": None},
    )

    result = pipeline.run(candidate)

    assert result.final_decision is WorthRememberingDecision.NO
    assert "not independently verified" in result.worth_remembering_result.reasoning
    assert memory._experience.search(category="execution_outcome") == []



def test_intent_contract_exposes_decision_fields():
    from app.intent.classifier import IntentClassifier

    result = IntentClassifier().classify("Delete this file")
    contract = result.to_contract()

    assert contract["intent"] == result.intent.value
    assert contract["request_kind"] == "action"
    assert contract["action_required"] is True
    assert contract["ambiguity"] in {"confident", "ambiguous", "insufficient_context"}
    assert "risk_hint" in contract


def test_safety_gate_denial_is_fail_closed_and_traceable():
    gate = SafetyGate()
    context = {"trace_id": "request_safety_failure", "session_id": "session-safety"}

    assessment = gate.assess("Destroy system", "system_destruction", context)

    assert assessment.action is SafetyAction.BLOCK
    assert assessment.metadata["trace_id"] == "request_safety_failure"
    try:
        gate.check_and_enforce("Destroy system", "system_destruction", context)
    except SafetyViolationError:
        pass
    else:
        raise AssertionError("blocked operation was not denied")


def test_safety_gate_can_require_approval_without_allowing_execution():
    policy = SafetyPolicy(always_require_approval={"external_api_call"})
    gate = SafetyGate(policy=policy)

    assessment = gate.assess("Call external API", "external_api_call", {"trace_id": "request_approval"})

    assert assessment.action is SafetyAction.REQUIRE_APPROVAL
    assert assessment.requires_approval is True
    assert assessment.allowed is False


def test_verification_timeout_and_llm_boundary_fail_safely():
    timeout = VerificationResult(False, ["verify"], "", "timed out", -1)
    assert timeout.status is VerificationStatus.UNKNOWN

    router = MagicMock()
    control = MagicMock()
    control.route_question.side_effect = RuntimeError("LLM unavailable")
    facade = AgentFacadeImpl(
        router=router,
        execution=MagicMock(),
        control=control,
        chat_activity=MagicMock(),
        priority_llm=MagicMock(),
        memory=MagicMock(),
    )

    response = facade.chat("Answer despite unavailable model", context=RequestContext.create("Answer despite unavailable model").to_dict())

    assert "couldn't complete" in response.lower()
    control.finish_question.assert_called_once_with()


def test_learning_pipeline_suppresses_rejected_answer_candidate(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = LearningCandidate(
        candidate_type=LearningCandidateType.ANSWER_VERIFICATION,
        timestamp=datetime.now(timezone.utc),
        source_component="AnswerVerifier",
        raw_observation={"answer": "unsupported draft", "is_valid_answer": False},
        context={"verification_stage": "fallback_answer_evaluation"},
        metadata={},
    )

    result = pipeline.run(candidate)

    assert result.final_decision is WorthRememberingDecision.NO
    assert "not independently verified" in result.worth_remembering_result.reasoning
