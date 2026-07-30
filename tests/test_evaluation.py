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
)
from app.evaluation.pipeline import (
    EvaluationPipeline,
    RequirementVerifier,
    ValidationRunner,
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
        # But confidence-weighted: (0.9 + 0.6*0.5 + 0.3*0) / 3? No, the implementation uses status-based scoring
        # The actual implementation: satisfied=1.0, partially=0.5, not_satisfied=0
        assert 0.45 <= result.requirement_score <= 0.55

        # Validation score: 2/3 = 0.67
        assert 0.6 <= result.validation_score <= 0.7

        # Overall: req_score * 0.4 + val_score * 0.6
        expected_overall = result.requirement_score * 0.4 + result.validation_score * 0.6
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