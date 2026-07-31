"""Tests for World Model functionality."""

import json
import tempfile
import time
from pathlib import Path

from app.world_model.model import (
    EnvironmentSnapshot,
    ProjectInfo,
    RuntimeInfo,
    GitInfo,
    ResourceInfo,
    ToolInfo,
    HealthInfo,
    WorldModel,
    create_world_model,
)
from app.world_model.retrieval import (
    TaskContext,
    get_relevant_context,
    filter_snapshot_for_task,
    get_relevant_summary,
    list_supported_task_types,
)


class TestSnapshotModels:
    """Test the snapshot data models."""

    def test_project_info_serialization(self):
        """Test ProjectInfo round-trip serialization."""
        project = ProjectInfo(
            name="TestProject",
            root_path="/tmp/test",
            is_git_repo=True,
            file_count=10,
            total_lines=500,
            main_language="Python",
            framework="FastAPI",
            build_system="pip",
            entry_points=["main.py"],
            config_files=["pyproject.toml"],
        )
        data = project.to_dict()
        assert data["name"] == "TestProject"
        assert data["file_count"] == 10
        assert data["framework"] == "FastAPI"

    def test_runtime_info_serialization(self):
        """Test RuntimeInfo round-trip serialization."""
        runtime = RuntimeInfo(
            os_name="Windows",
            os_family="windows",
            shell_name="powershell",
            python_version="3.11.0",
            python_major=3,
            python_minor=11,
            python_patch=0,
            python_executable="python.exe",
            working_directory="/tmp/test",
            environment={"PATH": "/usr/bin"},
        )
        data = runtime.to_dict()
        assert data["os"]["family"] == "windows"
        assert data["python"]["version"] == "3.11.0"

    def test_git_info_serialization(self):
        """Test GitInfo round-trip serialization."""
        git = GitInfo(
            is_repo=True,
            is_clean=False,
            current_branch="main",
            branches=[{"name": "main"}],
            remotes=["origin"],
            ahead=2,
            behind=1,
            has_changes=True,
        )
        data = git.to_dict()
        assert data["is_repo"] is True
        assert data["current_branch"] == "main"
        assert data["ahead"] == 2

    def test_resource_info_serialization(self):
        """Test ResourceInfo round-trip serialization."""
        res = ResourceInfo(
            cpu_percent=50.0,
            cpu_count=8,
            memory_total_gb=16.0,
            memory_used_gb=8.0,
            memory_percent=50.0,
            disk_percent=30.0,
            health_score=85.0,
            health_status="good",
        )
        data = res.to_dict()
        assert data["cpu"]["percent"] == 50.0
        assert data["health_score"] == 85.0

    def test_tool_info_serialization(self):
        """Test ToolInfo round-trip serialization."""
        tools = ToolInfo(
            available_tools=["read_file", "write_file", "git_status"],
            tool_versions={"git": "2.40.0", "python": "3.11.0"},
            git_available=True,
            python_available=True,
        )
        data = tools.to_dict()
        assert "read_file" in data["available_tools"]
        assert data["git_available"] is True

    def test_health_info_serialization(self):
        """Test HealthInfo round-trip serialization."""
        health = HealthInfo(
            overall_status="excellent",
            health_score=95.0,
            metrics_count=15,
            alerts_count=0,
            code_quality={"pep8_compliance": {"value": 95, "status": "excellent"}},
        )
        data = health.to_dict()
        assert data["overall_status"] == "excellent"
        assert data["health_score"] == 95.0

    def test_environment_snapshot_serialization(self):
        """Test full EnvironmentSnapshot round-trip serialization."""
        snap = EnvironmentSnapshot(
            snapshot_id="test_123",
            elapsed_ms=150.5,
            project=ProjectInfo(name="Test", root_path="/tmp", file_count=5),
            runtime=RuntimeInfo(os_family="linux", python_version="3.11"),
            git=GitInfo(is_repo=True, current_branch="main"),
            resources=ResourceInfo(cpu_percent=10.0, health_status="excellent"),
            tools=ToolInfo(available_tools=["test_tool"]),
            health=HealthInfo(overall_status="good", health_score=80.0),
        )

        # Test to_dict
        data = snap.to_dict()
        assert data["snapshot_id"] == "test_123"
        assert data["project"]["name"] == "Test"
        assert data["elapsed_ms"] == 150.5

        # Test to_json
        json_str = snap.to_json()
        assert "test_123" in json_str
        assert "Test" in json_str

        # Test from_dict
        restored = EnvironmentSnapshot.from_dict(data)
        assert restored.snapshot_id == "test_123"
        assert restored.project.name == "Test"
        assert restored.runtime.os_family == "linux"
        assert restored.git.current_branch == "main"
        assert restored.health.health_score == 80.0

    def test_environment_snapshot_summary_text(self):
        """Test snapshot summary text generation."""
        snap = EnvironmentSnapshot(
            project=ProjectInfo(name="TestProj", root_path="/tmp", main_language="Python"),
            runtime=RuntimeInfo(os_family="linux", python_version="3.11"),
            git=GitInfo(is_repo=True, current_branch="main", is_clean=True),
            resources=ResourceInfo(cpu_percent=10.0, memory_percent=40.0, disk_percent=20.0, health_status="excellent"),
            tools=ToolInfo(git_available=True, python_available=True),
            health=HealthInfo(overall_status="excellent", health_score=90.0),
        )

        summary = snap.get_summary_text()
        assert "TestProj" in summary
        assert "Python" in summary
        assert "main" in summary
        assert "excellent" in summary
        assert "90" in summary


class TestWorldModel:
    """Test the WorldModel facade."""

    def test_world_model_creation(self):
        """Test WorldModel can be created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            assert wm is not None
            assert wm.workspace == Path(tmpdir).resolve()

    def test_get_snapshot_basic(self):
        """Test getting a basic snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            snapshot = wm.get_snapshot()

            assert isinstance(snapshot, EnvironmentSnapshot)
            assert Path(snapshot.project.root_path).resolve() == Path(tmpdir).resolve()
            assert snapshot.runtime.python_version != ""
            assert snapshot.tools.available_tools  # Should have default tools
            assert snapshot.snapshot_id != ""

    def test_snapshot_caching(self):
        """Test that snapshots are cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            snap1 = wm.get_snapshot()
            snap2 = wm.get_snapshot()

            # Should return cached snapshot
            assert snap1.snapshot_id == snap2.snapshot_id

    def test_force_refresh(self):
        """Test force_refresh bypasses cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            snap1 = wm.get_snapshot()
            time.sleep(0.01)  # Small delay
            snap2 = wm.refresh()

            # Should be different snapshot IDs
            assert snap1.snapshot_id != snap2.snapshot_id

    def test_get_project_info(self):
        """Test getting project info only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            info = wm.get_project_info()

            assert isinstance(info, ProjectInfo)
            assert info.root_path == str(Path(tmpdir).resolve())

    def test_get_git_status(self):
        """Test getting git status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            git_info = wm.get_git_status()

            assert isinstance(git_info, GitInfo)
            # Not a git repo by default
            assert git_info.is_repo is False

    def test_get_resource_summary(self):
        """Test getting resource summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            res = wm.get_resource_summary()

            assert isinstance(res, ResourceInfo)
            assert res.cpu_count > 0
            assert res.memory_total_gb > 0

    def test_get_available_tools(self):
        """Test getting available tools."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            tools = wm.get_available_tools()

            assert isinstance(tools, ToolInfo)
            assert "read_file" in tools.available_tools
            assert "write_file" in tools.available_tools
            assert "run_terminal" in tools.available_tools

    def test_get_health_status(self):
        """Test getting health status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            health = wm.get_health_status()

            assert isinstance(health, HealthInfo)
            assert health.overall_status in ["unknown", "excellent", "good", "fair", "poor", "critical"]

    def test_get_runtime_context(self):
        """Test getting runtime context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            runtime = wm.get_runtime_context()

            assert isinstance(runtime, RuntimeInfo)
            assert runtime.os_family in ["windows", "linux", "macos"]
            assert runtime.python_version != ""

    def test_is_healthy(self):
        """Test quick health check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            # Just verify it runs without error
            result = wm.is_healthy()
            assert isinstance(result, bool)

    def test_get_quick_summary(self):
        """Test quick summary for LLM context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            summary = wm.get_quick_summary()

            assert "summary" in summary
            assert "snapshot_id" in summary
            assert "Project:" in summary["summary"]
            assert "Git:" in summary["summary"]
            assert "OS:" in summary["summary"]
            assert "Python:" in summary["summary"]
            assert "Resources:" in summary["summary"]
            assert "Health:" in summary["summary"]
            assert "Tools:" in summary["summary"]


class TestContextAwareRetrieval:
    """Test context-aware retrieval/filtering."""

    def test_task_context_creation(self):
        """Test TaskContext creation."""
        ctx = TaskContext(task_type="build")
        assert ctx.task_type == "build"
        assert ctx.keywords == []

        ctx2 = TaskContext.from_string("test")
        assert ctx2.task_type == "test"

    def test_filter_snapshot_for_build(self):
        """Test filtering snapshot for build task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            filtered = filter_snapshot_for_task(full_snap, "build")

            assert filtered.project.name == full_snap.project.name
            assert filtered.runtime.os_family == full_snap.runtime.os_family
            assert filtered.git.is_repo == full_snap.git.is_repo
            assert filtered.resources.cpu_percent == full_snap.resources.cpu_percent
            assert filtered.tools.available_tools == full_snap.tools.available_tools
            # Health should be present for build
            assert filtered.health.overall_status == full_snap.health.overall_status

    def test_filter_snapshot_for_test(self):
        """Test filtering snapshot for test task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            filtered = filter_snapshot_for_task(full_snap, "test")

            assert filtered.project.name == full_snap.project.name
            assert filtered.git.is_repo == full_snap.git.is_repo
            # Health should include test metrics
            assert filtered.health.overall_status == full_snap.health.overall_status

    def test_filter_snapshot_for_deploy(self):
        """Test filtering snapshot for deploy task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            filtered = filter_snapshot_for_task(full_snap, "deploy")

            # Deploy needs most layers
            assert filtered.project.name
            assert filtered.runtime.os_family
            assert filtered.git.is_repo is not None
            assert filtered.resources.health_status
            assert filtered.tools.available_tools
            assert filtered.health.overall_status

    def test_filter_snapshot_for_debug(self):
        """Test filtering snapshot for debug task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            filtered = filter_snapshot_for_task(full_snap, "debug")

            # Debug needs runtime, resources, health details
            assert filtered.runtime.os_family
            assert filtered.resources.cpu_percent >= 0
            assert filtered.health.overall_status

    def test_filter_unknown_task_type(self):
        """Test filtering with unknown task type falls back to all layers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            filtered = filter_snapshot_for_task(full_snap, "unknown_type")

            # Should have all layers (fallback to unknown)
            assert filtered.project.name
            assert filtered.runtime.os_family
            assert filtered.git.is_repo is not None
            assert filtered.resources.cpu_percent >= 0
            assert filtered.tools.available_tools
            assert filtered.health.overall_status

    def test_get_relevant_context(self):
        """Test get_relevant_context returns dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            ctx = TaskContext.from_string("build")
            relevant = get_relevant_context(full_snap, ctx)

            assert "task_type" in relevant
            assert "snapshot_id" in relevant
            assert "timestamp" in relevant

    def test_get_relevant_summary(self):
        """Test get_relevant_summary returns text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            full_snap = wm.get_snapshot()
            summary = get_relevant_summary(full_snap, "build")

            assert "Environment (build)" in summary
            assert "Project:" in summary
            assert "OS:" in summary

    def test_list_supported_task_types(self):
        """Test listing supported task types."""
        types = list_supported_task_types()
        assert "build" in types
        assert "test" in types
        assert "deploy" in types
        assert "debug" in types
        assert "refactor" in types
        assert "develop" in types
        assert "analyze" in types
        assert "install" in types
        assert "lint" in types
        assert "unknown" in types


class TestWorldModelIntegration:
    """Integration tests with existing components."""

    def test_world_model_with_existing_components(self):
        """Verify WorldModel uses existing components correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple Python file
            (Path(tmpdir) / "main.py").write_text("print('hello')\n")
            (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname = 'test'\n")

            wm = create_world_model(workspace=tmpdir)
            snap = wm.get_snapshot()

            # Project should detect Python and pyproject.toml
            assert snap.project.main_language == "Python"
            assert any("pyproject.toml" in f for f in snap.project.config_files)
            assert snap.project.build_system != "unknown"
            assert snap.project.file_count >= 2

            # Runtime should be populated
            assert snap.runtime.python_version != ""
            assert snap.runtime.os_family in ["windows", "linux", "macos"]

            # Git should work (not a repo by default)
            assert snap.git.is_repo is False

            # Resources should have real values
            assert snap.resources.cpu_count > 0
            assert snap.resources.memory_total_gb > 0

            # Tools should include defaults
            assert len(snap.tools.available_tools) > 10

    def test_snapshot_performance(self):
        """Test snapshot collection is reasonably fast."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)

            # First call (cold)
            start = time.perf_counter()
            snap1 = wm.get_snapshot()
            cold_time = (time.perf_counter() - start) * 1000

            # Second call (cached)
            start = time.perf_counter()
            snap2 = wm.get_snapshot()
            cached_time = (time.perf_counter() - start) * 1000

            # Cached should be much faster
            assert cached_time < cold_time
            assert cold_time < 10000  # Should complete in under 10 seconds
            assert snap1.elapsed_ms > 0

    def test_snapshot_serialization_roundtrip(self):
        """Test snapshot can be serialized and deserialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = create_world_model(workspace=tmpdir)
            snap = wm.get_snapshot()

            # Serialize to JSON
            json_str = snap.to_json()
            assert isinstance(json_str, str)
            assert "snapshot_id" in json_str

            # Parse back
            data = json.loads(json_str)
            restored = EnvironmentSnapshot.from_dict(data)

            assert restored.snapshot_id == snap.snapshot_id
            assert restored.project.name == snap.project.name
            assert restored.runtime.os_family == snap.runtime.os_family


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])