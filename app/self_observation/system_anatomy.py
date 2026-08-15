"""Factual introspection of Freya's currently registered runtime system.

The anatomy is a read-only projection of existing registries.  It is not a
second component or capability registry and does not claim relationships that
are not present in registration metadata.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from app.core.observability import ComponentType, HealthStatus, ObservabilityHub, get_observability_hub
from app.orchestrator.capability_registry import CapabilityRegistry, CapabilityState


@dataclass(frozen=True)
class AnatomyNode:
    """One live component or capability in the system anatomy."""

    name: str
    category: str
    running: Optional[bool]
    health: str
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    active_provider: Optional[str] = None
    mutation_boundary: bool = False
    mutation_operations: List[str] = field(default_factory=list)
    provenance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SystemAnatomy:
    """Read-only query API for a deterministic live anatomy snapshot."""

    _MUTATING_ACTIONS = {"create", "delete", "execute", "modify", "patch", "write", "update", "remove"}

    def __init__(
        self,
        observability: Optional[ObservabilityHub] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        orchestrator: Any = None,
    ) -> None:
        self._observability = observability or get_observability_hub()
        self._capability_registry = capability_registry or CapabilityRegistry()
        self._orchestrator = orchestrator

    def snapshot(self) -> Dict[str, Any]:
        nodes = self._discover_nodes()
        dependent_map: Dict[str, List[str]] = {name: [] for name in nodes}
        for node in nodes.values():
            for dependency in node.dependencies:
                if dependency in dependent_map:
                    dependent_map[dependency].append(node.name)
        result: List[AnatomyNode] = []
        for name in sorted(nodes):
            node = nodes[name]
            result.append(AnatomyNode(
                **{**node.to_dict(), "dependents": sorted(dependent_map.get(name, []))}
            ))
        return {"nodes": [node.to_dict() for node in result], "count": len(result)}

    def list_nodes(self) -> List[Dict[str, Any]]:
        return self.snapshot()["nodes"]

    def get_node(self, name: str) -> Optional[Dict[str, Any]]:
        return next((node for node in self.list_nodes() if node["name"] == name), None)

    def dependencies_of(self, name: str) -> List[str]:
        node = self.get_node(name)
        return list(node["dependencies"]) if node else []

    def dependents_of(self, name: str) -> List[str]:
        node = self.get_node(name)
        return list(node["dependents"]) if node else []

    def _discover_nodes(self) -> Dict[str, AnatomyNode]:
        nodes: Dict[str, AnatomyNode] = {}
        for component in self._observability.list_components():
            info = self._observability.get_component(component["name"])
            metadata = getattr(info, "metadata", {}) or {}
            dependencies = self._normalise_dependencies(metadata)
            nodes[component["name"]] = AnatomyNode(
                name=component["name"],
                category=component.get("type", ComponentType.SERVICE.value),
                running=self._component_running(component.get("status")),
                health=component.get("status", HealthStatus.UNKNOWN.value),
                dependencies=dependencies,
                active_provider=self._provider(metadata),
                mutation_boundary=bool(metadata.get("mutation_boundary", False)),
                mutation_operations=self._operations(metadata),
                provenance="observability",
            )

        for name, capability in sorted(self._capability_registry.get_all().items()):
            metadata = capability.metadata
            operations = list(metadata.supported_actions or [metadata.default_action])
            nodes[name] = AnatomyNode(
                name=name,
                category=metadata.category.value,
                running=capability.state == CapabilityState.ACTIVE,
                health=self._capability_health(capability),
                dependencies=sorted(set(metadata.dependencies + metadata.depends_on)),
                active_provider=self._provider(metadata.__dict__),
                mutation_boundary=bool(set(operations) & self._MUTATING_ACTIONS),
                mutation_operations=sorted(set(operations) & self._MUTATING_ACTIONS),
                provenance="capability_registry",
            )
        return nodes

    @staticmethod
    def _normalise_dependencies(metadata: Dict[str, Any]) -> List[str]:
        values = metadata.get("dependencies", []) + metadata.get("depends_on", [])
        return sorted({value for value in values if isinstance(value, str) and value})

    @staticmethod
    def _provider(metadata: Dict[str, Any]) -> Optional[str]:
        value = metadata.get("active_provider", metadata.get("provider"))
        return value if isinstance(value, str) and value else None

    def _operations(self, metadata: Dict[str, Any]) -> List[str]:
        operations = metadata.get("mutation_operations", metadata.get("supported_actions", []))
        return sorted({value for value in operations if isinstance(value, str) and value})

    @staticmethod
    def _component_running(status: Optional[str]) -> Optional[bool]:
        if status in {HealthStatus.HEALTHY.value, HealthStatus.DEGRADED.value}:
            return True
        if status == HealthStatus.UNHEALTHY.value:
            return False
        return None

    @staticmethod
    def _capability_health(capability: Any) -> str:
        if capability.state == CapabilityState.ERROR:
            return "unhealthy"
        if capability.state == CapabilityState.ACTIVE:
            return "healthy"
        return "unknown"


def get_system_anatomy(
    observability: Optional[ObservabilityHub] = None,
    capability_registry: Optional[CapabilityRegistry] = None,
    orchestrator: Any = None,
) -> SystemAnatomy:
    return SystemAnatomy(observability, capability_registry, orchestrator)


__all__ = ["AnatomyNode", "SystemAnatomy", "get_system_anatomy"]
 
