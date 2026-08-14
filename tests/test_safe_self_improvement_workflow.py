"""Workflow handoff contracts for safe self-improvement proposals."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.events import EventBus
from app.safe_self_improvement.models import ExecutionResult, ImprovementCandidate, RiskLevel
from app.safe_self_improvement.self_improvement import SafeSelfImprovementEngine


class AlwaysAllowed:
    def check_candidate_allowed(self, candidate):
        return True, []

    def get_stats(self):
        return {}


class ValidBoundaries:
    def validate_candidate(self, candidate):
        return True, []

    def get_session_stats(self):
        return {}


class FailingVerificationExecutor:
    def __init__(self):
        self.executions = 0

    def assess_risk(self, candidate):
        return SimpleNamespace(
            allow_execution=True,
            requires_approval=False,
            overall_risk=RiskLevel.LOW,
            details={"risk": "low"},
        )

    def execute(self, candidate, approval_status):
        self.executions += 1
        return ExecutionResult(
            candidate_id=candidate.id,
            success=False,
            verification_results={"verification": {"passed": False}},
            error="verification failed",
        )

    def get_stats(self):
        return {}


class AlwaysAllowedPolicy:
    def evaluate(self, candidate):
        return {"denied": False, "requires_approval": False}

    def get_stats(self):
        return {}


class ReadyPrioritizer:
    def prioritize(self, candidates):
        return [SimpleNamespace(meets_threshold=True, score=1.0, rank=1, breakdown={})]

    def get_criteria(self):
        return {}


class RecordingRollbackManager:
    def __init__(self):
        self.rollbacks = []

    def create_checkpoint(self, candidate, description):
        return SimpleNamespace(id=f"checkpoint-{candidate.id}")

    def rollback(self, candidate_id, reason, checkpoint_id):
        self.rollbacks.append((candidate_id, reason, checkpoint_id))
        return {"candidate_id": candidate_id, "reason": reason.value}

    def get_stats(self):
        return {}


class NoPromotion:
    def promote(self, candidate, execution_result):
        raise AssertionError("A failed execution must not be promoted")

    def get_stats(self):
        return {}


class RecordingWorkflowOrchestrator:
    def __init__(self):
        self.requests = []

    def execute_safe_self_improvement(self, candidate, execute, approval_status):
        self.requests.append({"candidate_id": candidate.id, "approval_status": approval_status})
        return execute()


def _engine(event_bus, workflow_orchestrator):
    return SafeSelfImprovementEngine(
        event_bus=event_bus,
        workflow_orchestrator=workflow_orchestrator,
        allowlist_manager=AlwaysAllowed(),
        boundary_manager=ValidBoundaries(),
        risk_executor=FailingVerificationExecutor(),
        policy_engine=AlwaysAllowedPolicy(),
        prioritizer=ReadyPrioritizer(),
        rollback_manager=RecordingRollbackManager(),
        promotion_manager=NoPromotion(),
    )


def test_applied_improvement_is_workflow_gated_and_emits_verification_and_rollback_events():
    event_bus = EventBus()
    workflow = RecordingWorkflowOrchestrator()
    engine = _engine(event_bus, workflow)
    candidate = ImprovementCandidate(title="Verify workflow handoff", source="test")

    result = engine.submit_improvement(candidate, auto_execute=True)

    assert result.accepted is True
    assert workflow.requests == [{"candidate_id": candidate.id, "approval_status": "not_required"}]
    assert engine.risk_executor.executions == 1
    assert engine.rollback_manager.rollbacks
    assert event_bus.history().get_by_name("self_improvement.workflow_requested")
    assert event_bus.history().get_by_name("self_improvement.applied")[-1].data["success"] is False
    assert event_bus.history().get_by_name("self_improvement.verified")[-1].data["passed"] is False
    assert event_bus.history().get_by_name("self_improvement.rolled_back")


def test_improvement_is_not_applied_when_no_workflow_orchestrator_is_bound():
    event_bus = EventBus()
    engine = _engine(event_bus, workflow_orchestrator=None)
    candidate = ImprovementCandidate(title="Require workflow boundary", source="test")

    result = engine.submit_improvement(candidate, auto_execute=True)

    assert result.accepted is True
    assert engine.risk_executor.executions == 0
    status = engine.get_candidate_status(candidate.id)
    assert status["status"] == "completed"
    assert status["result"]["success"] is False
    assert status["result"]["metadata"]["workflow_required"] is True
    assert event_bus.history().get_by_name("self_improvement.rejected")
