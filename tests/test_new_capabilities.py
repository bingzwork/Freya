from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from app.api_connector.capability import APIConnectorCapability
from app.automation.capability import AutomationCapability
from app.orchestrator.capabilities import create_all_capabilities
from app.vision.capability import VisionCapability, VisionEvidence


class FakeJob:
    def __init__(self, job_id):
        self.id = job_id


class FakeJobService:
    def __init__(self):
        self.jobs = {}
        self.history = []

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def schedule(self, job_id, func, trigger, **kwargs):
        self.jobs[job_id] = FakeJob(job_id)
        self.jobs[job_id].func = func
        self.jobs[job_id].trigger = trigger
        return job_id

    def get_job_summary(self, job_id):
        return {"id": job_id, "status": "scheduled"} if job_id in self.jobs else None

    def get_job_history(self, job_id=None, limit=100):
        return [record for record in self.history if record.get("job_id") == job_id][:limit]

    def pause_job(self, job_id):
        return job_id in self.jobs

    def resume_job(self, job_id):
        return job_id in self.jobs

    def cancel_job(self, job_id):
        return job_id in self.jobs

    def remove_job(self, job_id):
        return self.jobs.pop(job_id, None) is not None


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def execute_intent(self, request, context):
        self.calls.append((request, context))
        return "workflow-1"


class FakeVisionProvider:
    name = "fake"

    def ocr(self, image_path):
        return VisionEvidence(text="Total: 12.50", confidence=0.96, provider=self.name)

    def analyze(self, image_path, question):
        return VisionEvidence(text="The visible error is timeout", confidence=0.91, provider=self.name)

    def extract_fields(self, image_path, fields):
        return VisionEvidence(fields={field: "value" for field in fields}, confidence=0.88, provider=self.name)


class FakeCredentialStore:
    def resolve(self, reference):
        assert reference == "github_token"
        return {"Authorization": "Bearer top-secret"}


class FakeSafetyGate:
    class Assessment:
        allowed = True

    def __init__(self):
        self.calls = []

    def check_and_enforce(self, **kwargs):
        self.calls.append(kwargs)
        return self.Assessment()


def test_capability_factory_registers_new_capabilities():
    capabilities = {cap.name: cap for cap in create_all_capabilities()}
    assert {"automation", "vision", "api_connector"}.issubset(capabilities)
    assert capabilities["automation"].supports_action("create_schedule")
    assert capabilities["vision"].supports_action("ocr")
    assert capabilities["api_connector"].supports_action("request")


def test_automation_creates_recurring_job_and_uses_workflow_boundary(tmp_path):
    jobs = FakeJobService()
    orchestrator = FakeOrchestrator()
    capability = AutomationCapability(tmp_path)
    capability.set_services(jobs, orchestrator, workspace=tmp_path)

    result = capability.action_create_schedule({
        "schedule_id": "weekly-leads",
        "name": "Weekly leads",
        "request": "Research new podcast leads",
        "trigger_type": "recurring",
        "interval_seconds": 3600,
    })

    assert result["success"] is True
    assert result["schedule"]["id"] == "weekly-leads"
    assert jobs.jobs["weekly-leads"].trigger.interval_seconds == 3600
    jobs.jobs["weekly-leads"].func()
    assert orchestrator.calls[0][0] == "Research new podcast leads"
    assert orchestrator.calls[0][1]["source"] == "automation_capability"


def test_automation_persists_and_reloads_schedule(tmp_path):
    jobs = FakeJobService()
    capability = AutomationCapability(tmp_path)
    capability.set_services(jobs, FakeOrchestrator(), workspace=tmp_path)
    created = capability.action_create_schedule({
        "schedule_id": "persisted-id",
        "request": "send a reminder",
        "trigger_type": "one_time",
        "delay_seconds": 60,
    })
    assert created["success"] is True

    reloaded_jobs = FakeJobService()
    reloaded = AutomationCapability(tmp_path)
    reloaded.set_services(reloaded_jobs, FakeOrchestrator(), workspace=tmp_path)
    restored = reloaded.restore_persisted()
    assert restored["restored"] == 1
    assert "persisted-id" in reloaded_jobs.jobs


def test_automation_rejects_invalid_cron_expression(tmp_path):
    capability = AutomationCapability(tmp_path)
    capability.set_services(FakeJobService(), FakeOrchestrator(), workspace=tmp_path)
    result = capability.action_create_schedule({
        "schedule_id": "bad-cron",
        "request": "run",
        "trigger_type": "cron",
        "cron_expression": "every monday",
    })
    assert result["success"] is False
    assert "cron_expression" in result["error"]


def test_automation_rejects_unsafe_frequency_and_duplicate_ids(tmp_path):
    jobs = FakeJobService()
    capability = AutomationCapability(tmp_path)
    capability.set_services(jobs, FakeOrchestrator(), workspace=tmp_path)

    invalid = capability.action_create_schedule({
        "schedule_id": "too-fast",
        "request": "run",
        "trigger_type": "recurring",
        "interval_seconds": 5,
    })
    assert invalid["success"] is False
    assert "interval" in invalid["error"]

    first = capability.action_create_schedule({
        "schedule_id": "same-id",
        "request": "run once",
        "trigger_type": "one_time",
    })
    second = capability.action_create_schedule({
        "schedule_id": "same-id",
        "request": "run again",
        "trigger_type": "one_time",
    })
    assert first["success"] is True
    assert second["success"] is False


def test_new_capabilities_are_discoverable_by_the_existing_router_bridge(tmp_path):
    from app.capabilities.registration_bridge import CapabilityRegistrationBridge
    from app.capabilities.router import CapabilityRouter
    from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry

    reset_capability_registry()
    registry = CapabilityRegistry()
    router = CapabilityRouter()

    class ToolManagerStub:
        def __init__(self):
            self.tools = {}

        def register(self, name, handler):
            self.tools[name] = handler

        def execute(self, name, **kwargs):
            class Result:
                success = True
                output = kwargs["context"]
                error = None
            return Result()

    bridge = CapabilityRegistrationBridge(
        registry=registry,
        router=router,
        tool_manager=ToolManagerStub(),
    )
    for capability in (AutomationCapability(tmp_path), VisionCapability(provider=FakeVisionProvider()), APIConnectorCapability(allowed_domains={"api.example.com"})):
        assert registry.register(capability)
    bridge.sync()

    assert router.find_matching("Remind me tomorrow to send the report")[0][0] == "automation"
    assert router.find_matching("Read this screenshot and extract the text")[0][0] == "vision"
    assert router.find_matching("Call this API endpoint with GET")[0][0] == "api_connector"


def test_vision_ocr_returns_structured_evidence(tmp_path):
    image_path = tmp_path / "receipt.png"
    Image.new("RGB", (10, 10), "white").save(image_path)
    capability = VisionCapability(provider=FakeVisionProvider())

    result = capability.action_ocr({"image_path": str(image_path)})

    assert result["success"] is True
    assert result["text"] == "Total: 12.50"
    assert result["confidence"] == 0.96
    assert result["evidence"]["source"]["filename"] == "receipt.png"


def test_vision_provider_error_is_not_fabricated(tmp_path):
    image_path = tmp_path / "empty.png"
    Image.new("RGB", (10, 10), "white").save(image_path)

    class UnavailableProvider(FakeVisionProvider):
        def ocr(self, image_path):
            return VisionEvidence(provider="unavailable", error="provider unavailable", uncertain=True)

    result = VisionCapability(provider=UnavailableProvider()).action_ocr({"image_path": str(image_path)})
    assert result["success"] is False
    assert result["text"] == ""
    assert "unavailable" in result["message"]


def test_api_connector_allows_configured_get_and_redacts_credentials():
    calls = []

    def fake_http(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {
            "status": 200,
            "headers": {"Content-Type": "application/json", "Set-Cookie": "secret-cookie"},
            "json": {"token_echo": "Bearer top-secret"},
            "body": "Bearer top-secret",
            "error": None,
        }

    capability = APIConnectorCapability(
        allowed_domains={"api.example.com"},
        credential_store=FakeCredentialStore(),
        http_client=fake_http,
    )
    result = capability.action_get({
        "url": "https://api.example.com/data",
        "credential_ref": "github_token",
    })

    assert result["success"] is True
    assert result["status"] == 200
    assert result["headers"]["Set-Cookie"] == "[REDACTED]"
    assert "top-secret" not in result["body"]
    assert "top-secret" not in str(result["json"])
    assert calls[0][2]["headers"]["Authorization"] == "Bearer top-secret"


def test_api_connector_blocks_domain_url_and_raw_sensitive_headers():
    client = Mock(return_value={"status": 200, "headers": {}, "json": {}, "body": "", "error": None})
    capability = APIConnectorCapability(allowed_domains={"api.example.com"}, http_client=client)

    assert capability.action_get({"url": "https://evil.example.net/data"})["success"] is False
    assert capability.action_get({"url": "http://127.0.0.1:8080/admin"})["success"] is False
    assert capability.action_get({
        "url": "https://api.example.com/data",
        "headers": {"Authorization": "Bearer raw-secret"},
    })["success"] is False
    client.assert_not_called()


def test_api_connector_requires_safety_gate_for_mutating_methods():
    client = Mock(return_value={"status": 201, "headers": {}, "json": {"ok": True}, "body": "{}", "error": None})
    capability = APIConnectorCapability(allowed_domains={"api.example.com"}, http_client=client)
    blocked = capability.action_post({"url": "https://api.example.com/data", "json_body": {"ok": True}})
    assert blocked["success"] is False
    assert "SafetyGate" in blocked["error"]
    client.assert_not_called()

    gate = FakeSafetyGate()
    capability.set_safety_gate(gate)
    allowed = capability.action_post({"url": "https://api.example.com/data", "json_body": {"ok": True}})
    assert allowed["success"] is True
    assert gate.calls[0]["operation_type"] == "external_api_call"
