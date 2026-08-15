from app.diagnostics.grouping import CausalRelation, DiagnosticEvent, DiagnosticGrouper


def event(event_id, *, component="worker", failure_type="Timeout", fingerprint="fp", timestamp="2026-08-15T00:00:00+00:00", **kwargs):
    return DiagnosticEvent(event_id, "runtime", failure_type, component, operation="execute", message=kwargs.pop("message", "timeout"), fingerprint=fingerprint, timestamp=timestamp, **kwargs)


def test_exact_duplicates_are_collapsed_with_occurrence_history():
    report = DiagnosticGrouper().group([
        event("a"),
        event("b", timestamp="2026-08-15T00:00:02+00:00"),
        event("c", message="different wording"),
    ])
    assert len(report.occurrences) == 1
    assert report.occurrences[0].occurrence_count == 3
    assert report.occurrences[0].to_dict()["event_ids"] == ["a", "c", "b"]


def test_similar_but_distinct_failures_are_not_deduplicated():
    report = DiagnosticGrouper().group([
        event("a", failure_type="Timeout", fingerprint="fp-a"),
        event("b", failure_type="ConnectionError", fingerprint="fp-b"),
    ])
    assert len(report.occurrences) == 2
    assert len(report.repair_proposals) == 2


def test_dependency_and_explicit_cause_group_symptoms_without_losing_them():
    root = event("root", component="database", failure_type="Unavailable")
    dependent = event("dependent", component="api", failure_type="UpstreamFailure", dependencies=["database"])
    explicit = event("explicit", component="worker", failure_type="Aborted", causal_parent="root")
    report = DiagnosticGrouper(dependencies={"api": ["database"]}).group([dependent, explicit, root])
    assert len(report.groups) == 1
    group = report.groups[0]
    assert group.root.representative.event_id == "root"
    assert {item.representative.event_id for item in group.symptoms} == {"dependent", "explicit"}
    assert group.relation in {CausalRelation.KNOWN_CAUSE, CausalRelation.LIKELY_CAUSE}
    assert sum(item.occurrence_count for item in group.symptoms) == 2
    assert len(report.repair_proposals) == 1


def test_temporal_workflow_relationship_is_related_not_asserted_causality():
    report = DiagnosticGrouper(time_window_seconds=10).group([
        event("a", component="a", workflow_id="wf"),
        event("b", component="b", workflow_id="wf", timestamp="2026-08-15T00:00:05+00:00"),
    ])
    assert report.groups[0].relation == CausalRelation.RELATED


def test_unrelated_simultaneous_failures_remain_separate():
    report = DiagnosticGrouper().group([
        event("a", component="a", workflow_id="wf-a"),
        event("b", component="b", workflow_id="wf-b"),
    ])
    assert len(report.groups) == 2
