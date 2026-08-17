"""Focused integration tests for Task 4's shared EventBus improvement flow."""

from datetime import datetime, timezone

import pytest

import app.diagnostics.diagnostic_engine as diagnostic_engine_module
from app.core.events import EventBus, EventPriority
from app.core.initializer import SystemInitializer
from app.core.protocols import SystemConfig
from app.diagnostics.diagnostic_engine import DiagnosticEngine
from app.diagnostics.grouping import CausalRelation, DiagnosticEvent, DiagnosticGrouper
from app.diagnostics.issue import Issue, IssueCollection, IssueSeverity, IssueType
from app.learning.models import LearningCandidate, LearningCandidateType
from app.learning.pipeline import LearningPipeline
from app.safe_self_improvement.models import ImprovementCategory
from app.safe_self_improvement.self_improvement import create_self_improvement_engine


class RecordingMemoryCoordinator:
    """Minimal memory collaborator used to run the real learning pipeline."""

    def __init__(self):
        self.experiences = []
        self.lessons = []

    def add_experience(self, entry):
        self.experiences.append(entry)

    def add_lesson(self, entry):
        self.lessons.append(entry)


@pytest.fixture
def shared_improvement_flow():
    """Create real publishers and consumer around one explicitly supplied EventBus."""
    event_bus = EventBus()
    self_improvement = create_self_improvement_engine(event_bus=event_bus)
    submissions = []

    def record_submission(candidate, auto_execute=False):
        submissions.append((candidate, auto_execute))

    self_improvement.submit_improvement = record_submission
    return event_bus, self_improvement, submissions


def test_self_improvement_factory_uses_the_injected_event_bus():
    event_bus = EventBus()

    self_improvement = create_self_improvement_engine(event_bus=event_bus)

    assert self_improvement._event_bus is event_bus
    assert event_bus.get_subscriptions("learning.improvement_candidate")["learning.improvement_candidate"] == 1
    assert event_bus.get_subscriptions("diagnostics.completed")["diagnostics.completed"] == 0
    assert event_bus.get_subscriptions("diagnostics.grouped")["diagnostics.grouped"] == 1


def test_self_improvement_factory_requires_an_event_bus():
    with pytest.raises(ValueError, match="requires an injected EventBus"):
        create_self_improvement_engine()


def test_learning_pipeline_publishes_to_shared_bus_and_creates_candidate(shared_improvement_flow):
    event_bus, self_improvement, submissions = shared_improvement_flow
    learning_pipeline = LearningPipeline(RecordingMemoryCoordinator(), event_bus=event_bus)
    learning_candidate = LearningCandidate(
        id="learning-event-1",
        candidate_type=LearningCandidateType.EXECUTION_OUTCOME,
        source_component="ExecutionVerifier",
        raw_observation={"outcome": "verification failed"},
        context={"task": "verify patch"},
        tags=["verification"],
    )

    result = learning_pipeline.run(learning_candidate)

    assert learning_pipeline._event_bus is self_improvement._event_bus is event_bus
    assert result.items_stored_via_memory_coordinator
    assert len(submissions) == 1
    improvement_candidate, auto_execute = submissions[0]
    assert auto_execute is True
    assert improvement_candidate.source == "learning_pipeline"
    assert improvement_candidate.category is ImprovementCategory.DOCUMENTATION
    assert improvement_candidate.metadata["learning_candidate_id"] == learning_candidate.id
    assert improvement_candidate.metadata["stored_item_ids"] == result.items_stored_via_memory_coordinator
    assert event_bus.history().get_by_name("learning.improvement_candidate")


def test_raw_diagnostics_remain_observable_without_parallel_candidate(monkeypatch, tmp_path, shared_improvement_flow):
    event_bus, self_improvement, submissions = shared_improvement_flow

    class ErrorDiagnosticAnalyzer:
        def __init__(self, workspace):
            self.workspace = workspace

        def analyze(self, paths):
            issues = IssueCollection()
            issues.add(
                Issue(
                    id="diagnostic-error-1",
                    title="Unsafe diagnostic behavior",
                    description="The diagnostic identified a real error.",
                    severity=IssueSeverity.ERROR,
                    issue_type=IssueType.BUG,
                    location="module.py:10",
                    file_path="module.py",
                    line_number=10,
                )
            )
            return issues

    monkeypatch.setattr(diagnostic_engine_module, "CodeAnalyzer", ErrorDiagnosticAnalyzer)
    diagnostic_engine = DiagnosticEngine(workspace=str(tmp_path), event_bus=event_bus)

    diagnostic_engine.run()

    assert diagnostic_engine._event_bus is self_improvement._event_bus is event_bus
    assert submissions == []
    diagnostic_events = event_bus.history().get_by_name("diagnostics.completed")
    assert len(diagnostic_events) == 1
    assert diagnostic_events[0].priority is EventPriority.NORMAL


def test_grouped_diagnostics_create_one_evidence_preserving_candidate(shared_improvement_flow):
    event_bus, self_improvement, submissions = shared_improvement_flow
    grouper = DiagnosticGrouper(dependencies={"api": ["database"]})
    report = grouper.group([
        DiagnosticEvent(
            event_id="root",
            source="runtime",
            failure_type="bug",
            component="database",
            operation="query",
            message="database unavailable",
            fingerprint="db-unavailable",
            metadata={"severity": "error"},
        ),
        DiagnosticEvent(
            event_id="symptom-1",
            source="runtime",
            failure_type="bug",
            component="api",
            operation="request",
            message="upstream request failed",
            fingerprint="api-upstream",
            dependencies=["database"],
            metadata={"severity": "error"},
        ),
    ])

    event_bus.emit("diagnostics.grouped", {"report": report.to_dict()}, source="DiagnosticGrouper")

    assert len(report.groups) == 1
    assert report.groups[0].relation == CausalRelation.LIKELY_CAUSE
    assert len(submissions) == 1
    improvement_candidate, auto_execute = submissions[0]
    assert auto_execute is False
    assert improvement_candidate.source == "diagnostics"
    assert improvement_candidate.category is ImprovementCategory.CORRECTNESS
    assert improvement_candidate.metadata["diagnostic_group_id"] == report.groups[0].group_id
    assert improvement_candidate.metadata["member_diagnostic_ids"] == ["root", "symptom-1"]


def test_diagnostic_event_publication_failure_is_propagated(tmp_path):
    class FailingEventBus:
        def publish(self, event):
            raise RuntimeError("event publication failed")

    diagnostic_engine = DiagnosticEngine(workspace=str(tmp_path), event_bus=FailingEventBus())
    diagnostic_engine._start_time = datetime.now(timezone.utc)
    diagnostic_engine._end_time = datetime.now(timezone.utc)

    with pytest.raises(RuntimeError, match="event publication failed"):
        diagnostic_engine._emit_diagnostic_event()


def test_production_initializer_wires_one_event_bus_for_the_affected_flow(tmp_path):
    config = SystemConfig(
        enable_autonomy=False,
        enable_orchestrator=False,
        enable_diagnostics=True,
        enable_self_improvement=True,
        enable_file_watcher=False,
        enable_config_hot_reload=False,
        enable_observability=False,
    )
    initializer = SystemInitializer(tmp_path, config)
    system = initializer.initialize()

    try:
        event_bus = system.infra.event_bus
        assert initializer.event_bus is event_bus
        assert system.learning_pipeline._event_bus is event_bus
        assert system.diagnostics._event_bus is event_bus
        assert system.self_improvement._event_bus is event_bus
    finally:
        initializer.shutdown(system)
