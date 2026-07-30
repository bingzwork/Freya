"""Evaluation Manager - Central orchestrator for self-evaluation.

This module provides the EvaluationManager class which coordinates the complete
self-evaluation process for Freya's completed work.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import uuid
import threading

from app.evaluation.models import (
    EvaluationConfig,
    EvaluationResult,
    EvaluationType,
    EvaluationTrigger,
    EvaluationStatus,
    VerificationStatus,
    ValidationStatus,
    ConfidenceLevel,
    Requirement,
    RequirementVerification,
    ValidationCheck,
    ValidationResult,
    QualityReview,
    DocCheckResult,
    ImprovementIteration,
    ImprovementLoopResult,
)
from app.evaluation.pipeline import (
    EvaluationPipeline,
    RequirementVerifier,
    ValidationRunner,
    RegressionDetector,
    CodeQualityReviewer,
    DocumentationVerifier,
)
from app.core.logger import logger

if TYPE_CHECKING:
    from app.agent.core_agent import FreyaAgent
    from app.decision.manager import DecisionManager
    from app.verification.runner import VerificationRunner


@dataclass
class EvaluationRecord:
    """Persistent record of an evaluation run."""
    evaluation_id: str
    evaluation_type: str
    trigger: str
    task_id: Optional[str]
    task_description: str
    original_request: str
    goal_id: Optional[str]
    plan_id: Optional[str]
    status: str
    started_at: str
    completed_at: Optional[str]
    duration_seconds: float
    overall_confidence: float
    confidence_level: str
    requirement_score: float
    validation_score: float
    should_deliver: bool
    requires_rework: bool
    requires_human_review: bool
    rework_reasons: List[str]
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "evaluation_type": self.evaluation_type,
            "trigger": self.trigger,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "original_request": self.original_request,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level,
            "requirement_score": self.requirement_score,
            "validation_score": self.validation_score,
            "should_deliver": self.should_deliver,
            "requires_rework": self.requires_rework,
            "requires_human_review": self.requires_human_review,
            "rework_reasons": self.rework_reasons,
            "summary": self.summary,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationRecord":
        return cls(**data)

    @classmethod
    def from_result(cls, result: EvaluationResult) -> "EvaluationRecord":
        config = result.config
        return cls(
            evaluation_id=result.evaluation_id,
            evaluation_type=config.evaluation_type.value if config else "unknown",
            trigger=config.trigger.value if config else "unknown",
            task_id=config.task_id if config else None,
            task_description=config.task_description if config else "",
            original_request=config.original_request if config else "",
            goal_id=config.goal_id if config else None,
            plan_id=config.plan_id if config else None,
            status=result.status.value,
            started_at=result.started_at or "",
            completed_at=result.completed_at,
            duration_seconds=result.duration_seconds,
            overall_confidence=result.overall_confidence,
            confidence_level=result.confidence_level.value,
            requirement_score=result.requirement_score,
            validation_score=result.validation_score,
            should_deliver=result.should_deliver,
            requires_rework=result.requires_rework,
            requires_human_review=result.requires_human_review,
            rework_reasons=result.rework_reasons,
            summary=result.summary,
        )


class EvaluationHistory:
    """Persistent history of evaluation runs."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()
        self.history_file = self.workspace / ".evaluation_history.json"
        self._records: List[EvaluationRecord] = []
        self._lock = threading.Lock()
        self._load_history()

    def _load_history(self) -> None:
        """Load history from disk."""
        if not self.history_file.exists():
            return
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._records = [EvaluationRecord.from_dict(r) for r in data.get("records", [])]
        except Exception as e:
            logger.warning(f"Failed to load evaluation history: {e}")
            self._records = []

    def _save_history(self) -> None:
        """Save history to disk."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        data = {"records": [r.to_dict() for r in self._records]}
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save evaluation history: {e}")

    def add_record(self, record: EvaluationRecord) -> None:
        """Add an evaluation record."""
        with self._lock:
            self._records.append(record)
            self._save_history()

    def get_record(self, evaluation_id: str) -> Optional[EvaluationRecord]:
        """Get a record by evaluation ID."""
        for r in self._records:
            if r.evaluation_id == evaluation_id:
                return r
        return None

    def query(
        self,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        evaluation_type: Optional[str] = None,
        trigger: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> List[EvaluationRecord]:
        """Query evaluation records with filters."""
        results = self._records

        if task_id:
            results = [r for r in results if r.task_id == task_id]
        if goal_id:
            results = [r for r in results if r.goal_id == goal_id]
        if evaluation_type:
            results = [r for r in results if r.evaluation_type == evaluation_type]
        if trigger:
            results = [r for r in results if r.trigger == trigger]
        if since:
            results = [r for r in results if r.started_at >= since]
        if until:
            results = [r for r in results if r.started_at <= until]

        # Sort by most recent first
        results.sort(key=lambda r: r.started_at, reverse=True)
        return results[:limit]

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        if not self._records:
            return {
                "total_evaluations": 0,
                "average_confidence": 0.0,
                "deliver_rate": 0.0,
                "rework_rate": 0.0,
                "by_type": {},
                "by_trigger": {},
                "by_confidence_level": {},
            }

        total = len(self._records)
        delivered = sum(1 for r in self._records if r.should_deliver)
        reworked = sum(1 for r in self._records if r.requires_rework)

        by_type = {}
        for r in self._records:
            by_type[r.evaluation_type] = by_type.get(r.evaluation_type, 0) + 1

        by_trigger = {}
        for r in self._records:
            by_trigger[r.trigger] = by_trigger.get(r.trigger, 0) + 1

        by_confidence = {}
        for r in self._records:
            by_confidence[r.confidence_level] = by_confidence.get(r.confidence_level, 0) + 1

        return {
            "total_evaluations": total,
            "average_confidence": sum(r.overall_confidence for r in self._records) / total,
            "deliver_rate": delivered / total,
            "rework_rate": reworked / total,
            "by_type": by_type,
            "by_trigger": by_trigger,
            "by_confidence_level": by_confidence,
        }


class EvaluationManager:
    """Central manager for self-evaluation of completed work.

    This is the main entry point for running evaluations. It coordinates:
    1. Requirement verification against original requests
    2. Functional validation (tests, build, lint)
    3. Confidence scoring
    4. Delivery decision (deliver / rework / human review)
    5. History persistence for learning

    Usage:
        manager = EvaluationManager(agent=freya_agent)
        result = manager.evaluate_task_completion(
            task_description="Implement feature X",
            original_request="User asked to implement feature X",
        )
    """

    def __init__(
        self,
        workspace: str = ".",
        agent: Optional["FreyaAgent"] = None,
        decision_manager: Optional["DecisionManager"] = None,
        verifier: Optional["VerificationRunner"] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the Evaluation Manager.

        Args:
            workspace: Workspace path for persistence
            agent: FreyaAgent instance for context access
            decision_manager: DecisionManager for integration with decision system
            verifier: VerificationRunner for test/build/lint execution
            config: Optional configuration overrides
        """
        self.workspace = Path(workspace).resolve()
        self.agent = agent
        self.decision_manager = decision_manager
        self.verifier = verifier

        # Default configuration
        self.default_config = {
            "verify_requirements": True,
            "requirement_confidence_threshold": 0.6,
            "run_tests": True,
            "run_lint": True,
            "run_build": True,
            "run_execution": False,
            "confidence_thresholds": {
                "requirement_verification": 0.6,
                "functional_validation": 0.7,
                "overall": 0.65,
            },
            "fail_fast": False,
            "require_approval_below_confidence": 0.5,
            "store_results": True,
        }
        if config:
            self.default_config.update(config)

        # Core components
        self.pipeline = EvaluationPipeline(
            agent=agent,
            decision_manager=decision_manager,
            verifier=verifier,
            workspace=workspace,
        )
        self.history = EvaluationHistory(workspace)

        # Statistics
        self._stats = {
            "total_evaluations": 0,
            "delivered": 0,
            "rework_required": 0,
            "human_review_required": 0,
            "failed": 0,
        }

        logger.info(f"EvaluationManager initialized with workspace: {workspace}")

    def evaluate_task_completion(
        self,
        task_description: str,
        original_request: str,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        evaluation_type: EvaluationType = EvaluationType.COMPREHENSIVE,
        trigger: EvaluationTrigger = EvaluationTrigger.TASK_COMPLETION,
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Evaluate a completed task.

        This is the primary method for evaluating work after task completion.
        It runs requirement verification and functional validation.

        Args:
            task_description: Description of the task that was completed
            original_request: The original user request or objective
            task_id: Optional task identifier
            goal_id: Optional goal identifier
            plan_id: Optional plan identifier
            evaluation_type: Type of evaluation to run
            trigger: What triggered this evaluation
            custom_config: Optional configuration overrides

        Returns:
            EvaluationResult with verification, validation, and decision
        """
        # Build evaluation config
        config = EvaluationConfig(
            evaluation_type=evaluation_type,
            trigger=trigger,
            task_id=task_id,
            task_description=task_description,
            original_request=original_request,
            goal_id=goal_id,
            plan_id=plan_id,
            verify_requirements=self.default_config["verify_requirements"],
            requirement_confidence_threshold=self.default_config["requirement_confidence_threshold"],
            run_tests=self.default_config["run_tests"],
            run_lint=self.default_config["run_lint"],
            run_build=self.default_config["run_build"],
            run_execution=self.default_config["run_execution"],
            confidence_thresholds=self.default_config["confidence_thresholds"],
            fail_fast=self.default_config["fail_fast"],
            require_approval_below_confidence=self.default_config["require_approval_below_confidence"],
            store_results=self.default_config["store_results"],
        )

        # Apply custom config overrides
        if custom_config:
            for key, value in custom_config.items():
                if hasattr(config, key):
                    setattr(config, key, value)

        # Run evaluation
        logger.info(f"[EvaluationManager] Starting evaluation for task: {task_description[:50]}...")
        result = self.pipeline.run_evaluation(config)

        # Record in history
        if config.store_results:
            record = EvaluationRecord.from_result(result)
            self.history.add_record(record)

        # Update statistics
        self._stats["total_evaluations"] += 1
        if result.should_deliver:
            self._stats["delivered"] += 1
        if result.requires_rework:
            self._stats["rework_required"] += 1
        if result.requires_human_review:
            self._stats["human_review_required"] += 1
        if result.status == EvaluationStatus.FAILED:
            self._stats["failed"] += 1

        # Log result
        logger.info(
            f"[EvaluationManager] Evaluation complete: "
            f"confidence={result.overall_confidence:.0%} ({result.confidence_level.value}), "
            f"deliver={result.should_deliver}, rework={result.requires_rework}"
        )

        return result

    def evaluate_goal_completion(
        self,
        goal_id: str,
        goal_name: str,
        goal_description: str,
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Evaluate completion of a goal."""
        return self.evaluate_task_completion(
            task_description=f"Goal: {goal_name} - {goal_description}",
            original_request=goal_description,
            goal_id=goal_id,
            evaluation_type=EvaluationType.COMPREHENSIVE,
            trigger=EvaluationTrigger.GOAL_COMPLETION,
            custom_config=custom_config,
        )

    def evaluate_repair_completion(
        self,
        task_description: str,
        original_request: str,
        task_id: Optional[str] = None,
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Evaluate completion of a repair task."""
        return self.evaluate_task_completion(
            task_description=task_description,
            original_request=original_request,
            task_id=task_id,
            evaluation_type=EvaluationType.FUNCTIONAL_VALIDATION,
            trigger=EvaluationTrigger.REPAIR_COMPLETION,
            custom_config=custom_config,
        )

    def run_requirement_verification_only(
        self,
        original_request: str,
        work_output: str,
        work_context: Dict[str, Any],
        execution_history: List[Dict[str, Any]],
    ) -> List[RequirementVerification]:
        """Run only requirement verification (no functional validation)."""
        verifier = RequirementVerifier(agent=self.agent, decision_manager=self.decision_manager)
        requirements = verifier.extract_requirements(original_request=original_request)
        return verifier.verify_all(requirements, work_output, work_context, execution_history)

    def run_functional_validation_only(
        self,
        run_tests: bool = True,
        run_lint: bool = True,
        run_build: bool = True,
        custom_checks: Optional[List[ValidationCheck]] = None,
    ) -> List[ValidationResult]:
        """Run only functional validation."""
        config = EvaluationConfig(
            run_tests=run_tests,
            run_lint=run_lint,
            run_build=run_build,
            custom_validations=custom_checks or [],
        )
        checks = self.pipeline._get_validation_checks(config)
        return self.pipeline.validation_runner.run_validations(checks)

    def calculate_confidence(
        self,
        requirement_verifications: List[RequirementVerification],
        validation_results: List[ValidationResult],
    ) -> tuple[float, ConfidenceLevel, Dict[str, float]]:
        """Calculate confidence from verification and validation results."""
        # Requirement score
        if requirement_verifications:
            satisfied = sum(1 for v in requirement_verifications if v.is_satisfied)
            partial = sum(0.5 for v in requirement_verifications if v.status == VerificationStatus.PARTIALLY_SATISFIED)
            req_score = (satisfied + partial) / len(requirement_verifications)
        else:
            req_score = 0.5

        # Validation score
        if validation_results:
            passed = sum(1 for r in validation_results if r.passed)
            val_score = passed / len(validation_results)
        else:
            val_score = 0.5

        # Overall confidence
        overall = req_score * 0.4 + val_score * 0.6
        level = ConfidenceLevel.from_score(overall)

        breakdown = {
            "requirement_verification": req_score,
            "functional_validation": val_score,
            "overall": overall,
        }

        return overall, level, breakdown

    def should_deliver(
        self,
        overall_confidence: float,
        requirement_score: float,
        validation_score: float,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> tuple[bool, bool, List[str]]:
        """Determine if work should be delivered, needs rework, or needs human review."""
        t = thresholds or self.default_config["confidence_thresholds"]
        overall_t = t.get("overall", 0.65)
        req_t = t.get("requirement_verification", 0.6)
        val_t = t.get("functional_validation", 0.7)
        approval_t = self.default_config["require_approval_below_confidence"]

        meets_overall = overall_confidence >= overall_t
        meets_req = requirement_score >= req_t
        meets_val = validation_score >= val_t

        should_deliver = meets_overall and meets_req and meets_val
        requires_rework = not should_deliver
        requires_human_review = overall_confidence < approval_t

        reasons = []
        if not meets_req:
            reasons.append(f"Requirements not met (score: {requirement_score:.2f} < {req_t})")
        if not meets_val:
            reasons.append(f"Validations failed (score: {validation_score:.2f} < {val_t})")
        if not meets_overall:
            reasons.append(f"Overall confidence too low ({overall_confidence:.2f} < {overall_t})")

        return should_deliver, requires_rework, requires_human_review, reasons

    def get_history(
        self,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[EvaluationRecord]:
        """Get evaluation history."""
        return self.history.query(task_id=task_id, goal_id=goal_id, limit=limit)

    def get_latest_for_task(self, task_id: str) -> Optional[EvaluationRecord]:
        """Get the latest evaluation for a specific task."""
        records = self.history.query(task_id=task_id, limit=1)
        return records[0] if records else None

    def get_statistics(self) -> Dict[str, Any]:
        """Get evaluation statistics."""
        stats = self._stats.copy()
        stats["history"] = self.history.get_summary()
        return stats

    def explain_result(self, result: EvaluationResult) -> str:
        """Generate human-readable explanation of evaluation result."""
        lines = [
            f"Self-Evaluation Report",
            f"=" * 50,
            f"Evaluation ID: {result.evaluation_id}",
            f"Status: {result.status.value}",
            f"Duration: {result.duration_seconds:.1f}s",
            f"",
            f"CONFIDENCE SCORES:",
            f"  Overall: {result.overall_confidence:.0%} ({result.confidence_level.value})",
            f"  Requirement Verification: {result.requirement_score:.0%}",
            f"  Functional Validation: {result.validation_score:.0%}",
            f"",
        ]

        if result.requirement_verifications:
            lines.append(f"REQUIREMENT VERIFICATION:")
            for v in result.requirement_verifications:
                status_icon = "✅" if v.status == VerificationStatus.SATISFIED else \
                              "⚠️" if v.status == VerificationStatus.PARTIALLY_SATISFIED else "❌"
                lines.append(f"  {status_icon} {v.requirement_description[:80]}")
                if v.gaps:
                    for gap in v.gaps[:2]:
                        lines.append(f"     Gap: {gap}")

        if result.validation_results:
            lines.append(f"\nFUNCTIONAL VALIDATION:")
            for r in result.validation_results:
                status_icon = "✅" if r.passed else "❌"
                lines.append(f"  {status_icon} {r.check_name} ({r.check_type})")
                if not r.passed and r.stderr:
                    lines.append(f"     Error: {r.stderr[:100]}")

        lines.append(f"\nDECISION:")
        if result.should_deliver:
            lines.append(f"  ✅ DELIVER - Work meets all quality criteria")
        elif result.requires_human_review:
            lines.append(f"  ⚠️ HUMAN REVIEW REQUIRED - Confidence below threshold")
        else:
            lines.append(f"  ❌ REWORK NEEDED")
            for reason in result.rework_reasons:
                lines.append(f"     - {reason}")

        if result.summary:
            lines.append(f"\nSUMMARY:")
            lines.append(f"  {result.summary}")

        return "\n".join(lines)

    # ========================================================================
    # HIGH PRIORITY: Improvement Loop
    # ========================================================================

    def run_improvement_loop(
        self,
        task_description: str,
        original_request: str,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        max_iterations: int = 3,
        confidence_threshold: float = 0.75,
        improvement_config: Optional[Dict[str, Any]] = None,
    ) -> ImprovementLoopResult:
        """Run an automatic self-improvement loop.

        This method:
        1. Evaluates the current work
        2. If confidence is below threshold, attempts to improve
        3. Re-evaluates after improvement
        4. Repeats until threshold is met or max iterations reached

        Args:
            task_description: Description of the completed task
            original_request: Original user request
            task_id: Optional task ID
            goal_id: Optional goal ID
            plan_id: Optional plan ID
            max_iterations: Maximum number of improvement iterations (default 3)
            confidence_threshold: Minimum confidence to stop improving (default 0.75)
            improvement_config: Optional config for improvement behavior

        Returns:
            ImprovementLoopResult with all iterations and final outcome
        """
        import time
        loop_start = time.time()

        loop_result = ImprovementLoopResult(
            initial_confidence=0.0,
            final_confidence=0.0,
            stopped_reason="",
            total_duration_seconds=0.0,
            success=False,
        )

        current_task_desc = task_description
        current_request = original_request

        for iteration in range(max_iterations):
            iter_start = time.time()

            # Run evaluation
            eval_result = self.evaluate_task_completion(
                task_description=current_task_desc,
                original_request=current_request,
                task_id=task_id,
                goal_id=goal_id,
                plan_id=plan_id,
                evaluation_type=EvaluationType.COMPREHENSIVE,
                trigger=EvaluationTrigger.TASK_COMPLETION,
            )

            # Record first evaluation confidence
            if iteration == 0:
                loop_result.initial_confidence = eval_result.overall_confidence

            loop_result.final_confidence = eval_result.overall_confidence

            # Create iteration record
            improvements_made = []

            # Check if we meet quality threshold
            if eval_result.overall_confidence >= confidence_threshold:
                loop_result.iterations.append(ImprovementIteration(
                    iteration=iteration + 1,
                    evaluation_id=eval_result.evaluation_id,
                    overall_confidence=eval_result.overall_confidence,
                    issues_found=len(eval_result.rework_reasons),
                    issues_fixed=0,
                    improvements_made=[],
                    duration_seconds=time.time() - iter_start,
                    met_threshold=True,
                ))
                loop_result.stopped_reason = "threshold_met"
                loop_result.success = True
                break

            # Determine what improvements to make
            improvements_made = self._attempt_improvements(
                eval_result,
                improvement_config or {},
                agent=self.agent,
            )

            iter_duration = time.time() - iter_start

            loop_result.iterations.append(ImprovementIteration(
                iteration=iteration + 1,
                evaluation_id=eval_result.evaluation_id,
                overall_confidence=eval_result.overall_confidence,
                issues_found=len(eval_result.rework_reasons),
                issues_fixed=len(improvements_made),
                improvements_made=improvements_made,
                duration_seconds=iter_duration,
                met_threshold=False,
            ))

            loop_result.total_issues_fixed += len(improvements_made)
            loop_result.total_improvements += len(improvements_made)

            # If no improvements made, stop
            if not improvements_made:
                loop_result.stopped_reason = "no_improvement"
                break

            # Continue to next iteration
            if iteration == max_iterations - 1:
                loop_result.stopped_reason = "max_iterations"
            else:
                # Optionally update task description with improvements made
                if improvements_made:
                    current_task_desc += "\n\nImprovements made: " + "; ".join(improvements_made)

        loop_result.total_duration_seconds = time.time() - loop_start
        loop_result.success = loop_result.final_confidence >= confidence_threshold

        logger.info(
            f"[ImprovementLoop] Completed: {len(loop_result.iterations)} iterations, "
            f"initial={loop_result.initial_confidence:.0%}, "
            f"final={loop_result.final_confidence:.0%}, "
            f"reason={loop_result.stopped_reason}, "
            f"success={loop_result.success}"
        )

        # Store loop result in history
        record = EvaluationRecord.from_result(loop_result.iterations[-1].evaluation_id
            if loop_result.iterations else None
        ) if loop_result.iterations else None

        return loop_result

    def _attempt_improvements(
        self,
        eval_result: EvaluationResult,
        config: Dict[str, Any],
        agent: Optional["FreyaAgent"] = None,
    ) -> List[str]:
        """Attempt to fix issues found during evaluation.

        Returns:
            List of improvements made
        """
        improvements = []

        # Try to fix requirement issues
        if eval_result.requirement_score < self.default_config["confidence_thresholds"].get("requirement_verification", 0.6):
            if self._fix_requirement_gaps(eval_result, agent):
                improvements.append("Fixed requirement gaps")

        # Try to fix validation failures
        if eval_result.validation_score < self.default_config["confidence_thresholds"].get("functional_validation", 0.7):
            if self._fix_validation_failures(eval_result, agent):
                improvements.append("Fixed validation failures")

        # Try to fix regressions
        if eval_result.regression_results:
            if self._fix_regressions(eval_result, agent):
                improvements.append("Fixed regressions")

        # Try to fix quality issues
        if eval_result.quality_review and eval_result.quality_review.overall_score < 0.6:
            if self._fix_quality_issues(eval_result.quality_review, agent):
                improvements.append("Fixed code quality issues")

        # Try to fix documentation issues
        if eval_result.doc_check_results:
            failed_docs = [r for r in eval_result.doc_check_results if not r.passed]
            if failed_docs:
                if self._fix_documentation(failed_docs, agent):
                    improvements.append("Fixed documentation issues")

        return improvements

    def _fix_requirement_gaps(
        self,
        eval_result: EvaluationResult,
        agent: Optional["FreyaAgent"],
    ) -> bool:
        """Attempt to fix requirement verification gaps."""
        if not agent or not eval_result.requirement_verifications:
            return False

        # Find unsatisfied requirements
        unsatisfied = [v for v in eval_result.requirement_verifications if not v.is_satisfied]
        if not unsatisfied:
            return False

        # For now, just log that improvement would be needed
        # In a real implementation, this would trigger a repair loop
        logger.info(f"[ImprovementLoop] Would fix {len(unsatisfied)} requirement gaps")
        return False  # Return False to indicate no automatic fix applied

    def _fix_validation_failures(
        self,
        eval_result: EvaluationResult,
        agent: Optional["FreyaAgent"],
    ) -> bool:
        """Attempt to fix validation failures."""
        if not agent or not eval_result.validation_results:
            return False

        failed = [r for r in eval_result.validation_results if not r.passed]
        if not failed:
            return False

        logger.info(f"[ImprovementLoop] Would fix {len(failed)} validation failures")
        return False  # Would trigger repair in real implementation

    def _fix_regressions(
        self,
        eval_result: EvaluationResult,
        agent: Optional["FreyaAgent"],
    ) -> bool:
        """Attempt to fix detected regressions."""
        if not agent or not eval_result.regression_results:
            return False

        regressions = [r for r in eval_result.regression_results if r.has_regression]
        if not regressions:
            return False

        logger.info(f"[ImprovementLoop] Would fix {len(regressions)} regressions")
        return False

    def _fix_quality_issues(
        self,
        quality_review: QualityReview,
        agent: Optional["FreyaAgent"],
    ) -> bool:
        """Attempt to fix code quality issues."""
        if not agent or not quality_review:
            return False

        if quality_review.issue_count == 0:
            return False

        logger.info(f"[ImprovementLoop] Would fix {quality_review.issue_count} quality issues")
        return False

    def _fix_documentation(
        self,
        failed_docs: List[DocCheckResult],
        agent: Optional["FreyaAgent"],
    ) -> bool:
        """Attempt to fix documentation issues."""
        if not agent or not failed_docs:
            return False

        logger.info(f"[ImprovementLoop] Would fix {len(failed_docs)} documentation issues")
        return False


# Convenience function for easy access
_default_manager: Optional[EvaluationManager] = None
_manager_lock = threading.Lock()


def get_evaluation_manager(
    workspace: str = ".",
    agent: Optional["FreyaAgent"] = None,
    decision_manager: Optional["DecisionManager"] = None,
    verifier: Optional["VerificationRunner"] = None,
) -> EvaluationManager:
    """Get or create the default EvaluationManager instance."""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = EvaluationManager(
                workspace=workspace,
                agent=agent,
                decision_manager=decision_manager,
                verifier=verifier,
            )
        return _default_manager


def evaluate_before_delivery(
    agent: "FreyaAgent",
    task_description: str,
    original_request: str,
    task_id: Optional[str] = None,
    goal_id: Optional[str] = None,
    plan_id: Optional[str] = None,
) -> EvaluationResult:
    """Convenience function to run evaluation before delivering work.

    This should be called by FreyaAgent before declaring a task complete.

    Args:
        agent: FreyaAgent instance
        task_description: What was accomplished
        original_request: Original user request
        task_id: Optional task ID
        goal_id: Optional goal ID
        plan_id: Optional plan ID

    Returns:
        EvaluationResult - check .should_deliver before proceeding
    """
    manager = get_evaluation_manager(
        workspace=agent.workspace,
        agent=agent,
        decision_manager=agent.decision_manager,
        verifier=agent.verifier,
    )
    return manager.evaluate_task_completion(
        task_description=task_description,
        original_request=original_request,
        task_id=task_id,
        goal_id=goal_id,
        plan_id=plan_id,
    )