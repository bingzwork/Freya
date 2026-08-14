"""Response Formatter.

Converts structured capability results into natural language responses.
Hides internal implementation details unless debug mode is enabled.
"""

import json
from typing import Any, Dict, List, Optional, Union

from app.capabilities.router import CapabilityResult, router
from app.core.logger import logger


class ResponseFormatter:
    """Formats capability results into natural language responses."""

    def __init__(self, debug_mode: bool = False):
        self._debug_mode = debug_mode

    @property
    def debug_mode(self) -> bool:
        return self._debug_mode or router.debug_mode

    def format(self, result: CapabilityResult) -> str:
        """Format a capability result into a natural language response.

        Args:
            result: The CapabilityResult to format.

        Returns:
            A formatted natural language string.
        """
        if not result.success:
            return self._format_failure(result)

        return self._format_success(result)

    def _format_success(self, result: CapabilityResult) -> str:
        """Format a successful capability result.

        Args:
            result: The successful CapabilityResult.

        Returns:
            A formatted success response.
        """
        # Route to specific formatters based on capability name
        formatters = {
            "ollama_status": self._format_ollama_status,
            "current_model": self._format_current_model,
            "provider_info": self._format_provider_info,
            "git_status": self._format_git_status,
            "python_version": self._format_python_version,
            "os_info": self._format_os_info,
            "shell_info": self._format_shell_info,
            "working_directory": self._format_working_directory,
            "memory_usage": self._format_memory_usage,
            "disk_usage": self._format_disk_usage,
            "internet_connectivity": self._format_internet_connectivity,
            "running_processes": self._format_running_processes,
            "system_health": self._format_system_health,
            "current_time": self._format_current_time,
            "research_capability": self._format_research_capability,
        }

        formatter = formatters.get(result.capability_name, self._format_generic)
        response = formatter(result)

        # Add debug info if debug mode is enabled
        if self.debug_mode:
            debug_info = self._get_debug_info(result)
            if debug_info:
                response = f"{response}\n\n[Debug: {debug_info}]"

        return response

    def _format_failure(self, result: CapabilityResult) -> str:
        """Format a failed capability result.

        Args:
            result: The failed CapabilityResult.

        Returns:
            A formatted failure response.
        """
        # Keep failure messages simple and user-friendly.
        if result.capability_name == "research_capability":
            return "I couldn't retrieve enough reliable current evidence to answer that."

        message = result.message or "Unable to retrieve that information."

        # Hide implementation details
        hidden_phrases = [
            "Error",
            "Exception",
            "Traceback",
            "FileNotFoundError",
            "subprocess",
            "timeout",
            "import",
            "module",
            "NotImplementedError",
            "AttributeError",
        ]

        for phrase in hidden_phrases:
            message = message.replace(phrase, "")

        message = message.strip(" ,.!")

        if not message:
            message = "Unable to retrieve that information."

        # Add debug info if debug mode is enabled
        if self.debug_mode:
            debug_info = self._get_debug_info(result)
            if debug_info:
                message = f"{message}\n\n[Debug: {debug_info}]"

        return message

    def _get_debug_info(self, result: CapabilityResult) -> str:
        """Get debug information for a result.

        Args:
            result: The CapabilityResult.

        Returns:
            A formatted debug info string.
        """
        parts = []

        if result.capability_name:
            parts.append(f"capability={result.capability_name}")

        if result.execution_time > 0:
            parts.append(f"execution_time={result.execution_time:.3f}s")

        if result.message:
            parts.append(f"message={result.message[:50]}")

        return ", ".join(parts)

    # Specific formatters for each capability

    def _format_ollama_status(self, result: CapabilityResult) -> str:
        """Format Ollama status result."""
        data = result.data or {}

        if data.get("connected"):
            model = data.get("model", "unknown")
            if data.get("healthy"):
                return f"Yes. I'm connected to Ollama and currently using {model}."
            else:
                return f"I'm connected to Ollama at {data.get('base_url', 'localhost')}, but the model {model} may not be available."
        else:
            return "No. I'm not currently connected to Ollama."

    def _format_current_model(self, result: CapabilityResult) -> str:
        """Format current model result."""
        data = result.data or {}
        model = data.get("model", "unknown")
        provider = data.get("provider", "unknown")
        return f"I'm currently using {model} with {provider}."

    def _format_provider_info(self, result: CapabilityResult) -> str:
        """Format provider info result."""
        data = result.data or {}
        default_provider = data.get("default_provider", "unknown")
        providers = data.get("providers", [])

        if len(providers) > 1:
            return f"I'm using {default_provider} as the default provider. Available providers: {', '.join(providers)}."
        else:
            return f"I'm using {default_provider} as the provider."

    def _format_git_status(self, result: CapabilityResult) -> str:
        """Format Git status result."""
        data = result.data or {}

        if not data.get("is_git_repo"):
            return "This is not a Git repository."

        branch = data.get("branch")
        is_clean = data.get("is_clean")
        changes_count = data.get("changes_count", 0)

        if branch:
            if is_clean:
                return f"Yes. This is a Git repository on branch '{branch}' with no uncommitted changes."
            else:
                return f"Yes. This is a Git repository on branch '{branch}' with {changes_count} uncommitted change(s)."
        else:
            if is_clean:
                return "Yes. This is a Git repository with no uncommitted changes."
            else:
                return f"Yes. This is a Git repository with {changes_count} uncommitted change(s)."

    def _format_python_version(self, result: CapabilityResult) -> str:
        """Format Python version result."""
        data = result.data or {}
        version = data.get("version", "unknown")
        return f"Python {version}."

    def _format_os_info(self, result: CapabilityResult) -> str:
        """Format OS info result."""
        data = result.data or {}
        name = data.get("name", "unknown")
        version = data.get("version", "")

        if version:
            return f"{name} {version}."
        return f"{name}."

    def _format_shell_info(self, result: CapabilityResult) -> str:
        """Format shell info result."""
        data = result.data or {}
        shell = data.get("shell", "unknown")
        return f"{shell}."

    def _format_working_directory(self, result: CapabilityResult) -> str:
        """Format working directory result."""
        data = result.data or {}
        path = data.get("path", "unknown")
        return f"{path}."

    def _format_memory_usage(self, result: CapabilityResult) -> str:
        """Format memory usage result."""
        data = result.data or {}

        if "error" in data:
            return "Unable to determine memory usage."

        usage_percent = data.get("usage_percent")
        total = data.get("total_gb")
        used = data.get("used_gb")
        free = data.get("free_gb")

        if usage_percent is not None:
            if total and used:
                return f"Memory usage: {used}GB used of {total}GB ({usage_percent}% usage)."
            return f"Memory usage: {usage_percent}%."
        return "Unable to determine memory usage."

    def _format_disk_usage(self, result: CapabilityResult) -> str:
        """Format disk usage result."""
        data = result.data or {}

        if "error" in data:
            return "Unable to determine disk usage."

        usage_percent = data.get("usage_percent")
        total = data.get("total_gb")
        used = data.get("used_gb")
        free = data.get("free_gb")

        if usage_percent is not None:
            if total and used:
                return f"Disk usage: {used}GB used of {total}GB ({usage_percent}% usage)."
            return f"Disk usage: {usage_percent}%."
        return "Unable to determine disk usage."

    def _format_internet_connectivity(self, result: CapabilityResult) -> str:
        """Format internet connectivity result."""
        data = result.data or {}
        connected = data.get("connected")

        if connected:
            return "Yes. I have internet connectivity."
        else:
            return "No. I don't have internet connectivity."

    def _format_running_processes(self, result: CapabilityResult) -> str:
        """Format running processes result."""
        data = result.data or {}
        count = data.get("count", 0)
        error = data.get("error")

        if error:
            return "Unable to retrieve running processes."
        return f"There are {count} running processes."

    def _format_system_health(self, result: CapabilityResult) -> str:
        """Format system health result."""
        data = result.data or {}

        # Check if all systems are healthy
        ollama = data.get("ollama", {})
        git = data.get("git", {})

        ollama_ok = ollama.get("connected") and ollama.get("healthy")
        git_ok = git.get("is_git_repo")

        if ollama_ok:
            return f"Yes. I'm connected to Ollama using {ollama.get('model', 'unknown')} and ready to help."
        else:
            return "I'm running but may have some connectivity issues."

    def _format_current_time(self, result: CapabilityResult) -> str:
        """Format current time result."""
        data = result.data or {}
        time_str = data.get("time", "unknown")
        return f"The current time is {time_str}."

    def _format_research_capability(self, result: CapabilityResult) -> str:
        """Present canonical research output without dropping provenance."""
        payload = result.data if isinstance(result.data, dict) else {}
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return result.message or "I could not retrieve verifiable research results."

        answer = data.get("answer")
        if answer:
            response = str(answer)
            citations = data.get("citations") or []
            source_lines = []
            seen_urls = set()
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                url = citation.get("source_url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = citation.get("source_title") or url
                source_lines.append(f"- {title}: {url}")
            if source_lines:
                response += "\n\nSources:\n" + "\n".join(source_lines[:5])
            uncertainty = data.get("uncertainty") or []
            if uncertainty:
                response += "\n\nCaveats: " + " ".join(str(item) for item in uncertainty[:3])
            return response

        status = data.get("status")
        if status:
            claim = data.get("claim") or "The claim"
            response = f"{claim}: {str(status).replace('_', ' ')}."
            supporting_sources = data.get("supporting_sources") or []
            if supporting_sources:
                response += "\n\nSources:\n" + "\n".join(
                    f"- {source}" for source in supporting_sources[:5]
                )
            return response

        search_results = data.get("results") or payload.get("results") or []
        if search_results:
            lines = []
            for item in search_results[:5]:
                if isinstance(item, dict) and item.get("url"):
                    lines.append(f"- {item.get('title') or item['url']}: {item['url']}")
            if lines:
                return "I found these relevant sources:\n" + "\n".join(lines)

        return result.message or "I could not retrieve verifiable research results."

    def _format_generic(self, result: CapabilityResult) -> str:
        """Generic formatter for unknown capability types.

        Prefers the hand-written response message so internal field names do not
        leak to the user. Falls back to a description of the data only when no
        message was supplied.
        """
        # Prefer the explicitly-written user-facing message.
        if result.message:
            return result.message

        data = result.data or {}

        # If data is a simple value, just return it
        if isinstance(data, (str, int, float, bool)):
            return str(data)

        # If data is a dictionary with a clear main value
        if isinstance(data, dict):
            # Look for common fields
            if "value" in data:
                return str(data["value"])
            if "result" in data:
                return str(data["result"])
            if "status" in data:
                return f"Status: {data['status']}"

            # Convert to a simple description
            items = []
            for key, value in list(data.items())[:5]:  # Limit to first 5 items
                items.append(f"{key}: {value}")
            return ", ".join(items)

        return json.dumps(data, default=str)


# Global formatter instance
formatter = ResponseFormatter()


def format_capability_result(result: CapabilityResult) -> str:
    """Convenience function to format a capability result.

    Args:
        result: The CapabilityResult to format.

    Returns:
        A formatted natural language string.
    """
    return formatter.format(result)
