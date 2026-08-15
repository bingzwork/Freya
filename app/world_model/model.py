"""World Model Core Module.

This module provides the unified EnvironmentSnapshot dataclass and WorldModel
facade that integrates all of Freya's environment awareness components.
"""

import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.core.logger import logger

if TYPE_CHECKING:
    from app.monitoring.system_monitor import SystemHealthStatus, ResourceMetrics
    from app.monitoring.process_monitor import ProcessMonitor
    from app.git.git_manager import GitManager, GitStatus
    from app.core.tool_manager import ToolManager
    from app.health.health_monitor import HealthMonitor
    from app.core.project_index import ProjectIndex
    from app.world_model.project_metadata import ProjectMetadata, DependencySet, ProjectDependencies


@dataclass
class ProjectInfo:
    """Project-level information."""
    name: str = ""
    root_path: str = ""
    is_git_repo: bool = False
    main_language: str = ""
    framework: str = ""
    build_system: str = ""
    entry_points: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    file_count: int = 0
    total_lines: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "root_path": self.root_path,
            "is_git_repo": self.is_git_repo,
            "main_language": self.main_language,
            "framework": self.framework,
            "build_system": self.build_system,
            "entry_points": self.entry_points,
            "config_files": self.config_files,
            "file_count": self.file_count,
            "total_lines": self.total_lines,
        }


@dataclass
class RuntimeInfo:
    """Runtime environment information."""
    os_name: str = ""
    os_version: str = ""
    os_family: str = ""
    shell_name: str = ""
    shell_path: str = ""
    python_version: str = ""
    python_major: int = 0
    python_minor: int = 0
    python_patch: int = 0
    python_executable: str = ""
    working_directory: str = ""
    environment: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "os": {
                "name": self.os_name,
                "version": self.os_version,
                "family": self.os_family,
            },
            "shell": {
                "name": self.shell_name,
                "path": self.shell_path,
            },
            "python": {
                "version": self.python_version,
                "major": self.python_major,
                "minor": self.python_minor,
                "patch": self.python_patch,
                "executable": self.python_executable,
            },
            "working_directory": self.working_directory,
            "environment": self.environment,
        }


@dataclass
class GitInfo:
    """Git repository information."""
    is_repo: bool = False
    is_clean: bool = False
    current_branch: str = ""
    branches: List[Dict[str, Any]] = field(default_factory=list)
    remotes: List[str] = field(default_factory=list)
    status: Dict[str, Any] = field(default_factory=dict)
    ahead: int = 0
    behind: int = 0
    has_changes: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_repo": self.is_repo,
            "is_clean": self.is_clean,
            "current_branch": self.current_branch,
            "branches": self.branches,
            "remotes": self.remotes,
            "status": self.status,
            "ahead": self.ahead,
            "behind": self.behind,
            "has_changes": self.has_changes,
        }


@dataclass
class ResourceInfo:
    """System resource information."""
    cpu_percent: float = 0.0
    cpu_count: int = 0
    cpu_freq_mhz: float = 0.0
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_free_gb: float = 0.0
    memory_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_percent: float = 0.0
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0
    net_sent_mb: float = 0.0
    net_recv_mb: float = 0.0
    process_count: int = 0
    thread_count: int = 0
    temperature_celsius: Optional[float] = None
    load_avg_1min: Optional[float] = None
    load_avg_5min: Optional[float] = None
    load_avg_15min: Optional[float] = None
    health_score: float = 0.0
    health_status: str = "unknown"
    # GPU information
    gpu_count: int = 0
    gpu_driver_version: str = ""
    gpu_by_vendor: Dict[str, int] = field(default_factory=dict)
    gpu_devices: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            "health_score": self.health_score,
            "health_status": self.health_status,
            "gpu": {
                "count": self.gpu_count,
                "driver_version": self.gpu_driver_version,
                "by_vendor": self.gpu_by_vendor,
                "devices": self.gpu_devices,
            },
        }


@dataclass
class ToolInfo:
    """Tool availability and version information."""
    available_tools: List[str] = field(default_factory=list)
    tool_versions: Dict[str, str] = field(default_factory=dict)
    git_available: bool = False
    python_available: bool = False
    node_available: bool = False
    npm_available: bool = False
    docker_available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available_tools": self.available_tools,
            "tool_versions": self.tool_versions,
            "git_available": self.git_available,
            "python_available": self.python_available,
            "node_available": self.node_available,
            "npm_available": self.npm_available,
            "docker_available": self.docker_available,
        }


@dataclass
class HealthInfo:
    """Health and diagnostics information."""
    overall_status: str = "unknown"
    health_score: float = 0.0
    metrics_count: int = 0
    alerts_count: int = 0
    code_quality: Dict[str, Any] = field(default_factory=dict)
    test_metrics: Dict[str, Any] = field(default_factory=dict)
    performance_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "health_score": self.health_score,
            "metrics_count": self.metrics_count,
            "alerts_count": self.alerts_count,
            "code_quality": self.code_quality,
            "test_metrics": self.test_metrics,
            "performance_metrics": self.performance_metrics,
        }


@dataclass
class EnvironmentSnapshot:
    """Unified point-in-time snapshot of Freya's operating environment.

    This dataclass captures all environment layers at a single moment,
    providing a consistent view for planning, decision-making, and debugging.
    """
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    elapsed_ms: float = 0.0

    # Core environment layers
    project: ProjectInfo = field(default_factory=ProjectInfo)
    runtime: RuntimeInfo = field(default_factory=RuntimeInfo)
    git: GitInfo = field(default_factory=GitInfo)
    resources: ResourceInfo = field(default_factory=ResourceInfo)
    tools: ToolInfo = field(default_factory=ToolInfo)
    health: HealthInfo = field(default_factory=HealthInfo)
    services: List[Any] = field(default_factory=list)  # External services

    # Metadata
    snapshot_id: str = field(default_factory=lambda: f"snap_{int(time.time() * 1000)}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "elapsed_ms": self.elapsed_ms,
            "project": self.project.to_dict(),
            "runtime": self.runtime.to_dict(),
            "git": self.git.to_dict(),
            "resources": self.resources.to_dict(),
            "tools": self.tools.to_dict(),
            "health": self.health.to_dict(),
            "services": [service.to_dict() for service in self.services],
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnvironmentSnapshot":
        """Create snapshot from dictionary."""
        snapshot = cls(
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            elapsed_ms=data.get("elapsed_ms", 0.0),
            snapshot_id=data.get("snapshot_id", f"snap_{int(time.time() * 1000)}"),
        )

        if "project" in data:
            snapshot.project = ProjectInfo(**data["project"])
        if "runtime" in data:
            r = data["runtime"]
            # to_dict() produces nested dict, flatten for constructor
            snapshot.runtime = RuntimeInfo(
                os_name=r.get("os", {}).get("name", ""),
                os_version=r.get("os", {}).get("version", ""),
                os_family=r.get("os", {}).get("family", ""),
                shell_name=r.get("shell", {}).get("name", ""),
                shell_path=r.get("shell", {}).get("path", ""),
                python_version=r.get("python", {}).get("version", ""),
                python_major=r.get("python", {}).get("major", 0),
                python_minor=r.get("python", {}).get("minor", 0),
                python_patch=r.get("python", {}).get("patch", 0),
                python_executable=r.get("python", {}).get("executable", ""),
                working_directory=r.get("working_directory", ""),
                environment=r.get("environment", {}),
            )
        if "git" in data:
            snapshot.git = GitInfo(**data["git"])
        if "resources" in data:
            res = data["resources"]
            cpu = res.get("cpu", {})
            mem = res.get("memory", {})
            disk = res.get("disk", {})
            net = res.get("network", {})
            proc = res.get("processes", {})
            load = res.get("load_avg", {})
            snapshot.resources = ResourceInfo(
                cpu_percent=cpu.get("percent", 0.0),
                cpu_count=cpu.get("count", 0),
                cpu_freq_mhz=cpu.get("freq_mhz", 0.0),
                memory_total_gb=mem.get("total_gb", 0.0),
                memory_used_gb=mem.get("used_gb", 0.0),
                memory_free_gb=mem.get("free_gb", 0.0),
                memory_percent=mem.get("percent", 0.0),
                disk_total_gb=disk.get("total_gb", 0.0),
                disk_used_gb=disk.get("used_gb", 0.0),
                disk_free_gb=disk.get("free_gb", 0.0),
                disk_percent=disk.get("percent", 0.0),
                disk_read_mb=disk.get("read_mb", 0.0),
                disk_write_mb=disk.get("write_mb", 0.0),
                net_sent_mb=net.get("sent_mb", 0.0),
                net_recv_mb=net.get("recv_mb", 0.0),
                process_count=proc.get("count", 0),
                thread_count=proc.get("threads", 0),
                temperature_celsius=res.get("temperature"),
                load_avg_1min=load.get("1min"),
                load_avg_5min=load.get("5min"),
                load_avg_15min=load.get("15min"),
                health_score=res.get("health_score", 0.0),
                health_status=res.get("health_status", "unknown"),
            )
        if "tools" in data:
            snapshot.tools = ToolInfo(**data["tools"])
        if "health" in data:
            snapshot.health = HealthInfo(**data["health"])
        if "services" in data:
            # Import here to avoid circular imports
            from app.services.external_registry import ServiceMetadata
            snapshot.services = [ServiceMetadata.from_dict(service_data) for service_data in data["services"]]

        return snapshot

    def get_summary_text(self) -> str:
        """Get a human-readable summary of the snapshot."""
        lines = [
            f"=== Environment Snapshot ({self.snapshot_id}) ===",
            f"Time: {self.timestamp}",
            f"Collection time: {self.elapsed_ms:.1f}ms",
            "",
            f"Project: {self.project.name or 'Unknown'} ({self.project.root_path})",
            f"  Language: {self.project.main_language}",
            f"  Files: {self.project.file_count}, Lines: {self.project.total_lines}",
            f"  Build: {self.project.build_system}, Framework: {self.project.framework}",
            f"  Git: {'Yes' if self.project.is_git_repo else 'No'}",
            "",
            f"Runtime: {self.runtime.os_name} ({self.runtime.os_family})",
            f"  Shell: {self.runtime.shell_name}",
            f"  Python: {self.runtime.python_version} ({self.runtime.python_executable})",
            f"  CWD: {self.runtime.working_directory}",
            "",
            f"Git: {self.git.current_branch or 'N/A'}",
            f"  Clean: {'Yes' if self.git.is_clean else 'No'}",
            f"  Ahead: {self.git.ahead}, Behind: {self.git.behind}",
            "",
            f"Resources: CPU {self.resources.cpu_percent:.0f}% / Mem {self.resources.memory_percent:.0f}% / Disk {self.resources.disk_percent:.0f}%",
            f"  Health: {self.resources.health_status} ({self.resources.health_score:.0f}/100)",
        ]

        # Add GPU info
        if self.resources.gpu_count > 0:
            lines.append(f"  GPUs: {self.resources.gpu_count} (Driver: {self.resources.gpu_driver_version})")
            for vendor, count in self.resources.gpu_by_vendor.items():
                lines.append(f"    {vendor}: {count}")
            for gpu in self.resources.gpu_devices:
                util = gpu.get('utilization_percent', 0)
                mem = gpu.get('memory_percent', 0)
                temp = gpu.get('temperature_celsius')
                temp_str = f", {temp:.0f}C" if temp else ""
                lines.append(f"    [{gpu['index']}] {gpu['name']} (Vendor: {gpu['vendor']}) - GPU: {util:.0f}%, Mem: {mem:.0f}%{temp_str}")

        lines.extend([
            "",
            f"Tools: {len(self.tools.available_tools)} available",
            f"  Git: {'Yes' if self.tools.git_available else 'No'}",
            f"  Python: {'Yes' if self.tools.python_available else 'No'}",
            f"  Node: {'Yes' if self.tools.node_available else 'No'}",
            f"  Docker: {'Yes' if self.tools.docker_available else 'No'}",
            "",
            f"Project Health: {self.health.overall_status} ({self.health.health_score:.0f}/100)",
            f"  Code Quality: {len(self.health.code_quality)} metrics",
            f"  Tests: {len(self.health.test_metrics)} metrics",
            f"  Performance: {len(self.health.performance_metrics)} metrics",
        ])
        return "\n".join(lines)


class WorldModel:
    """Unified World Model facade for Freya's operating environment.

    This class provides a single entry point for retrieving environment state,
    coordinating all existing environment components (RuntimeContext, SystemMonitor,
    GitManager, ProjectIndex, ToolManager, HealthMonitor) without replacing them.

    Usage:
        world_model = create_world_model(workspace=".")
        snapshot = world_model.get_snapshot()
        task_context = world_model.get_relevant_context("build")
    """

    def __init__(
        self,
        workspace: str = ".",
        system_monitor: Optional["SystemMonitor"] = None,
        process_monitor: Optional["ProcessMonitor"] = None,
        git_manager: Optional["GitManager"] = None,
        tool_manager: Optional["ToolManager"] = None,
        health_monitor: Optional["HealthMonitor"] = None,
        project_index: Optional["ProjectIndex"] = None,
    ):
        """Initialize the WorldModel with optional component overrides.

        Args:
            workspace: Project workspace directory
            system_monitor: Optional SystemMonitor instance (creates default if None)
            process_monitor: Optional ProcessMonitor instance
            git_manager: Optional GitManager instance (creates default if None)
            tool_manager: Optional ToolManager instance (creates default if None)
            health_monitor: Optional HealthMonitor instance (creates default if None)
            project_index: Optional ProjectIndex instance (creates default if None)
        """
        self.workspace = Path(workspace).resolve()
        self._workspace_str = str(self.workspace)

        # Lazy-initialized components
        self._system_monitor = system_monitor
        self._process_monitor = process_monitor
        self._git_manager = git_manager
        self._tool_manager = tool_manager
        self._health_monitor = health_monitor
        self._project_index = project_index

        # Runtime context (from intent.runtime_context)
        from app.intent.runtime_context import get_runtime_context, RuntimeContext
        self._runtime_context: RuntimeContext = get_runtime_context()

        # Snapshot cache
        self._last_snapshot: Optional[EnvironmentSnapshot] = None
        self._snapshot_cache_ttl: float = 30.0  # seconds
        self._last_snapshot_time: float = 0.0

    # --- Component accessors (lazy initialization) ---

    @property
    def system_monitor(self) -> "SystemMonitor":
        if self._system_monitor is None:
            from app.monitoring.system_monitor import SystemMonitor, MonitorConfig
            self._system_monitor = SystemMonitor(MonitorConfig(workspace=self._workspace_str))
        return self._system_monitor

    @property
    def process_monitor(self) -> "ProcessMonitor":
        if self._process_monitor is None:
            from app.monitoring.process_monitor import ProcessMonitor
            self._process_monitor = ProcessMonitor(self._workspace_str)
        return self._process_monitor

    @property
    def git_manager(self) -> "GitManager":
        if self._git_manager is None:
            from app.git.git_manager import GitManager
            self._git_manager = GitManager(workspace=self._workspace_str)
        # Sync branch info
        try:
            self._git_manager._load_config()
        except Exception:
            pass
        return self._git_manager

    @property
    def tool_manager(self) -> "ToolManager":
        if self._tool_manager is None:
            from app.core.tool_manager import ToolManager
            self._tool_manager = ToolManager(self._workspace_str)
        return self._tool_manager

    @property
    def health_monitor(self) -> "HealthMonitor":
        if self._health_monitor is None:
            from app.health.health_monitor import HealthMonitor
            self._health_monitor = HealthMonitor(workspace=self._workspace_str)
        return self._health_monitor

    @property
    def project_index(self) -> "ProjectIndex":
        if self._project_index is None:
            from app.core.project_index import ProjectIndex
            self._project_index = ProjectIndex(self._workspace_str)
            self._project_index.build()
        return self._project_index

    @property
    def project_metadata(self) -> "ProjectMetadata":
        """Get project metadata (cached)."""
        if not hasattr(self, '_project_metadata') or self._project_metadata is None:
            from app.world_model.project_metadata import detect_project_metadata
            self._project_metadata = detect_project_metadata(self._workspace_str)
        return self._project_metadata

    @property
    def project_dependencies(self) -> "DependencySet":
        """Get project dependencies (cached)."""
        if not hasattr(self, '_project_dependencies') or self._project_dependencies is None:
            from app.world_model.project_metadata import detect_dependencies
            self._project_dependencies = detect_dependencies(self._workspace_str)
        return self._project_dependencies

    def get_full_project_data(self) -> "ProjectDependencies":
        """Get full project data including metadata and all dependencies."""
        from app.world_model.project_metadata import ProjectDependencies
        return ProjectDependencies(
            metadata=self.project_metadata,
            dependencies=self.project_dependencies,
        )

    def get_project_context(self, task_type: str = "unknown") -> Dict[str, Any]:
        """Get relevant project context for a task type."""
        return self.get_full_project_data().get_context_for_task(task_type)

    # --- Public API ---

    def get_snapshot(self, force_refresh: bool = False) -> EnvironmentSnapshot:
        """Get a complete environment snapshot.

        Args:
            force_refresh: If True, bypass cache and collect fresh data.

        Returns:
            EnvironmentSnapshot with all environment layers.
        """
        start_time = time.perf_counter()
        now = time.time()

        # Check cache
        if not force_refresh and self._last_snapshot is not None:
            if (now - self._last_snapshot_time) < self._snapshot_cache_ttl:
                logger.debug("[WorldModel] Returning cached snapshot")
                return self._last_snapshot

        logger.info("[WorldModel] Collecting environment snapshot...")

        snapshot = EnvironmentSnapshot()

        # Collect all layers
        snapshot.project = self._collect_project_info()
        snapshot.runtime = self._collect_runtime_info()
        snapshot.git = self._collect_git_info()
        snapshot.resources = self._collect_resource_info()
        snapshot.tools = self._collect_tool_info()
        snapshot.health = self._collect_health_info()
        snapshot.services = self._collect_service_info()

        snapshot.elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Update cache
        self._last_snapshot = snapshot
        self._last_snapshot_time = now

        logger.info(f"[WorldModel] Snapshot collected in {snapshot.elapsed_ms:.1f}ms")
        return snapshot

    def refresh(self) -> EnvironmentSnapshot:
        """Force refresh and return new snapshot."""
        return self.get_snapshot(force_refresh=True)

    def get_relevant_context(self, task_type: str) -> EnvironmentSnapshot:
        """Get a filtered snapshot containing only information relevant to a task type.

        Args:
            task_type: Type of task (e.g., "build", "test", "deploy", "debug", "refactor")

        Returns:
            Filtered EnvironmentSnapshot with only relevant fields populated.
        """
        from app.world_model.retrieval import filter_snapshot_for_task
        full_snapshot = self.get_snapshot()
        return filter_snapshot_for_task(full_snapshot, task_type)

    # --- Lightweight helper methods ---

    def get_project_info(self) -> ProjectInfo:
        """Get project information only."""
        return self._collect_project_info()

    def get_git_status(self) -> GitInfo:
        """Get git status only."""
        return self._collect_git_info()

    def get_resource_summary(self) -> ResourceInfo:
        """Get system resource summary only."""
        return self._collect_resource_info()

    def get_available_tools(self) -> ToolInfo:
        """Get available tools only."""
        return self._collect_tool_info()

    def get_health_status(self) -> HealthInfo:
        """Get health status only."""
        return self._collect_health_info()

    def get_runtime_context(self) -> RuntimeInfo:
        """Get runtime context only."""
        return self._collect_runtime_info()

    def is_healthy(self) -> bool:
        """Quick health check."""
        health = self.get_health_status()
        return health.overall_status in ("excellent", "good", "fair")

    def get_quick_summary(self) -> Dict[str, Any]:
        """Get a quick text summary for LLM context."""
        snapshot = self.get_snapshot()
        gpu_str = ""
        if snapshot.resources.gpu_count > 0:
            gpu_str = f" / GPUs: {snapshot.resources.gpu_count}"
            if snapshot.resources.gpu_by_vendor:
                gpu_str += " (" + ", ".join(f"{k}: {v}" for k, v in snapshot.resources.gpu_by_vendor.items()) + ")"

        lines = [
            f"Project: {snapshot.project.name or 'Unknown'} ({snapshot.project.root_path})",
            f"Git: {snapshot.git.current_branch or 'N/A'} ({'clean' if snapshot.git.is_clean else 'dirty'})",
            f"OS: {snapshot.runtime.os_family} ({snapshot.runtime.shell_name})",
            f"Python: {snapshot.runtime.python_version}",
            f"Resources: CPU {snapshot.resources.cpu_percent:.0f}%, Mem {snapshot.resources.memory_percent:.0f}%, Disk {snapshot.resources.disk_percent:.0f}%{gpu_str}",
            f"Health: {snapshot.health.overall_status} ({snapshot.health.health_score:.0f}/100)",
            f"Tools: {len(snapshot.tools.available_tools)} available",
        ]
        return {"summary": "\n".join(lines), "snapshot_id": snapshot.snapshot_id}

    # --- Private collection methods ---

    def _collect_project_info(self) -> ProjectInfo:
        """Collect project-level information using the enhanced metadata parser."""
        info = ProjectInfo(root_path=self._workspace_str)

        try:
            # Use the new project metadata parser for rich information
            meta = self.project_metadata

            # Basic info
            info.name = meta.name or self.workspace.name
            info.main_language = meta.primary_language
            info.build_system = meta.build_system
            info.framework = meta.framework

            # Check git repo
            info.is_git_repo = self.git_manager.is_repo()

            # Use project index for file stats
            pi = self.project_index
            info.file_count = len(pi.files)

            # Count lines
            total_lines = 0
            for content in pi.files.values():
                total_lines += content.count("\n") + 1
            info.total_lines = total_lines

            # Config files from metadata
            info.config_files = list(meta.raw_config.get("config_files", []))

            # Entry points from metadata
            info.entry_points = meta.entry_points[:10] if meta.entry_points else []

        except Exception as e:
            logger.warning(f"[WorldModel] Error collecting project info: {e}")

        return info

    def _collect_runtime_info(self) -> RuntimeInfo:
        """Collect runtime context from RuntimeContext."""
        rc = self._runtime_context
        return RuntimeInfo(
            os_name=rc.os_name,
            os_version=rc.os_version,
            os_family=rc.os_family,
            shell_name=rc.shell_name,
            shell_path=rc.shell_path or "",
            python_version=rc.python_version,
            python_major=rc.python_major,
            python_minor=rc.python_minor,
            python_patch=rc.python_patch,
            python_executable=rc.python_executable,
            working_directory=rc.working_directory,
            environment=dict(rc.environment),
        )

    def _collect_git_info(self) -> GitInfo:
        """Collect git repository information."""
        gm = self.git_manager

        try:
            if not gm.is_repo():
                return GitInfo(is_repo=False)

            summary = gm.get_summary()
            status = gm.get_status()

            return GitInfo(
                is_repo=True,
                is_clean=summary.get("is_clean", False),
                current_branch=summary.get("current_branch", ""),
                branches=summary.get("branches", []),
                remotes=summary.get("remotes", []),
                status=summary.get("status", {}),
                ahead=status.get("ahead", 0),
                behind=status.get("behind", 0),
                has_changes=summary.get("has_changes", False),
            )
        except Exception as e:
            logger.warning(f"[WorldModel] Error collecting git info: {e}")
            return GitInfo(is_repo=gm.is_repo())

    def _collect_resource_info(self) -> ResourceInfo:
        """Collect system resource metrics."""
        try:
            metrics = self.system_monitor.collect_metrics()

            # Build GPU info
            gpu_devices = []
            for gpu in metrics.gpus:
                gpu_devices.append({
                    "index": gpu.index,
                    "vendor": gpu.vendor,
                    "name": gpu.name,
                    "driver_version": gpu.driver_version,
                    "utilization_percent": gpu.gpu_utilization_percent,
                    "memory_percent": gpu.memory_percent,
                    "temperature_celsius": gpu.temperature_celsius,
                    "power_draw_watts": gpu.power_draw_watts,
                })

            return ResourceInfo(
                cpu_percent=metrics.cpu_percent,
                cpu_count=metrics.cpu_count,
                cpu_freq_mhz=metrics.cpu_freq_mhz,
                memory_total_gb=metrics.memory_total_gb,
                memory_used_gb=metrics.memory_used_gb,
                memory_free_gb=metrics.memory_free_gb,
                memory_percent=metrics.memory_percent,
                disk_total_gb=metrics.disk_total_gb,
                disk_used_gb=metrics.disk_used_gb,
                disk_free_gb=metrics.disk_free_gb,
                disk_percent=metrics.disk_percent,
                disk_read_mb=metrics.disk_read_mb,
                disk_write_mb=metrics.disk_write_mb,
                net_sent_mb=metrics.net_sent_mb,
                net_recv_mb=metrics.net_recv_mb,
                process_count=metrics.process_count,
                thread_count=metrics.thread_count,
                temperature_celsius=metrics.temperature_celsius,
                load_avg_1min=metrics.load_avg_1min,
                load_avg_5min=metrics.load_avg_5min,
                load_avg_15min=metrics.load_avg_15min,
                health_score=metrics.calculate_health_score(),
                health_status=metrics.get_health_status().value,
                gpu_count=metrics.gpu_count,
                gpu_driver_version=metrics.gpu_driver_version,
                gpu_by_vendor=metrics.gpu_by_vendor,
                gpu_devices=gpu_devices,
            )
        except Exception as e:
            logger.warning(f"[WorldModel] Error collecting resource info: {e}")
            return ResourceInfo()

    def _collect_tool_info(self) -> ToolInfo:
        """Collect tool availability and versions."""
        tm = self.tool_manager
        available = list(tm.tools.keys())

        # Check versions of key tools
        versions = {}
        git_available = python_available = node_available = npm_available = docker_available = False

        import shutil
        for tool, version_flag in [
            ("git", "--version"),
            ("python", "--version"),
            ("node", "--version"),
            ("npm", "--version"),
            ("docker", "--version"),
        ]:
            path = shutil.which(tool)
            if path:
                try:
                    result = subprocess.run(
                        [tool, version_flag],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip().split("\n")[0]
                        versions[tool] = version
                        if tool == "git": git_available = True
                        elif tool == "python": python_available = True
                        elif tool == "node": node_available = True
                        elif tool == "npm": npm_available = True
                        elif tool == "docker": docker_available = True
                except Exception:
                    pass

        return ToolInfo(
            available_tools=available,
            tool_versions=versions,
            git_available=git_available,
            python_available=python_available,
            node_available=node_available,
            npm_available=npm_available,
            docker_available=docker_available,
        )

    def _collect_health_info(self) -> HealthInfo:
        """Collect health and diagnostics information."""
        try:
            hm = self.health_monitor
            # Must call check_metrics() first to populate _current_metrics,
            # otherwise get_health_score() returns 0.0 and status is CRITICAL
            hm.check_metrics(include_test_metrics=False)
            summary = hm.get_summary()

            # Get detailed metrics (already collected by check_metrics)
            metrics = hm.get_metrics()

            code_quality = {}
            test_metrics = {}
            performance_metrics = {}

            for name, metric in metrics.items():
                if name in ("total_files", "python_files", "lines_of_code", "pep8_compliance",
                           "docstring_coverage", "type_hint_coverage", "import_structure_score"):
                    code_quality[name] = {"value": metric.value, "status": metric.status.value}
                elif name in ("total_tests", "test_pass_rate", "test_coverage"):
                    test_metrics[name] = {"value": metric.value, "status": metric.status.value}
                elif name in ("indexing_speed", "llm_response_time"):
                    performance_metrics[name] = {"value": metric.value, "status": metric.status.value}

            return HealthInfo(
                overall_status=summary.get("status", "unknown"),
                health_score=summary.get("score", 0.0),
                metrics_count=summary.get("metrics_count", 0),
                alerts_count=summary.get("alerts_count", 0),
                code_quality=code_quality,
                test_metrics=test_metrics,
                performance_metrics=performance_metrics,
            )
        except Exception as e:
            logger.warning(f"[WorldModel] Error collecting health info: {e}")
            return HealthInfo()

    def _collect_service_info(self) -> List[Any]:
        """Collect external services information."""
        try:
            # Import here to avoid circular imports
            from app.services.external_registry import service_registry
            return service_registry.list()
        except Exception as e:
            logger.warning(f"[WorldModel] Error collecting service info: {e}")
            return []


def create_world_model(workspace: str = ".", **components) -> WorldModel:
    """Factory function to create a WorldModel instance.

    Args:
        workspace: Project workspace directory
        **components: Optional component overrides (system_monitor, process_monitor,
                     git_manager, tool_manager, health_monitor, project_index)

    Returns:
        Configured WorldModel instance.
    """
    return WorldModel(workspace=workspace, **components)