import time
from pathlib import Path

from app.automation.capability import AutomationCapability
from app.core.background_jobs import (
    BackgroundJobService,
    JobStatus,
    NonRetryableJobError,
    RetryConfig,
)


class FakeWorkflowOrchestrator:
    def __init__(self):
        self.preflight_calls = []
        self.execution_calls = []

    def validate_intent(self, request, context=None):
        self.preflight_calls.append((request, context or {}))
        if "zero-step" in request:
            return {"valid": False, "steps": 0}
        return {"valid": True, "steps": 1, "capabilities": ["show_identity"]}

    def execute_intent(self, request, context=None, async_mode=True):
        self.execution_calls.append((request, context or {}))
        return "execution-id"


def make_capability(tmp_path: Path):
    service = BackgroundJobService(tick_interval=0.01)
    orchestrator = FakeWorkflowOrchestrator()
    capability = AutomationCapability(workspace=tmp_path)
    capability.set_services(service, orchestrator, workspace=tmp_path)
    return capability, service, orchestrator


def test_capability_evaluation_prompt_is_not_scheduled(tmp_path):
    capability, service, _ = make_capability(tmp_path)
    request = "Use the automation capability. Cover these eight cases in your response."
    result = capability.action_create_schedule({"request": request})
    assert result["success"] is False
    assert "capability-evaluation" in result["error"]
    assert service.list_jobs() == []
    assert capability.action_list_schedules({})["count"] == 0


def test_missing_schedule_time_is_controlled_failure(tmp_path):
    capability, service, _ = make_capability(tmp_path)
    result = capability.action_create_schedule({"request": "Remind me to call John."})
    assert result["success"] is False
    assert "schedule timing is required" in result["error"]
    assert service.list_jobs() == []


def test_valid_natural_language_one_time_schedule_is_preflighted_and_created(tmp_path):
    capability, service, orchestrator = make_capability(tmp_path)
    result = capability.action_create_schedule({
        "request": "Remind me tomorrow at 9 AM to check my email.",
    })
    assert result["success"] is True
    assert result["schedule"]["trigger_type"] == "one_time"
    assert result["schedule"]["delay_seconds"] >= 60
    assert orchestrator.preflight_calls
    schedule_id = result["schedule"]["id"]
    assert service.get_job(schedule_id) is not None
    assert capability.action_remove({"schedule_id": schedule_id})["success"] is True


def test_valid_recurring_schedule_is_created(tmp_path):
    capability, service, _ = make_capability(tmp_path)
    result = capability.action_create_schedule({
        "request": "Every Monday at 9 AM remind me to review my tasks.",
    })
    assert result["success"] is True
    assert result["schedule"]["trigger_type"] == "recurring"
    assert result["schedule"]["interval_seconds"] == 604800.0
    capability.action_remove({"schedule_id": result["schedule"]["id"]})


def test_zero_step_preflight_never_persists_or_schedules(tmp_path):
    capability, service, _ = make_capability(tmp_path)
    result = capability.action_create_schedule({
        "request": "Remind me tomorrow to run a zero-step workflow.",
    })
    assert result["success"] is False
    assert "Workflow has no executable steps" in result["error"]
    assert service.list_jobs() == []
    assert capability.action_list_schedules({})["count"] == 0


def test_deterministic_validation_failure_is_terminal_without_retry():
    service = BackgroundJobService(tick_interval=0.01)

    def fail_deterministically():
        raise NonRetryableJobError("Workflow has no executable steps")

    job_id = service.add_job(
        fail_deterministically,
        name="deterministic-invalid-workflow",
        retry_config=RetryConfig(max_retries=5, base_delay_seconds=0.01),
    )
    service.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline:
            summary = service.get_job_summary(job_id)
            if summary and summary["status"] == JobStatus.FAILED.value:
                break
            time.sleep(0.01)
        summary = service.get_job_summary(job_id)
        assert summary["status"] == JobStatus.FAILED.value
        assert summary["current_retry"] == 0
        assert len(service.get_job_history(job_id=job_id)) == 1
        time.sleep(0.08)
        assert len(service.get_job_history(job_id=job_id)) == 1
    finally:
        service.shutdown(timeout=2)


def test_failed_job_is_excluded_from_future_scheduler_ticks():
    service = BackgroundJobService(tick_interval=0.01)
    calls = []

    def fail_once():
        calls.append(time.time())
        raise ValueError("invalid workflow schema")

    job_id = service.add_job(
        fail_once,
        name="terminal-invalid-workflow",
        retry_config=RetryConfig(max_retries=0),
    )
    service.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline and not service.get_job_summary(job_id)["status"] == JobStatus.FAILED.value:
            time.sleep(0.01)
        time.sleep(0.08)
        assert service.get_job_summary(job_id)["status"] == JobStatus.FAILED.value
        assert len(calls) == 1
        assert len(service.get_job_history(job_id=job_id)) == 1
    finally:
        service.shutdown(timeout=2)


def test_transient_failure_retries_with_bounded_backoff():
    service = BackgroundJobService(tick_interval=0.005)
    calls = []

    def transient_then_success():
        calls.append(time.time())
        if len(calls) < 3:
            raise RuntimeError("temporary provider timeout")
        return "ok"

    job_id = service.add_job(
        transient_then_success,
        name="bounded-transient-job",
        retry_config=RetryConfig(max_retries=2, base_delay_seconds=0.01, max_delay_seconds=0.02),
    )
    service.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline and service.get_job_summary(job_id)["status"] != JobStatus.COMPLETED.value:
            time.sleep(0.01)
        assert service.get_job_summary(job_id)["status"] == JobStatus.COMPLETED.value
        assert len(calls) == 3
        assert len(service.get_job_history(job_id=job_id)) == 3
    finally:
        service.shutdown(timeout=2)
