"""Tests for the Network/Service Monitor module."""

import asyncio
import json
import socket
import pytest
from unittest.mock import patch, MagicMock, Mock, AsyncMock
from datetime import datetime, timezone

from app.monitoring.network_monitor import (
    NetworkMonitor,
    NetworkHealthChecker,
    ServiceConfig,
    EndpointConfig,
    ServiceHealth,
    HealthCheckResult,
    CheckType,
    ServiceStatus,
    quick_http_check,
    quick_tcp_check,
    quick_dns_check,
)


class TestEndpointConfig:
    """Tests for EndpointConfig."""

    def test_endpoint_config_creation(self):
        """Test creating an endpoint configuration."""
        endpoint = EndpointConfig(
            name="api_health",
            url="https://api.example.com/health",
            check_type=CheckType.HTTPS,
            timeout_seconds=10.0,
            expected_status_codes=[200],
            interval_seconds=60.0,
            enabled=True,
            max_retries=3,
            retry_delay_seconds=2.0,
            max_latency_ms=5000.0,
        )
        assert endpoint.name == "api_health"
        assert endpoint.check_type == CheckType.HTTPS
        assert endpoint.timeout_seconds == 10.0
        assert endpoint.max_retries == 3

    def test_endpoint_config_from_dict(self):
        """Test creating endpoint from dictionary."""
        data = {
            "name": "api_check",
            "url": "http://localhost:8080/health",
            "check_type": "tcp",
            "timeout_seconds": 5.0,
            "expected_status_codes": [200],
            "interval_seconds": 30.0,
            "enabled": True,
            "max_retries": 2,
            "retry_delay_seconds": 1.0,
            "max_latency_ms": 2000.0,
        }
        endpoint = EndpointConfig.from_dict(data)
        assert endpoint.name == "api_check"
        assert endpoint.check_type == CheckType.TCP
        assert endpoint.timeout_seconds == 5.0

    def test_endpoint_config_to_dict(self):
        """Test converting endpoint to dictionary."""
        endpoint = EndpointConfig(
            name="test_endpoint",
            url="https://api.test.com/status",
            check_type=CheckType.HTTP,
        )
        d = endpoint.to_dict()
        assert d["name"] == "test_endpoint"
        assert d["url"] == "https://api.test.com/status"
        assert d["check_type"] == "http"


class TestServiceConfig:
    """Tests for ServiceConfig."""

    def test_service_config_creation(self):
        """Test creating a service configuration."""
        endpoint = EndpointConfig(name="ep1", url="http://localhost:8000/health")
        service = ServiceConfig(
            name="my_service",
            description="Test service",
            endpoints=[endpoint],
            check_interval_seconds=60.0,
            depends_on=["database"],
        )
        assert service.name == "my_service"
        assert len(service.endpoints) == 1
        assert "database" in service.depends_on

    def test_service_config_from_dict(self):
        """Test creating service from dictionary."""
        data = {
            "name": "api",
            "description": "API Service",
            "endpoints": [
                {"name": "health", "url": "http://localhost:8000/health"},
            ],
            "check_interval_seconds": 30.0,
            "depends_on": ["redis", "postgres"],
        }
        service = ServiceConfig.from_dict(data)
        assert service.name == "api"
        assert len(service.endpoints) == 1
        assert "redis" in service.depends_on


class TestHealthCheckResult:
    """Tests for HealthCheckResult."""

    def test_health_check_result_creation(self):
        """Test creating a health check result."""
        result = HealthCheckResult(
            endpoint_name="health_endpoint",
            service_name="api",
            check_type=CheckType.HTTP,
            status=ServiceStatus.HEALTHY,
            success=True,
            latency_ms=50.0,
            status_code=200,
            resolved_ip="192.168.1.1",
        )
        assert result.endpoint_name == "health_endpoint"
        assert result.service_name == "api"
        assert result.success is True
        assert result.latency_ms == 50.0

    def test_health_check_result_to_dict(self):
        """Test converting health check result to dictionary."""
        result = HealthCheckResult(
            endpoint_name="ep1",
            service_name="service1",
            check_type=CheckType.HTTPS,
            status=ServiceStatus.UNHEALTHY,
            success=False,
            latency_ms=1000.0,
            status_code=500,
            error_message="Internal server error",
            response_content="Internal Server Error",
        )
        d = result.to_dict()
        assert d["endpoint_name"] == "ep1"
        assert d["status"] == "unhealthy"
        assert d["success"] is False
        assert d["latency_ms"] == 1000.0
        assert d["error_message"] == "Internal server error"


class TestServiceHealth:
    """Tests for ServiceHealth."""

    def test_service_health_creation(self):
        """Test creating service health."""
        health = ServiceHealth(name="api", status=ServiceStatus.HEALTHY)
        assert health.name == "api"
        assert health.status == ServiceStatus.HEALTHY

    def test_service_health_to_dict(self):
        """Test converting service health to dictionary."""
        result = HealthCheckResult(
            endpoint_name="ep1",
            service_name="api",
            check_type=CheckType.HTTP,
            status=ServiceStatus.HEALTHY,
            success=True,
            latency_ms=50.0,
        )
        health = ServiceHealth(
            name="api",
            status=ServiceStatus.HEALTHY,
            healthy_endpoints=2,
            total_endpoints=2,
            consecutive_successes=5,
            uptime_percentage=99.5,
            last_results=[result],
        )
        d = health.to_dict()
        assert d["name"] == "api"
        assert d["status"] == "healthy"
        assert d["healthy_endpoints"] == 2
        assert d["consecutive_successes"] == 5
        assert len(d["recent_results"]) == 1


class TestCheckType:
    """Tests for CheckType enum."""

    def test_check_type_values(self):
        """Test check type enum values."""
        assert CheckType.TCP.value == "tcp"
        assert CheckType.HTTP.value == "http"
        assert CheckType.HTTPS.value == "https"
        assert CheckType.DNS.value == "dns"
        assert CheckType.ICMP.value == "icmp"


class TestServiceStatus:
    """Tests for ServiceStatus enum."""

    def test_service_status_values(self):
        """Test service status enum values."""
        assert ServiceStatus.HEALTHY.value == "healthy"
        assert ServiceStatus.DEGRADED.value == "degraded"
        assert ServiceStatus.UNHEALTHY.value == "unhealthy"
        assert ServiceStatus.UNKNOWN.value == "unknown"


class TestNetworkHealthChecker:
    """Tests for NetworkHealthChecker."""

    @pytest.mark.asyncio
    async def test_check_tcp_success(self):
        """Test successful TCP check."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_reader = AsyncMock()
            mock_writer = AsyncMock()
            mock_open.return_value = (mock_reader, mock_writer)

            with patch("socket.gethostbyname", return_value="127.0.0.1"):
                result = await checker.check_tcp("localhost", 8000, timeout=5.0)

            assert result.success is True
            assert result.status == ServiceStatus.HEALTHY
            assert result.resolved_ip == "127.0.0.1"
            # Note: latency may be 0 in mocked tests
            assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_tcp_timeout(self):
        """Test TCP check timeout."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        with patch("asyncio.open_connection", side_effect=asyncio.TimeoutError()):
            result = await checker.check_tcp("localhost", 8000, timeout=5.0)

        assert result.success is False
        assert result.status == ServiceStatus.UNHEALTHY
        assert "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_check_tcp_connection_error(self):
        """Test TCP check connection error."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError("Connection refused")):
            result = await checker.check_tcp("localhost", 8000, timeout=5.0)

        assert result.success is False
        assert result.status == ServiceStatus.UNHEALTHY
        assert "connection refused" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_check_http_success(self):
        """Test successful HTTP check."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        # Create a proper async context manager mock
        class MockResponse:
            def __init__(self):
                self.status = 200
            async def text(self):
                return '{"status": "ok"}'
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        mock_session = AsyncMock()
        mock_response = MockResponse()
        # Use regular Mock for get() to return the async context manager directly
        mock_session.get = Mock(return_value=mock_response)

        with patch.object(checker, "_get_session", return_value=mock_session):
            with patch("socket.gethostbyname", return_value="127.0.0.1"):
                result = await checker.check_http(
                    "http://localhost:8000/health",
                    expected_status_codes=[200],
                    expected_content="ok",
                )

        assert result.success is True
        assert result.status == ServiceStatus.HEALTHY
        assert result.status_code == 200
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_http_wrong_status(self):
        """Test HTTP check with wrong status code."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        class MockResponse:
            def __init__(self):
                self.status = 500
            async def text(self):
                return "Internal Server Error"
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        mock_session = AsyncMock()
        mock_response = MockResponse()
        mock_session.get = Mock(return_value=mock_response)

        with patch.object(checker, "_get_session", return_value=mock_session):
            result = await checker.check_http(
                "http://localhost:8000/health",
                expected_status_codes=[200],
            )

        assert result.success is False
        assert result.status == ServiceStatus.DEGRADED
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_http_timeout(self):
        """Test HTTP check timeout."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        mock_session = AsyncMock()
        mock_session.get = Mock(side_effect=asyncio.TimeoutError())

        with patch.object(checker, "_get_session", return_value=mock_session):
            result = await checker.check_http("http://localhost:8000/health", timeout=5.0)

        assert result.success is False
        assert result.status == ServiceStatus.UNHEALTHY
        assert "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_check_dns_success(self):
        """Test successful DNS check."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(return_value=[
                (0, 0, 0, "", ("127.0.0.1", 0)),
                (0, 0, 0, "", ("::1", 0)),
            ])

            result = await checker.check_dns("localhost", timeout=5.0)

        assert result.success is True
        assert result.status == ServiceStatus.HEALTHY
        assert result.resolved_ip in ["127.0.0.1", "::1"]
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_dns_failure(self):
        """Test DNS check failure."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                side_effect=socket.gaierror("Name or service not known")
            )

            result = await checker.check_dns("nonexistent.domain.invalid", timeout=5.0)

        assert result.success is False
        assert result.status == ServiceStatus.UNHEALTHY
        assert "dns" in result.error_message.lower() or "resolution" in result.error_message.lower() or "name or service not known" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing aiohttp session."""
        checker = NetworkHealthChecker(default_timeout=5.0)

        mock_session = AsyncMock()
        mock_session.closed = False
        checker._session = mock_session

        await checker.close()

        mock_session.close.assert_awaited_once()


class TestNetworkMonitor:
    """Tests for NetworkMonitor."""

    def test_monitor_initialization(self):
        """Test NetworkMonitor initialization."""
        monitor = NetworkMonitor(workspace=".", default_check_interval=60.0)
        assert monitor.workspace.name == "Freya"  # Resolved workspace directory name
        assert monitor.default_check_interval == 60.0
        assert monitor._running is False
        assert len(monitor._services) == 0

    def test_register_service(self):
        """Test registering a service."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])

        monitor.register_service(service)

        assert "api" in monitor._services
        assert "api" in monitor._service_health
        assert monitor._services["api"] == service

    def test_unregister_service(self):
        """Test unregistering a service."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])

        monitor.register_service(service)
        monitor.unregister_service("api")

        assert "api" not in monitor._services
        assert "api" not in monitor._service_health

    def test_get_service(self):
        """Test getting a service by name."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])

        monitor.register_service(service)

        retrieved = monitor.get_service("api")
        assert retrieved == service

        not_found = monitor.get_service("nonexistent")
        assert not_found is None

    def test_list_services(self):
        """Test listing all services."""
        monitor = NetworkMonitor(workspace=".")
        endpoint1 = EndpointConfig(name="health", url="http://localhost:8000/health")
        endpoint2 = EndpointConfig(name="ready", url="http://localhost:8000/ready")
        service1 = ServiceConfig(name="api", endpoints=[endpoint1])
        service2 = ServiceConfig(name="worker", endpoints=[endpoint2])

        monitor.register_service(service1)
        monitor.register_service(service2)

        services = monitor.list_services()
        assert len(services) == 2
        names = [s.name for s in services]
        assert "api" in names
        assert "worker" in names

    def test_get_service_health(self):
        """Test getting service health."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])

        monitor.register_service(service)

        health = monitor.get_service_health("api")
        assert health is not None
        assert health.name == "api"
        assert health.status == ServiceStatus.UNKNOWN

    def test_get_all_health(self):
        """Test getting all service health."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])

        monitor.register_service(service)

        all_health = monitor.get_all_health()
        assert "api" in all_health
        assert all_health["api"].name == "api"

    def test_add_health_change_callback(self):
        """Test adding health change callback."""
        monitor = NetworkMonitor(workspace=".")
        callback_called = []

        def callback(service_name, old_status, new_status):
            callback_called.append((service_name, old_status, new_status))

        monitor.add_health_change_callback(callback)
        assert len(monitor._health_change_callbacks) == 1

    def test_add_check_complete_callback(self):
        """Test adding check complete callback."""
        monitor = NetworkMonitor(workspace=".")
        callback_called = []

        def callback(result):
            callback_called.append(result)

        monitor.add_check_complete_callback(callback)
        assert len(monitor._check_complete_callbacks) == 1

    @pytest.mark.asyncio
    async def test_check_service_no_endpoints(self):
        """Test checking service with no enabled endpoints."""
        monitor = NetworkMonitor(workspace=".")
        service = ServiceConfig(name="api", endpoints=[])
        monitor.register_service(service)

        results = await monitor.check_service("api")
        assert results == []

    @pytest.mark.asyncio
    async def test_check_all_services(self):
        """Test checking all services."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])
        monitor.register_service(service)

        with patch.object(monitor, "check_service", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = []

            results = await monitor.check_all_services()

            assert "api" in results
            mock_check.assert_called_once_with("api")

    def test_get_summary(self):
        """Test getting monitoring summary."""
        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint])
        monitor.register_service(service)

        summary = monitor.get_summary()
        assert summary["monitoring"] is False
        assert summary["total_services"] == 1
        assert summary["enabled_services"] == 1
        assert "api" in summary["services"]

    def test_get_check_history(self):
        """Test getting check history."""
        monitor = NetworkMonitor(workspace=".")
        # Add some fake history
        result = HealthCheckResult(
            endpoint_name="ep1",
            service_name="api",
            check_type=CheckType.HTTP,
            status=ServiceStatus.HEALTHY,
            success=True,
            latency_ms=50.0,
        )
        monitor._check_history = [result]

        history = monitor.get_check_history()
        assert len(history) == 1

        history_filtered = monitor.get_check_history(count=1)
        assert len(history_filtered) == 1

        history_none = monitor.get_check_history(service_name="nonexistent")
        assert len(history_none) == 0

    def test_load_services_from_config(self, tmp_path):
        """Test loading services from config file."""
        config_file = tmp_path / "services.json"
        config_data = {
            "services": [
                {
                    "name": "api",
                    "description": "API Service",
                    "endpoints": [
                        {"name": "health", "url": "http://localhost:8000/health"}
                    ],
                }
            ]
        }
        config_file.write_text(json.dumps(config_data))

        monitor = NetworkMonitor(workspace=".")
        monitor.load_services_from_config(str(config_file))

        assert "api" in monitor._services
        assert len(monitor._services["api"].endpoints) == 1

    def test_save_services_to_config(self, tmp_path):
        """Test saving services to config file."""
        config_file = tmp_path / "services.json"

        monitor = NetworkMonitor(workspace=".")
        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint], description="API Service")
        monitor.register_service(service)

        monitor.save_services_to_config(str(config_file))

        import json
        with open(config_file, "r") as f:
            data = json.load(f)

        assert "services" in data
        assert len(data["services"]) == 1
        assert data["services"][0]["name"] == "api"


class TestQuickChecks:
    """Tests for quick check convenience functions."""

    @pytest.mark.asyncio
    async def test_quick_http_check(self):
        """Test quick HTTP check."""
        with patch("app.monitoring.network_monitor.NetworkHealthChecker.check_http", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = HealthCheckResult(
                endpoint_name="test",
                service_name="",
                check_type=CheckType.HTTP,
                status=ServiceStatus.HEALTHY,
                success=True,
                latency_ms=50.0,
                status_code=200,
            )

            result = await quick_http_check("http://localhost:8000/health", timeout=5.0)

            assert result.success is True
            assert result.status == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_quick_tcp_check(self):
        """Test quick TCP check."""
        with patch("app.monitoring.network_monitor.NetworkHealthChecker.check_tcp", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = HealthCheckResult(
                endpoint_name="localhost:8000",
                service_name="",
                check_type=CheckType.TCP,
                status=ServiceStatus.HEALTHY,
                success=True,
                latency_ms=10.0,
                resolved_ip="127.0.0.1",
            )

            result = await quick_tcp_check("localhost", 8000, timeout=5.0)

            assert result.success is True
            assert result.status == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_quick_dns_check(self):
        """Test quick DNS check."""
        with patch("app.monitoring.network_monitor.NetworkHealthChecker.check_dns", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = HealthCheckResult(
                endpoint_name="example.com",
                service_name="",
                check_type=CheckType.DNS,
                status=ServiceStatus.HEALTHY,
                success=True,
                latency_ms=20.0,
                resolved_ip="93.184.216.34",
            )

            result = await quick_dns_check("example.com", timeout=5.0)

            assert result.success is True
            assert result.status == ServiceStatus.HEALTHY


class TestNetworkMonitorIntegration:
    """Integration tests for NetworkMonitor with EventBus."""

    def test_monitor_with_event_bus(self):
        """Test NetworkMonitor with EventBus."""
        from app.core.events import get_event_bus
        event_bus = get_event_bus()

        monitor = NetworkMonitor(workspace=".", event_bus=event_bus)
        assert monitor.event_bus is event_bus

    def test_register_service_emits_event(self):
        """Test that registering a service emits event."""
        from app.core.events import get_event_bus, Event
        event_bus = get_event_bus()

        monitor = NetworkMonitor(workspace=".", event_bus=event_bus)
        received = []

        def capture(event: Event):
            received.append(event)

        sub_id = event_bus.subscribe("service.registered", capture)

        endpoint = EndpointConfig(name="health", url="http://localhost:8000/health")
        service = ServiceConfig(name="api", endpoints=[endpoint], depends_on=["db"])
        monitor.register_service(service)

        assert len(received) == 1
        assert received[0].name == "service.registered"
        assert received[0].data["service_name"] == "api"
        assert "health" in received[0].data["endpoints"]

        event_bus.unsubscribe(sub_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])