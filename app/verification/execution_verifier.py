"""Execution verification and learning handoff for the canonical execution pipeline."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.logger import logger
from app.core.protocols import ChatActivityProvider
from app.learning.models import LearningCandidate, LearningCandidateType
from app.verification.runner import VerificationResult


@dataclass
class ExecutionOutcome:
    """Verified execution state together with its typed learning candidate.

    ``LearningCandidate`` is the sole public contract at the verification to
    learning boundary.  This wrapper retains the verification-facing result
    needed by the execution state machine without creating a second learning
    outcome type.
    """

    success: bool
    verification_result: Optional[VerificationResult]
    learning_candidate: LearningCandidate
    execution_results: List[Any]
    error_message: Optional[str] = None


class ExecutionVerifier:
    """Verify execution outcomes and send every terminal outcome to learning."""

    def __init__(
        self,
        verification_runner: Any,
        learning_pipeline: Any,
        observability_hub: Any,
        chat_activity: ChatActivityProvider,
    ):
        self._verification_runner = verification_runner
        self._learning_pipeline = learning_pipeline
        self._observability_hub = observability_hub
        self._chat_activity = chat_activity
        self._request_context: Dict[str, Any] = {}

    def set_request_context(self, request_context: Optional[Dict[str, Any]]) -> None:
        """Bind request identity to the next terminal verification outcome."""
        self._request_context = dict(request_context or {})

    def set_learning_pipeline(self, learning_pipeline: Any) -> None:
        """Late-bind the canonical LearningPipeline after ordered construction."""
        self._learning_pipeline = learning_pipeline

    def verify_execution(
        self,
        task: str,
        plan_results: List[Any],
        allow_mutations: bool = True,
        verification_result: Optional[VerificationResult] = None,
        route_learning: bool = True,
    ) -> ExecutionOutcome:
        """Verify a completed execution and route its typed outcome to learning.

        ``verification_result`` is accepted for a repaired execution, where the
        repair loop has already performed the final verification.  It prevents a
        second verification command while preserving the same learning handoff.
        """
        logger.info("[ExecutionVerifier] Started")
        self._record_metric("execution.verification.started")

        verification_result = verification_result or self._verification_runner.dry_run_verify()
        outcome = self._create_outcome(
            task=task,
            plan_results=plan_results,
            allow_mutations=allow_mutations,
            verification_result=verification_result,
            success=verification_result.success,
            error_message=None if verification_result.success else self._verification_error(verification_result),
        )

        if route_learning:
            self._route_to_learning_pipeline(outcome.learning_candidate)
            if outcome.success:
                logger.info("[ExecutionVerifier] Passed - routing to task completion")
                self._route_to_task_completion(task, outcome.learning_candidate)
                self._record_metric("execution.verification.passed")
            else:
                logger.info("[ExecutionVerifier] Failed - routed to learning pipeline")
                self._record_metric("execution.verification.failed")
        return outcome

    def record_execution_failure(
        self,
        task: str,
        plan_results: List[Any],
        error_message: str,
        allow_mutations: bool = True,
        verification_result: Optional[VerificationResult] = None,
    ) -> ExecutionOutcome:
        """Route an execution failure that occurred before verification.

        An executor failure has no ``VerificationResult``.  It is nevertheless a
        terminal execution outcome and therefore uses the same
        ``LearningCandidate`` contract as verification failures and successes.
        """
        logger.info("[ExecutionVerifier] Execution failed before verification")
        outcome = self._create_outcome(
            task=task,
            plan_results=plan_results,
            allow_mutations=allow_mutations,
            verification_result=verification_result,
            success=False,
            error_message=error_message,
        )
        self._route_to_learning_pipeline(outcome.learning_candidate)
        self._record_metric("execution.failed_before_verification")
        return outcome

    def _create_outcome(
        self,
        task: str,
        plan_results: List[Any],
        allow_mutations: bool,
        verification_result: Optional[VerificationResult],
        success: bool,
        error_message: Optional[str],
    ) -> ExecutionOutcome:
        candidate = self._create_learning_candidate(
            task=task,
            plan_results=plan_results,
            allow_mutations=allow_mutations,
            verification_result=verification_result,
            success=success,
            error_message=error_message,
        )
        return ExecutionOutcome(
            success=success,
            verification_result=verification_result,
            learning_candidate=candidate,
            execution_results=plan_results,
            error_message=error_message,
        )

    def _create_learning_candidate(
        self,
        task: str,
        plan_results: List[Any],
        allow_mutations: bool,
        verification_result: Optional[VerificationResult],
        success: bool,
        error_message: Optional[str],
    ) -> LearningCandidate:
        verification_data = None
        verification_status = "unknown"
        if verification_result is not None:
            verification_status = getattr(verification_result, "status", None)
            verification_status = getattr(verification_status, "value", verification_status) or (
                "verified" if verification_result.success else "failed"
            )
            verification_data = {
                "success": verification_result.success,
                "status": verification_status,
                "command": list(verification_result.command),
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "return_code": verification_result.return_code,
            }

        outcome_label = "successful" if success else "failed"
        verification_label = (
            "not_run"
            if verification_result is None
            else "passed" if verification_result.success else "failed"
        )
        timestamp = datetime.now(timezone.utc)
        raw_observation = {
            "task": task,
            "execution_results": self._serialize_value(plan_results),
            "execution_result_count": len(plan_results),
            "execution_success": success,
            "verification": verification_data,
            "error": error_message,
            "allow_mutations": allow_mutations,
            "verification_status": verification_status,
            "request_context": {
                key: self._request_context.get(key)
                for key in ("trace_id", "correlation_id", "request_id", "session_id", "source", "channel")
                if self._request_context.get(key) is not None
            },
        }
        context = {
            "verification_timestamp": timestamp.isoformat(),
            "verification_status": verification_status,
            "execution_context": "canonical_execution_engine",
            "trace_id": self._request_context.get("trace_id") or self._request_context.get("correlation_id"),
            "session_id": self._request_context.get("session_id"),
        }
        return LearningCandidate(
            candidate_type=LearningCandidateType.EXECUTION_OUTCOME,
            timestamp=timestamp,
            source_component="ExecutionVerifier",
            source_session_id=str(self._request_context.get("session_id") or ""),
            raw_observation=raw_observation,
            context=context,
            tags=["execution_outcome", f"execution_{outcome_label}", f"verification_{verification_label}"],
            metadata={
                "outcome": outcome_label,
                "execution_success": success,
                "verification_success": verification_result.success if verification_result else None,
            },
        )

    def _route_to_task_completion(self, task: str, candidate: LearningCandidate) -> None:
        """Notify conversation control after learning accepts a verified success."""
        if hasattr(self._chat_activity, "task_completed"):
            self._chat_activity.task_completed(task, candidate.to_dict())
        elif hasattr(self._chat_activity, "chat_ended"):
            self._chat_activity.chat_ended()

    def _route_to_learning_pipeline(self, candidate: LearningCandidate) -> Any:
        """Send the single supported typed contract to ``LearningPipeline.run``."""
        if self._learning_pipeline is None or not hasattr(self._learning_pipeline, "run"):
            raise RuntimeError("ExecutionVerifier requires a learning pipeline exposing run(candidate).")
        return self._learning_pipeline.run(candidate)

    def _record_metric(self, name: str) -> None:
        if hasattr(self._observability_hub, "record_metric"):
            self._observability_hub.record_metric(name, 1)

    @staticmethod
    def _verification_error(verification_result: VerificationResult) -> str:
        return (verification_result.stderr or verification_result.stdout or "verification failed").strip()

    @classmethod
    def _serialize_value(cls, value: Any) -> Any:
        """Keep learning payloads compatible with durable JSON memory storage."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._serialize_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._serialize_value(item) for item in value]
        return str(value)


__all__ = ["ExecutionOutcome", "ExecutionVerifier"]
