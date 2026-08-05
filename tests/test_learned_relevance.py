"""Tests for Learned Relevance Ranking."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock

from app.world_model.retrieval import (
    TaskContext,
    filter_snapshot_for_task,
    get_relevant_context,
    get_relevant_summary,
    list_supported_task_types,
    get_task_type_description,
    record_retrieval_outcome,
    get_learned_relevance_summary,
    get_all_learned_relevance,
    reset_learned_relevance,
    init_learned_relevance,
    TASK_TYPES,
    TASK_RELEVANCE,
    FIELD_RELEVANCE,
)
from app.world_model.learned_relevance import (
    LearnedRelevanceEngine,
    TaskRelevanceWeights,
    RetrievalOutcome,
    create_learned_relevance_engine,
)
from app.world_model.model import (
    EnvironmentSnapshot,
    ProjectInfo,
    RuntimeInfo,
    GitInfo,
    ResourceInfo,
    ToolInfo,
    HealthInfo,
)


def create_test_snapshot() -> EnvironmentSnapshot:
    """Create a test environment snapshot."""
    return EnvironmentSnapshot(
        snapshot_id="test_snap_1",
        timestamp="2026-01-01T00:00:00",
        project=ProjectInfo(
            name="test_project",
            main_language="python",
            build_system="pip",
            framework="fastapi",
            config_files=["pyproject.toml"],
            entry_points=["main.py"],
            file_count=100,
            total_lines=5000,
        ),
        runtime=RuntimeInfo(
            os_name="Linux",
            os_version="Ubuntu 22.04",
            os_family="linux",
            shell_name="bash",
            shell_path="/bin/bash",
            python_version="3.12.0",
            python_major=3,
            python_minor=12,
            python_patch=0,
            python_executable="/usr/bin/python3",
            working_directory="/home/user/project",
            environment={},
        ),
        git=GitInfo(
            is_repo=True,
            current_branch="main",
            is_clean=False,
            has_changes=True,
            ahead=2,
            behind=1,
            remotes=["origin"],
            status="M file1.py",
        ),
        resources=ResourceInfo(
            cpu_percent=45.0,
            cpu_count=8,
            cpu_freq_mhz=3000.0,
            memory_total_gb=32.0,
            memory_used_gb=16.0,
            memory_free_gb=16.0,
            memory_percent=50.0,
            disk_total_gb=500.0,
            disk_used_gb=250.0,
            disk_free_gb=250.0,
            disk_percent=50.0,
            disk_read_mb=100.0,
            disk_write_mb=50.0,
            net_sent_mb=10.0,
            net_recv_mb=20.0,
            process_count=150,
            thread_count=300,
            temperature_celsius=45.0,
            load_avg_1min=1.5,
            load_avg_5min=1.2,
            load_avg_15min=1.0,
            health_score=85.0,
            health_status="healthy",
        ),
        tools=ToolInfo(
            available_tools=["git", "python", "docker", "npm"],
            tool_versions={"git": "2.34", "python": "3.12", "docker": "24.0"},
            git_available=True,
            python_available=True,
            node_available=False,
            docker_available=True,
            npm_available=True,
        ),
        health=HealthInfo(
            overall_status="healthy",
            health_score=85.0,
            metrics_count=10,
            alerts_count=0,
            code_quality=80.0,
            test_metrics=90.0,
            performance_metrics=85.0,
        ),
    )


class TestLearnedRelevanceEngine:
    """Test the LearnedRelevanceEngine class."""

    def test_engine_creation(self):
        """Test creating a learned relevance engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_learned_relevance_engine(storage_path=Path(tmpdir) / "relevance.json")
            assert engine is not None
            assert engine.min_samples == 5
            assert engine.learning_rate == 0.1

    def test_initial_weights_from_static(self):
        """Test that initial weights are derived from static mapping."""
        engine = LearnedRelevanceEngine()

        # Check all task types have weights
        for task_type in ["build", "test", "deploy", "debug", "refactor", "develop", "analyze", "install", "lint"]:
            weights = engine._learned_weights.get(task_type)
            assert weights is not None
            assert weights.task_type == task_type
            assert weights.sample_count == 0
            assert weights.confidence == 0.0

            # Check layer weights are initialized from static mapping
            relevant_layers = TASK_RELEVANCE[task_type]
            for layer in relevant_layers:
                assert layer in weights.layer_weights
                assert weights.layer_weights[layer] > 0

    def test_get_layer_relevance_static_fallback(self):
        """Test layer relevance falls back to static when no learning data."""
        engine = LearnedRelevanceEngine()

        # For build task, project layer should be relevant
        score = engine.get_layer_relevance("build", "project")
        assert score == 1.0  # Static relevant

        # For build task, health layer is also in static mapping
        score = engine.get_layer_relevance("build", "health")
        assert score == 1.0

        # For unknown layer not in static mapping
        score = engine.get_layer_relevance("build", "nonexistent_layer")
        assert score == 0.0

    def test_get_field_relevance_static_fallback(self):
        """Test field relevance falls back to static when no learning data."""
        engine = LearnedRelevanceEngine()

        # For build task, project.name should be relevant
        score = engine.get_field_relevance("build", "project", "name")
        assert score == 1.0

        # For build task, project.framework is not in static mapping for build
        score = engine.get_field_relevance("build", "project", "framework")
        assert score == 0.0

    def test_record_outcome_updates_weights(self):
        """Test that recording outcomes updates learned weights."""
        engine = LearnedRelevanceEngine()

        # Record several successful outcomes for 'build' task with project layer
        for i in range(10):
            outcome = RetrievalOutcome(
                task_type="build",
                query="build script",
                retrieved_layers=["project", "runtime"],
                retrieved_fields={
                    "project": ["name", "build_system"],
                    "runtime": ["family"],
                },
                success=True,
            )
            engine.record_outcome(outcome)

        # Process any buffered outcomes
        engine._process_outcomes()

        # Check that weights have been updated
        weights = engine._learned_weights["build"]
        assert weights.sample_count > 0
        assert weights.confidence > 0.0

        # Project layer should have higher weight due to success
        project_weight = weights.layer_weights.get("project", 0)
        assert project_weight > 0

    def test_record_mixed_outcomes(self):
        """Test that mixed success/failure outcomes are handled correctly."""
        engine = LearnedRelevanceEngine()

        # Record mixed outcomes - project succeeds, runtime fails
        for i in range(10):
            outcome = RetrievalOutcome(
                task_type="test",
                query="run tests",
                retrieved_layers=["project", "runtime"],
                retrieved_fields={
                    "project": ["name", "framework"],
                    "runtime": ["family"],
                },
                success=True,  # project success
            )
            engine.record_outcome(outcome)

        for i in range(10):
            outcome = RetrievalOutcome(
                task_type="test",
                query="run tests",
                retrieved_layers=["runtime"],
                retrieved_fields={"runtime": ["family", "version"]},
                success=False,  # runtime failure
            )
            engine.record_outcome(outcome)

        engine._process_outcomes()

        weights = engine._learned_weights["test"]
        assert weights.sample_count > 0

    def test_persistence(self):
        """Test that learned weights are persisted to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "relevance.json"
            engine = create_learned_relevance_engine(storage_path=storage_path)

            # Record some outcomes
            for i in range(10):
                outcome = RetrievalOutcome(
                    task_type="deploy",
                    query="deploy app",
                    retrieved_layers=["project", "git"],
                    retrieved_fields={"project": ["name"], "git": ["current_branch"]},
                    success=True,
                )
                engine.record_outcome(outcome)

            engine._save()

            # Create new engine and load
            engine2 = create_learned_relevance_engine(storage_path=storage_path)
            assert "deploy" in engine2._learned_weights
            weights = engine2._learned_weights["deploy"]
            assert weights.sample_count > 0

    def test_get_relevant_layers_ranked(self):
        """Test getting relevant layers ranked by learned relevance."""
        engine = LearnedRelevanceEngine()

        # Initially should return static layers
        layers = engine.get_relevant_layers("build")
        assert "project" in layers
        assert "runtime" in layers
        assert len(layers) == 6  # All static layers for build

    def test_get_relevant_fields_ranked(self):
        """Test getting relevant fields ranked by learned relevance."""
        engine = LearnedRelevanceEngine()

        # Initially should return static fields
        fields = engine.get_relevant_fields("build", "project")
        assert "name" in fields
        assert "build_system" in fields
        assert "config_files" in fields

    def test_reset_task_weights(self):
        """Test resetting learned weights to static defaults."""
        engine = LearnedRelevanceEngine()

        # Record some outcomes to change weights
        for i in range(10):
            outcome = RetrievalOutcome(
                task_type="debug",
                query="debug issue",
                retrieved_layers=["project", "git"],
                retrieved_fields={"project": ["name"], "git": ["has_changes"]},
                success=True,
            )
            engine.record_outcome(outcome)

        engine._process_outcomes()

        # Reset
        engine.reset_task_weights("debug")

        # Should be back to static defaults
        weights = engine._learned_weights["debug"]
        assert weights.sample_count == 0
        assert weights.confidence == 0.0

        # Layer weights should be uniform from static
        relevant_layers = TASK_RELEVANCE["debug"]
        expected_weight = 1.0 / len(relevant_layers)
        for layer in relevant_layers:
            assert abs(weights.layer_weights[layer] - expected_weight) < 0.01

    def test_weight_summary(self):
        """Test getting weight summary."""
        engine = LearnedRelevanceEngine()

        summary = engine.get_weight_summary("analyze")
        assert summary["task_type"] == "analyze"
        assert summary["learned"] is True
        assert "layer_weights" in summary
        assert "field_weights" in summary
        assert summary["sample_count"] == 0
        assert summary["confidence"] == 0.0

    def test_unknown_task_type(self):
        """Test handling of unknown task type."""
        engine = LearnedRelevanceEngine()

        # Unknown task type should fall back to unknown static mapping
        score = engine.get_layer_relevance("unknown", "project")
        assert score == 1.0  # project is in unknown mapping

        score = engine.get_layer_relevance("unknown", "nonexistent")
        assert score == 0.0


class TestLearnedRelevanceIntegration:
    """Test integration with retrieval functions."""

    def test_filter_snapshot_uses_learned(self):
        """Test that filter_snapshot_for_task can use learned relevance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize engine with storage
            storage_path = Path(tmpdir) / "relevance.json"
            engine = init_learned_relevance(storage_path=storage_path)

            snapshot = create_test_snapshot()

            # Filter with learned relevance (should work even with no data)
            filtered = filter_snapshot_for_task(
                snapshot,
                "build",
                use_learned=True,
                relevance_threshold=0.3,
            )

            assert filtered is not None
            assert filtered.project is not None
            assert filtered.runtime is not None

    def test_filter_snapshot_static_fallback(self):
        """Test that filter_snapshot_for_task falls back to static when learned unavailable."""
        snapshot = create_test_snapshot()

        # Filter without learned relevance
        filtered = filter_snapshot_for_task(
            snapshot,
            "test",
            use_learned=False,
        )

        assert filtered is not None
        assert filtered.project is not None
        assert filtered.runtime is not None

    def test_get_relevant_context_with_learned(self):
        """Test get_relevant_context with learned relevance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_learned_relevance(storage_path=Path(tmpdir) / "relevance.json")

            snapshot = create_test_snapshot()
            task_context = TaskContext.from_string("deploy")

            context = get_relevant_context(
                snapshot,
                task_context,
                use_learned=True,
            )

            assert "task_type" in context
            assert context["task_type"] == "deploy"
            assert "project" in context
            assert "runtime" in context

    def test_get_relevant_summary_with_learned(self):
        """Test get_relevant_summary with learned relevance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_learned_relevance(storage_path=Path(tmpdir) / "relevance.json")

            snapshot = create_test_snapshot()

            summary = get_relevant_summary(
                snapshot,
                "lint",
                use_learned=True,
            )

            assert "Environment (lint)" in summary
            assert "Project:" in summary

    def test_record_retrieval_outcome(self):
        """Test recording retrieval outcome for learning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_learned_relevance(storage_path=Path(tmpdir) / "relevance.json")

            record_retrieval_outcome(
                task_type="install",
                query="install dependencies",
                retrieved_layers=["project", "runtime"],
                retrieved_fields={"project": ["config_files"], "runtime": ["working_directory"]},
                success=True,
                user_feedback="positive",
            )

            # Check summary updated
            summary = get_learned_relevance_summary("install")
            assert summary["learned"] is True

    def test_get_all_learned_relevance(self):
        """Test getting all learned relevance weights."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_learned_relevance(storage_path=Path(tmpdir) / "relevance.json")

            all_weights = get_all_learned_relevance()

            assert isinstance(all_weights, dict)
            assert "build" in all_weights
            assert "test" in all_weights

    def test_reset_learned_relevance(self):
        """Test resetting learned relevance for a task type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_learned_relevance(storage_path=Path(tmpdir) / "relevance.json")

            # Record some outcomes
            record_retrieval_outcome(
                task_type="refactor",
                query="refactor code",
                retrieved_layers=["project"],
                retrieved_fields={"project": ["name"]},
                success=True,
            )

            # Reset
            reset_learned_relevance("refactor")

            summary = get_learned_relevance_summary("refactor")
            assert summary["sample_count"] == 0
            assert summary["confidence"] == 0.0


class TestTaskContext:
    """Test TaskContext functionality."""

    def test_from_string(self):
        """Test creating TaskContext from string."""
        ctx = TaskContext.from_string("build")
        assert ctx.task_type == "build"
        assert ctx.keywords == []

    def test_from_task_inference(self):
        """Test inferring task type from description."""
        ctx = TaskContext.from_task("Build the docker image")
        assert ctx.task_type == "build"
        assert "build" in ctx.keywords

        ctx = TaskContext.from_task("Run pytest tests")
        assert ctx.task_type == "test"

        ctx = TaskContext.from_task("Fix the bug in login")
        assert ctx.task_type == "debug"

        ctx = TaskContext.from_task("Refactor the auth module")
        assert ctx.task_type == "refactor"

        ctx = TaskContext.from_task("Analyze the performance")
        assert ctx.task_type == "analyze"

        ctx = TaskContext.from_task("Install dependencies")
        assert ctx.task_type == "install"

        ctx = TaskContext.from_task("Lint the code with ruff")
        assert ctx.task_type == "lint"

        ctx = TaskContext.from_task("General development work")
        assert ctx.task_type == "develop"

    def test_unknown_task_fallback(self):
        """Test unknown task falls back to develop."""
        ctx = TaskContext.from_task("Do something completely unknown")
        assert ctx.task_type == "develop"


class TestStaticRelevanceMappings:
    """Test that static relevance mappings are complete and consistent."""

    def test_all_task_types_have_relevance(self):
        """Test all defined task types have relevance mappings."""
        for task_type in TASK_TYPES:
            if task_type == "unknown":
                continue
            assert task_type in TASK_RELEVANCE, f"Missing TASK_RELEVANCE for {task_type}"
            assert len(TASK_RELEVANCE[task_type]) > 0, f"Empty TASK_RELEVANCE for {task_type}"

    def test_all_task_types_have_field_relevance(self):
        """Test all task types have field relevance for each layer."""
        for task_type in TASK_TYPES:
            if task_type == "unknown":
                continue
            for layer in TASK_RELEVANCE[task_type]:
                assert layer in FIELD_RELEVANCE, f"Missing FIELD_RELEVANCE layer {layer}"
                assert task_type in FIELD_RELEVANCE[layer], f"Missing field relevance for {layer}/{task_type}"
                assert len(FIELD_RELEVANCE[layer][task_type]) > 0, f"Empty field relevance for {layer}/{task_type}"

    def test_list_supported_task_types(self):
        """Test listing supported task types."""
        types = list_supported_task_types()
        assert isinstance(types, list)
        assert "build" in types
        assert "test" in types
        assert "unknown" in types

    def test_get_task_type_description(self):
        """Test getting task type descriptions."""
        assert "Building" in get_task_type_description("build")
        assert "Running tests" in get_task_type_description("test")
        assert "Unknown" in get_task_type_description("unknown")
        assert "Unknown" in get_task_type_description("nonexistent")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])