"""Response Formatter.

Converts structured capability results into natural language responses.
Hides internal implementation details unless debug mode is enabled.
"""

import html
import json
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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

    @staticmethod
    def _is_unusable_source_url(value: Any) -> bool:
        parsed = urlparse(str(value or ""))
        path = parsed.path.lower()
        query = parsed.query.lower()
        host = (parsed.hostname or "").lower()
        if host in {"news.google.com", "google.com", "www.google.com", "bing.com", "www.bing.com"} and path.startswith(("/rss/articles", "/url", "/ck/a")):
            return True
        return any(token in path for token in ("/challenge", "/captcha", "/.stile")) or ".stile/" in path or "rung=nojs" in query or "captcha" in query

    @staticmethod
    def _clean_research_display(value: Any) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://(?:news\.google\.com|www?\.google\.com|www?\.bing\.com|bing\.com)/[^\s)]+", " ", text, flags=re.I)
        text = re.sub(r"\[[^\]]{0,240}\]", " ", text)
        text = text.replace("[", " ").replace("]", " ")
        text = text.replace("â", " ").replace("Â", " ").replace("¯", " ").replace("�", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"(?m)^\s*[-*•]\s*(?:\r?\n|$)", "", text)
        text = re.sub(r"(?m)^\s*\d+[.)]\s*(?:\r?\n|$)", "", text)
        text = re.sub(r"(?m)^\s*(?:date not exposed|source)\s*;?\s*(?:\r?\n|$)", "", text, flags=re.I)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _format_research_capability(self, result: CapabilityResult) -> str:
        """Present canonical research output without dropping provenance."""

        payload = result.data if isinstance(result.data, dict) else {}
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return result.message or "I could not retrieve verifiable research results."

        answer = data.get("answer")
        if answer:
            response = self._clean_research_display(answer)
            response = re.split(r"\n\s*Sources:\s*\n", response, maxsplit=1, flags=re.I)[0].strip()
            candidates = data.get("product_candidates") or data.get("candidates") or []
            if isinstance(candidates, list) and candidates:
                rows = ["\n\nPrice comparison:", "| Product | Price | Seller | Marketplace |", "|---|---:|---|---|"]
                for item in candidates[:8]:
                    if not isinstance(item, dict):
                        continue
                    price = item.get("price")
                    price_text = f"{item.get('currency', '')} {float(price):,.2f}".strip() if isinstance(price, (int, float)) else "Not exposed"
                    rows.append(f"| {str(item.get('product_name') or 'Listing').replace('|', '/')} | {price_text} | {str(item.get('seller') or 'Not exposed').replace('|', '/')} | {str(item.get('marketplace') or 'Not exposed').replace('|', '/')} |")
                if len(rows) > 3:
                    response += "\n".join(rows)
            citations = data.get("citations") or []
            source_records = data.get("sources") or []
            source_lines = []
            seen_urls = set()
            for citation in [*source_records, *citations]:
                if not isinstance(citation, dict):
                    continue
                page = citation.get("page") if isinstance(citation.get("page"), dict) else {}
                search_result = citation.get("search_result") if isinstance(citation.get("search_result"), dict) else {}
                url = citation.get("source_url") or citation.get("url") or page.get("url") or search_result.get("url")
                if not url:
                    continue
                parsed = urlparse(str(url))
                host = (parsed.hostname or "").lower()
                path = parsed.path.lower()
                if self._is_unusable_source_url(url):
                    continue
                query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in {"ref", "tag", "spm"}]
                canonical_url = urlunparse((parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.path.rstrip("/") or "/", "", urlencode(query), ""))
                if not canonical_url or canonical_url in seen_urls:
                    continue
                seen_urls.add(canonical_url)
                title = self._clean_research_display(citation.get("source_title") or citation.get("title") or page.get("title") or search_result.get("title") or "Public source")
                title = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", title)
                title = re.sub(r"(?i)(nvidia|amd|intel|python|geforce|ryzen|core|rtx)(?=\1)", r"\1 · ", title)
                for repeated in re.findall(r"(?i)\b(?:rtx|ryzen|core\s+i[3579]|python)\s+\d[\w.-]*", title):
                    first = title.lower().find(repeated.lower())
                    second = title.lower().find(repeated.lower(), first + len(repeated))
                    if second > 24:
                        title = title[:second].rstrip(" -:;,.…")
                        break
                title = re.sub(r"\s+", " ", title).strip()
                if len(title) > 90:
                    title = title[:87].rsplit(" ", 1)[0] + "…"
                source_lines.append(f"- {title}: {canonical_url}")
            evidence_limited = bool(re.search(r"none contained readable evidence|could not verify.*(?:evidence|cause)|not enough readable evidence", response, re.I))
            if source_lines and not evidence_limited:
                response += "\n\nSources:\n" + "\n".join(source_lines[:5])
            uncertainty = data.get("uncertainty") or []
            cleaned_uncertainty = []
            hidden_diagnostic_seen = False
            diagnostic_pattern = re.compile(r"(?:exception|httperror|traceback|ddgs|failed\s+to\s+fetch|failed\s+to\s+read|provider\s+attempt|connection\s+reset|timeout|no\s+usable\s+public\s+page|browser\s+page\s+contained|insufficient\s+readable\s+public\s+content|maintained\s+extractor|no\s+content\s+extracted)", re.I)
            for item in uncertainty:
                cleaned = self._clean_research_display(item)
                if not cleaned:
                    continue
                if re.search(r"materially different numeric values", cleaned, re.I):
                    cleaned = "Some sources disagree on numeric details; the answer follows the strongest available evidence."
                elif re.search(r"answer-quality verification|unsupported or insufficiently grounded claims", cleaned, re.I):
                    cleaned = "The answer is limited to claims supported by the available evidence."
                if diagnostic_pattern.search(cleaned):
                    hidden_diagnostic_seen = True
                    continue
                if cleaned not in cleaned_uncertainty:
                    cleaned_uncertainty.append(cleaned)
            if hidden_diagnostic_seen:
                cleaned_uncertainty.append("Some public sources were unavailable or unreadable; the comparison uses the evidence that remained.")
            if cleaned_uncertainty:
                response += "\n\nEvidence notes: " + " ".join(cleaned_uncertainty[:3])
            followups = data.get("follow_up_questions") or (data.get("grounded_answer") or {}).get("follow_up_questions") or []
            followups = [self._clean_research_display(item) for item in followups if self._clean_research_display(item)]
            if followups:
                response += "\n\nTo narrow this down: " + " ".join(followups[:3])
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
            for item in search_results[:4]:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                title = self._clean_research_display(item.get("title") or "Public source")
                title = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", title)
                title = re.sub(r"(?i)(nvidia|amd|intel|python|geforce|ryzen|core|rtx)(?=\1)", r"\1 · ", title)
                for repeated in re.findall(r"(?i)\b(?:rtx|ryzen|core\s+i[3579]|python)\s+\d[\w.-]*", title):
                    first = title.lower().find(repeated.lower())
                    second = title.lower().find(repeated.lower(), first + len(repeated))
                    if second > 24:
                        title = title[:second].rstrip(" -:;,.…")
                        break
                title = re.sub(r"\s+", " ", title).strip()
                if len(title) > 90:
                    title = title[:87].rsplit(" ", 1)[0] + "…"
                url = str(item.get("url") or "").strip()
                if self._is_unusable_source_url(url):
                    continue
                if title and url:
                    lines.append(f"[{title}]({url})")
            if lines:
                count = len(search_results)
                return f"I found {count} potentially relevant public sources, but I could not read enough reliable page content to synthesize a grounded answer. You can open the strongest matches below:\n\n" + "\n".join(lines)

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
