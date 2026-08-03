"""Runtime Capability Registry for the Central Autonomous Orchestrator.

This module provides a dynamic runtime capability registry that complements the
audit-focused CapabilityRegistry in app/audit/capability_registry.py. This
registry focuses on:
- Automatic discovery of capabilities at runtime
- Capability lifecycle management (register, activate, deactivate, health check)
- Dependency resolution between capabilities
- Capability health monitoring
- Dynamic workflow composition from available capabilities
"""

import asyncio
import logging
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union
from uuid import uuid4

from app.core.events import get_event_bus, Event, EventPriority
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus, ComponentInfo, ComponentType
from app.core.background_jobs import get_job_service, JobTriggerConfig, JobTriggerType, JobPriority


logger = logging.getLogger(__name__)


class CapabilityState(Enum):
    """Lifecycle state of a capability."""
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DEACTIVATED = "deactivated"
    ERROR = "error"
    UNLOADING = "unloading"


class CapabilityCategory(Enum):
    """Categories of capabilities for organization and routing."""
    MEMORY = "memory"
    PLANNING = "planning"
    EXECUTION = "execution"
    DECISION = "decision"
    LEARNING = "learning"
    MONITORING = "monitoring"
    COMMUNICATION = "communication"
    TOOL = "tool"
    SAFETY = "safety"
    KNOWLEDGE = "knowledge"
    REASONING = "reasoning"
    ORCHESTRATION = "orchestration"
    RECOVERY = "recovery"
    CUSTOM = "custom"


@dataclass
class CapabilityMetadata:
    """Rich metadata for a capability."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: CapabilityCategory = CapabilityCategory.CUSTOM
    author: str = "freya"
    tags: List[str] = field(default_factory=list)

    # Dependencies
    depends_on: List[str] = field(default_factory=list)  # Capability names
    conflicts_with: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)  # Interfaces/APIs provided

    # Runtime characteristics
    is_async: bool = True
    is_stateful: bool = False
    is_singleton: bool = True
    max_concurrency: int = 1
    timeout_seconds: float = 30.0

    # Resource requirements
    required_resources: List[str] = field(default_factory=list)
    resource_limits: Dict[str, Any] = field(default_factory=dict)

    # Health and monitoring
    health_check_interval: float = 30.0
    degradation_threshold: float = 0.8  # Success rate below this = degraded

    # Configuration
    config_schema: Dict[str, Any] = field(default_factory=dict)
    default_config: Dict[str, Any] = field(default_factory=dict)

    # Discovery
    auto_discoverable: bool = True
    discovery_keywords: List[str] = field(default_factory=list)

    # Extension points
    extension_points: List[str] = field(default_factory=list)
    extends: Optional[str] = None  # Name of capability being extended

    # Default action for workflow composition
    default_action: str = ""
    supported_actions: List[str] = field(default_factory=list)


@dataclass
class CapabilityHealth:
    """Health status of a capability."""
    capability_name: str
    state: CapabilityState = CapabilityState.UNREGISTERED
    last_check: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    uptime_seconds: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    last_error: Optional[str] = None
    last_success: Optional[str] = None
    avg_latency_ms: float = 0.0
    custom_metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def is_healthy(self) -> bool:
        return self.state == CapabilityState.ACTIVE and self.success_rate >= 0.5


class Capability(ABC):
    """Base class for all capabilities."""

    def __init__(self, metadata: CapabilityMetadata):
        self.metadata = metadata
        self._state = CapabilityState.REGISTERED
        self._config = metadata.default_config.copy()
        self._health = CapabilityHealth(capability_name=metadata.name)
        self._lock = threading.RLock()
        self._start_time: Optional[float] = None
        self._event_bus = get_event_bus()

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def state(self) -> CapabilityState:
        with self._lock:
            return self._state

    @property
    def health(self) -> CapabilityHealth:
        with self._lock:
            self._health.uptime_seconds = time.time() - self._start_time if self._start_time else 0
            return self._health

    @property
    def config(self) -> Dict[str, Any]:
        with self._lock:
            return self._config.copy()

    def configure(self, config: Dict[str, Any]) -> bool:
        """Configure the capability. Returns True if successful."""
        with self._lock:
            # Validate against schema if provided
            if self.metadata.config_schema:
                if not self._validate_config(config):
                    return False
            self._config.update(config)
            return True

    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate config against schema. Override for custom validation."""
        return True

    def initialize(self) -> bool:
        """Initialize the capability. Called once after registration."""
        with self._lock:
            if self._state != CapabilityState.REGISTERED:
                return False
            self._state = CapabilityState.INITIALIZING

        try:
            result = self._initialize()
            with self._lock:
                if result:
                    self._state = CapabilityState.ACTIVE
                    self._start_time = time.time()
                    self._health.state = CapabilityState.ACTIVE
                    self._publish_event("capability.activated", {"capability": self.name})
                else:
                    self._state = CapabilityState.ERROR
                    self._health.state = CapabilityState.ERROR
            return result
        except Exception as e:
            logger.error(f"Failed to initialize capability {self.name}: {e}")
            with self._lock:
                self._state = CapabilityState.ERROR
                self._health.state = CapabilityState.ERROR
                self._health.last_error = str(e)
            return False

    @abstractmethod
    def _initialize(self) -> bool:
        """Subclass implementation of initialization."""
        pass

    def activate(self) -> bool:
        """Activate the capability."""
        with self._lock:
            if self._state not in (CapabilityState.REGISTERED, CapabilityState.DEACTIVATED):
                return False
            self._state = CapabilityState.INITIALIZING

        try:
            result = self._activate()
            with self._lock:
                if result:
                    self._state = CapabilityState.ACTIVE
                    self._start_time = time.time()
                    self._health.state = CapabilityState.ACTIVE
                    self._publish_event("capability.activated", {"capability": self.name})
                else:
                    self._state = CapabilityState.ERROR
                    self._health.state = CapabilityState.ERROR
            return result
        except Exception as e:
            logger.error(f"Failed to activate capability {self.name}: {e}")
            with self._lock:
                self._state = CapabilityState.ERROR
                self._health.state = CapabilityState.ERROR
                self._health.last_error = str(e)
            return False

    @abstractmethod
    def _activate(self) -> bool:
        """Subclass implementation of activation."""
        pass

    def deactivate(self) -> bool:
        """Deactivate the capability gracefully."""
        with self._lock:
            if self._state != CapabilityState.ACTIVE:
                return False
            self._state = CapabilityState.DEACTIVATED

        try:
            result = self._deactivate()
            with self._lock:
                if result:
                    self._state = CapabilityState.DEACTIVATED
                    self._health.state = CapabilityState.DEACTIVATED
                    self._publish_event("capability.deactivated", {"capability": self.name})
                else:
                    self._state = CapabilityState.ERROR
                    self._health.state = CapabilityState.ERROR
            return result
        except Exception as e:
            logger.error(f"Failed to deactivate capability {self.name}: {e}")
            with self._lock:
                self._state = CapabilityState.ERROR
                self._health.state = CapabilityState.ERROR
                self._health.last_error = str(e)
            return False

    @abstractmethod
    def _deactivate(self) -> bool:
        """Subclass implementation of deactivation."""
        pass

    def health_check(self) -> CapabilityHealth:
        """Perform health check. Override for custom logic."""
        with self._lock:
            self._health.last_check = datetime.now(timezone.utc).isoformat()
            self._health.uptime_seconds = time.time() - self._start_time if self._start_time else 0

            # Auto-degrade based on success rate
            if self._health.success_rate < self.metadata.degradation_threshold:
                if self._state == CapabilityState.ACTIVE:
                    self._state = CapabilityState.DEGRADED
                    self._health.state = CapabilityState.DEGRADED
            elif self._state == CapabilityState.DEGRADED and self._health.success_rate >= self.metadata.degradation_threshold:
                self._state = CapabilityState.ACTIVE
                self._health.state = CapabilityState.ACTIVE

            return self._health

    def record_success(self, latency_ms: float = 0.0):
        """Record a successful operation."""
        with self._lock:
            self._health.success_count += 1
            self._health.last_success = datetime.now(timezone.utc).isoformat()
            # Update rolling average latency
            if self._health.avg_latency_ms == 0:
                self._health.avg_latency_ms = latency_ms
            else:
                self._health.avg_latency_ms = 0.9 * self._health.avg_latency_ms + 0.1 * latency_ms

    def record_failure(self, error: str):
        """Record a failed operation."""
        with self._lock:
            self._health.failure_count += 1
            self._health.last_error = error
            self._health.last_check = datetime.now(timezone.utc).isoformat()

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source=self.name,
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.deactivate()


@dataclass
class CapabilityRegistration:
    """Registration record for a capability."""
    capability: Capability
    metadata: CapabilityMetadata
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    registered_by: str = "system"
    instance_id: str = field(default_factory=lambda: uuid4().hex[:8])


class CapabilityRegistry:
    """
    Runtime Capability Registry with automatic discovery, lifecycle management,
    dependency resolution, and health monitoring.

    This is the PRIMARY extension mechanism for the Freya architecture.
    All capabilities MUST register here to participate in orchestration.
    """

    def __init__(self, auto_discovery: bool = True, health_check_interval: float = 30.0):
        self._capabilities: Dict[str, CapabilityRegistration] = {}
        self._capability_index: Dict[CapabilityCategory, Set[str]] = defaultdict(set)
        self._provides_index: Dict[str, Set[str]] = defaultdict(set)  # interface -> capability names
        self._lock = threading.RLock()
        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()
        self._job_service = get_job_service()

        self._auto_discovery = auto_discovery
        self._health_check_interval = health_check_interval
        self._health_check_job_id: Optional[str] = None
        self._running = False

        # Dependency resolution cache
        self._resolution_cache: Dict[str, List[str]] = {}
        self._cache_valid = False

    def start(self):
        """Start the registry (health checks, auto-discovery)."""
        with self._lock:
            if self._running:
                return
            self._running = True

        # Register health check with observability
        self._observability.add_health_check(HealthCheck(
            name="capability_registry_health",
            component="capability_registry",
            check_func=self._registry_health_check,
            interval_seconds=self._health_check_interval,
        ))

        # Schedule periodic health checks for all capabilities
        self._health_check_job_id = self._job_service.schedule(
            job_id="capability_registry_health_checks",
            func=self._run_health_checks,
            trigger=JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=self._health_check_interval),
            priority=JobPriority.NORMAL,
            replace_existing=True,
        )

        # Register self with observability
        self._observability.register_component(ComponentInfo(
            name="CapabilityRegistry",
            component_type=ComponentType.SERVICE,
            version="1.0.0",
            description="Runtime capability registry for dynamic orchestration",
            metadata={}
        ))

        logger.info("CapabilityRegistry started")

    def stop(self):
        """Stop the registry and deactivate all capabilities."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Cancel health check job
        if self._health_check_job_id:
            self._job_service.cancel_job(self._health_check_job_id)

        # Deactivate all capabilities
        for name in list(self._capabilities.keys()):
            self.deactivate_capability(name)

        logger.info("CapabilityRegistry stopped")

    def register(self, capability: Capability, registered_by: str = "system") -> bool:
        """
        Register a capability.

        Args:
            capability: The Capability instance to register
            registered_by: Identifier of what registered this (e.g., "plugin:my_plugin", "system")

        Returns:
            True if registration successful, False otherwise
        """
        with self._lock:
            name = capability.metadata.name

            if name in self._capabilities:
                logger.warning(f"Capability {name} already registered, replacing")

            # Check dependencies
            if not self._check_dependencies(capability.metadata):
                logger.error(f"Cannot register {name}: missing dependencies")
                return False

            # Check conflicts
            if not self._check_conflicts(capability.metadata):
                logger.error(f"Cannot register {name}: conflicts with existing capabilities")
                return False

            # Create registration record
            registration = CapabilityRegistration(
                capability=capability,
                metadata=capability.metadata,
                registered_by=registered_by
            )

            self._capabilities[name] = registration
            self._capability_index[capability.metadata.category].add(name)

            # Index provided interfaces
            for interface in capability.metadata.provides:
                self._provides_index[interface].add(name)

            # Invalidate resolution cache
            self._cache_valid = False

            # Initialize the capability
            init_success = capability.initialize()

            if not init_success:
                # Rollback registration
                del self._capabilities[name]
                self._capability_index[capability.metadata.category].discard(name)
                for interface in capability.metadata.provides:
                    self._provides_index[interface].discard(name)
                logger.error(f"Failed to initialize capability {name}")
                return False

            self._publish_event("capability.registered", {
                "capability": name,
                "category": capability.metadata.category.value,
                "version": capability.metadata.version,
                "registered_by": registered_by
            })

            logger.info(f"Registered capability: {name} ({capability.metadata.category.value})")
            return True

    def unregister(self, name: str) -> bool:
        """Unregister a capability."""
        with self._lock:
            if name not in self._capabilities:
                return False

            registration = self._capabilities[name]

            # Deactivate first
            registration.capability.deactivate()

            # Remove from indexes
            del self._capabilities[name]
            self._capability_index[registration.metadata.category].discard(name)
            for interface in registration.metadata.provides:
                self._provides_index[interface].discard(name)

            self._cache_valid = False

            self._publish_event("capability.unregistered", {"capability": name})

            logger.info(f"Unregistered capability: {name}")
            return True

    def get_capability(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        with self._lock:
            reg = self._capabilities.get(name)
            return reg.capability if reg else None

    def get_capability_metadata(self, name: str) -> Optional[CapabilityMetadata]:
        """Get capability metadata by name."""
        with self._lock:
            reg = self._capabilities.get(name)
            return reg.metadata if reg else None

    def list_capabilities(self, category: Optional[CapabilityCategory] = None,
                          state: Optional[CapabilityState] = None,
                          active_only: bool = False) -> List[CapabilityMetadata]:
        """List capabilities with optional filtering."""
        with self._lock:
            results = []
            for reg in self._capabilities.values():
                if category and reg.metadata.category != category:
                    continue
                if state and reg.capability.state != state:
                    continue
                if active_only and reg.capability.state != CapabilityState.ACTIVE:
                    continue
                results.append(reg.metadata)
            return results

    def get_capabilities_by_category(self, category: CapabilityCategory) -> List[Capability]:
        """Get all active capabilities in a category."""
        with self._lock:
            names = self._capability_index.get(category, set())
            return [self._capabilities[n].capability for n in names
                    if n in self._capabilities and self._capabilities[n].capability.state == CapabilityState.ACTIVE]

    def find_capabilities_providing(self, interface: str) -> List[Capability]:
        """Find all active capabilities providing an interface."""
        with self._lock:
            names = self._provides_index.get(interface, set())
            return [self._capabilities[n].capability for n in names
                    if n in self._capabilities and self._capabilities[n].capability.state == CapabilityState.ACTIVE]

    def find_capabilities_by_keywords(self, keywords: List[str]) -> List[Capability]:
        """Find capabilities matching discovery keywords."""
        with self._lock:
            results = []
            for reg in self._capabilities.values():
                if not reg.metadata.auto_discoverable:
                    continue
                if reg.capability.state != CapabilityState.ACTIVE:
                    continue
                if any(kw.lower() in ' '.join(reg.metadata.discovery_keywords).lower() for kw in keywords):
                    results.append(reg.capability)
            return results

    def _check_dependencies(self, metadata: CapabilityMetadata) -> bool:
        """Check if all dependencies are satisfied."""
        for dep in metadata.depends_on:
            if dep not in self._capabilities:
                return False
            if self._capabilities[dep].capability.state != CapabilityState.ACTIVE:
                return False
        return True

    def _check_conflicts(self, metadata: CapabilityMetadata) -> bool:
        """Check for conflicts with existing capabilities."""
        for conflict in metadata.conflicts_with:
            if conflict in self._capabilities:
                existing = self._capabilities[conflict]
                if existing.capability.state in (CapabilityState.ACTIVE, CapabilityState.INITIALIZING):
                    return False
        return True

    def resolve_dependencies(self, capability_name: str) -> List[str]:
        """
        Resolve dependency order for a capability.
        Returns list of capability names in activation order.
        """
        with self._lock:
            if capability_name in self._resolution_cache and self._cache_valid:
                return self._resolution_cache[capability_name]

            visited = set()
            visiting = set()
            result = []

            def visit(name: str):
                if name in visiting:
                    raise ValueError(f"Circular dependency detected involving {name}")
                if name in visited or name not in self._capabilities:
                    return

                visiting.add(name)
                for dep in self._capabilities[name].metadata.depends_on:
                    visit(dep)
                visiting.remove(name)
                visited.add(name)
                result.append(name)

            visit(capability_name)
            self._resolution_cache[capability_name] = result
            return result

    def activate_capability(self, name: str) -> bool:
        """Activate a capability and its dependencies."""
        with self._lock:
            if name not in self._capabilities:
                return False

            # Resolve and activate dependencies first
            dep_order = self.resolve_dependencies(name)
            for dep_name in dep_order:
                if dep_name != name:
                    dep_cap = self._capabilities[dep_name].capability
                    if dep_cap.state != CapabilityState.ACTIVE:
                        if not dep_cap.activate():
                            logger.error(f"Failed to activate dependency {dep_name}")
                            return False

            # Activate the capability itself
            return self._capabilities[name].capability.activate()

    def deactivate_capability(self, name: str, force: bool = False) -> bool:
        """Deactivate a capability."""
        with self._lock:
            if name not in self._capabilities:
                return False

            # Check if other active capabilities depend on this
            if not force:
                for reg in self._capabilities.values():
                    if reg.capability.state == CapabilityState.ACTIVE and name in reg.metadata.depends_on:
                        logger.warning(f"Cannot deactivate {name}: required by {reg.metadata.name}")
                        return False

            return self._capabilities[name].capability.deactivate()

    def _run_health_checks(self):
        """Run health checks on all active capabilities."""
        with self._lock:
            active_caps = [
                (name, reg.capability) for name, reg in self._capabilities.items()
                if reg.capability.state in (CapabilityState.ACTIVE, CapabilityState.DEGRADED)
            ]

        for name, cap in active_caps:
            try:
                health = cap.health_check()
                # Update observability metrics
                self._observability.record_metric(f"capability.{name}.success_rate", health.success_rate)
                self._observability.record_metric(f"capability.{name}.latency_ms", health.avg_latency_ms)
                self._observability.record_metric(f"capability.{name}.state", health.state.value)

                if health.state == CapabilityState.ERROR:
                    self._publish_event("capability.error", {
                        "capability": name,
                        "error": health.last_error
                    })
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")

    def _registry_health_check(self) -> HealthResult:
        """Health check for the registry itself."""
        try:
            with self._lock:
                total = len(self._capabilities)
                active = sum(1 for r in self._capabilities.values() if r.capability.state == CapabilityState.ACTIVE)
                degraded = sum(1 for r in self._capabilities.values() if r.capability.state == CapabilityState.DEGRADED)
                error = sum(1 for r in self._capabilities.values() if r.capability.state == CapabilityState.ERROR)

            if error > 0:
                return HealthResult(
                    name="capability_registry_health",
                    component="capability_registry",
                    status=HealthStatus.DEGRADED,
                    message=f"{error} capabilities in error state",
                    metadata={"total": total, "active": active, "degraded": degraded, "error": error}
                )
            elif degraded > 0:
                return HealthResult(
                    name="capability_registry_health",
                    component="capability_registry",
                    status=HealthStatus.DEGRADED,
                    message=f"{degraded} capabilities degraded",
                    metadata={"total": total, "active": active, "degraded": degraded, "error": error}
                )
            else:
                return HealthResult(
                    name="capability_registry_health",
                    component="capability_registry",
                    status=HealthStatus.HEALTHY,
                    message=f"All {active} capabilities healthy",
                    metadata={"total": total, "active": active, "degraded": degraded, "error": error}
                )
        except Exception as e:
            return HealthResult(
                name="capability_registry_health",
                component="capability_registry",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish an event to the event bus."""
        try:
            event = Event(
                name=event_type,
                data=payload,
                source="capability_registry",
                priority=EventPriority.NORMAL
            )
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_type}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            stats = {
                "total_capabilities": len(self._capabilities),
                "by_category": {},
                "by_state": {},
                "capabilities": []
            }

            for state in CapabilityState:
                stats["by_state"][state.value] = 0

            for cat in CapabilityCategory:
                stats["by_category"][cat.value] = 0

            for reg in self._capabilities.values():
                state = reg.capability.state.value
                cat = reg.metadata.category.value
                stats["by_state"][state] = stats["by_state"].get(state, 0) + 1
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

                stats["capabilities"].append({
                    "name": reg.metadata.name,
                    "version": reg.metadata.version,
                    "category": cat,
                    "state": state,
                    "health": {
                        "success_rate": reg.capability.health.success_rate,
                        "uptime_seconds": reg.capability.health.uptime_seconds,
                        "avg_latency_ms": reg.capability.health.avg_latency_ms
                    }
                })

            return stats


# Global registry instance
_registry_instance: Optional[CapabilityRegistry] = None
_registry_lock = threading.Lock()


def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry instance."""
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = CapabilityRegistry()
        return _registry_instance


def reset_capability_registry() -> None:
    """Reset the global registry instance (for testing)."""
    global _registry_instance
    with _registry_lock:
        if _registry_instance:
            _registry_instance.stop()
        _registry_instance = None