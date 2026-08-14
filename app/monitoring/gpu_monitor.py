"""GPU / Hardware Detection Monitor.

This module provides cross-vendor GPU detection and monitoring capabilities
supporting NVIDIA (via pynvml), AMD (via rocm-smi/lspci), and Intel (via intel_gpu_top/lspci).
"""

import json
import platform
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.events import EventBus, get_event_bus, EventPriority


class GPUVendor(Enum):
    """GPU vendor types."""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"


@dataclass
class GPUInfo:
    """Static GPU hardware information."""
    index: int = 0
    vendor: GPUVendor = GPUVendor.UNKNOWN
    name: str = ""
    driver_version: str = ""
    vram_total_mb: float = 0.0
    vram_free_mb: float = 0.0
    vram_used_mb: float = 0.0
    compute_capability: Optional[str] = None
    cuda_version: Optional[str] = None
    rocm_version: Optional[str] = None
    opencl_version: Optional[str] = None
    pcie_bandwidth: Optional[str] = None
    architecture: str = ""
    device_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "index": self.index,
            "vendor": self.vendor.value,
            "name": self.name,
            "driver_version": self.driver_version,
            "vram": {
                "total_mb": self.vram_total_mb,
                "used_mb": self.vram_used_mb,
                "free_mb": self.vram_free_mb,
            },
            "compute_capability": self.compute_capability,
            "cuda_version": self.cuda_version,
            "rocm_version": self.rocm_version,
            "opencl_version": self.opencl_version,
            "pcie_bandwidth": self.pcie_bandwidth,
            "architecture": self.architecture,
            "device_id": self.device_id,
        }


@dataclass
class GPUMetrics:
    """Dynamic GPU runtime metrics."""
    index: int = 0
    vendor: GPUVendor = GPUVendor.UNKNOWN
    name: str = ""
    gpu_utilization_percent: float = 0.0
    memory_utilization_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    memory_total_mb: float = 0.0
    temperature_celsius: Optional[float] = None
    power_draw_watts: Optional[float] = None
    power_limit_watts: Optional[float] = None
    fan_speed_percent: Optional[float] = None
    clock_graphics_mhz: Optional[int] = None
    clock_memory_mhz: Optional[int] = None
    clock_processor_mhz: Optional[int] = None
    encoder_utilization_percent: Optional[float] = None
    decoder_utilization_percent: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "index": self.index,
            "vendor": self.vendor.value,
            "name": self.name,
            "utilization": {
                "gpu_percent": self.gpu_utilization_percent,
                "memory_percent": self.memory_utilization_percent,
                "encoder_percent": self.encoder_utilization_percent,
                "decoder_percent": self.decoder_utilization_percent,
            },
            "memory": {
                "used_mb": self.memory_used_mb,
                "free_mb": self.memory_free_mb,
                "total_mb": self.memory_total_mb,
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
                "processor_mhz": self.clock_processor_mhz,
            },
            "timestamp": self.timestamp,
        }


@dataclass
class GPUHealthResult:
    """Verified, structured GPU capability health for operational consumers."""
    status: str = "unknown"
    availability: str = "unknown"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    error_category: Optional[str] = None
    fallback_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": "gpu",
            "status": self.status,
            "availability": self.availability,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "error_category": self.error_category,
            "fallback_active": self.fallback_active,
        }


class GPUDetector:
    """Cross-vendor GPU hardware detection."""

    def __init__(self):
        self._nvidia_available = False
        self._amd_available = False
        self._intel_available = False
        self._vendor_detectors = {}
        self._probe_errors: List[Dict[str, str]] = []

    @property
    def probe_errors(self) -> List[Dict[str, str]]:
        return list(self._probe_errors)

    def _record_probe_error(self, source: str, error: Exception) -> None:
        category = "tooling_unavailable" if isinstance(error, (ImportError, FileNotFoundError)) else "probe_failure"
        entry = {"source": source, "category": category, "message": str(error)}
        if not any(item["source"] == source and item["category"] == category for item in self._probe_errors):
            self._probe_errors.append(entry)

    def detect_all(self) -> List[GPUInfo]:
        """Detect all GPUs across all vendors."""
        self._probe_errors.clear()
        all_gpus = []

        # Try NVIDIA via pynvml
        nvidia_gpus = self._detect_nvidia()
        all_gpus.extend(nvidia_gpus)

        # Try AMD via rocm-smi / lspci
        amd_gpus = self._detect_amd()
        all_gpus.extend(amd_gpus)

        # Try Intel via lspci / intel_gpu_top
        intel_gpus = self._detect_intel()
        all_gpus.extend(intel_gpus)

        # Fallback: lspci for any missed GPUs
        fallback_gpus = self._detect_via_lspci(existing=all_gpus)
        all_gpus.extend(fallback_gpus)

        # Assign indices
        for idx, gpu in enumerate(all_gpus):
            gpu.index = idx

        return all_gpus

    def _detect_nvidia(self) -> List[GPUInfo]:
        """Detect NVIDIA GPUs using pynvml."""
        gpus = []

        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvidia_available = True

            driver_version = ""
            try:
                dv = pynvml.nvmlSystemGetDriverVersion()
                driver_version = dv.decode('utf-8') if isinstance(dv, bytes) else dv
            except Exception:
                pass

            gpu_count = pynvml.nvmlDeviceGetCount()

            for i in range(gpu_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode('utf-8')

                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    vram_total_mb = round(mem_info.total / (1024 ** 2), 2)
                    vram_used_mb = round(mem_info.used / (1024 ** 2), 2)
                    vram_free_mb = round(mem_info.free / (1024 ** 2), 2)

                    # Compute capability
                    compute_cap = ""
                    try:
                        major = pynvml.nvmlDeviceGetCudaComputeCapability(handle)[0]
                        minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)[1]
                        compute_cap = f"{major}.{minor}"
                    except Exception:
                        pass

                    # Architecture
                    arch = ""
                    try:
                        arch = pynvml.nvmlDeviceGetArchitecture(handle)
                    except Exception:
                        pass

                    # Device ID
                    device_id = ""
                    try:
                        device_id = f"{pynvml.nvmlDeviceGetPciInfo(handle).deviceId:x}"
                    except Exception:
                        pass

                    gpu = GPUInfo(
                        index=i,
                        vendor=GPUVendor.NVIDIA,
                        name=name,
                        driver_version=driver_version,
                        vram_total_mb=vram_total_mb,
                        vram_used_mb=vram_used_mb,
                        vram_free_mb=vram_free_mb,
                        compute_capability=compute_cap,
                        cuda_version=self._get_cuda_version(),
                        architecture=arch,
                        device_id=device_id,
                    )
                    gpus.append(gpu)
                except Exception as error:
                    self._record_probe_error("nvidia_device", error)
                    continue

            pynvml.nvmlShutdown()
        except Exception as error:
            self._nvidia_available = False
            self._record_probe_error("nvidia", error)

        return gpus

    def _get_cuda_version(self) -> Optional[str]:
        """Get CUDA version if available."""
        try:
            import subprocess
            result = subprocess.run(
                ["nvcc", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if "release" in line.lower():
                        parts = line.split()
                        for p in parts:
                            if p.startswith("V") or p.replace(".", "").isdigit():
                                return p
        except Exception:
            pass
        return None

    def _detect_amd(self) -> List[GPUInfo]:
        """Detect AMD GPUs using rocm-smi or lspci."""
        gpus = []

        # Try rocm-smi first (ROCm)
        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname", "--showvram", "--showmeminfo", "--showuniqueid", "-j"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for idx, (key, val) in enumerate(data.items()):
                    if key.startswith("card") or key.startswith("gpu"):
                        gpu = GPUInfo(
                            index=len(gpus),
                            vendor=GPUVendor.AMD,
                            name=val.get("Card series", "AMD GPU"),
                            driver_version=val.get("Driver Version", ""),
                            vram_total_mb=self._parse_mb(val.get("Total VRAM", "0")),
                            vram_used_mb=self._parse_mb(val.get("Used VRAM", "0")),
                            vram_free_mb=self._parse_mb(val.get("Free VRAM", "0")),
                            rocm_version=self._get_rocm_version(),
                            device_id=val.get("Unique ID", ""),
                        )
                        gpus.append(gpu)
                self._amd_available = True
        except Exception as error:
            self._record_probe_error("amd", error)

        # Fallback to lspci for AMD
        if not gpus:
            gpus.extend(self._detect_amd_via_lspci())

        return gpus

    def _detect_amd_via_lspci(self) -> List[GPUInfo]:
        """Detect AMD GPUs via lspci."""
        gpus = []
        try:
            result = subprocess.run(
                ["lspci", "-nn", "-k"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return gpus

            for line in result.stdout.split('\n'):
                if "VGA compatible controller" in line and ("AMD" in line or "Advanced Micro Devices" in line):
                    # Parse device ID
                    device_id = ""
                    import re
                    match = re.search(r'\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    if match:
                        device_id = f"{match.group(1)}:{match.group(2)}"

                    # Extract name
                    name = line.split("VGA compatible controller:")[-1].strip()

                    gpu = GPUInfo(
                        index=len(gpus),
                        vendor=GPUVendor.AMD,
                        name=name,
                        device_id=device_id,
                    )
                    gpus.append(gpu)
        except Exception as error:
            self._record_probe_error("amd_lspci", error)

        return gpus

    def _get_rocm_version(self) -> Optional[str]:
        """Get ROCm version if available."""
        try:
            result = subprocess.run(
                ["rocminfo"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if "ROCm" in line and "Version" in line:
                        return line.split("Version")[-1].strip()
        except Exception:
            pass
        return None

    def _parse_mb(self, val: str) -> float:
        """Parse memory value to MB."""
        try:
            val = val.upper().strip()
            if val.endswith("GB"):
                return float(val[:-2]) * 1024
            elif val.endswith("MB"):
                return float(val[:-2])
            elif val.endswith("KB"):
                return float(val[:-2]) / 1024
            else:
                return float(val) / (1024 * 1024)  # Assume bytes
        except Exception:
            return 0.0

    def _detect_intel(self) -> List[GPUInfo]:
        """Detect Intel GPUs using intel_gpu_top or lspci."""
        gpus = []

        # Try lspci for Intel integrated/discrete GPUs
        gpus.extend(self._detect_intel_via_lspci())

        return gpus

    def _detect_intel_via_lspci(self) -> List[GPUInfo]:
        """Detect Intel GPUs via lspci."""
        gpus = []
        try:
            result = subprocess.run(
                ["lspci", "-nn", "-k"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return gpus

            for line in result.stdout.split('\n'):
                if "VGA compatible controller" in line and "Intel" in line:
                    device_id = ""
                    import re
                    match = re.search(r'\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    if match:
                        device_id = f"{match.group(1)}:{match.group(2)}"

                    name = line.split("VGA compatible controller:")[-1].strip()

                    gpu = GPUInfo(
                        index=len(gpus),
                        vendor=GPUVendor.INTEL,
                        name=name,
                        device_id=device_id,
                    )
                    gpus.append(gpu)
        except Exception as error:
            self._record_probe_error("intel_lspci", error)

        return gpus

    def _detect_via_lspci(self, existing: List[GPUInfo]) -> List[GPUInfo]:
        """Fallback GPU detection via lspci for any missed GPUs."""
        gpus = []
        try:
            result = subprocess.run(
                ["lspci", "-nn"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return gpus

            existing_names = {g.name.lower() for g in existing}

            for line in result.stdout.split('\n'):
                if "VGA compatible controller" in line or "3D controller" in line:
                    # Check if already detected
                    name_lower = line.lower()
                    if any(existing in name_lower for existing in existing_names):
                        continue

                    vendor = GPUVendor.UNKNOWN
                    if "NVIDIA" in line:
                        vendor = GPUVendor.NVIDIA
                    elif "AMD" in line or "Advanced Micro Devices" in line:
                        vendor = GPUVendor.AMD
                    elif "Intel" in line:
                        vendor = GPUVendor.INTEL

                    device_id = ""
                    import re
                    match = re.search(r'\[([0-9a-f]{4}):([0-9a-f]{4})\]', line)
                    if match:
                        device_id = f"{match.group(1)}:{match.group(2)}"

                    name = line.split(":")[-1].strip()

                    gpu = GPUInfo(
                        index=len(gpus),
                        vendor=vendor,
                        name=name,
                        device_id=device_id,
                    )
                    gpus.append(gpu)
        except Exception as error:
            self._record_probe_error("lspci", error)

        return gpus


class GPUMetricsCollector:
    """Collects runtime GPU metrics from all vendors."""

    def __init__(self):
        self._nvidia_available = False
        self._probe_errors: List[Dict[str, str]] = []

    @property
    def probe_errors(self) -> List[Dict[str, str]]:
        return list(self._probe_errors)

    def _record_probe_error(self, source: str, error: Exception) -> None:
        category = "tooling_unavailable" if isinstance(error, (ImportError, FileNotFoundError)) else "probe_failure"
        entry = {"source": source, "category": category, "message": str(error)}
        if not any(item["source"] == source and item["category"] == category for item in self._probe_errors):
            self._probe_errors.append(entry)

    def collect_all(self) -> List[GPUMetrics]:
        """Collect metrics from all detected GPUs."""
        self._probe_errors.clear()
        all_metrics = []

        # NVIDIA via pynvml
        nvidia_metrics = self._collect_nvidia()
        all_metrics.extend(nvidia_metrics)

        # AMD - try rocm-smi for metrics
        amd_metrics = self._collect_amd()
        all_metrics.extend(amd_metrics)

        # Intel - no standard tools for runtime metrics on Linux
        # Could use intel_gpu_top but it's interactive
        intel_metrics = self._collect_intel()
        all_metrics.extend(intel_metrics)

        return all_metrics

    def _collect_nvidia(self) -> List[GPUMetrics]:
        """Collect NVIDIA GPU metrics via pynvml."""
        metrics = []

        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvidia_available = True

            gpu_count = pynvml.nvmlDeviceGetCount()

            for i in range(gpu_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode('utf-8')

                    # Memory info
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    memory_total_mb = round(mem_info.total / (1024 ** 2), 2)
                    memory_used_mb = round(mem_info.used / (1024 ** 2), 2)
                    memory_free_mb = round(mem_info.free / (1024 ** 2), 2)
                    memory_utilization_percent = round((mem_info.used / mem_info.total) * 100, 2) if mem_info.total > 0 else 0.0

                    # Utilization
                    utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_utilization_percent = utilization.gpu

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
                        power_draw_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                        power_limit_watts = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
                    except Exception:
                        pass

                    # Fan speed
                    fan_speed_percent = None
                    try:
                        fan_speed_percent = pynvml.nvmlDeviceGetFanSpeed(handle)
                    except Exception:
                        pass

                    # Clock speeds
                    clock_graphics_mhz = None
                    clock_memory_mhz = None
                    try:
                        clock_graphics_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                        clock_memory_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                    except Exception:
                        pass

                    # Encoder/Decoder
                    encoder_util = None
                    decoder_util = None
                    try:
                        encoder_stats = pynvml.nvmlDeviceGetEncoderStats(handle)
                        if encoder_stats.sessionCount > 0:
                            encoder_util = encoder_stats.averageLatency
                    except Exception:
                        pass
                    try:
                        decoder_stats = pynvml.nvmlDeviceGetDecoderStats(handle)
                        if decoder_stats.sessionCount > 0:
                            decoder_util = decoder_stats.averageLatency
                    except Exception:
                        pass

                    gpu_metric = GPUMetrics(
                        index=i,
                        vendor=GPUVendor.NVIDIA,
                        name=name,
                        gpu_utilization_percent=gpu_utilization_percent,
                        memory_utilization_percent=memory_utilization_percent,
                        memory_used_mb=memory_used_mb,
                        memory_free_mb=memory_free_mb,
                        memory_total_mb=memory_total_mb,
                        temperature_celsius=temperature_celsius,
                        power_draw_watts=power_draw_watts,
                        power_limit_watts=power_limit_watts,
                        fan_speed_percent=fan_speed_percent,
                        clock_graphics_mhz=clock_graphics_mhz,
                        clock_memory_mhz=clock_memory_mhz,
                        encoder_utilization_percent=encoder_util,
                        decoder_utilization_percent=decoder_util,
                    )
                    metrics.append(gpu_metric)
                except Exception:
                    continue

            pynvml.nvmlShutdown()
        except Exception as error:
            self._nvidia_available = False
            self._record_probe_error("nvidia_metrics", error)

        return metrics

    def _collect_amd(self) -> List[GPUMetrics]:
        """Collect AMD GPU metrics via rocm-smi."""
        metrics = []

        try:
            result = subprocess.run(
                ["rocm-smi", "--showuse", "--showtemp", "--showpower", "--showfan", "--showclk", "-j"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for idx, (key, val) in enumerate(data.items()):
                    if key.startswith("card") or key.startswith("gpu"):
                        gpu_util = val.get("GPU use (%)", 0)
                        mem_util = val.get("GPU memory use (%)", 0)

                        m = GPUMetrics(
                            index=len(metrics),
                            vendor=GPUVendor.AMD,
                            name=val.get("Card series", "AMD GPU"),
                            gpu_utilization_percent=float(gpu_util) if gpu_util else 0.0,
                            memory_utilization_percent=float(mem_util) if mem_util else 0.0,
                            temperature_celsius=self._parse_float(val.get("Temperature (edge)")) if val.get("Temperature (edge)") else None,
                            power_draw_watts=self._parse_float(val.get("Average Power (W)")) if val.get("Average Power (W)") else None,
                            fan_speed_percent=self._parse_float(val.get("Fan Speed (%)")) if val.get("Fan Speed (%)") else None,
                        )
                        metrics.append(m)
        except Exception as error:
            self._record_probe_error("amd_metrics", error)

        return metrics

    def _parse_float(self, val) -> Optional[float]:
        """Parse a value to float."""
        try:
            if val is None:
                return None
            return float(str(val).split()[0])
        except Exception:
            return None

    def _collect_intel(self) -> List[GPUMetrics]:
        """Collect Intel GPU metrics - limited availability."""
        # No standard cross-platform tool for Intel GPU runtime metrics
        # intel_gpu_top is interactive, not scriptable
        return []


class GPUMonitor:
    """Cross-vendor GPU monitor with explicit optional-capability health reporting."""

    def __init__(
        self,
        workspace: str = ".",
        event_bus: Optional[EventBus] = None,
        poll_interval_seconds: float = 5.0,
        enabled: bool = True,
    ):
        self.workspace = Path(workspace).resolve()
        self.event_bus = event_bus or get_event_bus()
        self.poll_interval = poll_interval_seconds
        self.enabled = enabled
        self._detector = GPUDetector()
        self._collector = GPUMetricsCollector()
        self._gpu_info: List[GPUInfo] = []
        self._current_metrics: List[GPUMetrics] = []
        self._running = False
        self._lock = threading.RLock()
        self._gpu_health = GPUHealthResult()
        self._initialize_hardware_state()

    def _set_gpu_health(
        self,
        *,
        status: str,
        availability: str,
        reason: str = "",
        error_category: Optional[str] = None,
        fallback_active: bool = False,
    ) -> None:
        self._gpu_health = GPUHealthResult(
            status=status,
            availability=availability,
            reason=reason,
            error_category=error_category,
            fallback_active=fallback_active,
        )

    def _initialize_hardware_state(self) -> None:
        if not self.enabled:
            self._set_gpu_health(
                status="disabled",
                availability="unknown",
                reason="GPU monitoring is disabled",
            )
            return
        try:
            self._gpu_info = self._detector.detect_all()
        except Exception as error:
            self._gpu_info = []
            self._set_gpu_health(
                status="degraded",
                availability="unknown",
                reason=f"GPU detection failed: {error}",
                error_category="probe_failure",
                fallback_active=True,
            )
            self._emit_gpu_probe_failure()
            self._emit_fallback_activated()
            return

        probe_errors = getattr(self._detector, "probe_errors", [])
        probe_failure = next((entry for entry in probe_errors if entry.get("category") == "probe_failure"), None)
        if self._gpu_info:
            self._set_gpu_health(
                status="degraded" if probe_failure else "healthy",
                availability="available",
                reason=(probe_failure or {}).get("message", "GPU devices detected"),
                error_category=(probe_failure or {}).get("category"),
            )
            self._emit_gpu_detected_events()
            if probe_failure:
                self._emit_gpu_probe_failure()
            return

        if probe_failure:
            self._set_gpu_health(
                status="degraded",
                availability="unknown",
                reason=probe_failure.get("message", "GPU detection probe failed"),
                error_category="probe_failure",
                fallback_active=True,
            )
            self._emit_gpu_probe_failure()
        else:
            tooling_error = next((entry for entry in probe_errors if entry.get("category") == "tooling_unavailable"), None)
            self._set_gpu_health(
                status="unavailable",
                availability="unavailable",
                reason=(tooling_error or {}).get("message", "No supported GPU detected"),
                error_category=(tooling_error or {}).get("category", "no_supported_gpu"),
                fallback_active=True,
            )
            self._emit_gpu_unavailable()
        self._emit_fallback_activated()

    def _emit_gpu_detected_events(self) -> None:
        for gpu in self._gpu_info:
            self.event_bus.emit(
                name="gpu.detected",
                data=gpu.to_dict(),
                source="gpu_monitor",
                priority=EventPriority.NORMAL,
                tags={"vendor": gpu.vendor.value},
            )

    def _emit_gpu_unavailable(self) -> None:
        self.event_bus.emit(
            name="gpu.unavailable",
            data=self._gpu_health.to_dict(),
            source="gpu_monitor",
            priority=EventPriority.NORMAL,
            tags={"availability": "unavailable"},
        )

    def _emit_gpu_probe_failure(self) -> None:
        self.event_bus.emit(
            name="gpu.probe_failed",
            data=self._gpu_health.to_dict(),
            source="gpu_monitor",
            priority=EventPriority.HIGH,
            tags={"error_category": self._gpu_health.error_category or "probe_failure"},
        )

    def _emit_fallback_activated(self) -> None:
        self.event_bus.emit(
            name="gpu.fallback_activated",
            data=self._gpu_health.to_dict(),
            source="gpu_monitor",
            priority=EventPriority.NORMAL,
            tags={"fallback": "cpu_local"},
        )

    def get_gpu_info(self) -> List[GPUInfo]:
        with self._lock:
            return list(self._gpu_info)

    def get_gpu_count(self) -> int:
        with self._lock:
            return len(self._gpu_info)

    def get_gpus_by_vendor(self, vendor: GPUVendor) -> List[GPUInfo]:
        with self._lock:
            return [gpu for gpu in self._gpu_info if gpu.vendor == vendor]

    def get_health(self) -> Dict[str, Any]:
        """Return the latest verified GPU capability health result."""
        with self._lock:
            return self._gpu_health.to_dict()

    def _record_metrics_failure(self, error: Exception) -> None:
        with self._lock:
            availability = self._gpu_health.availability
            fallback_active = availability != "available"
            self._set_gpu_health(
                status="degraded",
                availability=availability,
                reason=f"GPU metrics probe failed: {error}",
                error_category="metrics_failure",
                fallback_active=fallback_active,
            )
        self._emit_gpu_probe_failure()

    def collect_metrics(self) -> List[GPUMetrics]:
        """Collect GPU metrics; report a failed probe without crashing consumers."""
        if not self.enabled:
            return []
        try:
            metrics = self._collector.collect_all()
        except Exception as error:
            self._record_metrics_failure(error)
            return []

        collector_errors = getattr(self._collector, "probe_errors", [])
        probe_failure = next((entry for entry in collector_errors if entry.get("category") == "probe_failure"), None)
        if probe_failure and self._gpu_health.availability == "available":
            self._record_metrics_failure(RuntimeError(probe_failure.get("message", "GPU metrics probe failed")))

        with self._lock:
            previous_metrics = {metric.index: metric for metric in self._current_metrics}
            self._current_metrics = list(metrics)
        for metric in metrics:
            self._check_and_emit_change_events(metric, previous_metrics.get(metric.index))
        return list(metrics)

    def _check_and_emit_change_events(self, metric: GPUMetrics, previous: Optional[GPUMetrics]) -> None:
        if previous is None:
            return
        util_diff = abs(metric.gpu_utilization_percent - previous.gpu_utilization_percent)
        if util_diff > 20:
            self.event_bus.emit(
                name="gpu.usage_changed",
                data={
                    "index": metric.index,
                    "vendor": metric.vendor.value,
                    "name": metric.name,
                    "old_utilization": previous.gpu_utilization_percent,
                    "new_utilization": metric.gpu_utilization_percent,
                    "change": util_diff,
                },
                source="gpu_monitor",
                priority=EventPriority.NORMAL,
                tags={"vendor": metric.vendor.value, "gpu_index": str(metric.index)},
            )
        if metric.temperature_celsius and previous.temperature_celsius:
            temp_diff = abs(metric.temperature_celsius - previous.temperature_celsius)
            if temp_diff > 10:
                self.event_bus.emit(
                    name="gpu.temperature_changed",
                    data={
                        "index": metric.index,
                        "vendor": metric.vendor.value,
                        "name": metric.name,
                        "old_temperature": previous.temperature_celsius,
                        "new_temperature": metric.temperature_celsius,
                        "change": temp_diff,
                    },
                    source="gpu_monitor",
                    priority=EventPriority.HIGH if metric.temperature_celsius > 85 else EventPriority.NORMAL,
                    tags={"vendor": metric.vendor.value, "gpu_index": str(metric.index)},
                )
        if metric.temperature_celsius and metric.temperature_celsius > 85:
            self.event_bus.emit(
                name="gpu.health_changed",
                data={
                    "index": metric.index,
                    "vendor": metric.vendor.value,
                    "name": metric.name,
                    "status": "critical",
                    "reason": f"Temperature {metric.temperature_celsius}C exceeds threshold",
                },
                source="gpu_monitor",
                priority=EventPriority.CRITICAL,
                tags={"vendor": metric.vendor.value, "gpu_index": str(metric.index)},
            )

    def get_current_metrics(self) -> List[GPUMetrics]:
        with self._lock:
            metrics_available = bool(self._current_metrics)
        return list(self._current_metrics) if metrics_available else self.collect_metrics()

    def get_summary(self) -> Dict[str, Any]:
        metrics = self.get_current_metrics()
        with self._lock:
            gpu_info = list(self._gpu_info)
            health = self._gpu_health.to_dict()
        by_vendor: Dict[str, int] = {}
        for gpu in gpu_info:
            by_vendor[gpu.vendor.value] = by_vendor.get(gpu.vendor.value, 0) + 1
        return {
            "enabled": self.enabled,
            "total_gpus": len(gpu_info),
            "by_vendor": by_vendor,
            "devices": [gpu.to_dict() for gpu in gpu_info],
            "metrics": [metric.to_dict() for metric in metrics],
            "poll_interval_seconds": self.poll_interval,
            "health": health,
        }

    def start_monitoring(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()

    def stop_monitoring(self) -> None:
        with self._lock:
            self._running = False
            thread = getattr(self, "_thread", None)
        if thread:
            thread.join(timeout=self.poll_interval + 1)

    def _monitor_loop(self) -> None:
        import time
        while True:
            with self._lock:
                if not self._running:
                    break
                poll_interval = self.poll_interval
            self.collect_metrics()
            for _ in range(max(1, int(poll_interval * 10))):
                with self._lock:
                    if not self._running:
                        break
                time.sleep(0.1)

    def __enter__(self):
        self.start_monitoring()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_monitoring()


_gpu_monitor: Optional[GPUMonitor] = None
_gpu_monitor_lock = threading.Lock()


def get_gpu_monitor(
    workspace: str = ".",
    event_bus: Optional[EventBus] = None,
    poll_interval_seconds: float = 5.0,
    enabled: bool = True,
) -> GPUMonitor:
    """Get or create the global GPU monitor instance."""
    global _gpu_monitor
    with _gpu_monitor_lock:
        if _gpu_monitor is None:
            _gpu_monitor = GPUMonitor(
                workspace=workspace,
                event_bus=event_bus,
                poll_interval_seconds=poll_interval_seconds,
                enabled=enabled,
            )
        return _gpu_monitor


def set_gpu_monitor(monitor: GPUMonitor) -> None:
    """Set the global GPU monitor instance."""
    global _gpu_monitor
    with _gpu_monitor_lock:
        _gpu_monitor = monitor


def create_gpu_monitor(
    workspace: str = ".",
    event_bus: Optional[EventBus] = None,
    poll_interval_seconds: float = 5.0,
    enabled: bool = True,
) -> GPUMonitor:
    """Factory function to create a GPUMonitor instance."""
    return GPUMonitor(
        workspace=workspace,
        event_bus=event_bus,
        poll_interval_seconds=poll_interval_seconds,
        enabled=enabled,
    )