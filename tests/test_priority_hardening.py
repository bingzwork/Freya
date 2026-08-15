"""Focused contracts for the P1/P2 canonical-runtime hardening work."""

from types import SimpleNamespace

import pytest

from app.autonomy.models import AutonomyConfig, WatchdogEventType, WatchdogSeverity
from app.autonomy.watchdog import Watchdog
from app.core.background_jobs import (
    BackgroundJobService,
    JobStatus,
    JobTriggerConfig,
    JobTriggerType,
)
from app.core.correlation import correlation_scope
from app.core.events import Event, EventBus
from app.orchestrator.capability_registry import (
    Capability,
    CapabilityMetadata,
    CapabilityRegistry,
    reset_capability_registry,
)


class RecordingLearningPipeline:
    def __init__(self):
        self.candidates = []

    def submit(self, candidate):
        self.candidates.append(candidate)


class ToolManagerStub:
    def execute(self, *_args, **_kwargs):
        return SimpleNamespace(success=True)

    def register(self, *_args, **_kwargs):
        return None


@pytest.fixture(autouse=True)
def clean_capability_registry():
    reset_capability_registry()
    yield
    reset_capability_registry()


def test_watchdog_deduplicates_replayed_observations_before_learning_queue():
    pipeline = RecordingLearningPipeline()
    watchdog = Watchdog(
        config=AutonomyConfig(
            use_background_job_service=True,
            watchdog_dedup_window_seconds=60.0,
            watchdog_dedup_max_entries=2,
        ),
        learning_pipeline=pipeline,
    )

    for _ in range(2):
        watchdog._create_observation(
            event_type=WatchdogEventType.HEALTH_CHECK,
            severity=WatchdogSeverity.WARNING,
            component="memory_coordinator",
            message="Memory coordinator is degraded",
            details={"status": "degraded", "checked_at": "ephemeral"},
        )

    assert len(pipeline.candidates) == 1


def test_running_recurring_job_is_not_redispatched():
    jobs = BackgroundJobService()
    jobs.schedule(
        "recurring-job",
        lambda: None,
        JobTriggerConfig(type=JobTriggerType.RECURRING, interval_seconds=1.0),
    )
    job = jobs.get_job("recurring-job")
    job.status = JobStatus.RUNNING

    assert job.is_ready(current_time=job.trigger_time + 10.0) is False


def test_event_and_background_job_lifecycle_retain_one_correlation_identifier():
    bus = EventBus()
    observed: list[Event] = []

    def capture(event: Event) -> None:
        observed.append(event)

    bus.subscribe("trace.*", capture)
    bus.subscribe("job.created", capture)

    with correlation_scope("request_123"):
        bus.emit("trace.router.decision", {"decision": "answer"}, source="test")

    jobs = BackgroundJobService(event_bus=bus)
    jobs.schedule(
        "correlated-job",
        lambda: None,
        JobTriggerConfig(type=JobTriggerType.ONE_TIME),
        correlation_id="request_123",
    )

    assert [event.metadata["correlation_id"] for event in observed] == [
        "request_123",
        "request_123",
    ]
    assert observed[-1].data["correlation_id"] == "request_123"


def test_startup_audit_isolates_unsafe_discovery_and_checks_declared_collaborators():
    registry = CapabilityRegistry()
    internal = Capability(
        CapabilityMetadata(
            name="internal_action",
            description="Internal workflow action",
            default_action="run",
            supported_actions=["run"],
            required_collaborators=["tool_manager"],
        ),
        handler=lambda _inputs: {"success": True},
    )
    query = Capability(
        CapabilityMetadata(
            name="safe_query",
            description="Read-only status query",
            default_action="execute",
            supported_actions=["execute"],
            safe_query=True,
        ),
        handler=lambda _inputs: {"success": True},
    )
    assert registry.register(internal)
    assert registry.register(query)
    registry.start()

    audit = registry.audit_startup(collaborators={"tool_manager": ToolManagerStub()})

    assert audit["passed"] is True
    assert internal.metadata.auto_discoverable is False
    assert query.metadata.auto_discoverable is True
    assert audit["tool_manager_available"] is True


def test_extension_ports_use_registry_events_scheduler_and_memory_boundary():
    """A representative extension reaches shared services only through four ports."""
    bus = EventBus()
    received: list[Event] = []

    def capture(event: Event) -> None:
        received.append(event)

    bus.subscribe("job.created", capture)

    registry = CapabilityRegistry()
    extension = Capability(
        CapabilityMetadata(
            name="extension_probe",
            description="Read-only extension probe",
            default_action="inspect",
            supported_actions=["inspect"],
            safe_query=True,
        ),
        handler=lambda inputs: {"success": True, "correlation_id": inputs["correlation_id"]},
    )
    assert registry.register(extension, registered_by="extension-test")
    registry.start()

    jobs = BackgroundJobService(event_bus=bus)
    job_id = jobs.schedule(
        "extension-probe-job",
        lambda: bus.emit("extension.observed", {"source": "extension"}),
        JobTriggerConfig(type=JobTriggerType.ONE_TIME),
        correlation_id="extension_123",
    )

    # The extension can be registered, observed, and scheduled via shared ports.
    # Durable learning remains covered by LearningPipeline's existing
    # MemoryCoordinator-only persistence contract rather than a direct store.
    assert registry.get_capability("extension_probe") is extension
    assert jobs.get_job(job_id).metadata["correlation_id"] == "extension_123"
    assert received and received[0].name == "job.created"
