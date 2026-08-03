"""
Safe Patch Promotion.

Manages the promotion of patches from staging to production.
Integrates with SafetyPromotionGates for evaluation.
"""

import logging
import threading
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
from app.core.safety_gates import SafetyPromotionGates, PromotionDecision
from app.core.logger import logger


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
    ):
        self.safety_gates = safety_gates or SafetyPromotionGates()
        self.config = config or PromotionPipelineConfig()
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
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
        skip_stages: Optional[List[PromotionStage]] = None,
    ) -> PromotionResult:
        """
        Promote a successfully executed improvement through the pipeline.

        Args:
            candidate: The improvement candidate
            execution_result: Result of the execution
            skip_stages: Stages to skip (for emergency promotions)

        Returns:
            PromotionResult with outcome
        """
        with self._lock:
            if not execution_result.success:
                return PromotionResult(
                    candidate_id=candidate.id,
                    success=False,
                    stage=PromotionStage.STAGING,
                    decision=PromotionDecision.REJECTED,
                    details={},
                    error="Execution was not successful",
                )

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
            # Run through each stage
            skip_stages = skip_stages or []
            all_passed = True
            stage_results = {}

            for stage in self.config.stages:
                if stage in skip_stages:
                    stage_results[stage.value] = {"skipped": True}
                    continue

                # Update current stage
                with self._lock:
                    if candidate.id in self._active_promotions:
                        self._active_promotions[candidate.id]["current_stage"] = stage.value

                # Run stage
                stage_result = self._run_stage(candidate, execution_result, stage)
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
            if not success and self.config.rollback_on_failure:
                from app.safe_self_improvement.rollback import RollbackManager
                rollback_manager = RollbackManager()
                rollback_manager.rollback(candidate.id, RollbackReason.VERIFICATION_FAILED)
                self._stats["rolled_back_promotions"] += 1

            final_stage = self.config.stages[-1] if all_passed else stage
            result = PromotionResult(
                candidate_id=candidate.id,
                success=success,
                stage=final_stage,
                decision=decision,
                details={
                    "stages": stage_results,
                    "promotion_id": promotion_id,
                },
                error=None if success else stage_results.get(final_stage.value, {}).get("error"),
            )

            if success:
                self._stats["successful_promotions"] += 1
            else:
                self._stats["failed_promotions"] += 1

        except Exception as e:
            logger.error(f"[PatchPromotionManager] Promotion error: {e}")
            result = PromotionResult(
                candidate_id=candidate.id,
                success=False,
                stage=PromotionStage.STAGING,
                decision=PromotionDecision.REJECTED,
                details={},
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

    def _run_stage(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
        stage: PromotionStage,
    ) -> Dict[str, Any]:
        """Run a promotion stage."""
        result = {"stage": stage.value, "passed": False, "details": {}}

        if stage == PromotionStage.VERIFICATION:
            result = self._run_verification_stage(candidate, execution_result)
        elif stage == PromotionStage.TESTING:
            result = self._run_testing_stage(candidate, execution_result)
        elif stage == PromotionStage.CANARY:
            result = self._run_canary_stage(candidate, execution_result)
        elif stage == PromotionStage.PRODUCTION:
            result = self._run_production_stage(candidate, execution_result)

        return result

    def _run_verification_stage(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> Dict[str, Any]:
        """Run verification stage - check execution verification results."""
        details = {}

        # Check verification results from execution
        verification = execution_result.verification_results
        details["execution_verification"] = verification

        # Run safety gates
        gate_result = self.safety_gates.evaluate(candidate, execution_result)
        details["safety_gates"] = gate_result.to_dict() if gate_result else {}

        passed = gate_result.decision == PromotionDecision.APPROVED if gate_result else True

        return {"stage": "verification", "passed": passed, "details": details}

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
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> Dict[str, Any]:
        """Run canary stage - deploy to subset."""
        # In a real implementation, this would deploy to a canary environment
        # For now, we simulate with a quick health check
        import time

        details = {
            "canary_percentage": self.config.canary_percentage,
            "duration_seconds": self.config.canary_duration_seconds,
            "simulated": True,
        }

        # Simulate canary period
        time.sleep(min(1.0, self.config.canary_duration_seconds / 100))

        # Check health (placeholder)
        details["health_check"] = {"status": "healthy", "simulated": True}

        return {"stage": "canary", "passed": True, "details": details}

    def _run_production_stage(
        self,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
    ) -> Dict[str, Any]:
        """Run production stage - final validation."""
        details = {"final_validation": True}

        # Final safety gate check
        gate_result = self.safety_gates.evaluate(candidate, execution_result)
        details["final_safety_gates"] = gate_result.to_dict() if gate_result else {}

        passed = gate_result.decision == PromotionDecision.APPROVED if gate_result else True

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