from unittest.mock import Mock, patch

from app.learning.models import (
    EvaluationResult,
    LearningCandidate,
    LearningCandidateType,
    WorthRememberingDecision,
)
from app.learning.pipeline import LearningPipeline, _has_meaningful_telemetry


def test_meaningful_telemetry_helper_distinguishes_routine_and_failure_events():
    routine = LearningCandidate(
        candidate_type=LearningCandidateType.WATCHDOG_OBSERVATION,
        source_component="watchdog",
        raw_observation={"status": "healthy", "event": "health_check", "ok": True},
        context={"kind": "heartbeat"},
    )
    meaningful = LearningCandidate(
        candidate_type=LearningCandidateType.WATCHDOG_OBSERVATION,
        source_component="watchdog",
        raw_observation={"status": "failed", "error": "database timeout"},
        context={"transition": "degraded"},
    )

    assert callable(_has_meaningful_telemetry)
    assert not _has_meaningful_telemetry(routine)
    assert _has_meaningful_telemetry(meaningful)


def test_drain_pending_filters_repeated_routine_telemetry_without_durable_learning():
    memory = Mock()
    pipeline = LearningPipeline(memory)
    routine = LearningCandidate(
        candidate_type=LearningCandidateType.EVENT_BUS_EVENT,
        source_component="event_bus",
        raw_observation={"status": "healthy", "event": "health_check", "ok": True},
        context={"kind": "heartbeat"},
    )

    pipeline.submit(routine)
    assert pipeline._drain_pending() == 1
    first = pipeline.run(routine)
    second = pipeline.run(LearningCandidate(
        candidate_type=LearningCandidateType.EVENT_BUS_EVENT,
        source_component="event_bus",
        raw_observation={"status": "healthy", "event": "health_check", "ok": True},
        context={"kind": "heartbeat"},
    ))

    assert first.worth_remembering_result.decision == WorthRememberingDecision.NO
    assert second.worth_remembering_result.decision == WorthRememberingDecision.NO
    assert "routine" in first.worth_remembering_result.reasoning
    assert memory.method_calls == []


def test_meaningful_operational_telemetry_reaches_learning_evaluation():
    pipeline = LearningPipeline(Mock())
    meaningful = LearningCandidate(
        candidate_type=LearningCandidateType.WATCHDOG_OBSERVATION,
        source_component="watchdog",
        raw_observation={"status": "failed", "error": "database timeout"},
        context={"transition": "degraded"},
    )
    evaluation = EvaluationResult(
        candidate_id=meaningful.id,
        has_learning_potential=False,
        evaluation_notes="focused regression test",
    )

    with patch.object(pipeline, "_evaluate", return_value=evaluation) as evaluate:
        result = pipeline.run(meaningful)

    evaluate.assert_called_once()
    assert result.worth_remembering_result.decision == WorthRememberingDecision.NO
    assert "routine" not in result.worth_remembering_result.reasoning
