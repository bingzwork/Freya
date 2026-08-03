"""
Safe Self-Improvement Engine.

Main orchestrator for safe autonomous self-improvement operations.
Integrates all components: allowlist, boundaries, risk execution, approval gates,
prioritization, rollback, promotion, and policies.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from app.safe_self_improvement.models import (
    ImprovementCandidate,
    FileModification,
    ExecutionResult,
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    SafeSelfImprovementConfig,
)
from app.safe_self_improvement.allowlist import AllowlistManager, create_default_allowlist_manager
from app.safe_self_improvement.boundaries import BoundaryManager, create_default_boundary_manager
from app.safe_self_improvement.risk_execution import RiskBasedExecutor, ExecutionRiskAssessment
from app.safe_self_improvement.approval_gates import ApprovalGateManager, ApprovalDecision
from app.safe_self_improvement.prioritization import ImprovementPrioritizer, PrioritizationCriteria, create_balanced_prioritizer
from app.safe_self_improvement.rollback import RollbackManager, RollbackReason, create_rollback_manager
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionStage, create_patch_promotion_manager
from app.safe_self_improvement.policies import PolicyEngine, PolicyAction, create_policy_engine
from app.core.logger import logger


class EngineState(Enum):
    """State of the self-improvement engine."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ImprovementSubmissionResult:
    """Result of submitting an improvement for processing."""

    candidate_id: str
    accepted: bool
    approval_request: Optional[ApprovalRequest] = None
    risk_assessment: Optional[ExecutionRiskAssessment] = None
    policy_evaluation: Optional[Dict[str, Any]] = None
    prioritization: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    queued: bool = False


class SafeSelfImprovementEngine:
    """
    Main engine for safe self-improvement operations.

    Orchestrates the complete pipeline:
    1. Submit improvement candidate
    2. Validate against allowlist/denylist
    3. Check modification boundaries
    4. Assess risk
    5. Evaluate policies
    6. Prioritize
    7. Request approval if needed
    8. Execute with risk-based safeguards
    9. Verify and promote
    10. Rollback on failure
    """

    def __init__(
        self,
        config: Optional[SafeSelfImprovementConfig] = None,
        allowlist_manager: Optional[AllowlistManager] = None,
        boundary_manager: Optional[BoundaryManager] = None,
        risk_executor: Optional[RiskBasedExecutor] = None,
        approval_gates: Optional[ApprovalGateManager] = None,
        prioritizer: Optional[ImprovementPrioritizer] = None,
        rollback_manager: Optional[RollbackManager] = None,
        promotion_manager: Optional[PatchPromotionManager] = None,
        policy_engine: Optional[PolicyEngine] = None,
    ):
        self.config = config or SafeSelfImprovementConfig()
        self._lock = threading.RLock()
        self._state = EngineState.IDLE

        # Initialize components
        self.allowlist = allowlist_manager or create_default_allowlist_manager()
        self.boundaries = boundary_manager or create_default_boundary_manager()
        self.risk_executor = risk_executor or RiskBasedExecutor(
            auto_approve_max_risk=self.config.auto_approve_max_risk,
            require_human_approval_risk=self.config.require_human_approval_risk,
            max_concurrent_improvements=self.config.max_concurrent_improvements,
        )
        self.approval_gates = approval_gates or ApprovalGateManager(
            default_timeout_seconds=self.config.approval_timeout_seconds,
        )
        self.prioritizer = prioritizer or create_balanced_prioritizer()
        self.rollback_manager = rollback_manager or create_rollback_manager(
            retention_hours=self.config.checkpoint_retention_hours,
        )
        self.promotion_manager = promotion_manager or create_patch_promotion_manager()
        self.policy_engine = policy_engine or create_policy_engine()

        # State tracking
        self._pending_candidates: Dict[str, ImprovementCandidate] = {}
        self._processing_candidates: Dict[str, Dict[str, Any]] = {}
        self._completed_candidates: Dict[str, ExecutionResult] = {}
        self._submission_queue: List[str] = []
        self._background_thread: Optional[threading.Thread] = None
        self._stop_background = threading.Event()
        self._callbacks: Dict[str, List[Callable]] = {
            "on_submit": [],
            "on_approval_requested": [],
            "on_approved": [],
            "on_rejected": [],
            "on_executing": [],
            "on_executed": [],
            "on_promoted": [],
            "on_rolled_back": [],
            "on_error": [],
        }
        self._stats = {
            "submitted": 0,
            "accepted": 0,
            "rejected": 0,
            "executed": 0,
            "succeeded": 0,
            "failed": 0,
            "rolled_back": 0,
            "promoted": 0,
        }

    def submit_improvement(
        self,
        candidate: ImprovementCandidate,
        auto_execute: bool = False,
    ) -> ImprovementSubmissionResult:
        """
        Submit an improvement candidate for processing.

        Runs all validation checks and either queues for execution,
        requests approval, or rejects.
        """
        with self._lock:
            self._stats["submitted"] += 1
            self._trigger_callbacks("on_submit", candidate)

        # 1. Validate against allowlist
        allowlist_ok, allowlist_reasons = self.allowlist.check_candidate_allowed(candidate)
        if not allowlist_ok:
            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=False,
                error=f"Allowlist check failed: {'; '.join(allowlist_reasons)}",
            )

        # 2. Validate against boundaries
        boundary_ok, boundary_violations = self.boundaries.validate_candidate(candidate)
        if not boundary_ok:
            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=False,
                error=f"Boundary violations: {'; '.join(boundary_violations)}",
            )

        # 3. Assess risk
        risk_assessment = self.risk_executor.assess_risk(candidate)
        if not risk_assessment.allow_execution:
            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=False,
                error=f"Risk too high: {risk_assessment.overall_risk.value}",
                risk_assessment=risk_assessment,
            )

        # 4. Evaluate policies
        policy_evaluation = self.policy_engine.evaluate(candidate)

        # Handle policy actions
        if policy_evaluation["denied"]:
            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=False,
                error="Denied by policy",
                policy_evaluation=policy_evaluation,
            )

        # 5. Prioritize
        prioritization_results = self.prioritizer.prioritize([candidate])
        prioritization = prioritization_results[0] if prioritization_results else None

        if prioritization and not prioritization.meets_threshold:
            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=False,
                error=f"Below prioritization threshold: {prioritization.score:.2f}",
                prioritization={
                    "score": prioritization.score,
                    "rank": prioritization.rank,
                    "breakdown": prioritization.breakdown,
                },
            )

        # 6. Check if approval needed
        approval_request = None
        if policy_evaluation["requires_approval"] or risk_assessment.requires_approval:
            # Check auto-approval eligibility
            approval_request = self.approval_gates.request_approval(
                candidate,
                requested_by="system",
                risk_assessment=risk_assessment.details,
            )

            if approval_request.status == ApprovalStatus.PENDING:
                # Queued for approval
                with self._lock:
                    self._pending_candidates[candidate.id] = candidate
                    self._submission_queue.append(candidate.id)
                self._trigger_callbacks("on_approval_requested", approval_request)
                self._stats["accepted"] += 1

                return ImprovementSubmissionResult(
                    candidate_id=candidate.id,
                    accepted=True,
                    approval_request=approval_request,
                    risk_assessment=risk_assessment,
                    policy_evaluation=policy_evaluation,
                    prioritization={
                        "score": prioritization.score if prioritization else 0,
                        "rank": prioritization.rank if prioritization else 0,
                    },
                    queued=True,
                )
            elif approval_request.status == ApprovalStatus.AUTO_APPROVED:
                # Auto-approved, proceed to execution
                pass
            elif approval_request.status in (ApprovalStatus.REJECTED, ApprovalStatus.TIMED_OUT):
                return ImprovementSubmissionResult(
                    candidate_id=candidate.id,
                    accepted=False,
                    approval_request=approval_request,
                    error=f"Approval {approval_request.status.value}",
                )

        # 7. Create checkpoint if required
        checkpoint = None
        if self.config.require_rollback_checkpoint:
            checkpoint = self.rollback_manager.create_checkpoint(
                candidate,
                f"Pre-execution checkpoint for {candidate.title}",
            )

        # 8. Execute if auto_execute or already approved
        if auto_execute or approval_request is None or approval_request.status in (ApprovalStatus.APPROVED, ApprovalStatus.AUTO_APPROVED, ApprovalStatus.OVERRIDDEN):
            with self._lock:
                self._processing_candidates[candidate.id] = {
                    "candidate": candidate,
                    "checkpoint_id": checkpoint.id if checkpoint else None,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }

            self._trigger_callbacks("on_executing", candidate)

            execution_result = self.risk_executor.execute(
                candidate,
                approval_status=approval_request.status.value if approval_request else "not_required",
            )

            # Handle execution result
            if not execution_result.success:
                # Rollback if needed
                if checkpoint and (
                    self.config.auto_rollback_on_verification_failure and
                    execution_result.verification_results.get("verification", {}).get("passed") is False
                ):
                    rollback_result = self.rollback_manager.rollback(
                        candidate.id,
                        RollbackReason.VERIFICATION_FAILED,
                        checkpoint.id,
                    )
                    execution_result.rollback_performed = True
                    self._trigger_callbacks("on_rolled_back", rollback_result)
                    self._stats["rolled_back"] += 1
                elif checkpoint and self.config.auto_rollback_on_test_failure:
                    # Check test failures
                    test_result = execution_result.verification_results.get("verification", {}).get("checks", {}).get("tests", {})
                    if test_result and not test_result.get("passed", True):
                        rollback_result = self.rollback_manager.rollback(
                            candidate.id,
                            RollbackReason.TESTS_FAILED,
                            checkpoint.id,
                        )
                        execution_result.rollback_performed = True
                        self._trigger_callbacks("on_rolled_back", rollback_result)
                        self._stats["rolled_back"] += 1

            with self._lock:
                if candidate.id in self._processing_candidates:
                    del self._processing_candidates[candidate.id]
                self._completed_candidates[candidate.id] = execution_result

            self._trigger_callbacks("on_executed", execution_result)

            if execution_result.success:
                self._stats["succeeded"] += 1

                # 9. Promote if successful
                if self.config.promotion_require_tests or self.config.promotion_require_lint:
                    promo_result = self.promotion_manager.promote(candidate, execution_result)
                    if promo_result.success:
                        self._stats["promoted"] += 1
                        self._trigger_callbacks("on_promoted", promo_result)

                self._stats["executed"] += 1
            else:
                self._stats["failed"] += 1
                self._trigger_callbacks("on_error", execution_result)

            return ImprovementSubmissionResult(
                candidate_id=candidate.id,
                accepted=True,
                approval_request=approval_request,
                risk_assessment=risk_assessment,
                policy_evaluation=policy_evaluation,
                prioritization={
                    "score": prioritization.score if prioritization else 0,
                    "rank": prioritization.rank if prioritization else 0,
                },
                error=None,
            )

        # Queued for approval
        with self._lock:
            self._pending_candidates[candidate.id] = candidate
            self._submission_queue.append(candidate.id)

        self._stats["accepted"] += 1
        return ImprovementSubmissionResult(
            candidate_id=candidate.id,
            accepted=True,
            approval_request=approval_request,
            risk_assessment=risk_assessment,
            policy_evaluation=policy_evaluation,
            prioritization={
                "score": prioritization.score if prioritization else 0,
                "rank": prioritization.rank if prioritization else 0,
            },
            queued=True,
        )

    def process_pending_approvals(self) -> int:
        """Process pending approval requests (check timeouts, etc.)."""
        with self._lock:
            processed = 0
            for candidate_id in list(self._pending_candidates.keys()):
                candidate = self._pending_candidates[candidate_id]

                # Check if there's an approval request
                # In a real system, we'd look up by candidate_id
                # For now, skip if still pending

            # Process timeouts
            timed_out = self.approval_gates.process_timeouts()
            processed += timed_out

            return processed

    def approve_candidate(self, candidate_id: str, approved_by: str, reason: str = "") -> tuple[bool, str]:
        """Approve a pending candidate and execute it."""
        with self._lock:
            candidate = self._pending_candidates.get(candidate_id)
            if not candidate:
                return False, "Candidate not found in pending queue"

        # Find approval request (in real system, would query by candidate_id)
        # For now, assume we can find it
        pending_requests = self.approval_gates.get_pending_requests()
        approval_request = None
        for req in pending_requests:
            if req.candidate_id == candidate_id:
                approval_request = req
                break

        if not approval_request:
            return False, "No pending approval request found"

        # Approve
        success, msg = self.approval_gates.approve(approval_request.id, approved_by, reason)
        if not success:
            return False, msg

        # Execute
        submission_result = self.submit_improvement(candidate, auto_execute=True)
        return True, "Approved and executed" if submission_result.accepted else f"Approved but execution failed: {submission_result.error}"

    def reject_candidate(self, candidate_id: str, rejected_by: str, reason: str = "") -> tuple[bool, str]:
        """Reject a pending candidate."""
        with self._lock:
            if candidate_id in self._pending_candidates:
                del self._pending_candidates[candidate_id]
            if candidate_id in self._submission_queue:
                self._submission_queue.remove(candidate_id)

        # Find and reject approval request
        pending_requests = self.approval_gates.get_pending_requests()
        for req in pending_requests:
            if req.candidate_id == candidate_id:
                success, msg = self.approval_gates.reject(req.id, rejected_by, reason)
                return success, msg

        return False, "No pending approval request found"

    def get_candidate_status(self, candidate_id: str) -> Dict[str, Any]:
        """Get status of a candidate."""
        with self._lock:
            # Check pending
            if candidate_id in self._pending_candidates:
                return {"status": "pending_approval", "candidate": self._pending_candidates[candidate_id].to_dict()}

            # Check processing
            if candidate_id in self._processing_candidates:
                return {"status": "processing", "details": self._processing_candidates[candidate_id]}

            # Check completed
            if candidate_id in self._completed_candidates:
                exec_result = self._completed_candidates[candidate_id]
                return {"status": "completed", "result": exec_result.to_dict()}

            # Check approval
            pending_requests = self.approval_gates.get_pending_requests()
            for req in pending_requests:
                if req.candidate_id == candidate_id:
                    return {"status": "awaiting_approval", "approval_request": req.to_dict()}

        return {"status": "unknown"}

    def get_pending_candidates(self) -> List[ImprovementCandidate]:
        """Get all pending candidates."""
        with self._lock:
            return list(self._pending_candidates.values())

    def get_processing_candidates(self) -> List[Dict[str, Any]]:
        """Get all currently processing candidates."""
        with self._lock:
            return list(self._processing_candidates.values())

    def get_recent_executions(self, limit: int = 50) -> List[ExecutionResult]:
        """Get recent execution results."""
        with self._lock:
            return list(reversed(list(self._completed_candidates.values())))[:limit]

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for engine events."""
        with self._lock:
            if event in self._callbacks:
                self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, data: Any) -> None:
        """Trigger callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"[SafeSelfImprovementEngine] Callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        with self._lock:
            return {
                **self._stats,
                "state": self._state.value,
                "pending_count": len(self._pending_candidates),
                "processing_count": len(self._processing_candidates),
                "completed_count": len(self._completed_candidates),
                "queue_length": len(self._submission_queue),
            }

    def get_component_stats(self) -> Dict[str, Any]:
        """Get statistics from all components."""
        return {
            "allowlist": self.allowlist.get_stats(),
            "boundaries": self.boundaries.get_session_stats(),
            "risk_executor": self.risk_executor.get_stats(),
            "approval_gates": self.approval_gates.get_stats(),
            "prioritizer": self.prioritizer.get_criteria(),
            "rollback_manager": self.rollback_manager.get_stats(),
            "promotion_manager": self.promotion_manager.get_stats(),
            "policy_engine": self.policy_engine.get_stats(),
        }

    def pause(self) -> None:
        """Pause the engine."""
        with self._lock:
            self._state = EngineState.PAUSED

    def resume(self) -> None:
        """Resume the engine."""
        with self._lock:
            self._state = EngineState.IDLE

    def shutdown(self) -> None:
        """Shutdown the engine."""
        with self._lock:
            self._state = EngineState.ERROR
            self._stop_background.set()


def create_self_improvement_engine(
    config: Optional[SafeSelfImprovementConfig] = None,
) -> SafeSelfImprovementEngine:
    """Create a SafeSelfImprovementEngine with sensible defaults."""
    return SafeSelfImprovementEngine(config=config)