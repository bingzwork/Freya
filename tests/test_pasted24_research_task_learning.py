from __future__ import annotations

from types import SimpleNamespace

from app.research.task_learning import (
    ResearchTaskIntent,
    ResearchTaskLearningOrchestrator,
    ResearchTaskSemanticAnalyzer,
)
from app.routing.knowledge_first_resolver import KnowledgeFirstResolver


def test_general_semantics_distinguish_knowledge_study_learning_and_implementation():
    assert ResearchTaskSemanticAnalyzer.analyze("What is Browser Use?").intent == ResearchTaskIntent.KNOWLEDGE_QUERY.value
    assert ResearchTaskSemanticAnalyzer.analyze("Study Open Deep Research's architecture.").intent == ResearchTaskIntent.ARCHITECTURE_STUDY_TASK.value
    assert ResearchTaskSemanticAnalyzer.analyze("Study Playwright and learn its browser lifecycle patterns.").intent == ResearchTaskIntent.RESEARCH_AND_LEARNING_TASK.value
    assert ResearchTaskSemanticAnalyzer.analyze("Use what you learned from Browser Use to improve Freya.").intent == ResearchTaskIntent.IMPLEMENTATION_TASK.value


def test_current_entire_repository_study_requires_fresh_external_inspection():
    semantic = ResearchTaskSemanticAnalyzer.analyze("Study this GitHub repository's entire current architecture")
    assert semantic.requires_task is True
    assert semantic.fresh_external_inspection_required is True
    assert semantic.learning_requested is False


def test_learning_request_is_explicit_and_does_not_apply_implementation():
    semantic = ResearchTaskSemanticAnalyzer.analyze("Learn useful patterns from this framework")
    assert semantic.intent == ResearchTaskIntent.RESEARCH_AND_LEARNING_TASK.value
    assert semantic.learning_requested is True
    assert semantic.implementation_requested is False


def test_knowledge_first_resolver_escalates_study_before_local_knowledge():
    resolver = KnowledgeFirstResolver(
        unified_retrieval=SimpleNamespace(retrieve=lambda query: []),
        intelligence=SimpleNamespace(),
        capability_router=SimpleNamespace(find_matching=lambda *args: []),
        llm_stack=SimpleNamespace(),
    )
    result = resolver.resolve("Study Open Deep Research's architecture")
    assert result.action == "task"
    assert result.routing_metadata["task_required"] is True
    assert result.routing_metadata["local_knowledge_reuse_as_context"] is True


def test_structured_findings_require_provenance_and_verification():
    semantic = ResearchTaskSemanticAnalyzer.analyze("Study Playwright and learn its lifecycle")
    findings = ResearchTaskLearningOrchestrator._structured_findings(
        [{"claim": "A canonical browser session owns lifecycle state", "source_url": "https://example.org/a", "source_title": "Docs", "confidence": 0.9}],
        semantic,
        {},
    )
    assert findings[0]["verification_status"] == "verified"
    assert findings[0]["provenance"]["source_url"] == "https://example.org/a"


def test_conflicted_findings_are_not_admitted_to_learning():
    semantic = ResearchTaskSemanticAnalyzer.analyze("Study a framework and learn reusable patterns")
    findings = ResearchTaskLearningOrchestrator._structured_findings(
        [{"claim": "Conflicting claim", "source_url": "https://example.org/a", "confidence": 0.9}],
        semantic,
        {"conflicts": [{"claims": [{"claim": "a"}, {"claim": "b"}]}]},
    )
    assert findings[0]["verification_status"] == "needs_more_verification"
    assert findings[0]["usefulness"] == "needs_more_verification"


def test_orchestrator_uses_existing_pipeline_only_for_verified_learning():
    class FakePipeline:
        def __init__(self):
            self.candidates = []
        def run(self, candidate):
            self.candidates.append(candidate)
            return SimpleNamespace(final_decision=SimpleNamespace(value="yes"), items_stored_via_memory_coordinator=["lesson-1"])

    pipeline = FakePipeline()
    system = SimpleNamespace(infra=None, learning_pipeline=pipeline)
    router = SimpleNamespace(execute_capability=lambda *args, **kwargs: SimpleNamespace(success=True, data={"data": {"key_findings": [{"claim": "Reusable pattern", "source_url": "https://example.org/docs", "source_title": "Docs", "confidence": 0.9}], "source_count": 1}}))
    semantic = ResearchTaskSemanticAnalyzer.analyze("Study a framework and learn reusable patterns")
    result = ResearchTaskLearningOrchestrator(system, router).run(semantic)
    assert result["success"] is True
    assert result["learning"]["stored"] == 1
    assert len(pipeline.candidates) == 1
    assert pipeline.candidates[0].context["provenance"]["source_url"] == "https://example.org/docs"


def test_research_only_does_not_submit_to_learning_pipeline():
    class RejectIfCalled:
        def run(self, candidate):
            raise AssertionError("learning must not run without explicit request")
    system = SimpleNamespace(infra=None, learning_pipeline=RejectIfCalled())
    router = SimpleNamespace(execute_capability=lambda *args, **kwargs: SimpleNamespace(success=True, data={"data": {"key_findings": [{"claim": "Finding", "source_url": "https://example.org", "confidence": 0.9}]}}))
    semantic = ResearchTaskSemanticAnalyzer.analyze("Study a framework's architecture")
    result = ResearchTaskLearningOrchestrator(system, router).run(semantic)
    assert result["success"] is True
    assert result["learning"]["status"] == "NOT_REQUESTED"
