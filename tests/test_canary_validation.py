from app.safe_self_improvement.canary import CanaryDecision, CanaryValidator
from app.safe_self_improvement.models import ExecutionResult, ImprovementCandidate
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionPipelineConfig, PromotionStage


def _candidate():
    return ImprovementCandidate(title="candidate", confidence=1.0, metadata={"rollback_plan": "checkpoint"})


def _execution(candidate):
    return ExecutionResult(
        candidate_id=candidate.id,
        success=True,
        verification_results={"verification": {"passed": True}},
    )


def test_canary_uses_real_controlled_executor_and_returns_evidence():
    candidate = _candidate()
    validator = CanaryValidator(lambda c, e: {
        "tested": "health probe",
        "environment": "isolated-subset",
        "executed": True,
        "outcome": "success",
        "metrics": {"success_rate": 1.0},
        "baseline": {"success_rate": 0.9},
        "decision": "PASS",
    })
    evidence = validator.validate(candidate, _execution(candidate))
    assert evidence.passed is True
    assert evidence.decision is CanaryDecision.PASS
    assert evidence.environment == "isolated-subset"
    assert evidence.metrics["success_rate"] == 1.0


def test_canary_failure_and_inconclusive_are_not_approval():
    candidate = _candidate()
    failed = CanaryValidator(lambda c, e: {"executed": True, "outcome": "failure", "decision": "FAIL", "failures": ["regression"]}).validate(candidate, _execution(candidate))
    inconclusive = CanaryValidator(lambda c, e: {"executed": True, "outcome": "success", "decision": "INCONCLUSIVE"}).validate(candidate, _execution(candidate))
    crashed = CanaryValidator(lambda c, e: (_ for _ in ()).throw(RuntimeError("validator down"))).validate(candidate, _execution(candidate))
    unavailable = CanaryValidator().validate(candidate, _execution(candidate))
    assert failed.passed is False
    assert inconclusive.passed is False
    assert crashed.passed is False
    assert unavailable.passed is False


def test_promotion_blocks_without_real_canary_evidence(tmp_path):
    candidate = _candidate()
    manager = PatchPromotionManager(
        config=PromotionPipelineConfig(
            stages=[PromotionStage.CANARY],
            canary_validator=None,
        ),
        staging_dir=str(tmp_path / "staging"),
        production_dir=str(tmp_path / "production"),
    )
    result = manager.promote(candidate, _execution(candidate))
    assert result.success is False
    assert result.details["stages"]["canary"]["passed"] is False
    assert result.details["stages"]["canary"]["details"]["evidence"]["decision"] == "INCONCLUSIVE"


def test_promotion_accepts_only_real_canary_pass(tmp_path):
    candidate = _candidate()
    manager = PatchPromotionManager(
        config=PromotionPipelineConfig(
            stages=[PromotionStage.CANARY],
            canary_validator=CanaryValidator(lambda c, e: {
                "tested": "controlled execution",
                "environment": "isolated-subset",
                "executed": True,
                "outcome": "success",
                "decision": "PASS",
                "metrics": {"errors": 0},
            }),
        ),
        staging_dir=str(tmp_path / "staging"),
        production_dir=str(tmp_path / "production"),
    )
    result = manager.promote(candidate, _execution(candidate))
    assert result.success is True
    assert result.details["stages"]["canary"]["details"]["simulated"] is False
