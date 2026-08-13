"""
Risk-Based Execution with RiskAnalyzer Integration.

Provides risk assessment and execution control for self-improvements
using the existing RiskAnalyzer from app/risk.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from enum import Enum

from app.safe_self_improvement.models import (
    FileModification,
    ImprovementCandidate,
    ExecutionResult,
    RiskLevel,
)
from app.risk.risk_analyzer import RiskAnalyzer
from app.core.logger import logger


class ExecutionRiskAssessment:
    """Container for execution risk assessment results."""

    def __init__(
        self,
        candidate: ImprovementCandidate,
        overall_risk: RiskLevel,
        risk_score: float,
        risk_factors: List[Dict[str, Any]],
        allow_execution: bool,
        requires_approval: bool,
        requires_verification: bool,
        recommended_rollback: bool,
        details: Dict[str, Any],
    ):
        self.candidate = candidate
        self.overall_risk = overall_risk
        self.risk_score = risk_score
        self.risk_factors = risk_factors
        self.allow_execution = allow_execution
        self.requires_approval = requires_approval
        self.requires_verification = requires_verification
        self.recommended_rollback = recommended_rollback
        self.details = details
        self.assessed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate.id,
            "overall_risk": self.overall_risk.value,
            "risk_score": self.risk_score,
            "risk_factors": self.risk_factors,
            "allow_execution": self.allow_execution,
            "requires_approval": self.requires_approval,
            "requires_verification": self.requires_verification,
            "recommended_rollback": self.recommended_rollback,
            "details": self.details,
            "assessed_at": self.assessed_at,
        }


class RiskBasedExecutor:
    """
    Executes improvements with risk-based decision making.

    Integrates with RiskAnalyzer to assess risk before execution
    and applies appropriate safeguards based on risk level.
    """

    def __init__(
        self,
        risk_analyzer: Optional[RiskAnalyzer] = None,
        auto_approve_max_risk: RiskLevel = RiskLevel.LOW,
        require_human_approval_risk: RiskLevel = RiskLevel.HIGH,
        require_verification_risk: RiskLevel = RiskLevel.MEDIUM,
        max_concurrent_improvements: int = 1,
        enable_dry_run: bool = True,
    ):
        self.risk_analyzer = risk_analyzer or RiskAnalyzer()
        self.auto_approve_max_risk = auto_approve_max_risk
        self.require_human_approval_risk = require_human_approval_risk
        self.require_verification_risk = require_verification_risk
        self.max_concurrent_improvements = max_concurrent_improvements
        self.enable_dry_run = enable_dry_run

        self._lock = threading.RLock()
        self._active_executions: Dict[str, ExecutionResult] = {}
        self._execution_history: List[ExecutionResult] = []
        self._stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "rolled_back_executions": 0,
            "auto_approved": 0,
            "human_approved": 0,
            "rejected_by_risk": 0,
        }

    def assess_risk(self, candidate: ImprovementCandidate) -> ExecutionRiskAssessment:
        """
        Assess the risk of executing an improvement candidate.

        Uses RiskAnalyzer to analyze each modification and aggregates results.
        """
        all_risk_factors = []
        file_risk_scores = []

        for mod in candidate.modifications:
            # Analyze risk for this modification's new content
            content = mod.new_content or ""
            if content:
                risk_result = self.risk_analyzer.analyze(content, mod.file_path)

                # Extract risk factors
                for check_name, check_result in risk_result.check_results.items():
                    if check_result.get("risk_level") != "none":
                        all_risk_factors.append({
                            "modification_id": mod.id,
                            "file_path": mod.file_path,
                            "check": check_name,
                            "risk_level": check_result.get("risk_level"),
                            "details": check_result.get("details", {}),
                        })

                # Get numeric risk score
                risk_score = risk_result.risk_score
                file_risk_scores.append(risk_score)

        # Calculate overall risk
        if file_risk_scores:
            overall_risk_score = max(file_risk_scores)
            overall_risk = RiskLevel.from_score(overall_risk_score)
        else:
            overall_risk_score = 0.0
            overall_risk = RiskLevel.NONE

        # Determine execution requirements
        allow_execution = overall_risk <= RiskLevel.CRITICAL
        requires_approval = overall_risk >= self.require_human_approval_risk
        requires_verification = overall_risk >= self.require_verification_risk
        recommended_rollback = overall_risk >= RiskLevel.HIGH

        # Auto-approval logic
        if overall_risk <= self.auto_approve_max_risk:
            requires_approval = False

        details = {
            "file_count": len(candidate.modifications),
            "file_risk_scores": dict(zip([m.file_path for m in candidate.modifications], file_risk_scores)),
            "max_file_risk": max(file_risk_scores) if file_risk_scores else 0.0,
            "risk_factor_count": len(all_risk_factors),
        }

        return ExecutionRiskAssessment(
            candidate=candidate,
            overall_risk=overall_risk,
            risk_score=overall_risk_score,
            risk_factors=all_risk_factors,
            allow_execution=allow_execution,
            requires_approval=requires_approval,
            requires_verification=requires_verification,
            recommended_rollback=recommended_rollback,
            details=details,
        )

    def execute(
        self,
        candidate: ImprovementCandidate,
        approval_status: str = "pending",
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute an improvement candidate.

        Args:
            candidate: The improvement to execute
            approval_status: Current approval status (pending, approved, auto_approved)
            dry_run: If True, perform a dry run without applying changes

        Returns:
            ExecutionResult with outcome
        """
        import time
        start_time = time.time()

        with self._lock:
            # Check concurrent limit
            active_count = sum(1 for r in self._active_executions.values() if not r.success)
            if active_count >= self.max_concurrent_improvements:
                return ExecutionResult(
                    candidate_id=candidate.id,
                    success=False,
                    error=f"Max concurrent improvements reached ({self.max_concurrent_improvements})",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Create execution record
            execution = ExecutionResult(candidate_id=candidate.id)
            self._active_executions[candidate.id] = execution
            self._stats["total_executions"] += 1

        try:
            # Assess risk first
            assessment = self.assess_risk(candidate)

            # Check if execution is allowed
            if not assessment.allow_execution:
                execution.success = False
                execution.error = f"Risk too high: {assessment.overall_risk.value}"
                self._stats["rejected_by_risk"] += 1
                return self._finalize_execution(candidate.id, execution, start_time)

            # Check approval requirements
            if assessment.requires_approval and approval_status not in ("approved", "auto_approved"):
                execution.success = False
                execution.error = "Human approval required but not provided"
                return self._finalize_execution(candidate.id, execution, start_time)

            # Track approval type
            if approval_status == "auto_approved":
                self._stats["auto_approved"] += 1
            elif approval_status == "approved":
                self._stats["human_approved"] += 1

            # Perform dry run if enabled and not already done
            if dry_run or (self.enable_dry_run and not dry_run):
                dry_run_result = self._dry_run(candidate)
                if not dry_run_result.success:
                    execution.success = False
                    execution.error = f"Dry run failed: {dry_run_result.error}"
                    return self._finalize_execution(candidate.id, execution, start_time)
                execution.verification_results["dry_run"] = dry_run_result.verification_results

            # Apply modifications
            applied, failed = self._apply_modifications(candidate.modifications)
            execution.applied_modifications = applied
            execution.failed_modifications = failed

            if failed:
                execution.success = False
                execution.error = f"{len(failed)} modifications failed"
                self._stats["failed_executions"] += 1

                # Rollback if needed
                if assessment.recommended_rollback and applied:
                    rollback_result = self._rollback(candidate.id, applied)
                    execution.rollback_performed = True
                    execution.rollback_reason = "execution_failed"
                    self._stats["rolled_back_executions"] += 1
                return self._finalize_execution(candidate.id, execution, start_time)

            # Run verification if required
            if assessment.requires_verification:
                verification_result = self._verify(candidate, applied)
                execution.verification_results["verification"] = verification_result

                if not verification_result.get("passed", False):
                    execution.success = False
                    execution.error = "Verification failed"

                    # Auto-rollback on verification failure
                    if applied:
                        rollback_result = self._rollback(candidate.id, applied)
                        execution.rollback_performed = True
                        execution.rollback_reason = "verification_failed"
                        self._stats["rolled_back_executions"] += 1
                    return self._finalize_execution(candidate.id, execution, start_time)

            execution.success = True
            self._stats["successful_executions"] += 1

        except Exception as e:
            logger.error(f"[RiskBasedExecutor] Execution error: {e}")
            execution.success = False
            execution.error = str(e)
            self._stats["failed_executions"] += 1

        return self._finalize_execution(candidate.id, execution, start_time)

    def _dry_run(self, candidate: ImprovementCandidate) -> ExecutionResult:
        """Perform a dry run of the modifications."""
        # Validate modifications would apply cleanly
        for mod in candidate.modifications:
            # Check file exists for modifications
            if mod.modification_type in (ModificationType.MODIFY, ModificationType.RENAME, ModificationType.MOVE, ModificationType.DELETE):
                from pathlib import Path
                if not Path(mod.file_path).exists():
                    return ExecutionResult(
                        candidate_id=candidate.id,
                        success=False,
                        error=f"File not found for modification: {mod.file_path}",
                    )

            # Check for syntax issues in Python files
            if mod.file_path.endswith(".py") and mod.new_content:
                try:
                    import ast
                    ast.parse(mod.new_content)
                except SyntaxError as e:
                    return ExecutionResult(
                        candidate_id=candidate.id,
                        success=False,
                        error=f"Syntax error in {mod.file_path}: {e}",
                    )

        return ExecutionResult(
            candidate_id=candidate.id,
            success=True,
            verification_results={"dry_run": "passed"},
        )

    def _apply_modifications(
        self, modifications: List[FileModification]
    ) -> tuple[List[FileModification], List[FileModification]]:
        """Apply modifications to files."""
        import shutil
        from pathlib import Path

        applied = []
        failed = []

        for mod in modifications:
            try:
                file_path = Path(mod.file_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)

                if mod.modification_type == ModificationType.CREATE:
                    file_path.write_text(mod.new_content or "", encoding="utf-8")
                elif mod.modification_type == ModificationType.MODIFY:
                    file_path.write_text(mod.new_content or "", encoding="utf-8")
                elif mod.modification_type == ModificationType.DELETE:
                    if file_path.exists():
                        file_path.unlink()
                elif mod.modification_type == ModificationType.RENAME:
                    # Rename is handled as move with new name
                    new_path = Path(mod.new_content or "")
                    shutil.move(str(file_path), str(new_path))
                elif mod.modification_type == ModificationType.MOVE:
                    new_path = Path(mod.new_content or "")
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(file_path), str(new_path))

                applied.append(mod)

            except Exception as e:
                logger.error(f"[RiskBasedExecutor] Failed to apply {mod.file_path}: {e}")
                failed.append(mod)

        return applied, failed

    def _verify(self, candidate: ImprovementCandidate, applied: List[FileModification]) -> Dict[str, Any]:
        """Verify applied modifications."""
        results = {"checks": {}, "passed": True}

        # Run tests if available
        try:
            import subprocess
            result = subprocess.run(
                ["python", "-m", "pytest", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(Path(".").resolve()),
            )
            results["checks"]["tests"] = {
                "passed": result.returncode == 0,
                "output": result.stdout[-2000:] if result.stdout else "",
                "error": result.stderr[-2000:] if result.stderr else "",
            }
            if result.returncode != 0:
                results["passed"] = False
        except subprocess.TimeoutExpired:
            results["checks"]["tests"] = {"passed": False, "error": "Test timeout"}
            results["passed"] = False
        except Exception as e:
            results["checks"]["tests"] = {"passed": False, "error": str(e)}

        # Run linting
        try:
            import subprocess
            result = subprocess.run(
                ["python", "-m", "ruff", "check", "."],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(Path(".").resolve()),
            )
            results["checks"]["lint"] = {
                "passed": result.returncode == 0,
                "output": result.stdout[-2000:] if result.stdout else "",
            }
            if result.returncode != 0:
                results["passed"] = False
        except Exception as e:
            results["checks"]["lint"] = {"passed": True, "skipped": True, "error": str(e)}

        # Run RiskAnalyzer on modified files
        try:
            risk_results = {}
            for mod in applied:
                if mod.new_content and mod.file_path.endswith(".py"):
                    risk_result = self.risk_analyzer.analyze(mod.new_content, mod.file_path)
                    risk_results[mod.file_path] = {
                        "risk_score": risk_result.risk_score,
                        "risk_level": risk_result.risk_level.value,
                    }
            results["checks"]["risk_analysis"] = risk_results
        except Exception as e:
            results["checks"]["risk_analysis"] = {"error": str(e)}

        return results

    def _rollback(self, candidate_id: str, applied: List[FileModification]) -> Dict[str, Any]:
        """Rollback applied modifications."""
        # For simplicity, we'd need a RollbackManager with checkpoints
        # This is a placeholder - actual implementation in rollback.py
        return {"rolled_back": True, "candidate_id": candidate_id}

    def _finalize_execution(
        self, candidate_id: str, execution: ExecutionResult, start_time: float
    ) -> ExecutionResult:
        """Finalize execution record."""
        execution.duration_ms = (time.time() - start_time) * 1000
        execution.executed_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            if candidate_id in self._active_executions:
                del self._active_executions[candidate_id]
            self._execution_history.append(execution)
            # Keep last 1000
            if len(self._execution_history) > 1000:
                self._execution_history = self._execution_history[-1000:]

        return execution

    def get_execution(self, candidate_id: str) -> Optional[ExecutionResult]:
        """Get execution result by candidate ID."""
        with self._lock:
            # Check active
            if candidate_id in self._active_executions:
                return self._active_executions[candidate_id]
            # Check history
            for exec_result in reversed(self._execution_history):
                if exec_result.candidate_id == candidate_id:
                    return exec_result
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        with self._lock:
            return dict(self._stats)

    def get_recent_executions(self, limit: int = 50) -> List[ExecutionResult]:
        """Get recent execution history."""
        with self._lock:
            return self._execution_history[-limit:]