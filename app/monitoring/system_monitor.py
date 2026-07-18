"""System Monitor for tracking system resources and health.

This module provides real-time monitoring of system resources including
CPU, memory, disk usage, and overall system health.
"""

import os
import platform
import psutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.monitoring.alert_manager import SystemAlert


class SystemHealthStatus(Enum):
    """Overall system health status."""
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ResourceMetrics:
    """Metrics for system resources."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # CPU metrics
    cpu_percent: float = 0.0
    cpu_count: int = 0
    cpu_freq_mhz: float = 0.0

    # Memory metrics
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_free_gb: float = 0.0
    memory_percent: float = 0.0

    # Disk metrics
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_percent: float = 0.0
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0

    # Network metrics
    net_sent_mb: float = 0.0
    net_recv_mb: float = 0.0

    # System info
    system_name: str = ""
    system_version: str = ""
    systemarch: str = ""

    # Process metrics
    process_count: int = 0
    thread_count: int = 0

    # Temperature (if available)
    temperature_celsius: Optional[float] = None

    # Load average (Unix-like systems)
    load_avg_1min: Optional[float] = None
    load_avg_5min: Optional[float] = None
    load_avg_15min: Optional[float] = None

    @classmethod
    def collect(cls) -> "ResourceMetrics":
        """Collect current system metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq()
            cpu_freq_mhz = cpu_freq.max if cpu_freq else 0.0

            # Memory metrics
            memory = psutil.virtual_memory()
            memory_total_gb = round(memory.total / (1024 ** 3), 2)
            memory_used_gb = round(memory.used / (1024 ** 3), 2)
            memory_free_gb = round(memory.free / (1024 ** 3), 2)
            memory_percent = memory.percent

            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_total_gb = round(disk.total / (1024 ** 3), 2)
            disk_used_gb = round(disk.used / (1024 ** 3), 2)
            disk_free_gb = round(disk.free / (1024 ** 3), 2)
            disk_percent = disk.percent

            # Disk I/O
            disk_io = psutil.disk_io_counters()
            disk_read_mb = round(disk_io.read_bytes / (1024 ** 2), 2) if disk_io else 0.0
            disk_write_mb = round(disk_io.write_bytes / (1024 ** 2), 2) if disk_io else 0.0

            # Network metrics
            net_io = psutil.net_io_counters()
            net_sent_mb = round(net_io.bytes_sent / (1024 ** 2), 2) if net_io else 0.0
            net_recv_mb = round(net_io.bytes_recv / (1024 ** 2), 2) if net_io else 0.0

            # System info
            system_name = platform.system()
            system_version = platform.version()
            system_arch = platform.machine()

            # Process metrics
            process_count = len(psutil.pids())
            thread_count = psutil.Process().num_threads() if hasattr(psutil, 'Process') else 0

            # Temperature (if available)
            temperature = None
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    # Get CPU temperature if available
                    cpu_temps = temps.get('coretemp', temps.get('cpu_thermal', []))
                    if cpu_temps:
                        temperature = max(t.current for t in cpu_temps if t.current is not None)
            except (AttributeError, KeyError):
                pass

            # Load average
            load_avg_1 = load_avg_5 = load_avg_15 = None
            try:
                if hasattr(psutil, 'getloadavg'):
                    load_avg = psutil.getloadavg()
                    load_avg_1 = load_avg[0]
                    load_avg_5 = load_avg[1]
                    load_avg_15 = load_avg[2]
            except Exception:
                pass

            return cls(
                cpu_percent=cpu_percent,
                cpu_count=cpu_count,
                cpu_freq_mhz=cpu_freq_mhz,
                memory_total_gb=memory_total_gb,
                memory_used_gb=memory_used_gb,
                memory_free_gb=memory_free_gb,
                memory_percent=memory_percent,
                disk_total_gb=disk_total_gb,
                disk_used_gb=disk_used_gb,
                disk_free_gb=disk_free_gb,
                disk_percent=disk_percent,
                disk_read_mb=disk_read_mb,
                disk_write_mb=disk_write_mb,
                net_sent_mb=net_sent_mb,
                net_recv_mb=net_recv_mb,
                system_name=system_name,
                system_version=system_version,
                systemarch=system_arch,
                process_count=process_count,
                thread_count=thread_count,
                temperature_celsius=temperature,
                load_avg_1min=load_avg_1,
                load_avg_5min=load_avg_5,
                load_avg_15min=load_avg_15,
            )
        except Exception as e:
            # Return default metrics if collection fails
            return cls()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "cpu": {
                "percent": self.cpu_percent,
                "count": self.cpu_count,
                "freq_mhz": self.cpu_freq_mhz,
            },
            "memory": {
                "total_gb": self.memory_total_gb,
                "used_gb": self.memory_used_gb,
                "free_gb": self.memory_free_gb,
                "percent": self.memory_percent,
            },
            "disk": {
                "total_gb": self.disk_total_gb,
                "used_gb": self.disk_used_gb,
                "free_gb": self.disk_free_gb,
                "percent": self.disk_percent,
                "read_mb": self.disk_read_mb,
                "write_mb": self.disk_write_mb,
            },
            "network": {
                "sent_mb": self.net_sent_mb,
                "recv_mb": self.net_recv_mb,
            },
            "system": {
                "name": self.system_name,
                "version": self.system_version,
                "arch": self.systemarch,
            },
            "processes": {
                "count": self.process_count,
                "threads": self.thread_count,
            },
            "temperature": self.temperature_celsius,
            "load_avg": {
                "1min": self.load_avg_1min,
                "5min": self.load_avg_5min,
                "15min": self.load_avg_15min,
            },
        }

    def calculate_health_score(self) -> float:
        """Calculate a health score from 0-100 based on resource usage."""
        score = 100.0

        # CPU: penalize if > 80%
        if self.cpu_percent > 80:
            score -= (self.cpu_percent - 80) * 0.5

        # Memory: penalize if > 80%
        if self.memory_percent > 80:
            score -= (self.memory_percent - 80) * 0.5

        # Disk: penalize if > 85%
        if self.disk_percent > 85:
            score -= (self.disk_percent - 85) * 0.5

        # Temperature: penalize if > 80C
        if self.temperature_celsius and self.temperature_celsius > 80:
            score -= (self.temperature_celsius - 80) * 0.5

        return max(0, min(100, score))

    def get_health_status(self) -> SystemHealthStatus:
        """Get the overall health status based on metrics."""
        score = self.calculate_health_score()
        if score >= 80:
            return SystemHealthStatus.EXCELLENT
        elif score >= 60:
            return SystemHealthStatus.GOOD
        elif score >= 40:
            return SystemHealthStatus.WARNING
        elif score >= 20:
            return SystemHealthStatus.WARNING
        else:
            return SystemHealthStatus.CRITICAL


@dataclass
class AlertThreshold:
    """Threshold configuration for alerts."""
    cpu_percent: float = 90.0
    memory_percent: float = 90.0
    disk_percent: float = 95.0
    temperature_celsius: Optional[float] = 85.0

    # Process monitoring
    max_process_count: Optional[int] = None
    max_thread_count: Optional[int] = None

    # Load average thresholds (Unix-like)
    load_avg_1min: Optional[float] = None
    load_avg_5min: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertThreshold":
        """Create from dictionary."""
        return cls(
            cpu_percent=data.get("cpu_percent", 90.0),
            memory_percent=data.get("memory_percent", 90.0),
            disk_percent=data.get("disk_percent", 95.0),
            temperature_celsius=data.get("temperature_celsius", 85.0),
            max_process_count=data.get("max_process_count"),
            max_thread_count=data.get("max_thread_count"),
            load_avg_1min=data.get("load_avg_1min"),
            load_avg_5min=data.get("load_avg_5min"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "temperature_celsius": self.temperature_celsius,
            "max_process_count": self.max_process_count,
            "max_thread_count": self.max_thread_count,
            "load_avg_1min": self.load_avg_1min,
            "load_avg_5min": self.load_avg_5min,
        }


@dataclass
class MonitorConfig:
    """Configuration for the system monitor."""
    interval_seconds: float = 5.0
    enabled: bool = True
    thresholds: AlertThreshold = field(default_factory=AlertThreshold)
    history_size: int = 100  # Number of historical samples to keep
    workspace: str = "."

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorConfig":
        """Create from dictionary."""
        thresholds = AlertThreshold.from_dict(data.get("thresholds", {}))
        return cls(
            interval_seconds=data.get("interval_seconds", 5.0),
            enabled=data.get("enabled", True),
            thresholds=thresholds,
            history_size=data.get("history_size", 100),
            workspace=data.get("workspace", "."),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "thresholds": self.thresholds.to_dict(),
            "history_size": self.history_size,
            "workspace": self.workspace,
        }


class MonitoringCallback:
    """Base class for monitoring callbacks."""

    def on_metrics_collected(self, metrics: ResourceMetrics) -> None:
        """Called when metrics are collected."""
        raise NotImplementedError

    def on_health_change(self, old_status: SystemHealthStatus, new_status: SystemHealthStatus) -> None:
        """Called when health status changes."""
        raise NotImplementedError

    def on_alert(self, alert: "SystemAlert") -> None:
        """Called when an alert is triggered."""
        raise NotImplementedError


class LoggingMonitoringCallback(MonitoringCallback):
    """Logs monitoring events to console."""

    def __init__(self, verbosity: int = 1):
        self.verbosity = verbosity

    def on_metrics_collected(self, metrics: ResourceMetrics) -> None:
        """Log metrics collection."""
        if self.verbosity >= 2:
            print(f"[MONITOR] Metrics collected: CPU={metrics.cpu_percent}%, Memory={metrics.memory_percent}%, Disk={metrics.disk_percent}%")

    def on_health_change(self, old_status: SystemHealthStatus, new_status: SystemHealthStatus) -> None:
        """Log health status change."""
        print(f"[MONITOR] Health status changed: {old_status.value} -> {new_status.value}")

    def on_alert(self, alert: "SystemAlert") -> None:
        """Log alert."""
        print(f"[MONITOR] ALERT: {alert.severity.value}: {alert.title}")


class SystemMonitor:
    """Main system monitor class.

    This class provides continuous monitoring of system resources and
    triggers alerts when thresholds are breached.
    """

    def __init__(self, config: Optional[MonitorConfig] = None):
        """Initialize the system monitor.

        Args:
            config: Configuration for the monitor.
        """
        self.config = config or MonitorConfig()
        self.workspace = Path(self.config.workspace).resolve()
        self._running = False
        self._metrics_history: List[ResourceMetrics] = []
        self._current_metrics: Optional[ResourceMetrics] = None
        self._current_status = SystemHealthStatus.UNKNOWN
        self._callbacks: List[MonitoringCallback] = []
        self._alert_callbacks: List[Callable[["SystemAlert"], None]] = []

    def add_callback(self, callback: MonitoringCallback) -> None:
        """Add a monitoring callback."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: MonitoringCallback) -> None:
        """Remove a monitoring callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def collect_metrics(self) -> ResourceMetrics:
        """Collect current system metrics."""
        metrics = ResourceMetrics.collect()
        self._current_metrics = metrics

        # Add to history
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > self.config.history_size:
            self._metrics_history = self._metrics_history[-self.config.history_size:]

        # Check health status
        old_status = self._current_status
        self._current_status = metrics.get_health_status()

        # Notify callbacks
        for callback in self._callbacks:
            callback.on_metrics_collected(metrics)

        if old_status != self._current_status:
            for callback in self._callbacks:
                callback.on_health_change(old_status, self._current_status)

        return metrics

    def get_current_metrics(self) -> Optional[ResourceMetrics]:
        """Get the current metrics."""
        if self._current_metrics is None:
            self.collect_metrics()
        return self._current_metrics

    def get_health_status(self) -> SystemHealthStatus:
        """Get the current health status."""
        if self._current_metrics is None:
            self.collect_metrics()
        return self._current_status

    def get_metrics_history(self, count: Optional[int] = None) -> List[ResourceMetrics]:
        """Get historical metrics."""
        if count is None:
            return list(self._metrics_history)
        return list(self._metrics_history[-count:])

    def check_thresholds(self) -> List["SystemAlert"]:
        """Check if any thresholds are breached and return alerts."""
        from app.monitoring.alert_manager import SystemAlert, AlertSeverity

        alerts = []
        metrics = self.get_current_metrics()
        thresholds = self.config.thresholds

        if metrics is None:
            return alerts

        # CPU threshold
        if metrics.cpu_percent > thresholds.cpu_percent:
            alerts.append(SystemAlert(
                id=f"cpu_{int(time.time())}",
                title=f"High CPU Usage: {metrics.cpu_percent:.1f}%",
                description=f"CPU usage ({metrics.cpu_percent:.1f}%) exceeds threshold ({thresholds.cpu_percent}%)",
                severity=AlertSeverity.HIGH,
                metric_name="cpu_percent",
                current_value=metrics.cpu_percent,
                threshold=thresholds.cpu_percent,
            ))

        # Memory threshold
        if metrics.memory_percent > thresholds.memory_percent:
            alerts.append(SystemAlert(
                id=f"memory_{int(time.time())}",
                title=f"High Memory Usage: {metrics.memory_percent:.1f}%",
                description=f"Memory usage ({metrics.memory_percent:.1f}%) exceeds threshold ({thresholds.memory_percent}%)",
                severity=AlertSeverity.HIGH,
                metric_name="memory_percent",
                current_value=metrics.memory_percent,
                threshold=thresholds.memory_percent,
            ))

        # Disk threshold
        if metrics.disk_percent > thresholds.disk_percent:
            alerts.append(SystemAlert(
                id=f"disk_{int(time.time())}",
                title=f"High Disk Usage: {metrics.disk_percent:.1f}%",
                description=f"Disk usage ({metrics.disk_percent:.1f}%) exceeds threshold ({thresholds.disk_percent}%)",
                severity=AlertSeverity.HIGH,
                metric_name="disk_percent",
                current_value=metrics.disk_percent,
                threshold=thresholds.disk_percent,
            ))

        # Temperature threshold
        if metrics.temperature_celsius and thresholds.temperature_celsius:
            if metrics.temperature_celsius > thresholds.temperature_celsius:
                alerts.append(SystemAlert(
                    id=f"temp_{int(time.time())}",
                    title=f"High Temperature: {metrics.temperature_celsius:.1f}C",
                    description=f"Temperature ({metrics.temperature_celsius:.1f}C) exceeds threshold ({thresholds.temperature_celsius}C)",
                    severity=AlertSeverity.CRITICAL,
                    metric_name="temperature",
                    current_value=metrics.temperature_celsius,
                    threshold=thresholds.temperature_celsius,
                ))

        # Process count threshold
        if thresholds.max_process_count and metrics.process_count > thresholds.max_process_count:
            alerts.append(SystemAlert(
                id=f"process_count_{int(time.time())}",
                title=f"High Process Count: {metrics.process_count}",
                description=f"Process count ({metrics.process_count}) exceeds threshold ({thresholds.max_process_count})",
                severity=AlertSeverity.MEDIUM,
                metric_name="process_count",
                current_value=float(metrics.process_count),
                threshold=float(thresholds.max_process_count),
            ))

        # Load average thresholds
        if metrics.load_avg_1min and thresholds.load_avg_1min:
            if metrics.load_avg_1min > thresholds.load_avg_1min:
                alerts.append(SystemAlert(
                    id=f"load_1min_{int(time.time())}",
                    title=f"High 1-minute Load Average: {metrics.load_avg_1min:.2f}",
                    description=f"1-minute load average ({metrics.load_avg_1min:.2f}) exceeds threshold ({thresholds.load_avg_1min})",
                    severity=AlertSeverity.MEDIUM,
                    metric_name="load_avg_1min",
                    current_value=metrics.load_avg_1min,
                    threshold=thresholds.load_avg_1min,
                ))

        return alerts

    def start(self) -> None:
        """Start continuous monitoring."""
        if self._running:
            return

        self._running = True
        import threading
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop continuous monitoring."""
        self._running = False
        if hasattr(self, '_thread'):
            self._thread.join(timeout=self.config.interval_seconds + 1)

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self.collect_metrics()
                alerts = self.check_thresholds()
                for alert in alerts:
                    for callback in self._callbacks:
                        callback.on_alert(alert)
            except Exception as e:
                print(f"[MONITOR] Error in monitoring loop: {e}")

            # Sleep for the interval
            for _ in range(int(self.config.interval_seconds * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current system state."""
        metrics = self.get_current_metrics()
        if metrics is None:
            return {"status": "unknown"}

        return {
            "status": self._current_status.value,
            "health_score": metrics.calculate_health_score(),
            "cpu_percent": metrics.cpu_percent,
            "memory_percent": metrics.memory_percent,
            "disk_percent": metrics.disk_percent,
            "temperature": metrics.temperature_celsius,
            "process_count": metrics.process_count,
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
