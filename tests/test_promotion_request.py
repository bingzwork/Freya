from dataclasses import FrozenInstanceError, replace

from app.safe_self_improvement.measurement import MetricDirection, measure_improvement
from app.safe_self_improvement.models import ExecutionResult, ImprovementCandidate, RiskLevel
from app.safe_self_improvement.canary import CanaryValidator
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionPipelineConfig, PromotionStage
from app.safe_self_improvement.promotion_contract import (
    PromotionRequest,
    RollbackEvidence,
)


def _candidate(candidate_id="candidate-a"):
    return ImprovementCandidate(
        id=candidate_id,
        title="Measured improvement",
        description="Improve a safe component",
        confidence=1.0,
        metadata={"measurement_required": True},
    )


def _evidence(candidate_id, before=10, after=5):
    return measure_improvement(
        {"latency": before},
        {"latency": after},
        definitions={"latency": {"direction": MetricDirection.LOWER_IS_BETTER, "unit": "ms"}},
        candidate_id=candidate_id,
        provenance="focused-test",
    )


def _request(candidate=None, evidence=None, execution=None, rollback=None):
    candidate = candidate or _candidate()
    execution = execution or ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
    )
    evidence = _evidence(candidate.id) if evidence is None else evidence
    rollback = rollback or RollbackEvidence(candidate_id=candidate.id, rollback_plan="restore checkpoint")
    return PromotionRequest.from_execution(
        candidate,
        execution,
        improvement_evidence=evidence,
        rollback_evidence=rollback,
    )


def _manager():
    return PatchPromotionManager(
        config=PromotionPipelineConfig(stages=[PromotionStage.VERIFICATION]),
    )


class _RecordingRollback:
    def __init__(self):
        self.calls = []

    def rollback(self, candidate_id, reason, checkpoint_id=None):
        self.calls.append((candidate_id, reason, checkpoint_id))
        return {"success": True, "candidate_id": candidate_id}


def test_valid_promotion_request_is_accepted():
    request = _request()
    assert request.validate().valid is True
    assert _manager().promote(request).success is True


def test_promotion_request_rejects_missing_candidate_identity():
    request = replace(_request(), candidate_identity="")
    validation = request.validate()
    assert validation.valid is False
    assert "candidate identity" in " ".join(validation.errors).lower()


def test_promotion_request_rejects_candidate_and_evidence_mismatch():
    candidate = _candidate("candidate-a")
    request = _request(candidate=candidate, evidence=_evidence("candidate-b"))
    validation = request.validate()
    assert validation.valid is False
    assert any("does not match candidate" in error for error in validation.errors)


def test_promotion_request_rejects_failed_verification_and_missing_rollback():
    candidate = _candidate()
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": False}},
    )
    request = replace(_request(candidate=candidate, execution=execution), rollback_evidence=None)
    validation = request.validate()
    assert validation.valid is False
    assert "Verification evidence did not pass" in validation.errors
    assert "Rollback evidence is missing or malformed" in validation.errors


def test_promotion_request_rejects_invalid_provenance():
    request = replace(_request(), provenance=None)
    validation = request.validate()
    assert validation.valid is False
    assert "provenance" in " ".join(validation.errors).lower()


def test_promotion_request_is_immutable():
    request = _request()
    try:
        request.candidate_identity = "other"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("PromotionRequest must be immutable")


def test_typed_improvement_evidence_is_authoritative_when_metadata_is_missing():
    candidate = _candidate()
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
        metadata={},
    )
    result = _manager().promote(_request(candidate=candidate, execution=execution))
    assert result.success is True


def test_typed_regression_wins_over_false_metadata_improvement():
    candidate = _candidate()
    regressed = _evidence(candidate.id, before=5, after=10)
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
        metadata={"improvement_evidence": {"valid": True, "comparisons": {"latency": {"status": "improved"}}}},
    )
    result = _manager().promote(_request(candidate=candidate, execution=execution, evidence=regressed))
    assert result.success is False
    assert any("regression" in error.lower() for error in result.details["validation_errors"])


def test_fabricated_metadata_cannot_supply_missing_typed_evidence():
    candidate = _candidate()
    execution = ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
        metadata={"improvement_evidence": {"valid": True, "comparisons": {"latency": {"status": "improved"}}}},
    )
    request = _request(candidate=candidate, execution=execution, evidence=None)
    # The helper's default is valid evidence, so explicitly remove it.
    request = replace(request, improvement_evidence=None)
    result = _manager().promote(request)
    assert result.success is False
    assert any("measurement evidence" in error.lower() for error in result.details["validation_errors"])


def test_rollback_identity_mismatch_is_rejected():
    request = _request(rollback=RollbackEvidence(candidate_id="candidate-b", rollback_plan="restore"))
    validation = request.validate()
    assert validation.valid is False
    assert any("rollback evidence" in error.lower() for error in validation.errors)


def test_gate_rejection_uses_canonical_rollback_manager():
    candidate = _candidate()
    candidate.estimated_risk = RiskLevel.HIGH
    rollback = _RecordingRollback()
    manager = PatchPromotionManager(
        rollback_manager=rollback,
        config=PromotionPipelineConfig(stages=[PromotionStage.VERIFICATION]),
    )
    result = manager.promote(_request(candidate=candidate))
    assert result.success is False
    assert rollback.calls
    assert rollback.calls[0][0] == candidate.id


def test_canary_failure_uses_canonical_rollback_manager():
    rollback = _RecordingRollback()
    validator = CanaryValidator(
        lambda candidate, execution: {
            "executed": True,
            "outcome": "failure",
            "decision": "FAIL",
            "failures": ["health regression"],
        }
    )
    manager = PatchPromotionManager(
        rollback_manager=rollback,
        config=PromotionPipelineConfig(stages=[PromotionStage.CANARY], canary_validator=validator),
    )
    result = manager.promote(_request())
    assert result.success is False
    assert rollback.calls
