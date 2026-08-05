"""External Services Registry - Service metadata models and registry.

This module provides the core data models for external services that Freya can access,
and a registry for service registration, discovery, and health tracking.

Integrates with:
- NetworkMonitor (existing service health checking)
- EventBus (service lifecycle events)
- WorldModel (EnvironmentSnapshot services layer)
- ObservabilityHub (health monitoring)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


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


class ServiceProvider(Enum):
    """Well-known service providers."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HUGGINGFACE = "huggingface"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    QDRANT = "qdrant"
    PINECONE = "pinecone"
    WEAVIATE = "weaviate"
    CHROMA = "chroma"
    MILVUS = "milvus"
    REDIS = "redis"
    MEMCACHED = "memcached"
    MINIO = "minio"
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    GCS = "gcs"
    MCP_LOCAL = "mcp_local"
    MCP_REMOTE = "mcp_remote"
    UNKNOWN = "unknown"


class ServiceHealth(Enum):
    """Health status of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    UNREACHABLE = "unreachable"


class ServiceAvailability(Enum):
    """Availability status of a service."""
    AVAILABLE = "available"
    LIMITED = "limited"      # Rate limited, partial functionality
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AuthStatus(Enum):
    """Authentication status for a service."""
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    EXPIRED = "expired"
    INVALID = "invalid"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class ServiceCapability(Enum):
    """Capabilities that a service may provide."""
    # LLM Capabilities
    TEXT_GENERATION = "text_generation"
    CHAT_COMPLETION = "chat_completion"
    EMBEDDING = "embedding"
    TOOL_USE = "tool_use"
    VISION = "vision"
    AUDIO = "audio"
    STREAMING = "streaming"
    FINE_TUNING = "fine_tuning"

    # Code/Version Control
    REPO_READ = "repo_read"
    REPO_WRITE = "repo_write"
    ISSUE_MANAGEMENT = "issue_management"
    PR_MANAGEMENT = "pr_management"
    CI_CD = "ci_cd"
    CODE_SEARCH = "code_search"
    GIT_OPERATIONS = "git_operations"

    # Database
    SQL_QUERY = "sql_query"
    SQL_WRITE = "sql_write"
    VECTOR_SEARCH = "vector_search"
    VECTOR_INSERT = "vector_insert"
    VECTOR_DELETE = "vector_delete"

    # Storage
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    FILE_LIST = "file_list"

    # Knowledge/Search
    SEMANTIC_SEARCH = "semantic_search"
    KEYWORD_SEARCH = "keyword_search"
    DOCUMENT_INDEXING = "document_indexing"
    DOCUMENT_RETRIEVAL = "document_retrieval"

    # MCP
    TOOL_EXECUTION = "tool_execution"
    RESOURCE_ACCESS = "resource_access"
    PROMPT_TEMPLATES = "prompt_templates"

    # General
    HEALTH_CHECK = "health_check"
    METRICS = "metrics"
    CONFIGURATION = "configuration"


@dataclass
class ServiceEndpoint:
    """Network endpoint configuration for a service."""
    url: str
    protocol: str = "https"  # http, https, ws, wss, tcp, unix
    headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 1.0
    verify_ssl: bool = True
    # For local/unix socket services
    socket_path: Optional[str] = None
    # For services with multiple endpoints (load balancing)
    backup_urls: List[str] = field(default_factory=list)


@dataclass
class ServiceCredentials:
    """Authentication credentials for a service."""
    auth_type: str = "none"  # none, api_key, bearer_token, basic, oauth2, jwt, custom
    api_key: Optional[str] = None
    bearer_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    oauth2_client_id: Optional[str] = None
    oauth2_client_secret: Optional[str] = None
    oauth2_token_url: Optional[str] = None
    oauth2_scopes: List[str] = field(default_factory=list)
    custom_headers: Dict[str, str] = field(default_factory=dict)
    custom_data: Dict[str, Any] = field(default_factory=dict)
    # Metadata
    expires_at: Optional[str] = None  # ISO timestamp
    last_refreshed: Optional[str] = None
    status: AuthStatus = AuthStatus.UNKNOWN


@dataclass
class ServiceMetrics:
    """Runtime metrics for a service."""
    # Latency
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    # Throughput
    requests_per_second: float = 0.0
    successful_requests: int = 0
    failed_requests: int = 0
    total_requests: int = 0

    # Error tracking
    error_rate: float = 0.0
    last_error: Optional[str] = None
    last_error_at: Optional[str] = None
    consecutive_failures: int = 0

    # Availability
    uptime_percentage: float = 100.0
    last_check_at: Optional[str] = None
    last_success_at: Optional[str] = None

    # Resource usage (if available)
    cpu_usage_percent: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    disk_usage_mb: Optional[float] = None

    # Rate limiting
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset_at: Optional[str] = None
    rate_limit_limit: Optional[int] = None

    def update_on_success(self, latency_ms: float) -> None:
        """Update metrics on successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.last_success_at = datetime.now(timezone.utc).isoformat()
        # Simple running average
        self.avg_latency_ms = (self.avg_latency_ms * (self.total_requests - 1) + latency_ms) / self.total_requests
        if self.total_requests > 0:
            self.error_rate = self.failed_requests / self.total_requests

    def update_on_failure(self, error: str) -> None:
        """Update metrics on failed request."""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.last_error = error
        self.last_error_at = datetime.now(timezone.utc).isoformat()
        if self.total_requests > 0:
            self.error_rate = self.failed_requests / self.total_requests


@dataclass
class ServiceInfo:
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
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "p50_latency_ms": self.metrics.p50_latency_ms,
                "p95_latency_ms": self.metrics.p95_latency_ms,
                "p99_latency_ms": self.metrics.p99_latency_ms,
                "requests_per_second": self.metrics.requests_per_second,
                "successful_requests": self.metrics.successful_requests,
                "failed_requests": self.metrics.failed_requests,
                "total_requests": self.metrics.total_requests,
                "error_rate": self.metrics.error_rate,
                "last_error": self.metrics.last_error,
                "last_error_at": self.metrics.last_error_at,
                "consecutive_failures": self.metrics.consecutive_failures,
                "uptime_percentage": self.metrics.uptime_percentage,
                "last_check_at": self.metrics.last_check_at,
                "last_success_at": self.metrics.last_success_at,
                "cpu_usage_percent": self.metrics.cpu_usage_percent,
                "memory_usage_mb": self.metrics.memory_usage_mb,
                "disk_usage_mb": self.metrics.disk_usage_mb,
                "rate_limit_remaining": self.metrics.rate_limit_remaining,
                "rate_limit_reset_at": self.metrics.rate_limit_reset_at,
                "rate_limit_limit": self.metrics.rate_limit_limit,
            },
            "is_enabled": self.is_enabled,
            "is_default": self.is_default,
            "priority": self.priority,
            "tags": list(self.tags),
            "metadata": self.metadata,
            "health_check_enabled": self.health_check_enabled,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "health_check_timeout_seconds": self.health_check_timeout_seconds,
            "health_check_path": self.health_check_path,
            "expected_status_codes": self.expected_status_codes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceInfo":
        """Create ServiceInfo from dictionary."""
        # Parse enums
        service_type = ServiceType(data.get("service_type", "custom"))
        provider = ServiceProvider(data.get("provider", "unknown"))
        availability = ServiceAvailability(data.get("availability", "unknown"))
        health = ServiceHealth(data.get("health", "unknown"))
        auth_status = AuthStatus(data.get("auth_status", "unknown"))

        # Parse endpoint
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

        # Parse credentials
        cred_data = data.get("credentials")
        credentials = None
        if cred_data:
            credentials = ServiceCredentials(
                auth_type=cred_data.get("auth_type", "none"),
                api_key=cred_data.get("api_key"),
                bearer_token=cred_data.get("bearer_token"),
                username=cred_data.get("username"),
                password=cred_data.get("password"),
                oauth2_client_id=cred_data.get("oauth2_client_id"),
                oauth2_client_secret=cred_data.get("oauth2_client_secret"),
                oauth2_token_url=cred_data.get("oauth2_token_url"),
                oauth2_scopes=cred_data.get("oauth2_scopes", []),
                custom_headers=cred_data.get("custom_headers", {}),
                custom_data=cred_data.get("custom_data", {}),
                expires_at=cred_data.get("expires_at"),
                last_refreshed=cred_data.get("last_refreshed"),
                status=AuthStatus(cred_data.get("status", "unknown")),
            )

        # Parse metrics
        metrics_data = data.get("metrics", {})
        metrics = ServiceMetrics(
            avg_latency_ms=metrics_data.get("avg_latency_ms", 0.0),
            p50_latency_ms=metrics_data.get("p50_latency_ms", 0.0),
            p95_latency_ms=metrics_data.get("p95_latency_ms", 0.0),
            p99_latency_ms=metrics_data.get("p99_latency_ms", 0.0),
            requests_per_second=metrics_data.get("requests_per_second", 0.0),
            successful_requests=metrics_data.get("successful_requests", 0),
            failed_requests=metrics_data.get("failed_requests", 0),
            total_requests=metrics_data.get("total_requests", 0),
            error_rate=metrics_data.get("error_rate", 0.0),
            last_error=metrics_data.get("last_error"),
            last_error_at=metrics_data.get("last_error_at"),
            consecutive_failures=metrics_data.get("consecutive_failures", 0),
            uptime_percentage=metrics_data.get("uptime_percentage", 100.0),
            last_check_at=metrics_data.get("last_check_at"),
            last_success_at=metrics_data.get("last_success_at"),
            cpu_usage_percent=metrics_data.get("cpu_usage_percent"),
            memory_usage_mb=metrics_data.get("memory_usage_mb"),
            disk_usage_mb=metrics_data.get("disk_usage_mb"),
            rate_limit_remaining=metrics_data.get("rate_limit_remaining"),
            rate_limit_reset_at=metrics_data.get("rate_limit_reset_at"),
            rate_limit_limit=metrics_data.get("rate_limit_limit"),
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
            metrics=metrics,
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

    def has_capability(self, capability: ServiceCapability) -> bool:
        """Check if service has a specific capability."""
        return capability in self.capabilities

    def has_any_capability(self, capabilities: List[ServiceCapability]) -> bool:
        """Check if service has any of the listed capabilities."""
        return any(c in self.capabilities for c in capabilities)

    def has_all_capabilities(self, capabilities: List[ServiceCapability]) -> bool:
        """Check if service has all listed capabilities."""
        return all(c in self.capabilities for c in capabilities)

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


# Event types for service lifecycle
class ServiceEventType(Enum):
    """Event types for service lifecycle events."""
    REGISTERED = "service.registered"
    UNREGISTERED = "service.unregistered"
    UPDATED = "service.updated"
    HEALTH_CHANGED = "service.health_changed"
    AVAILABILITY_CHANGED = "service.availability_changed"
    AUTH_CHANGED = "service.auth_changed"
    METRICS_UPDATED = "service.metrics_updated"
    CAPABILITY_ADDED = "service.capability_added"
    CAPABILITY_REMOVED = "service.capability_removed"
    SET_AS_DEFAULT = "service.set_as_default"
    UNSET_AS_DEFAULT = "service.unset_as_default"
    ENABLED = "service.enabled"
    DISABLED = "service.disabled"


# Query filters for service discovery
@dataclass
class ServiceQuery:
    """Query parameters for service discovery."""
    service_types: Optional[List[ServiceType]] = None
    providers: Optional[List[ServiceProvider]] = None
    capabilities: Optional[List[ServiceCapability]] = None
    availability: Optional[List[ServiceAvailability]] = None
    health: Optional[List[ServiceHealth]] = None
    auth_status: Optional[List[AuthStatus]] = None
    tags: Optional[List[str]] = None
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    min_priority: Optional[int] = None
    max_priority: Optional[int] = None
    require_all_capabilities: bool = False  # If True, service must have ALL capabilities
    limit: Optional[int] = None
    offset: int = 0
    sort_by: str = "priority"  # priority, health, availability, last_used, registered_at
    sort_desc: bool = False


# Type aliases for convenience
ServiceInfoDict = Dict[str, Any]
ServiceList = List[ServiceInfo]