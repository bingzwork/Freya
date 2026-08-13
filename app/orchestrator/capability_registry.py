
"""
CapabilityRegistry - Registry for workflow capabilities.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from threading import RLock

from app.core.logger import logger


class CapabilityCategory(Enum):
    """Categories of capabilities."""
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


class CapabilityState(Enum):
    """State of a capability."""
    INACTIVE = "inactive"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    DEACTIVATING = "deactivating"
    ERROR = "error"


class CapabilityHealth(Enum):
    """Health status of a capability."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class CapabilityRegistration:
    """Registration info for a capability."""
    capability: 'Capability'
    registered_by: str = "user"
    registered_at: str = ""


@dataclass
class CapabilityMetadata:
    """Metadata for a capability."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: CapabilityCategory = CapabilityCategory.CUSTOM
    is_singleton: bool = False
    auto_discoverable: bool = True
    default_action: str = "execute"
    supported_actions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    # Compatibility fields consumed by the production workflow composer.
    depends_on: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)
    timeout_seconds: float = 30.0


class Capability:
    """A registered capability."""

    def __init__(
        self,
        metadata: CapabilityMetadata,
        handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.metadata = metadata
        self._handler = handler
        self.state = CapabilityState.INACTIVE

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def category(self) -> CapabilityCategory:
        return self.metadata.category

    def execute(self, action: str, inputs: Dict[str, Any]) -> Any:
        """Execute a capability action."""
        if self._handler:
            return self._handler(inputs)
        raise NotImplementedError(f"Action '{action}' not implemented")

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        self.state = CapabilityState.ACTIVE
        return True

    def _deactivate(self) -> bool:
        self.state = CapabilityState.INACTIVE
        return True


class CapabilityRegistry:
    """Registry for managing workflow capabilities."""

    _instance: Optional['CapabilityRegistry'] = None
    _lock = RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._capabilities: Dict[str, Capability] = {}
        self._running = False
        self._initialized = True

    def register(self, capability: Capability) -> bool:
        """Register a capability."""
        if capability.name in self._capabilities:
            logger.warning(f"[CapabilityRegistry] Capability '{capability.name}' already exists, replacing")
        self._capabilities[capability.name] = capability
        logger.info(f"[CapabilityRegistry] Registered capability: {capability.name}")
        return True

    def unregister(self, name: str) -> bool:
        """Unregister a capability."""
        if name in self._capabilities:
            del self._capabilities[name]
            logger.info(f"[CapabilityRegistry] Unregistered capability: {name}")
            return True
        return False

    def get_capability(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        return self._capabilities.get(name)

    def list_capabilities(self, category: Optional[CapabilityCategory] = None, active_only: bool = False) -> List[CapabilityMetadata]:
        """List all registered capability metadata."""
        results = []
        for cap in self._capabilities.values():
            if active_only and cap.state != CapabilityState.ACTIVE:
                continue
            if category is None or cap.category == category:
                results.append(cap.metadata)
        return results

    def get_all(self) -> Dict[str, Capability]:
        """Get all capabilities."""
        return dict(self._capabilities)

    def get_capabilities_by_category(
        self,
        category: CapabilityCategory,
        active_only: bool = True,
    ) -> List[Capability]:
        """Return registered capability objects for workflow composition."""
        return [
            capability
            for capability in self._capabilities.values()
            if capability.category == category
            and (not active_only or capability.state == CapabilityState.ACTIVE)
        ]

    def start(self) -> None:
        """Start the registry."""
        self._running = True
        for cap in self._capabilities.values():
            cap._initialize()
            if cap._activate():
                cap.state = CapabilityState.ACTIVE
        logger.info("[CapabilityRegistry] Started")

    def stop(self) -> None:
        """Stop the registry."""
        for cap in self._capabilities.values():
            cap._deactivate()
        self._running = False
        logger.info("[CapabilityRegistry] Stopped")

    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        active_count = sum(1 for c in self._capabilities.values() if c.state == CapabilityState.ACTIVE)
        return {
            "total_capabilities": len(self._capabilities),
            "active_capabilities": active_count,
            "running": self._running,
        }


def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry instance."""
    return CapabilityRegistry()


def reset_capability_registry() -> None:
    """Reset the global capability registry instance (for testing)."""
    with CapabilityRegistry._lock:
        if CapabilityRegistry._instance:
            CapabilityRegistry._instance.stop()
        CapabilityRegistry._instance = None
