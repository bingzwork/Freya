from pathlib import Path

from app.autonomy.models import AutonomyConfig
from app.core.protocols import SystemConfig
from app.learning.models import LearningCandidate, LearningCandidateType
from app.orchestrator.capability_registry import reset_capability_registry
from main import FreyaApp


import pytest


@pytest.fixture(autouse=True)
def isolate_capability_registry():
    reset_capability_registry()
    yield
    reset_capability_registry()


def _start(tmp_path: Path, enabled: bool) -> FreyaApp:
    workspace = tmp_path / ("enabled" if enabled else "disabled")
    workspace.mkdir()
    app = FreyaApp(
        workspace,
        SystemConfig(
            workspace=workspace,
            enable_autonomy=enabled,
            enable_orchestrator=False,
            enable_diagnostics=False,
            enable_self_improvement=False,
            enable_file_watcher=False,
            enable_config_hot_reload=False,
            autonomy_config=AutonomyConfig(
                watchdog_enabled=False,
                self_initiated_enabled=False,
                maintenance_enabled=False,
            ),
        ),
    )
    app.start()
    return app


def test_production_initializer_starts_canonical_learning_pipeline(tmp_path: Path):
    app = _start(tmp_path, True)
    try:
        pipeline = app.system.learning_pipeline
        assert pipeline is app.system.autonomy._learning_pipeline
        assert pipeline.is_running() is True
        assert app.system.infra.job_service.get_job("autonomy_learning_pipeline") is not None
        assert app.system.autonomy.get_status()["learning_pipeline"]["started_by_autonomy"] is True
    finally:
        app.shutdown()


def test_disabled_autonomy_does_not_start_learning_pipeline(tmp_path: Path):
    app = _start(tmp_path, False)
    try:
        assert app.system.autonomy is None
        assert app.system.learning_pipeline.is_running() is False
    finally:
        app.shutdown()


def test_background_learning_handoff_reaches_durable_memory(tmp_path: Path):
    app = _start(tmp_path, True)
    try:
        pipeline = app.system.learning_pipeline
        candidate = LearningCandidate(
            candidate_type=LearningCandidateType.WATCHDOG_OBSERVATION,
            source_component="Task11Test",
            raw_observation={"event": "knowledge_gap", "gap": "verified execution"},
            context={"origin": "long_term_autonomy"},
            tags=["task11", "learning_gap"],
        )

        pipeline.submit(candidate)
        assert pipeline._drain_pending() >= 1

        experiences = list(app.system.memory.experience_memory.all())
        assert any(
            entry.metadata.get("source_component") == "Task11Test"
            for entry in experiences
        )
        assert (app.workspace / "data" / "memory" / "experience_memory.json").exists()
    finally:
        app.shutdown()


def test_learning_pipeline_shutdown_removes_shared_background_job(tmp_path: Path):
    app = _start(tmp_path, True)
    job_service = app.system.infra.job_service
    try:
        assert job_service.get_job("autonomy_learning_pipeline") is not None
    finally:
        app.shutdown()

    assert job_service.get_job("autonomy_learning_pipeline") is None
