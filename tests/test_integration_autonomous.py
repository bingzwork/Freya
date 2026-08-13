"""Production-path integration evidence for the canonical Freya runtime.

These tests intentionally enter through ``FreyaApp`` and retain the production
object graph built by ``SystemInitializer``.  Only true external boundaries are
substituted: the local LLM and operating-system verification command runner.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

import pytest

from app.core.background_jobs import JobStatus, JobTriggerConfig, JobTriggerType
from app.core.events import Event as FreyaEvent
from app.core.events import get_event_bus
from app.core.observability import get_observability_hub
from app.core.protocols import SystemConfig
from app.execution.engine import ExecutionLifecycleState
from app.safe_self_improvement.models import (
    FileModification,
    ImprovementCandidate,
    ImprovementCategory,
    ModificationType,
    RiskLevel,
)
from app.verification.runner import VerificationResult
from main import FreyaApp


def _start_application(tmp_path: Path, *, enable_autonomy: bool) -> FreyaApp:
    """Start the canonical production graph with only autonomy made optional."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Freya production integration fixture.\n")
    app = FreyaApp(
        workspace,
        SystemConfig(workspace=workspace, enable_autonomy=enable_autonomy),
    )
    app.start()
    return app


@pytest.fixture
def production_app(tmp_path: Path):
    """Provide the normal foreground Freya production graph for focused paths."""
    app = _start_application(tmp_path, enable_autonomy=False)
    try:
        yield app
    finally:
        app.shutdown()


@pytest.fixture
def autonomous_app(tmp_path: Path):
    """Provide the complete graph, including the production autonomy runtime."""
    app = _start_application(tmp_path, enable_autonomy=True)
    try:
        yield app
    finally:
        app.shutdown()


def _verified_result(success: bool, stderr: str = "") -> VerificationResult:
    """Return the result supplied by the operating-system verification boundary."""
    return VerificationResult(
        success=success,
        command=["verify", "tests+lint"],
        stdout="verification passed" if success else "",
        stderr=stderr,
        return_code=0 if success else 1,
    )


def _deterministic_llm(prompt: str, *args, **kwargs) -> str:
    """Deterministic replacement for the external local-LLM service."""
    if "Plan a SHORT execution" in prompt:
        return '{"steps": ["Read README.md"]}'
    if "Summarize for the user" in prompt:
        return "The requested read completed and verification passed."
    return "Freya is running through the verified production path."


def _run_task_with_verification(
    app: FreyaApp,
    monkeypatch: pytest.MonkeyPatch,
    verification_result: VerificationResult,
) -> str:
    """Exercise the public task API with real internal wiring and safe fakes."""
    system = app.system
    monkeypatch.setattr(system.priority_llm, "ask", _deterministic_llm)
    monkeypatch.setattr(
        system.execution._execution_verifier._verification_runner,
        "dry_run_verify",
        lambda: verification_result,
    )
    return app.execute_task("Read README.md", allow_mutations=False)


def test_startup_composes_one_shared_production_graph(autonomous_app: FreyaApp):
    """FreyaApp startup builds the canonical graph rather than legacy substitutes."""
    system = autonomous_app.system

    assert type(system.facade).__name__ == "AgentFacadeImpl"
    assert type(system.control).__name__ == "ConversationControlHandler"
    assert type(system.execution).__name__ == "ExecutionEngine"
    assert type(system.autonomy).__name__ == "AutonomyManager"
    assert type(system.orchestrator).__name__ == "WorkflowOrchestrator"
    assert system.learning_pipeline is not None
    assert system.diagnostics is not None
    assert system.self_improvement is not None

    assert system.execution._safety_gate is system.orchestrator.safety_gate
    assert system.infra.event_bus is get_event_bus()
    assert system.infra.job_service is system.autonomy._job_service
    assert system.infra.observability is get_observability_hub()
    assert system.control.event_bus is system.infra.event_bus
    assert system.control.job_service is system.infra.job_service
    assert system.control.observability is system.infra.observability
    assert system.autonomy.is_running()
    assert autonomous_app._running


def test_public_chat_question_reaches_the_production_control_path(production_app: FreyaApp):
    """A normal chat request travels through FreyaApp, facade, router, and control."""
    response = production_app.chat("status")

    assert response == "Idle. Waiting for next request."
    assert production_app.system.facade.get_status().chat_active is False


def test_public_task_success_is_safety_checked_verified_learned_and_persisted(
    production_app: FreyaApp,
    monkeypatch: pytest.MonkeyPatch,
):
    """The public task API completes only after the real execution verifier succeeds."""
    response = _run_task_with_verification(
        production_app, monkeypatch, _verified_result(True)
    )
    execution = production_app.system.execution

    assert response == "The requested read completed and verification passed."
    assert execution.lifecycle_state is ExecutionLifecycleState.SUCCEEDED
    assert execution.last_outcome is not None
    assert execution.last_outcome.verification is not None
    assert execution.last_outcome.verification.success is True
    assert execution.last_learning_outcome is not None
    assert execution.last_learning_outcome.success is True
    assert execution.plan_manager.load_plan(execution.last_outcome.plan_id) is not None


def test_safety_denial_stops_the_public_task_before_any_side_effect(
    production_app: FreyaApp,
    monkeypatch: pytest.MonkeyPatch,
):
    """A critical destructive request is denied by the real SafetyGate."""
    monkeypatch.setattr(production_app.system.priority_llm, "ask", _deterministic_llm)
    protected = production_app.workspace / "README.md"
    original = protected.read_text()

    response = production_app.execute_task("rm -rf /", allow_mutations=True)
    execution = production_app.system.execution

    assert "not completed safely" in response
    assert execution.lifecycle_state is ExecutionLifecycleState.SAFETY_DENIED
    assert execution.last_outcome is not None
    assert "blocked by safety gate" in (execution.last_outcome.error or "").lower()
    assert protected.read_text() == original


def test_failed_verification_routes_to_recovery_and_safe_failure(
    production_app: FreyaApp,
    monkeypatch: pytest.MonkeyPatch,
):
    """A verifier rejection cannot be presented as successful task completion."""
    response = _run_task_with_verification(
        production_app, monkeypatch, _verified_result(False, "fixture verification failure")
    )
    execution = production_app.system.execution

    assert "not completed safely" in response
    assert execution.lifecycle_state is ExecutionLifecycleState.FAILED
    assert execution.last_outcome is not None
    assert execution.last_outcome.verification is not None
    assert execution.last_outcome.verification.success is False
    assert "verification failed" in (execution.last_outcome.error or "").lower()
    assert execution.last_learning_outcome is not None
    assert execution.last_learning_outcome.success is False


def test_retrieval_and_persistence_survive_a_real_app_restart(tmp_path: Path):
    """State is written through the live app graph and loaded by a new FreyaApp."""
    workspace = tmp_path / "restart-workspace"
    workspace.mkdir()
    marker = "production-restart-retrieval-marker"

    first = FreyaApp(workspace, SystemConfig(workspace=workspace, enable_autonomy=False))
    first.start()
    try:
        first.system.memory.record_conversation({"role": "user", "content": marker})
        retrieved = first.system.memory.unified_retrieval.retrieve(marker)
        assert any(marker in result.content for result in retrieved)
    finally:
        first.shutdown()

    second = FreyaApp(workspace, SystemConfig(workspace=workspace, enable_autonomy=False))
    second.start()
    try:
        history = second.system.memory.conversation_memory.get_history()
        assert any(turn.content == marker for turn in history)
        assert (workspace / "data" / "memory" / "conversation_memory.json").exists()
    finally:
        second.shutdown()


def test_diagnostics_events_and_monitoring_use_the_shared_runtime_infrastructure(
    production_app: FreyaApp,
):
    """Diagnostics publish meaningful lifecycle data to the live event and monitoring services."""
    system = production_app.system
    received: list[FreyaEvent] = []
    subscription = system.infra.event_bus.subscribe("diagnostics.completed", received.append)

    try:
        issues = system.diagnostics.run([str(production_app.workspace)])
    finally:
        system.infra.event_bus.unsubscribe(subscription)

    assert issues is not None
    assert received
    assert received[-1]["workspace"] == str(production_app.workspace)

    component_names = {component["name"] for component in system.infra.observability.list_components()}
    assert {"SafetyGate", "WorkflowOrchestrator", "ConversationControlHandler"} <= component_names
    health = system.infra.observability.get_health()
    assert health["status"] in {"healthy", "degraded", "unhealthy", "unknown"}
    assert system.infra.observability.get_system_metrics() is not None


def test_autonomy_jobs_run_on_the_shared_service_and_record_results(
    autonomous_app: FreyaApp,
):
    """The production autonomy manager registers jobs and the shared service records outcomes."""
    system = autonomous_app.system
    job_service = system.infra.job_service
    autonomy = system.autonomy

    assert autonomy.get_status()["running"] is True
    assert job_service.get_job("watchdog_health_check").func == autonomy.watchdog._periodic_health_check
    assert job_service.get_job("self_initiated_work_check") is not None
    assert job_service.get_job("maintenance_check") is not None

    completed = Event()
    completed_id = job_service.schedule(
        job_id="task7_production_job_success",
        func=lambda: completed.set(),
        trigger=JobTriggerConfig(type=JobTriggerType.ONE_TIME),
        max_retries=0,
        replace_existing=True,
    )
    assert completed.wait(5.0)
    assert job_service.get_job(completed_id).status is JobStatus.COMPLETED
    assert job_service.get_job_history(completed_id)[-1]["success"] is True

    failed = Event()

    def fail_job() -> None:
        failed.set()
        raise RuntimeError("task7 expected job failure")

    failed_id = job_service.schedule(
        job_id="task7_production_job_failure",
        func=fail_job,
        trigger=JobTriggerConfig(type=JobTriggerType.ONE_TIME),
        max_retries=0,
        replace_existing=True,
    )
    assert failed.wait(5.0)
    assert job_service.get_job(failed_id).status is JobStatus.FAILED
    assert job_service.get_job_history(failed_id)[-1]["success"] is False


def test_safe_self_improvement_keeps_rejected_candidates_from_mutating_files(
    production_app: FreyaApp,
):
    """The live improvement engine validates proposals and preserves approval controls."""
    engine = production_app.system.self_improvement
    protected = production_app.workspace / "secrets" / "rejected.py"
    rejected = ImprovementCandidate(
        title="Rejected protected-file proposal",
        description="Attempt to change a protected path.",
        category=ImprovementCategory.SECURITY,
        source="integration-test",
        modifications=[
            FileModification(
                modification_type=ModificationType.CREATE,
                file_path="secrets/rejected.py",
                new_content="print('must never be written')\n",
                category=ImprovementCategory.SECURITY,
                risk_level=RiskLevel.HIGH,
            )
        ],
    )

    result = engine.submit_improvement(rejected, auto_execute=True)

    assert result.accepted is False
    assert result.error
    assert not protected.exists()
    assert engine.get_candidate_status(rejected.id)["status"] == "unknown"


def test_shutdown_releases_shared_runtime_services(tmp_path: Path):
    """A completed FreyaApp shutdown does not leave stale global service references."""
    workspace = tmp_path / "shutdown-workspace"
    workspace.mkdir()
    app = FreyaApp(workspace, SystemConfig(workspace=workspace, enable_autonomy=False))
    app.start()
    app.shutdown()

    assert app._running is False
    assert app.system.infra.job_service._shutdown is True
    assert app.system.infra.event_bus._running is False
    assert get_event_bus() is not app.system.infra.event_bus
""
