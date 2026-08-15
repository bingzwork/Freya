from __future__ import annotations

from pathlib import Path

from app.core.protocols import SystemConfig
from app.orchestrator.capability_registry import CapabilityRegistry
from main import FreyaApp


def _start_app(tmp_path: Path) -> FreyaApp:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("production capability wiring\n")
    app = FreyaApp(
        workspace,
        SystemConfig(
            workspace=workspace,
            enable_autonomy=False,
            enable_file_watcher=False,
            enable_config_hot_reload=False,
        ),
    )
    app.start()
    return app


def test_registered_capabilities_use_initializer_owned_production_services(tmp_path: Path):
    app = _start_app(tmp_path)
    try:
        system = app.system
        registry = CapabilityRegistry()
        capabilities = registry.get_all()

        code_execution = capabilities["code_execution"]
        assert code_execution._executor is system.execution._executor
        assert code_execution._verifier is system.execution.verification_runner
        assert code_execution._patch_engine is system.execution.repair_loop.patch_engine
        assert code_execution._tools is system.execution._tools

        decision = capabilities["decision_engine"]
        assert decision._decision_manager is app.initializer.decision_manager

        monitoring = capabilities["system_monitoring"]
        assert monitoring._observability is system.infra.observability

        tool_registry = capabilities["tool_registry"]
        assert tool_registry._tools is system.execution._tools

        safety = capabilities["safety_guard"]
        assert safety._safety_gate is system.orchestrator.safety_gate

        orchestration = capabilities["orchestration_core"]
        assert orchestration._orchestrator is system.orchestrator
    finally:
        app.shutdown()


def test_registered_capabilities_are_callable_without_initialization_errors(tmp_path: Path):
    app = _start_app(tmp_path)
    try:
        capabilities = CapabilityRegistry().get_all()

        assert capabilities["code_execution"].execute(
            "apply_patch", {"operations": []}
        )["success"] is True
        assert capabilities["decision_engine"].execute(
            "decide",
            {
                "task": "choose an inspection action",
                "options": [{"name": "inspect", "description": "Inspect the workspace"}],
            },
        )["success"] is True
        assert capabilities["system_monitoring"].execute(
            "get_health", {}
        )["success"] is True
        assert capabilities["system_monitoring"].execute(
            "get_metrics", {}
        )["success"] is True
        assert capabilities["tool_registry"].execute(
            "list_tools", {}
        )["success"] is True
        assert capabilities["safety_guard"].execute(
            "check",
            {
                "operation": "read README.md",
                "operation_type": "file_read",
                "context": {"capability": "safety_guard"},
            },
        )["success"] is True
        assert capabilities["orchestration_core"].execute(
            "get_status", {}
        )["success"] is True
    finally:
        app.shutdown()


def test_code_execution_capability_does_not_bypass_workflow_safety_path():
    from app.orchestrator.capabilities import CodeExecutionCapability

    capability = CodeExecutionCapability()
    assert "safety_gate" not in capability.action_run_command.__code__.co_names
    assert "check_and_enforce" not in capability.action_run_command.__code__.co_names
    assert "safety_gate" not in capability.action_apply_patch.__code__.co_names
    assert "check_and_enforce" not in capability.action_apply_patch.__code__.co_names
    assert "safety_gate" not in capability.action_verify.__code__.co_names
    assert "check_and_enforce" not in capability.action_verify.__code__.co_names

    # Risk authorization remains the responsibility of the existing workflow
    # TaskExecutor/ExecutionEngine SafetyGate path, not this direct adapter.
    assert "SafetyGate" not in capability.__class__.__module__
