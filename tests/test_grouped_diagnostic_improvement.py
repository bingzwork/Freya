"""Focused tests for grouped diagnostic evidence entering self-improvement."""

from app.core.events import EventBus
from app.core.initializer import SystemInitializer
from app.core.protocols import SystemConfig
from app.diagnostics.grouping import CausalRelation, DiagnosticEvent, DiagnosticGrouper
from app.safe_self_improvement.self_improvement import create_self_improvement_engine


def _event(event_id, *, component="worker", fingerprint=None, dependencies=None, causal_parent=None, severity="error", timestamp="2026-08-15T00:00:00+00:00"):
    return DiagnosticEvent(
        event_id=event_id,
        source="runtime",
        failure_type="bug",
        component=component,
        operation="execute",
        message=f"failure {event_id}",
        fingerprint=fingerprint or event_id,
        timestamp=timestamp,
        dependencies=dependencies or [],
        causal_parent=causal_parent,
        metadata={"severity": severity},
    )


def _flow():
    event_bus = EventBus()
    engine = create_self_improvement_engine(event_bus=event_bus)
    submissions = []
    engine.submit_improvement = lambda candidate, auto_execute=False: submissions.append((candidate, auto_execute))
    return event_bus, submissions


def _publish_report(event_bus, report):
    event_bus.emit("diagnostics.grouped", {"report": report.to_dict()}, source="DiagnosticGrouper")


def test_cascade_becomes_one_candidate_with_all_symptoms_preserved():
    event_bus, submissions = _flow()
    events = [_event("root", component="database", fingerprint="db")]
    events.extend(
        _event(
            f"symptom-{index}",
            component="api",
            fingerprint=f"api-{index}",
            dependencies=["database"],
        )
        for index in range(12)
    )
    report = DiagnosticGrouper(dependencies={"api": ["database"]}).group(events)

    _publish_report(event_bus, report)

    assert len(report.groups) == 1
    assert len(submissions) == 1
    candidate, auto_execute = submissions[0]
    assert auto_execute is False
    assert candidate.metadata["diagnostic_group_id"] == report.groups[0].group_id
    assert len(candidate.metadata["member_diagnostic_ids"]) == 13
    assert candidate.metadata["causal_relation"] == CausalRelation.LIKELY_CAUSE
    assert len(candidate.metadata["diagnostic_group"]["symptoms"]) == 12


def test_exact_duplicates_become_one_candidate_with_occurrence_count():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper().group(
        [_event(f"duplicate-{index}", fingerprint="same-failure") for index in range(20)]
    )

    _publish_report(event_bus, report)

    assert len(report.groups) == 1
    assert report.groups[0].relation == CausalRelation.UNRESOLVED
    assert report.groups[0].root.occurrence_count == 20
    assert len(submissions) == 1
    assert submissions[0][0].metadata["occurrence_count"] == 20


def test_unrelated_diagnostics_remain_separate_and_do_not_overgroup():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper().group([
        _event("database-timeout", component="database", fingerprint="db-timeout"),
        _event("render-failure", component="renderer", fingerprint="render-failure"),
    ])

    _publish_report(event_bus, report)

    assert len(report.groups) == 2
    assert submissions == []


def test_likely_cause_keeps_uncertainty_in_candidate_evidence():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper(dependencies={"api": ["database"]}).group([
        _event("database-error", component="database", fingerprint="db"),
        _event("api-error", component="api", fingerprint="api", dependencies=["database"]),
    ])

    _publish_report(event_bus, report)

    assert len(submissions) == 1
    metadata = submissions[0][0].metadata
    assert metadata["causal_relation"] == CausalRelation.LIKELY_CAUSE
    assert metadata["causal_relation"] != CausalRelation.KNOWN_CAUSE


def test_unresolved_single_finding_does_not_fabricate_causality():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper().group([_event("unresolved")])

    _publish_report(event_bus, report)

    assert report.groups[0].relation == CausalRelation.UNRESOLVED
    assert submissions == []


def test_repeated_equivalent_group_events_are_deduplicated():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper(dependencies={"api": ["database"]}).group([
        _event("database-error", component="database", fingerprint="db"),
        _event("api-error", component="api", fingerprint="api", dependencies=["database"]),
    ])

    _publish_report(event_bus, report)
    _publish_report(event_bus, report)

    assert len(submissions) == 1


def test_grouping_failure_keeps_raw_event_and_emits_no_repair_candidate(tmp_path):
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
    submissions = []
    system.self_improvement.submit_improvement = lambda candidate, auto_execute=False: submissions.append(candidate)
    system.diagnostic_grouper.group = lambda events: (_ for _ in ()).throw(RuntimeError("grouping unavailable"))

    try:
        system.infra.event_bus.emit(
            "diagnostics.completed",
            {"issues": [{"id": "raw-1", "severity": "error", "description": "raw failure"}]},
            source="DiagnosticEngine",
        )
        assert system.infra.event_bus.history().get_by_name("diagnostics.completed")
        assert system.infra.event_bus.history().get_by_name("diagnostics.grouping_failed")
        assert submissions == []
    finally:
        initializer.shutdown(system)


def test_raw_completed_event_has_no_direct_self_improvement_subscription():
    event_bus, submissions = _flow()

    event_bus.emit(
        "diagnostics.completed",
        {"issues": [{"id": "raw-error", "severity": "error"}]},
        source="DiagnosticEngine",
    )

    assert submissions == []
    assert event_bus.get_subscriptions("diagnostics.completed")["diagnostics.completed"] == 0
    assert event_bus.get_subscriptions("diagnostics.grouped")["diagnostics.grouped"] == 1


def test_known_cause_group_is_candidate_eligible():
    event_bus, submissions = _flow()
    report = DiagnosticGrouper().group([
        _event("root", component="database", fingerprint="db"),
        _event("child", component="worker", fingerprint="child", causal_parent="root"),
    ])

    _publish_report(event_bus, report)

    assert len(submissions) == 1
    assert submissions[0][0].metadata["causal_relation"] == CausalRelation.KNOWN_CAUSE


def test_grouped_candidate_keeps_raw_event_history_available():
    event_bus, _ = _flow()
    event_bus.emit(
        "diagnostics.completed",
        {"issues": [{"id": "raw-error", "severity": "error"}]},
        source="DiagnosticEngine",
    )

    assert len(event_bus.history().get_by_name("diagnostics.completed")) == 1
