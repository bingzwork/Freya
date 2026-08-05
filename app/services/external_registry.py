import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

# Import dependencies from existing services module
from app.world_model.services import (
    ServiceEndpoint,
    ServiceCredentials,
    ServiceMetrics,
    ServiceCapability,
    ServiceProvider,
    ServiceAvailability,
    AuthStatus,
)
from app.core.events import get_event_bus
from app.monitoring.network_monitor import NetworkMonitor, ServiceConfig, EndpointConfig, CheckType


class ServiceType(Enum):
    """Categories of external services Freya can interact with."""
    # LLM/AI Providers
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HUGGINGFACE = "huggingface"

    # Code/Version Control
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GIT = "git"

    # MCP (Model Context Protocol)
    MCP = "mcp"

    # Database Services
    SQL_DATABASE = "sql_database"
    VECTOR_DATABASE = "vector_database"
    NOSQL_DATABASE = "nosql_database"

    # File/Object Storage
    FILE_STORAGE = "file_storage"
    OBJECT_STORAGE = "object_storage"

    # Knowledge/Retrieval
    KNOWLEDGE_BASE = "knowledge_base"
    SEARCH_ENGINE = "search_engine"

    # Other
    LOCAL = "local"
    REMOTE_API = "remote_api"
    MESSAGE_QUEUE = "message_queue"
    CACHE = "cache"
    CUSTOM = "custom"


class ServiceHealth(Enum):
    """Health status of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    UNREACHABLE = "unreachable"


@dataclass
class ServiceMetadata:
    """Complete metadata for an external service.

    This is the core model that extends NetworkMonitor's ServiceConfig
    with additional fields for registry operations, capabilities, and metadata.
    """
    # Identity
    service_id: str = field(default_factory=lambda: f"svc_{uuid4().hex[:12]}")
    display_name: str = ""
    service_type: ServiceType = ServiceType.CUSTOM
    provider: ServiceProvider = ServiceProvider.UNKNOWN
    version: str = "unknown"

    # Network
    endpoint: Optional[ServiceEndpoint] = None
    credentials: Optional[ServiceCredentials] = None

    # Capabilities
    capabilities: Set[ServiceCapability] = field(default_factory=set)
    supported_models: List[str] = field(default_factory=list)  # For LLM services
    supported_operations: List[str] = field(default_factory=list)  # Custom operations

    # Status
    availability: ServiceAvailability = ServiceAvailability.UNKNOWN
    health: ServiceHealth = ServiceHealth.UNKNOWN
    auth_status: AuthStatus = AuthStatus.UNKNOWN

    # Timing
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_health_check: Optional[str] = None
    last_successful_use: Optional[str] = None
    last_failure: Optional[str] = None

    # Metrics
    metrics: ServiceMetrics = field(default_factory=ServiceMetrics)

    # Configuration
    is_enabled: bool = True
    is_default: bool = False  # Default service for its type
    priority: int = 100  # Lower = higher priority for selection
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Health check configuration
    health_check_enabled: bool = True
    health_check_interval_seconds: float = 60.0
    health_check_timeout_seconds: float = 10.0
    health_check_path: str = "/health"
    expected_status_codes: List[int] = field(default_factory=lambda: [200])

    def __post_init__(self):
        """Post-initialization processing."""
        if self.endpoint is None:
            self.endpoint = ServiceEndpoint(url="")
        if self.credentials is None:
            self.credentials = ServiceCredentials()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "service_id": self.service_id,
            "display_name": self.display_name,
            "service_type": self.service_type.value,
            "provider": self.provider.value,
            "version": self.version,
            "endpoint": {
                "url": self.endpoint.url,
                "protocol": self.endpoint.protocol,
                "headers": self.endpoint.headers,
                "query_params": self.endpoint.query_params,
                "timeout_seconds": self.endpoint.timeout_seconds,
                "max_retries": self.endpoint.max_retries,
                "retry_backoff": self.endpoint.retry_backoff,
                "verify_ssl": self.endpoint.verify_ssl,
                "socket_path": self.endpoint.socket_path,
                "backup_urls": self.endpoint.backup_urls,
            } if self.endpoint else None,
            "credentials": {
                "auth_type": self.credentials.auth_type,
                "api_key": "***" if self.credentials.api_key else None,
                "bearer_token": "***" if self.credentials.bearer_token else None,
                "username": self.credentials.username,
                "password": "***" if self.credentials.password else None,
                "oauth2_client_id": self.credentials.oauth2_client_id,
                "oauth2_client_secret": "***" if self.credentials.oauth2_client_secret else None,
                "oauth2_token_url": self.credentials.oauth2_token_url,
                "oauth2_scopes": self.credentials.oauth2_scopes,
                "custom_headers": self.credentials.custom_headers,
                "custom_data": self.credentials.custom_data,
                "expires_at": self.credentials.expires_at,
                "last_refreshed": self.credentials.last_refreshed,
                "status": self.credentials.status.value,
            } if self.credentials else None,
            "capabilities": [c.value for c in self.capabilities],
            "supported_models": self.supported_models,
            "supported_operations": self.supported_operations,
            "availability": self.availability.value,
            "health": self.health.value,
            "auth_status": self.auth_status.value,
            "registered_at": self.registered_at,
            "last_health_check": self.last_health_check,
            "last_successful_use": self.last_successful_use,
            "last_failure": self.last_failure,
            "metrics": {
                # Latency
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "p50_latency_ms": self.metrics.p50_latency_ms,
                "p95_latency_ms": self.metrics.p95_latency_ms,
                "p99_latency_ms": self.metrics.p99_latency_ms,

                # Throughput
                "requests_per_second": self.metrics.requests_per_second,
                "successful_requests": self.metrics.successful_requests,
                "failed_requests": self.metrics.failed_requests,
                "total_requests": self.metrics.total_requests,

                # Error tracking
                "error_rate": self.metrics.error_rate,
                "last_error": self.metrics.last_error,
                "last_error_at": self.metrics.last_error_at,
                "consecutive_failures": self.metrics.consecutive_failures,

                # Availability
                "uptime_percentage": self.metrics.uptime_percentage,
                "last_check_at": self.metrics.last_check_at,
                "last_success_at": self.metrics.last_success_at,

                # Resource usage (if available)
                "cpu_usage_percent": self.metrics.cpu_usage_percent,
                "memory_usage_mb": self.metrics.memory_usage_mb,
                "disk_usage_mb": self.metrics.disk_usage_mb,

                # Rate limiting
                "rate_limit_remaining": self.metrics.rate_limit_remaining,
                "rate_limit_reset_at": self.metrics.rate_limit_reset_at,
                "rate_limit_limit": self.metrics.rate_limit_limit,
            },

            # Configuration
            "is_enabled": self.is_enabled,
            "is_default": self.is_default,
            "priority": self.priority,
            "tags": list(self.tags),
            "metadata": self.metadata,

            # Health check configuration
            "health_check_enabled": self.health_check_enabled,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "health_check_timeout_seconds": self.health_check_timeout_seconds,
            "health_check_path": self.health_check_path,
            "expected_status_codes": self.expected_status_codes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceMetadata":
        """Create ServiceMetadata from dictionary."""
        # Handle enum fields that are stored as values
        service_type = ServiceType(data.get("service_type", "custom"))
        provider = ServiceProvider(data.get("provider", "unknown"))
        availability = ServiceAvailability(data.get("availability", "unknown"))
        health = ServiceHealth(data.get("health", "unknown"))
        auth_status = AuthStatus(data.get("auth_status", "unknown"))

        # Handle nested objects
        endpoint_data = data.get("endpoint")
        endpoint = None
        if endpoint_data:
            endpoint = ServiceEndpoint(
                url=endpoint_data.get("url", ""),
                protocol=endpoint_data.get("protocol", "https"),
                headers=endpoint_data.get("headers", {}),
                query_params=endpoint_data.get("query_params", {}),
                timeout_seconds=endpoint_data.get("timeout_seconds", 30.0),
                max_retries=endpoint_data.get("max_retries", 3),
                retry_backoff=endpoint_data.get("retry_backoff", 1.0),
                verify_ssl=endpoint_data.get("verify_ssl", True),
                socket_path=endpoint_data.get("socket_path"),
                backup_urls=endpoint_data.get("backup_urls", []),
            )

        credentials_data = data.get("credentials")
        credentials = None
        if credentials_data:
            credentials = ServiceCredentials(
                auth_type=credentials_data.get("auth_type", "none"),
                api_key=credentials_data.get("api_key"),
                bearer_token=credentials_data.get("bearer_token"),
                username=credentials_data.get("username"),
                password=credentials_data.get("password"),
                oauth2_client_id=credentials_data.get("oauth2_client_id"),
                oauth2_client_secret=credentials_data.get("oauth2_client_secret"),
                oauth2_token_url=credentials_data.get("oauth2_token_url"),
                oauth2_scopes=credentials_data.get("oauth2_scopes", []),
                custom_headers=credentials_data.get("custom_headers", {}),
                custom_data=credentials_data.get("custom_data", {}),
                expires_at=credentials_data.get("expires_at"),
                last_refreshed=credentials_data.get("last_refreshed"),
                status=AuthStatus(credentials_data.get("status", "unknown")),
            )

        return cls(
            service_id=data.get("service_id", f"svc_{uuid4().hex[:12]}"),
            display_name=data.get("display_name", ""),
            service_type=service_type,
            provider=provider,
            version=data.get("version", "unknown"),
            endpoint=endpoint,
            credentials=credentials,
            capabilities=set(ServiceCapability(c) for c in data.get("capabilities", [])),
            supported_models=data.get("supported_models", []),
            supported_operations=data.get("supported_operations", []),
            availability=availability,
            health=health,
            auth_status=auth_status,
            registered_at=data.get("registered_at", datetime.now(timezone.utc).isoformat()),
            last_health_check=data.get("last_health_check"),
            last_successful_use=data.get("last_successful_use"),
            last_failure=data.get("last_failure"),
            metrics=ServiceMetrics(
                # Latency
                avg_latency_ms=data.get("metrics", {}).get("avg_latency_ms", 0.0),
                p50_latency_ms=data.get("metrics", {}).get("p50_latency_ms", 0.0),
                p95_latency_ms=data.get("metrics", {}).get("p95_latency_ms", 0.0),
                p99_latency_ms=data.get("metrics", {}).get("p99_latency_ms", 0.0),

                # Throughput
                requests_per_second=data.get("metrics", {}).get("requests_per_second", 0.0),
                successful_requests=data.get("metrics", {}).get("successful_requests", 0),
                failed_requests=data.get("metrics", {}).get("failed_requests", 0),
                total_requests=data.get("metrics", {}).get("total_requests", 0),

                # Error tracking
                error_rate=data.get("metrics", {}).get("error_rate", 0.0),
                last_error=data.get("metrics", {}).get("last_error"),
                last_error_at=data.get("metrics", {}).get("last_error_at"),
                consecutive_failures=data.get("metrics", {}).get("consecutive_failures", 0),

                # Availability
                uptime_percentage=data.get("metrics", {}).get("uptime_percentage", 100.0),
                last_check_at=data.get("metrics", {}).get("last_check_at"),
                last_success_at=data.get("metrics", {}).get("last_success_at"),

                # Resource usage (if available)
                cpu_usage_percent=data.get("metrics", {}).get("cpu_usage_percent"),
                memory_usage_mb=data.get("metrics", {}).get("memory_usage_mb"),
                disk_usage_mb=data.get("metrics", {}).get("disk_usage_mb"),

                # Rate limiting
                rate_limit_remaining=data.get("metrics", {}).get("rate_limit_remaining"),
                rate_limit_reset_at=data.get("metrics", {}).get("rate_limit_reset_at"),
                rate_limit_limit=data.get("metrics", {}).get("rate_limit_limit"),
            ),
            is_enabled=data.get("is_enabled", True),
            is_default=data.get("is_default", False),
            priority=data.get("priority", 100),
            tags=set(data.get("tags", [])),
            metadata=data.get("metadata", {}),
            health_check_enabled=data.get("health_check_enabled", True),
            health_check_interval_seconds=data.get("health_check_interval_seconds", 60.0),
            health_check_timeout_seconds=data.get("health_check_timeout_seconds", 10.0),
            health_check_path=data.get("health_check_path", "/health"),
            expected_status_codes=data.get("expected_status_codes", [200]),
        )

    def is_healthy(self) -> bool:
        """Check if service is considered healthy for use."""
        return (
            self.is_enabled and
            self.health in (ServiceHealth.HEALTHY, ServiceHealth.DEGRADED) and
            self.availability in (ServiceAvailability.AVAILABLE, ServiceAvailability.LIMITED) and
            self.auth_status in (AuthStatus.AUTHENTICATED, AuthStatus.NOT_REQUIRED)
        )

    def get_effective_priority(self) -> int:
        """Get effective priority considering health and availability."""
        base = self.priority
        if self.health == ServiceHealth.UNHEALTHY:
            base += 1000
        elif self.health == ServiceHealth.DEGRADED:
            base += 100
        if self.availability == ServiceAvailability.UNAVAILABLE:
            base += 1000
        elif self.availability == ServiceAvailability.MAINTENANCE:
            base += 500
        elif self.availability == ServiceAvailability.LIMITED:
            base += 50
        if self.auth_status == AuthStatus.EXPIRED:
            base += 200
        elif self.auth_status == AuthStatus.INVALID:
            base += 500
        return base


class ExternalServiceRegistry:
    """Registry for external services."""

    def __init__(self):
        self._services: Dict[str, ServiceMetadata] = {}
        self._default_services: Dict[ServiceType, str] = {}  # service_type -> service_id
        self._event_bus = get_event_bus()

    def register(self, service: ServiceMetadata) -> None:
        """Register a service."""
        self._services[service.service_id] = service
        if service.is_default:
            self._default_services[service.service_type] = service.service_id
        # Emit service registered event
        self._event_bus.emit(
            name="service.registered",
            data={
                "service_id": service.service_id,
                "service": service.to_dict()
            },
            source="ExternalServiceRegistry"
        )

    def unregister(self, service_id: str) -> bool:
        """Unregister a service by ID. Returns True if removed."""
        if service_id in self._services:
            service = self._services.pop(service_id)
            # Remove from default services if it was set as default
            if service.service_type in self._default_services and self._default_services[service.service_type] == service_id:
                del self._default_services[service.service_type]
            # Emit service unregistered event
            self._event_bus.emit(
                name="service.unregistered",
                data={
                    "service_id": service_id
                },
                source="ExternalServiceRegistry"
            )
            return True
        return False

    def get(self, service_id: str) -> Optional[ServiceMetadata]:
        """Get a service by ID."""
        return self._services.get(service_id)

    def list(self, service_type: Optional[ServiceType] = None) -> List[ServiceMetadata]:
        """List services, optionally filtered by type."""
        services = list(self._services.values())
        if service_type is not None:
            services = [s for s in services if s.service_type == service_type]
        return services

    def update_health(self, service_id: str, health: ServiceHealth) -> bool:
        """Update the health status of a service."""
        service = self.get(service_id)
        if service:
            old_health = service.health
            if old_health != health:
                service.health = health
                service.last_health_check = datetime.now(timezone.utc).isoformat()
                # Emit health changed event
                self._event_bus.emit(
                    name="service.health_changed",
                    data={
                        "service_id": service_id,
                        "old_health": old_health.value,
                        "new_health": health.value
                    },
                    source="ExternalServiceRegistry"
                )
                return True
            return False  # No change
        return False  # Service not found

    def update_latency(self, service_id: str, latency_ms: float) -> bool:
        """Update the latency metrics for a service with a successful request."""
        service = self.get(service_id)
        if service:
            # Update latency as a successful request
            service.metrics.update_on_success(latency_ms)
            # Emit metrics updated event
            self._event_bus.emit(
                name="service.metrics_updated",
                data={
                    "service_id": service_id,
                    "metrics": {
                        # Latency
                        "avg_latency_ms": service.metrics.avg_latency_ms,
                        "p50_latency_ms": service.metrics.p50_latency_ms,
                        "p95_latency_ms": service.metrics.p95_latency_ms,
                        "p99_latency_ms": service.metrics.p99_latency_ms,

                        # Throughput
                        "requests_per_second": service.metrics.requests_per_second,
                        "successful_requests": service.metrics.successful_requests,
                        "failed_requests": service.metrics.failed_requests,
                        "total_requests": service.metrics.total_requests,

                        # Error tracking
                        "error_rate": service.metrics.error_rate,
                        "last_error": service.metrics.last_error,
                        "last_error_at": service.metrics.last_error_at,
                        "consecutive_failures": service.metrics.consecutive_failures,

                        # Availability
                        "uptime_percentage": service.metrics.uptime_percentage,
                        "last_check_at": service.metrics.last_check_at,
                        "last_success_at": service.metrics.last_success_at,

                        # Resource usage (if available)
                        "cpu_usage_percent": service.metrics.cpu_usage_percent,
                        "memory_usage_mb": service.metrics.memory_usage_mb,
                        "disk_usage_mb": service.metrics.disk_usage_mb,

                        # Rate limiting
                        "rate_limit_remaining": service.metrics.rate_limit_remaining,
                        "rate_limit_reset_at": service.metrics.rate_limit_reset_at,
                        "rate_limit_limit": service.metrics.rate_limit_limit,
                    }
                },
                source="ExternalServiceRegistry"
            )
            return True
        return False

    def query_by_capability(self, capability: ServiceCapability) -> List[ServiceMetadata]:
        """Return a list of services that have the specified capability."""
        return [service for service in self._services.values() if capability in service.capabilities]

    # --- Auto-discovery methods ---

    def discover_ollama(self) -> List[ServiceMetadata]:
        """Discover Ollama instances from environment and local defaults."""
        discovered = []

        # Check environment variable for Ollama host
        ollama_host = os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_BASE_URL")
        if ollama_host:
            # Parse URL to get host and port
            from urllib.parse import urlparse
            parsed = urlparse(ollama_host)
            host = parsed.hostname or "localhost"
            port = parsed.port or 11434
            base_url = f"http://{host}:{port}"
        else:
            # Default local Ollama
            base_url = "http://localhost:11434"
            host = "localhost"
            port = 11434

        # Create Ollama service metadata
        service = ServiceMetadata(
            display_name="Ollama (Local)",
            service_type=ServiceType.OLLAMA,
            provider=ServiceProvider.OLLAMA,
            version="unknown",
            endpoint=ServiceEndpoint(
                url=base_url,
                protocol="http",
                timeout_seconds=30.0,
            ),
            credentials=ServiceCredentials(auth_type="none"),
            capabilities={
                ServiceCapability.TEXT_GENERATION,
                ServiceCapability.CHAT_COMPLETION,
                ServiceCapability.EMBEDDING,
                ServiceCapability.TOOL_USE,
                ServiceCapability.STREAMING,
            },
            supported_models=[],  # Will be populated on health check
            is_enabled=True,
            is_default=True,
            priority=10,
            tags={"local", "llm", "auto-discovered"},
        )
        discovered.append(service)

        # Also check for additional Ollama hosts from env
        extra_hosts = os.environ.get("OLLAMA_EXTRA_HOSTS", "").split(",")
        for extra_host in extra_hosts:
            extra_host = extra_host.strip()
            if extra_host:
                from urllib.parse import urlparse
                parsed = urlparse(extra_host)
                h = parsed.hostname or "localhost"
                p = parsed.port or 11434
                url = f"http://{h}:{p}"

                extra_service = ServiceMetadata(
                    display_name=f"Ollama ({h}:{p})",
                    service_type=ServiceType.OLLAMA,
                    provider=ServiceProvider.OLLAMA,
                    version="unknown",
                    endpoint=ServiceEndpoint(
                        url=url,
                        protocol="http",
                        timeout_seconds=30.0,
                    ),
                    credentials=ServiceCredentials(auth_type="none"),
                    capabilities={
                        ServiceCapability.TEXT_GENERATION,
                        ServiceCapability.CHAT_COMPLETION,
                        ServiceCapability.EMBEDDING,
                        ServiceCapability.TOOL_USE,
                        ServiceCapability.STREAMING,
                    },
                    is_enabled=True,
                    priority=20,
                    tags={"remote", "llm", "auto-discovered"},
                )
                discovered.append(extra_service)

        return discovered

    def discover_openai(self) -> List[ServiceMetadata]:
        """Discover OpenAI service from environment variables."""
        discovered = []

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return discovered

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

        service = ServiceMetadata(
            display_name="OpenAI",
            service_type=ServiceType.OPENAI,
            provider=ServiceProvider.OPENAI,
            version="v1",
            endpoint=ServiceEndpoint(
                url=base_url,
                protocol="https",
                timeout_seconds=60.0,
                headers={"Authorization": f"Bearer {api_key}"},
            ),
            credentials=ServiceCredentials(
                auth_type="bearer_token",
                bearer_token=api_key,
            ),
            capabilities={
                ServiceCapability.TEXT_GENERATION,
                ServiceCapability.CHAT_COMPLETION,
                ServiceCapability.EMBEDDING,
                ServiceCapability.TOOL_USE,
                ServiceCapability.VISION,
                ServiceCapability.STREAMING,
            },
            supported_models=[model, "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
            is_enabled=True,
            priority=50,
            tags={"cloud", "llm", "auto-discovered"},
        )
        discovered.append(service)

        return discovered

    def discover_anthropic(self) -> List[ServiceMetadata]:
        """Discover Anthropic (Claude) service from environment variables."""
        discovered = []

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return discovered

        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20250620")

        service = ServiceMetadata(
            display_name="Anthropic (Claude)",
            service_type=ServiceType.ANTHROPIC,
            provider=ServiceProvider.ANTHROPIC,
            version="2023-06-01",
            endpoint=ServiceEndpoint(
                url=base_url,
                protocol="https",
                timeout_seconds=60.0,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            ),
            credentials=ServiceCredentials(
                auth_type="api_key",
                api_key=api_key,
            ),
            capabilities={
                ServiceCapability.TEXT_GENERATION,
                ServiceCapability.CHAT_COMPLETION,
                ServiceCapability.TOOL_USE,
                ServiceCapability.VISION,
                ServiceCapability.STREAMING,
            },
            supported_models=[model, "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
            is_enabled=True,
            priority=50,
            tags={"cloud", "llm", "auto-discovered"},
        )
        discovered.append(service)

        return discovered

    def discover_github(self) -> List[ServiceMetadata]:
        """Discover GitHub service from environment variables."""
        discovered = []

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
        if not token:
            return discovered

        base_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")

        service = ServiceMetadata(
            display_name="GitHub",
            service_type=ServiceType.GITHUB,
            provider=ServiceProvider.GITHUB,
            version="v3",
            endpoint=ServiceEndpoint(
                url=base_url,
                protocol="https",
                timeout_seconds=30.0,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            ),
            credentials=ServiceCredentials(
                auth_type="bearer_token",
                bearer_token=token,
            ),
            capabilities={
                ServiceCapability.REPO_READ,
                ServiceCapability.REPO_WRITE,
                ServiceCapability.ISSUE_MANAGEMENT,
                ServiceCapability.PR_MANAGEMENT,
                ServiceCapability.CI_CD,
                ServiceCapability.CODE_SEARCH,
                ServiceCapability.GIT_OPERATIONS,
            },
            is_enabled=True,
            priority=100,
            tags={"cloud", "vcs", "auto-discovered"},
        )
        discovered.append(service)

        return discovered

    def discover_gitlab(self) -> List[ServiceMetadata]:
        """Discover GitLab service from environment variables."""
        discovered = []

        token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PAT")
        if not token:
            return discovered

        base_url = os.environ.get("GITLAB_API_URL", "https://gitlab.com/api/v4")

        service = ServiceMetadata(
            display_name="GitLab",
            service_type=ServiceType.GITLAB,
            provider=ServiceProvider.GITLAB,
            version="v4",
            endpoint=ServiceEndpoint(
                url=base_url,
                protocol="https",
                timeout_seconds=30.0,
                headers={"Authorization": f"Bearer {token}"},
            ),
            credentials=ServiceCredentials(
                auth_type="bearer_token",
                bearer_token=token,
            ),
            capabilities={
                ServiceCapability.REPO_READ,
                ServiceCapability.REPO_WRITE,
                ServiceCapability.ISSUE_MANAGEMENT,
                ServiceCapability.PR_MANAGEMENT,
                ServiceCapability.CI_CD,
                ServiceCapability.CODE_SEARCH,
                ServiceCapability.GIT_OPERATIONS,
            },
            is_enabled=True,
            priority=100,
            tags={"cloud", "vcs", "auto-discovered"},
        )
        discovered.append(service)

        return discovered

    def discover_postgresql(self) -> List[ServiceMetadata]:
        """Discover PostgreSQL databases from environment variables."""
        discovered = []

        # Check for standard PostgreSQL connection info
        db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
        if db_url:
            service = self._create_sql_database_service(db_url, "PostgreSQL", ServiceProvider.POSTGRESQL)
            discovered.append(service)

        # Check for individual connection parameters
        host = os.environ.get("POSTGRES_HOST") or os.environ.get("PGHOST")
        if host:
            port = int(os.environ.get("POSTGRES_PORT", os.environ.get("PGPORT", "5432")))
            db_name = os.environ.get("POSTGRES_DB") or os.environ.get("PGDATABASE", "postgres")
            user = os.environ.get("POSTGRES_USER") or os.environ.get("PGUSER", "postgres")
            password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("PGPASSWORD")

            from urllib.parse import quote_plus
            pwd_part = f":{quote_plus(password)}" if password else ""
            db_url = f"postgresql://{user}{pwd_part}@{host}:{port}/{db_name}"

            service = self._create_sql_database_service(db_url, f"PostgreSQL ({host}:{port})", ServiceProvider.POSTGRESQL)
            discovered.append(service)

        return discovered

    def _create_sql_database_service(self, db_url: str, display_name: str, provider: ServiceProvider) -> ServiceMetadata:
        """Create a SQL database service metadata."""
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432

        return ServiceMetadata(
            display_name=display_name,
            service_type=ServiceType.SQL_DATABASE,
            provider=provider,
            version="unknown",
            endpoint=ServiceEndpoint(
                url=db_url,
                protocol="tcp",
                timeout_seconds=30.0,
            ),
            credentials=ServiceCredentials(
                auth_type="custom",
                custom_data={
                    "connection_string": db_url,
                    "host": host,
                    "port": port,
                },
            ),
            capabilities={
                ServiceCapability.SQL_QUERY,
                ServiceCapability.SQL_WRITE,
            },
            is_enabled=True,
            priority=200,
            tags={"database", "sql", "auto-discovered"},
        )

    def discover_mysql(self) -> List[ServiceMetadata]:
        """Discover MySQL databases from environment variables."""
        discovered = []

        db_url = os.environ.get("MYSQL_URL")
        if db_url:
            service = self._create_sql_database_service(db_url, "MySQL", ServiceProvider.MYSQL)
            discovered.append(service)

        host = os.environ.get("MYSQL_HOST")
        if host:
            port = int(os.environ.get("MYSQL_PORT", "3306"))
            db_name = os.environ.get("MYSQL_DATABASE", "mysql")
            user = os.environ.get("MYSQL_USER", "root")
            password = os.environ.get("MYSQL_PASSWORD")

            from urllib.parse import quote_plus
            pwd_part = f":{quote_plus(password)}" if password else ""
            db_url = f"mysql://{user}{pwd_part}@{host}:{port}/{db_name}"

            service = self._create_sql_database_service(db_url, f"MySQL ({host}:{port})", ServiceProvider.MYSQL)
            discovered.append(service)

        return discovered

    def discover_redis(self) -> List[ServiceMetadata]:
        """Discover Redis services from environment variables."""
        discovered = []

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            service = self._create_redis_service(redis_url, "Redis")
            discovered.append(service)

        host = os.environ.get("REDIS_HOST")
        if host:
            port = int(os.environ.get("REDIS_PORT", "6379"))
            password = os.environ.get("REDIS_PASSWORD")
            db = int(os.environ.get("REDIS_DB", "0"))

            if password:
                redis_url = f"redis://:{password}@{host}:{port}/{db}"
            else:
                redis_url = f"redis://{host}:{port}/{db}"

            service = self._create_redis_service(redis_url, f"Redis ({host}:{port})")
            discovered.append(service)

        return discovered

    def _create_redis_service(self, redis_url: str, display_name: str) -> ServiceMetadata:
        """Create a Redis service metadata."""
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379

        return ServiceMetadata(
            display_name=display_name,
            service_type=ServiceType.CACHE,
            provider=ServiceProvider.REDIS,
            version="unknown",
            endpoint=ServiceEndpoint(
                url=redis_url,
                protocol="tcp",
                timeout_seconds=5.0,
            ),
            credentials=ServiceCredentials(
                auth_type="custom",
                custom_data={"connection_string": redis_url, "host": host, "port": port},
            ),
            capabilities={
                ServiceCapability.FILE_READ,
                ServiceCapability.FILE_WRITE,
                ServiceCapability.FILE_DELETE,
            },
            is_enabled=True,
            priority=200,
            tags={"cache", "redis", "auto-discovered"},
        )

    def discover_qdrant(self) -> List[ServiceMetadata]:
        """Discover Qdrant vector database from environment variables."""
        discovered = []

        qdrant_url = os.environ.get("QDRANT_URL") or os.environ.get("QDRANT_HOST")
        if qdrant_url:
            # Ensure it's a proper URL
            if not qdrant_url.startswith("http"):
                qdrant_url = f"http://{qdrant_url}"
            if not qdrant_url.endswith("/"):
                qdrant_url = f"{qdrant_url}/"

            api_key = os.environ.get("QDRANT_API_KEY")
            headers = {}
            if api_key:
                headers["api-key"] = api_key

            service = ServiceMetadata(
                display_name="Qdrant",
                service_type=ServiceType.VECTOR_DATABASE,
                provider=ServiceProvider.QDRANT,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=qdrant_url,
                    protocol="http",
                    timeout_seconds=30.0,
                    headers=headers,
                ),
                credentials=ServiceCredentials(
                    auth_type="api_key" if api_key else "none",
                    api_key=api_key,
                ),
                capabilities={
                    ServiceCapability.VECTOR_SEARCH,
                    ServiceCapability.VECTOR_INSERT,
                    ServiceCapability.VECTOR_DELETE,
                },
                is_enabled=True,
                priority=150,
                tags={"vector-db", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_chroma(self) -> List[ServiceMetadata]:
        """Discover Chroma vector database from environment variables."""
        discovered = []

        chroma_host = os.environ.get("CHROMA_HOST")
        chroma_port = os.environ.get("CHROMA_PORT", "8000")
        chroma_url = os.environ.get("CHROMA_URL")

        base_url = chroma_url or f"http://{chroma_host}:{chroma_port}" if chroma_host else None
        if base_url:
            service = ServiceMetadata(
                display_name="Chroma",
                service_type=ServiceType.VECTOR_DATABASE,
                provider=ServiceProvider.CHROMA,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=base_url,
                    protocol="http",
                    timeout_seconds=30.0,
                ),
                credentials=ServiceCredentials(auth_type="none"),
                capabilities={
                    ServiceCapability.VECTOR_SEARCH,
                    ServiceCapability.VECTOR_INSERT,
                    ServiceCapability.VECTOR_DELETE,
                },
                is_enabled=True,
                priority=150,
                tags={"vector-db", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_pinecone(self) -> List[ServiceMetadata]:
        """Discover Pinecone vector database from environment variables."""
        discovered = []

        api_key = os.environ.get("PINECONE_API_KEY")
        environment = os.environ.get("PINECONE_ENVIRONMENT")
        if api_key and environment:
            base_url = f"https://{environment}.pinecone.io"

            service = ServiceMetadata(
                display_name=f"Pinecone ({environment})",
                service_type=ServiceType.VECTOR_DATABASE,
                provider=ServiceProvider.PINECONE,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=base_url,
                    protocol="https",
                    timeout_seconds=30.0,
                    headers={"Api-Key": api_key},
                ),
                credentials=ServiceCredentials(
                    auth_type="api_key",
                    api_key=api_key,
                ),
                capabilities={
                    ServiceCapability.VECTOR_SEARCH,
                    ServiceCapability.VECTOR_INSERT,
                    ServiceCapability.VECTOR_DELETE,
                },
                is_enabled=True,
                priority=150,
                tags={"vector-db", "cloud", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_weaviate(self) -> List[ServiceMetadata]:
        """Discover Weaviate vector database from environment variables."""
        discovered = []

        weaviate_url = os.environ.get("WEAVIATE_URL") or os.environ.get("WEAVIATE_HOST")
        if weaviate_url:
            if not weaviate_url.startswith("http"):
                weaviate_url = f"http://{weaviate_url}"
            if not weaviate_url.endswith("/"):
                weaviate_url = f"{weaviate_url}/"

            api_key = os.environ.get("WEAVIATE_API_KEY")
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            service = ServiceMetadata(
                display_name="Weaviate",
                service_type=ServiceType.VECTOR_DATABASE,
                provider=ServiceProvider.WEAVIATE,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=weaviate_url,
                    protocol="https" if weaviate_url.startswith("https") else "http",
                    timeout_seconds=30.0,
                    headers=headers,
                ),
                credentials=ServiceCredentials(
                    auth_type="bearer_token" if api_key else "none",
                    bearer_token=api_key,
                ),
                capabilities={
                    ServiceCapability.VECTOR_SEARCH,
                    ServiceCapability.VECTOR_INSERT,
                    ServiceCapability.VECTOR_DELETE,
                },
                is_enabled=True,
                priority=150,
                tags={"vector-db", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_minio(self) -> List[ServiceMetadata]:
        """Discover MinIO object storage from environment variables."""
        discovered = []

        endpoint = os.environ.get("MINIO_ENDPOINT") or os.environ.get("MINIO_URL")
        access_key = os.environ.get("MINIO_ACCESS_KEY")
        secret_key = os.environ.get("MINIO_SECRET_KEY")

        if endpoint and access_key and secret_key:
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"

            service = ServiceMetadata(
                display_name="MinIO",
                service_type=ServiceType.OBJECT_STORAGE,
                provider=ServiceProvider.MINIO,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=endpoint,
                    protocol="http",
                    timeout_seconds=30.0,
                ),
                credentials=ServiceCredentials(
                    auth_type="custom",
                    custom_data={
                        "access_key": access_key,
                        "secret_key": secret_key,
                        "endpoint": endpoint,
                    },
                ),
                capabilities={
                    ServiceCapability.FILE_READ,
                    ServiceCapability.FILE_WRITE,
                    ServiceCapability.FILE_DELETE,
                    ServiceCapability.FILE_LIST,
                },
                is_enabled=True,
                priority=300,
                tags={"object-storage", "s3-compatible", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_s3(self) -> List[ServiceMetadata]:
        """Discover AWS S3 from environment variables."""
        discovered = []

        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

        if access_key and secret_key:
            endpoint = f"https://s3.{region}.amazonaws.com"

            service = ServiceMetadata(
                display_name=f"AWS S3 ({region})",
                service_type=ServiceType.OBJECT_STORAGE,
                provider=ServiceProvider.S3,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=endpoint,
                    protocol="https",
                    timeout_seconds=30.0,
                ),
                credentials=ServiceCredentials(
                    auth_type="custom",
                    custom_data={
                        "access_key": access_key,
                        "secret_key": secret_key,
                        "region": region,
                    },
                ),
                capabilities={
                    ServiceCapability.FILE_READ,
                    ServiceCapability.FILE_WRITE,
                    ServiceCapability.FILE_DELETE,
                    ServiceCapability.FILE_LIST,
                },
                is_enabled=True,
                priority=300,
                tags={"object-storage", "cloud", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_azure_blob(self) -> List[ServiceMetadata]:
        """Discover Azure Blob Storage from environment variables."""
        discovered = []

        account_name = os.environ.get("AZURE_STORAGE_ACCOUNT")
        account_key = os.environ.get("AZURE_STORAGE_KEY")

        if account_name and account_key:
            endpoint = f"https://{account_name}.blob.core.windows.net"

            service = ServiceMetadata(
                display_name=f"Azure Blob ({account_name})",
                service_type=ServiceType.OBJECT_STORAGE,
                provider=ServiceProvider.AZURE_BLOB,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url=endpoint,
                    protocol="https",
                    timeout_seconds=30.0,
                ),
                credentials=ServiceCredentials(
                    auth_type="custom",
                    custom_data={
                        "account_name": account_name,
                        "account_key": account_key,
                    },
                ),
                capabilities={
                    ServiceCapability.FILE_READ,
                    ServiceCapability.FILE_WRITE,
                    ServiceCapability.FILE_DELETE,
                    ServiceCapability.FILE_LIST,
                },
                is_enabled=True,
                priority=300,
                tags={"object-storage", "cloud", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_gcs(self) -> List[ServiceMetadata]:
        """Discover Google Cloud Storage from environment variables."""
        discovered = []

        credentials_json = os.environ.get("GCS_CREDENTIALS_JSON") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_json:

            service = ServiceMetadata(
                display_name="Google Cloud Storage",
                service_type=ServiceType.OBJECT_STORAGE,
                provider=ServiceProvider.GCS,
                version="unknown",
                endpoint=ServiceEndpoint(
                    url="https://storage.googleapis.com",
                    protocol="https",
                    timeout_seconds=30.0,
                ),
                credentials=ServiceCredentials(
                    auth_type="custom",
                    custom_data={"credentials_path": credentials_json},
                ),
                capabilities={
                    ServiceCapability.FILE_READ,
                    ServiceCapability.FILE_WRITE,
                    ServiceCapability.FILE_DELETE,
                    ServiceCapability.FILE_LIST,
                },
                is_enabled=True,
                priority=300,
                tags={"object-storage", "cloud", "auto-discovered"},
            )
            discovered.append(service)

        return discovered

    def discover_mcp_servers(self) -> List[ServiceMetadata]:
        """Discover MCP (Model Context Protocol) servers from environment and config."""
        discovered = []

        # Check environment variable for MCP servers
        mcp_config = os.environ.get("MCP_SERVERS") or os.environ.get("MCP_CONFIG")
        if mcp_config:
            try:
                import json
                servers = json.loads(mcp_config)
                for server in servers:
                    service = self._create_mcp_service(server)
                    if service:
                        discovered.append(service)
            except json.JSONDecodeError:
                pass

        # Check for local MCP server configs
        mcp_dir = Path.home() / ".config" / "mcp" / "servers"
        if mcp_dir.exists():
            for config_file in mcp_dir.glob("*.json"):
                try:
                    import json
                    with open(config_file) as f:
                        server = json.load(f)
                        service = self._create_mcp_service(server)
                        if service:
                            discovered.append(service)
                except Exception:
                    pass

        return discovered

    def _create_mcp_service(self, server_config: Dict[str, Any]) -> Optional[ServiceMetadata]:
        """Create an MCP server service metadata from config."""
        name = server_config.get("name", "MCP Server")
        command = server_config.get("command")
        args = server_config.get("args", [])
        env = server_config.get("env", {})
        url = server_config.get("url")

        if not (command or url):
            return None

        if url:
            # Remote MCP server
            service = ServiceMetadata(
                display_name=name,
                service_type=ServiceType.MCP,
                provider=ServiceProvider.MCP_REMOTE,
                version="1.0",
                endpoint=ServiceEndpoint(
                    url=url,
                    protocol="https" if url.startswith("https") else "http",
                    timeout_seconds=30.0,
                    headers=env,
                ),
                credentials=ServiceCredentials(
                    auth_type="custom",
                    custom_data={"env": env},
                ),
                capabilities={
                    ServiceCapability.TOOL_EXECUTION,
                    ServiceCapability.RESOURCE_ACCESS,
                    ServiceCapability.PROMPT_TEMPLATES,
                },
                is_enabled=True,
                priority=500,
                tags={"mcp", "remote", "auto-discovered"},
            )
        else:
            # Local MCP server (stdio)
            service = ServiceMetadata(
                display_name=name,
                service_type=ServiceType.MCP,
                provider=ServiceProvider.MCP_LOCAL,
                version="1.0",
                endpoint=ServiceEndpoint(
                    url="stdio://local",
                    protocol="stdio",
                    timeout_seconds=30.0,
                    headers={},
                    custom_data={"command": command, "args": args, "env": env},
                ),
                credentials=ServiceCredentials(auth_type="none"),
                capabilities={
                    ServiceCapability.TOOL_EXECUTION,
                    ServiceCapability.RESOURCE_ACCESS,
                    ServiceCapability.PROMPT_TEMPLATES,
                },
                is_enabled=True,
                priority=500,
                tags={"mcp", "local", "auto-discovered"},
            )

        return service

    # --- Environment-based auto-registration ---

    def auto_discover_and_register(self) -> List[ServiceMetadata]:
        """Auto-discover all services from environment and register them."""
        all_discovered = []

        # Service discovery methods
        discover_methods = [
            self.discover_ollama,
            self.discover_openai,
            self.discover_anthropic,
            self.discover_github,
            self.discover_gitlab,
            self.discover_postgresql,
            self.discover_mysql,
            self.discover_redis,
            self.discover_qdrant,
            self.discover_chroma,
            self.discover_pinecone,
            self.discover_weaviate,
            self.discover_minio,
            self.discover_s3,
            self.discover_azure_blob,
            self.discover_gcs,
            self.discover_mcp_servers,
        ]

        for method in discover_methods:
            try:
                discovered = method()
                for service in discovered:
                    # Only register if not already registered (by type and endpoint)
                    if not self._is_service_registered(service):
                        self.register(service)
                        all_discovered.append(service)
            except Exception as e:
                print(f"[ExternalServiceRegistry] Auto-discovery failed for {method.__name__}: {e}")

        return all_discovered

    def _is_service_registered(self, new_service: ServiceMetadata) -> bool:
        """Check if a similar service is already registered."""
        for existing in self._services.values():
            if (existing.service_type == new_service.service_type and
                existing.provider == new_service.provider and
                existing.endpoint.url == new_service.endpoint.url):
                return True
        return False

    def register_default_services(self) -> List[ServiceMetadata]:
        """Register default services (e.g., local Ollama)."""
        registered = []

        # Always ensure local Ollama is registered as default for OLLAMA type
        ollama_services = self.list(service_type=ServiceType.OLLAMA)
        has_default = any(s.is_default for s in ollama_services)

        if not has_default:
            # Check if Ollama is actually running
            if self._check_ollama_running():
                service = self.discover_ollama()[0]  # First (local) one
                self.register(service)
                registered.append(service)

        return registered

    def _check_ollama_running(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/version", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    # --- NetworkMonitor integration ---

    _network_monitor: Optional[NetworkMonitor] = None

    def set_network_monitor(self, network_monitor: NetworkMonitor) -> None:
        """Set the NetworkMonitor instance for health monitoring integration."""
        self._network_monitor = network_monitor

    def sync_with_network_monitor(self) -> None:
        """Sync registered services with NetworkMonitor for health checks."""
        if not self._network_monitor:
            return

        for service in self._services.values():
            if not service.is_enabled or not service.health_check_enabled:
                continue

            # Create NetworkMonitor ServiceConfig
            nm_service = self._to_network_monitor_config(service)

            # Register if not already in NetworkMonitor
            existing = self._network_monitor.get_service(service.service_id)
            if not existing:
                self._network_monitor.register_service(nm_service)
            else:
                # Update existing
                self._network_monitor.unregister_service(service.service_id)
                self._network_monitor.register_service(nm_service)

    def _to_network_monitor_config(self, service: ServiceMetadata) -> ServiceConfig:
        """Convert ServiceMetadata to NetworkMonitor ServiceConfig."""
        endpoints = []

        if service.endpoint:
            check_type = CheckType.HTTP
            if service.endpoint.protocol == "https":
                check_type = CheckType.HTTPS
            elif service.endpoint.protocol == "tcp":
                check_type = CheckType.TCP

            endpoint = EndpointConfig(
                name=f"{service.service_id}_health",
                url=service.endpoint.url,
                check_type=check_type,
                timeout_seconds=service.health_check_timeout_seconds,
                expected_status_codes=service.expected_status_codes,
                interval_seconds=service.health_check_interval_seconds,
                enabled=service.health_check_enabled,
                labels={
                    "service_type": service.service_type.value,
                    "provider": service.provider.value,
                },
                headers=service.endpoint.headers,
                max_retries=service.endpoint.max_retries,
                retry_delay_seconds=service.endpoint.retry_backoff,
                auth_token=(service.credentials.bearer_token or service.credentials.api_key),
                auth_type=service.credentials.auth_type,
            )
            endpoints.append(endpoint)

            # Add backup URLs as additional endpoints
            for backup_url in service.endpoint.backup_urls:
                backup_endpoint = EndpointConfig(
                    name=f"{service.service_id}_backup_{len(endpoints)}",
                    url=backup_url,
                    check_type=check_type,
                    timeout_seconds=service.health_check_timeout_seconds,
                    expected_status_codes=service.expected_status_codes,
                    interval_seconds=service.health_check_interval_seconds,
                    enabled=service.health_check_enabled,
                    labels={
                        "service_type": service.service_type.value,
                        "provider": service.provider.value,
                        "backup": "true",
                    },
                )
                endpoints.append(backup_endpoint)

        return ServiceConfig(
            name=service.service_id,
            description=service.display_name,
            endpoints=endpoints,
            check_interval_seconds=service.health_check_interval_seconds,
            enabled=service.is_enabled,
            depends_on=[],
            labels={
                "service_type": service.service_type.value,
                "provider": service.provider.value,
            },
            metadata={
                "service_id": service.service_id,
                "capabilities": [c.value for c in service.capabilities],
                "is_default": service.is_default,
                "priority": service.priority,
            },
        )

    def start_health_monitoring(self) -> None:
        """Start background health monitoring for all registered services."""
        if self._network_monitor:
            self.sync_with_network_monitor()
            # NetworkMonitor runs its own background task
            # The background task is started separately

    # --- Persistence ---

    def save_to_file(self, filepath: str) -> bool:
        """Save registry to JSON file."""
        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "services": [service.to_dict() for service in self._services.values()],
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"[ExternalServiceRegistry] Failed to save registry: {e}")
            return False

    def load_from_file(self, filepath: str) -> int:
        """Load registry from JSON file. Returns number of services loaded."""
        try:
            path = Path(filepath)
            if not path.exists():
                return 0

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            for service_data in data.get("services", []):
                try:
                    service = ServiceMetadata.from_dict(service_data)
                    self.register(service)
                    count += 1
                except Exception as e:
                    print(f"[ExternalServiceRegistry] Failed to load service: {e}")

            return count
        except Exception as e:
            print(f"[ExternalServiceRegistry] Failed to load registry: {e}")
            return 0


# Global instance
service_registry = ExternalServiceRegistry()