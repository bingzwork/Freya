"""Evaluation Pipeline - Orchestrates the evaluation process.

This module implements the evaluation pipeline that runs requirement verification,
functional validation, regression detection, code quality review, and documentation
verification in a structured manner.
"""

import hashlib
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
    RegressionType,
    QualityDimension,
    DocumentationCheck,
    ImprovementAction,
    RegressionCheck,
    RegressionResult,
    QualityReview,
    QualityIssue,
    DocCheckResult,
    ImprovementIteration,
    ImprovementLoopResult,
)
from app.core.logger import logger

if TYPE_CHECKING:
    from app.agent.core_agent import FreyaAgent
    from app.verification.runner import VerificationRunner
    from app.decision.manager import DecisionManager
    from app.diagnostics.diagnostic_engine import DiagnosticEngine
    from app.diagnostics.code_analyzer import CodeAnalyzer


# ============================================================================
# Requirement Verifier (EXISTING)
# ============================================================================

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
        for entry in execution_history[-5:]:
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
        import re

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
        return unique[:10]

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


# ============================================================================
# Validation Runner (EXISTING)
# ============================================================================

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


# ============================================================================
# HIGH PRIORITY: Regression Detection
# ============================================================================

class RegressionDetector:
    """Detects regressions by comparing pre/post task state."""

    def __init__(
        self,
        workspace: str = ".",
        verifier: Optional["VerificationRunner"] = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.verifier = verifier
        self._pre_test_results: Optional[Dict[str, Any]] = None
        self._pre_file_hashes: Dict[str, str] = {}

    def capture_pre_state(self) -> None:
        """Capture the state before task execution."""
        # Run tests to get baseline
        try:
            test_result = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=line"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=180,
            )
            self._pre_test_results = {
                "returncode": test_result.returncode,
                "stdout": test_result.stdout,
                "stderr": test_result.stderr,
                "passed": test_result.returncode == 0,
            }
        except Exception as e:
            logger.warning(f"[RegressionDetector] Failed to capture pre-test state: {e}")
            self._pre_test_results = {"returncode": -1, "passed": False, "error": str(e)}

        # Capture file hashes for changed files
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line and len(line) > 3:
                        filepath = line[3:].strip()
                        full_path = self.workspace / filepath
                        if full_path.exists() and full_path.is_file():
                            self._pre_file_hashes[filepath] = self._file_hash(full_path)
        except Exception as e:
            logger.warning(f"[RegressionDetector] Failed to capture file hashes: {e}")

    def _file_hash(self, filepath: Path) -> str:
        """Compute SHA256 hash of a file."""
        try:
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def detect_regressions(self, changed_files: Optional[List[str]] = None) -> List[RegressionResult]:
        """Detect regressions by comparing pre/post state."""
        regressions = []

        if self._pre_test_results is None:
            logger.warning("[RegressionDetector] No pre-state captured, skipping regression detection")
            return regressions

        # 1. Test regression detection
        try:
            post_test = subprocess.run(
                ["python", "-m", "pytest", "-q", "--tb=line"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=180,
            )
            post_passed = post_test.returncode == 0

            if self._pre_test_results.get("passed") and not post_passed:
                regressions.append(RegressionResult(
                    check_id=f"reg_test_{uuid.uuid4().hex[:8]}",
                    check_name="Test Suite Regression",
                    check_type="test",
                    has_regression=True,
                    regression_details=[
                        "Test suite passed before task but fails after",
                        f"Pre-test return code: {self._pre_test_results.get('returncode')}",
                        f"Post-test return code: {post_test.returncode}",
                    ],
                    pre_value=self._pre_test_results,
                    post_value={
                        "returncode": post_test.returncode,
                        "stdout": post_test.stdout,
                        "stderr": post_test.stderr,
                        "passed": post_passed,
                    },
                ))
        except Exception as e:
            logger.warning(f"[RegressionDetector] Test regression check failed: {e}")

        # 2. Build/Lint regression (syntax check)
        try:
            post_lint = subprocess.run(
                ["python", "-m", "py_compile", "app"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=60,
            )
            post_lint_passed = post_lint.returncode == 0

            if self._pre_test_results.get("passed") and not post_lint_passed:
                regressions.append(RegressionResult(
                    check_id=f"reg_lint_{uuid.uuid4().hex[:8]}",
                    check_name="Lint/Build Regression",
                    check_type="lint",
                    has_regression=True,
                    regression_details=[
                        "Code compiled before task but has syntax errors after",
                        f"Lint stderr: {post_lint.stderr[:200]}",
                    ],
                    pre_value={"passed": True},
                    post_value={"passed": post_lint_passed, "stderr": post_lint.stderr},
                ))
        except Exception as e:
            logger.warning(f"[RegressionDetector] Lint regression check failed: {e}")

        # 3. File-level regression (changed files that shouldn't have changed)
        if changed_files:
            unexpected_changes = [f for f in changed_files
                                  if f not in self._pre_file_hashes and not f.startswith("tests/")]
            if unexpected_changes:
                regressions.append(RegressionResult(
                    check_id=f"reg_files_{uuid.uuid4().hex[:8]}",
                    check_name="Unexpected File Changes",
                    check_type="file_changes",
                    has_regression=True,
                    regression_details=[
                        f"Files modified unexpectedly: {', '.join(unexpected_changes[:5])}",
                        "These files were not expected to change during this task",
                    ],
                    pre_value={"expected_files": list(self._pre_file_hashes.keys())},
                    post_value={"unexpected_changes": unexpected_changes},
                ))

        return regressions


# ============================================================================
# HIGH PRIORITY: Code Quality Review
# ============================================================================

class CodeQualityReviewer:
    """Reviews code quality using the existing diagnostics infrastructure."""

    def __init__(
        self,
        workspace: str = ".",
    ):
        self.workspace = Path(workspace).resolve()

    def review(self, changed_files: Optional[List[str]] = None) -> QualityReview:
        """Perform code quality review on the codebase or changed files."""
        from app.diagnostics.diagnostic_engine import DiagnosticEngine, DiagnosticConfig

        review = QualityReview()

        # Determine paths to analyze
        if changed_files:
            paths = [str(self.workspace / f) for f in changed_files if (self.workspace / f).exists()]
        else:
            paths = [str(self.workspace)]

        if not paths:
            review.summary = "No files to review"
            review.overall_score = 1.0
            return review

        # Run diagnostics
        config = DiagnosticConfig(
            paths=paths,
            include_patterns=["**/*.py"],
            exclude_patterns=["**/__pycache__/**", "**/.git/**", "**/.venv/**"],
            check_unused_imports=True,
            check_unreachable_code=True,
            check_empty_blocks=True,
            check_long_functions=True,
            check_complex_functions=True,
            check_missing_docstrings=True,
            check_missing_type_hints=True,
            check_bare_except=True,
            check_security=True,
            long_function_threshold=100,
            complex_function_threshold=10,
        )

        engine = DiagnosticEngine(str(self.workspace), config)
        issues = engine.run(paths)

        # Convert diagnostic issues to quality issues
        for issue in issues.filter_unresolved():
            # Map severity
            severity_map = {
                "critical": "critical",
                "error": "error",
                "warning": "warning",
                "info": "info",
            }
            # Map issue type to category
            category_map = {
                "bug": "security",
                "performance": "performance",
                "security": "security",
                "code_quality": "style",
                "architectural": "architecture",
                "deprecation": "maintainability",
                "test": "testing",
                "documentation": "documentation",
                "maintenance": "maintainability",
            }

            qi = QualityIssue(
                file_path=issue.file_path or "",
                line_number=issue.line_number,
                category=category_map.get(issue.issue_type.value, "style"),
                severity=severity_map.get(issue.severity.value, "warning"),
                title=issue.title,
                description=issue.description,
                suggestion=issue.fix_suggestion or "",
                confidence=0.8,
            )
            review.issues.append(qi)

        # Calculate scores
        if review.issues:
            severity_weights = {"critical": 0.3, "error": 0.2, "warning": 0.1, "info": 0.05}
            total_penalty = sum(severity_weights.get(i.severity, 0.1) for i in review.issues)
            review.overall_score = max(0.0, 1.0 - min(total_penalty, 1.0))

            # Category scores
            for cat in ["style", "complexity", "architecture", "security", "performance",
                        "maintainability", "documentation", "testing"]:
                cat_issues = [i for i in review.issues if i.category == cat]
                if cat_issues:
                    cat_penalty = sum(severity_weights.get(i.severity, 0.1) for i in cat_issues)
                    review.category_scores[cat] = max(0.0, 1.0 - min(cat_penalty, 1.0))
                else:
                    review.category_scores[cat] = 1.0
        else:
            review.overall_score = 1.0
            for cat in ["style", "complexity", "architecture", "security", "performance",
                        "maintainability", "documentation", "testing"]:
                review.category_scores[cat] = 1.0

        # Generate summary
        review.summary = self._generate_summary(review)
        return review

    def _generate_summary(self, review: QualityReview) -> str:
        if not review.issues:
            return "No quality issues found"

        lines = [f"Quality Review: {review.issue_count} issues found"]
        if review.critical_count:
            lines.append(f"  🔴 Critical: {review.critical_count}")
        if review.error_count:
            lines.append(f"  🟠 Errors: {review.error_count}")
        if review.warning_count:
            lines.append(f"  🟡 Warnings: {review.warning_count}")
        if review.info_count:
            lines.append(f"  🔵 Info: {review.info_count}")
        lines.append(f"  Overall Score: {review.overall_score:.0%}")
        return "\n".join(lines)


# ============================================================================
# HIGH PRIORITY: Documentation Verification
# ============================================================================

class DocumentationVerifier:
    """Verifies documentation matches implementation."""

    def __init__(
        self,
        workspace: str = ".",
    ):
        self.workspace = Path(workspace).resolve()

    def verify(self, changed_files: Optional[List[str]] = None) -> List[DocCheckResult]:
        """Run documentation verification checks."""
        results = []

        # Check 1: README exists
        results.append(self._check_readme())

        # Check 2: Implementation status matches code
        results.append(self._check_implementation_status())

        # Check 3: Roadmap status consistency
        results.append(self._check_roadmap())

        # Check 4: Self-evaluation status
        results.append(self._check_self_evaluation())

        # Check 5: Check inline docs for changed files
        if changed_files:
            results.append(self._check_inline_docs(changed_files))

        # Check 6: Type hints presence
        if changed_files:
            results.append(self._check_type_hints(changed_files))

        return results

    def _check_readme(self) -> DocCheckResult:
        readme_files = list(self.workspace.glob("README*")) + list(self.workspace.glob("readme*"))
        passed = len(readme_files) > 0

        return DocCheckResult(
            check_id=f"doc_readme_{uuid.uuid4().hex[:8]}",
            check_name="README Exists",
            check_type="readme",
            passed=passed,
            issues=[] if passed else ["No README file found in project root"],
            suggestions=["Add a README.md file with project overview"] if not passed else [],
            details=f"Found: {[f.name for f in readme_files]}",
        )

    def _check_implementation_status(self) -> DocCheckResult:
        status_file = self.workspace / "IMPLEMENTATION_STATUS.md"
        issues = []
        suggestions = []

        if not status_file.exists():
            return DocCheckResult(
                check_id=f"doc_impl_status_{uuid.uuid4().hex[:8]}",
                check_name="Implementation Status Document",
                check_type="implementation_status",
                passed=False,
                issues=["IMPLEMENTATION_STATUS.md not found"],
                suggestions=["Create IMPLEMENTATION_STATUS.md to track implementation status"],
                details="File not found",
            )

        content = status_file.read_text(encoding="utf-8", errors="ignore")

        # Check if it has recent date
        import re
        date_pattern = r"202\d-\d{2}-\d{2}"
        dates = re.findall(date_pattern, content)
        if not dates:
            issues.append("No recent dates found in IMPLEMENTATION_STATUS.md")

        # Check if Self-Evaluation section exists
        if "Self-Evaluation" not in content:
            issues.append("Missing Self-Evaluation section in IMPLEMENTATION_STATUS.md")
            suggestions.append("Add Self-Evaluation section to track evaluation status")

        passed = len(issues) == 0
        return DocCheckResult(
            check_id=f"doc_impl_status_{uuid.uuid4().hex[:8]}",
            check_name="Implementation Status Document",
            check_type="implementation_status",
            passed=passed,
            issues=issues,
            suggestions=suggestions,
            details=f"File exists, {len(dates)} dates found",
        )

    def _check_roadmap(self) -> DocCheckResult:
        roadmap_file = self.workspace / "ROADMAP.md"
        issues = []
        suggestions = []

        if not roadmap_file.exists():
            return DocCheckResult(
                check_id=f"doc_roadmap_{uuid.uuid4().hex[:8]}",
                check_name="Roadmap Document",
                check_type="roadmap",
                passed=False,
                issues=["ROADMAP.md not found"],
                suggestions=["Create ROADMAP.md to track project roadmap"],
                details="File not found",
            )

        content = roadmap_file.read_text(encoding="utf-8", errors="ignore")

        # Check if it has Self-Evaluation section
        if "Self-Evaluation" not in content:
            issues.append("Missing Self-Evaluation section in ROADMAP.md")
            suggestions.append("Add Self-Evaluation section to track evaluation roadmap progress")

        passed = len(issues) == 0
        return DocCheckResult(
            check_id=f"doc_roadmap_{uuid.uuid4().hex[:8]}",
            check_name="Roadmap Document",
            check_type="roadmap",
            passed=passed,
            issues=issues,
            suggestions=suggestions,
            details="File exists" + ("" if passed else ", missing sections"),
        )

    def _check_self_evaluation(self) -> DocCheckResult:
        se_file = self.workspace / "SELF_EVALUATION.md"
        issues = []
        suggestions = []

        if not se_file.exists():
            return DocCheckResult(
                check_id=f"doc_self_eval_{uuid.uuid4().hex[:8]}",
                check_name="Self-Evaluation Document",
                check_type="self_evaluation",
                passed=False,
                issues=["SELF_EVALUATION.md not found"],
                suggestions=["Create SELF_EVALUATION.md to document evaluation capabilities"],
                details="File not found",
            )

        content = se_file.read_text(encoding="utf-8", errors="ignore")

        # Check if it has High Priority items mentioned
        if "High Priority" not in content and "⭐⭐⭐⭐" not in content:
            issues.append("SELF_EVALUATION.md missing High Priority section")
            suggestions.append("Add High Priority capabilities section to SELF_EVALUATION.md")

        passed = len(issues) == 0
        return DocCheckResult(
            check_id=f"doc_self_eval_{uuid.uuid4().hex[:8]}",
            check_name="Self-Evaluation Document",
            check_type="self_evaluation",
            passed=passed,
            issues=issues,
            suggestions=suggestions,
            details="File exists" + ("" if passed else ", missing sections"),
        )

    def _check_inline_docs(self, changed_files: List[str]) -> DocCheckResult:
        issues = []
        suggestions = []
        missing_docs = 0
        total_functions = 0

        for filepath in changed_files:
            full_path = self.workspace / filepath
            if not full_path.exists() or full_path.suffix != ".py":
                continue

            try:
                import ast
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name.startswith("_"):
                            continue
                        total_functions += 1
                        if not ast.get_docstring(node):
                            missing_docs += 1
                            issues.append(f"Missing docstring: {filepath}:{node.name} (line {node.lineno})")
            except Exception:
                pass

        if missing_docs > 0:
            suggestions.append(f"Add docstrings to {missing_docs} public functions/classes")

        passed = missing_docs == 0
        return DocCheckResult(
            check_id=f"doc_inline_{uuid.uuid4().hex[:8]}",
            check_name="Inline Documentation",
            check_type="inline_docs",
            passed=passed,
            issues=issues[:10],
            suggestions=suggestions,
            details=f"Checked {total_functions} public functions/classes, {missing_docs} missing docstrings",
        )

    def _check_type_hints(self, changed_files: List[str]) -> DocCheckResult:
        issues = []
        suggestions = []
        missing_hints = 0
        total_functions = 0

        for filepath in changed_files:
            full_path = self.workspace / filepath
            if not full_path.exists() or full_path.suffix != ".py":
                continue

            try:
                import ast
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name.startswith("_"):
                            continue
                        total_functions += 1
                        if not node.returns:
                            missing_hints += 1
                            issues.append(f"Missing return type hint: {filepath}:{node.name} (line {node.lineno})")
            except Exception:
                pass

        if missing_hints > 0:
            suggestions.append(f"Add return type hints to {missing_hints} functions")

        passed = missing_hints == 0
        return DocCheckResult(
            check_id=f"doc_type_hints_{uuid.uuid4().hex[:8]}",
            check_name="Type Hints",
            check_type="type_hints",
            passed=passed,
            issues=issues[:10],
            suggestions=suggestions,
            details=f"Checked {total_functions} public functions, {missing_hints} missing return type hints",
        )


# ============================================================================
# EvaluationPipeline
# ============================================================================

class EvaluationPipeline:
    """Main evaluation pipeline orchestrating all verification and validation."""

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
        self.regression_detector = RegressionDetector(workspace=workspace, verifier=verifier)
        self.quality_reviewer = CodeQualityReviewer(workspace=workspace)
        self.doc_verifier = DocumentationVerifier(workspace=workspace)

    def run_evaluation(self, config: EvaluationConfig) -> EvaluationResult:
        """Run a complete evaluation based on configuration."""
        start_time = time.time()

        result = EvaluationResult(
            config=config,
            status=EvaluationStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Capture changed files for regression detection
        changed_files = self._get_changed_files()

        try:
            # Gather work context
            work_output, work_context, execution_history = self._gather_work_context(config)
            work_context["changed_files"] = changed_files

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

            # Phase 3: Regression Detection (if enabled)
            if config.evaluation_type in (EvaluationType.COMPREHENSIVE, EvaluationType.REGRESSION_DETECTION):
                logger.info("[Evaluation] Phase 3: Regression Detection")
                self.regression_detector.capture_pre_state()
                # Note: In practice, we'd run this AFTER the task completes.
                # For now, we capture pre-state and can compare if we have post-state
                result.regression_results = self.regression_detector.detect_regressions(changed_files)

            # Phase 4: Code Quality Review (if enabled)
            if config.evaluation_type in (EvaluationType.COMPREHENSIVE, EvaluationType.CODE_QUALITY_REVIEW):
                logger.info("[Evaluation] Phase 4: Code Quality Review")
                result.quality_review = self.quality_reviewer.review(changed_files)

            # Phase 5: Documentation Verification (if enabled)
            if config.evaluation_type in (EvaluationType.COMPREHENSIVE, EvaluationType.DOCUMENTATION_VERIFICATION):
                logger.info("[Evaluation] Phase 5: Documentation Verification")
                result.doc_check_results = self.doc_verifier.verify(changed_files)

            # Phase 6: Calculate Scores and Confidence
            logger.info("[Evaluation] Phase 6: Confidence Scoring")
            self._calculate_scores(result, config)

            # Phase 7: Make Decision
            logger.info("[Evaluation] Phase 7: Decision")
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

    def _get_changed_files(self) -> List[str]:
        """Get list of changed files from git."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
            )
            changed = []
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line and len(line) > 3:
                        changed.append(line[3:].strip())
            return changed
        except Exception:
            return []

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

        # Regression score
        regression_penalty = 0.0
        if result.regression_results:
            regressions = sum(1 for r in result.regression_results if r.has_regression)
            if regressions > 0:
                regression_penalty = min(0.3 * regressions, 0.5)

        # Quality score
        quality_score = 1.0
        if result.quality_review:
            quality_score = result.quality_review.overall_score

        # Documentation score
        doc_score = 1.0
        if result.doc_check_results:
            passed = sum(1 for r in result.doc_check_results if r.passed)
            total = len(result.doc_check_results)
            if total > 0:
                doc_score = passed / total

        # Confidence breakdown
        result.confidence_breakdown = {
            "requirement_verification": result.requirement_score,
            "functional_validation": result.validation_score,
            "regression_detection": 1.0 - regression_penalty,
            "code_quality": quality_score,
            "documentation": doc_score,
        }

        # Overall confidence (weighted average)
        weights = {
            "requirement_verification": 0.3,
            "functional_validation": 0.3,
            "regression_detection": 0.1,
            "code_quality": 0.15,
            "documentation": 0.15,
        }
        result.overall_confidence = sum(
            result.confidence_breakdown.get(k, 0.5) * w for k, w in weights.items()
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

        # Check for regressions
        if result.regression_results:
            regressions = [r for r in result.regression_results if r.has_regression]
            if regressions:
                result.requires_rework = True
                result.rework_reasons.append(f"Regressions detected: {len(regressions)} issue(s)")

        # Check quality
        if result.quality_review and result.quality_review.overall_score < 0.6:
            result.requires_rework = True
            result.rework_reasons.append(f"Code quality score too low ({result.quality_review.overall_score:.0%})")

        # Check documentation
        if result.doc_check_results:
            failed_docs = [r for r in result.doc_check_results if not r.passed]
            if failed_docs:
                result.rework_reasons.append(f"Documentation issues: {len(failed_docs)} check(s) failed")

        # Generate summary
        result.summary = self._generate_summary(result)

    def _generate_summary(self, result: EvaluationResult) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Evaluation {result.evaluation_id} completed in {result.duration_seconds:.1f}s",
            f"Overall Confidence: {result.overall_confidence:.0%} ({result.confidence_level.value})",
            f"  Requirement Verification: {result.requirement_score:.0%}",
            f"  Functional Validation: {result.validation_score:.0%}",
        ]

        if "regression_detection" in result.confidence_breakdown:
            lines.append(f"  Regression Detection: {result.confidence_breakdown['regression_detection']:.0%}")
        if "code_quality" in result.confidence_breakdown:
            lines.append(f"  Code Quality: {result.confidence_breakdown['code_quality']:.0%}")
        if "documentation" in result.confidence_breakdown:
            lines.append(f"  Documentation: {result.confidence_breakdown['documentation']:.0%}")

        lines.append("")

        if result.requirement_verifications:
            satisfied = result.requirements_satisfied_count
            total = result.requirements_total_count
            lines.append(f"Requirements: {satisfied}/{total} satisfied")

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

        if result.regression_results:
            regressions = [r for r in result.regression_results if r.has_regression]
            if regressions:
                lines.append(f"\n⚠️ REGRESSIONS DETECTED: {len(regressions)}")
                for r in regressions:
                    lines.append(f"  - {r.check_name}: {', '.join(r.regression_details[:2])}")

        if result.quality_review:
            lines.append(f"\nCode Quality: {result.quality_review.overall_score:.0%} - {result.quality_review.issue_count} issues")
            if result.quality_review.critical_count:
                lines.append(f"  🔴 Critical: {result.quality_review.critical_count}")
            if result.quality_review.error_count:
                lines.append(f"  🟠 Errors: {result.quality_review.error_count}")

        if result.doc_check_results:
            passed = sum(1 for r in result.doc_check_results if r.passed)
            total = len(result.doc_check_results)
            lines.append(f"\nDocumentation: {passed}/{total} checks passed")
            for r in result.doc_check_results:
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


# ============================================================================
# Convenience function
# ============================================================================

def run_quick_evaluation(
    workspace: str = ".",
    task_description: str = "",
    original_request: str = "",
) -> EvaluationResult:
    """Run a quick evaluation for completed work."""
    pipeline = EvaluationPipeline(workspace=workspace)
    config = EvaluationConfig(
        evaluation_type=EvaluationType.COMPREHENSIVE,
        trigger=EvaluationTrigger.TASK_COMPLETION,
        task_description=task_description,
        original_request=original_request,
    )
    return pipeline.run_evaluation(config)