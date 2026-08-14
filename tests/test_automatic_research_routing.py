from types import SimpleNamespace

import pytest

from app.capabilities.formatter import format_capability_result
from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityResult, CapabilityRouter
from app.core.tool_manager import ToolManager
from app.intelligence.intelligence import AnswerabilityAssessment, ContextEvaluation, Intelligence
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry
from app.research.capability import ResearchCapability
from app.routing.knowledge_first_resolver import KnowledgeFirstResolver


@pytest.fixture(autouse=True)
def reset_registry():
    reset_capability_registry()
    yield
    reset_capability_registry()


class RecordingCapabilityRouter:
    def __init__(self, result=None, matches=None):
        self.result = result or CapabilityResult(
            success=True,
            data={"success": True, "data": {"answer": "Research answer.", "citations": []}},
            capability_name="research_capability",
        )
        self.matches = matches or []
        self.named_calls = []
        self.route_calls = []

    def execute_named(self, name, query, **context):
        self.named_calls.append((name, query, context))
        return self.result

    def find_matching(self, query, intent):
        return self.matches

    def route(self, query, intent, **context):
        self.route_calls.append((query, intent, context))
        return self.result


def make_assessment(
    query,
    *,
    can_answer=False,
    needs_external_information=False,
    requires_fresh_information=False,
    explicit_research_request=False,
    research_reason=None,
):
    context_evaluation = ContextEvaluation(
        query=query,
        retrieved_results=[],
        source_coverage={},
        is_sufficient=can_answer,
        confidence=0.9 if can_answer else 0.2,
    )
    return AnswerabilityAssessment(
        query=query,
        can_answer=can_answer,
        confidence=0.9 if can_answer else 0.2,
        context_evaluation=context_evaluation,
        recommended_action="answer" if can_answer else "use_llm",
        needs_external_information=needs_external_information,
        requires_fresh_information=requires_fresh_information,
        explicit_research_request=explicit_research_request,
        local_knowledge_sufficient=can_answer,
        research_reason=research_reason,
    )


def make_resolver(assessment, router):
    intelligence = SimpleNamespace(
        assess_answerability=lambda query, context: assessment,
        decide_next_action=lambda query, context: {
            "context_for_llm": {},
            "needs_external_information": assessment.needs_external_information,
        },
    )
    return KnowledgeFirstResolver(
        unified_retrieval=SimpleNamespace(retrieve=lambda retrieval_query: []),
        intelligence=intelligence,
        capability_router=router,
        llm_stack=object(),
    )


@pytest.mark.parametrize(
    ("query", "local_knowledge_sufficient", "expected_fresh", "expected_external"),
    [
        ("What's happening with OpenAI today?", True, True, True),
        ("What is NVIDIA's newest GPU?", True, True, True),
        ("Who won the game last night?", False, True, True),
        ("What's Bitcoin trading at?", True, True, True),
        ("What is photosynthesis?", True, False, False),
        ("Explain recursion", True, False, False),
    ],
)
def test_external_information_assessment_recognizes_freshness_without_researching_stable_questions(
    query,
    local_knowledge_sufficient,
    expected_fresh,
    expected_external,
):
    intelligence = Intelligence.__new__(Intelligence)

    decision = intelligence._assess_external_information_requirements(
        query,
        local_knowledge_sufficient=local_knowledge_sufficient,
        context={"intent_type": "question"},
    )

    assert decision["requires_fresh_information"] is expected_fresh
    assert decision["needs_external_information"] is expected_external


@pytest.mark.parametrize(
    "query",
    [
        "Research RTX 5060 performance.",
        "Search the web for this.",
        "Look this up.",
        "Verify this claim.",
        "Find recent information about OpenAI.",
        "Compare current sources about this topic.",
    ],
)
def test_external_information_assessment_honors_explicit_research_requests(query):
    intelligence = Intelligence.__new__(Intelligence)

    decision = intelligence._assess_external_information_requirements(
        query,
        local_knowledge_sufficient=True,
        context={"intent_type": "question"},
    )

    assert decision["explicit_research_request"] is True
    assert decision["needs_external_information"] is True


def test_missing_local_knowledge_for_named_entity_falls_back_to_research():
    intelligence = Intelligence.__new__(Intelligence)

    decision = intelligence._assess_external_information_requirements(
        "Who is the CEO of ExampleCorp?",
        local_knowledge_sufficient=False,
        context={"intent_type": "question"},
    )

    assert decision["needs_external_information"] is True
    assert decision["research_reason"] == "local knowledge is insufficient for an external lookup"


def test_fresh_question_routes_to_research_capability_through_named_capability_router():
    query = "What's happening with OpenAI today?"
    assessment = make_assessment(
        query,
        can_answer=True,
        needs_external_information=True,
        requires_fresh_information=True,
        research_reason="fresh or time-sensitive information requested",
    )
    router = RecordingCapabilityRouter()

    result = make_resolver(assessment, router).resolve(query)

    assert result.action == "capability"
    assert result.capability_name == "research_capability"
    assert result.routing_metadata == {
        "needs_external_information": True,
        "requires_fresh_information": True,
        "explicit_research_request": False,
        "local_knowledge_sufficient": True,
        "research_reason": "fresh or time-sensitive information requested",
    }
    assert router.named_calls[0][0] == "research_capability"
    assert router.named_calls[0][2]["capability_action"] == "research_topic"
    assert router.route_calls == []


def test_explicit_verify_request_uses_verify_claim_action():
    query = "Verify this claim: ExampleCorp released a new product."
    assessment = make_assessment(
        query,
        needs_external_information=True,
        explicit_research_request=True,
        research_reason="explicit external research request",
    )
    router = RecordingCapabilityRouter()

    result = make_resolver(assessment, router).resolve(query)

    assert result.capability_name == "research_capability"
    assert router.named_calls[0][2]["capability_action"] == "verify_claim"
    assert router.named_calls[0][2]["claim"] == "this claim: ExampleCorp released a new product."


def test_research_failure_returns_capability_result_without_llm_fallback():
    query = "Search the web for an unavailable source."
    assessment = make_assessment(
        query,
        needs_external_information=True,
        explicit_research_request=True,
        research_reason="explicit external research request",
    )
    router = RecordingCapabilityRouter(
        result=CapabilityResult(
            success=False,
            message="Insufficient evidence was retrieved to answer this question.",
            capability_name="research_capability",
        )
    )

    result = make_resolver(assessment, router).resolve(query)

    assert result.action == "capability"
    assert result.capability_result.success is False
    assert "local fallback is not fabricated" in result.reasoning[-1]
    assert router.named_calls


def test_stable_local_answer_remains_local_and_nonresearch_capability_routing_remains_available():
    local_query = "Explain recursion"
    local_assessment = make_assessment(local_query, can_answer=True)
    local_router = RecordingCapabilityRouter()
    local_result = make_resolver(local_assessment, local_router).resolve(local_query)

    assert local_result.action == "answer"
    assert local_router.named_calls == []

    capability_query = "Show system status"
    capability_assessment = make_assessment(capability_query)
    capability_router = RecordingCapabilityRouter(
        result=CapabilityResult(success=True, message="All systems operational.", capability_name="system_status"),
        matches=[("system_status", 0.9)],
    )
    capability_result = make_resolver(capability_assessment, capability_router).resolve(capability_query)

    assert capability_result.capability_name == "system_status"
    assert capability_router.route_calls == [(capability_query, "use_llm", {})]


def test_capability_bridge_executes_declared_research_action_without_creating_another_capability(tmp_path):
    registry = CapabilityRegistry()
    research = ResearchCapability()
    calls = []

    def research_topic(inputs):
        calls.append(inputs)
        return {"success": True, "data": {"answer": "Cited result.", "citations": []}}

    research.action_research_topic = research_topic
    tool_manager = ToolManager(str(tmp_path))
    research.set_tool_manager(tool_manager)
    assert registry.register(research, registered_by="test")
    registry.start()
    router = CapabilityRouter()
    CapabilityRegistrationBridge(registry=registry, router=router, tool_manager=tool_manager).sync()

    result = router.execute_named(
        "research_capability",
        query="What is current?",
        capability_action="research_topic",
        topic="What is current?",
    )

    assert result.success is True
    assert calls[0]["topic"] == "What is current?"
    assert router.get_capabilities().count("research_capability") == 1


def test_research_formatter_preserves_citations_and_safe_failure_message():
    research_result = CapabilityResult(
        success=True,
        capability_name="research_capability",
        data={
            "success": True,
            "data": {
                "answer": "The sources agree on the result.",
                "citations": [
                    {"source_title": "Official source", "source_url": "https://example.org/official"},
                    {"source_title": "Independent source", "source_url": "https://example.net/independent"},
                ],
                "uncertainty": ["One secondary source was unavailable."],
            },
        },
    )
    failure = CapabilityResult(
        success=False,
        capability_name="research_capability",
        message="Insufficient evidence was retrieved to answer this question.",
    )

    rendered = format_capability_result(research_result)

    assert "The sources agree on the result." in rendered
    assert "https://example.org/official" in rendered
    assert "Caveats:" in rendered
    failure_message = format_capability_result(failure)
    assert "enough reliable current evidence" in failure_message
