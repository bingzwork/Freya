from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.orchestrator.capability_registry import Capability, CapabilityMetadata
from app.orchestrator.task_executor import ExecutionState, TaskExecutor
from app.orchestrator.workflow_composer import WorkflowSpec
from app.planner.task import Task, TaskStatus
from app.planner.task_graph import TaskGraph
from app.verification.runner import VerificationResult


class StubSafetyGate:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def check_and_enforce(self, operation, operation_type, context):
        self.calls.append((operation, operation_type, context))
        if self.error:
            raise self.error
        return SimpleNamespace(action="allow")


class StubVerifier:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def dry_run_verify(self):
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


class StubRepair:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def run(self, propose):
        self.calls += 1
        return self.result


class StubExecutionVerifier:
    """Minimal verifier adapter used by the engine's direct state-machine tests."""

    def __init__(self, runner):
        self.runner = runner

    def verify_execution(self, task, plan_results, allow_mutations=True, verification_result=None, route_learning=True):
        result = verification_result or self.runner.dry_run_verify()
        return SimpleNamespace(success=result.success, verification_result=result)

    def record_execution_failure(self, task, plan_results, error_message, allow_mutations=True, verification_result=None):
        return SimpleNamespace(success=False, verification_result=verification_result)


def verification(success, stderr=""):
    return VerificationResult(
        success=success,
        command=["verify"],
        stdout="ok" if success else "",
        stderr=stderr,
        return_code=0 if success else 1,
    )


def make_task_graph():
    task = Task(
        id="task-1",
        title="Run safe capability",
        metadata={"capability_name": "echo", "action": "execute"},
    )
    graph = TaskGraph()
    graph.add_task(task)
    return graph, task


def make_capability():
    capability = Capability(
        CapabilityMetadata(name="echo"),
        handler=lambda inputs: {"value": "ok"},
    )
    capability._activate()
    return capability


def make_executor(tmp_path, gate, verifier, repair):
    return TaskExecutor(
        checkpoint_dir=Path(tmp_path) / "checkpoints",
        safety_gate=gate,
        verification_runner=verifier,
        repair_loop=repair,
    )


def test_task_executor_requires_safety_before_capability(tmp_path):
    gate = StubSafetyGate(error=RuntimeError("denied"))
    verifier = StubVerifier(verification(True))
    executor = make_executor(tmp_path, gate, verifier, StubRepair({"success": False, "attempts": []}))
    graph, task = make_task_graph()

    executor.execute("wf-denied", graph, {"echo": make_capability()}, async_mode=False)

    assert executor.get_status("wf-denied") == ExecutionState.SAFETY_DENIED
    assert task.status == TaskStatus.FAILED
    assert len(gate.calls) == 1
    assert verifier.calls == 0


def test_task_executor_finalizes_only_after_verification(tmp_path):
    gate = StubSafetyGate()
    verifier = StubVerifier(verification(True))
    executor = make_executor(tmp_path, gate, verifier, StubRepair({"success": False, "attempts": []}))
    graph, task = make_task_graph()

    executor.execute("wf-success", graph, {"echo": make_capability()}, async_mode=False)

    assert executor.get_status("wf-success") == ExecutionState.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert verifier.calls == 1
    assert gate.calls[0][1] == "task_execution"


def test_task_executor_verification_failure_is_terminal_and_repair_is_attempted(tmp_path):
    gate = StubSafetyGate()
    verifier = StubVerifier(verification(False, "tests failed"), verification(False, "tests still failed"))
    repair = StubRepair({
        "success": False,
        "attempts": [{"verification": verification(False, "tests still failed")}],
    })
    executor = make_executor(tmp_path, gate, verifier, repair)
    graph, task = make_task_graph()

    executor.execute("wf-unverified", graph, {"echo": make_capability()}, async_mode=False)

    assert executor.get_status("wf-unverified") == ExecutionState.VERIFICATION_FAILED
    assert task.status == TaskStatus.FAILED
    assert verifier.calls == 1
    assert repair.calls == 1


def test_workflow_orchestrator_calls_safety_gate_before_dispatch():
    from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, OrchestratorState

    orchestrator = WorkflowOrchestrator()
    orchestrator._state = OrchestratorState.RUNNING
    orchestrator._workflow_composer = MagicMock()
    orchestrator._capability_registry = MagicMock()
    orchestrator._task_executor = MagicMock()
    orchestrator._task_executor.execute.return_value = "wf-exec"
    orchestrator._safety_gate = StubSafetyGate()

    from app.orchestrator.workflow_composer import ComposedWorkflow
    workflow = ComposedWorkflow(
        spec=WorkflowSpec(workflow_id="wf-1", name="safe workflow"),
        steps=[],
        task_graph=TaskGraph(),
    )
    orchestrator._workflow_composer.compose.return_value = workflow

    execution_id = orchestrator.execute_workflow(workflow.spec, async_mode=False)

    assert execution_id == "wf-exec"
    assert len(orchestrator._safety_gate.calls) == 1
    assert orchestrator._task_executor.execute.call_args.kwargs["safety_approved"] is True


def test_workflow_orchestrator_does_not_dispatch_after_safety_denial():
    from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator, OrchestratorState

    orchestrator = WorkflowOrchestrator()
    orchestrator._state = OrchestratorState.RUNNING
    orchestrator._workflow_composer = MagicMock()
    orchestrator._capability_registry = MagicMock()
    orchestrator._task_executor = MagicMock()
    orchestrator._safety_gate = StubSafetyGate(error=RuntimeError("denied"))

    from app.orchestrator.workflow_composer import ComposedWorkflow
    workflow = ComposedWorkflow(
        spec=WorkflowSpec(workflow_id="wf-2", name="unsafe workflow"),
        steps=[],
        task_graph=TaskGraph(),
    )
    orchestrator._workflow_composer.compose.return_value = workflow

    with pytest.raises(RuntimeError, match="denied"):
        orchestrator.execute_workflow(workflow.spec, async_mode=False)

    orchestrator._task_executor.execute.assert_not_called()
    assert workflow.metadata["execution_state"] == "safety_denied"
    assert workflow.status.value == "failed"


def make_engine(plan, gate, verifier, repair, execution_result):
    from app.execution.engine import ExecutionEngine

    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine._chat_activity = MagicMock()
    engine._memory = MagicMock()
    engine._memory.retrieve_for_planning.return_value = "retrieved context"
    engine._planner = MagicMock()
    engine._planner.create_plan.return_value = plan
    engine._executor = SimpleNamespace(
        execute=MagicMock(return_value=execution_result),
        _verification=verifier,
        _repair=repair,
    )
    engine._execution_verifier = StubExecutionVerifier(verifier)
    engine._safety_gate = gate
    engine._llm = MagicMock()
    engine._llm.ask.return_value = "verified summary"
    engine.plan_manager = MagicMock()
    engine._lifecycle_state = None
    engine._execution_records = {}
    engine._last_outcome = None
    engine._last_learning_outcome = None
    engine._conversation_control = None
    return engine


def test_execution_engine_persists_only_verified_success():
    from app.execution.engine import ExecutionLifecycleState

    task = Task(id="plan-task", title="Read file")
    plan = SimpleNamespace(id="plan-success", tasks=[task], status="draft")
    gate = StubSafetyGate()
    verifier = StubVerifier(verification(True))
    repair = StubRepair({"success": False, "attempts": []})
    engine = make_engine(plan, gate, verifier, repair, [{"success": True}])

    result = engine.execute_plan("Read a file", allow_mutations=False)

    assert result == "verified summary"
    assert engine.lifecycle_state == ExecutionLifecycleState.SUCCEEDED
    assert engine.last_outcome.state == ExecutionLifecycleState.SUCCEEDED
    assert engine.plan_manager.save_plan.call_count == 1
    assert engine._executor.execute.call_args.args[1] is False


def test_execution_engine_safety_denial_never_reaches_executor():
    from app.execution.engine import ExecutionLifecycleState

    task = Task(id="plan-task", title="Delete file")
    plan = SimpleNamespace(id="plan-denied", tasks=[task], status="draft")
    gate = StubSafetyGate(error=RuntimeError("denied"))
    verifier = StubVerifier(verification(True))
    engine = make_engine(plan, gate, verifier, StubRepair({"success": False, "attempts": []}), [{"success": True}])

    result = engine.execute_plan("Delete a file")

    assert "not completed safely" in result
    assert engine.lifecycle_state == ExecutionLifecycleState.SAFETY_DENIED
    engine._executor.execute.assert_not_called()
    assert verifier.calls == 0
    assert engine.last_outcome.error == "denied"


def test_execution_engine_verification_failure_is_not_reported_as_success():
    from app.execution.engine import ExecutionLifecycleState

    task = Task(id="plan-task", title="Modify file")
    plan = SimpleNamespace(id="plan-unverified", tasks=[task], status="draft")
    gate = StubSafetyGate()
    verifier = StubVerifier(verification(False, "tests failed"), verification(False, "tests still failed"))
    repair = StubRepair({"success": False, "attempts": []})
    engine = make_engine(plan, gate, verifier, repair, [{"success": True}])

    result = engine.execute_plan("Modify a file")

    assert "not completed safely" in result
    assert engine.lifecycle_state == ExecutionLifecycleState.FAILED
    assert engine.last_outcome.state == ExecutionLifecycleState.FAILED
    assert engine.last_outcome.verification.success is False
    assert engine.plan_manager.save_plan.call_count == 1
    assert repair.calls == 1
