"""Network and Service Health Monitor.

This module provides network connectivity checks, API endpoint health monitoring,
and external service registry for tracking service dependencies.
"""

import asyncio
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Set
from urllib.parse import urlparse

import aiohttp

from app.monitoring.alert_manager import AlertManager, SystemAlert, AlertSeverity, AlertStatus


class CheckType(Enum):
    """Types of health checks."""
    TCP = "tcp"
    HTTP = "http"
    HTTPS = "https"
    DNS = "dns"
    ICMP = "icmp"


class ServiceStatus(Enum):
    """Status of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class EndpointConfig:
    """Configuration for an endpoint health check."""
    name: str
    url: str
    check_type: CheckType = CheckType.HTTP
    timeout_seconds: float = 10.0
    expected_status_codes: List[int] = field(default_factory=lambda: [200])
    expected_content: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    interval_seconds: float = 60.0
    enabled: bool = True
    labels: Dict[str, str] = field(default_factory=dict)
    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    # Alert thresholds
    max_latency_ms: float = 5000.0  # Alert if latency exceeds this
    # Authentication
    auth_token: Optional[str] = None
    auth_type: str = "bearer"  # bearer, basic, api_key

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EndpointConfig":
        """Create from dictionary."""
        check_type = CheckType(data.get("check_type", "http"))
        return cls(
            name=data["name"],
            url=data["url"],
            check_type=check_type,
            timeout_seconds=data.get("timeout_seconds", 10.0),
            expected_status_codes=data.get("expected_status_codes", [200]),
            expected_content=data.get("expected_content"),
            headers=data.get("headers", {}),
            interval_seconds=data.get("interval_seconds", 60.0),
            enabled=data.get("enabled", True),
            labels=data.get("labels", {}),
            max_retries=data.get("max_retries", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 2.0),
            max_latency_ms=data.get("max_latency_ms", 5000.0),
            auth_token=data.get("auth_token"),
            auth_type=data.get("auth_type", "bearer"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "url": self.url,
            "check_type": self.check_type.value,
            "timeout_seconds": self.timeout_seconds,
            "expected_status_codes": self.expected_status_codes,
            "expected_content": self.expected_content,
            "headers": self.headers,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "labels": self.labels,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "max_latency_ms": self.max_latency_ms,
            "auth_token": self.auth_token,
            "auth_type": self.auth_type,
        }


@dataclass
class ServiceConfig:
    """Configuration for a service with multiple endpoints."""
    name: str
    description: str = ""
    endpoints: List[EndpointConfig] = field(default_factory=list)
    # Service-level settings
    check_interval_seconds: float = 60.0
    enabled: bool = True
    # Dependency tracking
    depends_on: List[str] = field(default_factory=list)  # Other service names
    labels: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceConfig":
        """Create from dictionary."""
        endpoints = [EndpointConfig.from_dict(e) for e in data.get("endpoints", [])]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            endpoints=endpoints,
            check_interval_seconds=data.get("check_interval_seconds", 60.0),
            enabled=data.get("enabled", True),
            depends_on=data.get("depends_on", []),
            labels=data.get("labels", {}),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "endpoints": [e.to_dict() for e in self.endpoints],
            "check_interval_seconds": self.check_interval_seconds,
            "enabled": self.enabled,
            "depends_on": self.depends_on,
            "labels": self.labels,
            "metadata": self.metadata,
        }


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    endpoint_name: str
    service_name: str
    check_type: CheckType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: ServiceStatus = ServiceStatus.UNKNOWN
    success: bool = False
    latency_ms: float = 0.0
    status_code: Optional[int] = None
    error_message: str = ""
    response_content: str = ""
    # Additional metadata
    resolved_ip: Optional[str] = None
    ssl_cert_expiry: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "endpoint_name": self.endpoint_name,
            "service_name": self.service_name,
            "check_type": self.check_type.value,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "status_code": self.status_code,
            "error_message": self.error_message,
            "response_content": self.response_content[:500] if self.response_content else "",
            "resolved_ip": self.resolved_ip,
            "ssl_cert_expiry": self.ssl_cert_expiry,
            "metadata": self.metadata,
        }


@dataclass
class ServiceHealth:
    """Aggregated health status for a service."""
    name: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_check: Optional[str] = None
    healthy_endpoints: int = 0
    total_endpoints: int = 0
    last_results: List[HealthCheckResult] = field(default_factory=list)
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    uptime_percentage: float = 100.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check,
            "healthy_endpoints": self.healthy_endpoints,
            "total_endpoints": self.total_endpoints,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "uptime_percentage": self.uptime_percentage,
            "recent_results": [r.to_dict() for r in self.last_results[-5:]],
            "metadata": self.metadata,
        }


class NetworkHealthChecker:
    """Performs network health checks for various protocols."""

    def __init__(self, default_timeout: float = 10.0):
        self.default_timeout = default_timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.default_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def check_tcp(self, host: str, port: int, timeout: float = None) -> HealthCheckResult:
        """Check TCP connectivity to a host:port."""
        start_time = time.time()
        timeout = timeout or self.default_timeout

        try:
            # Resolve hostname
            resolved_ip = None
            try:
                resolved_ip = socket.gethostbyname(host)
            except socket.gaierror:
                pass

            # Attempt connection
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()

            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                endpoint_name=f"{host}:{port}",
                service_name="",
                check_type=CheckType.TCP,
                status=ServiceStatus.HEALTHY,
                success=True,
                latency_ms=latency_ms,
                resolved_ip=resolved_ip,
            )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                endpoint_name=f"{host}:{port}",
                service_name="",
                check_type=CheckType.TCP,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=f"Connection timeout after {timeout}s",
                resolved_ip=resolved_ip if 'resolved_ip' in locals() else None,
            )
        except Exception as e:
            return HealthCheckResult(
                endpoint_name=f"{host}:{port}",
                service_name="",
                check_type=CheckType.TCP,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
                resolved_ip=resolved_ip if 'resolved_ip' in locals() else None,
            )

    async def check_http(
        self,
        url: str,
        expected_status_codes: List[int] = None,
        expected_content: str = None,
        headers: Dict[str, str] = None,
        timeout: float = None,
        auth_token: str = None,
        auth_type: str = "bearer",
    ) -> HealthCheckResult:
        """Check HTTP/HTTPS endpoint health."""
        start_time = time.time()
        timeout = timeout or self.default_timeout
        expected_status_codes = expected_status_codes or [200]
        headers = headers or {}

        if auth_token:
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth_token}"
            elif auth_type == "api_key":
                headers["X-API-Key"] = auth_token

        parsed = urlparse(url)
        endpoint_name = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        try:
            session = await self._get_session()
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                latency_ms = (time.time() - start_time) * 1000
                status_code = response.status
                content = await response.text()

                success = status_code in expected_status_codes
                if expected_content and success:
                    success = expected_content in content

                status = ServiceStatus.HEALTHY if success else ServiceStatus.DEGRADED
                if not success and latency_ms > timeout * 1000:
                    status = ServiceStatus.UNHEALTHY

                # Check SSL cert for HTTPS
                ssl_cert_expiry = None
                if parsed.scheme == "https":
                    try:
                        # Note: aiohttp doesn't expose cert info easily
                        # This would need a separate ssl check
                        pass
                    except Exception:
                        pass

                return HealthCheckResult(
                    endpoint_name=endpoint_name,
                    service_name="",
                    check_type=CheckType.HTTPS if parsed.scheme == "https" else CheckType.HTTP,
                    status=status,
                    success=success,
                    latency_ms=latency_ms,
                    status_code=status_code,
                    error_message="" if success else f"Status {status_code} not in expected {expected_status_codes}",
                    response_content=content[:1000],
                    resolved_ip=socket.gethostbyname(parsed.hostname) if parsed.hostname else None,
                    ssl_cert_expiry=ssl_cert_expiry,
                )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                endpoint_name=endpoint_name,
                service_name="",
                check_type=CheckType.HTTPS if parsed.scheme == "https" else CheckType.HTTP,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=f"Request timeout after {timeout}s",
                resolved_ip=socket.gethostbyname(parsed.hostname) if parsed.hostname else None,
            )
        except aiohttp.ClientError as e:
            return HealthCheckResult(
                endpoint_name=endpoint_name,
                service_name="",
                check_type=CheckType.HTTPS if parsed.scheme == "https" else CheckType.HTTP,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=f"Client error: {str(e)}",
                resolved_ip=socket.gethostbyname(parsed.hostname) if parsed.hostname else None,
            )
        except Exception as e:
            return HealthCheckResult(
                endpoint_name=endpoint_name,
                service_name="",
                check_type=CheckType.HTTPS if parsed.scheme == "https" else CheckType.HTTP,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
                resolved_ip=socket.gethostbyname(parsed.hostname) if parsed.hostname else None,
            )

    async def check_dns(self, hostname: str, timeout: float = None) -> HealthCheckResult:
        """Check DNS resolution for a hostname."""
        start_time = time.time()
        timeout = timeout or self.default_timeout

        try:
            loop = asyncio.get_event_loop()
            # Use getaddrinfo for async DNS resolution
            addrinfo = await asyncio.wait_for(
                loop.getaddrinfo(hostname, None),
                timeout=timeout
            )
            ips = [ai[4][0] for ai in addrinfo]
            latency_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                endpoint_name=hostname,
                service_name="",
                check_type=CheckType.DNS,
                status=ServiceStatus.HEALTHY,
                success=True,
                latency_ms=latency_ms,
                resolved_ip=ips[0] if ips else None,
                metadata={"resolved_ips": ips},
            )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                endpoint_name=hostname,
                service_name="",
                check_type=CheckType.DNS,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=f"DNS resolution timeout after {timeout}s",
            )
        except Exception as e:
            return HealthCheckResult(
                endpoint_name=hostname,
                service_name="",
                check_type=CheckType.DNS,
                status=ServiceStatus.UNHEALTHY,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )


class NetworkMonitor:
    """Monitors network services and external dependencies."""

    def __init__(
        self,
        workspace: str = ".",
        alert_manager: Optional[AlertManager] = None,
        default_check_interval: float = 60.0,
    ):
        """Initialize the network monitor.

        Args:
            workspace: The project workspace directory.
            alert_manager: Optional alert manager for triggering alerts.
            default_check_interval: Default interval for health checks.
        """
        self.workspace = Path(workspace).resolve()
        self.alert_manager = alert_manager
        self.default_check_interval = default_check_interval

        # Services registry
        self._services: Dict[str, ServiceConfig] = {}
        self._service_health: Dict[str, ServiceHealth] = {}

        # Checker
        self._checker = NetworkHealthChecker()

        # Running state
        self._running = False
        self._check_tasks: Dict[str, asyncio.Task] = {}

        # Callbacks
        self._health_change_callbacks: List[Callable[[str, ServiceStatus, ServiceStatus], None]] = []
        self._check_complete_callbacks: List[Callable[[HealthCheckResult], None]] = []

        # History
        self._check_history: List[HealthCheckResult] = []
        self._max_history = 1000

        # Statistics
        self._stats = {
            "total_checks": 0,
            "successful_checks": 0,
            "failed_checks": 0,
            "alerts_triggered": 0,
        }

    def register_service(self, service: ServiceConfig) -> None:
        """Register a service for monitoring.

        Args:
            service: Service configuration to register.
        """
        self._services[service.name] = service
        self._service_health[service.name] = ServiceHealth(name=service.name)
        print(f"[NETWORK] Registered service: {service.name} with {len(service.endpoints)} endpoints")

    def unregister_service(self, name: str) -> None:
        """Unregister a service.

        Args:
            name: Name of the service to unregister.
        """
        self._services.pop(name, None)
        self._service_health.pop(name, None)

        # Cancel any running check task
        if name in self._check_tasks:
            self._check_tasks[name].cancel()
            del self._check_tasks[name]

    def get_service(self, name: str) -> Optional[ServiceConfig]:
        """Get a service configuration by name."""
        return self._services.get(name)

    def list_services(self) -> List[ServiceConfig]:
        """List all registered services."""
        return list(self._services.values())

    def get_service_health(self, name: str) -> Optional[ServiceHealth]:
        """Get health status for a service."""
        return self._service_health.get(name)

    def get_all_health(self) -> Dict[str, ServiceHealth]:
        """Get health status for all services."""
        return self._service_health.copy()

    def add_health_change_callback(self, callback: Callable[[str, ServiceStatus, ServiceStatus], None]) -> None:
        """Add callback for health status changes."""
        self._health_change_callbacks.append(callback)

    def add_check_complete_callback(self, callback: Callable[[HealthCheckResult], None]) -> None:
        """Add callback for completed health checks."""
        self._check_complete_callbacks.append(callback)

    async def check_service(self, service_name: str) -> List[HealthCheckResult]:
        """Check all endpoints for a service.

        Args:
            service_name: Name of the service to check.

        Returns:
            List of health check results.
        """
        service = self._services.get(service_name)
        if not service or not service.enabled:
            return []

        health = self._service_health.get(service_name)
        if not health:
            health = ServiceHealth(name=service_name)
            self._service_health[service_name] = health

        old_status = health.status
        results = []

        for endpoint in service.endpoints:
            if not endpoint.enabled:
                continue

            result = await self._check_endpoint(service_name, endpoint)
            results.append(result)

            # Notify check complete callbacks
            for callback in self._check_complete_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    print(f"[NETWORK] Error in check complete callback: {e}")

        # Update service health
        self._update_service_health(service_name, results)

        # Check for health status change
        if health.status != old_status:
            for callback in self._health_change_callbacks:
                try:
                    callback(service_name, old_status, health.status)
                except Exception as e:
                    print(f"[NETWORK] Error in health change callback: {e}")

        return results

    async def _check_endpoint(self, service_name: str, endpoint: EndpointConfig) -> HealthCheckResult:
        """Check a single endpoint with retries."""
        last_result = None

        for attempt in range(endpoint.max_retries):
            if endpoint.check_type in (CheckType.HTTP, CheckType.HTTPS):
                result = await self._checker.check_http(
                    endpoint.url,
                    expected_status_codes=endpoint.expected_status_codes,
                    expected_content=endpoint.expected_content,
                    headers=endpoint.headers,
                    timeout=endpoint.timeout_seconds,
                    auth_token=endpoint.auth_token,
                    auth_type=endpoint.auth_type,
                )
            elif endpoint.check_type == CheckType.TCP:
                # Parse host:port from URL
                parsed = urlparse(endpoint.url)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if not host:
                    result = HealthCheckResult(
                        endpoint_name=endpoint.name,
                        service_name=service_name,
                        check_type=CheckType.TCP,
                        status=ServiceStatus.UNHEALTHY,
                        success=False,
                        error_message="Invalid URL for TCP check",
                    )
                else:
                    result = await self._checker.check_tcp(host, port, endpoint.timeout_seconds)
            elif endpoint.check_type == CheckType.DNS:
                parsed = urlparse(endpoint.url)
                host = parsed.hostname or endpoint.url
                result = await self._checker.check_dns(host, endpoint.timeout_seconds)
            else:
                result = HealthCheckResult(
                    endpoint_name=endpoint.name,
                    service_name=service_name,
                    check_type=endpoint.check_type,
                    status=ServiceStatus.UNHEALTHY,
                    success=False,
                    error_message=f"Unsupported check type: {endpoint.check_type}",
                )

            result.service_name = service_name
            result.endpoint_name = endpoint.name
            last_result = result

            # Update stats
            self._stats["total_checks"] += 1
            if result.success:
                self._stats["successful_checks"] += 1
            else:
                self._stats["failed_checks"] += 1

            # Add to history
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history:]

            # If successful, break retry loop
            if result.success:
                break

            # Wait before retry
            if attempt < endpoint.max_retries - 1:
                await asyncio.sleep(endpoint.retry_delay_seconds)

        # Check latency threshold and trigger alert if needed
        if last_result and last_result.latency_ms > endpoint.max_latency_ms:
            await self._trigger_latency_alert(service_name, endpoint, last_result)

        return last_result

    async def _trigger_latency_alert(self, service_name: str, endpoint: EndpointConfig, result: HealthCheckResult) -> None:
        """Trigger alert for high latency."""
        if not self.alert_manager:
            return

        alert = SystemAlert(
            id=f"latency_{service_name}_{endpoint.name}_{int(time.time())}",
            title=f"High Latency: {service_name}/{endpoint.name}",
            description=f"Endpoint {endpoint.name} latency ({result.latency_ms:.0f}ms) exceeds threshold ({endpoint.max_latency_ms}ms)",
            severity=AlertSeverity.HIGH,
            metric_name=f"latency_{service_name}_{endpoint.name}",
            current_value=result.latency_ms,
            threshold=endpoint.max_latency_ms,
            tags=["network", "latency", service_name, endpoint.name],
            context={
                "service_name": service_name,
                "endpoint_name": endpoint.name,
                "url": endpoint.url,
                "check_type": endpoint.check_type.value,
            },
        )
        self.alert_manager.trigger(alert)
        self._stats["alerts_triggered"] += 1

    def _update_service_health(self, service_name: str, results: List[HealthCheckResult]) -> None:
        """Update aggregated service health from check results."""
        health = self._service_health[service_name]
        health.last_check = datetime.now(timezone.utc).isoformat()
        health.last_results = results
        health.total_endpoints = len(results)

        healthy_count = sum(1 for r in results if r.success)
        health.healthy_endpoints = healthy_count

        if healthy_count == 0:
            health.status = ServiceStatus.UNHEALTHY
        elif healthy_count == len(results):
            health.status = ServiceStatus.HEALTHY
        else:
            health.status = ServiceStatus.DEGRADED

        # Update consecutive counts
        if health.healthy_endpoints == health.total_endpoints:
            health.consecutive_successes += 1
            health.consecutive_failures = 0
        else:
            health.consecutive_failures += 1
            health.consecutive_successes = 0

        # Calculate uptime percentage (simplified)
        total_checks = health.consecutive_successes + health.consecutive_failures
        if total_checks > 0:
            health.uptime_percentage = (health.consecutive_successes / total_checks) * 100

    async def check_all_services(self) -> Dict[str, List[HealthCheckResult]]:
        """Check all registered services.

        Returns:
            Dictionary mapping service names to check results.
        """
        results = {}
        for service_name in self._services:
            if self._services[service_name].enabled:
                results[service_name] = await self.check_service(service_name)
        return results

    async def start_monitoring(self) -> None:
        """Start continuous monitoring of all services."""
        if self._running:
            return

        self._running = True
        print(f"[NETWORK] Starting monitoring for {len(self._services)} services")

        for service_name, service in self._services.items():
            if service.enabled:
                task = asyncio.create_task(self._monitor_service(service_name))
                self._check_tasks[service_name] = task

    async def stop_monitoring(self) -> None:
        """Stop continuous monitoring."""
        self._running = False

        # Cancel all check tasks
        for task in self._check_tasks.values():
            task.cancel()

        # Wait for tasks to complete
        if self._check_tasks:
            await asyncio.gather(*self._check_tasks.values(), return_exceptions=True)

        self._check_tasks.clear()
        await self._checker.close()

        print("[NETWORK] Monitoring stopped")

    async def _monitor_service(self, service_name: str) -> None:
        """Background task to monitor a single service."""
        service = self._services.get(service_name)
        if not service:
            return

        interval = service.check_interval_seconds or self.default_check_interval

        while self._running:
            try:
                await self.check_service(service_name)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[NETWORK] Error checking service {service_name}: {e}")

            # Wait for interval
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of network monitoring status."""
        healthy_services = sum(1 for h in self._service_health.values() if h.status == ServiceStatus.HEALTHY)
        degraded_services = sum(1 for h in self._service_health.values() if h.status == ServiceStatus.DEGRADED)
        unhealthy_services = sum(1 for h in self._service_health.values() if h.status == ServiceStatus.UNHEALTHY)

        return {
            "monitoring": self._running,
            "total_services": len(self._services),
            "enabled_services": sum(1 for s in self._services.values() if s.enabled),
            "healthy_services": healthy_services,
            "degraded_services": degraded_services,
            "unhealthy_services": unhealthy_services,
            "stats": self._stats.copy(),
            "services": {name: health.to_dict() for name, health in self._service_health.items()},
        }

    def get_check_history(self, count: Optional[int] = None, service_name: Optional[str] = None) -> List[HealthCheckResult]:
        """Get check history."""
        history = self._check_history

        if service_name:
            history = [r for r in history if r.service_name == service_name]

        if count:
            history = history[-count:]

        return history

    def load_services_from_config(self, config_path: str) -> None:
        """Load services from a JSON configuration file."""
        import json
        path = Path(config_path)
        if not path.exists():
            print(f"[NETWORK] Config file not found: {config_path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for service_data in data.get("services", []):
            service = ServiceConfig.from_dict(service_data)
            self.register_service(service)

    def save_services_to_config(self, config_path: str) -> None:
        """Save current services to a JSON configuration file."""
        import json
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "services": [s.to_dict() for s in self._services.values()],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop_monitoring()


# Convenience functions for common checks
async def quick_http_check(url: str, timeout: float = 10.0) -> HealthCheckResult:
    """Quick HTTP health check."""
    checker = NetworkHealthChecker(timeout)
    try:
        return await checker.check_http(url)
    finally:
        await checker.close()


async def quick_tcp_check(host: str, port: int, timeout: float = 5.0) -> HealthCheckResult:
    """Quick TCP connectivity check."""
    checker = NetworkHealthChecker(timeout)
    try:
        return await checker.check_tcp(host, port)
    finally:
        await checker.close()


async def quick_dns_check(hostname: str, timeout: float = 5.0) -> HealthCheckResult:
    """Quick DNS resolution check."""
    checker = NetworkHealthChecker(timeout)
    try:
        return await checker.check_dns(hostname)
    finally:
        await checker.close()