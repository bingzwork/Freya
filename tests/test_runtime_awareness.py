"""Tests for Runtime Awareness Service."""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch

from app.self_observation.runtime_awareness import (
    RuntimeAwareness,
    AwarenessConfig,
    get_runtime_awareness,
    set_runtime_awareness,
)
from app.self_observation.models import RuntimeAwarenessState, AwarenessComponent


class TestRuntimeAwareness:
    """Test Runtime Awareness Service."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator with necessary components."""
        orch = Mock()
        orch.state = Mock()
        orch.state.value = "running"
        orch._start_time = time.time()
        orch.get_system_status = Mock(return_value={
            "orchestrator": {"uptime_seconds": 0},
        })

        # Mock activity reporter
        reporter = Mock()
        reporter.get_recent_summary = Mock(return_value="Executing task: code review")
        orch.activity_reporter = reporter

        # Mock task executor
        executor = Mock()
        executor._lock = threading.RLock()
        executor._active_executions = {}
        executor.get_stats = Mock(return_value={
            "completed_workflows": 5,
            "failed_workflows": 1,
        })
        orch.task_executor = executor

        # Mock workflow composer
        composer = Mock()
        composer.get_stats = Mock(return_value={
            "by_status": {"pending": 2, "running": 3}
        })
        orch.workflow_composer = composer

        # Mock capability registry
        registry = Mock()
        cap1 = Mock()
        cap1.name = "file_operations"
        cap2 = Mock()
        cap2.name = "code_execution"
        cap3 = Mock()
        cap3.name = "git_operations"
        registry.list_capabilities = Mock(return_value=[cap1, cap2, cap3])
        orch.capability_registry = registry

        # Mock safety gate
        safety = Mock()
        orch.safety_gate = safety

        return orch

    @pytest.fixture
    def mock_decision_manager(self):
        """Create a mock decision manager."""
        dm = Mock()
        dm.get_statistics = Mock(return_value={
            "total_decisions": 10,
            "auto_executed": 8,
            "human_review_required": 2,
            "avg_confidence": 0.85,
        })
        return dm

    @pytest.fixture
    def mock_world_model(self):
        """Create a mock world model."""
        wm = Mock()
        snapshot = Mock()
        snapshot.resources.cpu_percent = 45.0
        snapshot.resources.memory_percent = 60.0
        snapshot.resources.memory_used_gb = 2.5
        wm.get_snapshot = Mock(return_value=snapshot)
        return wm

    @pytest.fixture
    def mock_memory_retrieval(self):
        """Create a mock memory retrieval."""
        return Mock()

    @pytest.fixture
    def mock_goal_storage(self):
        """Create a mock goal storage."""
        from app.memory.goals import Goal
        storage = Mock()
        storage._goals = {
            "goal_1": Goal(
                id="goal_1",
                name="Test Goal",
                description="A test goal",
                status="active",
                priority="high",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            ),
            "goal_2": Goal(
                id="goal_2",
                name="Another Goal",
                description="Another test goal",
                status="pending",
                priority="medium",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            ),
        }
        storage._active_goal_id = "goal_1"
        storage.active_goal = Mock(return_value=storage._goals["goal_1"])
        return storage

    @pytest.fixture
    def mock_autonomy_manager(self):
        """Create a mock autonomy manager."""
        am = Mock()
        am.is_running = True
        return am

    @pytest.fixture
    def mock_autonomous_learning(self):
        """Create a mock autonomous learning pipeline."""
        return Mock()

    @pytest.fixture
    def mock_failure_recovery(self):
        """Create a mock failure recovery."""
        return Mock()

    @pytest.fixture
    def awareness(
        self,
        mock_orchestrator,
        mock_decision_manager,
        mock_world_model,
        mock_memory_retrieval,
        mock_goal_storage,
        mock_autonomy_manager,
        mock_autonomous_learning,
        mock_failure_recovery,
    ):
        """Create a RuntimeAwareness instance with mocked dependencies."""
        config = AwarenessConfig(
            update_interval_seconds=1.0,
            max_history=10,
        )

        awareness = RuntimeAwareness(
            orchestrator=mock_orchestrator,
            decision_manager=mock_decision_manager,
            world_model=mock_world_model,
            memory_retrieval=mock_memory_retrieval,
            goal_storage=mock_goal_storage,
            autonomy_manager=mock_autonomy_manager,
            autonomous_learning=mock_autonomous_learning,
            failure_recovery=mock_failure_recovery,
            config=config,
        )
        yield awareness
        awareness.stop()

    def test_initialization(self, awareness):
        """Test that awareness initializes correctly."""
        assert awareness is not None
        assert awareness._running is False
        assert awareness._current_state is None
        assert awareness._awareness_history == []

    def test_start_stop(self, awareness):
        """Test starting and stopping the awareness service."""
        awareness.start()
        assert awareness._running is True
        assert awareness._awareness_thread is not None
        assert awareness._awareness_thread.is_alive()

        awareness.stop()
        assert awareness._running is False

    def test_update_awareness(self, awareness, mock_orchestrator, mock_world_model):
        """Test updating awareness state."""
        # Start awareness
        awareness.start()
        time.sleep(0.2)  # Allow loop to run once

        # Get current state
        state = awareness.get_current_state()

        assert state is not None
        assert isinstance(state, RuntimeAwarenessState)
        assert state.awareness_id is not None
        assert state.timestamp is not None

        # Check activity was gathered
        assert state.current_activity == "working"

        # Check resource consumption
        assert state.cpu_usage == 45.0
        assert state.memory_usage_mb == 2560.0  # 2.5 GB * 1024

        # Check goals
        assert len(state.active_goals) == 2
        assert state.current_goal is not None
        assert state.current_goal["name"] == "Test Goal"

        # Check tools
        assert len(state.active_tools) == 3
        assert "file_operations" in state.active_tools

        # Check pending work
        assert state.pending_workflows == 2

        # Check execution context
        assert state.execution_mode == "autonomous"
        assert state.total_decisions_made == 10
        assert state.total_tasks_completed == 6  # 5 completed + 1 failed

    def test_get_summary(self, awareness, mock_orchestrator, mock_world_model):
        """Test getting human-readable summary."""
        awareness.start()
        time.sleep(0.2)

        summary = awareness.get_summary()

        assert summary["activity"] == "working"
        assert summary["running_tasks"] == 0  # No active executions in mock
        assert summary["active_goals"] == 2
        assert summary["current_goal"] == "Test Goal"
        assert summary["cpu_usage"] == "45.0%"
        assert summary["memory_mb"] == "2560"
        assert summary["pending_workflows"] == 2
        assert summary["execution_mode"] == "autonomous"

    def test_get_history(self, awareness, mock_orchestrator, mock_world_model):
        """Test getting awareness history."""
        awareness.start()
        time.sleep(0.5)  # Allow multiple updates

        history = awareness.get_history(limit=5)

        assert len(history) > 0
        assert len(history) <= 5
        for state in history:
            assert isinstance(state, RuntimeAwarenessState)

    def test_get_stats(self, awareness, mock_orchestrator, mock_world_model):
        """Test getting awareness service stats."""
        awareness.start()
        time.sleep(0.2)

        stats = awareness.get_stats()

        assert stats["running"] is True
        assert stats["total_updates"] > 0
        assert stats["current_state"] is not None
        assert "update_interval_seconds" in stats
        assert "cached_metrics" in stats

    def test_get_trend(self, awareness, mock_orchestrator, mock_world_model):
        """Test getting trend data."""
        # Need multiple data points
        awareness.start()
        time.sleep(0.5)  # Allow multiple updates

        trend = awareness.get_trend("cpu_usage", window_seconds=10.0)

        # Should have enough samples for trend
        # Note: with 1 second interval and 0.5s wait, might have ~2 samples
        assert "trend" in trend
        assert "samples" in trend

    def test_get_all_trends(self, awareness, mock_orchestrator, mock_world_model):
        """Test getting all trends."""
        awareness.start()
        time.sleep(0.5)

        trends = awareness.get_all_trends()

        assert isinstance(trends, dict)
        # Should have at least some metrics
        assert len(trends) > 0

    def test_global_factory(self):
        """Test global factory function."""
        # Reset global
        set_runtime_awareness(None)

        # Get instance
        awareness = get_runtime_awareness()
        assert awareness is not None
        assert isinstance(awareness, RuntimeAwareness)

        # Get again - should return same instance
        awareness2 = get_runtime_awareness()
        assert awareness is awareness2

        # Cleanup
        awareness.stop()
        set_runtime_awareness(None)


class TestRuntimeAwarenessIntegration:
    """Integration tests for Runtime Awareness with other subsystems."""

    def test_awareness_without_optional_deps(self):
        """Test awareness works with minimal dependencies."""
        config = AwarenessConfig(update_interval_seconds=1.0, max_history=5)

        awareness = RuntimeAwareness(config=config)
        awareness.start()
        time.sleep(0.2)

        state = awareness.get_current_state()

        assert state is not None
        assert state.current_activity == "idle"  # Default when no reporter
        assert state.reasoning_phase == "observing"  # Default when no decision manager
        assert state.system_health_status == "unknown"  # Default from observability when no checks

        awareness.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])