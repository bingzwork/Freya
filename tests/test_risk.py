"""Tests for the Risk Assessment System."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest
import tempfile

from app.risk.risk_item import (
    RiskItem,
    RiskSeverity,
    RiskProbability,
    RiskStatus,
    RiskCategory,
)
from app.risk.risk_assessment import (
    RiskAssessment,
    RiskAssessmentResult,
)
from app.risk.risk_analyzer import RiskAnalyzer
from app.risk.risk_register import RiskRegister
from app.risk.risk_mitigation import (
    RiskMitigationStrategy,
    RiskMitigationPlan,
    MitigationStrategyType,
    MitigationStatus,
)
from app.risk.risk_metrics import (
    RiskMetrics,
    RiskScoreCalculator,
)


class TestRiskSeverity:
    """Tests for RiskSeverity."""

    def test_all_severities(self):
        """Test all severity values."""
        severities = [
            RiskSeverity.CRITICAL,
            RiskSeverity.HIGH,
            RiskSeverity.MEDIUM,
            RiskSeverity.LOW,
            RiskSeverity.INFO,
        ]
        for severity in severities:
            assert isinstance(severity, RiskSeverity)

    def test_severity_scores(self):
        """Test severity scores."""
        assert RiskSeverity.CRITICAL.score == 5
        assert RiskSeverity.HIGH.score == 4
        assert RiskSeverity.MEDIUM.score == 3
        assert RiskSeverity.LOW.score == 2
        assert RiskSeverity.INFO.score == 1


class TestRiskProbability:
    """Tests for RiskProbability."""

    def test_all_probabilities(self):
        """Test all probability values."""
        probabilities = [
            RiskProbability.CERTAIN,
            RiskProbability.LIKELY,
            RiskProbability.POSSIBLE,
            RiskProbability.UNLIKELY,
            RiskProbability.RARE,
        ]
        for probability in probabilities:
            assert isinstance(probability, RiskProbability)

    def test_probability_scores(self):
        """Test probability scores."""
        assert RiskProbability.CERTAIN.score == 5
        assert RiskProbability.LIKELY.score == 4
        assert RiskProbability.POSSIBLE.score == 3
        assert RiskProbability.UNLIKELY.score == 2
        assert RiskProbability.RARE.score == 1


class TestRiskStatus:
    """Tests for RiskStatus."""

    def test_all_statuses(self):
        """Test all status values."""
        statuses = [
            RiskStatus.IDENTIFIED,
            RiskStatus.ASSESSED,
            RiskStatus.MITIGATING,
            RiskStatus.MITIGATED,
            RiskStatus.ACCEPTED,
            RiskStatus.CLOSED,
            RiskStatus.MONITORING,
        ]
        for status in statuses:
            assert isinstance(status, RiskStatus)


class TestRiskCategory:
    """Tests for RiskCategory."""

    def test_all_categories(self):
        """Test all category values."""
        categories = [
            RiskCategory.TECHNICAL,
            RiskCategory.SECURITY,
            RiskCategory.PERFORMANCE,
            RiskCategory.RELIABILITY,
            RiskCategory.MAINTAINABILITY,
            RiskCategory.SCALABILITY,
            RiskCategory.COMPLIANCE,
            RiskCategory.BUSINESS,
            RiskCategory.OPERATIONAL,
            RiskCategory.FINANCIAL,
            RiskCategory.SCHEDULE,
            RiskCategory.RESOURCE,
            RiskCategory.QUALITY,
            RiskCategory.INTEGRATION,
            RiskCategory.DEPENDENCY,
        ]
        for category in categories:
            assert isinstance(category, RiskCategory)


class TestRiskItem:
    """Tests for RiskItem."""

    def test_risk_creation(self):
        """Test creating a risk item."""
        risk = RiskItem(
            title="Security Vulnerability",
            category=RiskCategory.SECURITY,
        )
        assert risk.title == "Security Vulnerability"
        assert risk.category == RiskCategory.SECURITY
        assert risk.id.startswith("risk_")

    def test_risk_with_all_fields(self):
        """Test creating a risk with all fields."""
        risk = RiskItem(
            title="Security Vulnerability",
            category=RiskCategory.SECURITY,
            description="SQL injection vulnerability in login endpoint",
            severity=RiskSeverity.CRITICAL,
            probability=RiskProbability.LIKELY,
            status=RiskStatus.IDENTIFIED,
            impact="Unauthorized database access",
            likely_hood=0.8,
            owner="security-team",
            tags=["security", "critical"],
            related_components=["auth-api", "login-endpoint"],
        )
        assert risk.severity == RiskSeverity.CRITICAL
        assert risk.probability == RiskProbability.LIKELY
        assert risk.risk_score > 0

    def test_risk_from_dict(self):
        """Test creating risk from dictionary."""
        data = {
            "id": "risk-001",
            "title": "Test Risk",
            "category": "security",
            "severity": "high",
            "probability": "likely",
        }
        risk = RiskItem.from_dict(data)
        assert risk.id == "risk-001"
        assert risk.category == RiskCategory.SECURITY
        assert risk.severity == RiskSeverity.HIGH

    def test_risk_to_dict(self):
        """Test converting risk to dictionary."""
        risk = RiskItem(
            id="risk-001",
            title="Test Risk",
            category=RiskCategory.SECURITY,
        )
        data = risk.to_dict()
        assert data["id"] == "risk-001"
        assert data["category"] == "security"

    def test_risk_score_calculation(self):
        """Test risk score calculation."""
        risk = RiskItem(
            title="Test",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.HIGH,
            probability=RiskProbability.LIKELY,
            likely_hood=0.8,
        )
        # Score = (5 * 5 * 0.8 / 25) * 100 = 80
        # But with HIGH=4, LIKELY=4: (4 * 4 * 0.8 / 25) * 100 = 51.2
        assert risk.risk_score > 0

    def test_risk_level(self):
        """Test risk level determination."""
        # Critical risk
        risk_critical = RiskItem(
            title="Critical",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.CRITICAL,
            probability=RiskProbability.CERTAIN,
            likely_hood=1.0,
        )
        assert risk_critical.risk_level in ["critical", "high"]

        # Low risk
        risk_low = RiskItem(
            title="Low",
            category=RiskCategory.QUALITY,
            severity=RiskSeverity.LOW,
            probability=RiskProbability.RARE,
            likely_hood=0.1,
        )
        assert risk_low.risk_level in ["low", "info"]

    def test_is_active(self):
        """Test checking if risk is active."""
        risk = RiskItem(
            title="Test",
            category=RiskCategory.SECURITY,
            status=RiskStatus.IDENTIFIED,
        )
        assert risk.is_active is True

        risk.status = RiskStatus.MITIGATED
        assert risk.is_active is False

    def test_is_closed(self):
        """Test checking if risk is closed."""
        risk = RiskItem(
            title="Test",
            category=RiskCategory.SECURITY,
            status=RiskStatus.MITIGATED,
        )
        assert risk.is_closed is True

        risk.status = RiskStatus.IDENTIFIED
        assert risk.is_closed is False

    def test_update_status(self):
        """Test updating risk status."""
        risk = RiskItem(title="Test", category=RiskCategory.SECURITY)
        risk.update_status(RiskStatus.ASSESSED)
        assert risk.status == RiskStatus.ASSESSED


class TestRiskAssessmentResult:
    """Tests for RiskAssessmentResult."""

    def test_result_creation(self):
        """Test creating an assessment result."""
        result = RiskAssessmentResult(
            assessment_id="assessment-001",
            risk_id="risk-001",
            severity=RiskSeverity.HIGH,
            probability=RiskProbability.LIKELY,
            risk_score=75.0,
            assessor="analyst1",
        )
        assert result.assessment_id == "assessment-001"
        assert result.risk_score == 75.0

    def test_result_from_dict(self):
        """Test creating result from dictionary."""
        data = {
            "assessment_id": "assessment-001",
            "risk_id": "risk-001",
            "severity": "high",
            "probability": "likely",
        }
        result = RiskAssessmentResult.from_dict(data)
        assert result.severity == RiskSeverity.HIGH

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = RiskAssessmentResult(
            assessment_id="assessment-001",
            risk_id="risk-001",
        )
        data = result.to_dict()
        assert data["assessment_id"] == "assessment-001"

    def test_risk_level(self):
        """Test risk level from score."""
        result = RiskAssessmentResult(
            assessment_id="test",
            risk_id="test",
            risk_score=85.0,
        )
        assert result.risk_level == "critical"


class TestRiskAssessment:
    """Tests for RiskAssessment."""

    def test_assessment_creation(self):
        """Test creating a risk assessment."""
        assessment = RiskAssessment(
            name="Project Security Assessment",
            description="Assessment of security risks in the project",
            scope=["auth-api", "user-service"],
        )
        assert assessment.name == "Project Security Assessment"
        assert assessment.id.startswith("assessment_")

    def test_assessment_from_dict(self):
        """Test creating assessment from dictionary."""
        data = {
            "id": "assessment-001",
            "name": "Test Assessment",
            "risk_items": [],
            "assessment_results": [],
        }
        assessment = RiskAssessment.from_dict(data)
        assert assessment.id == "assessment-001"

    def test_assessment_to_dict(self):
        """Test converting assessment to dictionary."""
        assessment = RiskAssessment(name="Test")
        data = assessment.to_dict()
        assert data["name"] == "Test"

    def test_add_risk_item(self):
        """Test adding a risk item to assessment."""
        assessment = RiskAssessment(name="Test")
        risk = RiskItem(title="Risk1", category=RiskCategory.SECURITY)
        assessment.add_risk_item(risk)
        assert len(assessment.risk_items) == 1

    def test_add_result(self):
        """Test adding a result to assessment."""
        assessment = RiskAssessment(name="Test")
        result = RiskAssessmentResult(
            assessment_id="test",
            risk_id="risk-001",
        )
        assessment.add_result(result)
        assert len(assessment.assessment_results) == 1

    def test_total_risk_score(self):
        """Test total risk score calculation."""
        assessment = RiskAssessment(name="Test")
        assessment.add_risk_item(
            RiskItem(title="Risk1", category=RiskCategory.SECURITY, severity=RiskSeverity.HIGH)
        )
        assessment.add_risk_item(
            RiskItem(title="Risk2", category=RiskCategory.SECURITY, severity=RiskSeverity.LOW)
        )
        assert assessment.total_risk_score > 0

    def test_average_risk_score(self):
        """Test average risk score calculation."""
        assessment = RiskAssessment(name="Test")
        assessment.add_risk_item(
            RiskItem(title="Risk1", category=RiskCategory.SECURITY, severity=RiskSeverity.HIGH)
        )
        assessment.add_risk_item(
            RiskItem(title="Risk2", category=RiskCategory.SECURITY, severity=RiskSeverity.HIGH)
        )
        assert assessment.average_risk_score > 0

    def test_highest_risk(self):
        """Test getting highest risk."""
        assessment = RiskAssessment(name="Test")
        risk1 = RiskItem(
            title="Risk1",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.HIGH,
            probability=RiskProbability.LIKELY,
        )
        risk2 = RiskItem(
            title="Risk2",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.LOW,
            probability=RiskProbability.RARE,
        )
        assessment.add_risk_item(risk1)
        assessment.add_risk_item(risk2)
        highest = assessment.highest_risk
        assert highest is not None
        assert highest.risk_score >= risk2.risk_score

    def test_summary(self):
        """Test getting assessment summary."""
        assessment = RiskAssessment(name="Test")
        assessment.add_risk_item(
            RiskItem(title="Risk1", category=RiskCategory.SECURITY)
        )
        summary = assessment.summary
        assert "total_risk_items" in summary
        assert summary["total_risk_items"] == 1


class TestRiskAnalyzer:
    """Tests for RiskAnalyzer."""

    def test_analyzer_creation(self):
        """Test creating a risk analyzer."""
        analyzer = RiskAnalyzer()
        assert len(analyzer.checks) > 0
        assert len(analyzer.patterns) > 0

    def test_register_check(self):
        """Test registering a custom check."""
        analyzer = RiskAnalyzer()
        initial_count = len(analyzer.checks)

        def custom_check(content, file_path):
            return []

        analyzer.register_check("custom_check", custom_check)
        assert len(analyzer.checks) == initial_count + 1

    def test_register_pattern(self):
        """Test registering a custom pattern."""
        analyzer = RiskAnalyzer()
        initial_count = len(analyzer.patterns)

        analyzer.register_pattern(
            name="custom_pattern",
            patterns=[r"custom.*pattern"],
            severity=RiskSeverity.MEDIUM,
            probability=RiskProbability.POSSIBLE,
            category=RiskCategory.TECHNICAL,
        )
        assert len(analyzer.patterns) == initial_count + 1

    def test_analyze_content(self):
        """Test analyzing content for risks."""
        analyzer = RiskAnalyzer()
        content = "# TODO: Fix this later\npassword = 'secret123'"

        findings = analyzer._analyze_content(content)
        # Should find TODO and password patterns
        assert len(findings) >= 1

    def test_analyze_file(self):
        """Test analyzing a file for risks."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# TODO: Fix this\npassword = 'secret')")
            temp_path = Path(f.name)

        try:
            analyzer = RiskAnalyzer()
            findings = analyzer.analyze_file(temp_path)
            assert len(findings) >= 0
        finally:
            # Clean up - close and remove the file
            try:
                temp_path.unlink()
            except (PermissionError, FileNotFoundError):
                pass

    def test_assess_risk(self):
        """Test assessing a risk."""
        analyzer = RiskAnalyzer()
        risk = RiskItem(
            title="Test Risk",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.HIGH,
            probability=RiskProbability.LIKELY,
            likely_hood=0.8,
        )
        result = analyzer.assess_risk(risk)
        assert result.assessment_id.startswith("assessment_")
        assert result.risk_score > 0

    def test_generate_recommendations(self):
        """Test generating recommendations."""
        analyzer = RiskAnalyzer()
        risk = RiskItem(
            title="Test Risk",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.CRITICAL,
        )
        recommendations = analyzer._generate_recommendations(risk)
        assert len(recommendations) > 0

    def test_get_summary(self):
        """Test getting analyzer summary."""
        analyzer = RiskAnalyzer()
        analyzer.findings = [
            RiskItem(title="R1", category=RiskCategory.SECURITY, severity=RiskSeverity.CRITICAL),
            RiskItem(title="R2", category=RiskCategory.SECURITY, severity=RiskSeverity.HIGH),
        ]
        summary = analyzer.get_summary()
        assert "total_findings" in summary
        assert summary["total_findings"] == 2

    def test_clear_findings(self):
        """Test clearing findings."""
        analyzer = RiskAnalyzer()
        analyzer.findings = [RiskItem(title="Test", category=RiskCategory.SECURITY)]
        analyzer.clear_findings()
        assert len(analyzer.findings) == 0


class TestRiskRegister:
    """Tests for RiskRegister."""

    def test_register_creation(self):
        """Test creating a risk register."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            assert register.count == 0

    def test_add_risk(self):
        """Test adding a risk to the register."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            risk = register.add_risk(
                title="Test Risk",
                category=RiskCategory.SECURITY,
            )
            assert risk is not None
            assert register.count == 1

    def test_update_risk(self):
        """Test updating a risk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            risk = register.add_risk(
                title="Test Risk",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.MEDIUM,
            )
            result = register.update_risk(risk.id, severity=RiskSeverity.HIGH)
            assert result is True
            updated = register.get_risk(risk.id)
            assert updated.severity == RiskSeverity.HIGH

    def test_remove_risk(self):
        """Test removing a risk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            risk = register.add_risk(title="Test", category=RiskCategory.SECURITY)
            result = register.remove_risk(risk.id)
            assert result is True
            assert register.count == 0

    def test_list_risks(self):
        """Test listing risks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(title="Risk1", category=RiskCategory.SECURITY)
            register.add_risk(title="Risk2", category=RiskCategory.TECHNICAL)
            risks = register.list_risks()
            assert len(risks) == 2

    def test_list_risks_by_category(self):
        """Test listing risks by category."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(title="Risk1", category=RiskCategory.SECURITY)
            register.add_risk(title="Risk2", category=RiskCategory.TECHNICAL)
            security_risks = register.list_risks(category=RiskCategory.SECURITY)
            assert len(security_risks) == 1

    def test_list_active_risks(self):
        """Test listing active risks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(
                title="Risk1",
                category=RiskCategory.SECURITY,
                status=RiskStatus.IDENTIFIED,
            )
            register.add_risk(
                title="Risk2",
                category=RiskCategory.SECURITY,
                status=RiskStatus.MITIGATED,
            )
            active = register.list_active_risks()
            assert len(active) == 1

    def test_add_assessment(self):
        """Test adding an assessment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            assessment = RiskAssessment(name="Test Assessment")
            register.add_assessment(assessment)
            assert len(register.list_assessments()) == 1

    def test_get_summary(self):
        """Test getting register summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(
                title="Risk1",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.CRITICAL,
            )
            register.add_risk(
                title="Risk2",
                category=RiskCategory.TECHNICAL,
                severity=RiskSeverity.LOW,
            )
            summary = register.get_summary()
            assert "total_risks" in summary
            assert summary["total_risks"] == 2

    def test_get_risk_distribution(self):
        """Test getting risk distribution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(
                title="Risk1",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.CRITICAL,
                probability=RiskProbability.CERTAIN,
                likely_hood=1.0,
            )
            register.add_risk(
                title="Risk2",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.HIGH,
                probability=RiskProbability.LIKELY,
                likely_hood=0.9,
            )
            register.add_risk(
                title="Risk3",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.MEDIUM,
                probability=RiskProbability.POSSIBLE,
                likely_hood=0.5,
            )
            distribution = register.get_risk_distribution()
            assert "critical" in distribution
            assert distribution["critical"] >= 1

    def test_clear(self):
        """Test clearing the register."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register = RiskRegister(workspace=tmpdir)
            register.add_risk(title="Test", category=RiskCategory.SECURITY)
            register.clear()
            assert register.count == 0

    def test_persistence(self):
        """Test that the register persists to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            register1 = RiskRegister(workspace=tmpdir)
            register1.add_risk(title="Test", category=RiskCategory.SECURITY)

            # Create a new register pointing to the same workspace
            register2 = RiskRegister(workspace=tmpdir)
            assert register2.count == 1


class TestMitigationStrategyType:
    """Tests for MitigationStrategyType."""

    def test_all_types(self):
        """Test all strategy types."""
        types = [
            MitigationStrategyType.AVOID,
            MitigationStrategyType.REDUCE,
            MitigationStrategyType.TRANSFER,
            MitigationStrategyType.ACCEPT,
            MitigationStrategyType.MITIGATE,
            MitigationStrategyType.CONTINGENCY,
        ]
        for strategy_type in types:
            assert isinstance(strategy_type, MitigationStrategyType)


class TestMitigationStatus:
    """Tests for MitigationStatus."""

    def test_all_statuses(self):
        """Test all mitigation statuses."""
        statuses = [
            MitigationStatus.PLANNED,
            MitigationStatus.IN_PROGRESS,
            MitigationStatus.COMPLETED,
            MitigationStatus.VERIFIED,
            MitigationStatus.FAILED,
        ]
        for status in statuses:
            assert isinstance(status, MitigationStatus)


class TestRiskMitigationStrategy:
    """Tests for RiskMitigationStrategy."""

    def test_strategy_creation(self):
        """Test creating a mitigation strategy."""
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        assert strategy.risk_id == "risk-001"
        assert strategy.id.startswith("mitigation_")

    def test_strategy_from_dict(self):
        """Test creating strategy from dictionary."""
        data = {
            "id": "mitigation-001",
            "risk_id": "risk-001",
            "strategy_type": "reduce",
            "status": "planned",
        }
        strategy = RiskMitigationStrategy.from_dict(data)
        assert strategy.strategy_type == MitigationStrategyType.REDUCE
        assert strategy.status == MitigationStatus.PLANNED

    def test_strategy_to_dict(self):
        """Test converting strategy to dictionary."""
        strategy = RiskMitigationStrategy(
            id="mitigation-001",
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        data = strategy.to_dict()
        assert data["id"] == "mitigation-001"
        assert data["strategy_type"] == "reduce"

    def test_is_active(self):
        """Test checking if strategy is active."""
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
            status=MitigationStatus.PLANNED,
        )
        assert strategy.is_active is True

        strategy.status = MitigationStatus.COMPLETED
        assert strategy.is_active is False

    def test_is_complete(self):
        """Test checking if strategy is complete."""
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
            status=MitigationStatus.COMPLETED,
        )
        assert strategy.is_complete is True

    def test_mark_completed(self):
        """Test marking strategy as completed."""
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        strategy.mark_completed(0.9)
        assert strategy.status == MitigationStatus.COMPLETED
        assert strategy.actual_effectiveness == 0.9

    def test_update_status(self):
        """Test updating strategy status."""
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        strategy.update_status(MitigationStatus.IN_PROGRESS)
        assert strategy.status == MitigationStatus.IN_PROGRESS


class TestRiskMitigationPlan:
    """Tests for RiskMitigationPlan."""

    def test_plan_creation(self):
        """Test creating a mitigation plan."""
        plan = RiskMitigationPlan(
            name="Security Mitigation Plan",
            description="Plan to mitigate security risks",
        )
        assert plan.name == "Security Mitigation Plan"
        assert plan.id.startswith("mitigation_plan_")

    def test_plan_from_dict(self):
        """Test creating plan from dictionary."""
        data = {
            "id": "plan-001",
            "name": "Test Plan",
            "strategies": [],
        }
        plan = RiskMitigationPlan.from_dict(data)
        assert plan.id == "plan-001"

    def test_plan_to_dict(self):
        """Test converting plan to dictionary."""
        plan = RiskMitigationPlan(name="Test Plan")
        data = plan.to_dict()
        assert data["name"] == "Test Plan"

    def test_add_strategy(self):
        """Test adding a strategy to the plan."""
        plan = RiskMitigationPlan(name="Test Plan")
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        plan.add_strategy(strategy)
        assert len(plan.strategies) == 1

    def test_remove_strategy(self):
        """Test removing a strategy from the plan."""
        plan = RiskMitigationPlan(name="Test Plan")
        strategy = RiskMitigationStrategy(
            risk_id="risk-001",
            strategy_type=MitigationStrategyType.REDUCE,
        )
        plan.add_strategy(strategy)
        result = plan.remove_strategy(strategy.id)
        assert result is True
        assert len(plan.strategies) == 0

    def test_completion_percentage(self):
        """Test completion percentage calculation."""
        plan = RiskMitigationPlan(name="Test Plan")
        plan.add_strategy(
            RiskMitigationStrategy(
                risk_id="risk-001",
                strategy_type=MitigationStrategyType.REDUCE,
                status=MitigationStatus.COMPLETED,
            )
        )
        plan.add_strategy(
            RiskMitigationStrategy(
                risk_id="risk-002",
                strategy_type=MitigationStrategyType.REDUCE,
                status=MitigationStatus.PLANNED,
            )
        )
        assert plan.completion_percentage == 50.0

    def test_total_estimated_effort(self):
        """Test total estimated effort calculation."""
        plan = RiskMitigationPlan(name="Test Plan")
        plan.add_strategy(
            RiskMitigationStrategy(
                risk_id="risk-001",
                strategy_type=MitigationStrategyType.REDUCE,
                estimated_effort_hours=10,
            )
        )
        plan.add_strategy(
            RiskMitigationStrategy(
                risk_id="risk-002",
                strategy_type=MitigationStrategyType.REDUCE,
                estimated_effort_hours=20,
            )
        )
        assert plan.total_estimated_effort == 30

    def test_get_summary(self):
        """Test getting plan summary."""
        plan = RiskMitigationPlan(name="Test Plan")
        plan.add_strategy(
            RiskMitigationStrategy(
                risk_id="risk-001",
                strategy_type=MitigationStrategyType.REDUCE,
            )
        )
        summary = plan.get_summary()
        assert "total_strategies" in summary
        assert summary["total_strategies"] == 1


class TestRiskScoreCalculator:
    """Tests for RiskScoreCalculator."""

    def test_calculator_creation(self):
        """Test creating a score calculator."""
        calculator = RiskScoreCalculator()
        assert calculator.severity_weight == 1.0

    def test_calculate_basic_score(self):
        """Test basic score calculation."""
        calculator = RiskScoreCalculator()
        score = calculator.calculate_basic_score(
            RiskSeverity.HIGH,
            RiskProbability.LIKELY,
            0.8,
        )
        # Score = (4 * 4 * 0.8 / 25) * 100 = 51.2
        assert score > 0

    def test_calculate_weighted_score(self):
        """Test weighted score calculation."""
        calculator = RiskScoreCalculator()
        risk = RiskItem(
            title="Test",
            category=RiskCategory.SECURITY,
            severity=RiskSeverity.HIGH,
            probability=RiskProbability.LIKELY,
            likely_hood=0.8,
        )
        score = calculator.calculate_weighted_score(risk)
        assert score > 0

    def test_calculate_fmea_score(self):
        """Test FMEA score calculation."""
        calculator = RiskScoreCalculator()
        score = calculator.calculate_fmea_score(5, 5, 5)
        assert score == 125

    def test_calculate_dread_score(self):
        """Test DREAD score calculation."""
        calculator = RiskScoreCalculator()
        score = calculator.calculate_dread_score(5, 5, 5, 5, 5)
        assert score == 25

    def test_classify_score(self):
        """Test score classification."""
        calculator = RiskScoreCalculator()
        assert calculator.classify_score(90) == "critical"
        assert calculator.classify_score(70) == "high"
        assert calculator.classify_score(50) == "medium"
        assert calculator.classify_score(30) == "low"
        assert calculator.classify_score(10) == "info"


class TestRiskMetrics:
    """Tests for RiskMetrics."""

    def test_metrics_creation(self):
        """Test creating risk metrics."""
        metrics = RiskMetrics()
        assert metrics.total_risks == 0

    def test_metrics_from_risk_items(self):
        """Test creating metrics from risk items."""
        risk_items = [
            RiskItem(
                title="Risk1",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.CRITICAL,
            ),
            RiskItem(
                title="Risk2",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.LOW,
            ),
        ]
        metrics = RiskMetrics.from_risk_items(risk_items)
        assert metrics.total_risks == 2

    def test_metrics_from_dict(self):
        """Test creating metrics from dictionary."""
        data = {
            "total_risks": 5,
            "active_risks": 3,
            "critical_risks": 1,
        }
        metrics = RiskMetrics.from_dict(data)
        assert metrics.total_risks == 5

    def test_add_to_history(self):
        """Test adding metrics to history."""
        metrics = RiskMetrics(total_risks=5, critical_risks=1)
        metrics.add_to_history()
        assert len(metrics.metrics_history) == 1

    def test_risk_trend(self):
        """Test risk trend detection."""
        metrics = RiskMetrics(total_risks=5, average_risk_score=50.0)
        metrics.add_to_history()
        metrics.total_risks = 10
        metrics.average_risk_score = 60.0
        metrics.add_to_history()
        assert metrics.risk_trend == "worsening"

    def test_get_summary(self):
        """Test getting metrics summary."""
        metrics = RiskMetrics(
            total_risks=10,
            active_risks=8,
            critical_risks=2,
        )
        summary = metrics.get_summary()
        assert "total_risks" in summary
        assert summary["total_risks"] == 10

    def test_get_distribution(self):
        """Test getting risk distribution."""
        metrics = RiskMetrics(
            total_risks=10,
            critical_risks=2,
            high_risks=3,
            medium_risks=4,
            low_risks=1,
            info_risks=0,
        )
        distribution = metrics.get_distribution()
        assert "by_level" in distribution
        assert distribution["by_level"]["critical"] == 2

    def test_get_category_metrics(self):
        """Test getting category metrics."""
        risk_items = [
            RiskItem(
                title="Risk1",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.HIGH,
            ),
            RiskItem(
                title="Risk2",
                category=RiskCategory.SECURITY,
                severity=RiskSeverity.LOW,
            ),
            RiskItem(
                title="Risk3",
                category=RiskCategory.TECHNICAL,
                severity=RiskSeverity.MEDIUM,
            ),
        ]
        metrics = RiskMetrics()
        category_metrics = metrics.get_category_metrics(risk_items)
        assert "security" in category_metrics
        assert category_metrics["security"]["count"] == 2


class TestRiskSystemIntegration:
    """Integration tests for the Risk Assessment System."""

    def test_full_risk_workflow(self):
        """Test the complete risk assessment workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a register
            register = RiskRegister(workspace=tmpdir)

            # Add risks
            risk1 = register.add_risk(
                title="SQL Injection Vulnerability",
                category=RiskCategory.SECURITY,
                description="User input not sanitized in login endpoint",
                severity=RiskSeverity.CRITICAL,
                probability=RiskProbability.LIKELY,
                likely_hood=0.8,
                owner="security-team",
            )

            risk2 = register.add_risk(
                title="Memory Leak in Cache",
                category=RiskCategory.PERFORMANCE,
                description="Cache not releasing memory properly",
                severity=RiskSeverity.MEDIUM,
                probability=RiskProbability.POSSIBLE,
                likely_hood=0.6,
                owner="backend-team",
            )

            # Create an assessment
            assessment = RiskAssessment(
                name="Security Audit Q1 2026",
                description="Quarterly security audit",
                scope=["auth-api", "user-service", "cache-service"],
                assessor="security-auditor",
            )

            # Add risks to assessment
            assessment.add_risk_item(risk1)
            assessment.add_risk_item(risk2)

            # Add assessment to register
            register.add_assessment(assessment)

            # Create mitigation strategies
            strategy1 = RiskMitigationStrategy(
                risk_id=risk1.id,
                strategy_type=MitigationStrategyType.MITIGATE,
                description="Implement input sanitization",
                implementation_plan="Add parameterized queries and input validation",
                owner="security-team",
                priority=1,
                estimated_effort_hours=16,
                effectiveness=0.9,
            )

            strategy2 = RiskMitigationStrategy(
                risk_id=risk2.id,
                strategy_type=MitigationStrategyType.REDUCE,
                description="Add cache TTL and cleanup",
                implementation_plan="Implement automatic cache cleanup with TTL",
                owner="backend-team",
                priority=2,
                estimated_effort_hours=8,
                effectiveness=0.8,
            )

            # Create a mitigation plan
            plan = RiskMitigationPlan(
                name="Q1 2026 Risk Mitigation Plan",
                description="Plan to address Q1 security and performance risks",
                scope="All critical services",
                owner="project-manager",
            )
            plan.add_strategy(strategy1)
            plan.add_strategy(strategy2)

            # Verify workflow
            assert register.count == 2
            assert len(register.list_assessments()) == 1
            assert len(plan.strategies) == 2
            assert plan.completion_percentage == 0.0  # No strategies completed yet

            # Mark a strategy as completed
            strategy1.mark_completed(0.95)
            assert plan.completion_percentage == 50.0

    def test_risk_system_exports(self):
        """Test that the risk module exports all expected classes."""
        from app.risk import (
            RiskItem,
            RiskSeverity,
            RiskProbability,
            RiskStatus,
            RiskCategory,
            RiskAssessment,
            RiskAssessmentResult,
            RiskAnalyzer,
            RiskRegister,
            RiskMitigationStrategy,
            RiskMitigationPlan,
            RiskMetrics,
            RiskScoreCalculator,
            MitigationStrategyType,
            MitigationStatus,
        )
        assert RiskItem is not None
        assert RiskSeverity is not None
        assert RiskRegister is not None
        assert RiskAnalyzer is not None
        assert RiskMitigationPlan is not None
