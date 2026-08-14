"""Focused production liveness and readiness surface tests."""

import json
import sys
from pathlib import Path

import pytest

import main as main_module
from app.core.events import EventBus
from app.core.observability import (
    ComponentInfo,
    ComponentType,
    HealthCheck,
    HealthResult,
    HealthStatus,
    ObservabilityHub,
)
from main import FreyaApp


@pytest.fixture
def observability_hub():
    """Provide an unstarted hub so tests control all observed health state."""
    return ObservabilityHub(event_bus=EventBus())


def register_dependency(
    hub: ObservabilityHub,
    name: str,
    *,
    status: HealthStatus,
    required: bool = True,
    category: str = "dependency",
    metadata: dict | None = None,
) -> None:
    """Register one dependency using the production observability health state."""
    hub.register_component(ComponentInfo(
        name=name,
        component_type=ComponentType.SERVICE,
        metadata={"readiness": {"category": category, "required": required}},
    ))
    hub.add_health_check(HealthCheck(
        name=f"{name}.readiness",
        component=name,
        check_func=lambda: HealthResult(
            name="",
            component="",
            status=status,
            message=f"{name} is {status.value}",
            metadata=metadata or {},
        ),
        critical=required,
    ))


def observe_dependencies(hub: ObservabilityHub) -> None:
    """Populate the hub's existing health state before querying the surface."""
    hub.run_health_checks(force=True)


def test_cli_health_query_does_not_start_runtime(monkeypatch, capsys):
    """The production CLI health query is read-only and does not initialize services."""
    started = False

    def unexpected_start(self):
        nonlocal started
        started = True
        raise AssertionError("health queries must not start Freya")

    monkeypatch.setattr(main_module.FreyaApp, "start", unexpected_start)
    monkeypatch.setattr(sys, "argv", ["main.py", "--health"])

    assert main_module.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert started is False
    assert output["liveness"]["alive"] is True
    assert output["readiness"]["ready"] is False


def test_live_but_not_ready_before_initialization(tmp_path: Path):
    """The process is live even though an application graph has not initialized."""
    app = FreyaApp(tmp_path)

    surface = app.get_health_surface()

    assert surface["liveness"] == {"status": "alive", "alive": True}
    assert surface["readiness"]["ready"] is False
    assert surface["readiness"]["status"] == "not_ready"
    assert surface["readiness"]["initialization"] == {"completed": False}
    assert surface["readiness"]["reasons"] == ["initialization_incomplete"]


def test_ready_when_required_dependencies_are_healthy(observability_hub: ObservabilityHub):
    """Ready requires completed initialization plus healthy required dependencies."""
    register_dependency(observability_hub, "agent_facade", status=HealthStatus.HEALTHY, category="agent")
    register_dependency(
        observability_hub,
        "llm_providers",
        status=HealthStatus.HEALTHY,
        category="providers",
        metadata={"providers": {"ollama": {"healthy": True, "model_available": True}}},
    )
    register_dependency(
        observability_hub,
        "background_job_service",
        status=HealthStatus.HEALTHY,
        category="background_service",
    )
    observe_dependencies(observability_hub)

    surface = observability_hub.get_health_surface(initialized=True)

    assert surface["liveness"]["alive"] is True
    assert surface["readiness"]["status"] == "ready"
    assert surface["readiness"]["ready"] is True
    assert surface["readiness"]["reasons"] == []
    provider = next(item for item in surface["readiness"]["dependencies"] if item["name"] == "llm_providers")
    assert provider["checks"][0]["metadata"]["providers"]["ollama"]["healthy"] is True


def test_required_provider_unavailable_makes_readiness_not_ready(observability_hub: ObservabilityHub):
    """A required provider health failure is represented as an unavailable dependency."""
    register_dependency(observability_hub, "agent_facade", status=HealthStatus.HEALTHY, category="agent")
    register_dependency(
        observability_hub,
        "llm_providers",
        status=HealthStatus.UNHEALTHY,
        category="providers",
        metadata={"providers": {"ollama": {"healthy": False, "error": "connection refused"}}},
    )
    register_dependency(
        observability_hub,
        "background_job_service",
        status=HealthStatus.HEALTHY,
        category="background_service",
    )
    observe_dependencies(observability_hub)

    readiness = observability_hub.get_health_surface(initialized=True)["readiness"]

    assert readiness["ready"] is False
    assert readiness["status"] == "not_ready"
    assert "required_dependency_unavailable:llm_providers" in readiness["reasons"]
    provider = next(item for item in readiness["dependencies"] if item["name"] == "llm_providers")
    assert provider["status"] == "unhealthy"
    assert provider["checks"][0]["metadata"]["providers"]["ollama"]["healthy"] is False


def test_required_background_service_unavailable_makes_readiness_not_ready(observability_hub: ObservabilityHub):
    """A stopped required background service prevents readiness."""
    register_dependency(observability_hub, "agent_facade", status=HealthStatus.HEALTHY, category="agent")
    register_dependency(observability_hub, "llm_providers", status=HealthStatus.HEALTHY, category="providers")
    register_dependency(
        observability_hub,
        "background_job_service",
        status=HealthStatus.UNHEALTHY,
        category="background_service",
    )
    observe_dependencies(observability_hub)

    readiness = observability_hub.get_health_surface(initialized=True)["readiness"]

    assert readiness["ready"] is False
    assert "required_dependency_unavailable:background_job_service" in readiness["reasons"]


def test_optional_provider_failure_does_not_make_agent_unready(observability_hub: ObservabilityHub):
    """Optional provider failures remain represented without overriding readiness."""
    register_dependency(observability_hub, "agent_facade", status=HealthStatus.HEALTHY, category="agent")
    register_dependency(observability_hub, "llm_providers", status=HealthStatus.HEALTHY, category="providers")
    register_dependency(
        observability_hub,
        "optional_provider",
        status=HealthStatus.UNHEALTHY,
        required=False,
        category="providers",
    )
    observe_dependencies(observability_hub)

    readiness = observability_hub.get_health_surface(initialized=True)["readiness"]

    assert readiness["ready"] is True
    optional = next(item for item in readiness["dependencies"] if item["name"] == "optional_provider")
    assert optional["status"] == "unhealthy"
    assert optional["required"] is False


def test_health_surface_is_read_only(observability_hub: ObservabilityHub):
    """Querying liveness/readiness does not re-run checks or mutate health state."""
    calls = 0

    def healthy_check():
        nonlocal calls
        calls += 1
        return True

    observability_hub.register_component(ComponentInfo(
        name="background_job_service",
        component_type=ComponentType.SERVICE,
        metadata={"readiness": {"category": "background_service", "required": True}},
    ))
    observability_hub.add_health_check(HealthCheck(
        name="background_job_service.readiness",
        component="background_job_service",
        check_func=healthy_check,
        critical=True,
    ))
    observe_dependencies(observability_hub)
    before = observability_hub.get_health()

    first = observability_hub.get_health_surface(initialized=True)
    second = observability_hub.get_health_surface(initialized=True)
    after = observability_hub.get_health()

    assert calls == 1
    assert first == second
    assert after == before


def test_initializer_registers_active_provider_and_background_state(tmp_path: Path, observability_hub: ObservabilityHub):
    """Initializer readiness checks reuse the active provider and service runtime state."""
    from app.core.initializer import SystemInitializer
    from app.providers.base import ProviderHealthStatus

    class PriorityRuntime:
        def get_provider_health(self):
            return {
                "ollama": ProviderHealthStatus(
                    provider_name="ollama",
                    is_healthy=False,
                    is_reachable=False,
                    model_available=False,
                    error_message="connection refused",
                ),
            }

    class BackgroundRuntime:
        def is_running(self):
            return False

    initializer = SystemInitializer(tmp_path)
    initializer._register_readiness_checks(
        observability=observability_hub,
        job_service=BackgroundRuntime(),
        priority_llm=PriorityRuntime(),
        facade=object(),
        orchestrator=None,
        autonomy=None,
    )
    observe_dependencies(observability_hub)

    readiness = observability_hub.get_health_surface(initialized=True)["readiness"]

    assert readiness["ready"] is False
    assert "required_dependency_unavailable:llm_providers" in readiness["reasons"]
    assert "required_dependency_unavailable:background_job_service" in readiness["reasons"]
    provider = next(item for item in readiness["dependencies"] if item["name"] == "llm_providers")
    assert provider["checks"][0]["metadata"]["providers"]["ollama"]["error"] == "connection refused"
