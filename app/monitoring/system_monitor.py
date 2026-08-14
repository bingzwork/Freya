"""System Monitor for tracking system resources and health.

This module provides real-time monitoring of system resources including
CPU, memory, disk usage, GPU, and overall system health.
"""

import os
import platform
import psutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.monitoring.alert_manager import SystemAlert
    from app.monitoring.network_monitor import NetworkMonitor

# Import ServiceStatus for runtime use in get_summary
from app.monitoring.network_monitor import ServiceStatus

# Import new GPU monitor for cross-vendor support
try:
    from app.monitoring.gpu_monitor import GPUMonitor, GPUMetrics as NewGPUMetrics
    HAS_GPU_MONITOR = True
except ImportError:
    HAS_GPU_MONITOR = False
    GPUMonitor = None
    NewGPUMetrics = None

# Optional GPU detection via pynvml (legacy)
try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False
    pynvml = None


class SystemHealthStatus(Enum):
    """Overall system health status."""
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class GPUMetrics:
    """Metrics for a single GPU device (compatible with new GPUMonitor)."""
    index: int = 0
    vendor: str = "unknown"
    name: str = ""
    driver_version: str = ""
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    memory_percent: float = 0.0
    gpu_utilization_percent: float = 0.0
    memory_utilization_percent: float = 0.0
    temperature_celsius: Optional[float] = None
    power_draw_watts: Optional[float] = None
    power_limit_watts: Optional[float] = None
    fan_speed_percent: Optional[float] = None
    clock_graphics_mhz: Optional[float] = None
    clock_memory_mhz: Optional[float] = None
    encoder_utilization_percent: Optional[float] = None
    decoder_utilization_percent: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "index": self.index,
            "vendor": self.vendor,
            "name": self.name,
            "driver_version": self.driver_version,
            "memory": {
                "total_mb": self.memory_total_mb,
                "used_mb": self.memory_used_mb,
                "free_mb": self.memory_free_mb,
                "percent": self.memory_percent,
            },
            "utilization": {
                "gpu_percent": self.gpu_utilization_percent,
                "memory_percent": self.memory_utilization_percent,
                "encoder_percent": self.encoder_utilization_percent,
                "decoder_percent": self.decoder_utilization_percent,
            },
            "temperature_celsius": self.temperature_celsius,
            "power": {
                "draw_watts": self.power_draw_watts,
                "limit_watts": self.power_limit_watts,
            },
            "fan_speed_percent": self.fan_speed_percent,
            "clocks": {
                "graphics_mhz": self.clock_graphics_mhz,
                "memory_mhz": self.clock_memory_mhz,
            },
        }


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

    # GPU metrics
    gpus: List[GPUMetrics] = field(default_factory=list)
    gpu_count: int = 0
    gpu_driver_version: str = ""
    gpu_by_vendor: Dict[str, int] = field(default_factory=dict)

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

    @classmethod
    def collect(cls) -> "ResourceMetrics":
        """Collect current system metrics including GPU metrics."""
        # First collect base metrics
        base_metrics = cls._collect_base_metrics()

        # Then collect GPU metrics
        gpus, gpu_driver_version, gpu_by_vendor = cls._collect_gpu_metrics()

        # Create final metrics object with GPU data
        return cls(
            cpu_percent=base_metrics.cpu_percent,
            cpu_count=base_metrics.cpu_count,
            cpu_freq_mhz=base_metrics.cpu_freq_mhz,
            memory_total_gb=base_metrics.memory_total_gb,
            memory_used_gb=base_metrics.memory_used_gb,
            memory_free_gb=base_metrics.memory_free_gb,
            memory_percent=base_metrics.memory_percent,
            disk_total_gb=base_metrics.disk_total_gb,
            disk_used_gb=base_metrics.disk_used_gb,
            disk_free_gb=base_metrics.disk_free_gb,
            disk_percent=base_metrics.disk_percent,
            disk_read_mb=base_metrics.disk_read_mb,
            disk_write_mb=base_metrics.disk_write_mb,
            net_sent_mb=base_metrics.net_sent_mb,
            net_recv_mb=base_metrics.net_recv_mb,
            system_name=base_metrics.system_name,
            system_version=base_metrics.system_version,
            systemarch=base_metrics.systemarch,
            process_count=base_metrics.process_count,
            thread_count=base_metrics.thread_count,
            temperature_celsius=base_metrics.temperature_celsius,
            load_avg_1min=base_metrics.load_avg_1min,
            load_avg_5min=base_metrics.load_avg_5min,
            load_avg_15min=base_metrics.load_avg_15min,
            gpus=gpus,
            gpu_count=len(gpus),
            gpu_driver_version=gpu_driver_version,
            gpu_by_vendor=gpu_by_vendor,
        )

    @classmethod
    def _collect_base_metrics(cls) -> "ResourceMetrics":
        """Collect base system metrics (CPU, memory, disk, network, etc.)."""
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

    @classmethod
    def _collect_gpu_metrics(cls) -> tuple[List[GPUMetrics], str]:
        """Collect GPU metrics using new GPUMonitor (cross-vendor) with fallback to pynvml."""
        gpus = []
        driver_version = ""
        gpu_by_vendor = {}

        # Try new GPUMonitor first (cross-vendor support)
        if HAS_GPU_MONITOR and GPUMonitor:
            try:
                gpu_monitor = GPUMonitor()
                gpu_info_list = gpu_monitor.get_gpu_info()
                metrics_list = gpu_monitor.collect_metrics()

                # Build GPU info lookup
                gpu_info_by_index = {g.index: g for g in gpu_info_list}

                for metric in metrics_list:
                    gpu_info = gpu_info_by_index.get(metric.index)
                    if gpu_info:
                        driver_version = gpu_info.driver_version or driver_version

                    gpu = GPUMetrics(
                        index=metric.index,
                        vendor=metric.vendor.value if hasattr(metric.vendor, 'value') else str(metric.vendor),
                        name=metric.name,
                        driver_version=driver_version,
                        memory_total_mb=metric.memory_total_mb,
                        memory_used_mb=metric.memory_used_mb,
                        memory_free_mb=metric.memory_free_mb,
                        memory_percent=metric.memory_utilization_percent,
                        gpu_utilization_percent=metric.gpu_utilization_percent,
                        memory_utilization_percent=metric.memory_utilization_percent,
                        temperature_celsius=metric.temperature_celsius,
                        power_draw_watts=metric.power_draw_watts,
                        power_limit_watts=metric.power_limit_watts,
                        fan_speed_percent=metric.fan_speed_percent,
                        clock_graphics_mhz=metric.clock_graphics_mhz,
                        clock_memory_mhz=metric.clock_memory_mhz,
                        encoder_utilization_percent=metric.encoder_utilization_percent,
                        decoder_utilization_percent=metric.decoder_utilization_percent,
                    )
                    gpus.append(gpu)

                # Count by vendor
                for g in gpu_info_list:
                    vendor = g.vendor.value if hasattr(g.vendor, 'value') else str(g.vendor)
                    gpu_by_vendor[vendor] = gpu_by_vendor.get(vendor, 0) + 1

                return gpus, driver_version, gpu_by_vendor
            except Exception:
                # Fall through to legacy method
                pass

        # Fallback to legacy pynvml
        if HAS_PYNVML:
            return cls._collect_gpu_metrics_legacy()

        return gpus, driver_version, gpu_by_vendor

    @classmethod
    def _collect_gpu_metrics_legacy(cls) -> tuple[List[GPUMetrics], str, Dict[str, int]]:
        """Legacy GPU metrics collection using pynvml (NVIDIA only)."""
        gpus = []
        driver_version = ""
        gpu_by_vendor = {}

        try:
            # Initialize NVML
            pynvml.nvmlInit()

            # Get driver version
            try:
                driver_version = pynvml.nvmlSystemGetDriverVersion().decode('utf-8')
            except Exception:
                driver_version = ""

            # Get GPU count
            gpu_count = pynvml.nvmlDeviceGetCount()

            for i in range(gpu_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                    # GPU name
                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode('utf-8')

                    # GPU driver version
                    if not driver_version:
                        try:
                            driver_version = pynvml.nvmlSystemGetDriverVersion()
                            if isinstance(driver_version, bytes):
                                driver_version = driver_version.decode('utf-8')
                        except Exception:
                            driver_version = ""

                    # Memory info
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    memory_total_mb = round(mem_info.total / (1024 ** 2), 2)
                    memory_used_mb = round(mem_info.used / (1024 ** 2), 2)
                    memory_free_mb = round(mem_info.free / (1024 ** 2), 2)
                    memory_percent = round((mem_info.used / mem_info.total) * 100, 2) if mem_info.total > 0 else 0.0

                    # Utilization
                    utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_utilization_percent = utilization.gpu
                    memory_utilization_percent = utilization.memory

                    # Temperature
                    temperature_celsius = None
                    try:
                        temperature_celsius = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    except Exception:
                        pass

                    # Power
                    power_draw_watts = None
                    power_limit_watts = None
                    try:
                        power_draw_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW to W
                        power_limit_watts = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
                    except Exception:
                        pass

                    # Encoder/Decoder utilization (optional)
                    encoder_utilization_percent = None
                    decoder_utilization_percent = None
                    try:
                        encoder_stats = pynvml.nvmlDeviceGetEncoderStats(handle)
                        if encoder_stats.sessionCount > 0:
                            encoder_utilization_percent = encoder_stats.averageLatency
                    except Exception:
                        pass
                    try:
                        decoder_stats = pynvml.nvmlDeviceGetDecoderStats(handle)
                        if decoder_stats.sessionCount > 0:
                            decoder_utilization_percent = decoder_stats.averageLatency
                    except Exception:
                        pass

                    gpu = GPUMetrics(
                        index=i,
                        vendor="nvidia",
                        name=name,
                        driver_version=driver_version,
                        memory_total_mb=memory_total_mb,
                        memory_used_mb=memory_used_mb,
                        memory_free_mb=memory_free_mb,
                        memory_percent=memory_percent,
                        gpu_utilization_percent=gpu_utilization_percent,
                        memory_utilization_percent=memory_utilization_percent,
                        temperature_celsius=temperature_celsius,
                        power_draw_watts=power_draw_watts,
                        power_limit_watts=power_limit_watts,
                        encoder_utilization_percent=encoder_utilization_percent,
                        decoder_utilization_percent=decoder_utilization_percent,
                    )
                    gpus.append(gpu)
                except Exception as e:
                    # Skip this GPU if there's an error
                    continue

            # Shutdown NVML
            pynvml.nvmlShutdown()

            gpu_by_vendor["nvidia"] = len(gpus)

        except Exception as e:
            # NVML not available or error initialization
            pass

        return gpus, driver_version, gpu_by_vendor

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
            "gpu": {
                "count": self.gpu_count,
                "driver_version": self.gpu_driver_version,
                "by_vendor": self.gpu_by_vendor,
                "devices": [gpu.to_dict() for gpu in self.gpus],
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

        # GPU: penalize if any GPU is > 85% utilization or > 85C
        for gpu in self.gpus:
            if gpu.gpu_utilization_percent > 85:
                score -= (gpu.gpu_utilization_percent - 85) * 0.3
            if gpu.memory_percent > 85:
                score -= (gpu.memory_percent - 85) * 0.3
            if gpu.temperature_celsius and gpu.temperature_celsius > 85:
                score -= (gpu.temperature_celsius - 85) * 0.3

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

    # GPU thresholds
    gpu_utilization_percent: float = 90.0
    gpu_memory_percent: float = 90.0
    gpu_temperature_celsius: Optional[float] = 85.0

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
            gpu_utilization_percent=data.get("gpu_utilization_percent", 90.0),
            gpu_memory_percent=data.get("gpu_memory_percent", 90.0),
            gpu_temperature_celsius=data.get("gpu_temperature_celsius", 85.0),
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
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "gpu_memory_percent": self.gpu_memory_percent,
            "gpu_temperature_celsius": self.gpu_temperature_celsius,
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

    def __init__(
        self,
        config: Optional[MonitorConfig] = None,
        network_monitor: Optional["NetworkMonitor"] = None,
    ):
        """Initialize the system monitor.

        Args:
            config: Configuration for the monitor.
            network_monitor: Optional NetworkMonitor instance to include service health in overall health.
        """
        self.config = config or MonitorConfig()
        self.workspace = Path(self.config.workspace).resolve()
        self._running = False
        self._metrics_history: List[ResourceMetrics] = []
        self._current_metrics: Optional[ResourceMetrics] = None
        self._current_status = SystemHealthStatus.UNKNOWN
        self._callbacks: List[MonitoringCallback] = []
        self._alert_callbacks: List[Callable[["SystemAlert"], None]] = []

        # Optional NetworkMonitor for service health integration
        self._network_monitor: Optional["NetworkMonitor"] = network_monitor

        # Initialize GPUMonitor for cross-vendor GPU tracking
        self._gpu_monitor: Optional[GPUMonitor] = None
        if HAS_GPU_MONITOR and GPUMonitor:
            try:
                from app.core.events import get_event_bus
                self._gpu_monitor = GPUMonitor(
                    workspace=str(self.workspace),
                    event_bus=get_event_bus(),
                    poll_interval_seconds=self.config.interval_seconds,
                    enabled=self.config.enabled,
                )
            except Exception:
                self._gpu_monitor = None

        # Thread safety for shared state
        self._lock = threading.RLock()

    def add_callback(self, callback: MonitoringCallback) -> None:
        """Add a monitoring callback."""
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: MonitoringCallback) -> None:
        """Remove a monitoring callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def collect_metrics(self) -> ResourceMetrics:
        """Collect current system metrics."""
        metrics = ResourceMetrics.collect()

        with self._lock:
            self._current_metrics = metrics

            # Add to history
            self._metrics_history.append(metrics)
            if len(self._metrics_history) > self.config.history_size:
                self._metrics_history = self._metrics_history[-self.config.history_size:]

            # Also collect from GPUMonitor for event publishing
            gpu_monitor = self._gpu_monitor
            old_status = self._current_status
            self._current_status = self._calculate_overall_health_status(metrics)
            callbacks = list(self._callbacks)

        # Notify callbacks (outside lock)
        for callback in callbacks:
            callback.on_metrics_collected(metrics)

        if old_status != self._current_status:
            for callback in callbacks:
                callback.on_health_change(old_status, self._current_status)

        # GPUMonitor collect (outside lock to avoid blocking)
        if gpu_monitor:
            try:
                gpu_monitor.collect_metrics()
            except Exception:
                pass

        return metrics

    def get_current_metrics(self) -> Optional[ResourceMetrics]:
        """Get the current metrics."""
        with self._lock:
            if self._current_metrics is None:
                pass  # Will collect outside lock

        if self._current_metrics is None:
            self.collect_metrics()

        with self._lock:
            return self._current_metrics

    def get_health_status(self) -> SystemHealthStatus:
        """Get the current health status."""
        with self._lock:
            if self._current_metrics is None:
                pass  # Will collect outside lock

        if self._current_metrics is None:
            self.collect_metrics()

        with self._lock:
            return self._current_status

    def get_metrics_history(self, count: Optional[int] = None) -> List[ResourceMetrics]:
        """Get historical metrics."""
        with self._lock:
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

        # GPU thresholds
        if metrics.gpus:
            for gpu in metrics.gpus:
                # GPU utilization threshold
                if gpu.gpu_utilization_percent > thresholds.gpu_utilization_percent:
                    alerts.append(SystemAlert(
                        id=f"gpu_{gpu.index}_util_{int(time.time())}",
                        title=f"High GPU {gpu.index} Utilization: {gpu.gpu_utilization_percent:.1f}%",
                        description=f"GPU {gpu.index} ({gpu.name}) utilization ({gpu.gpu_utilization_percent:.1f}%) exceeds threshold ({thresholds.gpu_utilization_percent}%)",
                        severity=AlertSeverity.HIGH,
                        metric_name=f"gpu_{gpu.index}_utilization",
                        current_value=gpu.gpu_utilization_percent,
                        threshold=thresholds.gpu_utilization_percent,
                    ))

                # GPU memory threshold
                if gpu.memory_percent > thresholds.gpu_memory_percent:
                    alerts.append(SystemAlert(
                        id=f"gpu_{gpu.index}_mem_{int(time.time())}",
                        title=f"High GPU {gpu.index} Memory Usage: {gpu.memory_percent:.1f}%",
                        description=f"GPU {gpu.index} ({gpu.name}) memory usage ({gpu.memory_percent:.1f}%) exceeds threshold ({thresholds.gpu_memory_percent}%)",
                        severity=AlertSeverity.HIGH,
                        metric_name=f"gpu_{gpu.index}_memory",
                        current_value=gpu.memory_percent,
                        threshold=thresholds.gpu_memory_percent,
                    ))

                # GPU temperature threshold
                if gpu.temperature_celsius and thresholds.gpu_temperature_celsius:
                    if gpu.temperature_celsius > thresholds.gpu_temperature_celsius:
                        alerts.append(SystemAlert(
                            id=f"gpu_{gpu.index}_temp_{int(time.time())}",
                            title=f"High GPU {gpu.index} Temperature: {gpu.temperature_celsius:.1f}C",
                            description=f"GPU {gpu.index} ({gpu.name}) temperature ({gpu.temperature_celsius:.1f}C) exceeds threshold ({thresholds.gpu_temperature_celsius}C)",
                            severity=AlertSeverity.CRITICAL,
                            metric_name=f"gpu_{gpu.index}_temperature",
                            current_value=gpu.temperature_celsius,
                            threshold=thresholds.gpu_temperature_celsius,
                        ))

        return alerts

    def start(self) -> None:
        """Start continuous monitoring."""
        with self._lock:
            if self._running:
                return

            self._running = True

        # Start GPUMonitor if available
        if self._gpu_monitor:
            try:
                self._gpu_monitor.start_monitoring()
            except Exception:
                pass

        import threading
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop continuous monitoring."""
        thread = None
        with self._lock:
            self._running = False
            thread = getattr(self, '_thread', None)

        # Stop GPUMonitor if available
        if self._gpu_monitor:
            try:
                self._gpu_monitor.stop_monitoring()
            except Exception:
                pass

        if thread:
            thread.join(timeout=self.config.interval_seconds + 1)

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                self.collect_metrics()
                alerts = self.check_thresholds()
                with self._lock:
                    callbacks = list(self._callbacks)
                for alert in alerts:
                    for callback in callbacks:
                        callback.on_alert(alert)
            except Exception as e:
                print(f"[MONITOR] Error in monitoring loop: {e}")

            # Sleep for the interval
            for _ in range(int(self.config.interval_seconds * 10)):
                with self._lock:
                    if not self._running:
                        break
                time.sleep(0.1)

    def _apply_network_health_to_score(self, score: float) -> float:
        """Apply only verified service-monitor signals to the operational health score."""
        if not self._network_monitor:
            return score
        try:
            all_health = self._network_monitor.get_all_health()
        except Exception:
            return min(score, 59.0)
        if not all_health:
            return score

        statuses = [health.status for health in all_health.values()]
        unhealthy_count = sum(status == ServiceStatus.UNHEALTHY for status in statuses)
        degraded_count = sum(status == ServiceStatus.DEGRADED for status in statuses)
        unverified = any(
            status == ServiceStatus.UNKNOWN
            or not health.last_check
            or not health.metadata.get("verified", False)
            for health, status in ((item, item.status) for item in all_health.values())
        )
        score -= min(30.0, unhealthy_count * 10.0 + degraded_count * 5.0)
        # A registered service with no verified result, or a completed non-healthy
        # result, must not be represented as an excellent/good readiness signal.
        if unverified or unhealthy_count or degraded_count:
            score = min(score, 59.0)
        return score

    def _calculate_overall_health_status(self, metrics: "ResourceMetrics") -> SystemHealthStatus:
        """Calculate health using structured, verified service-monitor results."""
        score = max(0.0, min(100.0, self._apply_network_health_to_score(metrics.calculate_health_score())))
        if score >= 80:
            return SystemHealthStatus.EXCELLENT
        if score >= 60:
            return SystemHealthStatus.GOOD
        if score >= 20:
            return SystemHealthStatus.WARNING
        return SystemHealthStatus.CRITICAL

    def _calculate_overall_health_score(self, metrics: "ResourceMetrics") -> float:
        """Return the numerical score corresponding to the verified health state."""
        return max(0.0, min(100.0, self._apply_network_health_to_score(metrics.calculate_health_score())))

    def _get_service_summary(self) -> Optional[Dict[str, Any]]:
        """Get a summary of monitored services if NetworkMonitor is available."""
        if not self._network_monitor:
            return None
        try:
            all_health = self._network_monitor.get_all_health()
            if not all_health:
                return None

            healthy = sum(1 for h in all_health.values() if h.status == ServiceStatus.HEALTHY)
            degraded = sum(1 for h in all_health.values() if h.status == ServiceStatus.DEGRADED)
            unhealthy = sum(1 for h in all_health.values() if h.status == ServiceStatus.UNHEALTHY)
            unknown = sum(1 for h in all_health.values() if h.status == ServiceStatus.UNKNOWN)

            return {
                "total": len(all_health),
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
                "unknown": unknown,
                "details": {
                    name: {
                        "status": health.status.value,
                        "healthy_endpoints": health.healthy_endpoints,
                        "total_endpoints": health.total_endpoints,
                        "consecutive_failures": health.consecutive_failures,
                    }
                    for name, health in all_health.items()
                },
            }
        except Exception:
            return None

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current system state."""
        with self._lock:
            metrics = self._current_metrics
            current_status = self._current_status
            gpu_monitor = self._gpu_monitor
            network_monitor = self._network_monitor

        if metrics is None:
            self.collect_metrics()
            with self._lock:
                metrics = self._current_metrics
                current_status = self._current_status

        if metrics is None:
            return {"status": "unknown"}

        gpu_summary = None
        if metrics.gpus:
            gpu_summary = {
                "count": metrics.gpu_count,
                "driver_version": metrics.gpu_driver_version,
                "by_vendor": metrics.gpu_by_vendor,
                "devices": [
                    {
                        "index": gpu.index,
                        "vendor": gpu.vendor,
                        "name": gpu.name,
                        "utilization_percent": gpu.gpu_utilization_percent,
                        "memory_percent": gpu.memory_percent,
                        "temperature_celsius": gpu.temperature_celsius,
                        "power_draw_watts": gpu.power_draw_watts,
                    }
                    for gpu in metrics.gpus
                ],
            }

        # Also include GPUMonitor summary if available (and merge key metrics)
        if gpu_monitor:
            try:
                monitor_summary = gpu_monitor.get_summary()
                if monitor_summary and isinstance(monitor_summary, dict):
                    # Merge vendor counts if available
                    if "by_vendor" in monitor_summary and monitor_summary["by_vendor"]:
                        if gpu_summary is None:
                            gpu_summary = {}
                        gpu_summary["by_vendor"] = monitor_summary["by_vendor"]
                    # Add total count if available
                    if "total_gpus" in monitor_summary:
                        if gpu_summary is None:
                            gpu_summary = {}
                        gpu_summary["total_gpus"] = monitor_summary["total_gpus"]
                    # Preserve the monitor's verified optional-capability health.
                    if "health" in monitor_summary:
                        if gpu_summary is None:
                            gpu_summary = {}
                        gpu_summary["health"] = monitor_summary["health"]
            except Exception:
                pass

        # Get service summary
        services = None
        if network_monitor:
            try:
                all_health = network_monitor.get_all_health()
                if all_health:
                    healthy = sum(1 for h in all_health.values() if h.status == ServiceStatus.HEALTHY)
                    degraded = sum(1 for h in all_health.values() if h.status == ServiceStatus.DEGRADED)
                    unhealthy = sum(1 for h in all_health.values() if h.status == ServiceStatus.UNHEALTHY)
                    unknown = sum(1 for h in all_health.values() if h.status == ServiceStatus.UNKNOWN)

                    services = {
                        "total": len(all_health),
                        "healthy": healthy,
                        "degraded": degraded,
                        "unhealthy": unhealthy,
                        "unknown": unknown,
                        "details": {
                            name: {
                                "status": health.status.value,
                                "healthy_endpoints": health.healthy_endpoints,
                                "total_endpoints": health.total_endpoints,
                                "consecutive_failures": health.consecutive_failures,
                                "last_check": health.last_check,
                                "verified": bool(health.last_check and health.metadata.get("verified", False)),
                                "error_categories": health.metadata.get("error_categories", []),
                            }
                            for name, health in all_health.items()
                        },
                    }
            except Exception:
                pass

        return {
            "status": current_status.value,
            "health_score": self._calculate_overall_health_score(metrics),
            "cpu_percent": metrics.cpu_percent,
            "memory_percent": metrics.memory_percent,
            "disk_percent": metrics.disk_percent,
            "temperature": metrics.temperature_celsius,
            "process_count": metrics.process_count,
            "gpu": gpu_summary,
            "services": services,
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
