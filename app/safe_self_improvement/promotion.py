"""
Safe Patch Promotion.

Manages the promotion of patches from staging to production.
Integrates with SafetyPromotionGates for evaluation.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum
import uuid

from app.safe_self_improvement.models import (
    ImprovementCandidate,
    FileModification,
    ExecutionResult,
    RollbackReason,
)
from app.core.safety_gates import SafetyPromotionGates, PromotionDecision, PromotionContext
from app.core.logger import logger
from app.safe_self_improvement.canary import CanaryValidator, CanaryEvidence
from app.safe_self_improvement.measurement import ImprovementEvidence
from app.safe_self_improvement.promotion_contract import (
    PromotionRequest,
    RollbackEvidence,
)
from app.safe_self_improvement.rollback import RollbackManager


class PromotionStage(Enum):
    """Stages in the promotion pipeline."""

    STAGING = "staging"
    VERIFICATION = "verification"
    TESTING = "testing"
    CANARY = "canary"
    PRODUCTION = "production"


class PromotionResult:
    """Result of a promotion attempt."""

    def __init__(
        self,
        candidate_id: str,
        success: bool,
        stage: PromotionStage,
        decision: PromotionDecision,
        details: Dict[str, Any],
        error: Optional[str] = None,
    ):
        self.candidate_id = candidate_id
        self.success = success
        self.stage = stage
        self.decision = decision
        self.details = details
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "success": self.success,
            "stage": self.stage.value,
            "decision": self.decision.value if self.decision else None,
            "details": self.details,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class PromotionPipelineConfig:
    """Configuration for the promotion pipeline."""

    stages: List[PromotionStage] = field(default_factory=lambda: [
        PromotionStage.VERIFICATION,
        PromotionStage.TESTING,
        PromotionStage.CANARY,
        PromotionStage.PRODUCTION,
    ])
    require_all_stages: bool = True
    canary_percentage: float = 10.0
    canary_duration_seconds: float = 300.0
    auto_promote_on_success: bool = True
    rollback_on_failure: bool = True
    canary_validator: Optional[CanaryValidator] = None


class PatchPromotionManager:
    """
    Manages safe patch promotion through stages.

    Integrates with SafetyPromotionGates for evaluation at each stage.
    """

    def __init__(
        self,
        safety_gates: Optional[SafetyPromotionGates] = None,
        config: Optional[PromotionPipelineConfig] = None,
        staging_dir: str = "data/promotion/staging",
        production_dir: str = "data/promotion/production",
        rollback_manager: Optional[RollbackManager] = None,
    ):
        self.safety_gates = safety_gates or SafetyPromotionGates()
        self.config = config or PromotionPipelineConfig()
        self.rollback_manager = rollback_manager
        self.staging_dir = Path(staging_dir)
        self.production_dir = Path(production_dir)

        self._lock = threading.RLock()
        self._promotion_history: List[PromotionResult] = []
        self._active_promotions: Dict[str, Dict[str, Any]] = {}
        self._stats = {
            "total_promotions": 0,
            "successful_promotions": 0,
            "failed_promotions": 0,
            "rolled_back_promotions": 0,
        }

        # Create directories
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.production_dir.mkdir(parents=True, exist_ok=True)

    def promote(
        self,
        request: PromotionRequest | ImprovementCandidate,
        execution_result: Optional[ExecutionResult] = None,
        skip_stages: Optional[List[PromotionStage]] = None,
    ) -> PromotionResult:
        """Promote a validated evidence package through the canonical pipeline.

        ``PromotionRequest`` is the authoritative API.  The legacy
        ``promote(candidate, execution_result)`` shape is retained only as a
        narrow adapter so existing callers cannot bypass request validation;
        notably, serialized metadata is never converted into improvement
        evidence by that adapter.
        """
        if isinstance(request, PromotionRequest):
            if execution_result is not None:
                return PromotionResult(
                    candidate_id=getattr(request.candidate, "id", ""),
                    success=False,
                    stage=PromotionStage.STAGING,
                    decision=PromotionDecision.REJECTED,
                    details={"validation_errors": ["PromotionRequest received an unexpected execution result"]},
                    error="Malformed promotion call",
                )
        else:
            if not isinstance(request, ImprovementCandidate) or not isinstance(execution_result, ExecutionResult):
                return PromotionResult(
                    candidate_id=getattr(request, "id", ""),
                    success=False,
                    stage=PromotionStage.STAGING,
                    decision=PromotionDecision.REJECTED,
                    details={"validation_errors": ["Promotion requires a PromotionRequest"]},
                    error="Malformed promotion call",
                )
            request = self._legacy_request(request, execution_result)

        validation = request.validate(require_rollback=self.config.rollback_on_failure)
        candidate = request.candidate
        execution_result = request.execution_result
        if not validation.valid:
            self._stats["total_promotions"] += 1
            self._stats["failed_promotions"] += 1
            rollback_result = self._rollback_request(request, RollbackReason.VERIFICATION_FAILED)
            result = PromotionResult(
                candidate_id=candidate.id,
                success=False,
                stage=PromotionStage.STAGING,
                decision=PromotionDecision.REJECTED,
                details={
                    "validation_errors": list(validation.errors),
                    "safety_gates": {"rejection_reasons": list(validation.errors)},
                    "rollback": rollback_result,
                },
                error="Promotion request validation failed",
            )
            self._promotion_history.append(result)
            return result

        with self._lock:
            self._stats["total_promotions"] += 1

            # Track active promotion
            promotion_id = f"promo_{uuid.uuid4().hex[:8]}"
            self._active_promotions[candidate.id] = {
                "promotion_id": promotion_id,
                "candidate": candidate,
                "execution_result": execution_result,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "current_stage": PromotionStage.STAGING.value,
            }

        try:
            # A promotion must always pass the authoritative safety gate,
            # even when callers request skipped stages.
            safety_result = self._evaluate_safety_gates(request)
            if safety_result.decision != PromotionDecision.APPROVED:
                rollback_result = self._rollback_request(request, RollbackReason.RISK_EXCEEDED)
                result = PromotionResult(
                    candidate_id=candidate.id,
                    success=False,
                    stage=PromotionStage.STAGING,
                    decision=PromotionDecision.REJECTED,
                    details={"safety_gates": safety_result.to_dict(), "rollback": rollback_result},
                    error="Safety promotion gates rejected the candidate",
                )
                self._stats["failed_promotions"] += 1
                self._promotion_history.append(result)
                return result

            # Run through each stage
            skip_stages = skip_stages or []
            all_passed = True
            stage_results = {"safety_preflight": safety_result.to_dict()}

            for stage in self.config.stages:
                if stage in skip_stages:
                    stage_results[stage.value] = {"skipped": True}
                    continue

                # Update current stage
                with self._lock:
                    if candidate.id in self._active_promotions:
                        self._active_promotions[candidate.id]["current_stage"] = stage.value

                # Run stage
                stage_result = self._run_stage(request, stage)
                stage_results[stage.value] = stage_result

                if not stage_result.get("passed", False):
                    all_passed = False
                    break

            # Determine final result
            if all_passed and self.config.auto_promote_on_success:
                # Move to production
                deploy_result = self._deploy_to_production(candidate, execution_result)
                success = deploy_result.get("success", False)
                decision = PromotionDecision.APPROVED if success else PromotionDecision.REJECTED
            else:
                success = all_passed
                decision = PromotionDecision.APPROVED if all_passed else PromotionDecision.REJECTED

            # Rollback on failure if configured
            rollback_result = None
            if not success:
                rollback_result = self._rollback_request(request, RollbackReason.VERIFICATION_FAILED)

            final_stage = self.config.stages[-1] if all_passed else stage
            result = PromotionResult(
                candidate_id=candidate.id,
                success=success,
                stage=final_stage,
                decision=decision,
                details={
                    "stages": stage_results,
                    "promotion_id": promotion_id,
                    "rollback": rollback_result,
                },
                error=None if success else stage_results.get(final_stage.value, {}).get("error"),
            )

            if success:
                self._stats["successful_promotions"] += 1
            else:
                self._stats["failed_promotions"] += 1

        except Exception as e:
            logger.error(f"[PatchPromotionManager] Promotion error: {e}")
            rollback_result = self._rollback_request(request, RollbackReason.SYSTEM_ERROR)
            result = PromotionResult(
                candidate_id=candidate.id,
                success=False,
                stage=PromotionStage.STAGING,
                decision=PromotionDecision.REJECTED,
                details={"rollback": rollback_result},
                error=str(e),
            )
            self._stats["failed_promotions"] += 1

        finally:
            with self._lock:
                if candidate.id in self._active_promotions:
                    del self._active_promotions[candidate.id]

        self._promotion_history.append(result)
        if len(self._promotion_history) > 1000:
            self._promotion_history = self._promotion_history[-1000:]

        return result

    def _rollback_request(
        self,
        request: PromotionRequest,
        reason: RollbackReason,
    ) -> Optional[Dict[str, Any]]:
        """Use the canonical rollback manager for every post-application rejection."""
        if not self.config.rollback_on_failure or self.rollback_manager is None:
            return None
        rollback = request.rollback_evidence
        checkpoint_id = rollback.checkpoint_id if isinstance(rollback, RollbackEvidence) else None
        try:
            result = self.rollback_manager.rollback(request.candidate_identity, reason, checkpoint_id)
        except Exception as error:
            logger.error("[PatchPromotionManager] Rollback failed: %s", error)
            return {"success": False, "error": str(error), "reason": reason.value}
        self._stats["rolled_back_promotions"] += 1
        return result

    def _legacy_request(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> PromotionRequest:
        """Adapt the old call shape without treating metadata as typed evidence."""
        candidate_metadata = getattr(candidate, "metadata", {}) or {}
        execution_metadata = getattr(execution_result, "metadata", {}) or {}
        checkpoint_id = str(
            execution_metadata.get("rollback_checkpoint_id")
            or candidate_metadata.get("rollback_checkpoint_id", "")
        )
        rollback_plan = str(
            execution_metadata.get("rollback_plan")
            or candidate_metadata.get("rollback_plan", "")
        )
        rollback_evidence = None
        if checkpoint_id or rollback_plan:
            rollback_evidence = RollbackEvidence(
                candidate_id=candidate.id,
                checkpoint_id=checkpoint_id,
                rollback_plan=rollback_plan,
                available=True,
            )
        return PromotionRequest.from_execution(
            candidate,
            execution_result,
            improvement_evidence=None,
            rollback_evidence=rollback_evidence,
        )

    def _evaluate_safety_gates(self, request: PromotionRequest):
        """Evaluate promotion safety using only validated typed request evidence."""
        from app.core.safety_gates import PromotionResult as SafetyPromotionResult

        candidate = request.candidate
        execution_result = request.execution_result
        evidence_errors: List[str] = []
        if execution_result.candidate_id != candidate.id:
            evidence_errors.append("Execution result does not match candidate")
        if not isinstance(execution_result.verification_results, dict):
            evidence_errors.append("Verification evidence is missing or malformed")
            verification = None
        else:
            verification = execution_result.verification_results.get("verification")
            if not isinstance(verification, dict):
                evidence_errors.append("Verification evidence is missing or malformed")
            elif "passed" not in verification:
                evidence_errors.append("Verification evidence has no explicit pass state")
            elif verification["passed"] is not True:
                evidence_errors.append("Verification evidence did not pass")
        if execution_result.failed_modifications:
            evidence_errors.append("Execution contains failed modifications")

        rollback = request.rollback_evidence
        rollback_plan = ""
        if isinstance(rollback, RollbackEvidence):
            rollback_plan = rollback.checkpoint_id or rollback.rollback_plan

        # ImprovementEvidence is authoritative here; the serialized metadata
        # mirror is deliberately not consulted for safety decisions.
        if (getattr(candidate, "metadata", {}) or {}).get("measurement_required"):
            evidence_errors.extend(self._validate_measurement_evidence(request.improvement_evidence))

        try:
            confidence = candidate.confidence
            if isinstance(confidence, bool):
                raise ValueError("boolean confidence")
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
            evidence_errors.append("Candidate confidence is invalid")

        risk_level = getattr(candidate, "estimated_risk", None)
        risk_mapping = {
            "none": "safe",
            "low": "low_risk",
            "medium": "medium_risk",
            "high": "high_risk",
            "critical": "critical",
        }
        risk_value = getattr(risk_level, "value", risk_level)
        safety_value = risk_mapping.get(risk_value)
        if safety_value is None:
            evidence_errors.append("Candidate risk level is invalid")
            safety_value = "critical"

        from app.core.safety_gates import SafetyLevel
        context = PromotionContext(
            operation_id=candidate.id,
            operation_type="self_improvement",
            description=candidate.description or candidate.title or "Self-improvement candidate",
            source=candidate.source or "SafeSelfImprovement",
            payload=candidate,
            metadata={
                "execution_verification": request.verification_evidence.to_dict(),
                "promotion_provenance": request.provenance.to_dict(),
                "safety_evidence_errors": evidence_errors,
            },
            confidence=confidence,
            rollback_possible=bool(rollback_plan),
            rollback_plan=str(rollback_plan),
            safety_level=SafetyLevel(safety_value),
            affected_systems=list(getattr(candidate, "affected_files", []) or []),
        )

        try:
            evaluator = getattr(self.safety_gates, "evaluate", None)
            if not callable(evaluator):
                evaluator = getattr(self.safety_gates, "evaluate_promotion", None)
            if not callable(evaluator):
                raise TypeError("Safety gate evaluator is unavailable")
            gate_result = evaluator(context)
            if not isinstance(gate_result, SafetyPromotionResult):
                raise TypeError("Safety gate evaluator returned malformed result")
        except Exception as error:
            gate_result = SafetyPromotionResult(
                operation_id=candidate.id,
                decision=PromotionDecision.REJECTED,
                safety_level=SafetyLevel.CRITICAL,
                overall_confidence=0.0,
                rejection_reasons=["Safety gate evaluation failed"],
                metadata={"evaluation_error": str(error)},
            )

        return gate_result

    @staticmethod
    def _validate_measurement_evidence(evidence: Any) -> List[str]:
        if not isinstance(evidence, ImprovementEvidence):
            return ["Required improvement measurement evidence is missing or malformed"]
        validation_errors = []
        if evidence.valid is not True:
            validation_errors.append("Improvement measurement evidence is invalid or inconclusive")
        if not evidence.comparisons:
            validation_errors.append("Improvement measurement comparisons are missing")
            return validation_errors
        statuses = {item.status.value for item in evidence.comparisons.values()}
        if "inconclusive" in statuses:
            validation_errors.append("Improvement measurement contains inconclusive metrics")
        if "regressed" in statuses:
            validation_errors.append("Improvement measurement detected a regression")
        if "improved" not in statuses:
            validation_errors.append("Improvement measurement provides no improvement evidence")
        return validation_errors

    def _run_stage(
        self,
        request: PromotionRequest,
        stage: PromotionStage,
    ) -> Dict[str, Any]:
        """Run a promotion stage using the validated request."""
        result = {"stage": stage.value, "passed": False, "details": {}}

        if stage == PromotionStage.VERIFICATION:
            result = self._run_verification_stage(request)
        elif stage == PromotionStage.TESTING:
            result = self._run_testing_stage(request.candidate, request.execution_result)
        elif stage == PromotionStage.CANARY:
            result = self._run_canary_stage(request)
        elif stage == PromotionStage.PRODUCTION:
            result = self._run_production_stage(request)

        return result

    def _run_verification_stage(
        self,
        request: PromotionRequest,
    ) -> Dict[str, Any]:
        """Run verification stage using typed evidence, not metadata."""
        details = {
            "execution_verification": request.verification_evidence.to_dict(),
            "improvement_evidence": request.improvement_evidence.to_dict()
            if request.improvement_evidence else None,
        }
        return {
            "stage": "verification",
            "passed": request.verification_evidence.passed is True,
            "details": details,
        }

    def _run_testing_stage(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> Dict[str, Any]:
        """Run testing stage - execute test suite."""
        import subprocess

        details = {}

        try:
            # Run pytest
            test_cmd = ["python", "-m", "pytest", "--tb=short", "-q"]
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(Path(".").resolve()),
            )
            details["pytest"] = {
                "returncode": result.returncode,
                "stdout": result.stdout[-5000:] if result.stdout else "",
                "stderr": result.stderr[-5000:] if result.stderr else "",
            }
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            details["pytest"] = {"error": "Test timeout"}
            passed = False
        except Exception as e:
            details["pytest"] = {"error": str(e)}
            passed = False

        # Also run lint
        try:
            lint_cmd = ["python", "-m", "ruff", "check", "."]
            result = subprocess.run(
                lint_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(Path(".").resolve()),
            )
            details["lint"] = {
                "returncode": result.returncode,
                "stdout": result.stdout[-2000:] if result.stdout else "",
            }
            if not passed and result.returncode != 0:
                passed = False  # Lint failure doesn't override test failure
        except Exception as e:
            details["lint"] = {"error": str(e), "skipped": True}

        return {"stage": "testing", "passed": passed, "details": details}

    def _run_canary_stage(
        self,
        request: PromotionRequest,
    ) -> Dict[str, Any]:
        """Run a real controlled canary and fail closed without exact PASS evidence."""
        candidate = request.candidate
        execution_result = request.execution_result
        validator = self.config.canary_validator
        if not isinstance(validator, CanaryValidator):
            evidence = CanaryValidator().validate(candidate, execution_result)
        else:
            evidence = validator.validate(candidate, execution_result)
        if evidence.candidate_id != request.candidate_identity:
            evidence = CanaryEvidence(
                candidate_id=evidence.candidate_id,
                tested=evidence.tested,
                environment=evidence.environment,
                executed=evidence.executed,
                outcome=evidence.outcome,
                metrics=evidence.metrics,
                baseline=evidence.baseline,
                failures=[*evidence.failures, "canary candidate identity does not match request"],
            )
        details = {
            "canary_percentage": self.config.canary_percentage,
            "duration_seconds": self.config.canary_duration_seconds,
            "simulated": False,
            "evidence": evidence.to_dict(),
        }
        return {
            "stage": "canary",
            "passed": evidence.passed,
            "details": details,
            "error": None if evidence.passed else "; ".join(evidence.failures) or "canary did not pass",
        }

    def _run_production_stage(
        self,
        request: PromotionRequest,
    ) -> Dict[str, Any]:
        """Run production stage - final validation."""
        details = {"final_validation": True}

        # Final safety gate check. Never default to approval when an
        # evaluator is unavailable or the gate API fails.
        gate_result = self._evaluate_safety_gates(request)
        details["final_safety_gates"] = gate_result.to_dict()

        passed = gate_result.decision == PromotionDecision.APPROVED

        return {"stage": "production", "passed": passed, "details": details}

    def _deploy_to_production(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> Dict[str, Any]:
        """Deploy to production (already applied, just record)."""
        # The modifications were already applied during execution
        # This stage just records the promotion
        try:
            # Save promotion record
            promo_file = self.production_dir / f"{candidate.id}_{datetime.now(timezone.utc).isoformat().replace(':', '-')}.json"
            promo_file.parent.mkdir(parents=True, exist_ok=True)

            promo_record = {
                "candidate_id": candidate.id,
                "title": candidate.title,
                "modifications": [m.to_dict() for m in execution_result.applied_modifications],
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "execution_result": execution_result.to_dict(),
            }

            import json
            with open(promo_file, "w", encoding="utf-8") as f:
                json.dump(promo_record, f, indent=2, ensure_ascii=False)

            return {"success": True, "promotion_file": str(promo_file)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_promotion_status(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an active promotion."""
        with self._lock:
            return self._active_promotions.get(candidate_id)

    def get_promotion_history(self, limit: int = 50) -> List[PromotionResult]:
        """Get promotion history."""
        with self._lock:
            return self._promotion_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get promotion statistics."""
        with self._lock:
            return {
                **self._stats,
                "active_promotions": len(self._active_promotions),
            }

    def cancel_promotion(self, candidate_id: str) -> bool:
        """Cancel an active promotion."""
        with self._lock:
            if candidate_id in self._active_promotions:
                del self._active_promotions[candidate_id]
                return True
            return False


def create_patch_promotion_manager(
    safety_gates: Optional[SafetyPromotionGates] = None,
) -> PatchPromotionManager:
    """Create a PatchPromotionManager with sensible defaults."""
    return PatchPromotionManager(safety_gates=safety_gates)