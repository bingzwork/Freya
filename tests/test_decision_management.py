"""Tests for the Decision Management System."""

import json
import tempfile
from pathlib import Path

import pytest

from app.decision.manager import (
    DecisionManager,
    DecisionManagerConfig,
    decide_context_sufficiency,
    decide_tool_selection,
    decide_recovery_action,
    decide_plan_approach,
    decide_replanning_strategy,
    get_default_manager,
)
from app.decision.models import (
    DecisionCategory,
    DecisionOption,
    DecisionType,
    DecisionRecord,
    DecisionContext,
)
from app.decision.history import DecisionHistory
from app.decision.workflow import DecisionWorkflow, WorkflowStep


class TestDecisionModels:
    """Tests for decision data models."""

    def test_decision_context_creation(self):
        """Test creating a DecisionContext."""
        ctx = DecisionContext(
            task_description="Test task",
            component="test_component",
            current_phase="planning",
        )
        assert ctx.task_description == "Test task"
        assert ctx.component == "test_component"
        assert ctx.current_phase == "planning"
        assert ctx.metadata == {}

    def test_decision_option_creation(self):
        """Test creating a DecisionOption."""
        opt = DecisionOption(
            name="test_tool",
            action="use_test_tool",
            description="Use test tool",
            decision_type=DecisionType.TOOL_SELECTION,
            category=DecisionCategory.EXECUTION,
            estimated_success=0.8,
            estimated_effort=0.3,
            estimated_impact=0.6,
        )
        assert opt.name == "test_tool"
        assert opt.decision_type == DecisionType.TOOL_SELECTION
        assert opt.category == DecisionCategory.EXECUTION
        # confidence_score is not a field - estimated_success is used instead
        assert opt.estimated_success == 0.8

    def test_decision_record_serialization(self):
        """Test DecisionRecord serialization."""
        record = DecisionRecord(
            record_id="test-123",
            decision_id="decision-456",
            decision_type=DecisionType.TOOL_SELECTION,
            category=DecisionCategory.EXECUTION,
            task_description="Test task",
            component="test",
            chosen_option_name="tool_a",
            chosen_option_action="use_tool_a",
            confidence=0.85,
            risk_level="low",
            rationale="Test rationale",
        )
        data = record.to_dict()
        assert data["record_id"] == "test-123"
        assert data["confidence"] == 0.85
        assert data["chosen_option_name"] == "tool_a"

        # Round-trip
        restored = DecisionRecord.from_dict(data)
        assert restored.record_id == "test-123"
        assert restored.confidence == 0.85


class TestDecisionHistory:
    """Tests for DecisionHistory persistence."""

    def test_add_and_query_records(self):
        """Test adding and querying decision records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = DecisionHistory(workspace=tmpdir, storage_path="test_history.json")

            record = DecisionRecord(
                record_id="rec-1",
                decision_id="dec-1",
                decision_type=DecisionType.TOOL_SELECTION,
                category=DecisionCategory.EXECUTION,
                task_description="Test task",
                component="executor",
                chosen_option_name="read_file",
                chosen_option_action="read_file",
                confidence=0.8,
                risk_level="low",
                rationale="Need to read file",
            )
            history.add_record(record)

            # Query by type
            results = history.query(decision_type=DecisionType.TOOL_SELECTION)
            assert len(results) == 1
            assert results[0].decision_type == DecisionType.TOOL_SELECTION

            # Query by category
            results = history.query(category=DecisionCategory.EXECUTION)
            assert len(results) == 1

            # Query by component
            results = history.query(component="executor")
            assert len(results) == 1

    def test_record_outcome(self):
        """Test recording outcomes for decisions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = DecisionHistory(workspace=tmpdir, storage_path="test_history.json")

            record = DecisionRecord(
                record_id="rec-1",
                decision_id="dec-1",
                decision_type=DecisionType.TOOL_SELECTION,
                category=DecisionCategory.EXECUTION,
                task_description="Test task",
                component="executor",
                chosen_option_name="read_file",
                chosen_option_action="read_file",
                confidence=0.8,
                risk_level="low",
                rationale="Test",
            )
            history.add_record(record)

            # Record outcome
            success = history.record_outcome(
                decision_id="dec-1",
                outcome="success",
                outcome_details="File read successfully",
                actual_success=True,
                actual_effort=0.2,
                actual_impact=0.8,
                lesson_learned="File reading works well",
                would_repeat=True,
            )
            assert success is True

            updated = history.get_decision("dec-1")
            assert updated is not None
            assert updated.outcome == "success"
            assert updated.actual_success is True
            assert "File reading works well" in updated.lesson_learned

    def test_summary_statistics(self):
        """Test summary statistics generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = DecisionHistory(workspace=tmpdir, storage_path="test_history.json")

            for i in range(5):
                record = DecisionRecord(
                    record_id=f"rec-{i}",
                    decision_id=f"dec-{i}",
                    decision_type=DecisionType.TOOL_SELECTION if i % 2 == 0 else DecisionType.CONTEXT_SUFFICIENCY,
                    category=DecisionCategory.EXECUTION if i % 2 == 0 else DecisionCategory.INFORMATION,
                    task_description=f"Task {i}",
                    component="executor",
                    chosen_option_name=f"option_{i}",
                    chosen_option_action=f"action_{i}",
                    confidence=0.5 + i * 0.1,
                    risk_level="low" if i < 3 else "medium",
                    rationale="Test",
                )
                history.add_record(record)

            summary = history.get_summary()
            assert summary["total_records"] == 5
            assert summary["average_confidence"] > 0.5
            assert "by_type" in summary
            assert "by_category" in summary


class TestDecisionWorkflow:
    """Tests for the DecisionWorkflow."""

    def test_workflow_execution(self):
        """Test basic workflow execution."""
        workflow = DecisionWorkflow()

        context = DecisionContext(
            task_description="Read a file",
            component="executor",
        )

        options = [
            DecisionOption(
                name="read_file",
                action="read_file",
                description="Read the file",
                decision_type=DecisionType.TOOL_SELECTION,
                category=DecisionCategory.EXECUTION,
                estimated_success=0.9,
                estimated_effort=0.2,
                estimated_impact=0.7,
            ),
            DecisionOption(
                name="write_file",
                action="write_file",
                description="Write the file",
                decision_type=DecisionType.TOOL_SELECTION,
                category=DecisionCategory.EXECUTION,
                estimated_success=0.8,
                estimated_effort=0.3,
                estimated_impact=0.6,
            ),
        ]

        result = workflow.execute(context, options)
        assert result is not None
        assert result.chosen_option is not None
        assert result.chosen_option.name in ["read_file", "write_file"]
        assert result.confidence > 0

    def test_workflow_step_order(self):
        """Test that workflow steps are defined correctly."""
        workflow = DecisionWorkflow()

        assert len(workflow.steps) == 6
        assert workflow.steps[0].name == WorkflowStep.OBSERVE.value
        assert workflow.steps[1].name == WorkflowStep.GATHER_CONTEXT.value
        assert workflow.steps[2].name == WorkflowStep.IDENTIFY_ACTIONS.value
        assert workflow.steps[3].name == WorkflowStep.EVALUATE_OPTIONS.value
        assert workflow.steps[4].name == WorkflowStep.CHOOSE_BEST.value
        assert workflow.steps[5].name == WorkflowStep.LEARN_OUTCOME.value


class TestDecisionManager:
    """Tests for the DecisionManager."""

    def test_manager_initialization(self):
        """Test DecisionManager initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)
            assert manager is not None
            assert manager.config is not None
            assert manager.workflow is not None
            assert manager.history is not None

    def test_decide_simple(self):
        """Test simplified decision interface."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            options = [
                DecisionOption(
                    name="option_a",
                    action="do_a",
                    description="Option A",
                    decision_type=DecisionType.TOOL_SELECTION,
                    category=DecisionCategory.EXECUTION,
                    estimated_success=0.8,
                    estimated_effort=0.3,
                    estimated_impact=0.7,
                ),
                DecisionOption(
                    name="option_b",
                    action="do_b",
                    description="Option B",
                    decision_type=DecisionType.TOOL_SELECTION,
                    category=DecisionCategory.EXECUTION,
                    estimated_success=0.6,
                    estimated_effort=0.2,
                    estimated_impact=0.5,
                ),
            ]

            result = manager.decide_simple(
                decision_type=DecisionType.TOOL_SELECTION,
                task_description="Test task",
                options=options,
                component="test",
            )

            assert result is not None
            assert result.chosen_option is not None
            assert result.chosen_option.name in ["option_a", "option_b"]

    def test_explain_decision(self):
        """Test decision explanation generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            options = [
                DecisionOption(
                    name="test_tool",
                    action="use_test_tool",
                    description="Use test tool",
                    decision_type=DecisionType.TOOL_SELECTION,
                    category=DecisionCategory.EXECUTION,
                    estimated_success=0.8,
                    estimated_effort=0.3,
                    estimated_impact=0.7,
                ),
            ]

            result = manager.decide_simple(
                decision_type=DecisionType.TOOL_SELECTION,
                task_description="Test task",
                options=options,
                component="test",
            )

            explanation = manager.explain_decision(result)
            assert "Decision:" in explanation
            assert "Confidence:" in explanation
            assert "Rationale:" in explanation

    def test_record_outcome(self):
        """Test recording decision outcomes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            options = [
                DecisionOption(
                    name="test_action",
                    action="test_action",
                    description="Test",
                    decision_type=DecisionType.TOOL_SELECTION,
                    category=DecisionCategory.EXECUTION,
                    estimated_success=0.8,
                    estimated_effort=0.3,
                    estimated_impact=0.7,
                ),
            ]

            result = manager.decide_simple(
                decision_type=DecisionType.TOOL_SELECTION,
                task_description="Test task",
                options=options,
                component="test",
            )

            manager.record_outcome(
                decision_id=result.decision_id,
                outcome="success",
                outcome_details="Completed successfully",
                actual_success=True,
                lesson_learned="Test action works",
                would_repeat=True,
            )

            record = manager.history.get_decision(result.decision_id)
            assert record.outcome == "success"
            assert record.actual_success is True


class TestConvenienceFunctions:
    """Tests for convenience decision functions."""

    def test_decide_context_sufficiency(self):
        """Test context sufficiency decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            result = decide_context_sufficiency(
                manager=manager,
                task="Read file and analyze",
                current_context="File content: hello world",
                intent_type="file_read",
            )

            assert result is not None
            assert result.chosen_option is not None
            assert result.decision_type == DecisionType.CONTEXT_SUFFICIENCY

    def test_decide_tool_selection(self):
        """Test tool selection decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            result = decide_tool_selection(
                manager=manager,
                task="Read a Python file",
                available_tools=["read_file", "write_file", "run_terminal"],
                context={"active_goal_id": "goal-1"},
            )

            assert result is not None
            assert result.chosen_option is not None
            assert result.chosen_option.name in ["read_file", "write_file", "run_terminal"]

    def test_decide_recovery_action(self):
        """Test recovery action decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            result = decide_recovery_action(
                manager=manager,
                task="Apply patch",
                failure_reason="Patch conflict",
                attempt_number=1,
                max_attempts=3,
            )

            assert result is not None
            assert result.chosen_option is not None
            # Recovery decisions can be RETRY_WITH_ALTERNATIVE, PAUSE_AND_ASK, or ABORT_TASK
            # depending on the situation - all are valid
            assert result.decision_type in (
                DecisionType.RETRY_WITH_ALTERNATIVE,
                DecisionType.PAUSE_AND_ASK,
                DecisionType.ABORT_TASK,
            )

    def test_decide_plan_approach(self):
        """Test planning approach decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            result = decide_plan_approach(
                manager=manager,
                task="Refactor module",
                context="Module has 500 lines, needs splitting",
                goal_id="goal-1",
                goal_name="Refactor large module",
            )

            assert result is not None
            assert result.chosen_option is not None
            assert result.decision_type == DecisionType.STRATEGY_SELECTION

    def test_decide_replanning_strategy(self):
        """Test replanning strategy decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DecisionManager(workspace=tmpdir)

            result = decide_replanning_strategy(
                manager=manager,
                failed_task="Apply refactoring patch",
                failure_context="Merge conflict in main.py",
                original_task="Refactor user authentication module",
            )

            assert result is not None
            assert result.chosen_option is not None
            assert result.decision_type == DecisionType.RETRY_WITH_ALTERNATIVE

    def test_get_default_manager(self):
        """Test global default manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager1 = get_default_manager(tmpdir)
            manager2 = get_default_manager(tmpdir)
            # Should return the same instance
            assert manager1 is manager2


class TestCategoryHandlers:
    """Tests for category-specific decision handlers."""

    def test_execution_handler_high_risk(self):
        """Test execution handler adds approval for high risk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DecisionManagerConfig(enable_human_oversight=True)
            manager = DecisionManager(workspace=tmpdir, config=config)

            options = [
                DecisionOption(
                    name="dangerous_tool",
                    action="run_dangerous",
                    description="Dangerous operation",
                    decision_type=DecisionType.COMMAND_EXECUTION,
                    category=DecisionCategory.EXECUTION,
                    estimated_success=0.9,
                    estimated_effort=0.5,
                    estimated_impact=0.8,
                    risk_level="high",
                ),
            ]

            context = DecisionContext(
                task_description="Run dangerous command",
                component="executor",
            )

            result = manager.decide(context, options)
            # High risk should require human approval
            assert result.requires_approval is True
            assert result.should_execute is False

    def test_information_handler_low_confidence(self):
        """Test information handler with low confidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DecisionManagerConfig(min_confidence_for_recommendation=0.6)
            manager = DecisionManager(workspace=tmpdir, config=config)

            options = [
                DecisionOption(
                    name="gather_more",
                    action="gather_more_context",
                    description="Gather more info",
                    decision_type=DecisionType.CONTEXT_SUFFICIENCY,
                    category=DecisionCategory.INFORMATION,
                    estimated_success=0.5,  # Low confidence
                    estimated_effort=0.3,
                    estimated_impact=0.5,
                ),
                DecisionOption(
                    name="proceed",
                    action="proceed_with_execution",
                    description="Proceed anyway",
                    decision_type=DecisionType.CONTEXT_SUFFICIENCY,
                    category=DecisionCategory.INFORMATION,
                    estimated_success=0.3,
                    estimated_effort=0.1,
                    estimated_impact=0.4,
                ),
            ]

            context = DecisionContext(
                task_description="Check context",
                component="agent",
            )

            result = manager.decide(context, options)
            # Low confidence should not auto-execute
            assert result.should_execute is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])