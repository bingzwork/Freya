"""Execution Verifier for the single execution pipeline.

Verifies execution outcomes and routes to appropriate next steps:
- Passed -> Task Complete -> ConversationControl
- Failed -> RepairLoop -> UnifiedPlanner (for re-planning)
"""

from dataclasses import dataclass
from typing import Optional, List, Any, Dict
from app.core.logger import logger
from app.core.protocols import ChatActivityProvider
from app.verification.runner import VerificationResult


@dataclass
class ExecutionOutcome:
    """Result of execution verification."""
    success: bool
    verification_result: VerificationResult
    experience_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class ExecutionVerifier:
    """
    Verifies execution outcomes and routes to learning pipeline or repair loop.

    Responsibilities:
    - Verify execution results using verification commands
    - Extract experience/outcome data for learning pipeline
    - Route successful executions to task completion
    - Route failed executions to repair loop
    """

    def __init__(
        self,
        verification_runner: Any,  # VerificationRunner instance
        learning_pipeline: Any,    # LearningPipeline instance
        observability_hub: Any,    # ObservabilityHub instance
        chat_activity: ChatActivityProvider,
    ):
        self._verification_runner = verification_runner
        self._learning_pipeline = learning_pipeline
        self._observability_hub = observability_hub
        self._chat_activity = chat_activity

    def verify_execution(
        self,
        task: str,
        plan_results: List[Any],
        allow_mutations: bool = True
    ) -> ExecutionOutcome:
        """
        Verify the execution of a plan and return the outcome.

        Args:
            task: The original task description
            plan_results: Results from executing the plan
            allow_mutations: Whether mutations were allowed

        Returns:
            ExecutionOutcome indicating success/failure and next steps
        """
        logger.info("[ExecutionVerifier]")
        logger.info("Started")

        # Notify observability hub of verification start
        if hasattr(self._observability_hub, 'record_metric'):
            self._observability_hub.record_metric("execution.verification.started", 1)

        # Run verification (tests + lint)
        verification_result = self._verification_runner.dry_run_verify()

        # Prepare experience data for learning pipeline
        experience_data = self._extract_experience_data(
            task, plan_results, verification_result, allow_mutations
        )

        outcome = ExecutionOutcome(
            success=verification_result.success,
            verification_result=verification_result,
            experience_data=experience_data,
            error_message=None if verification_result.success else verification_result.stderr
        )

        # Route to appropriate next step
        if verification_result.success:
            logger.info("[ExecutionVerifier]")
            logger.info("Passed - routing to task completion")
            self._route_to_task_completion(task, experience_data)
        else:
            logger.info("[ExecutionVerifier]")
            logger.info(f"Failed - routing to repair loop: {verification_result.stderr}")
            self._route_to_learning_pipeline(experience_data, success=False)

        # Notify observability hub of verification completion
        if hasattr(self._observability_hub, 'record_metric'):
            metric_name = "execution.verification.passed" if verification_result.success else "execution.verification.failed"
            self._observability_hub.record_metric(metric_name, 1)

        return outcome

    def _extract_experience_data(
        self,
        task: str,
        plan_results: List[Any],
        verification_result: VerificationResult,
        allow_mutations: bool
    ) -> Dict[str, Any]:
        """Extract experience data for the learning pipeline."""
        return {
            "task": task,
            "plan_results_count": len(plan_results),
            "allow_mutations": allow_mutations,
            "verification_stdout": verification_result.stdout,
            "verification_stderr": verification_result.stderr,
            "verification_return_code": verification_result.return_code,
            "success": verification_result.success,
            "timestamp": self._get_current_timestamp()
        }

    def _route_to_task_completion(self, task: str, experience_data: Dict[str, Any]) -> None:
        """Route successful execution to task completion and conversation control."""
        # Send experience to learning pipeline
        self._route_to_learning_pipeline(experience_data, success=True)

        # Notify conversation control of task completion
        if hasattr(self._chat_activity, 'task_completed'):
            self._chat_activity.task_completed(task, experience_data)
        elif hasattr(self._chat_activity, 'chat_ended'):
            self._chat_activity.chat_ended()

    def _route_to_learning_pipeline(self, experience_data: Dict[str, Any], success: bool) -> None:
        """Send experience data to the learning pipeline."""
        if self._learning_pipeline and hasattr(self._learning_pipeline, 'add_experience'):
            try:
                self._learning_pipeline.add_experience(
                    task=experience_data.get("task", ""),
                    outcome="positive" if success else "negative",
                    metadata=experience_data
                )
            except Exception as e:
                logger.warning(f"Failed to add experience to learning pipeline: {e}")

    def _get_current_timestamp(self) -> str:
        """Get current timestamp for experience records."""
        from datetime import datetime
        return datetime.now().isoformat()