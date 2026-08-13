"""Focused Task 5 evidence for execution-to-learning durable-memory wiring."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.events import EventBus
from app.core.initializer import SystemInitializer
from app.core.protocols import SystemConfig
from app.execution.engine import ExecutionEngine, ExecutionLifecycleState
from app.learning.models import LearningCandidateType
from app.learning.pipeline import LearningPipeline
from app.memory.coordinator import MemoryCoordinator
from app.planner.task import Task
from app.verification.execution_verifier import ExecutionVerifier
from app.verification.runner import VerificationResult


class StaticVerificationRunner:
    """Deterministic verification collaborator for the canonical engine path."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    def dry_run_verify(self):
        self.calls += 1
        return self._results[min(self.calls - 1, len(self._results) - 1)]


class StaticRepairLoop:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def run(self, _propose):
        self.calls += 1
        return self._result


def verification(success: bool, stderr: str = "") -> VerificationResult:
    return VerificationResult(
        success=success,
        command=["verify"],
        stdout="verified" if success else "",
        stderr=stderr,
        return_code=0 if success else 1,
    )


def build_engine(tmp_path, execution_results, verification_runner, repair_loop):
    """Build the real engine method around real verifier, learning, and memory components."""
    memory = MemoryCoordinator(tmp_path, EventBus())
    learning_pipeline = LearningPipeline(memory)
    execution_verifier = ExecutionVerifier(
        verification_runner=verification_runner,
        learning_pipeline=learning_pipeline,
        observability_hub=MagicMock(),
        chat_activity=MagicMock(),
    )
    task = Task(id="task-5", title="Persist execution outcome")
    plan = SimpleNamespace(id="plan-5", tasks=[task], status="draft")

    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine._chat_activity = MagicMock()
    engine._memory = MagicMock()
    engine._memory.retrieve_for_planning.return_value = "retrieved context"
    engine._planner = MagicMock()
    engine._planner.create_plan.return_value = plan
    engine._executor = SimpleNamespace(
        execute=MagicMock(return_value=execution_results),
        _repair=repair_loop,
    )
    engine._execution_verifier = execution_verifier
    engine._safety_gate = None
    engine._llm = MagicMock()
    engine._llm.ask.return_value = "verified summary"
    engine.plan_manager = MagicMock()
    engine._lifecycle_state = None
    engine._execution_records = {}
    engine._last_outcome = None
    engine._last_learning_outcome = None
    engine._conversation_control = None
    return engine, memory


def test_production_initializer_injects_shared_learning_pipeline_into_execution_verifier(tmp_path):
    config = SystemConfig(
        enable_autonomy=False,
        enable_orchestrator=False,
        enable_diagnostics=False,
        enable_self_improvement=False,
        enable_file_watcher=False,
        enable_config_hot_reload=False,
        enable_observability=False,
    )
    initializer = SystemInitializer(tmp_path, config)
    system = initializer.initialize()

    try:
        assert system.execution._execution_verifier._learning_pipeline is system.learning_pipeline
        assert system.execution._execution_verifier._observability_hub is system.infra.observability
    finally:
        initializer.shutdown(system)


def test_successful_execution_is_verified_learned_and_persisted_to_durable_memory(tmp_path):
    verification_runner = StaticVerificationRunner(verification(True))
    engine, memory = build_engine(
        tmp_path,
        execution_results=[{"success": True, "result": "applied"}],
        verification_runner=verification_runner,
        repair_loop=StaticRepairLoop({"success": False, "attempts": []}),
    )

    result = engine.execute_plan("Apply verified change", allow_mutations=True)

    assert result == "verified summary"
    assert engine.lifecycle_state is ExecutionLifecycleState.SUCCEEDED
    assert verification_runner.calls == 1
    outcome = engine.last_learning_outcome
    assert outcome.success is True
    assert outcome.learning_candidate.candidate_type is LearningCandidateType.EXECUTION_OUTCOME
    assert outcome.learning_candidate.raw_observation["execution_success"] is True
    assert outcome.learning_candidate.raw_observation["verification"]["success"] is True

    entries = memory._experience.search(category="execution_outcome", outcome="positive")
    assert len(entries) == 1
    assert entries[0].metadata["task"] == "Apply verified change"
    assert entries[0].metadata["verification_success"] is True
    durable_path = tmp_path / "data" / "memory" / "experience_memory.json"
    assert durable_path.exists()
    assert any(entry["outcome"] == "positive" for entry in json.loads(durable_path.read_text())["entries"])


def test_failed_verification_is_learned_and_persisted_to_durable_memory(tmp_path):
    verification_runner = StaticVerificationRunner(verification(False, "tests failed"))
    engine, memory = build_engine(
        tmp_path,
        execution_results=[{"success": True, "result": "applied"}],
        verification_runner=verification_runner,
        repair_loop=StaticRepairLoop({"success": False, "attempts": []}),
    )

    result = engine.execute_plan("Apply unverified change", allow_mutations=True)

    assert "not completed safely" in result
    assert engine.lifecycle_state is ExecutionLifecycleState.FAILED
    assert verification_runner.calls == 1
    outcome = engine.last_learning_outcome
    assert outcome.success is False
    assert outcome.learning_candidate.raw_observation["execution_success"] is False
    assert outcome.learning_candidate.raw_observation["verification"]["success"] is False
    assert outcome.learning_candidate.raw_observation["error"] == "Execution verification failed: tests failed"

    entries = memory._experience.search(category="execution_outcome", outcome="negative")
    assert len(entries) == 1
    assert entries[0].metadata["task"] == "Apply unverified change"
    assert entries[0].metadata["verification_success"] is False
    durable_path = tmp_path / "data" / "memory" / "experience_memory.json"
    assert durable_path.exists()
    assert any(entry["outcome"] == "negative" for entry in json.loads(durable_path.read_text())["entries"])


def test_learning_persistence_failure_cannot_be_reported_as_execution_success(tmp_path):
    verification_runner = StaticVerificationRunner(verification(True))
    engine, memory = build_engine(
        tmp_path,
        execution_results=[{"success": True, "result": "applied"}],
        verification_runner=verification_runner,
        repair_loop=StaticRepairLoop({"success": False, "attempts": []}),
    )
    memory._experience.store = MagicMock(side_effect=OSError("disk unavailable"))

    result = engine.execute_plan("Apply change with unavailable memory", allow_mutations=True)

    assert "execution learning handoff failed" in result.lower()
    assert engine.lifecycle_state is ExecutionLifecycleState.FAILED
    assert engine.last_outcome.error.startswith("Execution learning handoff failed")
