from copy import deepcopy

from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityRouter
from app.core.tool_manager import ToolManager
from app.orchestrator.capabilities import create_all_capabilities
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry
from app.simulation.capability import SimulationCapability, SimulationType


def setup_function():
    reset_capability_registry()


def test_simulation_capability_is_in_builtin_factory_and_registry_executable():
    capability = next(cap for cap in create_all_capabilities() if cap.name == "simulation_capability")
    assert capability.metadata.category.value == "reasoning"
    assert capability.metadata.default_action == "simulate"
    assert capability.is_executable()

    registry = CapabilityRegistry()
    assert registry.register(capability)
    assert registry.get_capability("simulation_capability") is capability


def test_direct_simulation_request_routes_through_canonical_bridge():
    registry = CapabilityRegistry()
    capability = SimulationCapability()
    assert registry.register(capability)
    router = CapabilityRouter()
    bridge = CapabilityRegistrationBridge(registry=registry, router=router, tool_manager=ToolManager())
    bridge.sync()

    result = router.route(
        "simulate what happens if CapabilityRouter goes down",
        simulation_type="system",
        objective="What breaks if CapabilityRouter goes down?",
        current_state={"components": {"CapabilityRouter": {}}, "dependencies": {"Agent": ["CapabilityRouter"]}},
        proposed_change={"component": "CapabilityRouter"},
    )
    assert result.success
    assert result.capability_name == "simulation_capability"
    assert result.data["simulation"]["result_kind"] == "PREDICTED"
    assert result.data["simulation"]["verified"] is False


def test_system_simulation_reports_known_and_unknown_relationships_without_invention():
    capability = SimulationCapability()
    known = capability.action_simulate({
        "simulation_type": SimulationType.SYSTEM.value,
        "objective": "What breaks if Router goes down?",
        "current_state": {"components": {"Router": {}, "Agent": {}}, "dependencies": {"Agent": ["Router"]}},
        "proposed_change": {"component": "Router"},
    })
    assert known["success"]
    assert "Agent" in known["simulation"]["predicted_outcomes"]["downstream_dependencies"]

    unknown = capability.action_simulate({
        "simulation_type": SimulationType.SYSTEM.value,
        "objective": "What breaks if Unknown goes down?",
        "current_state": {"components": {"Router": {}}, "dependencies": {"Agent": ["Router"]}},
        "proposed_change": {"component": "Unknown"},
    })
    assert unknown["success"]
    assert unknown["simulation"]["predicted_outcomes"]["failure_propagation"] == "unknown"
    assert "relationships for Unknown" in unknown["simulation"]["uncertainties"]


def test_workflow_resource_financial_and_project_simulations_are_deterministic():
    capability = SimulationCapability()
    workflow = capability.action_simulate({
        "simulation_type": "workflow",
        "objective": "Run automation every hour",
        "proposed_change": {"interval_minutes": 60, "expected_duration_minutes": 90, "horizon_hours": 4},
    })
    assert workflow["simulation"]["predicted_outcomes"]["estimated_runs"] == 4
    assert workflow["simulation"]["predicted_outcomes"]["overlap"] is True

    resources = capability.action_simulate({
        "simulation_type": "resource",
        "objective": "Load another model",
        "current_state": {"resources": {"ram": {"used": 28, "capacity": 32}, "vram": {"used": 7, "capacity": 8}}},
        "proposed_change": {"resources": {"ram": {"requested": 8}, "vram": {"requested": 2}}},
    })
    assert resources["simulation"]["predicted_outcomes"]["oversubscribed"] == ["ram", "vram"]

    financial = capability.action_simulate({
        "simulation_type": "financial",
        "objective": "Model a price scenario",
        "variables": {"starting_cash": 100, "price": 20, "units": 10, "fixed_costs": 50, "variable_cost_per_unit": 5, "forecast_period": 2},
    })
    assert financial["simulation"]["predicted_outcomes"]["net_cash_flow"] == 100
    assert financial["simulation"]["predicted_outcomes"]["ending_cash"] == 300

    project = capability.action_simulate({
        "simulation_type": "project",
        "objective": "Delay A by two weeks",
        "variables": {"tasks": [{"id": "A", "duration_days": 5}, {"id": "B", "duration_days": 3, "dependencies": ["A"]}], "delay_task": "A", "delay_days": 14},
    })
    assert project["simulation"]["predicted_outcomes"]["project_finish_days"] == 22


def test_decision_inconclusive_result_does_not_force_recommendation():
    result = SimulationCapability().action_compare({
        "objective": "Compare options",
        "alternatives": [{"name": "A"}, {"name": "B"}],
    })
    assert result["success"]
    assert result["simulation"]["recommendation"] is None
    assert result["simulation"]["confidence"] == "HIGH"


def test_agent_action_simulation_is_non_mutating_and_never_verification():
    proposed = {"actions": [{"tool": "delete_files", "mutating": True}], "rollback_available": False}
    original = deepcopy(proposed)
    result = SimulationCapability().action_simulate({
        "simulation_type": "agent_action",
        "objective": "Preview an autonomous action",
        "proposed_change": proposed,
    })
    assert proposed == original
    assert result["simulation"]["predicted_outcomes"]["would_execute_real_action"] is False
    assert result["simulation"]["result_kind"] == "PREDICTED"
    assert result["simulation"]["verified"] is False
    assert any(r["risk"] == "low_reversibility" for r in result["simulation"]["risks"])


def test_pre_execution_policy_skips_trivial_and_requires_consequential_plans():
    assert SimulationCapability.requires_pre_execution_simulation({"mutation_level": "read_only"}) is False
    assert SimulationCapability.requires_pre_execution_simulation({"mutation_level": "high"}) is True
    assert SimulationCapability.requires_pre_execution_simulation({"requires_simulation": False, "risk_level": "critical"}) is False
