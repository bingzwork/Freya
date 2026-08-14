"""Tests for the GPU Monitor module."""

import json
import pytest
from unittest.mock import patch, MagicMock, Mock, AsyncMock

from app.monitoring.gpu_monitor import (
    GPUMonitor,
    GPUDetector,
    GPUMetricsCollector,
    GPUInfo,
    GPUMetrics,
    GPUVendor,
    create_gpu_monitor,
)


class TestGPUInfo:
    """Tests for GPUInfo dataclass."""

    def test_gpu_info_creation(self):
        """Test creating GPUInfo."""
        gpu = GPUInfo(
            index=0,
            vendor=GPUVendor.NVIDIA,
            name="NVIDIA RTX 3080",
            driver_version="525.60.11",
            vram_total_mb=10240,
            vram_free_mb=8192,
            vram_used_mb=2048,
            compute_capability="8.6",
            cuda_version="12.0",
            architecture="Ampere",
            device_id="1234:5678",
        )
        assert gpu.index == 0
        assert gpu.vendor == GPUVendor.NVIDIA
        assert gpu.name == "NVIDIA RTX 3080"
        assert gpu.vram_total_mb == 10240

    def test_gpu_info_to_dict(self):
        """Test GPUInfo to_dict."""
        gpu = GPUInfo(
            index=1,
            vendor=GPUVendor.AMD,
            name="AMD Radeon RX 6800",
            driver_version="22.10",
            vram_total_mb=16384,
        )
        d = gpu.to_dict()
        assert d["index"] == 1
        assert d["vendor"] == "amd"
        assert d["name"] == "AMD Radeon RX 6800"
        assert d["vram"]["total_mb"] == 16384
        assert d["compute_capability"] is None
        assert d["cuda_version"] is None


class TestGPUMetrics:
    """Tests for GPUMetrics dataclass."""

    def test_gpu_metrics_creation(self):
        """Test creating GPUMetrics."""
        metrics = GPUMetrics(
            index=0,
            vendor=GPUVendor.NVIDIA,
            name="NVIDIA RTX 3080",
            gpu_utilization_percent=75.5,
            memory_utilization_percent=50.0,
            memory_used_mb=5120,
            memory_free_mb=5120,
            memory_total_mb=10240,
            temperature_celsius=65.0,
            power_draw_watts=250.0,
            power_limit_watts=320.0,
            fan_speed_percent=60.0,
            clock_graphics_mhz=1800,
            clock_memory_mhz=9500,
            encoder_utilization_percent=10.0,
            decoder_utilization_percent=5.0,
        )
        assert metrics.index == 0
        assert metrics.vendor == GPUVendor.NVIDIA
        assert metrics.gpu_utilization_percent == 75.5
        assert metrics.temperature_celsius == 65.0

    def test_gpu_metrics_to_dict(self):
        """Test GPUMetrics to_dict."""
        metrics = GPUMetrics(
            index=0,
            vendor=GPUVendor.INTEL,
            name="Intel UHD Graphics",
            gpu_utilization_percent=25.0,
            memory_utilization_percent=30.0,
            memory_used_mb=1024,
            memory_free_mb=2048,
            memory_total_mb=3072,
        )
        d = metrics.to_dict()
        assert d["index"] == 0
        assert d["vendor"] == "intel"
        assert d["utilization"]["gpu_percent"] == 25.0
        assert d["memory"]["used_mb"] == 1024
        assert d["temperature_celsius"] is None
        assert d["power"]["draw_watts"] is None


class TestGPUDetector:
    """Tests for GPUDetector."""

    @patch("subprocess.run")
    def test_detect_nvidia_mock(self, mock_run):
        """Test NVIDIA GPU detection with mocked pynvml."""
        # This test would require mocking pynvml which is complex
        # Instead we test the fallback lspci detection
        detector = GPUDetector()

        # Test vendor detection from lspci output
        gpus = detector._detect_via_lspci([])
        assert isinstance(gpus, list)

    def test_parse_mb(self):
        """Test memory parsing."""
        detector = GPUDetector()
        assert detector._parse_mb("1024 MB") == 1024.0
        assert detector._parse_mb("1 GB") == 1024.0
        assert detector._parse_mb("1024 KB") == 1.0
        assert detector._parse_mb("1073741824") == 1024.0  # bytes

    @patch("subprocess.run")
    def test_amd_via_lspci(self, mock_run):
        """Test AMD detection via lspci."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="01:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 [Radeon RX 6800/6800 XT / 6900 XT] [1002:73bf] (rev c0)"
        )
        detector = GPUDetector()
        gpus = detector._detect_amd_via_lspci()
        assert len(gpus) == 1
        assert gpus[0].vendor == GPUVendor.AMD
        assert "Radeon RX 6800" in gpus[0].name
        assert gpus[0].device_id == "1002:73bf"

    @patch("subprocess.run")
    def test_intel_via_lspci(self, mock_run):
        """Test Intel detection via lspci."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="00:02.0 VGA compatible controller [0300]: Intel Corporation UHD Graphics [8086:9a49] (rev 01)"
        )
        detector = GPUDetector()
        gpus = detector._detect_intel_via_lspci()
        assert len(gpus) == 1
        assert gpus[0].vendor == GPUVendor.INTEL
        assert "UHD Graphics" in gpus[0].name
        assert gpus[0].device_id == "8086:9a49"


class TestGPUMetricsCollector:
    """Tests for GPUMetricsCollector."""

    def test_collect_all_empty(self):
        """Test collecting metrics when no GPUs available."""
        collector = GPUMetricsCollector()
        # With no pynvml, no rocm-smi, etc., should return empty list
        metrics = collector.collect_all()
        assert isinstance(metrics, list)


class TestGPUMonitor:
    """Tests for GPUMonitor."""

    def test_monitor_initialization(self):
        """Test GPUMonitor initialization."""
        monitor = GPUMonitor(workspace=".", enabled=True, poll_interval_seconds=5.0)
        assert monitor.enabled is True
        assert monitor.poll_interval == 5.0
        assert monitor.workspace.name == "Freya"  # Resolved workspace directory name

    def test_get_gpu_info(self):
        """Test getting GPU info."""
        monitor = GPUMonitor(workspace=".")
        info = monitor.get_gpu_info()
        assert isinstance(info, list)

    def test_get_gpu_count(self):
        """Test getting GPU count."""
        monitor = GPUMonitor(workspace=".")
        count = monitor.get_gpu_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_get_gpus_by_vendor(self):
        """Test filtering GPUs by vendor."""
        monitor = GPUMonitor(workspace=".")
        nvidia_gpus = monitor.get_gpus_by_vendor(GPUVendor.NVIDIA)
        assert isinstance(nvidia_gpus, list)

    @patch("app.monitoring.gpu_monitor.GPUDetector.detect_all")
    def test_get_summary(self, mock_detect):
        """Test getting monitoring summary."""
        mock_detect.return_value = [
            GPUInfo(index=0, vendor=GPUVendor.NVIDIA, name="RTX 3080"),
            GPUInfo(index=1, vendor=GPUVendor.AMD, name="RX 6800"),
        ]
        monitor = GPUMonitor(workspace=".")
        summary = monitor.get_summary()
        assert summary["enabled"] is True
        assert summary["total_gpus"] == 2
        assert summary["by_vendor"]["nvidia"] == 1
        assert summary["by_vendor"]["amd"] == 1
        assert len(summary["devices"]) == 2

    def test_collect_metrics(self):
        """Test collecting metrics."""
        monitor = GPUMonitor(workspace=".")
        metrics = monitor.collect_metrics()
        assert isinstance(metrics, list)

    def test_get_current_metrics(self):
        """Test getting current metrics."""
        monitor = GPUMonitor(workspace=".")
        metrics = monitor.get_current_metrics()
        assert isinstance(metrics, list)

    def test_context_manager(self):
        """Test context manager for start/stop monitoring."""
        monitor = GPUMonitor(workspace=".")
        with monitor:
            assert isinstance(monitor, GPUMonitor)

    def test_start_stop_monitoring(self):
        """Test start/stop monitoring."""
        monitor = GPUMonitor(workspace=".", poll_interval_seconds=0.1)
        monitor.start_monitoring()
        assert monitor._running is True
        import time
        time.sleep(0.2)
        monitor.stop_monitoring()
        assert monitor._running is False


class TestCreateGPUMonitor:
    """Tests for create_gpu_monitor factory function."""

    def test_create_gpu_monitor(self):
        """Test factory function."""
        monitor = create_gpu_monitor(workspace=".", enabled=True, poll_interval_seconds=10.0)
        assert isinstance(monitor, GPUMonitor)
        assert monitor.enabled is True
        assert monitor.poll_interval == 10.0


class TestGPUIntegration:
    """Integration tests for GPU monitoring."""

    def test_gpu_monitor_with_event_bus(self):
        """Test GPU monitor integration with EventBus."""
        from app.core.events import get_event_bus, EventBus
        event_bus = get_event_bus()
        monitor = GPUMonitor(workspace=".", event_bus=event_bus)
        assert monitor.event_bus is event_bus

    def test_gpu_monitor_publishes_events(self):
        """Test that GPU monitor emits events."""
        from app.core.events import get_event_bus
        event_bus = get_event_bus()

        received_events = []

        def capture_event(event):
            received_events.append(event)

        sub_id = event_bus.subscribe("gpu.*", capture_event)

        monitor = GPUMonitor(workspace=".", event_bus=event_bus)
        # Initial detection should emit gpu.detected events

        # Give some time for events to be emitted
        import time
        time.sleep(0.5)

        # Cleanup
        event_bus.unsubscribe(sub_id)
        assert len(received_events) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestGPUHealthRegression:
    """Task 9 regression tests that do not require physical GPU hardware."""

    def test_detected_gpu_reports_healthy_capability(self):
        detected = [GPUInfo(index=0, vendor=GPUVendor.NVIDIA, name="Test GPU")]
        with patch("app.monitoring.gpu_monitor.GPUDetector.detect_all", return_value=detected):
            monitor = GPUMonitor(workspace=".")

        health = monitor.get_health()
        assert health["status"] == "healthy"
        assert health["availability"] == "available"
        assert health["fallback_active"] is False

    def test_no_gpu_reports_unavailable_and_cpu_fallback_event(self):
        from app.core.events import EventBus

        event_bus = EventBus()
        events = []
        subscription = event_bus.subscribe("gpu.*", lambda event, _data: events.append(event))
        with patch("app.monitoring.gpu_monitor.GPUDetector.detect_all", return_value=[]):
            monitor = GPUMonitor(workspace=".", event_bus=event_bus)
        event_bus.unsubscribe(subscription)

        health = monitor.get_health()
        assert health["status"] == "unavailable"
        assert health["availability"] == "unavailable"
        assert health["fallback_active"] is True
        assert {event.name for event in events} == {"gpu.unavailable", "gpu.fallback_activated"}

    def test_detection_failure_is_observable_without_startup_crash(self):
        from app.core.events import EventBus

        event_bus = EventBus()
        events = []
        subscription = event_bus.subscribe("gpu.*", lambda event, _data: events.append(event))
        with patch(
            "app.monitoring.gpu_monitor.GPUDetector.detect_all",
            side_effect=RuntimeError("vendor probe failed"),
        ):
            monitor = GPUMonitor(workspace=".", event_bus=event_bus)
        event_bus.unsubscribe(subscription)

        health = monitor.get_health()
        assert health["status"] == "degraded"
        assert health["error_category"] == "probe_failure"
        assert health["fallback_active"] is True
        assert {event.name for event in events} == {"gpu.probe_failed", "gpu.fallback_activated"}

    def test_metrics_failure_never_masquerades_as_healthy(self):
        detected = [GPUInfo(index=0, vendor=GPUVendor.NVIDIA, name="Test GPU")]
        with patch("app.monitoring.gpu_monitor.GPUDetector.detect_all", return_value=detected):
            monitor = GPUMonitor(workspace=".")
        with patch.object(monitor._collector, "collect_all", side_effect=RuntimeError("metrics failed")):
            assert monitor.collect_metrics() == []

        health = monitor.get_health()
        assert health["status"] == "degraded"
        assert health["availability"] == "available"
        assert health["error_category"] == "metrics_failure"

    def test_disabled_monitor_does_not_start_background_polling(self):
        monitor = GPUMonitor(workspace=".", enabled=False)

        monitor.start_monitoring()

        assert monitor._running is False
        assert monitor.get_health()["status"] == "disabled"
