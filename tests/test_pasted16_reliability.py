from pathlib import Path
from unittest.mock import MagicMock, patch

from main import FreyaApp
from app.core.observability import SystemMetricsCollector
from tests.test_capability_routing_regression import PROMPTS


EXPECTED_CAPABILITIES = set(PROMPTS)


def test_all_42_capabilities_are_registered_callable_and_reachable():
    app = FreyaApp(Path.cwd())
    app.start()
    try:
        router = app.system.facade._control._router
        registered = set(router.get_capabilities())
        assert EXPECTED_CAPABILITIES <= registered
        for name, prompt in PROMPTS.items():
            capability = router.get_capability(name)
            assert capability is not None
            assert callable(capability.handler)
            assert router.find_matching_capabilities(prompt)[0][0] == name
            route = router.route(prompt)
            assert route.capability_name == name
    finally:
        app.shutdown()


def test_system_metrics_zero_duration_collection_is_safe():
    collector = SystemMetricsCollector(MagicMock())
    collector._last_disk_io = __import__("psutil").disk_io_counters()
    collector._last_net_io = __import__("psutil").net_io_counters()
    collector._last_time = 100.0

    with patch("app.core.observability.time.time", return_value=100.0):
        metrics = collector.collect_once()

    assert metrics["system.disk.read_mb_s"] == 0
    assert metrics["system.disk.write_mb_s"] == 0
    assert metrics["system.network.sent_mb_s"] == 0
    assert metrics["system.network.recv_mb_s"] == 0
