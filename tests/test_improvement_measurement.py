from app.safe_self_improvement.measurement import (
    ComparisonStatus,
    MetricDirection,
    ImprovementMeasurement,
    measure_improvement,
)


def definitions():
    return {
        "success_rate": {"direction": MetricDirection.HIGHER_IS_BETTER, "unit": "%"},
        "latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"},
    }


def test_real_improvement_is_direction_aware():
    evidence = measure_improvement(
        {"success_rate": 0.91, "latency": 870},
        {"success_rate": 0.96, "latency": 510},
        definitions=definitions(),
        provenance="focused-test",
    )
    assert evidence.valid is True
    assert evidence.comparisons["success_rate"].status is ComparisonStatus.IMPROVED
    assert evidence.comparisons["latency"].status is ComparisonStatus.IMPROVED
    assert evidence.comparisons["latency"].delta == -360
    assert evidence.provenance == "focused-test"


def test_regression_and_unchanged_are_not_improvements():
    measurement = ImprovementMeasurement()
    before = measurement.collect({"latency": 10}, definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}})
    after = measurement.collect({"latency": 12}, definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}})
    evidence = measurement.compare(before, after)
    assert evidence.valid is True
    assert evidence.comparisons["latency"].status is ComparisonStatus.REGRESSED

    unchanged = measure_improvement({"latency": 10}, {"latency": 10}, definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}})
    assert unchanged.comparisons["latency"].status is ComparisonStatus.UNCHANGED


def test_missing_invalid_and_incompatible_metrics_are_inconclusive():
    evidence = measure_improvement(
        {"latency": 10, "only_before": 1, "bad": float("nan")},
        {"latency": 11, "only_after": 2, "bad": "invalid"},
        definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}},
    )
    assert evidence.valid is False
    assert evidence.comparisons["only_before"].status is ComparisonStatus.INCONCLUSIVE
    assert evidence.comparisons["only_after"].status is ComparisonStatus.INCONCLUSIVE
    assert evidence.comparisons["bad"].status is ComparisonStatus.INCONCLUSIVE


def test_unknown_direction_does_not_claim_improvement():
    evidence = measure_improvement({"quality": 1}, {"quality": 2})
    assert evidence.valid is False
    assert evidence.comparisons["quality"].status is ComparisonStatus.INCONCLUSIVE


def test_required_measurement_evidence_is_fail_closed():
    from app.safe_self_improvement.models import ImprovementCandidate, ExecutionResult
    from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionPipelineConfig, PromotionStage

    candidate = ImprovementCandidate(title="measured", confidence=1.0, metadata={"measurement_required": True, "rollback_plan": "checkpoint"})
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
        metadata={},
    )
    manager = PatchPromotionManager(config=PromotionPipelineConfig(stages=[PromotionStage.VERIFICATION]))
    rejected = manager.promote(candidate, execution)
    assert rejected.success is False
    assert rejected.decision.value == "rejected"
    assert any("measurement evidence" in reason.lower() for reason in rejected.details["safety_gates"]["rejection_reasons"])


def test_required_measurement_evidence_can_support_promotion_gate():
    from app.safe_self_improvement.models import ImprovementCandidate, ExecutionResult
    from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionPipelineConfig, PromotionStage
    from app.safe_self_improvement.promotion_contract import PromotionRequest, RollbackEvidence

    candidate = ImprovementCandidate(title="measured", confidence=1.0, metadata={"measurement_required": True, "rollback_plan": "checkpoint"})
    evidence = measure_improvement(
        {"latency": 10},
        {"latency": 5},
        definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}},
        candidate_id=candidate.id,
        provenance="focused-test",
    )
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
        metadata={"improvement_evidence": {"valid": False, "comparisons": {"latency": {"status": "regressed"}}}},
    )
    request = PromotionRequest.from_execution(
        candidate,
        execution,
        improvement_evidence=evidence,
        rollback_evidence=RollbackEvidence(candidate_id=candidate.id, rollback_plan="checkpoint"),
    )
    manager = PatchPromotionManager(config=PromotionPipelineConfig(stages=[PromotionStage.VERIFICATION]))
    result = manager.promote(request)
    assert result.success is True
