"""Capability Handlers.

These handlers provide direct answers to user queries about runtime state,
configuration, and system information without invoking the LLM.

Each handler returns a CapabilityResult with structured data that can be
formatted into natural language responses.
"""

import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.capabilities.router import Capability, CapabilityResult, router
from app.core.config import config
from app.core.logger import logger
from app.intent.runtime_context import get_runtime_context
from app.providers.health import ProviderHealthChecker
from app.providers.factory import ProviderFactory
from app.memory.goals.manager import GoalStorage
from app.memory.task_memory import create_task_memory
from pathlib import Path


# =============================================================================
# Router-facing wrapper handlers (thin wrappers around existing implementations)
# =============================================================================

def handle_show_capabilities(ctx: Dict[str, Any]) -> CapabilityResult:
    """Show all registered capabilities."""
    caps = router.get_capabilities()
    cap_details = []
    for name in caps:
        cap = router.get_capability(name)
        if cap:
            cap_details.append({
                "name": name,
                "description": cap.description,
                "keywords": cap.keywords,
            })
    return CapabilityResult(
        success=True,
        data={
            "count": len(cap_details),
            "capabilities": cap_details,
        },
        message=f"Found {len(cap_details)} registered capabilities",
    )


def handle_show_memory(ctx: Dict[str, Any]) -> CapabilityResult:
    """Show memory contents."""
    try:
        workspace = Path.cwd()
        # Check if memory directory exists
        memory_dir = workspace / "data" / "memory"
        has_memory_dir = memory_dir.exists()
        return CapabilityResult(
            success=True,
            data={
                "memory_root": str(memory_dir),
                "has_memory_dir": has_memory_dir,
            },
            message="Memory system is available" if has_memory_dir else "Memory directory not found",
        )
    except Exception as e:
        logger.debug(f"[handle_show_memory] Error: {e}")
        return CapabilityResult(
            success=False,
            message=f"Error showing memory: {e}",
        )


def handle_show_goals(ctx: Dict[str, Any]) -> CapabilityResult:
    """Show current goals."""
    try:
        workspace = Path.cwd()
        storage = GoalStorage(workspace=str(workspace))
        goals = storage.all()
        
        goal_list = []
        for goal in goals:
            goal_list.append({
                "id": goal.id,
                "name": goal.name,
                "description": goal.description,
                "status": goal.status,
                "priority": goal.priority,
                "created_at": goal.created_at,
                "updated_at": goal.updated_at,
            })
        
        active_id = storage.active_goal_id
        
        return CapabilityResult(
            success=True,
            data={
                "goals": goal_list,
                "active_goal_id": active_id,
                "count": len(goal_list),
            },
            message=f"Found {len(goal_list)} goals" + (f" (active: {active_id})" if active_id else ""),
        )
    except Exception as e:
        logger.debug(f"[handle_show_goals] Error: {e}")
        return CapabilityResult(
            success=False,
            message=f"Error showing goals: {e}",
        )


def handle_show_tasks(ctx: Dict[str, Any]) -> CapabilityResult:
    """Show active/planned tasks."""
    try:
        workspace = Path.cwd()
        task_memory = create_task_memory(workspace=str(workspace))
        
        all_tasks = task_memory.get_all_tasks()
        active_task = task_memory.get_active_task()
        
        task_list = []
        for task in all_tasks:
            progress = task.get_progress()
            task_list.append({
                "task_id": task.task_id,
                "description": task.description,
                "status": task.status,
                "progress": progress,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            })
        
        return CapabilityResult(
            success=True,
            data={
                "tasks": task_list,
                "active_task_id": active_task.task_id if active_task else None,
                "count": len(task_list),
            },
            message=f"Found {len(task_list)} tasks" + (f" (active: {active_task.task_id})" if active_task else ""),
        )
    except Exception as e:
        logger.debug(f"[handle_show_tasks] Error: {e}")
        return CapabilityResult(
            success=False,
            message=f"Error showing tasks: {e}",
        )


# Thin wrapper handlers that delegate to existing implementations

def handle_python_version(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_python_version."""
    return CapabilityResult(
        success=True,
        data=get_python_version(),
        message="Python version retrieved successfully",
    )


def handle_os_info(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_os_info."""
    return CapabilityResult(
        success=True,
        data=get_os_info(),
        message="OS information retrieved successfully",
    )


def handle_current_time(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for getting current time."""
    from datetime import datetime
    return CapabilityResult(
        success=True,
        data={
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time_only": datetime.now().strftime("%H:%M:%S"),
            "timestamp": datetime.now().isoformat(),
        },
        message="Current time retrieved successfully",
    )


def handle_working_directory(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_working_directory."""
    return CapabilityResult(
        success=True,
        data=get_working_directory(),
        message="Working directory retrieved successfully",
    )


def handle_current_model(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_current_model."""
    return CapabilityResult(
        success=True,
        data=get_current_model(),
        message="Current model retrieved successfully",
    )


def handle_ollama_status(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_ollama_status."""
    return CapabilityResult(
        success=True,
        data=get_ollama_status(),
        message="Ollama status retrieved successfully",
    )


def handle_git_status(ctx: Dict[str, Any]) -> CapabilityResult:
    """Wrapper for get_git_status."""
    return CapabilityResult(
        success=True,
        data=get_git_status(),
        message="Git status retrieved successfully",
    )


def get_ollama_status() -> Dict[str, Any]:
    """Get Ollama server status and model information."""
    checker = ProviderHealthChecker()

    try:
        # Check Ollama provider health
        model = config.model or "unknown"
        base_url = "http://localhost:11434"
        result = checker.check_provider(provider_name="ollama", model=model, base_url=base_url)

        # Try to get provider info
        try:
            provider = ProviderFactory.create("ollama", model=model, base_url=base_url)
            model = provider.model or model
            base_url = provider.base_url or base_url
        except Exception:
            pass

        return {
            "connected": result.is_reachable,
            "healthy": result.is_healthy,
            "model_available": result.model_available,
            "provider": "ollama",
            "model": model,
            "base_url": base_url,
            "error": result.error_message,
        }
    except Exception as e:
        logger.debug(f"[OllamaCapability] Error checking status: {e}")
        return {
            "connected": False,
            "healthy": False,
            "model_available": False,
            "provider": "ollama",
            "model": config.model or "unknown",
            "base_url": "http://localhost:11434",
            "error": str(e),
        }
def get_provider_info() -> Dict[str, Any]:
    """Get information about the current LLM provider."""
    return {
        "default_provider": ProviderFactory.get_default_provider(),
        "providers": ProviderFactory.get_registered_providers(),
    }


def get_current_model() -> Dict[str, Any]:
    """Get information about the current model."""
    try:
        # Get model from config first for efficiency
        model = config.model or "unknown"
        provider = ProviderFactory.create(ProviderFactory.get_default_provider(), model=model)
        return {
            "provider": ProviderFactory.get_default_provider(),
            "model": provider.model or model,
        }
    except Exception as e:
        logger.debug(f"[ModelCapability] Error getting model: {e}")
        return {
            "provider": ProviderFactory.get_default_provider(),
            "model": config.model or "unknown",
        }


def _is_git_auth_error(stderr: str) -> bool:
    """Check if the git error is an authentication failure."""
    auth_error_patterns = [
        "认证失败",  # Chinese
        "authentication failed",
        "permission denied",
        "access denied",
        "not authorized",
        "authentication required",
        "credentials required",
        "permission to",  # e.g., "Permission to user/repo.git denied"
        "remote: invalid",
        "fatal: authentication",
        "fatal: could not read",
        "no such device or address",  # SSH connection refused
    ]
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in auth_error_patterns)


def _get_git_error_message(stderr: str) -> str:
    """Get a user-friendly error message for git failures.

    Never exposes credentials in the error message.
    """
    if not stderr:
        return "Git operation failed"

    stderr_lower = stderr.lower()

    # Authentication failures
    if _is_git_auth_error(stderr):
        return (
            "Git authentication failed. "
            "Please ensure you have the correct credentials configured. "
            "Use 'git config --global user.name' and 'git config --global user.email' "
            "for local commits, or configure your SSH/HTTPS credentials for remote operations."
        )

    # Common error patterns
    if "not a git repository" in stderr_lower:
        return "Not a git repository"
    if "fatal:" in stderr_lower:
        # Extract the message after "fatal:" but sanitize it
        for line in stderr.split("\n"):
            if "fatal:" in line.lower():
                msg = line.split("fatal:", 1)[-1].strip()
                # Remove any potential credential info
                msg = msg.replace("//", "/")  # Remove protocol info
                return f"Git error: {msg}"

    return f"Git operation failed: {stderr.strip()[:200]}"


def get_git_status() -> Dict[str, Any]:
    """Get Git repository status for the current directory."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            # Parse porcelain output
            changes = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    status_code = line[:2]
                    file_path = line[3:]
                    changes.append({
                        "status": status_code,
                        "file": file_path,
                        "interpreted": interpret_git_status(status_code),
                    })

            # Get branch info
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

            # Check if repo is clean
            is_clean = len(changes) == 0

            return {
                "is_git_repo": True,
                "branch": branch,
                "is_clean": is_clean,
                "changes": changes,
                "changes_count": len(changes),
            }
        else:
            # Check for authentication errors in stderr
            error_msg = _get_git_error_message(result.stderr)
            return {
                "is_git_repo": False,
                "error": error_msg,
            }
    except FileNotFoundError:
        return {
            "is_git_repo": False,
            "error": "Git is not installed",
        }
    except subprocess.TimeoutExpired:
        return {
            "is_git_repo": False,
            "error": "Git command timed out",
        }
    except Exception as e:
        logger.debug(f"[GitCapability] Error checking status: {e}")
        return {
            "is_git_repo": False,
            "error": str(e),
        }


def interpret_git_status(code: str) -> str:
    """Interpret Git porcelain status code."""
    status_map = {
        "??": "untracked",
        "A ": "added to index",
        "AM": "added to index (modified)",
        "AD": "added to index (deleted)",
        " M": "modified",
        "MM": "modified (both index and working tree)",
        "MD": "modified (deleted in working tree)",
        " D": "deleted",
        " R": "renamed",
        " C": "copied",
        "!!": "ignored",
    }
    return status_map.get(code, "unknown")


def get_python_version() -> Dict[str, Any]:
    """Get Python version information."""
    return {
        "version": platform.python_version(),
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
        "executable": sys.executable,
        "implementation": platform.python_implementation(),
    }


def get_os_info() -> Dict[str, Any]:
    """Get operating system information."""
    return {
        "name": platform.system(),
        "version": platform.version(),
        "release": platform.release(),
        "family": get_os_family(),
    }


def get_os_family() -> str:
    """Get normalized OS family name."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    elif system == "darwin":
        return "macos"
    return system


def get_shell_info() -> Dict[str, Any]:
    """Get shell information."""
    runtime_context = get_runtime_context()
    return {
        "shell": runtime_context.shell_name,
        "shell_path": runtime_context.shell_path,
    }


def get_working_directory() -> Dict[str, Any]:
    """Get current working directory."""
    return {
        "path": os.getcwd(),
        "exists": os.path.exists(os.getcwd()),
    }


def get_internet_connectivity() -> Dict[str, Any]:
    """Check internet connectivity."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "8.8.8.8"], # Google DNS
            capture_output=True,
            text=True,
            timeout=3,
        )
        if platform.system().lower() == "windows":
            # Windows uses different ping syntax
            result = subprocess.run(
                ["ping", "-n", "1", "8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        return {
            "connected": result.returncode == 0,
        }
    except Exception as e:
        logger.debug(f"[ConnectivityCapability] Error checking connectivity: {e}")
        return {
            "connected": False,
            "error": str(e),
        }


def get_running_processes() -> Dict[str, Any]:
    """Get information about running processes."""
    try:
        if platform.system().lower() == "windows":
            result = subprocess.run(
                ["tasklist"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            processes = []
            for line in result.stdout.split("\n")[3:]:
                parts = [p for p in line.split(" ") if p.strip()]
                if len(parts) >= 4:
                    processes.append({
                        "name": parts[0],
                        "pid": parts[1],
                        "memory": parts[4] if len(parts) > 4 else None,
                    })
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            processes = []
            for line in result.stdout.split("\n")[1:]:
                parts = [p for p in line.split(None) if p]
                if len(parts) >= 11:
                    processes.append({
                        "user": parts[0],
                        "pid": parts[1],
                        "cpu": parts[2],
                        "memory": parts[3],
                        "command": " ".join(parts[10:]),
                    })

        return {
            "count": len(processes),
            "processes": processes[:20], # Limit to first 20
        }
    except Exception as e:
        logger.debug(f"[ProcessesCapability] Error getting processes: {e}")
        return {
            "count": 0,
            "processes": [],
            "error": str(e),
        }


def get_memory_usage() -> Dict[str, Any]:
    """Get system memory usage."""
    try:
        if platform.system().lower() == "windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            total = ctypes.c_ulonglong()
            free = ctypes.c_ulonglong()
            kernel32.GlobalMemoryStatusEx(ctypes.byref(total), ctypes.byref(free))
            return {
                "total_gb": round(total.value / (1024 ** 3), 2),
                "free_gb": round(free.value / (1024 ** 3), 2),
                "used_gb": round((total.value - free.value) / (1024 ** 3), 2),
                "usage_percent": round(100 - (free.value / total.value * 100), 1) if total.value > 0 else 0,
            }
        else:
            # Linux/Mac
            with open("/proc/meminfo", "r") as f:
                meminfo = f.read()

            def get_value(key):
                for line in meminfo.split("\n"):
                    if line.startswith(key):
                        return int(line.split()[1])
                return 0

            total = get_value("MemTotal:")
            free = get_value("MemFree:")
            available = get_value("MemAvailable:") if "MemAvailable:" in meminfo else free

            return {
                "total_gb": round(total / (1024 ** 2), 2),
                "free_gb": round(free / (1024 ** 2), 2),
                "available_gb": round(available / (1024 ** 2), 2),
                "usage_percent": round(100 - (available / total * 100), 1) if total > 0 else 0,
            }
    except Exception as e:
        logger.debug(f"[MemoryCapability] Error getting memory usage: {e}")
        return {
            "error": str(e),
        }


def get_disk_usage() -> Dict[str, Any]:
    """Get disk usage for the current directory."""
    try:
        import shutil
        cwd = os.getcwd()
        total, used, free = shutil.disk_usage(cwd)
        return {
            "path": cwd,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "usage_percent": round(used / total * 100, 1) if total > 0 else 0,
        }
    except ImportError:
        # shutil.disk_usage available in Python 3.3+
        try:
            total = os.statvfs(os.getcwd())
            block_size = total.f_frsize
            total_space = block_size * total.f_blocks
            free_space = block_size * total.f_bfree
            used_space = total_space - free_space
            return {
                "path": os.getcwd(),
                "total_gb": round(total_space / (1024 ** 3), 2),
                "used_gb": round(used_space / (1024 ** 3), 2),
                "free_gb": round(free_space / (1024 ** 3), 2),
                "usage_percent": round(used_space / total_space * 100, 1) if total_space > 0 else 0,
            }
        except Exception:
            return {"error": "Unable to determine disk usage"}
    except Exception as e:
        logger.debug(f"[DiskCapability] Error getting disk usage: {e}")
        return {
            "error": str(e),
        }


# =============================================================================
# System Status Handler (aggregates runtime, ollama, git)
# =============================================================================


def handle_system_status(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle system status query - returns aggregated system health."""
    from app.intent.runtime_context import get_runtime_context

    runtime = get_runtime_context().to_dict()
    ollama = get_ollama_status()
    git = get_git_status()

    data = {
        "runtime": runtime,
        "ollama": ollama,
        "git": git,
    }

    # Determine if system is healthy
    is_healthy = (
        ollama.get("healthy", False) and
        git.get("is_git_repo", False) is not False
    )

    return CapabilityResult(
        success=True,
        data=data,
        message="System status retrieved successfully" if is_healthy else "System status retrieved (some components unavailable)",
    )


# =============================================================================
# Runtime Capability Handler
# =============================================================================

class RuntimeCapabilityHandler:
    """Handles capabilities related to runtime environment and system information."""

    @staticmethod
    def register(router: "CapabilityRouter") -> None:
        """Register runtime capabilities with the router.

        Args:
            router: The CapabilityRouter to register with.
        """
        # Python version
        router.register(Capability(
            name="python_version",
            description="Get Python version information",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_python_version(),
                message="Python version retrieved successfully",
            ),
            patterns=[
                r"python\s+version",
                r"what.*python",
                r"which.*python",
            ],
            keywords=["python", "py"],
            intent_types=["system_status"],
        ))

        # Operating system
        router.register(Capability(
            name="os_info",
            description="Get operating system information",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_os_info(),
                message="OS information retrieved successfully",
            ),
            patterns=[
                r"os\s+version",
                r"operating\s+system",
                r"what.*os",
                r"what.*operating.*system",
            ],
            keywords=["os", "operating system", "platform", "windows", "linux", "macos"],
            intent_types=["system_status"],
        ))

        # Shell
        router.register(Capability(
            name="shell_info",
            description="Get shell information",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_shell_info(),
                message="Shell information retrieved successfully",
            ),
            patterns=[
                r"shell",
                r"what.*shell",
                r"current.*shell",
            ],
            keywords=["shell", "terminal", "bash", "powershell", "cmd", "zsh"],
            intent_types=["system_status"],
        ))

        # Working directory
        router.register(Capability(
            name="working_directory",
            description="Get current working directory",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_working_directory(),
                message="Working directory retrieved successfully",
            ),
            patterns=[
                r"current.*directory",
                r"working.*directory",
                r"pwd",
                r"where.*am.*i",
                r"what.*directory",
            ],
            keywords=["directory", "pwd", "cwd", "path", "location"],
            intent_types=["system_status"],
        ))

        # Memory usage
        router.register(Capability(
            name="memory_usage",
            description="Get system memory usage",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_memory_usage(),
                message="Memory usage retrieved successfully",
            ),
            patterns=[
                r"memory\s+usage",
                r"how.*much.*memory",
            ],
            keywords=["memory", "usage"],
            intent_types=["system_status"],
        ))

        # Disk usage
        router.register(Capability(
            name="disk_usage",
            description="Get disk usage",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_disk_usage(),
                message="Disk usage retrieved successfully",
            ),
            patterns=[
                r"disk\s+usage",
                r"disk\s+space",
                r"how.*much.*disk",
            ],
            keywords=["disk", "storage", "space", "usage"],
            intent_types=["system_status"],
        ))

        # Internet connectivity
        router.register(Capability(
            name="internet_connectivity",
            description="Check internet connectivity",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_internet_connectivity(),
                message="Internet connectivity checked successfully",
            ),
            patterns=[
                r"internet\s+connection",
                r"connected\s+to\s+internet",
                r"online",
            ],
            keywords=["internet", "connection", "online", "network", "connected"],
            intent_types=["system_status"],
        ))

        # Running processes
        router.register(Capability(
            name="running_processes",
            description="Get running processes",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_running_processes(),
                message="Running processes retrieved successfully",
            ),
            patterns=[
                r"running\s+processes",
                r"what.*processes",
                r"ps\s+aux",
            ],
            keywords=["processes", "running", "ps", "tasklist"],
            intent_types=["system_status"],
        ))


# =============================================================================
# Ollama Capability Handler
# =============================================================================

class OllamaCapabilityHandler:
    """Handles capabilities related to Ollama provider status."""

    @staticmethod
    def register(router: "CapabilityRouter") -> None:
        """Register Ollama capabilities with the router.

        Args:
            router: The CapabilityRouter to register with.
        """
        # Ollama status
        router.register(Capability(
            name="ollama_status",
            description="Get Ollama server status",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_ollama_status(),
                message="Ollama status retrieved successfully",
            ),
            patterns=[
                r"ollama\s+status",
                r"connected\s+to\s+ollama",
                r"are.*you.*connected.*ollama",
                r"ollama.*running",
                r"ollama.*server",
            ],
            keywords=["ollama", "connected", "connection", "running", "server"],
            intent_types=["system_status"],
        ))

        # Current model
        router.register(Capability(
            name="current_model",
            description="Get current model information",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_current_model(),
                message="Current model retrieved successfully",
            ),
            patterns=[
                r"what.*model.*using",
                r"current.*model",
                r"which.*model",
                r"model\s+name",
                r"what\s+(model|version)\s*(are\s+you|am\s+i)\s*using",
                r"what\s+version\s+are\s+you\s+using",
                r"how many\s+parameters",
                r"model\s+parameters",
                r"parameter\s+count",
            ],
            keywords=["model", "using", "current", "which", "what model", "version", "what version", "parameters", "parameter"],
            intent_types=["system_status"],
        ))

        # Provider info
        router.register(Capability(
            name="provider_info",
            description="Get LLM provider information",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_provider_info(),
                message="Provider information retrieved successfully",
            ),
            patterns=[
                r"provider",
                r"llm\s+provider",
                r"which.*provider",
                r"what.*provider",
            ],
            keywords=["provider", "llm", "using"],
            intent_types=["system_status"],
        ))


# =============================================================================
# Git Capability Handler
# =============================================================================

class GitCapabilityHandler:
    """Handles capabilities related to Git repository status."""

    @staticmethod
    def register(router: "CapabilityRouter") -> None:
        """Register Git capabilities with the router.

        Args:
            router: The CapabilityRouter to register with.
        """
        # Git status
        router.register(Capability(
            name="git_status",
            description="Get Git repository status",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data=get_git_status(),
                message="Git status retrieved successfully",
            ),
            patterns=[
                r"git\s+status",
                r"git\s+repo",
                r"is.*git\s+repo",
                r"am.*in.*git",
            ],
            keywords=["git", "status", "repository", "repo", "branch", "commit"],
            intent_types=["system_status"],
        ))


# =============================================================================
# System Capability Handler (General)
# =============================================================================

class SystemCapabilityHandler:
    """Handles general system status capabilities."""

    @staticmethod
    def register(router: "CapabilityRouter") -> None:
        """Register general system capabilities with the router.

        Args:
            router: The CapabilityRouter to register with.
        """
        # General health/status
        router.register(Capability(
            name="system_health",
            description="Get general system health",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data={
                    "runtime": get_runtime_context().to_dict(),
                    "ollama": get_ollama_status(),
                    "git": get_git_status(),
                },
                message="System health retrieved successfully",
            ),
            patterns=[
                r"system\s+health",
                r"status",
                r"are.*you.*ready",
                r"are.*you.*working",
            ],
            keywords=["status", "health", "ready", "working", "available"],
            intent_types=["system_status"],
        ))

        # Time
        router.register(Capability(
            name="current_time",
            description="Get current time",
            handler=lambda ctx: CapabilityResult(
                success=True,
                data={
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "time_only": datetime.now().strftime("%H:%M:%S"),
                    "timestamp": datetime.now().isoformat(),
                },
                message="Current time retrieved successfully",
            ),
            patterns=[
                r"what.*time",
                r"current.*time",
                r"date",
                r"what.*date",
            ],
            keywords=["time", "date", "now", "current"],
            intent_types=["system_status"],
        ))


# Register all handlers with the global router
RuntimeCapabilityHandler.register(router)
OllamaCapabilityHandler.register(router)
GitCapabilityHandler.register(router)
SystemCapabilityHandler.register(router)


# =============================================================================
# Conversational Control Handler
# =============================================================================

def _get_conversation_control():
    """Get the global conversation control handler."""
    from app.conversational_control import get_conversation_control_handler
    return get_conversation_control_handler()


class ConversationalControlHandler:
    """Handles meta-commands (stop / cancel / undo / redo / status).

    These capabilities short-circuit the normal conversation pipeline and
    return control to the user. See NATURAL_CONVERSATION.md "Conversational
    Control" for semantics.

    Handlers emit a `control_command` data field so a future autonomous runloop
    can pick up the signal without re-classifying the message. Today's runtime
    invoke these handlers synchronously from `FreyaAgent.run`, so the signal
    is also surfaced through the returned CapabilityResult message.
    """

    @staticmethod
    def register(router: "CapabilityRouter") -> None:
        """Register conversational control capabilities with the router.

        Args:
            router: The CapabilityRouter to register with.
        """
        router.register(Capability(
            name="control_stop",
            description="Interrupt the current operation",
            handler=lambda ctx: _handle_control_stop(ctx),
            patterns=[
                r"^\s*stop\s*[!.]?\s*$",
                r"^\s*halt\s*[!.]?\s*$",
                r"^\s*wait\s*[!.]?\s*$",
            ],
            keywords=["stop", "halt", "wait"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_cancel",
            description="Cancel a pending action",
            handler=lambda ctx: _handle_control_cancel(ctx),
            patterns=[
                r"^\s*cancel\s*[!.]?\s*$",
                r"^\s*nevermind\s*[!.]?\s*$",
                r"^\s*abort\s*[!.]?\s*$",
            ],
            keywords=["cancel", "nevermind", "abort"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_pause",
            description="Pause the current operation",
            handler=lambda ctx: _handle_control_pause(ctx),
            patterns=[
                r"^\s*pause\s*[!.]?\s*$",
            ],
            keywords=["pause"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_resume",
            description="Resume a paused operation",
            handler=lambda ctx: _handle_control_resume(ctx),
            patterns=[
                r"^\s*resume\s*[!.]?\s*$",
            ],
            keywords=["resume"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_undo",
            description="Undo the most recent mutation in the current session",
            handler=lambda ctx: _handle_control_undo(ctx),
            patterns=[
                r"^\s*undo\s*[!.]?\s*$",
                r"^\s*revert\s*[!.]?\s*$",
            ],
            keywords=["undo", "revert"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_redo",
            description="Redo the most recently undone mutation",
            handler=lambda ctx: _handle_control_redo(ctx),
            patterns=[
                r"^\s*redo\s*[!.]?\s*$",
            ],
            keywords=["redo"],
            intent_types=["conversational_control"],
        ))

        router.register(Capability(
            name="control_status",
            description="Report the current plan and last completed action",
            handler=lambda ctx: _handle_control_status(ctx),
            patterns=[
                r"^\s*status\s*[!.]?\s*$",
                r"^\s*what\s+are\s+you\s+doing\s*\?\s*$",
                r"^\s*current\s+plan\s*[!.]?\s*$",
                r"^\s*current\s+step\s*[!.]?\s*$",
            ],
            keywords=["status", "what are you doing", "current plan", "current step"],
            intent_types=["conversational_control"],
        ))


def _handle_control_stop(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle stop/halt/wait command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_stop(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Stopped. What's next?"),
        )
    # Fallback if control not initialized
    return CapabilityResult(
        success=True,
        data={"control_command": "stop"},
        message="Stopped. What's next?",
    )


def _handle_control_cancel(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle cancel/nevermind/abort command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_cancel(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Cancelled."),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "cancel"},
        message="Cancelled.",
    )


def _handle_control_pause(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle pause command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_pause(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Paused. Say 'resume' to continue."),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "pause"},
        message="Paused. Say 'resume' to continue.",
    )


def _handle_control_resume(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle resume command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_resume(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Resuming..."),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "resume"},
        message="Nothing to resume. Not currently paused.",
    )


def _handle_control_undo(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle undo command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_undo(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Done. I've undone the last action."),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "undo"},
        message="Nothing to undo in this session.",
    )


def _handle_control_redo(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle redo command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_redo(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "Done. I've reapplied the action."),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "redo"},
        message="Nothing to redo.",
    )


def _handle_control_status(ctx: Dict[str, Any]) -> CapabilityResult:
    """Handle status/what are you doing command."""
    control = _get_conversation_control()
    if control:
        result = control.handle_status(ctx)
        return CapabilityResult(
            success=True,
            data=result,
            message=result.get("message", "I'm ready to help. What would you like me to do?"),
        )
    return CapabilityResult(
        success=True,
        data={"control_command": "status"},
        message="Idle. Waiting for next request.",
    )


# Register the conversational control handler with the global router
ConversationalControlHandler.register(router)



