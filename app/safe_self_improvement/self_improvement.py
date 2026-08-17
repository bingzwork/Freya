"""
Safe Self-Improvement Engine.

Main orchestrator for safe autonomous self-improvement operations.
Integrates all components: allowlist, boundaries, risk execution, approval gates,
prioritization, rollback, promotion, and policies.
"""

import hashlib
import json
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
    ImprovementCategory,
)
from app.safe_self_improvement.allowlist import AllowlistManager, create_default_allowlist_manager
from app.safe_self_improvement.boundaries import BoundaryManager, create_default_boundary_manager
from app.safe_self_improvement.risk_execution import RiskBasedExecutor, ExecutionRiskAssessment
from app.safe_self_improvement.approval_gates import ApprovalGateManager, ApprovalDecision
from app.safe_self_improvement.prioritization import ImprovementPrioritizer, PrioritizationCriteria, create_balanced_prioritizer
from app.safe_self_improvement.rollback import RollbackManager, RollbackReason, create_rollback_manager
from app.safe_self_improvement.promotion import PatchPromotionManager, PromotionStage, create_patch_promotion_manager
from app.safe_self_improvement.measurement import ImprovementEvidence, ImprovementMeasurement
from app.safe_self_improvement.promotion_contract import (
    PromotionProvenance,
    PromotionRequest,
    RollbackEvidence,
)
from app.safe_self_improvement.policies import PolicyEngine, PolicyAction, create_policy_engine
from app.core.events import Event, EventBus
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
        event_bus: Optional[EventBus] = None,
        workflow_orchestrator=None,
        improvement_measurement: Optional[ImprovementMeasurement] = None,
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
        self.improvement_measurement = improvement_measurement

        # State tracking
        self._pending_candidates: Dict[str, ImprovementCandidate] = {}
        self._processing_candidates: Dict[str, Dict[str, Any]] = {}
        self._completed_candidates: Dict[str, ExecutionResult] = {}
        self._submission_queue: List[str] = []
        # Group identity and evidence signature prevent repeated equivalent
        # diagnostics.grouped events from reopening the same repair proposal.
        self._diagnostic_group_candidates: Dict[str, str] = {}
        self._background_thread: Optional[threading.Thread] = None
        self._stop_background = threading.Event()
        if event_bus is None:
            raise ValueError("SafeSelfImprovementEngine requires an injected EventBus")
        self._event_bus = event_bus
        self._workflow_orchestrator = workflow_orchestrator
        self._subscriptions = []

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
        self._subscribe_to_events()

    def submit_improvement(
        self,
        candidate: ImprovementCandidate,
        auto_execute: bool = False,
        _approved_request: Optional[ApprovalRequest] = None,
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

        # 6. Check if approval needed.  An already approved request may re-enter
        # here from approve_candidate(), but it must not create a second gate.
        approval_request = _approved_request
        if approval_request is None and (policy_evaluation["requires_approval"] or risk_assessment.requires_approval):
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
                    "baseline_measurements": self._collect_measurements(candidate),
                }

            self._trigger_callbacks("on_executing", candidate)

            approval_status = approval_request.status.value if approval_request else "not_required"
            self._event_bus.emit(
                "self_improvement.workflow_requested",
                {
                    "candidate_id": candidate.id,
                    "approval_status": approval_status,
                    "checkpoint_id": checkpoint.id if checkpoint else None,
                },
                source="SafeSelfImprovementEngine",
            )
            if self._workflow_orchestrator is None:
                execution_result = ExecutionResult(
                    candidate_id=candidate.id,
                    success=False,
                    error="No WorkflowOrchestrator is bound; improvement was not applied.",
                    metadata={"workflow_required": True},
                )
                self._event_bus.emit(
                    "self_improvement.rejected",
                    {"candidate_id": candidate.id, "reason": execution_result.error},
                    source="SafeSelfImprovementEngine",
                )
            else:
                try:
                    execution_result = self._workflow_orchestrator.execute_safe_self_improvement(
                        candidate,
                        execute=lambda: self.risk_executor.execute(
                            candidate,
                            approval_status=approval_status,
                        ),
                        approval_status=approval_status,
                    )
                except Exception as error:
                    execution_result = ExecutionResult(
                        candidate_id=candidate.id,
                        success=False,
                        error=f"Workflow safety gate rejected or failed: {error}",
                        metadata={"workflow_required": True},
                    )
                    self._event_bus.emit(
                        "self_improvement.rejected",
                        {"candidate_id": candidate.id, "reason": execution_result.error},
                        source="SafeSelfImprovementEngine",
                    )

            self._event_bus.emit(
                "self_improvement.applied",
                {
                    "candidate_id": candidate.id,
                    "success": execution_result.success,
                    "verification": execution_result.verification_results,
                },
                source="SafeSelfImprovementEngine",
            )
            verification = execution_result.verification_results.get("verification", {})
            self._event_bus.emit(
                "self_improvement.verified",
                {
                    "candidate_id": candidate.id,
                    "passed": verification.get("passed", execution_result.success),
                    "verification": verification,
                },
                source="SafeSelfImprovementEngine",
            )

            # Attach comparable before/after evidence before any promotion decision.
            processing_state = self._processing_candidates.get(candidate.id, {})
            improvement_evidence = self._attach_improvement_evidence(
                candidate,
                execution_result,
                processing_state.get("baseline_measurements", {}),
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
                    self._event_bus.emit(
                        "self_improvement.rolled_back",
                        {"candidate_id": candidate.id, "reason": RollbackReason.VERIFICATION_FAILED.value},
                        source="SafeSelfImprovementEngine",
                    )
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
                        self._event_bus.emit(
                            "self_improvement.rolled_back",
                            {"candidate_id": candidate.id, "reason": RollbackReason.TESTS_FAILED.value},
                            source="SafeSelfImprovementEngine",
                        )
                        self._stats["rolled_back"] += 1

            with self._lock:
                if candidate.id in self._processing_candidates:
                    del self._processing_candidates[candidate.id]
                self._completed_candidates[candidate.id] = execution_result

            self._trigger_callbacks("on_executed", execution_result)

            if execution_result.success:
                self._stats["succeeded"] += 1

                # 9. Promote if successful. The checkpoint is part of the
                # promotion evidence; without it, the safety gate must reject.
                if self.config.promotion_require_tests or self.config.promotion_require_lint:
                    if checkpoint:
                        execution_result.metadata["rollback_checkpoint_id"] = checkpoint.id
                    rollback_evidence = RollbackEvidence(
                        candidate_id=candidate.id,
                        checkpoint_id=checkpoint.id if checkpoint else str(
                            execution_result.metadata.get("rollback_checkpoint_id", "")
                        ),
                        rollback_plan=(
                            f"checkpoint:{checkpoint.id}" if checkpoint else str(
                                execution_result.metadata.get("rollback_plan", "")
                            )
                        ),
                        available=bool(checkpoint or execution_result.metadata.get("rollback_checkpoint_id") or execution_result.metadata.get("rollback_plan")),
                    )
                    request = PromotionRequest.from_execution(
                        candidate,
                        execution_result,
                        improvement_evidence=improvement_evidence,
                        rollback_evidence=rollback_evidence,
                        provenance=PromotionProvenance(
                            candidate_id=candidate.id,
                            execution_id=execution_result.executed_at,
                            verification_source="ExecutionResult.verification_results",
                            measurement_source=improvement_evidence.provenance if improvement_evidence else "",
                            rollback_checkpoint_id=rollback_evidence.checkpoint_id,
                        ),
                    )
                    promo_result = self.promotion_manager.promote(request)
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

    def _collect_measurements(self, candidate: ImprovementCandidate) -> Dict[str, Any]:
        """Collect factual metrics from the canonical measurement provider."""
        if self.improvement_measurement is None:
            return {}
        try:
            definitions = (getattr(candidate, "metadata", {}) or {}).get("measurement_definitions")
            return self.improvement_measurement.collect(definitions=definitions)
        except Exception as error:
            logger.warning('Improvement measurement collection failed: {0}'.format(error))
            return {}

    def _attach_improvement_evidence(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
        baseline: Dict[str, Any],
    ) -> Optional[ImprovementEvidence]:
        """Add typed before/after evidence and retain a serialized compatibility mirror."""
        if not (getattr(candidate, "metadata", {}) or {}).get("measurement_required"):
            return None
        after = self._collect_measurements(candidate)
        definitions = (getattr(candidate, "metadata", {}) or {}).get("measurement_definitions")
        if self.improvement_measurement is None:
            execution_result.metadata["improvement_evidence"] = {"valid": False, "reason": "measurement provider unavailable"}
            return None
        evidence = self.improvement_measurement.compare(
            baseline,
            after,
            tolerance=float((getattr(candidate, "metadata", {}) or {}).get("measurement_tolerance", 0.0)),
            provenance="ObservabilityHub",
            candidate_id=candidate.id,
        )
        execution_result.metadata["improvement_evidence"] = evidence.to_dict()
        return evidence

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

        # Re-enter the normal validation path with this exact approved request;
        # the execution branch will hand off to WorkflowOrchestrator rather than
        # directly applying mutations.
        submission_result = self.submit_improvement(
            candidate,
            auto_execute=True,
            _approved_request=approval_request,
        )
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

    def set_workflow_orchestrator(self, workflow_orchestrator) -> None:
        """Late-bind the canonical workflow boundary after ordered startup."""
        self._workflow_orchestrator = workflow_orchestrator

    def shutdown(self) -> None:
        """Shutdown the engine."""
        with self._lock:
            self._state = EngineState.ERROR
            self._stop_background.set()

    def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events from other subsystems."""
        # Subscribe to learning improvement candidates from LearningPipeline
        self._subscriptions.append(
            self._event_bus.subscribe(
                "learning.improvement_candidate",
                self._on_learning_improvement_candidate,
            )
        )
        
        # Raw diagnostic findings remain available to observability and other
        # consumers.  Grouped evidence is the sole diagnostic-derived input for
        # autonomous improvement-candidate consideration.
        self._subscriptions.append(
            self._event_bus.subscribe(
                "diagnostics.grouped",
                self._on_diagnostics_grouped,
            )
        )

    def _on_learning_improvement_candidate(self, event: Event) -> None:
        """Convert a learning event from the shared EventBus into an improvement candidate."""
        data = event.data
        candidate_id = data.get("candidate_id")
        stored_item_ids = data.get("stored_item_ids", [])
        source_component = data.get("source_component", "unknown")

        if not candidate_id or not stored_item_ids:
            return

        candidate = ImprovementCandidate(
            title=f"Learning pipeline improvement from {source_component}",
            description=f"Learning pipeline identified {len(stored_item_ids)} items worth storing as improvements",
            category=ImprovementCategory.DOCUMENTATION,
            source="learning_pipeline",
            metadata={
                "learning_candidate_id": candidate_id,
                "stored_item_ids": stored_item_ids,
                "source_component": source_component,
            },
        )

        self.submit_improvement(candidate, auto_execute=True)

    def _on_diagnostics_grouped(self, event: Event) -> None:
        """Consider one candidate per eligible causal diagnostic group.

        Raw ``diagnostics.completed`` findings are intentionally not handled
        here.  They remain observable evidence, while the initializer-owned
        DiagnosticGrouper is the authoritative diagnostic-to-candidate seam.
        Invalid or unresolved groups are ignored rather than converted into
        speculative repair proposals.
        """
        data = event.data if isinstance(event.data, dict) else {}
        report = data.get("report", data)
        groups = report.get("groups", []) if isinstance(report, dict) else []

        for group in groups:
            if not isinstance(group, dict):
                continue
            candidate = self._candidate_from_diagnostic_group(group)
            if candidate is None:
                continue

            group_key = self._diagnostic_group_key(group)
            evidence_signature = self._diagnostic_group_signature(group)
            with self._lock:
                if self._diagnostic_group_candidates.get(group_key) == evidence_signature:
                    continue

            self.submit_improvement(candidate, auto_execute=False)
            with self._lock:
                self._diagnostic_group_candidates[group_key] = evidence_signature

    @staticmethod
    def _diagnostic_group_key(group: Dict[str, Any]) -> str:
        """Reuse the grouper's stable group identity whenever available."""
        group_id = group.get("group_id")
        if group_id:
            return str(group_id)
        root = group.get("root", {})
        representative = root.get("representative", {}) if isinstance(root, dict) else {}
        stable_material = {
            "root": representative,
            "symptoms": group.get("symptoms", []),
        }
        return "group_" + hashlib.sha256(
            json.dumps(stable_material, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _diagnostic_group_signature(group: Dict[str, Any]) -> str:
        """Describe stable evidence state that justifies reconsideration."""
        evidence = []
        for occurrence in SafeSelfImprovementEngine._group_occurrences(group):
            representative = occurrence.get("representative", {})
            if not isinstance(representative, dict):
                representative = {}
            evidence.append(
                {
                    "stable_fields": {
                        "source": representative.get("source"),
                        "failure_type": representative.get("failure_type"),
                        "component": representative.get("component"),
                        "operation": representative.get("operation"),
                        "fingerprint": representative.get("fingerprint"),
                    },
                    "occurrence_count": int(occurrence.get("occurrence_count", 0) or 0),
                }
            )
        payload = {
            "group_id": SafeSelfImprovementEngine._diagnostic_group_key(group),
            "relation": group.get("relation"),
            "evidence": evidence,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _group_occurrences(group: Dict[str, Any]) -> List[Dict[str, Any]]:
        occurrences = []
        root = group.get("root")
        if isinstance(root, dict):
            occurrences.append(root)
        symptoms = group.get("symptoms", [])
        if isinstance(symptoms, list):
            occurrences.extend(item for item in symptoms if isinstance(item, dict))
        return occurrences

    @classmethod
    def _candidate_from_diagnostic_group(cls, group: Dict[str, Any]) -> Optional[ImprovementCandidate]:
        """Build a normal candidate while retaining the complete group evidence."""
        from app.diagnostics.grouping import CausalRelation

        relation = str(group.get("relation") or CausalRelation.UNRESOLVED)
        occurrences = cls._group_occurrences(group)
        root_occurrence_count = int((group.get("root") or {}).get("occurrence_count", 0) or 0)
        is_exact_duplicate_group = (
            relation == CausalRelation.UNRESOLVED
            and len(occurrences) == 1
            and root_occurrence_count > 1
        )
        if relation not in {
            CausalRelation.KNOWN_CAUSE,
            CausalRelation.LIKELY_CAUSE,
            CausalRelation.RELATED,
        } and not is_exact_duplicate_group:
            # An unresolved single finding cannot authorize a repair.  Exact
            # duplicates are the narrow exception: they yield one evidence-
            # preserving proposal without asserting a root cause.
            return None

        representatives = [
            item.get("representative", {})
            for item in occurrences
            if isinstance(item.get("representative", {}), dict)
        ]
        actionable_severities = set()
        for rep in representatives:
            metadata = rep.get("metadata", {}) if isinstance(rep.get("metadata"), dict) else {}
            severity = rep.get("severity") or metadata.get("severity") or rep.get("failure_type")
            if severity is not None:
                actionable_severities.add(str(severity).lower())
        if not actionable_severities.intersection({"error", "critical"}):
            return None

        root = group.get("root", {})
        root_rep = root.get("representative", {}) if isinstance(root, dict) else {}
        root_title = root_rep.get("title") or root_rep.get("failure_type") or "diagnostic group"
        group_id = cls._diagnostic_group_key(group)
        occurrence_count = sum(int(item.get("occurrence_count", 0) or 0) for item in occurrences)
        member_ids = []
        affected_files = []
        for item in occurrences:
            representative = item.get("representative", {})
            if isinstance(representative, dict):
                if representative.get("file_path"):
                    affected_files.append(str(representative["file_path"]))
            ids = item.get("event_ids", [])
            if isinstance(ids, list):
                member_ids.extend(str(identifier) for identifier in ids)

        if relation == CausalRelation.KNOWN_CAUSE:
            description_prefix = "Grouped diagnostics identify a known causal relationship."
        elif relation == CausalRelation.LIKELY_CAUSE:
            description_prefix = "Grouped diagnostics indicate a likely causal relationship; causality remains uncertain."
        elif is_exact_duplicate_group:
            description_prefix = "Grouped diagnostics are exact duplicate occurrences; no root cause is asserted."
        else:
            description_prefix = "Grouped diagnostics are related, but no root cause is asserted."

        metadata: Dict[str, Any] = {
            "diagnostic_group_id": group_id,
            "causal_relation": relation,
            "diagnostic_group": group,
            "member_diagnostic_ids": member_ids,
            "occurrence_count": occurrence_count,
            "severity": sorted(actionable_severities),
        }
        causal_confidence = group.get("causal_confidence")
        if causal_confidence is None and isinstance(root_rep.get("metadata"), dict):
            causal_confidence = root_rep["metadata"].get("causal_confidence")
        if causal_confidence is not None:
            metadata["causal_confidence"] = causal_confidence

        return ImprovementCandidate(
            title=f"Fix grouped diagnostic: {root_title}",
            description=f"{description_prefix} Evidence contains {len(member_ids)} diagnostic occurrences across {len(occurrences)} grouped findings.",
            category=ImprovementCategory.CORRECTNESS,
            source="diagnostics",
            affected_files=sorted(set(affected_files)),
            metadata=metadata,
        )


def create_self_improvement_engine(
    config: Optional[SafeSelfImprovementConfig] = None,
    event_bus: Optional[EventBus] = None,
    workflow_orchestrator=None,
    promotion_manager: Optional[PatchPromotionManager] = None,
    rollback_manager: Optional[RollbackManager] = None,
    improvement_measurement: Optional[ImprovementMeasurement] = None,
) -> SafeSelfImprovementEngine:
    """Create a SafeSelfImprovementEngine with shared runtime collaborators."""
    return SafeSelfImprovementEngine(
        config=config,
        event_bus=event_bus,
        workflow_orchestrator=workflow_orchestrator,
        promotion_manager=promotion_manager,
        rollback_manager=rollback_manager,
        improvement_measurement=improvement_measurement,
    )
