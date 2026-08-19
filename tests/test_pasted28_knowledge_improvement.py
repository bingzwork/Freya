from app.learning.models import LearningCandidateType
from app.research.capability import ResearchCapability
from app.research.intelligence import (
    KnowledgeFreshness,
    KnowledgeImprovementAssessor,
    KnowledgeImprovementState,
    KnowledgeReconciler,
    ResearchAnswerQualityVerifier,
    RequestSemanticAnalyzer,
)
from app.research.web_adapter import AdapterOutcome, SearchProviderPool


def test_local_baseline_is_enrichable_for_best_model_request():
    semantic = RequestSemanticAnalyzer.analyze("What is the best small local model for Freya?")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(
        semantic.query,
        [{"content": "Freya currently uses a small local model.", "source": "local:memory", "score": 0.9}],
        semantic,
    )
    decision = KnowledgeImprovementAssessor.assess(semantic.query, semantic, snapshot)
    assert decision["state"] == KnowledgeImprovementState.LOCAL_VALID_BUT_ENRICHABLE.value
    assert decision["should_research"] is True


def test_stable_local_explanation_can_remain_local():
    semantic = RequestSemanticAnalyzer.analyze("What is web scraping?")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(
        semantic.query,
        [
            {"content": "Web scraping extracts information from public web pages.", "source": "local:memory", "score": 0.95},
            {"content": "Scrapers commonly parse HTML and structured page content.", "source": "local:memory", "score": 0.9},
        ],
        semantic,
    )
    decision = KnowledgeImprovementAssessor.assess(semantic.query, semantic, snapshot)
    assert decision["state"] == KnowledgeImprovementState.LOCAL_SUFFICIENT_AND_CURRENT.value
    assert decision["should_research"] is False


def test_freshness_sensitive_local_knowledge_is_researched():
    semantic = RequestSemanticAnalyzer.analyze("What is the latest stable version of Python?")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(
        semantic.query,
        [{"content": "Python version is 3.11.", "source": "local:memory", "score": 0.8}],
        semantic,
    )
    decision = KnowledgeImprovementAssessor.assess(semantic.query, semantic, snapshot)
    assert decision["should_research"] is True
    assert decision["freshness"] in {KnowledgeFreshness.HIGH_CHANGE.value, KnowledgeFreshness.REALTIME.value}


def test_reconciliation_preserves_local_and_external_conflict():
    semantic = RequestSemanticAnalyzer.analyze("What is the current software version?")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(
        semantic.query,
        [{"content": "Software X version is 4.2.", "source": "local:memory", "score": 0.9}],
        semantic,
    )
    result = KnowledgeReconciler.reconcile(
        snapshot,
        [{"claim": "Software X version is 4.5.", "source_url": "https://official.example/version", "source_title": "Official release", "evidence_type": "OFFICIAL_DOCUMENTATION", "confidence": 0.95}],
        semantic,
    )
    assert result["status"] == "CONFLICTED"
    assert result["claims"][0]["status"] == "CONFLICT"
    assert "4.2" in result["claims"][0]["local_value"]
    assert "4.5" in result["claims"][0]["external_value"]


def test_reconciliation_identifies_web_only_enrichment():
    semantic = RequestSemanticAnalyzer.analyze("Explain software architecture with examples")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(
        semantic.query,
        [{"content": "Software architecture organizes system components.", "source": "local:memory", "score": 0.9}],
        semantic,
    )
    result = KnowledgeReconciler.reconcile(
        snapshot,
        [{"claim": "Layered architecture separates presentation, application, and data concerns.", "source_url": "https://docs.example/architecture", "confidence": 0.8}],
        semantic,
    )
    assert result["external_claim_count"] == 1
    assert any(item["status"] == "WEB_ONLY" for item in result["claims"])


def test_answer_quality_rejects_unsupported_claims():
    quality = ResearchAnswerQualityVerifier.verify(
        "The verified system supports Python 3.12. It also has unlimited GPU capacity.",
        [{"claim": "The verified system supports Python 3.12.", "source_url": "https://official.example/python"}],
        [{"url": "https://official.example/python"}],
    )
    assert quality["status"] == "PARTIALLY_VERIFIED"
    assert quality["unsupported_claims"]
    assert quality["repair_recommended"] is True


def test_answer_quality_accepts_evidence_grounded_result():
    quality = ResearchAnswerQualityVerifier.verify(
        "Python 3.12 is supported by the official documentation.",
        [{"claim": "Python 3.12 is supported by the official documentation.", "source_url": "https://official.example/python"}],
        [{"url": "https://official.example/python"}],
    )
    assert quality["status"] == "VERIFIED"
    assert quality["unsupported_claims"] == []


def test_search_provider_pool_aggregates_fallback_candidates():
    class Primary:
        name = "primary"

        def search(self, query, *, max_results=5):
            return AdapterOutcome(True, "primary", results=[{"url": "https://one.example", "title": "One"}], attempts=[{"provider": "primary", "success": True}])

    class Secondary:
        name = "secondary"

        def search(self, query, *, max_results=5):
            return AdapterOutcome(True, "secondary", results=[{"url": "https://two.example", "title": "Two"}], attempts=[{"provider": "secondary", "success": True}])

    result = SearchProviderPool(primary=Primary(), secondary=Secondary()).search("topic", max_results=5, multi_provider=True)
    assert result.success is True
    assert {item["url"] for item in result.results} == {"https://one.example", "https://two.example"}
    assert result.metadata["independent_provider_count"] == 2


def test_verified_research_learning_candidate_uses_structured_provenance():
    class Pipeline:
        def __init__(self):
            self.candidate = None

        def run(self, candidate):
            self.candidate = candidate
            return type("Result", (), {"final_decision": type("Decision", (), {"value": "yes"})()})()

    capability = ResearchCapability()
    pipeline = Pipeline()
    capability.set_learning_pipeline(pipeline)
    result = capability.action_learn_finding({
        "remember": True,
        "verified": True,
        "research_result": {
            "topic": "Python current version",
            "answer": "Python 3.12 is supported.",
            "confidence": 0.9,
            "answer_quality": {"status": "VERIFIED"},
            "citations": [{"url": "https://official.example/python"}],
            "supporting_evidence": [{"source_url": "https://official.example/python", "claim": "Python 3.12 is supported."}],
        },
    })
    assert result["accepted"] is True
    assert pipeline.candidate.candidate_type == LearningCandidateType.MANUAL_INPUT
    assert pipeline.candidate.raw_observation["verification_status"] == "verified"
    assert pipeline.candidate.raw_observation["metadata"]["evidence_count"] == 1


def test_user_local_requests_do_not_trigger_improvement_research_by_themselves():
    semantic = RequestSemanticAnalyzer.analyze("Summarize this local file")
    snapshot = KnowledgeImprovementAssessor.build_snapshot(semantic.query, [], semantic)
    assert semantic.intent not in {"NEWS_RESEARCH", "SHOPPING_PRICE_SEARCH"}
    assert snapshot.retrieval_count == 0
