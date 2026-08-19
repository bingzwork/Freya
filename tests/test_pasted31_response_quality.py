from app.capabilities.formatter import ResponseFormatter
from app.capabilities.router import CapabilityResult
from app.research.comparison_intelligence import ComparisonIntelligenceEngine
from app.research.intelligence import RequestSemanticAnalyzer
from ui_server import _direct_social_response, _is_external_factual_request, _missing_research_subject, _semantic_research_query


def test_greeting_is_conversational_not_capability_internal():
    semantic = RequestSemanticAnalyzer.analyze("Hello Freya, what can you help me with?")
    assert semantic.response_type == "conversation"
    answer = _direct_social_response("Hello Freya, what can you help me with?")
    assert answer is not None
    assert "memory_management" not in answer
    assert "registered capability" not in answer


def test_external_factual_questions_are_researchable():
    assert _is_external_factual_request("Who makes the RTX 5090?") is True
    assert _is_external_factual_request("What's the latest stable version of Python?") is True
    assert _is_external_factual_request("What can you help me with?") is False


def test_web_query_normalization_removes_question_wrappers():
    assert _semantic_research_query("What's the latest stable version of Python?") == "Python latest stable version"
    assert _semantic_research_query("Who makes the RTX 5090?") == "RTX 5090 manufacturer official"
    assert "Search the web" not in _semantic_research_query("Search the web for the official NVIDIA RTX 5060 specifications.")


def test_missing_named_subject_asks_for_clarification():
    answer = _missing_research_subject("Research the public work of a named author from reliable sources.")
    assert answer is not None
    assert "Which author" in answer


def test_research_fallback_is_not_a_raw_source_dump():
    result = CapabilityResult(
        success=True,
        capability_name="research_capability",
        data={"results": [{"title": "Python downloads", "url": "https://python.org/downloads/"}]},
    )
    answer = ResponseFormatter().format(result)
    assert "potentially relevant public sources" in answer
    assert "[Python downloads](https://python.org/downloads/)" in answer
    assert "I found these relevant sources:" not in answer


def test_cpu_model_names_are_not_performance_values():
    assert ComparisonIntelligenceEngine._value("AMD Ryzen 7 5700X processor benchmark", "performance") == ""
    assert ComparisonIntelligenceEngine._value("The chip is 1.2x faster in this test", "performance") == "1.2x, faster"


def test_specification_synthesis_rejects_marketing_only_claims():
    semantic = RequestSemanticAnalyzer.analyze("Search the web for the official NVIDIA RTX 5060 specifications.")
    from app.research.intelligence import SynthesisEngine
    answer = SynthesisEngine.synthesize(semantic, [{"claim": "The GPU enables game-changing AI capabilities in the latest games", "source_title": "NVIDIA"}], [], [], []).get("answer", "")
    assert "marketing copy" in answer or "could not verify" in answer or "none contained readable evidence" in answer
    assert "game-changing AI capabilities" not in answer


def test_current_version_prefers_primary_full_version():
    semantic = RequestSemanticAnalyzer.analyze("What's the latest stable version of Python?")
    from app.research.intelligence import SynthesisEngine
    answer = SynthesisEngine.synthesize(semantic, [{"claim": "Python 3.16", "source_title": "Unverified blog", "source_url": "https://example.com"}], [], [], [{"title": "Python Release Python 3.14.7", "url": "https://www.python.org/downloads/release/python-3147"}]).get("answer", "")
    assert "3.14.7" in answer
    assert "3.16" not in answer


def test_missing_subject_gate_covers_ambiguous_and_anaphoric_requests():
    from ui_server import _missing_research_subject
    assert _missing_research_subject("Find the best one.")
    assert _missing_research_subject("what about the other one")
    assert _missing_research_subject("That's wrong; correct the version.")


def test_comparison_query_order_round_robins_entities():
    from app.research.capability import ResearchCapability
    from app.research.comparison_intelligence import ComparisonIntelligenceEngine
    from app.research.intelligence import RequestSemanticAnalyzer
    engine = ComparisonIntelligenceEngine()
    semantic = engine.resolve_semantic(RequestSemanticAnalyzer.analyze("ryzen 7 5700x vs i5 14400"), context={})
    entities = engine.resolve(semantic, context={})
    plan = engine.build_plan(semantic, entities)
    entity_queries = [item for item in ResearchCapability._interleave_entity_queries(plan.queries, entities) if item.get("entity") not in {"shared", "gap", ""}]
    assert len(entity_queries) >= 2
    assert entity_queries[0]["entity"] != entity_queries[1]["entity"]


def test_authoritative_current_fact_extracts_full_patch_version():
    from app.research.capability import ResearchCapability
    semantic = RequestSemanticAnalyzer.analyze("What's the latest stable version of Python?")
    class Response:
        text = "<h1>Python 3.14.7</h1><a>Python 3.14.6</a>"
        def raise_for_status(self):
            return None
    module = __import__("app.research.capability", fromlist=["requests"])
    original = module.requests.get
    try:
        module.requests.get = lambda *args, **kwargs: Response()
        fact = ResearchCapability._authoritative_current_fact("What's the latest stable version of Python?", semantic)
    finally:
        module.requests.get = original
    assert fact is not None
    assert "3.14.7" in fact.claim


def test_image_provider_timeout_is_user_safe(monkeypatch):
    import ui_server
    from types import SimpleNamespace
    monkeypatch.setattr(ui_server, "FREYA", SimpleNamespace(system=SimpleNamespace(facade=SimpleNamespace(_router=object()))))
    def fail(*args, **kwargs):
        raise TimeoutError("provider timeout")
    monkeypatch.setattr(ui_server, "_bounded_call", fail)
    result = ui_server._image_search_by_text("River Lynn", requested_count=3)
    assert result.success is False
    assert result.data["image_results"] == []
    assert "provider" in result.message.lower() or "image" in result.message.lower()
    assert "Traceback" not in result.message


def test_subjectless_conflict_request_clarifies():
    from ui_server import _missing_research_subject
    answer = _missing_research_subject("Which source is correct when two official pages list different release dates?")
    assert answer
    assert "Which release" in answer
    assert "source" not in answer.lower() or "verify" in answer.lower()


def test_specification_intent_handles_explicit_web_prefix():
    semantic = RequestSemanticAnalyzer.analyze("Search the web for the official NVIDIA RTX 5060 specifications.")
    assert semantic.intent == "SPECIFICATION_LOOKUP"
    assert semantic.response_type == "specifications"
