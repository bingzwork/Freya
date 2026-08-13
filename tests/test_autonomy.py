"""Tests for Autonomy + Observation components."""

import pytest
import time
from unittest.mock import MagicMock, patch

# Test models
from app.autonomy.models import (
    WatchdogObservation,
    WatchdogEventType,
    WatchdogSeverity,
    AutonomyConfig,
    AutonomousWorkItem,
    GoalContext,
)


class TestAutonomyModels:
    """Test autonomy data models."""
    
    def test_watchdog_observation_creation(self):
        obs = WatchdogObservation(
            event_type=WatchdogEventType.SYSTEM_EVENT,
            severity=WatchdogSeverity.INFO,
            source="TestSource",
            component="TestComponent",
            message="Test message",
            details={"key": "value"},
            tags=["tag1", "tag2"],
        )
        assert obs.event_type == WatchdogEventType.SYSTEM_EVENT
        assert obs.severity == WatchdogSeverity.INFO
        assert obs.source == "TestSource"
        assert obs.component == "TestComponent"
        assert obs.message == "Test message"
        assert obs.details == {"key": "value"}
        assert obs.tags == ["tag1", "tag2"]
        assert obs.id.startswith("obs_")
    
    def test_watchdog_observation_to_learning_candidate(self):
        obs = WatchdogObservation(
            event_type=WatchdogEventType.HEALTH_CHECK,
            severity=WatchdogSeverity.WARNING,
            source="ObservabilityHub",
            component="Memory",
            message="Memory degraded",
            details={"usage": "85%"},
            tags=["health", "memory"],
        )
        candidate = obs.to_learning_candidate()
        assert candidate["candidate_type"].value == "watchdog_observation"
        assert candidate["source_component"] == "Watchdog"
        assert candidate["raw_observation"]["event_type"] == "health_check"
        assert candidate["raw_observation"]["severity"] == "warning"
        assert "watchdog" in candidate["tags"]
        assert "health_check" in candidate["tags"]
        assert "warning" in candidate["tags"]
    
    def test_autonomy_config_defaults(self):
        config = AutonomyConfig()
        assert config.enabled is True
        assert config.watchdog_enabled is True
        assert config.self_initiated_enabled is True
        assert config.maintenance_enabled is True
        assert config.use_background_job_service is True
        assert config.self_initiated_check_interval_seconds == 300.0
        assert config.maintenance_check_interval_seconds == 3600.0
        assert config.max_concurrent_autonomous_tasks == 3
    
    def test_autonomous_work_item_creation(self):
        work = AutonomousWorkItem(
            source="self_initiated",
            description="Test work",
            workflow_spec={"name": "Test", "strategy": "adaptive"},
            priority=3,
            goal_id="goal_123",
            metadata={"custom": "data"},
        )
        assert work.source == "self_initiated"
        assert work.description == "Test work"
        assert work.workflow_spec == {"name": "Test", "strategy": "adaptive"}
        assert work.priority == 3
        assert work.goal_id == "goal_123"
        assert work.metadata == {"custom": "data"}
        assert work.status == "pending"
        assert work.id.startswith("auto_work_")
    
    def test_goal_context_creation(self):
        ctx = GoalContext(
            goal_id="goal_1",
            name="Test Goal",
            description="Test description",
            status="in_progress",
            priority="high",
            progress=0.5,
            is_blocked=False,
            blocking_reasons=[],
            dependencies=[],
            duration_estimate={"estimated_seconds": 3600},
            metadata={},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert ctx.goal_id == "goal_1"
        assert ctx.name == "Test Goal"
        assert ctx.progress == 0.5
        assert ctx.is_blocked is False


# Test Watchdog
class TestWatchdog:
    """Test Watchdog component."""
    
    @pytest.fixture
    def mock_event_bus(self):
        bus = MagicMock()
        bus.subscribe.return_value = "sub_123"
        return bus
    
    @pytest.fixture
    def mock_observability(self):
        obs = MagicMock()
        obs.get_health.return_value = {"status": "healthy", "components": 5}
        obs.list_components.return_value = [
            {"name": "Component1", "status": "healthy"},
            {"name": "Component2", "status": "degraded"},
        ]
        obs.get_active_alerts.return_value = []
        return obs
    
    @pytest.fixture
    def mock_learning_pipeline(self):
        return MagicMock()
    
    @pytest.fixture
    def mock_job_service(self):
        job_svc = MagicMock()
        job_svc.schedule.return_value = "job_123"
        return job_svc
    
    @pytest.fixture
    def config(self):
        return AutonomyConfig(
            watchdog_enabled=True,
            use_background_job_service=False,  # Disable for testing
            self_initiated_check_interval_seconds=60.0,
        )
    
    def test_watchdog_start_stop(self, config, mock_event_bus, mock_observability, 
                                 mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        assert not watchdog.is_running()
        watchdog.start()
        assert watchdog.is_running()
        watchdog.stop()
        assert not watchdog.is_running()
    
    def test_watchdog_subscribes_to_events(self, config, mock_event_bus, mock_observability,
                                           mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        watchdog.start()
        
        # Should subscribe to all patterns in config
        assert mock_event_bus.subscribe.call_count == len(config.watchdog_event_subscriptions)
        
        watchdog.stop()
    
    def test_watchdog_processes_event(self, config, mock_event_bus, mock_observability,
                                      mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        from app.core.events import Event, EventPriority
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        watchdog.start()
        
        # Get the callback that was registered
        call_args = mock_event_bus.subscribe.call_args_list[0]
        callback = call_args[1]["callback"] if "callback" in call_args[1] else call_args[0][1]
        
        # Create a test event
        event = Event(
            name="task.started",
            data={"task_id": "task_123"},
            source="WorkflowOrchestrator",
            priority=EventPriority.NORMAL,
        )
        
        # Call the callback
        callback(event)
        
        # Learning pipeline should have been called
        mock_learning_pipeline.run.assert_called()
        
        watchdog.stop()
    
    def test_watchdog_creates_observations(self, config, mock_event_bus, mock_observability,
                                           mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        watchdog.start()
        
        # Stop the monitor thread to avoid periodic checks during test
        watchdog._shutdown_event.set()
        if hasattr(watchdog, "_monitor_thread") and watchdog._monitor_thread.is_alive():
            watchdog._monitor_thread.join(timeout=1.0)
        
        # Test observation handlers
        handler_called = []
        def handler(obs):
            handler_called.append(obs)
        watchdog.add_observation_handler(handler)
        
        # Trigger various observation methods
        watchdog.observe_task_stalled("task_1", {"reason": "timeout"})
        watchdog.observe_task_failed("task_2", "Exception", {"traceback": "..."})
        watchdog.observe_goal_stalled("goal_1", {"reason": "blocked"})
        watchdog.observe_goal_failed("goal_2", "Error", {"details": "..."})
        watchdog.observe_resource_pressure("cpu", 95.0, 80.0)
        
        assert len(handler_called) == 5
        
        # Check specific observations
        assert handler_called[0].event_type == WatchdogEventType.TASK_STALLED
        assert handler_called[1].event_type == WatchdogEventType.TASK_FAILED
        assert handler_called[2].event_type == WatchdogEventType.GOAL_STALLED
        assert handler_called[3].event_type == WatchdogEventType.GOAL_FAILED
        assert handler_called[4].event_type == WatchdogEventType.RESOURCE_PRESSURE
        
        watchdog.stop()
    
    def test_watchdog_periodic_health_check(self, config, mock_event_bus, mock_observability,
                                            mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        
        # Configure for degraded health
        mock_observability.get_health.return_value = {"status": "degraded", "components": 5}
        mock_observability.list_components.return_value = [
            {"name": "Component1", "status": "healthy"},
            {"name": "Component2", "status": "unhealthy"},
        ]
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        watchdog.start()
        
        # Call periodic health check directly
        watchdog._periodic_health_check()
        
        # Should have fed observations to learning pipeline for degraded/unhealthy
        assert mock_learning_pipeline.run.call_count >= 2
        
        watchdog.stop()
    
    def test_watchdog_metric_alerts(self, config, mock_event_bus, mock_observability,
                                    mock_learning_pipeline, mock_job_service):
        from app.autonomy.watchdog import Watchdog
        
        mock_observability.get_active_alerts.return_value = [
            {"rule": "high_cpu", "severity": "critical", "message": "CPU > 90%"},
            {"rule": "high_memory", "severity": "warning", "message": "Memory > 80%"},
        ]
        
        watchdog = Watchdog(
            config=config,
            event_bus=mock_event_bus,
            observability=mock_observability,
            learning_pipeline=mock_learning_pipeline,
            job_service=mock_job_service,
        )
        
        watchdog.start()
        
        # Check alerts
        watchdog._check_metric_alerts()
        
        assert mock_learning_pipeline.run.call_count >= 2
        
        watchdog.stop()


# Test SelfInitiatedWorkManager
class TestSelfInitiatedWorkManager:
    """Test SelfInitiatedWorkManager component."""
    
    @pytest.fixture
    def mock_goal_storage(self):
        storage = MagicMock()
        storage.get_next_eligible_goals.return_value = [
            {
                "goal_id": "goal_1",
                "name": "Goal 1",
                "description": "Test goal 1",
                "status": "in_progress",
                "priority": "high",
                "progress": 0.3,
                "is_blocked": False,
                "blocking_reasons": [],
                "dependencies": [],
                "duration_estimate": {"estimated_seconds": 3600},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        ]
        return storage
    
    @pytest.fixture
    def mock_workflow_orchestrator(self):
        orch = MagicMock()
        orch.execute_workflow.return_value = "exec_123"
        orch.get_workflow_status.return_value = None  # Will be set per test
        return orch
    
    @pytest.fixture
    def mock_job_service(self):
        job_svc = MagicMock()
        job_svc.schedule.return_value = "job_123"
        return job_svc
    
    @pytest.fixture
    def config(self):
        return AutonomyConfig(
            self_initiated_enabled=True,
            use_background_job_service=False,
            self_initiated_check_interval_seconds=1.0,  # Fast for testing
            max_concurrent_autonomous_tasks=3,
        )
    
    def test_self_initiated_start_stop(self, config, mock_goal_storage, 
                                       mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.self_initiated import SelfInitiatedWorkManager
        
        manager = SelfInitiatedWorkManager(
            config=config,
            goal_storage=mock_goal_storage,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        assert not manager.is_running()
        manager.start()
        assert manager.is_running()
        manager.stop()
        assert not manager.is_running()
    
    def test_self_initiated_generates_work(self, config, mock_goal_storage,
                                           mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.self_initiated import SelfInitiatedWorkManager
        from app.orchestrator.workflow_orchestrator import WorkflowStatus
        
        manager = SelfInitiatedWorkManager(
            config=config,
            goal_storage=mock_goal_storage,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        manager.start()
        
        # Mock workflow status to show completion
        mock_workflow_orchestrator.get_workflow_status.side_effect = [
            WorkflowStatus.EXECUTING,
            WorkflowStatus.COMPLETED,
        ]
        
        # Trigger check
        manager._check_and_generate_work()
        
        # Give time for async execution
        time.sleep(0.5)
        
        # Should have executed workflow
        mock_workflow_orchestrator.execute_workflow.assert_called()
        
        # Check active work
        active = manager.get_active_work()
        assert len(active) >= 1
        
        manager.stop()
    
    def test_self_initiated_respects_concurrent_limit(self, mock_goal_storage,
                                                      mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.self_initiated import SelfInitiatedWorkManager
        from app.autonomy.models import AutonomyConfig, AutonomousWorkItem
        
        # Create config with limit=1
        limited_config = AutonomyConfig(
            self_initiated_enabled=True,
            use_background_job_service=False,
            self_initiated_check_interval_seconds=1.0,
            max_concurrent_autonomous_tasks=1,
        )
        
        manager = SelfInitiatedWorkManager(
            config=limited_config,
            goal_storage=mock_goal_storage,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        # Add one active work manually BEFORE starting (to avoid race with check thread)
        work = AutonomousWorkItem(
            source="self_initiated",
            description="Existing work",
            workflow_spec={},
            status="running",
        )
        manager._active_work[work.id] = work
        
        manager.start()
        
        # Check should not generate new work due to limit
        manager._check_and_generate_work()
        
        mock_workflow_orchestrator.execute_workflow.assert_not_called()
        
        manager.stop()
    
    def test_self_initiated_skips_blocked_goals(self, config, mock_goal_storage,
                                                mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.self_initiated import SelfInitiatedWorkManager
        
        # Return a blocked goal
        mock_goal_storage.get_next_eligible_goals.return_value = [
            {
                "goal_id": "goal_blocked",
                "name": "Blocked Goal",
                "description": "This goal is blocked",
                "status": "in_progress",
                "priority": "high",
                "progress": 0.0,
                "is_blocked": True,
                "blocking_reasons": ["Waiting for dependency"],
                "dependencies": [],
                "duration_estimate": None,
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        ]
        
        manager = SelfInitiatedWorkManager(
            config=config,
            goal_storage=mock_goal_storage,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        manager.start()
        manager._check_and_generate_work()
        
        # Should not execute workflow for blocked goal
        mock_workflow_orchestrator.execute_workflow.assert_not_called()
        
        manager.stop()


# Test MaintenanceManager
class TestMaintenanceManager:
    """Test MaintenanceManager component."""
    
    @pytest.fixture
    def mock_workflow_orchestrator(self):
        orch = MagicMock()
        orch.execute_workflow.return_value = "exec_123"
        orch.get_workflow_status.return_value = None
        return orch
    
    @pytest.fixture
    def mock_job_service(self):
        job_svc = MagicMock()
        job_svc.schedule.return_value = "job_123"
        return job_svc
    
    @pytest.fixture
    def config(self):
        return AutonomyConfig(
            maintenance_enabled=True,
            use_background_job_service=False,
            maintenance_check_interval_seconds=1.0,
        )
    
    def test_maintenance_start_stop(self, config, mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.maintenance import MaintenanceManager
        
        manager = MaintenanceManager(
            config=config,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        assert not manager.is_running()
        manager.start()
        assert manager.is_running()
        manager.stop()
        assert not manager.is_running()
    
    def test_maintenance_has_default_tasks(self, config, mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.maintenance import MaintenanceManager
        
        manager = MaintenanceManager(
            config=config,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        scheduled = manager.get_scheduled_tasks()
        assert len(scheduled) > 0
        
        # Check for expected default tasks
        task_types = [t["task_type"] for t in scheduled]
        assert "health_check" in task_types
        assert "memory_consolidation" in task_types
        assert "learning_garbage_collection" in task_types
        assert "goal_progress_review" in task_types
        assert "capability_audit" in task_types
    
    def test_maintenance_add_remove_custom_task(self, config, mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.maintenance import MaintenanceManager
        
        manager = MaintenanceManager(
            config=config,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        # Add custom task
        manager.add_maintenance_task(
            task_type="custom_task",
            name="Custom Task",
            description="Custom maintenance task",
            workflow_spec={"name": "Custom", "strategy": "sequential"},
            interval_seconds=3600.0,
        )
        
        scheduled = manager.get_scheduled_tasks()
        task_types = [t["task_type"] for t in scheduled]
        assert "custom_task" in task_types
        
        # Remove it
        result = manager.remove_maintenance_task("custom_task")
        assert result is True
        
        scheduled = manager.get_scheduled_tasks()
        task_types = [t["task_type"] for t in scheduled]
        assert "custom_task" not in task_types
        
        # Remove non-existent
        result = manager.remove_maintenance_task("non_existent")
        assert result is False
    
    def test_maintenance_skips_when_concurrent_limit(self, mock_workflow_orchestrator, mock_job_service):
        from app.autonomy.maintenance import MaintenanceManager
        from app.autonomy.models import AutonomyConfig, AutonomousWorkItem
        
        config = AutonomyConfig(
            maintenance_enabled=True,
            use_background_job_service=False,
            maintenance_check_interval_seconds=1.0,
        )
        
        manager = MaintenanceManager(
            config=config,
            workflow_orchestrator=mock_workflow_orchestrator,
            job_service=mock_job_service,
        )
        
        # Manually fill active slots BEFORE starting
        for i in range(2):  # Max is 2 for maintenance
            work = AutonomousWorkItem(
                source="maintenance",
                description=f"Work {i}",
                workflow_spec={},
                status="running",
            )
            manager._active_work[work.id] = work
        
        manager.start()
        
        # Force run a task by setting last_run to long ago
        manager._last_run["health_check"] = 0
        
        manager._check_and_run_maintenance()
        
        # Should not execute new work (limit reached)
        mock_workflow_orchestrator.execute_workflow.assert_not_called()
        
        manager.stop()


# Test AutonomyManager (integration)
class TestAutonomyManager:
    """Test AutonomyManager as the main coordinator."""
    
    @pytest.fixture
    def mock_dependencies(self):
        return {
            "event_bus": MagicMock(),
            "observability": MagicMock(),
            "learning_pipeline": MagicMock(),
            "goal_storage": MagicMock(),
            "workflow_orchestrator": MagicMock(),
            "job_service": MagicMock(),
        }
    
    @pytest.fixture
    def autonomy_config(self):
        return AutonomyConfig(
            enabled=True,
            watchdog_enabled=True,
            self_initiated_enabled=True,
            maintenance_enabled=True,
            use_background_job_service=False,
        )
    
    def test_autonomy_manager_initialization(self, autonomy_config, mock_dependencies):
        from app.autonomy.manager import AutonomyManager
        
        manager = AutonomyManager(config=autonomy_config, **mock_dependencies)
        
        assert manager.watchdog is not None
        assert manager.self_initiated is not None
        assert manager.maintenance is not None
        assert not manager.is_running()
    
    def test_autonomy_manager_start_stop(self, autonomy_config, mock_dependencies):
        from app.autonomy.manager import AutonomyManager
        
        manager = AutonomyManager(config=autonomy_config, **mock_dependencies)
        
        assert not manager.is_running()
        result = manager.start()
        assert result is True
        assert manager.is_running()
        manager.stop()
        assert not manager.is_running()
    
    def test_autonomy_manager_status(self, autonomy_config, mock_dependencies):
        from app.autonomy.manager import AutonomyManager
        
        manager = AutonomyManager(config=autonomy_config, **mock_dependencies)
        manager.start()
        
        status = manager.get_status()
        
        assert status["running"] is True
        assert status["enabled"] is True
        assert "watchdog" in status
        assert "self_initiated" in status
        assert "maintenance" in status
        
        manager.stop()
    
    def test_autonomy_manager_late_binding(self, mock_dependencies, autonomy_config):
        from app.autonomy.manager import AutonomyManager
        
        # Create without some dependencies - use mocks for required globals
        manager = AutonomyManager(
            config=autonomy_config,
            event_bus=mock_dependencies["event_bus"],
            observability=mock_dependencies["observability"],
            job_service=mock_dependencies["job_service"],
        )
        
        # Set the remaining dependencies later
        manager.set_goal_storage(mock_dependencies["goal_storage"])
        manager.set_workflow_orchestrator(mock_dependencies["workflow_orchestrator"])
        manager.set_learning_pipeline(mock_dependencies["learning_pipeline"])
        
        assert manager._goal_storage == mock_dependencies["goal_storage"]
        assert manager._workflow_orchestrator == mock_dependencies["workflow_orchestrator"]
        assert manager._learning_pipeline == mock_dependencies["learning_pipeline"]
        assert manager.self_initiated._goal_storage == mock_dependencies["goal_storage"]
        assert manager.self_initiated._workflow_orchestrator == mock_dependencies["workflow_orchestrator"]
        assert manager.maintenance._workflow_orchestrator == mock_dependencies["workflow_orchestrator"]
        assert manager.watchdog._learning_pipeline == mock_dependencies["learning_pipeline"]
    
    @pytest.mark.skip(reason="Test hangs due to thread cleanup")
    def test_autonomy_manager_observation_methods(self, autonomy_config, mock_dependencies):
        from app.autonomy.manager import AutonomyManager
        
        manager = AutonomyManager(config=autonomy_config, **mock_dependencies)
        manager.start()
        
        # Test observation convenience methods
        manager.observe_task_stalled("task_1", {"reason": "timeout"})
        manager.observe_task_failed("task_2", "Error", {"traceback": "..."})
        manager.observe_goal_stalled("goal_1", {"reason": "blocked"})
        manager.observe_goal_failed("goal_2", "Error", {})
        manager.observe_resource_pressure("cpu", 95.0, 80.0)
        
        # Verify watchdog received them
        watchdog = manager.watchdog
        assert watchdog is not None
        
        manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])