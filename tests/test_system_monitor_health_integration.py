"""Focused Task 9 tests for verified monitoring health aggregation."""

from unittest.mock import patch

from app.monitoring.gpu_monitor import GPUMonitor
from app.monitoring.network_monitor import ServiceHealth, ServiceStatus
from app.monitoring.system_monitor import ResourceMetrics, SystemHealthStatus, SystemMonitor


class StaticNetworkMonitor:
    def __init__(self, health):
        self.health = health

    def get_all_health(self):
        return self.health


def _metrics() -> ResourceMetrics:
    return ResourceMetrics(
        cpu_percent=0.0,
        memory_percent=0.0,
        disk_percent=0.0,
        gpus=[],
    )


def test_verified_healthy_service_preserves_ready_system_health():
    network = StaticNetworkMonitor({
        "api": ServiceHealth(
            name="api",
            status=ServiceStatus.HEALTHY,
            last_check="2026-08-14T00:00:00+00:00",
            metadata={"verified": True},
        )
    })
    monitor = SystemMonitor(network_monitor=network)

    assert monitor._calculate_overall_health_status(_metrics()) == SystemHealthStatus.EXCELLENT


def test_unverified_or_unhealthy_service_cannot_report_ready_health():
    network = StaticNetworkMonitor({
        "api": ServiceHealth(
            name="api",
            status=ServiceStatus.UNHEALTHY,
            last_check="2026-08-14T00:00:00+00:00",
            metadata={"verified": True, "error_categories": ["connection_failure"]},
        ),
        "pending": ServiceHealth(name="pending", status=ServiceStatus.UNKNOWN),
    })
    monitor = SystemMonitor(network_monitor=network)

    assert monitor._calculate_overall_health_status(_metrics()) == SystemHealthStatus.WARNING
    assert monitor._calculate_overall_health_score(_metrics()) == 59.0


def test_optional_gpu_absence_does_not_make_system_health_unready():
    with patch("app.monitoring.gpu_monitor.GPUDetector.detect_all", return_value=[]):
        gpu_monitor = GPUMonitor(workspace=".")

    assert gpu_monitor.get_health()["availability"] == "unavailable"
    assert gpu_monitor.get_health()["fallback_active"] is True
    assert SystemMonitor()._calculate_overall_health_status(_metrics()) == SystemHealthStatus.EXCELLENT


def test_system_summary_exposes_verified_gpu_capability_health():
    monitor = SystemMonitor()
    monitor._gpu_monitor = type(
        "StaticGPUMonitor",
        (),
        {
            "collect_metrics": staticmethod(lambda: []),
            "get_summary": staticmethod(lambda: {
                "total_gpus": 0,
                "by_vendor": {},
                "health": {
                    "component": "gpu",
                    "status": "unavailable",
                    "availability": "unavailable",
                    "fallback_active": True,
                },
            }),
        },
    )()

    with patch("app.monitoring.system_monitor.ResourceMetrics.collect", return_value=_metrics()):
        summary = monitor.get_summary()

    assert summary["gpu"]["health"]["availability"] == "unavailable"
    assert summary["gpu"]["health"]["fallback_active"] is True
