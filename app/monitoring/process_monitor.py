"""Process Monitor for tracking individual processes.

This module provides monitoring capabilities for individual processes,
including CPU, memory usage, and status tracking.
"""

import os
import psutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import psutil exceptions
from psutil import AccessDenied, NoSuchProcess


class ProcessStatus(Enum):
    """Status of a process."""
    RUNNING = "running"
    SLEEPING = "sleeping"
    STOPPED = "stopped"
    ZOMBIE = "zombie"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass
class ProcessInfo:
    """Information about a process."""
    pid: int
    name: str
    exe: str
    cmdline: List[str] = field(default_factory=list)
    status: ProcessStatus = ProcessStatus.UNKNOWN
    username: str = ""
    create_time: float = 0.0
    cpu_percent: float = 0.0
    memory_info: Optional[Dict[str, Any]] = None
    memory_percent: float = 0.0
    num_threads: int = 0
    num_fds: int = 0  # Number of file descriptors
    io_counters: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_pid(cls, pid: int) -> "ProcessInfo":
        """Create ProcessInfo from a process ID."""
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                # Get basic info
                name = proc.name()
                exe = proc.exe()
                cmdline = proc.cmdline()

                # Get status
                try:
                    status_str = proc.status()
                    status = ProcessStatus[status_str.upper()]
                except (ValueError, KeyError):
                    status = ProcessStatus.UNKNOWN

                # Get user
                try:
                    username = proc.username()
                except (AccessDenied, NoSuchProcess):
                    username = "unknown"

                # Get create time
                try:
                    create_time = proc.create_time()
                except (AccessDenied, NoSuchProcess):
                    create_time = 0.0

                # Get CPU percent
                try:
                    cpu_percent = proc.cpu_percent(interval=0.1)
                except (AccessDenied, NoSuchProcess):
                    cpu_percent = 0.0

                # Get memory info
                memory_info = None
                memory_percent = 0.0
                try:
                    mem_info = proc.memory_info()
                    memory_info = {
                        "rss": mem_info.rss,
                        "vms": mem_info.vms,
                        "shared": getattr(mem_info, 'shared', 0),
                        "text": getattr(mem_info, 'text', 0),
                        "lib": getattr(mem_info, 'lib', 0),
                        "data": getattr(mem_info, 'data', 0),
                        "dirty": getattr(mem_info, 'dirty', 0),
                    }
                    memory_percent = proc.memory_percent()
                except (AccessDenied, NoSuchProcess):
                    pass

                # Get thread count
                try:
                    num_threads = proc.num_threads()
                except (AccessDenied, NoSuchProcess):
                    num_threads = 0

                # Get file descriptor count (not available on Windows)
                try:
                    num_fds = proc.num_fds()
                except (AccessDenied, NoSuchProcess, AttributeError, OSError):
                    num_fds = 0

                # Get I/O counters
                io_counters = None
                try:
                    io = proc.io_counters()
                    io_counters = {
                        "read_count": io.read_count,
                        "write_count": io.write_count,
                        "read_bytes": io.read_bytes,
                        "write_bytes": io.write_bytes,
                    }
                except (AccessDenied, NoSuchProcess):
                    pass

                return cls(
                    pid=pid,
                    name=name,
                    exe=exe,
                    cmdline=cmdline,
                    status=status,
                    username=username,
                    create_time=create_time,
                    cpu_percent=cpu_percent,
                    memory_info=memory_info,
                    memory_percent=memory_percent,
                    num_threads=num_threads,
                    num_fds=num_fds,
                    io_counters=io_counters,
                )
        except psutil.NoSuchProcess:
            return cls(
                pid=pid,
                name="unknown",
                exe="",
                status=ProcessStatus.UNKNOWN,
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pid": self.pid,
            "name": self.name,
            "exe": self.exe,
            "cmdline": self.cmdline,
            "status": self.status.value,
            "username": self.username,
            "create_time": self.create_time,
            "cpu_percent": self.cpu_percent,
            "memory_info": self.memory_info,
            "memory_percent": self.memory_percent,
            "num_threads": self.num_threads,
            "num_fds": self.num_fds,
            "io_counters": self.io_counters,
            "timestamp": self.timestamp,
        }

    def is_alive(self) -> bool:
        """Check if the process is still alive."""
        try:
            return psutil.pid_exists(self.pid)
        except Exception:
            return False

    def cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            proc = psutil.Process(self.pid)
            return proc.cpu_percent(interval=0.1)
        except (psutil.NoSuchProcess, AccessDenied):
            return 0.0

    def memory_usage_mb(self) -> float:
        """Get memory usage in MB."""
        if self.memory_info:
            return round(self.memory_info["rss"] / (1024 * 1024), 2)
        return 0.0


class ProcessFilter:
    """Filter for selecting processes to monitor."""

    def __init__(
        self,
        name_patterns: Optional[List[str]] = None,
        username_patterns: Optional[List[str]] = None,
        min_cpu_percent: Optional[float] = None,
        min_memory_mb: Optional[float] = None,
        status_filter: Optional[List[ProcessStatus]] = None,
    ):
        self.name_patterns = name_patterns or []
        self.username_patterns = username_patterns or []
        self.min_cpu_percent = min_cpu_percent
        self.min_memory_mb = min_memory_mb
        self.status_filter = status_filter or []

    def matches(self, proc_info: ProcessInfo) -> bool:
        """Check if a process matches the filter."""
        # Name filter
        if self.name_patterns:
            name_match = any(
                pattern.lower() in proc_info.name.lower()
                for pattern in self.name_patterns
            )
            if not name_match:
                # Also check cmdline
                name_match = any(
                    any(pattern.lower() in arg.lower() for arg in proc_info.cmdline)
                    for pattern in self.name_patterns
                )
            if not name_match:
                return False

        # Username filter
        if self.username_patterns:
            if not any(
                pattern.lower() in proc_info.username.lower()
                for pattern in self.username_patterns
            ):
                return False

        # CPU filter
        if self.min_cpu_percent and proc_info.cpu_percent < self.min_cpu_percent:
            return False

        # Memory filter
        if self.min_memory_mb and proc_info.memory_usage_mb() < self.min_memory_mb:
            return False

        # Status filter
        if self.status_filter and proc_info.status not in self.status_filter:
            return False

        return True


class ProcessMonitor:
    """Monitor for tracking processes.

    This class provides monitoring of individual processes, including
    resource usage tracking and filtering capabilities.
    """

    def __init__(self, workspace: str = "."):
        """Initialize the process monitor.

        Args:
            workspace: The project workspace directory.
        """
        self.workspace = Path(workspace).resolve()
        self._tracked_pids: Dict[int, ProcessInfo] = {}
        self._history: Dict[int, List[ProcessInfo]] = {}
        self._max_history: int = 100

    def get_process(self, pid: int) -> Optional[ProcessInfo]:
        """Get information about a specific process."""
        try:
            return ProcessInfo.from_pid(pid)
        except Exception:
            return None

    def get_processes(self, filter: Optional[ProcessFilter] = None) -> List[ProcessInfo]:
        """Get information about all processes, optionally filtered."""
        processes = []
        for pid in psutil.pids():
            try:
                proc_info = ProcessInfo.from_pid(pid)
                if filter and not filter.matches(proc_info):
                    continue
                processes.append(proc_info)
            except Exception:
                continue
        return processes

    def get_project_processes(self) -> List[ProcessInfo]:
        """Get processes related to the current project."""
        workspace_str = str(self.workspace).lower()
        filter = ProcessFilter(
            name_patterns=["python", "pytest", "node", "npm", "docker"],
        )
        all_processes = self.get_processes(filter)
        project_processes = []

        for proc in all_processes:
            # Check if process is in workspace or has related command line
            if workspace_str in str(proc.exe).lower():
                project_processes.append(proc)
                continue
            if any(workspace_str in arg.lower() for arg in proc.cmdline):
                project_processes.append(proc)
                continue
            # Check if PID is being tracked
            if proc.pid in self._tracked_pids:
                project_processes.append(proc)

        return project_processes

    def start_tracking(self, pid: int) -> bool:
        """Start tracking a specific process."""
        proc_info = self.get_process(pid)
        if proc_info is None:
            return False
        self._tracked_pids[pid] = proc_info
        self._history[pid] = [proc_info]
        return True

    def stop_tracking(self, pid: int) -> None:
        """Stop tracking a specific process."""
        self._tracked_pids.pop(pid, None)
        self._history.pop(pid, None)

    def update_tracked(self) -> None:
        """Update information for all tracked processes."""
        to_remove = []
        for pid, old_info in list(self._tracked_pids.items()):
            new_info = self.get_process(pid)
            if new_info is None:
                to_remove.append(pid)
                continue
            self._tracked_pids[pid] = new_info

            # Add to history
            if pid not in self._history:
                self._history[pid] = []
            self._history[pid].append(new_info)

            # Trim history
            if len(self._history[pid]) > self._max_history:
                self._history[pid] = self._history[pid][-self._max_history:]

        for pid in to_remove:
            self.stop_tracking(pid)

    def get_tracked_processes(self) -> List[ProcessInfo]:
        """Get all currently tracked processes."""
        return list(self._tracked_pids.values())

    def get_process_history(self, pid: int, count: Optional[int] = None) -> List[ProcessInfo]:
        """Get history for a specific process."""
        history = self._history.get(pid, [])
        if count is None:
            return list(history)
        return list(history[-count:])

    def find_high_cpu_processes(self, min_percent: float = 10.0, count: int = 10) -> List[ProcessInfo]:
        """Find processes with highest CPU usage."""
        processes = self.get_processes()
        sorted_processes = sorted(processes, key=lambda p: p.cpu_percent, reverse=True)
        return sorted_processes[:count]

    def find_high_memory_processes(self, count: int = 10) -> List[ProcessInfo]:
        """Find processes with highest memory usage."""
        processes = self.get_processes()
        sorted_processes = sorted(processes, key=lambda p: p.memory_usage_mb(), reverse=True)
        return sorted_processes[:count]

    def kill_process(self, pid: int, force: bool = False) -> bool:
        """Kill a process.

        Args:
            pid: Process ID to kill
            force: If True, force kill (SIGKILL instead of SIGTERM)

        Returns:
            True if process was killed successfully
        """
        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
            return True
        except psutil.NoSuchProcess:
            return False
        except Exception as e:
            print(f"Error killing process {pid}: {e}")
            return False

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of process monitoring."""
        tracked = self.get_tracked_processes()
        return {
            "total_processes": len(psutil.pids()),
            "tracked_count": len(tracked),
            "total_cpu_percent": sum(p.cpu_percent for p in tracked),
            "total_memory_mb": sum(p.memory_usage_mb() for p in tracked),
            "tracked_pids": [p.pid for p in tracked],
        }


