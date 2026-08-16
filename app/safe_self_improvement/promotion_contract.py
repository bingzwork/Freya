"""Typed, validated evidence contract for self-improvement promotion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from app.safe_self_improvement.measurement import (
    ComparisonStatus,
    ImprovementEvidence,
)
from app.safe_self_improvement.models import (
    ExecutionResult,
    ImprovementCandidate,
)


@dataclass(frozen=True)
class VerificationEvidence:
    """Explicit verification outcome submitted for promotion."""

    candidate_id: str
    passed: bool
    details: Mapping[str, Any] = field(default_factory=dict)
    provenance: str = "ExecutionResult.verification_results"

    @classmethod
    def from_execution_result(cls, execution_result: ExecutionResult) -> "VerificationEvidence":
        raw = execution_result.verification_results
        verification = raw.get("verification") if isinstance(raw, dict) else None
        passed = isinstance(verification, dict) and verification.get("passed") is True
        return cls(
            candidate_id=execution_result.candidate_id,
            passed=passed,
            details=dict(raw) if isinstance(raw, dict) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "details": dict(self.details),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class RollbackEvidence:
    """Reference proving that the applied candidate can be restored."""

    candidate_id: str
    checkpoint_id: str = ""
    rollback_plan: str = ""
    available: bool = True
    provenance: str = "RollbackManager"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "checkpoint_id": self.checkpoint_id,
            "rollback_plan": self.rollback_plan,
            "available": self.available,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class PromotionProvenance:
    """Traceability linking all evidence in a promotion request."""

    candidate_id: str
    execution_id: str
    verification_source: str
    measurement_source: str = ""
    rollback_checkpoint_id: str = ""
    policy_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "execution_id": self.execution_id,
            "verification_source": self.verification_source,
            "measurement_source": self.measurement_source,
            "rollback_checkpoint_id": self.rollback_checkpoint_id,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class PromotionValidation:
    """Result of validating a PromotionRequest."""

    errors: Tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.valid


@dataclass(frozen=True)
class PromotionRequest:
    """Complete typed evidence package submitted to the promotion boundary."""

    candidate: ImprovementCandidate
    candidate_identity: str
    execution_result: ExecutionResult
    verification_evidence: VerificationEvidence
    improvement_evidence: Optional[ImprovementEvidence]
    rollback_evidence: Optional[RollbackEvidence]
    provenance: PromotionProvenance

    @classmethod
    def from_execution(
        cls,
        candidate: ImprovementCandidate,
        execution_result: ExecutionResult,
        *,
        improvement_evidence: Optional[ImprovementEvidence] = None,
        rollback_evidence: Optional[RollbackEvidence] = None,
        provenance: Optional[PromotionProvenance] = None,
    ) -> "PromotionRequest":
        verification_evidence = VerificationEvidence.from_execution_result(execution_result)
        if provenance is None:
            provenance = PromotionProvenance(
                candidate_id=candidate.id,
                execution_id=execution_result.executed_at,
                verification_source=verification_evidence.provenance,
                measurement_source=(improvement_evidence.provenance if improvement_evidence else ""),
                rollback_checkpoint_id=rollback_evidence.checkpoint_id if rollback_evidence else "",
            )
        return cls(
            candidate=candidate,
            candidate_identity=candidate.id,
            execution_result=execution_result,
            verification_evidence=verification_evidence,
            improvement_evidence=improvement_evidence,
            rollback_evidence=rollback_evidence,
            provenance=provenance,
        )

    def validate(self, *, require_rollback: bool = True) -> PromotionValidation:
        """Validate the complete request without consulting arbitrary metadata."""
        errors = []
        candidate = self.candidate
        candidate_id = candidate.id if isinstance(candidate, ImprovementCandidate) else ""

        if not isinstance(candidate, ImprovementCandidate):
            errors.append("Promotion request candidate is missing or malformed")
        if not isinstance(self.candidate_identity, str) or not self.candidate_identity:
            errors.append("Promotion request candidate identity is missing or malformed")
        elif candidate_id and self.candidate_identity != candidate_id:
            errors.append("Promotion request candidate identity does not match candidate")

        execution = self.execution_result
        if not isinstance(execution, ExecutionResult):
            errors.append("Promotion request execution result is missing or malformed")
        else:
            if execution.candidate_id != candidate_id:
                errors.append("Execution result does not match candidate")
            if execution.success is not True:
                errors.append("Execution was not successful")
            if execution.failed_modifications:
                errors.append("Execution contains failed modifications")

        verification = self.verification_evidence
        if not isinstance(verification, VerificationEvidence):
            errors.append("Verification evidence is missing or malformed")
        else:
            if verification.candidate_id != candidate_id:
                errors.append("Verification evidence does not match candidate")
            if not isinstance(verification.details, Mapping) or "verification" not in verification.details:
                errors.append("Verification evidence is missing or malformed")
            elif verification.passed is not True:
                errors.append("Verification evidence did not pass")

        candidate_requires_measurement = (
            isinstance(candidate, ImprovementCandidate)
            and bool((candidate.metadata or {}).get("measurement_required"))
        )
        improvement = self.improvement_evidence
        if candidate_requires_measurement and not isinstance(improvement, ImprovementEvidence):
            errors.append("Required improvement measurement evidence is missing or malformed")
        if improvement is not None:
            if not isinstance(improvement, ImprovementEvidence):
                errors.append("Improvement measurement evidence is malformed")
            else:
                if not improvement.candidate_id:
                    errors.append("Improvement measurement evidence candidate identity is missing")
                elif improvement.candidate_id != candidate_id:
                    errors.append("Improvement measurement evidence does not match candidate")
                errors.extend(self._validate_improvement_evidence(improvement))

        rollback = self.rollback_evidence
        if require_rollback and not isinstance(rollback, RollbackEvidence):
            errors.append("Rollback evidence is missing or malformed")
        if rollback is not None:
            if not isinstance(rollback, RollbackEvidence):
                errors.append("Rollback evidence is malformed")
            else:
                if rollback.candidate_id != candidate_id:
                    errors.append("Rollback evidence does not match candidate")
                if rollback.available is not True:
                    errors.append("Rollback evidence is unavailable")
                if not rollback.checkpoint_id and not rollback.rollback_plan:
                    errors.append("Rollback evidence has no checkpoint or rollback plan")

        provenance = self.provenance
        if not isinstance(provenance, PromotionProvenance):
            errors.append("Promotion provenance is missing or malformed")
        else:
            if provenance.candidate_id != candidate_id:
                errors.append("Promotion provenance does not match candidate")
            if not provenance.execution_id or not provenance.verification_source:
                errors.append("Promotion provenance is incomplete")
            if rollback is not None and provenance.rollback_checkpoint_id and (
                provenance.rollback_checkpoint_id != rollback.checkpoint_id
            ):
                errors.append("Promotion provenance rollback checkpoint does not match rollback evidence")

        return PromotionValidation(tuple(dict.fromkeys(errors)))

    @staticmethod
    def _validate_improvement_evidence(evidence: ImprovementEvidence) -> list[str]:
        errors = []
        if evidence.valid is not True:
            errors.append("Improvement measurement evidence is invalid or inconclusive")
        if not evidence.comparisons:
            errors.append("Improvement measurement comparisons are missing")
            return errors
        statuses = {comparison.status for comparison in evidence.comparisons.values()}
        if ComparisonStatus.INCONCLUSIVE in statuses:
            errors.append("Improvement measurement contains inconclusive metrics")
        if ComparisonStatus.REGRESSED in statuses:
            errors.append("Improvement measurement detected a regression")
        if ComparisonStatus.IMPROVED not in statuses:
            errors.append("Improvement measurement provides no improvement evidence")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict() if isinstance(self.candidate, ImprovementCandidate) else None,
            "candidate_identity": self.candidate_identity,
            "execution_result": self.execution_result.to_dict() if isinstance(self.execution_result, ExecutionResult) else None,
            "verification_evidence": self.verification_evidence.to_dict() if isinstance(self.verification_evidence, VerificationEvidence) else None,
            "improvement_evidence": self.improvement_evidence.to_dict() if self.improvement_evidence else None,
            "rollback_evidence": self.rollback_evidence.to_dict() if self.rollback_evidence else None,
            "provenance": self.provenance.to_dict() if isinstance(self.provenance, PromotionProvenance) else None,
        }


__all__ = [
    "VerificationEvidence",
    "RollbackEvidence",
    "PromotionProvenance",
    "PromotionValidation",
    "PromotionRequest",
]
