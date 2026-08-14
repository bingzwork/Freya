from types import SimpleNamespace

from app.routing.knowledge_first_resolver import KnowledgeFirstResolver
from app.verification.answer_verifier import AnswerVerifier


class RecordingLearningPipeline:
    def __init__(self):
        self.candidates = []

    def run(self, candidate):
        self.candidates.append(candidate)
        return SimpleNamespace()


def test_target_fallback_rejects_empty_local_evidence():
    verifier = AnswerVerifier(learning_pipeline=RecordingLearningPipeline())
    assert verifier.verify_fallback_answer(
        answer="Freya can answer this question with confidence.",
        prompt="What can Freya answer?",
        context={"knowledge_first": True, "retrieved_results": []},
    ) is None


def test_target_fallback_accepts_answer_supported_by_retrieval():
    verifier = AnswerVerifier(learning_pipeline=RecordingLearningPipeline())
    answer = "Freya uses the local memory coordinator to retrieve engineering lessons."
    assert verifier.verify_fallback_answer(
        answer=answer,
        prompt="How does Freya retrieve lessons?",
        context={
            "knowledge_first": True,
            "retrieved_results": [
                {"content": "The local memory coordinator retrieves engineering lessons."}
            ],
        },
    ) == answer


def test_target_resolver_preserves_retrieved_evidence_for_verifier():
    evidence = SimpleNamespace(
        content="The local model is used only after internal memory is insufficient.",
        source="lessons",
        source_id="lesson-1",
        score=0.7,
        metadata={},
        timestamp=None,
    )
    assessment = SimpleNamespace(
        can_answer=False,
        confidence=0.2,
        recommended_action="question",
        reasoning=["insufficient"],
        context_evaluation=SimpleNamespace(
            retrieved_results=[evidence],
            source_coverage={"lessons": 1},
        ),
        goal_context=None,
    )
    resolver = KnowledgeFirstResolver(
        unified_retrieval=SimpleNamespace(retrieve=lambda query: [evidence]),
        intelligence=SimpleNamespace(
            assess_answerability=lambda query, context: assessment,
            decide_next_action=lambda query, context: {"context_for_llm": {}},
        ),
        capability_router=SimpleNamespace(find_matching=lambda query, intent: []),
        llm_stack=object(),
    )

    result = resolver.resolve("When is the local model used?")

    assert result.action == "llm_fallback"
    assert result.llm_context["knowledge_first"] is True
    assert result.llm_context["retrieved_results"][0]["source_id"] == "lesson-1"
