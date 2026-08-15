from pathlib import Path

from app.core.protocols import SystemConfig
from app.orchestrator.capability_registry import CapabilityRegistry
from main import FreyaApp


def test_initializer_exposes_one_canonical_runtime_graph(tmp_path: Path):
    app = FreyaApp(
        tmp_path,
        SystemConfig(
            enable_file_watcher=False,
            enable_config_hot_reload=False,
        ),
    )
    app.start()
    system = app.system
    try:
        assert system.runtime_awareness is not None
        assert system.system_anatomy is not None
        assert system.diagnostics is not None
        assert system.diagnostic_grouper is not None
        assert system.predictive_diagnostics is not None
        assert system.improvement_measurement is not None
        assert system.canary_validator is not None
        assert system.patch_promotion_manager is not None
        assert system.self_improvement is not None

        assert system.runtime_awareness._event_bus is system.infra.event_bus
        assert system.runtime_awareness._observability is system.infra.observability
        assert system.predictive_diagnostics._runtime_awareness is system.runtime_awareness
        assert system.predictive_diagnostics._event_bus is system.infra.event_bus
        assert system.diagnostics._event_bus is system.infra.event_bus
        assert system.system_anatomy._capability_registry is CapabilityRegistry()
        assert system.self_improvement.promotion_manager is system.patch_promotion_manager
        assert system.self_improvement.rollback_manager is system.patch_promotion_manager.rollback_manager
        assert system.patch_promotion_manager.config.canary_validator is system.canary_validator
        assert callable(system.canary_validator._executor)
        assert system.runtime_awareness.get_stats()["running"] is True
        assert system.predictive_diagnostics._running is True
    finally:
        app.shutdown()

    assert system.runtime_awareness.get_stats()["running"] is False
    assert system.predictive_diagnostics._running is False
    assert system.infra.job_service.is_running() is False
