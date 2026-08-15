from __future__ import annotations

from pathlib import Path

from app.core.safety_gates import (
    PromotionContext,
    PromotionDecision,
    SafetyEvaluator,
    SafetyLevel,
    SafetyPromotionGates,
    ValidationGate,
    ValidationGateStatus,
)
from app.safe_self_improvement.models import ExecutionResult, ImprovementCandidate, RiskLevel
from app.safe_self_improvement.promotion import (
    PatchPromotionManager,
    PromotionPipelineConfig,
    PromotionStage,
)


def _context(**overrides) -> PromotionContext:
    values = {
        "operation_id": "candidate-1",
        "operation_type": "self_improvement",
        "description": "Improve a safe component",
        "source": "autonomous",
        "confidence": 0.95,
        "rollback_possible": True,
        "rollback_plan": "restore checkpoint candidate-1",
    }
    values.update(overrides)
    return PromotionContext(**values)


def _candidate(**overrides) -> ImprovementCandidate:
    values = {
        "id": "candidate-1",
        "title": "Safe improvement",
        "description": "Improve a safe component",
        "source": "autonomous",
        "confidence": 0.95,
        "estimated_risk": RiskLevel.NONE,
        "metadata": {"rollback_plan": "restore checkpoint candidate-1"},
    }
    values.update(overrides)
    return ImprovementCandidate(**values)


def _successful_execution(candidate: ImprovementCandidate, **overrides) -> ExecutionResult:
    values = {
        "candidate_id": candidate.id,
        "success": True,
        "verification_results": {"verification": {"passed": True}},
    }
    values.update(overrides)
    return ExecutionResult(**values)


def test_safe_candidate_is_approved_when_all_required_gates_pass():
    result = SafetyPromotionGates(evaluators=[]).evaluate(_context())

    assert result.decision is PromotionDecision.APPROVED
    assert result.rejection_reasons == []
    assert all(status is ValidationGateStatus.PASSED for status in result.gate_results.values() if status != ValidationGateStatus.SKIPPED)


def test_unsafe_candidate_is_rejected():
    result = SafetyPromotionGates().evaluate(
        _context(
            operation_type="delete_records",
            rollback_possible=False,
            rollback_plan="",
        )
    )

    assert result.decision is PromotionDecision.REJECTED
    assert any("high/critical risks" in reason for reason in result.rejection_reasons)


def test_missing_validation_evidence_rejects_promotion(tmp_path: Path):
    candidate = _candidate()
    manager = PatchPromotionManager(
        config=PromotionPipelineConfig(stages=[PromotionStage.VERIFICATION]),
        staging_dir=str(tmp_path / "staging"),
        production_dir=str(tmp_path / "production"),
    )

    result = manager.promote(candidate, _successful_execution(candidate, verification_results={}))

    assert result.success is False
    assert result.decision is PromotionDecision.REJECTED
    assert "Verification evidence is missing or malformed" in result.details["safety_gates"]["rejection_reasons"]
    assert not list((tmp_path / "production").glob("*"))


def test_failed_required_gate_rejects_promotion():
    gates = SafetyPromotionGates(evaluators=[])
    gates.add_gate(
        ValidationGate(
            name="required_failure",
            description="Always fails",
            check_func=lambda context: ValidationGateStatus.FAILED,
            required=True,
        )
    )

    result = gates.evaluate(_context())

    assert result.decision is PromotionDecision.REJECTED
    assert "Required gates failed" in result.rejection_reasons[0]


class _RaisingEvaluator(SafetyEvaluator):
    @property
    def name(self) -> str:
        return "raising"

    def evaluate(self, context):
        raise RuntimeError("validator unavailable")


def test_evaluation_exception_fails_closed():
    result = SafetyPromotionGates(evaluators=[_RaisingEvaluator()]).evaluate(_context())

    assert result.decision is PromotionDecision.REJECTED
    assert "Safety evaluator 'raising' failed" in result.rejection_reasons


def test_rejected_safety_result_cannot_reach_production(tmp_path: Path):
    candidate = _candidate(estimated_risk=RiskLevel.HIGH)
    manager = PatchPromotionManager(
        config=PromotionPipelineConfig(stages=[PromotionStage.PRODUCTION]),
        staging_dir=str(tmp_path / "staging"),
        production_dir=str(tmp_path / "production"),
    )

    result = manager.promote(candidate, _successful_execution(candidate))

    assert result.success is False
    assert result.decision is PromotionDecision.REJECTED
    assert not list((tmp_path / "production").glob("*"))
    assert manager.get_stats()["successful_promotions"] == 0


def test_final_production_gate_never_defaults_to_approval(tmp_path: Path):
    candidate = _candidate()
    manager = PatchPromotionManager(
        config=PromotionPipelineConfig(stages=[PromotionStage.PRODUCTION]),
        staging_dir=str(tmp_path / "staging"),
        production_dir=str(tmp_path / "production"),
    )

    manager.safety_gates = None
    result = manager.promote(candidate, _successful_execution(candidate))

    assert result.success is False
    assert result.decision is PromotionDecision.REJECTED
    assert not list((tmp_path / "production").glob("*"))
