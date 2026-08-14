from unittest.mock import patch

from app.core.events import EventBus
from app.learning.models import (
    ExtractedLearning,
    LearningCandidate,
    LearningCandidateType,
    WorthRememberingDecision,
    WorthRememberingResult,
)
from app.learning.pipeline import LearningPipeline
from app.memory.coordinator import MemoryCoordinator


def _candidate(candidate_type=LearningCandidateType.MANUAL_INPUT, **raw_observation):
    return LearningCandidate(
        candidate_type=candidate_type,
        source_component="LearningDistillationRuntimeTest",
        source_session_id="runtime-distillation-test",
        raw_observation=raw_observation or {"observed": True},
        context={"problem": "focused runtime learning verification"},
        tags=["focused-test"],
    )


def _item(learning_type, title, content, category="custom", **metadata):
    return {
        "title": title,
        "content": content,
        "category": category,
        "confidence": 0.9,
        "source": "focused_runtime_test",
        "metadata": {"learning_type": learning_type, **metadata},
    }


def _run_item(pipeline, candidate, item):
    with patch.object(
        pipeline,
        "_extract_learning",
        return_value=ExtractedLearning(candidate_id=candidate.id, knowledge_items=[item]),
    ):
        return pipeline.run(candidate)


def test_worth_remembering_false_discards_without_distillation_or_storage(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate()
    item = _item("knowledge", "Discarded fact", "This item must not be persisted.")

    with patch.object(
        pipeline,
        "_worth_remembering",
        return_value=WorthRememberingResult(
            candidate_id=candidate.id,
            decision=WorthRememberingDecision.NO,
            reasoning="Focused discard test",
        ),
    ):
        result = _run_item(pipeline, candidate, item)

    assert result.final_decision is WorthRememberingDecision.NO
    assert result.classifications == []
    assert result.distilled_items == []
    assert result.items_stored_via_memory_coordinator == []
    assert memory.semantic_memory.search(query="Discarded fact") == []


def test_knowledge_is_distilled_stored_and_retrievable_through_normal_path(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate()
    item = _item(
        "knowledge",
        "Python asyncio event loop",
        "Python asyncio coordinates asynchronous tasks through an event loop.",
        category="language_rule",
        evidence="official Python documentation",
    )

    result = _run_item(pipeline, candidate, item)

    assert [value.learning_type.value for value in result.classifications] == ["knowledge"]
    assert [value.learning_type.value for value in result.distilled_items] == ["knowledge"]
    assert len(result.items_stored_via_memory_coordinator) == 1
    entry = memory.semantic_memory.get("language_rule", "Python asyncio event loop")
    assert entry is not None
    assert entry.metadata["distiller"] == "KnowledgeDistiller"
    assert candidate.id in entry.metadata["evidence_ids"]
    assert "asyncio" in memory.retrieve_for_planning("asyncio event loop").lower()


def test_experience_is_distilled_with_observed_structure_and_stored(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate(task="repair a failing test")
    item = _item(
        "experience",
        "Repairing a failing test",
        "Run the targeted test after correcting the fixture setup.",
        category="execution_outcome",
        context="a test fails because fixture setup is incomplete",
        action="correct the fixture setup and run the targeted test",
        result="the targeted test passed",
        successful_repair="initialize the missing fixture dependency",
        verification="pytest targeted test passed",
        execution_success=True,
    )

    result = _run_item(pipeline, candidate, item)

    assert [value.learning_type.value for value in result.classifications] == ["experience"]
    assert [value.learning_type.value for value in result.distilled_items] == ["experience"]
    entries = memory.experience_memory.search(category="execution_outcome", outcome="positive")
    assert len(entries) == 1
    experience = entries[0]
    assert experience.metadata["distiller"] == "ExperienceDistiller"
    assert experience.metadata["experience"]["action"] == "correct the fixture setup and run the targeted test"
    assert experience.metadata["experience"]["verification"] == "pytest targeted test passed"


def test_skill_is_distilled_stored_as_existing_lesson_and_keeps_validation(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate()
    item = _item(
        "skill",
        "Shorten Windows Python workspace paths",
        "Use a shorter workspace and virtual-environment path before modifying application code.",
        category="skill",
        applicability="Windows Python tooling fails because of path-length limits",
        instructions="Move the workspace or virtual environment to a shorter path, then retry the command",
        validation="the Python tooling command completes without a path-length error",
        failure_handling="collect the remaining path-length error before changing application code",
    )

    result = _run_item(pipeline, candidate, item)

    assert [value.learning_type.value for value in result.classifications] == ["skill"]
    assert [value.learning_type.value for value in result.distilled_items] == ["skill"]
    lessons = memory.engineering_lessons.search(keyword="Shorten Windows Python workspace paths")
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.context["distiller"] == "SkillDistiller"
    assert lesson.context["skill"]["validation"] == "the Python tooling command completes without a path-length error"
    assert lesson.confidence <= 0.6


def test_failed_validation_never_reaches_memory(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate()
    invalid_item = _item("knowledge", "", "This item has no title and must fail validation.")

    result = _run_item(pipeline, candidate, invalid_item)

    assert result.final_decision is WorthRememberingDecision.NO
    assert result.validate_result.rejected_items == [invalid_item]
    assert result.items_stored_via_memory_coordinator == []
    assert memory.semantic_memory.search(query="must fail validation") == []


def test_explicitly_unverified_llm_output_never_reaches_memory(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate(LearningCandidateType.ANSWER_VERIFICATION, verified=False)
    item = _item(
        "knowledge",
        "Unverified model claim",
        "This output has not passed answer verification and must be discarded.",
    )

    result = _run_item(pipeline, candidate, item)

    assert result.final_decision is WorthRememberingDecision.NO
    details = next(iter(result.validate_result.validation_details.values()))
    assert "Unverified answer output" in details["reasons"]
    assert result.items_stored_via_memory_coordinator == []
    assert memory.semantic_memory.search(query="Unverified model claim") == []


def test_duplicate_knowledge_is_upserted_and_reinforced_not_duplicated(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    first = _run_item(
        pipeline,
        _candidate(),
        _item(
            "knowledge",
            "Freya learning storage",
            "Validated learning is written through MemoryCoordinator.",
            category="architecture",
        ),
    )
    second = _run_item(
        pipeline,
        _candidate(),
        _item(
            "knowledge",
            "Freya learning storage",
            "Validated learning is written through MemoryCoordinator.",
            category="architecture",
        ),
    )

    assert len(first.items_stored_via_memory_coordinator) == 1
    assert first.items_stored_via_memory_coordinator == second.items_stored_via_memory_coordinator
    entry = memory.semantic_memory.get("architecture", "Freya learning storage")
    assert entry is not None
    assert entry.metadata["evidence_count"] == 2
    assert entry.metadata["reinforcement_count"] >= 1
    assert len(memory.semantic_memory.search(query="Validated learning is written")) == 1


def test_reusable_experience_derives_a_skill_with_bounded_initial_confidence(tmp_path):
    memory = MemoryCoordinator(tmp_path, EventBus())
    pipeline = LearningPipeline(memory)
    candidate = _candidate()
    item = _item(
        "experience",
        "Repair short workspace paths",
        "A shorter workspace path fixed the Python tooling path-length failure.",
        category="execution_outcome",
        context="Windows Python tooling reports a path-length error",
        action="move the workspace and virtual environment to a shorter path",
        result="the tooling command completed",
        verification="the retry completed without a path-length error",
        successful_repair="use a shorter workspace path before application changes",
        execution_success=True,
        derive_skill=True,
    )

    result = _run_item(pipeline, candidate, item)

    assert [value.learning_type.value for value in result.distilled_items] == [
        "experience",
        "skill",
    ]
    lessons = memory.engineering_lessons.search(keyword="Repair short workspace paths")
    assert len(lessons) == 1
    assert lessons[0].context["derived_from_experience"] == "Repair short workspace paths"
    assert lessons[0].confidence <= 0.6
