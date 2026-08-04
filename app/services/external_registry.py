from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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

    def register(self, service: ServiceMetadata) -> None:
        """Register a service."""
        self._services[service.service_id] = service
        if service.is_default:
            self._default_services[service.service_type] = service.service_id

    def unregister(self, service_id: str) -> bool:
        """Unregister a service by ID. Returns True if removed."""
        if service_id in self._services:
            service = self._services.pop(service_id)
            # Remove from default services if it was set as default
            if service.service_type in self._default_services and self._default_services[service.service_type] == service_id:
                del self._default_services[service.service_type]
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
            service.health = health
            return True
        return False

    def update_latency(self, service_id: str, latency_ms: float) -> bool:
        """Update the latency metrics for a service with a successful request."""
        service = self.get(service_id)
        if service:
            service.metrics.update_on_success(latency_ms)
            return True
        return False

    def query_by_capability(self, capability: ServiceCapability) -> List[ServiceMetadata]:
        """Return a list of services that have the specified capability."""
        return [service for service in self._services.values() if capability in service.capabilities]