"""Tests for Predictive Diagnostics - verifying float division by zero fix."""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from app.self_observation.runtime_awareness import RuntimeAwareness, AwarenessConfig
from app.self_observation.predictive_diagnostics import (
    PredictiveDiagnostics,
    PredictionType,
    PredictionHorizon,
    PredictionStatus,
)
from app.self_observation.predictive_models import (
    ResourceForecastingModel,
    PerformanceDegradationModel,
    PredictionInput,
)


class TestPredictiveModelsFloatDivisionFix:
    """Tests to verify the float division by zero fix in predictive models."""

    def test_resource_forecasting_with_zero_cpu_values(self):
        """Test ResourceForecastingModel handles 0.0 CPU usage correctly."""
        model = ResourceForecastingModel(min_data_points=3)

        # Historical data with 0.0 CPU usage (idle system - valid data)
        historical_context = [
            {"timestamp": "2026-01-01T00:00:00", "cpu_usage": 0.0},
            {"timestamp": "2026-01-01T00:01:00", "cpu_usage": 0.0},
            {"timestamp": "2026-01-01T00:02:00", "cpu_usage": 0.5},
            {"timestamp": "2026-01-01T00:03:00", "cpu_usage": 1.0},
            {"timestamp": "2026-01-01T00:04:00", "cpu_usage": 2.0},
        ]

        source_data = {"cpu_usage": 2.5}

        # This should NOT raise "float division by zero"
        series = model._extract_metric_series(historical_context, source_data)

        # Should extract cpu_percent series
        assert "cpu_percent" in series
        assert len(series["cpu_percent"]) >= 3
        # Verify values are correct (0.0, 0.0, 0.5, 1.0, 2.0, 2.5)
        assert 0.0 in series["cpu_percent"]
        assert 2.5 in series["cpu_percent"]

    def test_resource_forecasting_skips_unavailable_memory_percent(self):
        """Test that 0.0 for memory_percent is skipped (unavailable)."""
        model = ResourceForecastingModel(min_data_points=3)

        # Historical data with 0.0 memory_percent (unavailable)
        historical_context = [
            {"timestamp": "2026-01-01T00:00:00", "memory_percent": 0.0},
            {"timestamp": "2026-01-01T00:01:00", "memory_percent": 0.0},
            {"timestamp": "2026-01-01T00:02:00", "memory_percent": 45.0},
            {"timestamp": "2026-01-01T00:03:00", "memory_percent": 50.0},
        ]

        source_data = {"memory_percent": 55.0}

        series = model._extract_metric_series(historical_context, source_data)

        # Should extract memory_percent but skip the 0.0 values
        assert "memory_percent" in series
        # Only the non-zero values should be included (45.0, 50.0, 55.0)
        assert len(series["memory_percent"]) == 3
        assert 0.0 not in series["memory_percent"]
        assert all(v > 0 for v in series["memory_percent"])

    def test_resource_forecasting_constant_series_produces_stable_forecast(self):
        """Test that constant-value series produce a stable forecast (not filtered out)."""
        model = ResourceForecastingModel(min_data_points=3)

        # All same values - no variation (but this IS valid data representing a stable system)
        historical_context = [
            {"timestamp": "2026-01-01T00:00:00", "cpu_usage": 50.0},
            {"timestamp": "2026-01-01T00:01:00", "cpu_usage": 50.0},
            {"timestamp": "2026-01-01T00:02:00", "cpu_usage": 50.0},
            {"timestamp": "2026-01-01T00:03:00", "cpu_usage": 50.0},
        ]

        source_data = {"cpu_usage": 50.0}

        series = model._extract_metric_series(historical_context, source_data)

        # Constant series should NOT be filtered out - they represent stable system behavior
        # and _forecast_linear handles them correctly (producing stable forecast with low confidence)
        assert "cpu_percent" in series
        # 4 historical points (current from source_data is deduplicated since it's same as last historical)
        assert len(series["cpu_percent"]) == 4

        # Full prediction should work and produce a stable forecast
        from app.self_observation.predictive_models import PredictionInput, PredictionType, PredictionHorizon
        input_data = PredictionInput(
            prediction_type=PredictionType.RESOURCE_EXHAUSTION,
            horizon=PredictionHorizon.SHORT_TERM,
            source_data=source_data,
            historical_context=historical_context
        )
        result = model.predict(input_data)

        # Should produce a valid prediction (not insufficient_data)
        assert result.predicted_state != "insufficient_data"
        # Should be stable trend
        assert "stable" in str(result.model_info.get("forecasts", {}))
        # Confidence should be low (appropriate for constant data)
        assert result.confidence_score < 0.5

    def test_performance_degradation_with_zero_cpu_contention(self):
        """Test PerformanceDegradationModel handles 0.0 CPU usage correctly."""
        model = PerformanceDegradationModel(min_data_points=3)

        # Historical data with 0.0 cpu_contention (idle system - valid data)
        historical_context = [
            {"timestamp": "2026-01-01T00:00:00", "cpu_usage": 0.0},
            {"timestamp": "2026-01-01T00:01:00", "cpu_usage": 0.0},
            {"timestamp": "2026-01-01T00:02:00", "cpu_usage": 5.0},
            {"timestamp": "2026-01-01T00:03:00", "cpu_usage": 10.0},
            {"timestamp": "2026-01-01T00:04:00", "cpu_usage": 15.0},
        ]

        source_data = {"cpu_usage": 20.0}

        # This should NOT raise "float division by zero"
        series = model._extract_performance_metrics(historical_context, source_data)

        # Should extract cpu_contention series
        assert "cpu_contention" in series
        assert len(series["cpu_contention"]) >= 3
        assert 0.0 in series["cpu_contention"]
        assert 20.0 in series["cpu_contention"]

    def test_performance_degradation_skips_unavailable_memory_pressure(self):
        """Test that 0.0 for memory_pressure (system.memory.percent) is skipped."""
        model = PerformanceDegradationModel(min_data_points=3)

        historical_context = [
            {"timestamp": "2026-01-01T00:00:00", "system.memory.percent": 0.0},
            {"timestamp": "2026-01-01T00:01:00", "system.memory.percent": 0.0},
            {"timestamp": "2026-01-01T00:02:00", "system.memory.percent": 40.0},
            {"timestamp": "2026-01-01T00:03:00", "system.memory.percent": 45.0},
        ]

        source_data = {"system.memory.percent": 50.0}

        series = model._extract_performance_metrics(historical_context, source_data)

        # Should extract memory_pressure but skip the 0.0 values
        assert "memory_pressure" in series
        assert len(series["memory_pressure"]) == 3
        assert 0.0 not in series["memory_pressure"]
        assert all(v > 0 for v in series["memory_pressure"])


class TestPredictiveDiagnosticsIntegration:
    """Integration tests for PredictiveDiagnostics with runtime awareness."""

    @pytest.fixture
    def mock_awareness(self):
        """Create a mock runtime awareness with controlled data."""
        config = AwarenessConfig(
            update_interval_seconds=0.1,
            max_history=50,
        )

        awareness = RuntimeAwareness(config=config)
        awareness.start()
        time.sleep(0.3)  # Allow a few snapshots
        yield awareness
        awareness.stop()

    def test_forecast_does_not_crash_with_idle_system(self, mock_awareness):
        """Test that forecasting doesn't crash when system is mostly idle (0.0 CPU)."""
        # Get mock to return known states
        original_get_current = mock_awareness.get_current_state
        original_get_history = mock_awareness.get_history

        # Create a state with 0.0 CPU (idle system)
        from app.self_observation.models import RuntimeAwarenessState

        def mock_get_current():
            state = RuntimeAwarenessState()
            state.cpu_usage = 0.0  # Idle system
            state.memory_usage_mb = 100.0
            state.disk_io_mb_s = 0.0
            state.network_io_mb_s = 0.0
            state.gpu_utilization_percent = 0.0
            state.gpu_memory_used_mb = 0.0
            state.gpu_memory_total_mb = 8192.0
            state.system_health_status = "healthy"
            state.running_tasks = []
            state.active_goals = []
            state.pending_workflows = 0
            state.background_jobs = 0
            state.gpu_devices = []
            return state

        # Create history with some variation for forecasting
        history_states = []
        for i in range(10):
            state = RuntimeAwarenessState()
            state.timestamp = datetime.now(timezone.utc).isoformat()
            state.cpu_usage = float(i * 2)  # 0, 2, 4, 6, 8, 10, 12, 14, 16, 18
            state.memory_usage_mb = 100.0 + i * 10
            state.disk_io_mb_s = 0.0
            state.network_io_mb_s = 0.0
            state.gpu_utilization_percent = 0.0
            state.gpu_memory_used_mb = 0.0
            state.gpu_memory_total_mb = 8192.0
            state.system_health_status = "healthy"
            state.running_tasks = []
            state.active_goals = []
            state.pending_workflows = 0
            state.background_jobs = 0
            state.gpu_devices = []
            history_states.append(state)

        from unittest.mock import patch, MagicMock

        with patch.object(mock_awareness, 'get_current_state', side_effect=mock_get_current):
            with patch.object(mock_awareness, 'get_history', return_value=history_states):
                # Create predictive diagnostics
                from app.self_observation.predictive_diagnostics import PredictiveDiagnostics
                diagnostics = PredictiveDiagnostics(mock_awareness)

                # This should NOT raise "float division by zero"
                results = diagnostics.run_predictions(force=True)

                # Should complete without error
                assert results is not None
                assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
def test_prepare_prediction_input_handles_unknown_gpu_metrics():
    from app.self_observation.models import RuntimeAwarenessState
    diagnostics = object.__new__(PredictiveDiagnostics)
    diagnostics._observability = None
    diagnostics._runtime_awareness = Mock()
    diagnostics._runtime_awareness.get_all_trends.return_value = []
    diagnostics._config = Mock(trend_window_seconds=3600)
    diagnostics._get_gpu_metrics = lambda: {}
    state = RuntimeAwarenessState()
    result = diagnostics._prepare_prediction_input(PredictionType.RESOURCE_EXHAUSTION, next(iter(PredictionHorizon)), state, [])
    assert isinstance(result.source_data, dict)
    assert 'gpu_memory_percent' not in result.source_data
