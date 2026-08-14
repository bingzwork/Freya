"""
ObservabilityHub - Centralized monitoring and observability for Freya.

Consolidates monitoring functionality from:
- app/monitoring/system_monitor.py (system resources)
- app/monitoring/alert_manager.py (alerts)
- app/monitoring/metric_collector.py (metrics)
- app/monitoring/process_monitor.py (process tracking)
- app/monitoring/project_metrics.py (project-specific metrics)

Provides unified:
- Health monitoring
- Metrics collection and aggregation
- Status reporting
- Error reporting
- Performance monitoring
- Component registration and tracking
- Unified observability interfaces
"""

import asyncio
import threading
import time
import psutil
import platform
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from app.core.logger import logger, FreyaLogger
from app.core.events import EventBus, get_event_bus, Event, EventPriority


class HealthStatus(Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentType(Enum):
    """Types of monitored components."""
    SYSTEM = "system"
    AGENT = "agent"
    SERVICE = "service"
    PIPELINE = "pipeline"
    MEMORY = "memory"
    TOOL = "tool"
    EXTERNAL = "external"


@dataclass
class HealthCheck:
    """Health check definition."""
    name: str
    check_func: Callable[[], bool]
    component: str
    component_type: ComponentType = ComponentType.SERVICE
    interval_seconds: float = 30.0
    timeout_seconds: float = 5.0
    critical: bool = False
    tags: Dict[str, str] = field(default_factory=dict)
    # Runtime state (not part of constructor)
    _last_run_time: float = field(default=0.0, init=False, repr=False)


@dataclass
class HealthResult:
    """Result of a health check."""
    name: str
    component: str
    status: HealthStatus
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Sync details and metadata for backward compatibility
        if self.details and not self.metadata:
            self.metadata = self.details
        elif self.metadata and not self.details:
            self.details = self.metadata


@dataclass
class MetricPoint:
    """Single metric data point."""
    name: str
    value: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    labels: Dict[str, str] = field(default_factory=dict)
    unit: str = ""


@dataclass
class ComponentInfo:
    """Registered component information."""
    name: str
    component_type: ComponentType
    version: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_heartbeat: Optional[str] = None
    status: HealthStatus = HealthStatus.UNKNOWN
    tags: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """Collects and aggregates metrics."""

    def __init__(self, max_points_per_metric: int = 1000):
        self.max_points_per_metric = max_points_per_metric
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_points_per_metric))
        self._lock = threading.RLock()
        self._aggregators: Dict[str, Callable[[List[MetricPoint]], float]] = {}

    def record(self, metric: MetricPoint) -> None:
        """Record a metric point."""
        with self._lock:
            self._metrics[metric.name].append(metric)

    def record_value(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        unit: str = "",
    ) -> None:
        """Record a metric value."""
        self.record(MetricPoint(
            name=name,
            value=value,
            labels=labels or {},
            unit=unit,
        ))

    def get_latest(self, name: str) -> Optional[MetricPoint]:
        """Get latest metric value."""
        with self._lock:
            points = self._metrics.get(name)
            return points[-1] if points else None

    def get_history(
        self,
        name: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[MetricPoint]:
        """Get metric history."""
        with self._lock:
            points = list(self._metrics.get(name, []))
            if since:
                points = [p for p in points if datetime.fromisoformat(p.timestamp.replace('Z', '+00:00')) > since]
            if limit:
                points = points[-limit:]
            return points

    def get_summary(self, name: str, window_seconds: float = 300) -> Dict[str, Any]:
        """Get metric summary over a time window."""
        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        points = self.get_history(name, since=since)

        if not points:
            return {"name": name, "count": 0}

        values = [p.value for p in points]
        return {
            "name": name,
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1],
            "unit": points[-1].unit if points else "",
            "window_seconds": window_seconds,
        }

    def list_metrics(self) -> List[str]:
        """List all metric names."""
        with self._lock:
            return list(self._metrics.keys())

    def register_aggregator(self, name: str, func: Callable[[List[MetricPoint]], float]) -> None:
        """Register a custom aggregator for a metric."""
        self._aggregators[name] = func

    def clear(self, name: Optional[str] = None) -> None:
        """Clear metrics."""
        with self._lock:
            if name:
                self._metrics.pop(name, None)
            else:
                self._metrics.clear()


class HealthMonitor:
    """Monitors component health."""

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._checks: Dict[str, HealthCheck] = {}
        self._results: Dict[str, HealthResult] = {}
        self._components: Dict[str, ComponentInfo] = {}
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        # Track previous statuses for change detection
        self._previous_statuses: Dict[str, HealthStatus] = {}

    def register_component(self, component: ComponentInfo) -> None:
        """Register a component for monitoring."""
        with self._lock:
            self._components[component.name] = component
            component.status = HealthStatus.UNKNOWN
        logger.info(f"Registered component: {component.name} ({component.component_type.value})")

    def unregister_component(self, name: str) -> bool:
        """Unregister a component."""
        with self._lock:
            if name in self._components:
                del self._components[name]
                # Also remove associated health checks
                checks_to_remove = [k for k, v in self._checks.items() if v.component == name]
                for k in checks_to_remove:
                    del self._checks[k]
                logger.info(f"Unregistered component: {name}")
                return True
        return False

    def add_health_check(self, check: HealthCheck) -> None:
        """Add a health check."""
        with self._lock:
            self._checks[check.name] = check
        logger.debug(f"Added health check: {check.name} for {check.component}")

    def remove_health_check(self, name: str) -> bool:
        """Remove a health check."""
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                return True
        return False

    def run_check(self, check_name: str, force: bool = False) -> Optional[HealthResult]:
        """Run a single health check."""
        with self._lock:
            check = self._checks.get(check_name)
            if not check:
                return None

            # Respect check interval unless forced
            now = time.time()
            if not force and check._last_run_time + check.interval_seconds > now:
                # Return cached result if available
                return self._results.get(check_name)

            check._last_run_time = now

        start = time.time()
        try:
            result = check.check_func()
            duration = (time.time() - start) * 1000

            # Handle both bool and HealthResult return types
            if isinstance(result, HealthResult):
                health_result = result
                health_result.name = check.name
                health_result.component = check.component
                health_result.duration_ms = duration
            else:
                status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                if check.critical and not result:
                    status = HealthStatus.UNHEALTHY

                health_result = HealthResult(
                    name=check.name,
                    component=check.component,
                    status=status,
                    message="OK" if result else "Check failed",
                    duration_ms=duration,
                )
        except Exception as e:
            duration = (time.time() - start) * 1000
            health_result = HealthResult(
                name=check.name,
                component=check.component,
                status=HealthStatus.UNHEALTHY,
                message=f"Check error: {e}",
                duration_ms=duration,
                metadata={"error": str(e), "type": type(e).__name__},
            )

        with self._lock:
            # Check if status changed
            prev_status = self._previous_statuses.get(check_name)
            status_changed = prev_status != health_result.status
            self._previous_statuses[check_name] = health_result.status

            self._results[check.name] = health_result

            # Update component status
            component = self._components.get(check.component)
            if component:
                # Determine overall component status from all its checks
                component_checks = [r for r in self._results.values() if r.component == check.component]
                if component_checks:
                    status_order = [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN, 
HealthStatus.UNHEALTHY]
                    worst = min(
                        (c.status for c in component_checks),
                        key=lambda s: status_order.index(s)
                    )
                    component.status = worst
                    component.last_heartbeat = datetime.now(timezone.utc).isoformat()

        # Emit event only on status change or forced
        if status_changed or force:
            self._event_bus.emit(
                "health.check.completed",
                data={
                    "check_name": check_name,
                    "component": check.component,
                    "status": health_result.status.value,
                    "duration_ms": duration,
                    "status_changed": status_changed,
                    "message": health_result.message,
                },
                source="HealthMonitor",
            )

            # Log only on status change
            if status_changed:
                logger.info(f"Health check {check_name} status changed: {health_result.status.value} - {health_result.message}")
            elif force:
                logger.debug(f"Health check {check_name}: {health_result.status.value} - {health_result.message}")

        return health_result

    def run_all_checks(self, force: bool = False) -> List[HealthResult]:
        """Run all health checks."""
        with self._lock:
            checks = list(self._checks.keys())

        results = []
        for check_name in checks:
            result = self.run_check(check_name, force=force)
            if result:
                results.append(result)
        return results

    def get_check_result(self, name: str) -> Optional[HealthResult]:
        """Get latest check result."""
        with self._lock:
            return self._results.get(name)

    def get_component_health(self, name: str) -> Optional[Dict[str, Any]]:
        """Get health summary for a component."""
        with self._lock:
            component = self._components.get(name)
            if not component:
                return None

            checks = [r for r in self._results.values() if r.component == name]
            return {
                "component": component.name,
                "type": component.component_type.value,
                "status": component.status.value,
                "last_heartbeat": component.last_heartbeat,
                "checks": [
                    {
                        "name": c.name,
                        "status": c.status.value,
                        "message": c.message,
                        "duration_ms": c.duration_ms,
                        "timestamp": c.timestamp,
                    }
                    for c in checks
                ],
            }

    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall system health."""
        with self._lock:
            components = list(self._components.values())
            checks = list(self._results.values())

            if not components:
                return {"status": HealthStatus.UNKNOWN.value, "components": 0}

            # Determine overall status
            statuses = [c.status for c in components]
            if HealthStatus.UNHEALTHY in statuses:
                overall = HealthStatus.UNHEALTHY
            elif HealthStatus.DEGRADED in statuses:
                overall = HealthStatus.DEGRADED
            elif HealthStatus.UNKNOWN in statuses:
                overall = HealthStatus.UNKNOWN
            else:
                overall = HealthStatus.HEALTHY

            return {
                "status": overall.value,
                "components": len(components),
                "healthy": sum(1 for s in statuses if s == HealthStatus.HEALTHY),
                "degraded": sum(1 for s in statuses if s == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for s in statuses if s == HealthStatus.UNHEALTHY),
                "unknown": sum(1 for s in statuses if s == HealthStatus.UNKNOWN),
                "total_checks": len(checks),
                "passing_checks": sum(1 for c in checks if c.status == HealthStatus.HEALTHY),
                "failing_checks": sum(1 for c in checks if c.status == HealthStatus.UNHEALTHY),
            }

    def start(self, interval_seconds: float = 30.0) -> None:
        """Start continuous health monitoring."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            name="HealthMonitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info(f"HealthMonitor started (interval={interval_seconds}s)")

    def stop(self) -> None:
        """Stop health monitoring."""
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        logger.info("HealthMonitor stopped")

    def _monitor_loop(self, interval_seconds: float) -> None:
        """Background monitoring loop."""
        # Sleep in smaller increments to allow quick shutdown
        sleep_chunk = min(5.0, interval_seconds / 5.0) if interval_seconds > 5.0 else 1.0
        while self._running:
            try:
                self.run_all_checks()
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
            # Sleep in chunks, checking _running frequently
            elapsed = 0.0
            while self._running and elapsed < interval_seconds:
                time.sleep(sleep_chunk)
                elapsed += sleep_chunk


class SystemMetricsCollector:
    """Collects system-level metrics."""

    def __init__(self, metrics_collector: MetricsCollector, interval_seconds: float = 5.0):
        self._metrics = metrics_collector
        self._interval = interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_disk_io = None
        self._last_net_io = None
        self._last_time = 0.0

    def start(self) -> None:
        """Start system metrics collection."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._collect_loop,
            name="SystemMetricsCollector",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"SystemMetricsCollector started (interval={self._interval}s)")

    def stop(self) -> None:
        """Stop system metrics collection."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("SystemMetricsCollector stopped")

    def collect_once(self) -> Dict[str, Any]:
        """Collect metrics once."""
        return self._collect_metrics()

    def _collect_loop(self) -> None:
        """Background collection loop."""
        while self._running:
            try:
                self._collect_metrics()
            except Exception as e:
                logger.error(f"Error collecting system metrics: {e}")
            time.sleep(self._interval)

    def _collect_metrics(self) -> Dict[str, Any]:
        """Collect current system metrics."""
        now = time.time()

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = cpu_freq.current if cpu_freq else 0

        # Memory
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024 ** 3)
        memory_used_gb = memory.used / (1024 ** 3)
        memory_free_gb = memory.free / (1024 ** 3)
        memory_percent = memory.percent

        # Disk
        disk = psutil.disk_usage('/')
        disk_total_gb = disk.total / (1024 ** 3)
        disk_used_gb = disk.used / (1024 ** 3)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_percent = (disk_used_gb / disk_total_gb) * 100

        # Disk I/O
        disk_io = psutil.disk_io_counters()
        disk_read_mb = 0
        disk_write_mb = 0
        if disk_io and self._last_disk_io and self._last_time:
            dt = now - self._last_time
            disk_read_mb = (disk_io.read_bytes - self._last_disk_io.read_bytes) / (1024 ** 2) / dt
            disk_write_mb = (disk_io.write_bytes - self._last_disk_io.write_bytes) / (1024 ** 2) / dt
        self._last_disk_io = disk_io

        # Network
        net_io = psutil.net_io_counters()
        net_sent_mb = 0
        net_recv_mb = 0
        if net_io and self._last_net_io and self._last_time:
            dt = now - self._last_time
            net_sent_mb = (net_io.bytes_sent - self._last_net_io.bytes_sent) / (1024 ** 2) / dt
            net_recv_mb = (net_io.bytes_recv - self._last_net_io.bytes_recv) / (1024 ** 2) / dt
        self._last_net_io = net_io

        self._last_time = now

        # Process
        process_count = len(psutil.pids())
        current_process = psutil.Process()
        thread_count = current_process.num_threads()
        process_memory_mb = current_process.memory_info().rss / (1024 ** 2)
        process_cpu_percent = current_process.cpu_percent()

        # Temperature (if available)
        temperature = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                cpu_temps = temps.get('coretemp', temps.get('cpu_thermal', []))
                if cpu_temps:
                    temperature = max(t.current for t in cpu_temps if t.current is not None)
        except (AttributeError, KeyError):
            pass

        # Load average (Unix)
        load_avg = None
        try:
            if hasattr(psutil, 'getloadavg'):
                load_avg = psutil.getloadavg()
        except Exception:
            pass

        # Record metrics
        metrics = {
            "system.cpu.percent": cpu_percent,
            "system.cpu.count": cpu_count,
            "system.cpu.freq_mhz": cpu_freq_mhz,
            "system.memory.total_gb": memory_total_gb,
            "system.memory.used_gb": memory_used_gb,
            "system.memory.free_gb": memory_free_gb,
            "system.memory.percent": memory_percent,
            "system.disk.total_gb": disk_total_gb,
            "system.disk.used_gb": disk_used_gb,
            "system.disk.free_gb": disk_free_gb,
            "system.disk.percent": disk_percent,
            "system.disk.read_mb_s": disk_read_mb,
            "system.disk.write_mb_s": disk_write_mb,
            "system.network.sent_mb_s": net_sent_mb,
            "system.network.recv_mb_s": net_recv_mb,
            "system.process.count": process_count,
            "system.process.threads": thread_count,
            "system.process.memory_mb": process_memory_mb,
            "system.process.cpu_percent": process_cpu_percent,
        }

        if temperature is not None:
            metrics["system.temperature.celsius"] = temperature

        if load_avg:
            metrics["system.load.1min"] = load_avg[0]
            metrics["system.load.5min"] = load_avg[1]
            metrics["system.load.15min"] = load_avg[2]

        # Record to metrics collector
        for name, value in metrics.items():
            self._metrics.record_value(name, value, unit=self._get_unit(name))

        return metrics

    def _get_unit(self, name: str) -> str:
        """Get unit for metric name."""
        if "percent" in name:
            return "%"
        elif "gb" in name.lower():
            return "GB"
        elif "mb" in name.lower():
            return "MB"
        elif "mhz" in name.lower():
            return "MHz"
        elif "celsius" in name.lower():
            return "°C"
        elif "count" in name or "threads" in name:
            return "count"
        return ""


class AlertManager:
    """Manages alerts from monitoring."""

    def __init__(self, event_bus: EventBus, max_history: int = 1000):
        self._event_bus = event_bus
        self._max_history = max_history
        self._active_alerts: Dict[str, Dict[str, Any]] = {}
        self._history: deque = deque(maxlen=max_history)
        self._lock = threading.RLock()
        self._rules: List[Dict[str, Any]] = []

    def add_rule(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        severity: str = "warning",
        message: str = "",
        cooldown_seconds: float = 300.0,
    ) -> None:
        """Add an alert rule."""
        rule = {
            "name": name,
            "condition": condition,
            "severity": severity,
            "message": message,
            "cooldown_seconds": cooldown_seconds,
            "last_triggered": 0.0,
        }
        self._rules.append(rule)

    def check_metrics(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check metrics against alert rules."""
        triggered = []
        now = time.time()

        with self._lock:
            for rule in self._rules:
                if now - rule["last_triggered"] < rule["cooldown_seconds"]:
                    continue

                try:
                    if rule["condition"](metrics):
                        alert = {
                            "id": str(uuid4()),
                            "rule": rule["name"],
                            "severity": rule["severity"],
                            "message": rule["message"] or f"Alert: {rule['name']}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "metrics": {k: v for k, v in metrics.items() if "percent" in k or "cpu" in k or "memory" in k},
                        }

                        self._active_alerts[alert["id"]] = alert
                        self._history.append(alert)
                        rule["last_triggered"] = now

                        # Emit event
                        self._event_bus.emit(
                            "alert.triggered",
                            data=alert,
                            source="AlertManager",
                            priority=EventPriority.HIGH if rule["severity"] in ("high", "critical") else EventPriority.NORMAL,
                        )

                        triggered.append(alert)
                except Exception as e:
                    logger.error(f"Error evaluating alert rule {rule['name']}: {e}")

        return triggered

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        with self._lock:
            if alert_id in self._active_alerts:
                self._active_alerts[alert_id]["acknowledged"] = True
                self._active_alerts[alert_id]["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    def resolve(self, alert_id: str) -> bool:
        """Resolve an alert."""
        with self._lock:
            if alert_id in self._active_alerts:
                alert = self._active_alerts.pop(alert_id)
                alert["resolved"] = True
                alert["resolved_at"] = datetime.now(timezone.utc).isoformat()
                self._history.append(alert)
                return True
        return False

    def get_active(self) -> List[Dict[str, Any]]:
        """Get active alerts."""
        with self._lock:
            return list(self._active_alerts.values())

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get alert history."""
        with self._lock:
            history = list(self._history)
            if limit:
                history = history[-limit:]
            return history

    def clear(self) -> None:
        """Clear all alerts."""
        with self._lock:
            self._active_alerts.clear()
            self._history.clear()


class ObservabilityHub:
    """
    Central observability hub for Freya.

    Integrates:
    - Health monitoring
    - Metrics collection
    - Alert management
    - Component registration
    - System metrics
    - Event emission for external consumers
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        metrics_interval: float = 5.0,
        health_interval: float = 30.0,
    ):
        """
        Initialize the observability hub.

        Args:
            event_bus: Event bus for emitting observability events
            metrics_interval: System metrics collection interval (seconds)
            health_interval: Health check interval (seconds)
        """
        self._event_bus = event_bus or get_event_bus()

        # Core components
        self._metrics = MetricsCollector()
        self._health = HealthMonitor(self._event_bus)
        self._alerts = AlertManager(self._event_bus)
        self._system_metrics = SystemMetricsCollector(self._metrics, metrics_interval)

        # Default alert rules
        self._setup_default_alerts()

        # State
        self._started = False

    def _setup_default_alerts(self) -> None:
        """Set up default alert rules."""
        # High CPU
        self._alerts.add_rule(
            "high_cpu",
            lambda m: m.get("system.cpu.percent", 0) > 90,
            severity="critical",
            message="CPU usage exceeds 90%",
        )

        # High memory
        self._alerts.add_rule(
            "high_memory",
            lambda m: m.get("system.memory.percent", 0) > 90,
            severity="critical",
            message="Memory usage exceeds 90%",
        )

        # High disk
        self._alerts.add_rule(
            "high_disk",
            lambda m: m.get("system.disk.percent", 0) > 95,
            severity="critical",
            message="Disk usage exceeds 95%",
        )

        # High temperature
        self._alerts.add_rule(
            "high_temperature",
            lambda m: m.get("system.temperature.celsius", 0) > 85,
            severity="critical",
            message="System temperature exceeds 85°C",
        )

    def start(self) -> None:
        """Start all observability components."""
        if self._started:
            return

        self._system_metrics.start()
        self._health.start()
        self._started = True

        # Register self as a component
        self.register_component(ComponentInfo(
            name="ObservabilityHub",
            component_type=ComponentType.SERVICE,
            description="Central observability hub",
            version="1.0.0",
        ))

        logger.info("ObservabilityHub started")

    def stop(self) -> None:
        """Stop all observability components."""
        self._system_metrics.stop()
        self._health.stop()
        self._started = False
        logger.info("ObservabilityHub stopped")

    # Component registration

    def register_component(self, component: ComponentInfo) -> None:
        """Register a component for monitoring."""
        self._health.register_component(component)

        self._event_bus.emit(
            "component.registered",
            data={
                "name": component.name,
                "type": component.component_type.value,
                "version": component.version,
            },
            source="ObservabilityHub",
        )

    def unregister_component(self, name: str) -> bool:
        """Unregister a component."""
        return self._health.unregister_component(name)

    def get_component(self, name: str) -> Optional[ComponentInfo]:
        """Get component info."""
        with self._health._lock:
            return self._health._components.get(name)

    def list_components(self) -> List[Dict[str, Any]]:
        """List all registered components."""
        with self._health._lock:
            return [
                {
                    "name": c.name,
                    "type": c.component_type.value,
                    "status": c.status.value,
                    "version": c.version,
                    "last_heartbeat": c.last_heartbeat,
                }
                for c in self._health._components.values()
            ]

    # Health monitoring

    def add_health_check(self, check: HealthCheck) -> None:
        """Add a health check."""
        self._health.add_health_check(check)

    def remove_health_check(self, name: str) -> bool:
        """Remove a health check."""
        return self._health.remove_health_check(name)

    def run_health_checks(self, force: bool = False) -> List[HealthResult]:
        """Run all health checks through the shared monitor."""
        return self._health.run_all_checks(force=force)

    def get_health(self, component: Optional[str] = None) -> Dict[str, Any]:
        """Get health status."""
        if component:
            result = self._health.get_component_health(component)
            return result or {"component": component, "status": "not_found"}
        return self._health.get_overall_health()

    def get_readiness_status(self, initialized: bool) -> Dict[str, Any]:
        """Return a read-only readiness snapshot from registered health state.

        Runtime components opt into this view by registering ``metadata`` with a
        ``readiness`` mapping.  This method never runs a check or changes state;
        it reports the latest observations collected by ``HealthMonitor``.
        """
        with self._health._lock:
            components = list(self._health._components.values())
            results = list(self._health._results.values())

        dependencies = []
        required_unavailable = []
        degraded = []
        for component in components:
            readiness = component.metadata.get("readiness", {})
            if not readiness:
                continue

            checks = [result for result in results if result.component == component.name]
            dependency = {
                "name": component.name,
                "category": readiness.get("category", component.component_type.value),
                "required": bool(readiness.get("required", False)),
                "status": component.status.value,
                "checks": [
                    {
                        "name": result.name,
                        "status": result.status.value,
                        "message": result.message,
                        "timestamp": result.timestamp,
                        "metadata": dict(result.metadata),
                    }
                    for result in checks
                ],
            }
            dependencies.append(dependency)

            if dependency["required"] and component.status in {
                HealthStatus.UNKNOWN,
                HealthStatus.UNHEALTHY,
            }:
                required_unavailable.append(component.name)
            elif component.status == HealthStatus.DEGRADED:
                degraded.append(component.name)

        if not initialized:
            status = "not_ready"
            ready = False
            reasons = ["initialization_incomplete"]
        elif required_unavailable:
            status = "not_ready"
            ready = False
            reasons = [f"required_dependency_unavailable:{name}" for name in required_unavailable]
        elif degraded:
            status = "degraded"
            ready = True
            reasons = [f"dependency_degraded:{name}" for name in degraded]
        else:
            status = "ready"
            ready = True
            reasons = []

        return {
            "status": status,
            "ready": ready,
            "initialization": {"completed": initialized},
            "dependencies": dependencies,
            "reasons": reasons,
        }

    def get_health_surface(self, initialized: bool) -> Dict[str, Any]:
        """Return the production liveness/readiness surface without side effects."""
        return {
            "liveness": {
                "status": "alive",
                "alive": True,
            },
            "readiness": self.get_readiness_status(initialized=initialized),
        }

    # Metrics

    def record_metric(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        unit: str = "",
    ) -> None:
        """Record a custom metric."""
        self._metrics.record_value(name, value, labels, unit)

    def get_metric(self, name: str) -> Optional[MetricPoint]:
        """Get latest metric value."""
        return self._metrics.get_latest(name)

    def get_metric_history(
        self,
        name: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[MetricPoint]:
        """Get metric history."""
        return self._metrics.get_history(name, since, limit)

    def get_metric_summary(self, name: str, window_seconds: float = 300) -> Dict[str, Any]:
        """Get metric summary."""
        return self._metrics.get_summary(name, window_seconds)

    def list_metrics(self) -> List[str]:
        """List all metric names."""
        return self._metrics.list_metrics()

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics snapshot."""
        return self._system_metrics.collect_once()

    # Alerts

    def add_alert_rule(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        severity: str = "warning",
        message: str = "",
        cooldown_seconds: float = 300.0,
    ) -> None:
        """Add an alert rule."""
        self._alerts.add_rule(name, condition, severity, message, cooldown_seconds)

    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check metrics against alert rules."""
        metrics = self.get_system_metrics()
        return self._alerts.check_metrics(metrics)

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active alerts."""
        return self._alerts.get_active()

    def get_alert_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get alert history."""
        return self._alerts.get_history(limit)

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        return self._alerts.acknowledge(alert_id)

    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert."""
        return self._alerts.resolve(alert_id)

    # Status and reporting

    def get_status(self) -> Dict[str, Any]:
        """Get overall observability status."""
        return {
            "started": self._started,
            "health": self.get_health(),
            "active_alerts": len(self.get_active_alerts()),
            "registered_components": len(self.list_components()),
            "metrics_collected": len(self.list_metrics()),
        }

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive observability report."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": self.get_status(),
            "health": self.get_health(),
            "system_metrics": self.get_system_metrics(),
            "active_alerts": self.get_active_alerts(),
            "components": self.list_components(),
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# Global instance
_observability_hub: Optional[ObservabilityHub] = None


def get_observability_hub() -> ObservabilityHub:
    """Get the global observability hub instance."""
    global _observability_hub
    if _observability_hub is None:
        _observability_hub = ObservabilityHub()
    return _observability_hub


def set_observability_hub(hub: ObservabilityHub) -> None:
    """Set the global observability hub instance."""
    global _observability_hub
    _observability_hub = hub