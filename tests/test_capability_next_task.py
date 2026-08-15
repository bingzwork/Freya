from __future__ import annotations

from pathlib import Path

from app.core.protocols import SystemConfig
from app.orchestrator.capability_registry import CapabilityRegistry
from app.planner.task import TaskStatus
from main import FreyaApp


def _start_app(tmp_path: Path) -> FreyaApp:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("capability production fixture\n")
    (workspace / "requirements.txt").write_text("pytest>=8\n")
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


def test_registered_next_task_capabilities_use_production_collaborators(tmp_path: Path):
    app = _start_app(tmp_path)
    try:
        system = app.system
        capabilities = CapabilityRegistry().get_all()

        planning = capabilities["planning_engine"]
        assert planning._planner is system.execution._planner
        assert planning._plan_manager is system.execution.plan_manager
        assert planning._decision_manager is app.initializer.decision_manager

        communication = capabilities["communication_hub"]
        assert communication._event_bus is system.infra.event_bus

        debugging = capabilities["debugging"]
        assert debugging._tools is system.execution._tools
        assert debugging._verifier is system.execution.verification_runner
        assert debugging._safety_gate is system.orchestrator.safety_gate

        dependency = capabilities["dependency_management"]
        assert dependency._tools is system.execution._tools
        assert dependency._verifier is system.execution.verification_runner
        assert dependency._safety_gate is system.orchestrator.safety_gate
        assert dependency._auditor.workspace == app.workspace.resolve()
    finally:
        app.shutdown()


def test_planning_communication_debugging_and_dependency_actions_are_operational(
    tmp_path: Path, monkeypatch
):
    app = _start_app(tmp_path)
    try:
        system = app.system
        capabilities = CapabilityRegistry().get_all()
        planning = capabilities["planning_engine"]

        plan = system.execution.plan_manager.create_plan("fixture plan", "fixture")
        task = system.execution.plan_manager.add_task("Initial step")
        task.status = TaskStatus.FAILED
        monkeypatch.setattr(
            system.execution._planner,
            "create_plan",
            lambda *_args, **_kwargs: plan,
        )
        created = planning.execute("create_plan", {"task": "fixture plan"})
        assert created["success"] is True
        replanned = planning.execute(
            "replan",
            {
                "plan_id": plan.id,
                "failed_task_id": task.id,
                "new_steps": ["Run the corrected validation"],
            },
        )
        assert replanned["success"] is True
        assert replanned["added"]
        assert replanned["plan_id"] == plan.id

        communication = capabilities["communication_hub"]
        published = communication.execute(
            "publish",
            {"event_type": "capability.test", "data": {"ok": True}},
        )
        assert published["success"] is True
        history = communication.execute("get_history", {"limit": 10})
        assert history["success"] is True
        assert any(event["name"] == "capability.test" for event in history["events"])

        debugging = capabilities["debugging"]
        inspected = debugging.execute(
            "inspect_error", {"path": "README.md"}
        )
        assert inspected["success"] is True
        diagnostics = debugging.execute(
            "run_diagnostics", {"command": "printf debug-ok"}
        )
        assert diagnostics["success"] is True
        assert diagnostics["stdout"] == "debug-ok"

        dependency = capabilities["dependency_management"]
        inspected_dependencies = dependency.execute("inspect", {})
        assert inspected_dependencies["success"] is True
        assert "requirements.txt" in inspected_dependencies["dependencies"]["sources"]
        validated = dependency.execute("validate", {})
        assert validated["success"] is True
        installed = dependency.execute("check_installed", {"packages": ["pytest"]})
        assert installed["success"] is True
        assert installed["packages"]["pytest"]["installed"] is True

        # Mutation remains behind the existing SafetyGate, even when the caller
        # supplies the capability-level explicit-authorization flag.
        blocked = dependency.execute(
            "install", {"package": "pytest", "authorized": True}
        )
        assert blocked["success"] is False
        assert "safety" in blocked["error"].lower() or "blocked" in blocked["error"].lower()
    finally:
        app.shutdown()


def test_communication_subscription_boundary_is_not_exposed_as_a_fake_action():
    from app.orchestrator.capabilities import CommunicationHubCapability

    capability = CommunicationHubCapability()
    assert "subscribe" not in capability.metadata.supported_actions
    assert not hasattr(capability, "action_subscribe")
