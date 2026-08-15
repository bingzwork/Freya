from types import SimpleNamespace

from app.core.observability import ComponentInfo, ComponentType, HealthStatus
from app.orchestrator.capability_registry import (
    Capability,
    CapabilityCategory,
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityState,
)
from app.self_observation.system_anatomy import SystemAnatomy


class FakeObservability:
    def __init__(self):
        self.components = {
            "EventBus": ComponentInfo(
                name="EventBus",
                component_type=ComponentType.SERVICE,
                metadata={"active_provider": "in_process"},
                status=HealthStatus.HEALTHY,
            ),
            "Workflow": ComponentInfo(
                name="Workflow",
                component_type=ComponentType.PIPELINE,
                metadata={"dependencies": ["EventBus"], "mutation_boundary": True, "mutation_operations": ["execute"]},
                status=HealthStatus.DEGRADED,
            ),
            "Unknown": ComponentInfo(name="Unknown", component_type=ComponentType.SERVICE),
        }

    def list_components(self):
        return [
            {"name": item.name, "type": item.component_type.value, "status": item.status.value}
            for item in self.components.values()
        ]

    def get_component(self, name):
        return self.components.get(name)


def test_live_anatomy_discovers_components_and_relationships():
    registry = CapabilityRegistry()
    registry._capabilities = {}
    capability = Capability(CapabilityMetadata(
        name="patcher",
        category=CapabilityCategory.EXECUTION,
        dependencies=["Workflow"],
        supported_actions=["execute", "read"],
    ), handler=lambda inputs: inputs)
    capability.metadata.__dict__["provider"] = "local"
    capability.state = CapabilityState.ACTIVE
    registry._capabilities[capability.name] = capability

    anatomy = SystemAnatomy(FakeObservability(), registry)
    snapshot = anatomy.snapshot()
    assert [node["name"] for node in snapshot["nodes"]] == ["EventBus", "Unknown", "Workflow", "patcher"]
    assert anatomy.dependencies_of("patcher") == ["Workflow"]
    assert anatomy.dependents_of("Workflow") == ["patcher"]

    workflow = anatomy.get_node("Workflow")
    assert workflow["running"] is True
    assert workflow["health"] == "degraded"
    assert workflow["mutation_boundary"] is True
    assert workflow["active_provider"] is None

    patcher = anatomy.get_node("patcher")
    assert patcher["running"] is True
    assert patcher["health"] == "healthy"
    assert patcher["active_provider"] == "local"
    assert patcher["mutation_operations"] == ["execute"]

    assert anatomy.get_node("Unknown")["running"] is None
    assert anatomy.get_node("missing") is None


def test_anatomy_output_is_deterministic():
    anatomy = SystemAnatomy(FakeObservability(), CapabilityRegistry())
    assert anatomy.snapshot() == anatomy.snapshot()
    assert anatomy.list_nodes() == sorted(anatomy.list_nodes(), key=lambda node: node["name"])


def test_capability_error_is_not_reported_healthy():
    registry = CapabilityRegistry()
    registry._capabilities = {}
    capability = Capability(CapabilityMetadata(name="broken"), handler=lambda inputs: inputs)
    capability.state = CapabilityState.ERROR
    registry._capabilities[capability.name] = capability
    node = SystemAnatomy(FakeObservability(), registry).get_node("broken")
    assert node["running"] is False
    assert node["health"] == "unhealthy"
