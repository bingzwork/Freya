from pathlib import Path

import pytest

from app.core.background_jobs import BackgroundJobService, set_job_service
from app.core.events import EventBus, set_event_bus
from app.core.observability import ObservabilityHub, set_observability_hub
from app.orchestrator.capabilities import create_all_capabilities
from app.orchestrator.capability_registry import (
    Capability,
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityState,
    reset_capability_registry,
)
from app.orchestrator.safety_gate import SafetyGate, SafetyViolationError
from app.orchestrator.task_executor import ExecutionState, TaskExecutor
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, WorkflowOrchestratorConfig
from app.planner.task import Task, TaskStatus
from app.planner.task_graph import TaskGraph


class CountingCapability(Capability):
    """Small executable capability used to prove dispatch ordering."""

    def __init__(self):
        super().__init__(
            CapabilityMetadata(
                name="counting",
                default_action="perform",
                supported_actions=["perform"],
            )
        )
        self.calls = 0

    def action_perform(self, inputs):
        self.calls += 1
        return {"success": True, "value": inputs.get("value", "ok")}


@pytest.fixture(autouse=True)
def runtime_services():
    """Provide the shared infrastructure expected by production components."""
    reset_capability_registry()
    bus = EventBus()
    set_event_bus(bus)
    set_job_service(BackgroundJobService(event_bus=bus))
    set_observability_hub(ObservabilityHub(event_bus=bus))
    yield bus
    reset_capability_registry()
    set_event_bus(None)
    set_job_service(None)
    set_observability_hub(None)


def make_graph(title="Read a file", action="perform"):
    task = Task(
        id="task-1",
        title=title,
        metadata={"capability_name": "counting", "action": action},
    )
    graph = TaskGraph()
    graph.add_task(task)
    return graph, task


def test_registry_accepts_only_callable_declared_actions_and_rejects_duplicates():
    registry = CapabilityRegistry()
    valid = CountingCapability()

    assert registry.register(valid) is True
    assert registry.get_capability("counting") is valid
    assert registry.register(CountingCapability()) is False
    assert registry.get_capability("unknown") is None

    placeholder = Capability(
        CapabilityMetadata(
            name="placeholder",
            default_action="missing",
            supported_actions=["missing"],
        )
    )
    non_callable = Capability(
        CapabilityMetadata(
            name="non-callable",
            default_action="execute",
            supported_actions=["execute"],
        ),
        handler="not-a-callable",
    )

    assert registry.register(placeholder) is False
    assert registry.register(non_callable) is False
    assert registry.get_capability("placeholder") is None
    assert registry.get_capability("non-callable") is None


def test_builtin_factory_does_not_expose_placeholder_actions_or_capabilities():
    capabilities = {cap.name: cap for cap in create_all_capabilities()}

    assert "failure_recovery" not in capabilities
    assert capabilities["communication_hub"].metadata.supported_actions == [
        "publish",
        "get_history",
    ]
    assert all(cap.is_executable() for cap in capabilities.values())


def test_unknown_action_fails_before_safety_or_capability_dispatch(tmp_path: Path):
    capability = CountingCapability()
    capability._activate()
    gate = SafetyGate()
    graph, task = make_graph(action="missing")
    executor = TaskExecutor(
        checkpoint_dir=tmp_path / "checkpoints",
        safety_gate=gate,
    )

    executor.execute("unknown-action", graph, {"counting": capability}, async_mode=False)

    assert executor.get_status("unknown-action") is ExecutionState.FAILED
    assert task.status is TaskStatus.FAILED
    assert "does not expose callable action" in task.error
    assert capability.calls == 0
    assert gate.get_assessment_history() == []


def test_workflow_step_runs_safety_before_a_callable_capability(tmp_path: Path):
    capability = CountingCapability()
    capability._activate()
    gate = SafetyGate()
    graph, task = make_graph()
    executor = TaskExecutor(
        checkpoint_dir=tmp_path / "checkpoints",
        safety_gate=gate,
    )

    executor.execute("approved-workflow", graph, {"counting": capability}, async_mode=False)

    assert executor.get_status("approved-workflow") is ExecutionState.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert capability.calls == 1
    assessment = gate.get_assessment_history()[-1]
    assert assessment.operation_type == "task_execution"
    assert assessment.metadata["capability"] == "counting"
    assert assessment.allowed is True


def test_denied_workflow_step_emits_observability_and_never_dispatches(tmp_path: Path, runtime_services):
    capability = CountingCapability()
    capability._activate()
    gate = SafetyGate()
    graph, task = make_graph(title="rm -rf /")
    executor = TaskExecutor(
        checkpoint_dir=tmp_path / "checkpoints",
        safety_gate=gate,
    )
    blocked_events = []
    subscription = runtime_services.subscribe("safety.execution_blocked", blocked_events.append)

    try:
        executor.execute("denied-workflow", graph, {"counting": capability}, async_mode=False)
    finally:
        runtime_services.unsubscribe(subscription)

    assert executor.get_status("denied-workflow") is ExecutionState.SAFETY_DENIED
    assert task.status is TaskStatus.FAILED
    assert capability.calls == 0
    assert blocked_events
    assert blocked_events[-1]["assessment_id"]
    assert blocked_events[-1]["operation_type"] == "task_execution"
    assert blocked_events[-1]["capability"] == "counting"
    assert blocked_events[-1]["decision"] == "block"
    assert blocked_events[-1]["reason"]
    assert blocked_events[-1]["execution_blocked"] is True


def test_safety_evaluation_failure_is_fail_closed_and_observable(tmp_path: Path, monkeypatch, runtime_services):
    capability = CountingCapability()
    capability._activate()
    gate = SafetyGate()
    graph, task = make_graph()
    executor = TaskExecutor(
        checkpoint_dir=tmp_path / "checkpoints",
        safety_gate=gate,
    )
    failures = []
    subscription = runtime_services.subscribe("safety.evaluation_failed", failures.append)
    monkeypatch.setattr(gate, "assess", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("risk unavailable")))

    try:
        executor.execute("failed-evaluation", graph, {"counting": capability}, async_mode=False)
    finally:
        runtime_services.unsubscribe(subscription)

    assert executor.get_status("failed-evaluation") is ExecutionState.SAFETY_DENIED
    assert task.status is TaskStatus.FAILED
    assert capability.calls == 0
    assert failures[-1]["capability"] == "counting"
    assert failures[-1]["execution_blocked"] is True


def test_workflow_orchestrator_does_not_own_background_job_lifecycle():
    assert not hasattr(WorkflowOrchestrator, "_start_background_jobs")
    assert "enable_background_jobs" not in WorkflowOrchestratorConfig.__dataclass_fields__
    assert "job_service" in WorkflowOrchestrator.__init__.__annotations__


def test_safety_gate_denial_raises_before_a_protected_side_effect():
    gate = SafetyGate()
    calls = 0

    with pytest.raises(SafetyViolationError):
        gate.check_and_enforce("rm -rf /", "task_execution", {"capability": "counting"})

    assert calls == 0
