"""Runtime Context Module.

This module provides environment awareness for Freya, detecting the operating
system, shell, Python version, and other runtime information. This context
is included in LLM prompts so the model can generate appropriate commands
for the current environment.
"""

import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from app.core.logger import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.intent.classifier import IntentType, IntentClassification


@dataclass
class RuntimeContext:
    """Runtime context information for Freya.

    Contains information about the operating system, shell, Python version,
    and other runtime details that the LLM needs to know to generate
    appropriate commands.
    """

    # Operating system
    os_name: str  # "Windows", "Linux", "Darwin" (macOS)
    os_version: str
    os_family: str  # "windows", "linux", "macos"

    # Shell information
    shell_name: str  # "cmd", "powershell", "bash", "zsh", "sh", etc.
    shell_path: Optional[str]

    # Python information
    python_version: str
    python_major: int
    python_minor: int
    python_patch: int
    python_executable: str

    # Working directory
    working_directory: str

    # Environment variables (filtered)
    environment: Dict[str, str] = field(default_factory=dict)

    # Additional context
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def detect(cls) -> "RuntimeContext":
        """Detect the runtime context automatically."""
        logger.info("[RuntimeContext] Detecting runtime environment...")
        os_name = platform.system()
        os_version = platform.version()
        os_family = cls._normalize_os_family(os_name)
        shell_name, shell_path = cls._detect_shell()
        python_version = platform.python_version()
        python_major, python_minor, python_patch = cls._parse_python_version(python_version)
        python_executable = sys.executable or "python"
        working_directory = os.getcwd()
        environment = cls._get_filtered_environment()
        context = cls(
            os_name=os_name,
            os_version=os_version,
            os_family=os_family,
            shell_name=shell_name,
            shell_path=shell_path,
            python_version=python_version,
            python_major=python_major,
            python_minor=python_minor,
            python_patch=python_patch,
            python_executable=python_executable,
            working_directory=working_directory,
            environment=environment,
        )
        logger.info(
            f"[RuntimeContext] Detected: OS={os_family}, Shell={shell_name}, "
            f"Python={python_version}, CWD={working_directory}"
        )
        return context

    @staticmethod
    def _normalize_os_family(os_name: str) -> str:
        """Normalize OS name to a consistent family name."""
        os_name_lower = os_name.lower()
        if os_name_lower == "windows":
            return "windows"
        elif os_name_lower == "linux":
            return "linux"
        elif os_name_lower == "darwin":
            return "macos"
        else:
            return os_name_lower

    @staticmethod
    def _detect_shell() -> Tuple[str, Optional[str]]:
        """Detect the current shell."""
        shell = os.environ.get("SHELL", "")
        if platform.system() == "Windows":
            if "POWERSHELL" in os.environ or "PSModulePath" in os.environ:
                return "powershell", shell if shell else None
            if os.environ.get("COMSPEC", ""):
                return "cmd", os.environ.get("COMSPEC")
            return "cmd", None
        if shell:
            shell_name = os.path.basename(shell)
            return shell_name, shell
        try:
            import psutil
            parent = psutil.Process().parent()
            if parent:
                try:
                    proc = psutil.Process(parent.pid)
                    cmdline = " ".join(proc.cmdline())
                    if "powershell" in cmdline.lower():
                        return "powershell", cmdline.split()[0]
                    elif "bash" in cmdline.lower():
                        return "bash", cmdline.split()[0]
                    elif "zsh" in cmdline.lower():
                        return "zsh", cmdline.split()[0]
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass
        if platform.system() != "Windows":
            return "bash", "/bin/bash"
        return "unknown", None

    @staticmethod
    def _parse_python_version(version: str) -> Tuple[int, int, int]:
        """Parse Python version string into major, minor, patch."""
        parts = version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 3
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = 0
        if len(parts) > 2:
            # Extract numeric prefix, handling versions like "3.11.0a1" -> 0
            patch_part = parts[2]
            numeric = ""
            for c in patch_part:
                if c.isdigit():
                    numeric += c
                else:
                    break
            patch = int(numeric) if numeric else 0
        return (major, minor, patch)

    @staticmethod
    def _get_filtered_environment() -> Dict[str, str]:
        """Get filtered environment variables for context."""
        safe_vars = [
            "PATH", "HOME", "USER", "USERNAME", "PWD",
            "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
            "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
            "OLLAMA_MODEL", "OLLAMA_BASE_URL",
            "DEFAULT_PROVIDER", "MODEL",
        ]
        env = {}
        for var in safe_vars:
            if var in os.environ:
                env[var] = os.environ[var]
        return env

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
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
            "extra": self.extra,
        }

    def get_system_prompt_suffix(self) -> str:
        """Get a system prompt suffix with runtime context."""
        lines = [
            "",
            "=== RUNTIME CONTEXT ===",
            f"Operating System: {self.os_name} ({self.os_family})",
            f"Shell: {self.shell_name}",
            f"Python: {self.python_version} ({self.python_executable})",
            f"Working Directory: {self.working_directory}",
        ]
        if self.environment.get("OLLAMA_MODEL"):
            lines.append(f"Ollama Model: {self.environment['OLLAMA_MODEL']}")
        if self.environment.get("DEFAULT_PROVIDER"):
            lines.append(f"Default Provider: {self.environment['DEFAULT_PROVIDER']}")
        return "\n".join(lines)

    def get_command_hint(self) -> str:
        """Get a hint for generating appropriate commands."""
        if self.os_family == "windows":
            if self.shell_name == "powershell":
                return (
                    "Use PowerShell commands. Example: 'Get-ChildItem' instead of 'ls', "
                    "'Test-NetConnection -Count 4 google.com' instead of 'ping -c 4 google.com'"
                )
            else:
                return "Use Windows CMD commands. Example: 'dir' instead of 'ls', 'ping google.com' (no -c flag)"
        else:
            return "Use Unix/Linux commands. Example: 'ls', 'ping -c 4 google.com'"

    def is_windows(self) -> bool:
        """Check if running on Windows."""
        return self.os_family == "windows"

    def is_linux(self) -> bool:
        """Check if running on Linux."""
        return self.os_family == "linux"

    def is_macos(self) -> bool:
        """Check if running on macOS."""
        return self.os_family == "macos"

    def __repr__(self) -> str:
        """String representation."""
        return f"RuntimeContext(os={self.os_family}, shell={self.shell_name}, python={self.python_version})"

    def should_include_for_intent(self, intent_type: "IntentType") -> bool:
        """Check if runtime context should be included for a given intent type.

        Runtime context is only included for engineering-related intents where
        it helps generate appropriate commands for the current environment.

        Args:
            intent_type: The IntentType to check.

        Returns:
            True if runtime context should be included for this intent type.
        """
        return intent_type.is_engineering


# Global runtime context instance
_global_context: Optional[RuntimeContext] = None


def get_runtime_context() -> RuntimeContext:
    """Get the global runtime context.

    Creates and caches the context on first access.
    """
    global _global_context
    if _global_context is None:
        _global_context = RuntimeContext.detect()
    return _global_context


def set_runtime_context(context: RuntimeContext) -> None:
    """Set the global runtime context."""
    global _global_context
    _global_context = context
    logger.info(f"[RuntimeContext] Global context set: {context}")


def reset_runtime_context() -> None:
    """Reset the global runtime context to None."""
    global _global_context
    _global_context = None
    logger.info("[RuntimeContext] Global context reset")
