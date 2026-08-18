from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

from app.core.events import EventBus
from app.learning.models import LearningCandidate, LearningCandidateType
from app.learning.pipeline import LearningPipeline
from app.memory.coordinator import MemoryCoordinator
from app.orchestrator.capabilities import LearningPipelineCapability
from app.routing.knowledge_first_resolver import KnowledgeFirstResolver


def _runtime(workspace: Path):
    memory = MemoryCoordinator(workspace, EventBus())
    pipeline = LearningPipeline(memory)
    capability = LearningPipelineCapability()
    capability.set_learning_pipeline(pipeline, memory)
    return memory, pipeline, capability


def _lesson_inputs(**metadata):
    return {
        "title": "Create a verified note file",
        "description": "Use file_output write with a path, keep SafetyGate approval, and verify the file exists.",
        "category": "skill",
        "tags": ["file_output", "procedural"],
        "metadata": {
            "verified": True,
            "verification_status": "verified",
            "capability": "file_output",
            "action": "write",
            "argument_schema": {"path": "string", "content": "string"},
            "safety_requirement": "SafetyGate approval remains required",
            "verification": "read the file and compare content",
            **metadata,
        },
    }


def test_public_store_lesson_distills_verified_procedure_with_operational_metadata(tmp_path):
    memory, _, capability = _runtime(tmp_path)

    result = capability.execute("store_lesson", _lesson_inputs())

    assert result["success"] is True
    stored = memory.engineering_lessons.all()
    assert len(stored) == 1
    lesson = stored[0]
    assert lesson.context["distiller"] == "SkillDistiller"
    assert lesson.context["capability"] == "file_output"
    assert lesson.context["action"] == "write"
    assert lesson.context["skill"]["validation"] == "read the file and compare content"
    assert lesson.context["safety_requirement"].startswith("SafetyGate")
    assert lesson.confidence <= 0.6


def test_distilled_skill_persists_across_memory_restart_and_reaches_planner_context(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    capability.execute("store_lesson", _lesson_inputs())
    first_ids = [lesson.id for lesson in memory.engineering_lessons.all()]

    restarted = MemoryCoordinator(tmp_path, EventBus())
    lessons = restarted.engineering_lessons.search(keyword="verified note file")
    planner_context = restarted.unified_retrieval.retrieve_for_planner("make a note file with supplied text")

    assert [lesson.id for lesson in lessons] == first_ids
    assert "file_output" in planner_context
    assert "SafetyGate" in planner_context
    assert "read the file and compare content" in planner_context


def test_duplicate_verified_lessons_reinforce_without_memory_spam(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    capability.execute("store_lesson", _lesson_inputs())
    first = memory.engineering_lessons.all()[0]
    capability.execute("store_lesson", _lesson_inputs())

    lessons = memory.engineering_lessons.all()
    assert len(lessons) == 1
    assert lessons[0].id == first.id
    assert lessons[0].context["reinforcement_count"] >= 1
    assert len(lessons[0].context["evidence_ids"]) >= 2


def test_concurrent_equivalent_lessons_are_deduplicated(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: capability.execute("store_lesson", _lesson_inputs()), range(4)))

    assert all(result["success"] is True for result in results)
    lessons = memory.engineering_lessons.all()
    assert len(lessons) == 1
    assert lessons[0].context["reinforcement_count"] >= 3
    assert len(lessons[0].context["evidence_ids"]) >= 4


def test_weak_conflict_is_rejected_but_explicit_user_correction_wins(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    memory.store_learned({
        "learning_type": "knowledge",
        "title": "Temporary project codename",
        "content": "The codename is Aurora.",
        "category": "user_fact",
        "confidence": 0.95,
        "source": "verified_execution",
        "metadata": {"authority": "verified_execution", "verified": True},
    })
    memory.store_learned({
        "learning_type": "knowledge",
        "title": "Temporary project codename",
        "content": "The codename is Borealis.",
        "category": "user_fact",
        "confidence": 0.20,
        "source": "model_inference",
        "metadata": {"authority": "model", "verified": False},
    })
    retained = memory.semantic_memory.get("user_fact", "Temporary project codename")
    assert retained.content == "The codename is Aurora."
    assert retained.metadata["conflict_rejected"] is True

    memory.store_learned({
        "learning_type": "knowledge",
        "title": "Temporary project codename",
        "content": "The codename is Orion.",
        "category": "user_fact",
        "confidence": 0.70,
        "source": "user_correction",
        "metadata": {"authority": "user_correction", "user_correction": True},
    })
    corrected = memory.semantic_memory.get("user_fact", "Temporary project codename")
    assert corrected.content == "The codename is Orion."
    assert corrected.metadata["user_correction"] is True


def test_temporal_metadata_survives_distillation_and_restart(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    capability.execute(
        "store_lesson",
        _lesson_inputs(
            observed_at="2026-08-19T00:00:00+00:00",
            valid_until="2026-08-20T00:00:00+00:00",
            temporal_scope="current_status",
        ),
    )
    restarted = MemoryCoordinator(tmp_path, EventBus())
    lesson = restarted.engineering_lessons.search(keyword="verified note file")[0]
    assert lesson.context["observed_at"] == "2026-08-19T00:00:00+00:00"
    assert lesson.context["valid_until"] == "2026-08-20T00:00:00+00:00"
    assert lesson.context["temporal_scope"] == "current_status"


def test_expired_temporal_knowledge_is_marked_stale_on_retrieval(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    memory.store_learned({
        "learning_type": "knowledge",
        "title": "P17 current disposable status",
        "content": "The disposable status was green at observation time.",
        "category": "time_sensitive",
        "confidence": 0.9,
        "source": "verified_research",
        "metadata": {
            "observed_at": "2020-01-01T00:00:00+00:00",
            "valid_until": "2020-01-02T00:00:00+00:00",
            "temporal_scope": "current_status",
        },
    })

    results = memory.unified_retrieval.retrieve("P17 current disposable status")
    semantic = next(result for result in results if result.source == "semantic")
    assert semantic.metadata["stale"] is True
    assert "STALE" in semantic.content
    assert semantic.metadata["temporal"]["valid_until"] == "2020-01-02T00:00:00+00:00"


def test_sensitive_or_hidden_reasoning_content_is_not_promoted(tmp_path):
    memory, pipeline, _ = _runtime(tmp_path)
    candidate = LearningCandidate(
        candidate_type=LearningCandidateType.MANUAL_INPUT,
        source_component="pasted17_sensitive_test",
        source_session_id="sensitive-test",
        raw_observation={
            "title": "Temporary credential",
            "content": "The password=super-secret-value must never be retained.",
            "category": "knowledge",
            "metadata": {"chain_of_thought": "private deliberation", "api_key": "sk-test-secret-value-123456"},
        },
        context={},
        tags=["disposable-test"],
    )

    result = pipeline.run(candidate)

    assert result.final_decision.value == "no"
    assert result.items_stored_via_memory_coordinator == []
    assert memory.semantic_memory.search(query="Temporary credential") == []
    assert memory.experience_memory.search("Temporary credential") == []
    assert memory.engineering_lessons.search(keyword="Temporary credential") == []


def test_failed_execution_is_not_promoted_as_successful_skill(tmp_path):
    memory, pipeline, _ = _runtime(tmp_path)
    candidate = LearningCandidate(
        candidate_type=LearningCandidateType.EXECUTION_OUTCOME,
        source_component="ExecutionVerifier",
        source_session_id="failed-execution-test",
        raw_observation={
            "task": "create a disposable note",
            "execution_success": False,
            "verification_status": "failed",
            "verification": {"success": False, "error": "verification mismatch"},
            "error": "verification mismatch",
        },
        context={"task": "create a disposable note"},
        tags=["failure", "verification"],
    )

    result = pipeline.run(candidate)

    assert result.final_decision.value == "yes"
    assert result.items_stored_via_memory_coordinator
    assert memory.engineering_lessons.all() == []
    experiences = memory.experience_memory.all()
    assert experiences
    assert all(entry.metadata.get("outcome") != "positive" for entry in experiences)


def test_unverified_structured_lesson_is_not_promoted(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    result = capability.execute(
        "store_lesson",
        {
            **_lesson_inputs(),
            "metadata": {
                **_lesson_inputs()["metadata"],
                "verified": False,
                "verification_status": "unknown",
            },
        },
    )

    assert result["success"] is True
    assert memory.engineering_lessons.search(keyword="verified note file") == []


def test_normal_knowledge_first_path_consumes_learned_skill_before_model(tmp_path):
    memory, _, capability = _runtime(tmp_path)
    capability.execute("store_lesson", _lesson_inputs())
    llm_stack = MagicMock()
    resolver = KnowledgeFirstResolver(
        unified_retrieval=memory.unified_retrieval,
        intelligence=MagicMock(),
        capability_router=MagicMock(),
        llm_stack=llm_stack,
    )

    result = resolver.resolve("What is the verified note file procedure?")

    assert result.action == "answer"
    assert result.routing_metadata["local_knowledge_reuse"] is True
    assert result.routing_metadata["model_fallback_suppressed"] is True
    assert "SafetyGate" in result.answer
    llm_stack.assert_not_called()


def test_learning_pipeline_unavailable_is_safe_failure(tmp_path):
    capability = LearningPipelineCapability()
    result = capability.execute("store_lesson", _lesson_inputs())
    assert result["success"] is False
    assert "unavailable" in result["error"].lower()
