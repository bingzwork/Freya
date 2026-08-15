"""Controlled canary validation primitives for safe promotion."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CanaryDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class CanaryEvidence:
    candidate_id: str
    tested: str
    environment: str
    executed: bool
    outcome: Optional[str]
    metrics: Dict[str, Any] = field(default_factory=dict)
    baseline: Dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    decision: CanaryDecision = CanaryDecision.INCONCLUSIVE

    @property
    def passed(self) -> bool:
        return self.executed and self.outcome == "success" and self.decision is CanaryDecision.PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "tested": self.tested,
            "environment": self.environment,
            "executed": self.executed,
            "outcome": self.outcome,
            "metrics": self.metrics,
            "baseline": self.baseline,
            "failures": self.failures,
            "decision": self.decision.value,
            "passed": self.passed,
        }


class CanaryValidator:
    """Run a supplied controlled executor and validate its evidence."""

    def __init__(self, executor: Optional[Callable[[Any, Any], Dict[str, Any]]] = None) -> None:
        self._executor = executor

    def validate(self, candidate: Any, execution_result: Any) -> CanaryEvidence:
        if not callable(self._executor):
            return CanaryEvidence(
                candidate_id=candidate.id,
                tested=candidate.title or candidate.id,
                environment="controlled_canary",
                executed=False,
                outcome=None,
                failures=["controlled canary executor unavailable"],
            )
        try:
            raw = self._executor(candidate, execution_result)
        except Exception as exc:
            return CanaryEvidence(
                candidate_id=candidate.id,
                tested=candidate.title or candidate.id,
                environment="controlled_canary",
                executed=False,
                outcome=None,
                failures=[f"validator crashed: {exc}"],
            )
        if not isinstance(raw, dict):
            return CanaryEvidence(
                candidate_id=candidate.id,
                tested=candidate.title or candidate.id,
                environment="controlled_canary",
                executed=False,
                outcome=None,
                failures=["validator returned malformed evidence"],
            )
        try:
            decision = CanaryDecision(raw.get("decision", CanaryDecision.INCONCLUSIVE))
        except ValueError:
            decision = CanaryDecision.INCONCLUSIVE
        failures = raw.get("failures", [])
        if not isinstance(failures, list):
            failures = ["canary failures field is malformed"]
            decision = CanaryDecision.INCONCLUSIVE
        executed = raw.get("executed") is True
        outcome = raw.get("outcome")
        if not executed or outcome not in {"success", "failure"}:
            failures = list(failures) + ["canary execution evidence is incomplete"]
            decision = CanaryDecision.INCONCLUSIVE
        return CanaryEvidence(
            candidate_id=candidate.id,
            tested=str(raw.get("tested", candidate.title or candidate.id)),
            environment=str(raw.get("environment", "controlled_canary")),
            executed=executed,
            outcome=outcome if isinstance(outcome, str) else None,
            metrics=raw.get("metrics", {}) if isinstance(raw.get("metrics", {}), dict) else {},
            baseline=raw.get("baseline", {}) if isinstance(raw.get("baseline", {}), dict) else {},
            failures=[str(item) for item in failures],
            decision=decision,
        )


__all__ = ["CanaryDecision", "CanaryEvidence", "CanaryValidator"]
