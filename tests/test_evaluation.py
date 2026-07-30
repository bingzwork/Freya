"""Tests for the Self-Evaluation System."""

import tempfile
from pathlib import Path

import pytest

from app.evaluation.manager import (
    EvaluationManager,
    EvaluationRecord,
    EvaluationHistory,
    get_evaluation_manager,
    evaluate_before_delivery,
)
from app.evaluation.models import (
    EvaluationType,
    EvaluationStatus,
    EvaluationTrigger,
    VerificationStatus,
    ValidationStatus,
    ConfidenceLevel,
    Requirement,
    RequirementVerification,
    ValidationCheck,
    ValidationResult,
    EvaluationConfig,
    EvaluationResult,
    RegressionCheck,
    RegressionResult,
    QualityReview,
    QualityIssue,
    DocCheck,
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


class TestEvaluationModels:
    """Tests for evaluation data models."""

    def test_requirement_creation(self):
        """Test creating a Requirement."""
        req = Requirement(
            description="Implement user authentication",
            source="user_request",
            category="functional",
            priority="high",
            acceptance_criteria=["Users can log in", "Users can register"],
        )
        assert req.description == "Implement user authentication"
        assert req.source == "user_request"
        assert req.category == "functional"
        assert req.priority == "high"
        assert len(req.acceptance_criteria) == 2

    def test_requirement_serialization(self):
        """Test Requirement to/from dict."""
        req = Requirement(
            id="req_123",
            description="Test requirement",
            source="goal",
            category="quality",
            priority="medium",
        )
        data = req.to_dict()
        assert data["id"] == "req_123"
        assert data["description"] == "Test requirement"

        restored = Requirement.from_dict(data)
        assert restored.id == "req_123"
        assert restored.description == "Test requirement"

    def test_requirement_verification(self):
        """Test RequirementVerification model."""
        verification = RequirementVerification(
            requirement_id="req_123",
            requirement_description="Test requirement",
            status=VerificationStatus.SATISFIED,
            evidence=["Test passed", "Code implemented"],
            gaps=[],
            confidence=0.9,
            notes="All criteria met",
        )
        assert verification.is_satisfied is True
        assert verification.status == VerificationStatus.SATISFIED

        # Partially satisfied
        verification.status = VerificationStatus.PARTIALLY_SATISFIED
        assert verification.is_satisfied is True

        # Not satisfied
        verification.status = VerificationStatus.NOT_SATISFIED
        assert verification.is_satisfied is False

    def test_validation_check(self):
        """Test ValidationCheck model."""
        check = ValidationCheck(
            name="pytest",
            type="test",
            command=["python", "-m", "pytest", "-q"],
            working_directory=".",
            timeout_seconds=120,
        )
        assert check.name == "pytest"
        assert check.type == "test"
        assert check.timeout_seconds == 120

    def test_validation_result(self):
        """Test ValidationResult model."""
        result = ValidationResult(
            check_id="val_123",
            check_name="pytest",
            check_type="test",
            status=ValidationStatus.PASSED,
            stdout="5 passed",
            stderr="",
            return_code=0,
            duration_seconds=2.5,
            passed=True,
        )
        assert result.passed is True
        assert result.status == ValidationStatus.PASSED

    def test_evaluation_config(self):
        """Test EvaluationConfig model."""
        config = EvaluationConfig(
            evaluation_type=EvaluationType.COMPREHENSIVE,
            trigger=EvaluationTrigger.TASK_COMPLETION,
            task_description="Test task",
            original_request="Original request",
            run_tests=True,
            run_lint=True,
            confidence_thresholds={"overall": 0.7},
        )
        assert config.evaluation_type == EvaluationType.COMPREHENSIVE
        assert config.run_tests is True
        assert config.confidence_thresholds["overall"] == 0.7

    def test_confidence_level_from_score(self):
        """Test ConfidenceLevel.from_score()."""
        assert ConfidenceLevel.from_score(0.95) == ConfidenceLevel.VERY_HIGH
        assert ConfidenceLevel.from_score(0.75) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.55) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.35) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.15) == ConfidenceLevel.CRITICAL


class TestRequirementVerifier:
    """Tests for RequirementVerifier."""

    def test_extract_requirements_from_text(self):
        """Test extracting requirements from text."""
        verifier = RequirementVerifier()
        text = """
        - Implement user login
        - Add password reset functionality
        - Ensure all tests pass
        """
        requirements = verifier._parse_requirements_from_text(text, "user_request")
        assert len(requirements) >= 2
        assert any("login" in r.description.lower() for r in requirements)

    def test_extract_requirements_with_imperative(self):
        """Test extracting requirements with imperative language."""
        verifier = RequirementVerifier()
        text = "Must implement authentication. Should add tests."
        requirements = verifier._parse_requirements_from_text(text, "task_description")
        assert len(requirements) >= 1

    def test_extract_requirements_general_fallback(self):
        """Test fallback when no explicit requirements found."""
        verifier = RequirementVerifier()
        text = "Fix the bug in the login module"
        requirements = verifier._parse_requirements_from_text(text, "user_request")
        assert len(requirements) == 1
        assert "bug" in requirements[0].description.lower()

    def test_extract_key_terms(self):
        """Test key term extraction."""
        verifier = RequirementVerifier()
        terms = verifier._extract_key_terms("implement user authentication system")
        assert "implement" in terms
        assert "user" in terms
        assert "authentication" in terms
        assert "system" in terms

    def test_verify_heuristic_satisfied(self):
        """Test heuristic verification - satisfied."""
        verifier = RequirementVerifier()
        req = Requirement(description="Implement user login")
        context = "User login implemented with JWT tokens. Tests pass."

        result = verifier._verify_heuristic(req, context)
        assert result.status in (VerificationStatus.SATISFIED, VerificationStatus.PARTIALLY_SATISFIED)
        assert result.confidence > 0.5

    def test_verify_heuristic_not_satisfied(self):
        """Test heuristic verification - not satisfied."""
        verifier = RequirementVerifier()
        req = Requirement(description="Implement user logout functionality")
        # Context has login but NOT logout
        context = "User login implemented with JWT tokens. Session management works."

        result = verifier._verify_heuristic(req, context)
        # Should be NOT_SATISFIED or PARTIALLY_SATISFIED (overlapping terms)
        assert result.status in (VerificationStatus.NOT_SATISFIED, VerificationStatus.PARTIALLY_SATISFIED)
        if result.status == VerificationStatus.NOT_SATISFIED:
            assert result.confidence < 0.6


class TestValidationRunner:
    """Tests for ValidationRunner."""

    def test_get_default_validations(self):
        """Test getting default validation checks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ValidationRunner(workspace=tmpdir)
            checks = runner.get_default_validations()
            assert len(checks) >= 2  # lint and test at minimum
            check_types = {c.type for c in checks}
            assert "lint" in check_types
            assert "test" in check_types

    def test_run_validation_lint(self):
        """Test running lint validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple Python file
            (Path(tmpdir) / "test.py").write_text("print('hello')\n")

            runner = ValidationRunner(workspace=tmpdir)
            checks = runner.get_default_validations()
            lint_check = next((c for c in checks if c.type == "lint"), None)

            assert lint_check is not None
            result = runner.run_validation(lint_check)
            assert result.check_name == "python_lint"
            assert result.check_type == "lint"

    def test_run_validation_test(self):
        """Test running test validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = ValidationRunner(workspace=tmpdir)
            checks = runner.get_default_validations()
            test_check = next((c for c in checks if c.type == "test"), None)

            if test_check:
                result = runner.run_validation(test_check)
                assert result.check_name == "pytest"
                # Result may pass or fail depending on project state


class TestEvaluationPipeline:
    """Tests for EvaluationPipeline."""

    def test_pipeline_creation(self):
        """Test creating pipeline with components."""
        pipeline = EvaluationPipeline(workspace=".")
        assert pipeline.requirement_verifier is not None
        assert pipeline.validation_runner is not None

    def test_calculate_scores(self):
        """Test score calculation."""
        pipeline = EvaluationPipeline(workspace=".")

        # Create mock result
        result = EvaluationResult(
            config=EvaluationConfig(),
        )
        config = EvaluationConfig(
            confidence_thresholds={"requirement_verification": 0.6, "functional_validation": 0.7}
        )
        result.config = config

        # Add requirement verifications
        result.requirement_verifications = [
            RequirementVerification(
                requirement_id="1",
                requirement_description="Req 1",
                status=VerificationStatus.SATISFIED,
                confidence=0.9,
            ),
            RequirementVerification(
                requirement_id="2",
                requirement_description="Req 2",
                status=VerificationStatus.PARTIALLY_SATISFIED,
                confidence=0.6,
            ),
            RequirementVerification(
                requirement_id="3",
                requirement_description="Req 3",
                status=VerificationStatus.NOT_SATISFIED,
                confidence=0.3,
            ),
        ]

        # Add validation results
        result.validation_results = [
            ValidationResult(check_id="1", check_name="test1", check_type="test", status=ValidationStatus.PASSED, passed=True),
            ValidationResult(check_id="2", check_name="test2", check_type="test", status=ValidationStatus.PASSED, passed=True),
            ValidationResult(check_id="3", check_name="lint", check_type="lint", status=ValidationStatus.FAILED, passed=False),
        ]

        # Calculate scores
        pipeline._calculate_scores(result, config)

        # Requirement score: (1 + 0.5 + 0) / 3 = 0.5
        assert 0.45 <= result.requirement_score <= 0.55

        # Validation score: 2/3 = 0.67
        assert 0.6 <= result.validation_score <= 0.7

        # Overall: 5-weight breakdown (req 30%, val 30%, regression 10%, quality 15%, docs 15%)
        # Defaults when not present: regression=1.0, quality=1.0, docs=1.0
        expected_overall = (
            result.requirement_score * 0.3 +
            result.validation_score * 0.3 +
            1.0 * 0.1 +  # regression (no regressions by default)
            1.0 * 0.15 + # quality (no issues by default)
            1.0 * 0.15   # documentation (no checks by default)
        )
        assert abs(result.overall_confidence - expected_overall) < 0.01
        # High confidence if overall >= 0.6
        if result.overall_confidence >= 0.6:
            assert result.confidence_level in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)


class TestEvaluationManager:
    """Tests for EvaluationManager."""

    def test_manager_initialization(self):
        """Test EvaluationManager initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)
            assert manager.workspace == Path(tmpdir).resolve()
            assert manager.pipeline is not None
            assert manager.history is not None

    def test_evaluate_task_completion(self):
        """Test evaluating a task completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            result = manager.evaluate_task_completion(
                task_description="Create a simple Python script",
                original_request="User asked to create a hello world script",
            )

            assert result is not None
            assert result.status == EvaluationStatus.COMPLETED
            assert result.overall_confidence >= 0
            assert result.overall_confidence <= 1.0
            assert result.config is not None

    def test_evaluate_goal_completion(self):
        """Test evaluating a goal completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            result = manager.evaluate_goal_completion(
                goal_id="goal_123",
                goal_name="Implement Authentication",
                goal_description="Add user login and registration",
            )

            assert result is not None
            assert result.config.goal_id == "goal_123"
            assert result.config.trigger == EvaluationTrigger.GOAL_COMPLETION

    def test_evaluate_repair_completion(self):
        """Test evaluating a repair completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            result = manager.evaluate_repair_completion(
                task_description="Fix login bug",
                original_request="Login fails with 500 error",
            )

            assert result is not None
            assert result.config.trigger == EvaluationTrigger.REPAIR_COMPLETION
            assert result.config.evaluation_type == EvaluationType.FUNCTIONAL_VALIDATION

    def test_calculate_confidence(self):
        """Test confidence calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            verifications = [
                RequirementVerification(requirement_id="1", requirement_description="Req 1",
                    status=VerificationStatus.SATISFIED, confidence=0.9),
                RequirementVerification(requirement_id="2", requirement_description="Req 2",
                    status=VerificationStatus.NOT_SATISFIED, confidence=0.2),
            ]

            validations = [
                ValidationResult(check_id="1", check_name="test", check_type="test",
                    status=ValidationStatus.PASSED, passed=True),
            ]

            confidence, level, breakdown = manager.calculate_confidence(verifications, validations)

            assert 0.0 <= confidence <= 1.0
            assert isinstance(level, ConfidenceLevel)
            assert "requirement_verification" in breakdown
            assert "functional_validation" in breakdown
            assert "overall" in breakdown

    def test_should_deliver(self):
        """Test delivery decision logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            # High confidence - should deliver
            should, rework, review, reasons = manager.should_deliver(
                overall_confidence=0.8,
                requirement_score=0.8,
                validation_score=0.8,
            )
            assert should is True
            assert rework is False

            # Low confidence - needs rework
            should, rework, review, reasons = manager.should_deliver(
                overall_confidence=0.4,
                requirement_score=0.4,
                validation_score=0.4,
            )
            assert should is False
            assert rework is True
            assert len(reasons) > 0

    def test_history_persistence(self):
        """Test that evaluation history is persisted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            # Run evaluation
            result = manager.evaluate_task_completion(
                task_description="Test task",
                original_request="Test request",
                task_id="task_123",
            )

            # Check history
            history = manager.get_history(task_id="task_123")
            assert len(history) == 1
            assert history[0].task_id == "task_123"
            assert history[0].evaluation_id == result.evaluation_id

    def test_get_latest_for_task(self):
        """Test getting latest evaluation for a task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            manager.evaluate_task_completion(
                task_description="Task 1",
                original_request="Request 1",
                task_id="task_456",
            )
            manager.evaluate_task_completion(
                task_description="Task 1 again",
                original_request="Request 1 again",
                task_id="task_456",
            )

            latest = manager.get_latest_for_task("task_456")
            assert latest is not None
            assert "again" in latest.task_description

    def test_explain_result(self):
        """Test result explanation generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            result = manager.evaluate_task_completion(
                task_description="Implement feature",
                original_request="Add new feature",
            )

            explanation = manager.explain_result(result)
            assert "Self-Evaluation Report" in explanation
            assert "CONFIDENCE SCORES" in explanation
            assert "DECISION" in explanation

    def test_get_statistics(self):
        """Test statistics retrieval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = EvaluationManager(workspace=tmpdir)

            manager.evaluate_task_completion(task_description="Task 1", original_request="Req 1")
            manager.evaluate_task_completion(task_description="Task 2", original_request="Req 2")

            stats = manager.get_statistics()
            assert stats["total_evaluations"] == 2
            assert "history" in stats


class TestEvaluationHistory:
    """Tests for EvaluationHistory."""

    def test_add_and_query_records(self):
        """Test adding and querying records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = EvaluationHistory(workspace=tmpdir)

            record = EvaluationRecord(
                evaluation_id="eval_123",
                evaluation_type="comprehensive",
                trigger="task_completion",
                task_id="task_1",
                task_description="Test task",
                original_request="Test request",
                goal_id=None,
                plan_id=None,
                status="completed",
                started_at="2024-01-01T00:00:00",
                completed_at="2024-01-01T00:00:10",
                duration_seconds=10.0,
                overall_confidence=0.8,
                confidence_level="high",
                requirement_score=0.8,
                validation_score=0.8,
                should_deliver=True,
                requires_rework=False,
                requires_human_review=False,
                rework_reasons=[],
                summary="Test summary",
            )
            history.add_record(record)

            records = history.query(task_id="task_1")
            assert len(records) == 1
            assert records[0].evaluation_id == "eval_123"

    def test_get_summary(self):
        """Test summary statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = EvaluationHistory(workspace=tmpdir)

            for i in range(5):
                record = EvaluationRecord(
                    evaluation_id=f"eval_{i}",
                    evaluation_type="comprehensive",
                    trigger="task_completion",
                    task_id=f"task_{i}",
                    task_description=f"Task {i}",
                    original_request=f"Request {i}",
                    goal_id=None,
                    plan_id=None,
                    status="completed",
                    started_at="2024-01-01T00:00:00",
                    completed_at="2024-01-01T00:00:10",
                    duration_seconds=10.0,
                    overall_confidence=0.5 + i * 0.1,
                    confidence_level="medium" if i < 3 else "high",
                    requirement_score=0.5 + i * 0.1,
                    validation_score=0.5 + i * 0.1,
                    should_deliver=i >= 2,
                    requires_rework=i < 2,
                    requires_human_review=False,
                    rework_reasons=[],
                    summary=f"Summary {i}",
                )
                history.add_record(record)

            summary = history.get_summary()
            assert summary["total_evaluations"] == 5
            assert 0.5 <= summary["average_confidence"] <= 0.9
            assert summary["deliver_rate"] == 0.6  # 3 out of 5
            assert summary["rework_rate"] == 0.4  # 2 out of 5


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_evaluation_manager_singleton(self):
        """Test that get_evaluation_manager returns same instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = get_evaluation_manager(workspace=tmpdir)
            m2 = get_evaluation_manager(workspace=tmpdir)
            assert m1 is m2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestRegressionDetector:
    """Tests for RegressionDetector (High Priority #5)."""

    def test_singleton_capture_pre_state(self):
        """Test capturing pre-state before task execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = RegressionDetector(workspace=tmpdir)
            detector.capture_pre_state()
            # Should not crash even if no tests exist
            assert detector._pre_test_results is not None

    def test_detect_regressions_no_pre_state(self):
        """Test detect_regressions when no pre-state captured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = RegressionDetector(workspace=tmpdir)
            regressions = detector.detect_regressions()
            assert regressions == []  # No pre-state, empty result

    def test_regression_result_model(self):
        """Test RegressionResult model."""
        result = RegressionResult(
            check_id="reg_123",
            check_name="Test Suite Regression",
            check_type="test",
            has_regression=True,
            regression_details=["Tests passed before, failed after"],
            pre_value={"passed": True},
            post_value={"passed": False},
        )
        assert result.has_regression is True
        assert len(result.regression_details) == 1
        data = result.to_dict()
        assert data["check_id"] == "reg_123"
        assert data["has_regression"] is True

    def test_regression_check_model(self):
        """Test RegressionCheck model."""
        check = RegressionCheck(
            name="Test Check",
            type="test",
            pre_state={"tests": 5, "passed": 5},
            post_state={"tests": 5, "passed": 3},
        )
        assert check.name == "Test Check"
        assert check.type == "test"
        assert check.pre_state["tests"] == 5


class TestCodeQualityReviewer:
    """Tests for CodeQualityReviewer (High Priority #6)."""

    def test_quality_issue_model(self):
        """Test QualityIssue model."""
        issue = QualityIssue(
            file_path="app/test.py",
            line_number=10,
            category="complexity",
            severity="warning",
            title="Function too complex",
            description="Function has cyclomatic complexity 15",
            suggestion="Refactor into smaller functions",
            confidence=0.9,
        )
        assert issue.file_path == "app/test.py"
        assert issue.line_number == 10
        assert issue.category == "complexity"
        assert issue.severity == "warning"

    def test_quality_review_model(self):
        """Test QualityReview model."""
        review = QualityReview(
            issues=[
                QualityIssue(
                    file_path="app/test.py",
                    line_number=10,
                    category="complexity",
                    severity="warning",
                    title="Complex function",
                    description="Function is too complex",
                ),
                QualityIssue(
                    file_path="app/main.py",
                    line_number=5,
                    category="style",
                    severity="info",
                    title="Missing docstring",
                    description="Public function lacks docstring",
                ),
            ],
            overall_score=0.8,
            category_scores={"complexity": 0.7, "style": 0.9},
            summary="2 issues found",
        )
        assert review.issue_count == 2
        assert review.warning_count == 1
        assert review.info_count == 1
        assert review.critical_count == 0
        assert review.error_count == 0

        data = review.to_dict()
        assert data["issue_count"] == 2
        assert data["overall_score"] == 0.8
        assert "complexity" in data["category_scores"]

    def test_review_no_issues(self):
        """Test QualityReview with no issues."""
        review = QualityReview()
        assert review.issue_count == 0
        assert review.overall_score == 1.0
        assert review.summary == ""

    def test_code_quality_reviewer_instantiation(self):
        """Test CodeQualityReviewer instantiation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reviewer = CodeQualityReviewer(workspace=tmpdir)
            assert reviewer.workspace == Path(tmpdir).resolve()

    def test_review_creates_empty_review_for_no_files(self):
        """Test that review returns empty review for no files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reviewer = CodeQualityReviewer(workspace=tmpdir)
            review = reviewer.review(changed_files=[])
            assert isinstance(review, QualityReview)
            assert review.issue_count == 0
            assert review.overall_score == 1.0


class TestDocumentationVerifier:
    """Tests for DocumentationVerifier (High Priority #7)."""

    def test_doc_check_model(self):
        """Test DocCheck model."""
        check = DocCheck(
            name="README Check",
            type="readme",
            target_files=["README.md"],
            check_function="check_readme",
        )
        assert check.name == "README Check"
        assert check.type == "readme"
        assert "README.md" in check.target_files

    def test_doc_check_result_model(self):
        """Test DocCheckResult model."""
        result = DocCheckResult(
            check_id="doc_123",
            check_name="README Check",
            check_type="readme",
            passed=True,
            issues=[],
            suggestions=["Add badges"],
            details="README.md exists",
        )
        assert result.passed is True
        assert result.check_name == "README Check"
        data = result.to_dict()
        assert data["passed"] is True
        assert data["check_type"] == "readme"

    def test_doc_verifier_instantiation(self):
        """Test DocumentationVerifier instantiation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            verifier = DocumentationVerifier(workspace=tmpdir)
            assert verifier.workspace == Path(tmpdir).resolve()

    def test_check_readme_exists(self):
        """Test README existence check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            verifier = DocumentationVerifier(workspace=tmpdir)
            result = verifier._check_readme()
            assert isinstance(result, DocCheckResult)
            assert result.check_type == "readme"
            assert result.passed is False  # No README in empty dir

    def test_check_readme_passes_when_exists(self):
        """Test README check passes when file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "README.md").write_text("# Test Project\n")
            verifier = DocumentationVerifier(workspace=tmpdir)
            result = verifier._check_readme()
            assert result.passed is True
            assert "README.md" in result.details

    def test_check_inline_docs(self):
        """Test inline documentation check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file with and without docstrings
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("""
def public_function():
    return 42

def _private_function():
    return 1

class PublicClass:
    def method(self):
        pass
""")
            verifier = DocumentationVerifier(workspace=tmpdir)
            result = verifier._check_inline_docs(["test.py"])
            assert isinstance(result, DocCheckResult)
            assert result.check_type == "inline_docs"
            # public_function and PublicClass.method missing docstrings

    def test_check_type_hints(self):
        """Test type hints check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("""
def no_return_hint():
    return 42

def has_return_hint() -> int:
    return 42
""")
            verifier = DocumentationVerifier(workspace=tmpdir)
            result = verifier._check_type_hints(["test.py"])
            assert isinstance(result, DocCheckResult)
            assert result.check_type == "type_hints"
            # no_return_hint missing return type hint


class TestImprovementLoop:
    """Tests for Improvement Loop (High Priority #8)."""

    def test_improvement_iteration_model(self):
        """Test ImprovementIteration model."""
        iteration = ImprovementIteration(
            iteration=1,
            evaluation_id="eval_123",
            overall_confidence=0.65,
            issues_found=5,
            issues_fixed=3,
            improvements_made=["Fixed complexity", "Added tests"],
            duration_seconds=10.5,
            met_threshold=True,
        )
        assert iteration.iteration == 1
        assert iteration.issues_found == 5
        assert iteration.issues_fixed == 3
        assert len(iteration.improvements_made) == 2
        assert iteration.met_threshold is True

    def test_improvement_loop_result_model(self):
        """Test ImprovementLoopResult model."""
        loop_result = ImprovementLoopResult(
            iterations=[
                ImprovementIteration(
                    iteration=1,
                    evaluation_id="eval_1",
                    overall_confidence=0.5,
                    issues_found=5,
                    issues_fixed=2,
                    improvements_made=["Fix 1", "Fix 2"],
                ),
                ImprovementIteration(
                    iteration=2,
                    evaluation_id="eval_2",
                    overall_confidence=0.75,
                    issues_found=3,
                    issues_fixed=1,
                    improvements_made=["Fix 3"],
                ),
            ],
            initial_confidence=0.5,
            final_confidence=0.75,
            total_issues_fixed=3,
            total_improvements=3,
            stopped_reason="threshold_met",
            total_duration_seconds=25.0,
            success=True,
        )
        assert len(loop_result.iterations) == 2
        assert loop_result.initial_confidence == 0.5
        assert loop_result.final_confidence == 0.75
        assert loop_result.total_issues_fixed == 3
        assert loop_result.stopped_reason == "threshold_met"
        assert loop_result.success is True

        data = loop_result.to_dict()
        assert data["loop_id"].startswith("il_")
        assert len(data["iterations"]) == 2
        assert data["success"] is True


class TestHighPriorityIntegration:
    """Integration tests for High Priority capabilities."""

    def test_pipeline_includes_high_priority_components(self):
        """Test that pipeline has all high-priority components."""
        pipeline = EvaluationPipeline(workspace=".")
        assert pipeline.regression_detector is not None
        assert pipeline.quality_reviewer is not None
        assert pipeline.doc_verifier is not None

    def test_evaluation_config_has_high_priority_flags(self):
        """Test EvaluationConfig has high-priority capability flags."""
        config = EvaluationConfig()
        assert hasattr(config, "run_regression_detection")
        assert hasattr(config, "run_code_quality_review")
        assert hasattr(config, "run_documentation_verification")
        assert config.run_regression_detection is True
        assert config.run_code_quality_review is True
        assert config.run_documentation_verification is True

    def test_evaluation_result_has_high_priority_fields(self):
        """Test EvaluationResult has high-priority result fields."""
        result = EvaluationResult()
        assert hasattr(result, "regression_results")
        assert hasattr(result, "quality_review")
        assert hasattr(result, "doc_check_results")
        assert isinstance(result.regression_results, list)
        assert result.quality_review is None
        assert isinstance(result.doc_check_results, list)

    def test_confidence_breakdown_includes_high_priority(self):
        """Test confidence breakdown includes high-priority categories."""
        pipeline = EvaluationPipeline(workspace=".")
        result = EvaluationResult(config=EvaluationConfig())
        config = EvaluationConfig()
        result.config = config

        result.requirement_verifications = [
            RequirementVerification(
                requirement_id="1",
                requirement_description="Req 1",
                status=VerificationStatus.SATISFIED,
                confidence=0.8,
            )
        ]
        result.validation_results = [
            ValidationResult(check_id="1", check_name="test", check_type="test", status=ValidationStatus.PASSED, passed=True),
        ]

        pipeline._calculate_scores(result, config)

        assert "requirement_verification" in result.confidence_breakdown
        assert "functional_validation" in result.confidence_breakdown
        assert "regression_detection" in result.confidence_breakdown
        assert "code_quality" in result.confidence_breakdown
        assert "documentation" in result.confidence_breakdown
        assert "overall" in result.confidence_breakdown

    def test_decision_considers_regressions(self):
        """Test that decision considers regressions."""
        pipeline = EvaluationPipeline(workspace=".")
        result = EvaluationResult(config=EvaluationConfig())
        config = EvaluationConfig()
        result.config = config

        # Add good scores
        result.requirement_verifications = [
            RequirementVerification(requirement_id="1", requirement_description="Req 1", status=VerificationStatus.SATISFIED, confidence=0.9),
        ]
        result.validation_results = [
            ValidationResult(check_id="1", check_name="test", check_type="test", status=ValidationStatus.PASSED, passed=True),
        ]

        # Add a regression
        result.regression_results = [
            RegressionResult(
                check_id="reg_1",
                check_name="Test Suite",
                check_type="test",
                has_regression=True,
                regression_details=["Tests failed after task"],
            )
        ]

        pipeline._calculate_scores(result, config)
        pipeline._make_decision(result, config)

        assert result.requires_rework is True
        assert any("Regressions detected" in r for r in result.rework_reasons)

    def test_decision_considers_quality(self):
        """Test that decision considers code quality."""
        pipeline = EvaluationPipeline(workspace=".")
        result = EvaluationResult(config=EvaluationConfig())
        config = EvaluationConfig()
        result.config = config

        result.requirement_verifications = [
            RequirementVerification(requirement_id="1", requirement_description="Req 1", status=VerificationStatus.SATISFIED, confidence=0.9),
        ]
        result.validation_results = [
            ValidationResult(check_id="1", check_name="test", check_type="test", status=ValidationStatus.PASSED, passed=True),
        ]
        result.quality_review = QualityReview(
            overall_score=0.4,  # Below threshold
            category_scores={"complexity": 0.3},
            summary="Too many issues",
        )

        pipeline._calculate_scores(result, config)
        pipeline._make_decision(result, config)

        assert result.requires_rework is True
        assert any("Code quality score too low" in r for r in result.rework_reasons)

    def test_decision_considers_documentation(self):
        """Test that decision considers documentation."""
        pipeline = EvaluationPipeline(workspace=".")
        result = EvaluationResult(config=EvaluationConfig())
        config = EvaluationConfig()
        result.config = config

        result.requirement_verifications = [
            RequirementVerification(requirement_id="1", requirement_description="Req 1", status=VerificationStatus.SATISFIED, confidence=0.9),
        ]
        result.validation_results = [
            ValidationResult(check_id="1", check_name="test", check_type="test", status=ValidationStatus.PASSED, passed=True),
        ]
        result.doc_check_results = [
            DocCheckResult(
                check_id="doc_1",
                check_name="README",
                check_type="readme",
                passed=False,
                issues=["No README found"],
            )
        ]

        pipeline._calculate_scores(result, config)
        pipeline._make_decision(result, config)

        assert any("Documentation issues" in r for r in result.rework_reasons)