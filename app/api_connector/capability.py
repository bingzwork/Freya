"""Controlled API connector over Freya's existing HTTP tools."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Set
from urllib.parse import urlparse

from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.orchestrator.capabilities import BaseCapability
from app.tools.http_tools import http_request


_SENSITIVE_HEADER_NAMES = {
    "authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key",
    "x-auth-token", "api-key", "token", "password", "secret",
}
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
_SAFE_METHODS = {"GET", "HEAD"}
_MAX_TIMEOUT = 120
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class CredentialStore(Protocol):
    """Named credential lookup boundary; implementations must not expose secrets."""

    def resolve(self, reference: str) -> Mapping[str, str]:
        ...


class EnvironmentCredentialStore:
    """Resolve named references from process environment without logging values."""

    def resolve(self, reference: str) -> Mapping[str, str]:
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", reference):
            raise ValueError("credential_ref contains unsupported characters")
        prefix = f"FREYA_CREDENTIAL_{reference.upper().replace('-', '_').replace('.', '_').replace(':', '_')}"
        value = os.getenv(prefix)
        if not value:
            raise KeyError(f"Credential reference '{reference}' is not configured")
        return {"Authorization": value}


@dataclass
class ConnectorPolicy:
    allowed_domains: Set[str]
    max_response_bytes: int = _MAX_RESPONSE_BYTES
    default_timeout_seconds: int = 30
    allow_redirects: bool = False


class APIConnectorCapability(BaseCapability):
    """Registered, approval-aware HTTP connector using existing networking primitives."""

    def __init__(
        self,
        *,
        allowed_domains: Optional[Set[str]] = None,
        credential_store: Optional[CredentialStore] = None,
        http_client=http_request,
    ):
        super().__init__(CapabilityMetadata(
            name="api_connector",
            version="1.0.0",
            description="Controlled allowlisted HTTP API calls with named credentials and safety approval",
            category=CapabilityCategory.TOOL,
            is_singleton=True,
            auto_discoverable=True,
            safe_query=True,
            default_action="request",
            supported_actions=["request", "get", "post", "put", "patch", "delete", "head"],
            tags=[
                "api", "API", "endpoint", "HTTP", "GET", "POST", "PUT", "PATCH", "DELETE",
                "call", "send JSON", "request", "website monitoring",
            ],
        ))
        self._policy = ConnectorPolicy(
            allowed_domains={self._normalize_domain(domain) for domain in (allowed_domains or set())},
        )
        self._credential_store = credential_store or EnvironmentCredentialStore()
        self._http_client = http_client
        self._safety_gate = None

    def set_policy(
        self,
        *,
        allowed_domains: Optional[Set[str]] = None,
        max_response_bytes: Optional[int] = None,
        default_timeout_seconds: Optional[int] = None,
        allow_redirects: Optional[bool] = None,
    ) -> None:
        if allowed_domains is not None:
            self._policy.allowed_domains = {
                self._normalize_domain(domain) for domain in allowed_domains
            }
        if max_response_bytes is not None:
            if not 1 <= int(max_response_bytes) <= _MAX_RESPONSE_BYTES:
                raise ValueError(f"max_response_bytes must be between 1 and {_MAX_RESPONSE_BYTES}")
            self._policy.max_response_bytes = int(max_response_bytes)
        if default_timeout_seconds is not None:
            if not 1 <= int(default_timeout_seconds) <= _MAX_TIMEOUT:
                raise ValueError(f"timeout must be between 1 and {_MAX_TIMEOUT} seconds")
            self._policy.default_timeout_seconds = int(default_timeout_seconds)
        if allow_redirects is not None:
            self._policy.allow_redirects = bool(allow_redirects)

    def set_safety_gate(self, safety_gate) -> None:
        self._safety_gate = safety_gate

    def set_credential_store(self, credential_store: CredentialStore) -> None:
        self._credential_store = credential_store

    def action_request(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        method = str(inputs.get("method", "GET")).upper().strip()
        if method not in _ALLOWED_METHODS:
            return self._error(f"Unsupported HTTP method: {method}")
        url, error = self._validate_url(inputs.get("url"))
        if error:
            return self._error(error)
        if not self._policy.allowed_domains:
            return self._error("API connector has no configured allowed domains")
        if not self._domain_allowed(url.hostname or ""):
            return self._error(f"Domain is not allowlisted: {url.hostname}")

        timeout = inputs.get("timeout", self._policy.default_timeout_seconds)
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            return self._error("timeout must be an integer")
        if not 1 <= timeout <= _MAX_TIMEOUT:
            return self._error(f"timeout must be between 1 and {_MAX_TIMEOUT} seconds")

        headers = inputs.get("headers") or {}
        if not isinstance(headers, dict):
            return self._error("headers must be an object")
        headers = {str(key): str(value) for key, value in headers.items()}
        if any(str(key).lower() in _SENSITIVE_HEADER_NAMES for key in headers):
            return self._error("Sensitive headers require a named credential_ref")

        credential_ref = inputs.get("credential_ref")
        if credential_ref is not None:
            try:
                credentials = dict(self._credential_store.resolve(str(credential_ref)))
            except (KeyError, TypeError, ValueError) as error:
                return self._error(f"Credential reference unavailable: {error}")
            headers = {**credentials, **headers}

        query = inputs.get("params") or inputs.get("query") or {}
        if not isinstance(query, dict):
            return self._error("params/query must be an object")
        json_body = inputs.get("json_body", inputs.get("json"))
        if json_body is not None and not isinstance(json_body, (dict, list)):
            return self._error("json_body must be an object or array")

        if method not in _SAFE_METHODS:
            safety_error = self._authorize_mutation(method, url.geturl(), inputs)
            if safety_error:
                return safety_error

        try:
            raw = self._http_client(
                method,
                url.geturl(),
                json=json_body,
                headers=headers,
                params=query,
                timeout=timeout,
                allow_redirects=self._policy.allow_redirects,
                max_response_bytes=self._policy.max_response_bytes,
            )
        except Exception as error:
            return self._error(f"HTTP request failed: {self._safe_text(str(error), headers)}")

        if not isinstance(raw, dict):
            return self._error("HTTP primitive returned an invalid response")
        if raw.get("truncated"):
            return self._error("Response exceeded the configured size limit")
        body = self._safe_text(str(raw.get("body") or ""), headers)
        if len(body.encode("utf-8")) > self._policy.max_response_bytes:
            return self._error("Response exceeded the configured size limit")
        response_headers = self._redact_headers(raw.get("headers") or {})
        response_json = self._redact_value(raw.get("json"), headers)
        status = raw.get("status")
        success = raw.get("error") is None and isinstance(status, int) and status < 400
        result = {
            "success": success,
            "status": status,
            "headers": response_headers,
            "json": response_json,
            "body": body,
            "error": self._safe_text(str(raw.get("error")), headers) if raw.get("error") else None,
            "method": method,
            "url": self._redact_url(url.geturl()),
        }
        return result

    def action_get(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "GET"})

    def action_post(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "POST"})

    def action_put(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "PUT"})

    def action_patch(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "PATCH"})

    def action_delete(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "DELETE"})

    def action_head(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.action_request({**inputs, "method": "HEAD"})

    def _authorize_mutation(self, method: str, url: str, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self._safety_gate is None:
            return self._error("Sensitive API method requires the existing SafetyGate")
        safe_inputs = {key: value for key, value in inputs.items() if key not in {"headers", "credential_ref"}}
        try:
            assessment = self._safety_gate.check_and_enforce(
                operation=f"API {method} request to {url}",
                operation_type="external_api_call",
                context={"capability": self.name, "method": method, "inputs": safe_inputs},
            )
        except Exception as error:
            return self._error(f"API operation blocked by SafetyGate: {error}")
        if not getattr(assessment, "allowed", False):
            return self._error("API operation was not authorized by SafetyGate")
        return None

    @staticmethod
    def _validate_url(value: Any):
        if not isinstance(value, str) or not value.strip():
            return None, "url is required"
        try:
            parsed = urlparse(value.strip())
        except ValueError as error:
            return None, f"Malformed URL: {error}"
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None, "URL must use http or https and include a hostname"
        if parsed.username or parsed.password:
            return None, "URL userinfo is not allowed"
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
            return None, "Local/internal hostnames are not allowed"
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return None, "Local/internal IP addresses are not allowed"
        except ValueError:
            if "." not in hostname:
                return None, "Hostname is not fully qualified"
        return parsed, None

    def _domain_allowed(self, hostname: str) -> bool:
        normalized = hostname.lower().rstrip(".")
        return any(normalized == domain or normalized.endswith(f".{domain}") for domain in self._policy.allowed_domains)

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        domain = str(domain).strip().lower().rstrip(".")
        if not domain or "/" in domain or "://" in domain:
            raise ValueError(f"Invalid allowlisted domain: {domain}")
        return domain

    @staticmethod
    def _redact_headers(headers: Mapping[str, Any]) -> Dict[str, str]:
        output = {}
        for key, value in headers.items():
            output[str(key)] = "[REDACTED]" if str(key).lower() in _SENSITIVE_HEADER_NAMES else str(value)
        return output

    @classmethod
    def _redact_value(cls, value: Any, headers: Mapping[str, str]) -> Any:
        if isinstance(value, str):
            return cls._safe_text(value, headers)
        if isinstance(value, dict):
            return {str(key): cls._redact_value(item, headers) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_value(item, headers) for item in value]
        return value

    @staticmethod
    def _safe_text(value: str, headers: Mapping[str, str]) -> str:
        sanitized = value
        for key, secret in headers.items():
            if str(key).lower() in _SENSITIVE_HEADER_NAMES and secret:
                sanitized = sanitized.replace(str(secret), "[REDACTED]")
        return sanitized

    @staticmethod
    def _redact_url(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(query="[REDACTED]" if parsed.query else "").geturl()

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message, "message": message}


__all__ = ["APIConnectorCapability", "CredentialStore", "EnvironmentCredentialStore", "ConnectorPolicy"]
