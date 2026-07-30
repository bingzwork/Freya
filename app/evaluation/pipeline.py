"""Evaluation Pipeline - Orchestrates the evaluation process.

This module implements the evaluation pipeline that runs requirement verification
and functional validation in a structured manner.
"""

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import uuid

from app.evaluation.models import (
    EvaluationConfig,
    EvaluationResult,
    EvaluationStatus,
    EvaluationType,
    Requirement,
    RequirementVerification,
    ValidationCheck,
    ValidationResult,
    ValidationStatus,
    VerificationStatus,
    ConfidenceLevel,
)
from app.core.logger import logger

if TYPE_CHECKING:
    from app.agent.core_agent import FreyaAgent
    from app.verification.runner import VerificationRunner, VerificationResult
    from app.decision.manager import DecisionManager
    from app.confidence.confidence_scoring import ConfidenceCalculator


class RequirementVerifier:
    """Verifies completed work against original requirements."""

    def __init__(
        self,
        agent: Optional["FreyaAgent"] = None,
        decision_manager: Optional["DecisionManager"] = None,
        llm: Optional[Any] = None,
    ):
        self.agent = agent
        self.decision_manager = decision_manager
        self.llm = llm or (agent.llm if agent else None)

    def extract_requirements(
        self,
        original_request: str,
        task_description: str = "",
        goal_description: str = "",
        plan_steps: Optional[List[str]] = None,
    ) -> List[Requirement]:
        """Extract requirements from the original request and context."""
        requirements = []

        # Parse original request for explicit requirements
        reqs_from_request = self._parse_requirements_from_text(original_request, "user_request")
        requirements.extend(reqs_from_request)

        # Parse task description
        if task_description and task_description != original_request:
            reqs_from_task = self._parse_requirements_from_text(task_description, "task_description")
            requirements.extend(reqs_from_task)

        # Parse goal description
        if goal_description:
            reqs_from_goal = self._parse_requirements_from_text(goal_description, "goal")
            requirements.extend(reqs_from_goal)

        # Parse plan steps as implicit requirements
        if plan_steps:
            for i, step in enumerate(plan_steps):
                req = Requirement(
                    id=f"plan_step_{i}",
                    description=f"Execute plan step: {step}",
                    source="plan",
                    category="functional",
                    priority="high",
                    acceptance_criteria=[f"Step completed: {step}"],
                )
                requirements.append(req)

        # If no explicit requirements found, create a general one
        if not requirements:
            requirements.append(Requirement(
                id="general_completion",
                description=f"Complete the task: {original_request or task_description}",
                source="user_request",
                category="functional",
                priority="high",
                acceptance_criteria=["Task objectives achieved"],
            ))

        return requirements

    def _parse_requirements_from_text(self, text: str, source: str) -> List[Requirement]:
        """Parse requirements from natural language text."""
        requirements = []

        # Simple heuristic: look for bullet points, numbered lists, or imperative sentences
        lines = text.strip().split("\n")
        current_req = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check for bullet/numbered list items
            if stripped.startswith(("- ", "* ", "• ")) or \
               (len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in (".", ")", ":")):
                if current_req:
                    requirements.append(current_req)
                current_req = Requirement(
                    description=stripped.lstrip("- *•0123456789.): "),
                    source=source,
                    category="functional",
                    priority="high",
                )
            elif stripped.lower().startswith(("must ", "should ", "need to ", "require ", "ensure ")):
                if current_req:
                    requirements.append(current_req)
                current_req = Requirement(
                    description=stripped,
                    source=source,
                    category="functional",
                    priority="high",
                )
            elif current_req and (stripped.startswith("  ") or stripped.startswith("\t")):
                # Continuation of previous requirement
                current_req.acceptance_criteria.append(stripped)
            else:
                # Could be a new requirement or just context
                if current_req:
                    requirements.append(current_req)
                current_req = Requirement(
                    description=stripped,
                    source=source,
                    category="functional",
                    priority="medium",
                )

        if current_req:
            requirements.append(current_req)

        return requirements

    def verify_requirement(
        self,
        requirement: Requirement,
        work_output: str,
        work_context: Dict[str, Any],
        execution_history: List[Dict[str, Any]],
    ) -> RequirementVerification:
        """Verify a single requirement against completed work."""
        # Build context for verification
        context = self._build_verification_context(work_output, work_context, execution_history)

        # Use LLM to verify if available
        if self.llm:
            return self._verify_with_llm(requirement, context)

        # Fallback: simple keyword matching
        return self._verify_heuristic(requirement, context)

    def _build_verification_context(
        self,
        work_output: str,
        work_context: Dict[str, Any],
        execution_history: List[Dict[str, Any]],
    ) -> str:
        """Build context string for verification."""
        parts = []
        parts.append("WORK OUTPUT:")
        parts.append(work_output[:3000])

        parts.append("\n\nWORK CONTEXT:")
        for key, value in work_context.items():
            if isinstance(value, (str, int, float, bool)):
                parts.append(f"  {key}: {value}")

        parts.append("\n\nEXECUTION HISTORY:")
        for entry in execution_history[-5:]:  # Last 5 iterations
            if isinstance(entry, dict):
                parts.append(f"  Iteration {entry.get('iteration', '?')}: {entry.get('summary', 'No summary')[:200]}")

        return "\n".join(parts)

    def _verify_with_llm(
        self,
        requirement: Requirement,
        context: str,
    ) -> RequirementVerification:
        """Use LLM to verify requirement."""
        prompt = f"""You are evaluating whether a requirement has been satisfied.

REQUIREMENT:
- ID: {requirement.id}
- Description: {requirement.description}
- Source: {requirement.source}
- Category: {requirement.category}
- Priority: {requirement.priority}
- Acceptance Criteria: {requirement.acceptance_criteria or ["None specified"]}

COMPLETED WORK CONTEXT:
{context}

Evaluate whether this requirement is SATISFIED, PARTIALLY_SATISFIED, or NOT_SATISFIED.
Consider the evidence in the work output and execution history.

Respond with JSON only:
{{
  "status": "SATISFIED|PARTIALLY_SATISFIED|NOT_SATISFIED|CANNOT_VERIFY",
  "evidence": ["specific evidence from the work that satisfies the requirement"],
  "gaps": ["what is missing or not adequately addressed"],
  "confidence": 0.0-1.0,
  "notes": "brief explanation"
}}"""

        try:
            response = self.llm.ask(prompt)
            # Extract JSON from response
            import json
            import re

            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return RequirementVerification(
                    requirement_id=requirement.id,
                    requirement_description=requirement.description,
                    status=VerificationStatus(data.get("status", "CANNOT_VERIFY")),
                    evidence=data.get("evidence", []),
                    gaps=data.get("gaps", []),
                    confidence=float(data.get("confidence", 0.5)),
                    notes=data.get("notes", ""),
                )
        except Exception as e:
            logger.warning(f"LLM verification failed: {e}")

        return self._verify_heuristic(requirement, context)

    def _verify_heuristic(
        self,
        requirement: Requirement,
        context: str,
    ) -> RequirementVerification:
        """Heuristic verification using keyword matching."""
        context_lower = context.lower()
        req_lower = requirement.description.lower()

        # Extract key terms from requirement
        key_terms = self._extract_key_terms(req_lower)

        # Count matches
        matches = sum(1 for term in key_terms if term in context_lower)
        coverage = matches / max(len(key_terms), 1)

        # Determine status
        if coverage >= 0.8:
            status = VerificationStatus.SATISFIED
            confidence = 0.7 + coverage * 0.3
        elif coverage >= 0.4:
            status = VerificationStatus.PARTIALLY_SATISFIED
            confidence = 0.4 + coverage * 0.3
        else:
            status = VerificationStatus.NOT_SATISFIED
            confidence = coverage * 0.5

        # Evidence and gaps
        evidence = [term for term in key_terms if term in context_lower]
        gaps = [term for term in key_terms if term not in context_lower][:3]

        return RequirementVerification(
            requirement_id=requirement.id,
            requirement_description=requirement.description,
            status=status,
            evidence=evidence,
            gaps=gaps,
            confidence=confidence,
            notes=f"Heuristic verification: {coverage:.0%} key term coverage",
        )

    def _extract_key_terms(self, text: str) -> List[str]:
        """Extract key terms from requirement text."""
        # Simple extraction: nouns, verbs, technical terms
        import re

        # Remove common words
        stop_words = {"the", "a", "an", "and", "or", "but", "to", "for", "in", "on", "of", "with",
                      "should", "must", "need", "require", "ensure", "that", "this", "is", "be"}
        words = re.findall(r"\b\w+\b", text.lower())
        key_terms = [w for w in words if w not in stop_words and len(w) > 2]
        # Deduplicate preserving order
        seen = set()
        unique = []
        for term in key_terms:
            if term not in seen:
                seen.add(term)
                unique.append(term)
        return unique[:10]  # Limit to top 10

    def verify_all(
        self,
        requirements: List[Requirement],
        work_output: str,
        work_context: Dict[str, Any],
        execution_history: List[Dict[str, Any]],
    ) -> List[RequirementVerification]:
        """Verify all requirements."""
        results = []
        for req in requirements:
            verification = self.verify_requirement(req, work_output, work_context, execution_history)
            results.append(verification)
        return results


class ValidationRunner:
    """Runs functional validation checks (tests, build, lint, etc.)."""

    def __init__(
        self,
        workspace: str = ".",
        verifier: Optional["VerificationRunner"] = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.verifier = verifier

    def get_default_validations(self) -> List[ValidationCheck]:
        """Get default validation checks for the project."""
        checks = []

        # Python lint check
        checks.append(ValidationCheck(
            name="python_lint",
            type="lint",
            command=["python", "-m", "py_compile", "app"],
            working_directory=str(self.workspace),
        ))

        # Run tests
        checks.append(ValidationCheck(
            name="pytest",
            type="test",
            command=["python", "-m", "pytest", "-q", "--tb=short"],
            working_directory=str(self.workspace),
            timeout_seconds=180,
        ))

        # Check for syntax errors in changed files (if git available)
        checks.append(ValidationCheck(
            name="git_diff_syntax",
            type="static_analysis",
            command=["git", "diff", "--name-only"],
            working_directory=str(self.workspace),
        ))

        return checks

    def run_validation(self, check: ValidationCheck) -> ValidationResult:
        """Run a single validation check."""
        start_time = time.time()

        try:
            result = subprocess.run(
                check.command,
                cwd=check.working_directory,
                capture_output=True,
                text=True,
                timeout=check.timeout_seconds,
                shell=False,
            )

            duration = time.time() - start_time

            passed = result.returncode == 0
            status = ValidationStatus.PASSED if passed else ValidationStatus.FAILED

            return ValidationResult(
                check_id=check.id,
                check_name=check.name,
                check_type=check.type,
                status=status,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration_seconds=duration,
                passed=passed,
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                check_id=check.id,
                check_name=check.name,
                check_type=check.type,
                status=ValidationStatus.ERROR,
                stderr=f"Validation timed out after {check.timeout_seconds} seconds",
                return_code=-1,
                duration_seconds=check.timeout_seconds,
                passed=False,
            )
        except Exception as e:
            return ValidationResult(
                check_id=check.id,
                check_name=check.name,
                check_type=check.type,
                status=ValidationStatus.ERROR,
                stderr=str(e),
                return_code=-1,
                duration_seconds=time.time() - start_time,
                passed=False,
            )

    def run_validations(self, checks: List[ValidationCheck]) -> List[ValidationResult]:
        """Run multiple validation checks."""
        results = []
        for check in checks:
            logger.info(f"[Evaluation] Running validation: {check.name} ({check.type})")
            result = self.run_validation(check)
            results.append(result)
            logger.info(f"[Evaluation] Validation {check.name}: {result.status.value}")
        return results


class EvaluationPipeline:
    """Main evaluation pipeline orchestrating verification and validation."""

    def __init__(
        self,
        agent: Optional["FreyaAgent"] = None,
        decision_manager: Optional["DecisionManager"] = None,
        verifier: Optional["VerificationRunner"] = None,
        workspace: str = ".",
    ):
        self.agent = agent
        self.decision_manager = decision_manager
        self.workspace = workspace

        self.requirement_verifier = RequirementVerifier(agent=agent, decision_manager=decision_manager)
        self.validation_runner = ValidationRunner(workspace=workspace, verifier=verifier)

    def run_evaluation(self, config: EvaluationConfig) -> EvaluationResult:
        """Run a complete evaluation based on configuration."""
        start_time = time.time()

        result = EvaluationResult(
            config=config,
            status=EvaluationStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Gather work context
            work_output, work_context, execution_history = self._gather_work_context(config)

            # Phase 1: Requirement Verification
            if config.verify_requirements:
                logger.info("[Evaluation] Phase 1: Requirement Verification")
                result.requirements = self.requirement_verifier.extract_requirements(
                    original_request=config.original_request,
                    task_description=config.task_description,
                    goal_description=work_context.get("goal_description", ""),
                    plan_steps=work_context.get("plan_steps", []),
                )
                result.requirement_verifications = self.requirement_verifier.verify_all(
                    requirements=result.requirements,
                    work_output=work_output,
                    work_context=work_context,
                    execution_history=execution_history,
                )

            # Phase 2: Functional Validation
            logger.info("[Evaluation] Phase 2: Functional Validation")
            validation_checks = self._get_validation_checks(config)
            result.validation_checks = validation_checks
            result.validation_results = self.validation_runner.run_validations(validation_checks)

            # Phase 3: Calculate Scores and Confidence
            logger.info("[Evaluation] Phase 3: Confidence Scoring")
            self._calculate_scores(result, config)

            # Phase 4: Make Decision
            logger.info("[Evaluation] Phase 4: Decision")
            self._make_decision(result, config)

            result.status = EvaluationStatus.COMPLETED

        except Exception as e:
            logger.error(f"[Evaluation] Evaluation failed: {e}")
            result.status = EvaluationStatus.FAILED
            result.summary = f"Evaluation failed: {e}"
            result.requires_rework = True
            result.rework_reasons = [f"Evaluation error: {e}"]

        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = time.time() - start_time

        return result

    def _gather_work_context(self, config: EvaluationConfig) -> tuple:
        """Gather context about the completed work."""
        work_output = ""
        work_context = {}
        execution_history = []

        if self.agent:
            # Get conversation history
            work_output = self.agent.conversation.get_history_text()

            # Get last execution progress
            progress = self.agent.get_last_execution_progress()
            if progress:
                work_context["execution_progress"] = progress

            # Get plan info
            if config.plan_id:
                plan = self.agent.plan_manager.load_plan(config.plan_id)
                if plan and hasattr(plan, 'tasks'):
                    work_context["plan_steps"] = [t.title for t in plan.tasks]

            # Get goal info
            if config.goal_id:
                goal = self.agent.goal_storage.load(config.goal_id)
                if goal:
                    work_context["goal_description"] = goal.description

        return work_output, work_context, execution_history

    def _get_validation_checks(self, config: EvaluationConfig) -> List[ValidationCheck]:
        """Get validation checks to run based on config."""
        checks = []

        if config.run_tests or config.run_lint:
            default_checks = self.validation_runner.get_default_validations()
            if config.run_lint:
                checks.extend([c for c in default_checks if c.type == "lint"])
            if config.run_tests:
                checks.extend([c for c in default_checks if c.type == "test"])
            # Add others
            checks.extend([c for c in default_checks if c.type not in ("lint", "test")])

        # Add custom validations
        checks.extend(config.custom_validations)

        return checks

    def _calculate_scores(self, result: EvaluationResult, config: EvaluationConfig) -> None:
        """Calculate requirement score, validation score, and overall confidence."""
        # Requirement score
        if result.requirement_verifications:
            satisfied_weight = sum(1.0 for v in result.requirement_verifications if v.status == VerificationStatus.SATISFIED)
            partial_weight = sum(0.5 for v in result.requirement_verifications if v.status == VerificationStatus.PARTIALLY_SATISFIED)
            result.requirement_score = (satisfied_weight + partial_weight) / len(result.requirement_verifications)
        else:
            result.requirement_score = 0.5  # Neutral if no requirements

        # Validation score
        if result.validation_results:
            passed = sum(1 for r in result.validation_results if r.passed)
            result.validation_score = passed / len(result.validation_results)
        else:
            result.validation_score = 0.5  # Neutral if no validations

        # Confidence breakdown
        result.confidence_breakdown = {
            "requirement_verification": result.requirement_score,
            "functional_validation": result.validation_score,
        }

        # Overall confidence (weighted average)
        req_weight = 0.4
        val_weight = 0.6
        result.overall_confidence = (
            result.requirement_score * req_weight +
            result.validation_score * val_weight
        )
        result.confidence_level = ConfidenceLevel.from_score(result.overall_confidence)

        # Update breakdown with overall
        result.confidence_breakdown["overall"] = result.overall_confidence

    def _make_decision(self, result: EvaluationResult, config: EvaluationConfig) -> None:
        """Make delivery decision based on scores and thresholds."""
        overall_threshold = config.confidence_thresholds.get("overall", 0.65)
        req_threshold = config.confidence_thresholds.get("requirement_verification", 0.6)
        val_threshold = config.confidence_thresholds.get("functional_validation", 0.7)
        approval_threshold = config.require_approval_below_confidence

        # Check if we meet all thresholds
        meets_overall = result.overall_confidence >= overall_threshold
        meets_requirements = result.requirement_score >= req_threshold
        meets_validations = result.validation_score >= val_threshold

        # Determine if we should deliver
        result.should_deliver = meets_overall and meets_requirements and meets_validations

        # Check if human review is required
        result.requires_human_review = result.overall_confidence < approval_threshold

        # Check if rework is needed
        if not result.should_deliver:
            result.requires_rework = True
            if not meets_requirements:
                result.rework_reasons.append(f"Requirements not met (score: {result.requirement_score:.2f} < {req_threshold})")
            if not meets_validations:
                result.rework_reasons.append(f"Validations failed (score: {result.validation_score:.2f} < {val_threshold})")
            if not meets_overall:
                result.rework_reasons.append(f"Overall confidence too low ({result.overall_confidence:.2f} < {overall_threshold})")

        # Generate summary
        result.summary = self._generate_summary(result)

    def _generate_summary(self, result: EvaluationResult) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Evaluation {result.evaluation_id} completed in {result.duration_seconds:.1f}s",
            f"Overall Confidence: {result.overall_confidence:.0%} ({result.confidence_level.value})",
            f"  Requirement Verification: {result.requirement_score:.0%}",
            f"  Functional Validation: {result.validation_score:.0%}",
            "",
        ]

        if result.requirement_verifications:
            satisfied = result.requirements_satisfied_count
            total = result.requirements_total_count
            lines.append(f"Requirements: {satisfied}/{total} satisfied")

            # Show unsatisfied
            for v in result.requirement_verifications:
                if not v.is_satisfied:
                    lines.append(f"  - MISSING: {v.requirement_description}")
                    for gap in v.gaps[:2]:
                        lines.append(f"    Gap: {gap}")

        if result.validation_results:
            passed = result.validations_passed_count
            total = result.validations_total_count
            lines.append(f"Validations: {passed}/{total} passed")

            for r in result.validation_results:
                if not r.passed:
                    lines.append(f"  - FAILED: {r.check_name} ({r.check_type})")

        lines.append("")
        if result.should_deliver:
            lines.append("✅ RECOMMENDATION: DELIVER - All criteria met")
        elif result.requires_human_review:
            lines.append("⚠️ RECOMMENDATION: HUMAN REVIEW REQUIRED - Low confidence")
        else:
            lines.append("❌ RECOMMENDATION: REWORK NEEDED")
            for reason in result.rework_reasons:
                lines.append(f"  - {reason}")

        return "\n".join(lines)