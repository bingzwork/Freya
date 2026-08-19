from pathlib import Path
from types import SimpleNamespace

from app.core.protocols import SystemConfig
from app.ui.agent_console import (
    get_agent_console_snapshot,
    get_memory_snapshot,
    get_system_snapshot,
    get_tasks_snapshot,
)


class FakeJobs:
    def list_jobs(self, limit=None):
        return [
            {
                "id": "job-1",
                "name": "Autonomy learning",
                "type": "recurring",
                "status": "running",
                "created_at": "2026-08-19T00:00:00+00:00",
                "started_at": "2026-08-19T00:01:00+00:00",
                "completed_at": None,
                "last_error": None,
                "origin": "autonomy",
                "autonomous": True,
                "goal_id": "goal-1",
                "workflow_id": "workflow-1",
                "trace_id": "trace-1",
                "waiting_reason": None,
                "approval_required": False,
            }
        ]

    def get_job_history(self, limit=100):
        return [
            {
                "job_id": "job-2",
                "job_name": "Completed maintenance",
                "success": True,
                "duration_seconds": 2.5,
                "timestamp": "2026-08-19T00:02:00+00:00",
            }
        ]


class FakeMemory:
    def get_status_snapshot(self):
        return {
            "memory_system_ready": True,
            "working_memory_active": False,
            "working_memory_active_items": 0,
            "conversation_context_items": 4,
            "long_term_memory_available": True,
            "knowledge_store_available": True,
            "retrieval_status": "ready",
            "recent_retrieval_count": None,
            "recent_storage_count": None,
            "last_memory_activity_at": None,
            "learning_pipeline_ready": None,
            "pending_learning_count": None,
            "accepted_learning_count": None,
            "rejected_learning_count": None,
            "last_learning_activity_at": None,
        }


class FakeObservability:
    def get_readiness_status(self, initialized=True):
        return {
            "status": "ready",
            "ready": True,
            "dependencies": [
                {"name": "agent_facade", "status": "healthy"},
                {"name": "llm_providers", "status": "healthy"},
                {"name": "memory_coordinator", "status": "healthy"},
            ],
        }

    def get_system_metrics(self):
        return {
            "system.cpu.percent": 21.5,
            "system.memory.total_gb": 16.0,
            "system.memory.used_gb": 8.0,
            "system.memory.percent": 50.0,
            "system.disk.percent": 42.0,
            "system.process.memory_mb": 123.0,
        }


class FakeAutonomy:
    def get_status(self):
        return {"state": "OFF", "running": False, "active_autonomous_tasks": 0}


class FakeSafetyGate:
    def get_stats(self):
        return {"policy_mode": "balanced", "total_assessments": 3, "pending_approvals": 0}


class FakeSystem:
    def __init__(self):
        self.infra = SimpleNamespace(job_service=FakeJobs(), observability=FakeObservability())
        self.memory = FakeMemory()
        self.learning_pipeline = None
        self.autonomy = FakeAutonomy()
        self.orchestrator = SimpleNamespace(_safety_gate=FakeSafetyGate())
        self.priority_llm = SimpleNamespace(_llm=SimpleNamespace(model="qwen3.5:4b", get_provider_health=lambda: {}))


def test_tasks_snapshot_uses_real_job_and_history_metadata_without_raw_payloads():
    snapshot = get_tasks_snapshot(FakeSystem())
    assert snapshot["available"] is True
    assert {task["task_id"] for task in snapshot["tasks"]} == {"job-1", "job-2"}
    active = next(task for task in snapshot["tasks"] if task["task_id"] == "job-1")
    assert active["origin"] == "AUTONOMY"
    assert active["status"] == "RUNNING"
    assert active["trace_id"] == "trace-1"
    assert "metadata" not in active
    assert "prompt" not in active


def test_memory_snapshot_is_metadata_only():
    snapshot = get_memory_snapshot(FakeSystem())
    assert snapshot["available"] is True
    assert snapshot["conversation_context_items"] == 4
    assert "content" not in snapshot
    assert "prompt" not in snapshot
    assert "embedding" not in snapshot


def test_system_snapshot_maps_flat_observability_metrics_and_model():
    snapshot = get_system_snapshot(FakeSystem())
    assert snapshot["available"] is True
    assert snapshot["hardware"]["cpu_percent"] == 21.5
    assert snapshot["hardware"]["memory_used_gb"] == 8.0
    assert snapshot["hardware"]["memory_total_gb"] == 16.0
    assert snapshot["hardware"]["disk_percent"] == 42.0
    assert snapshot["components"]["local_model"]["model"] == "qwen3.5:4b"
    assert snapshot["components"]["local_model"]["ready"] is True
    assert snapshot["components"]["safety_gate"]["status"] == "Ready"
    assert snapshot["components"]["safety_gate"]["mode"] == "balanced"


def test_agent_console_snapshot_keeps_autonomy_explicitly_off_by_default():
    snapshot = get_agent_console_snapshot(FakeSystem())
    assert snapshot["autonomy"]["state"] == "OFF"
    assert snapshot["autonomy"]["running"] is False
    assert snapshot["tasks"]["available"] is True


def test_system_config_defaults_autonomy_startup_off():
    config = SystemConfig()
    assert config.start_autonomy_on_boot is False


def test_frontend_uses_real_agent_console_endpoints_and_confirmation():
    source = Path("client/src/pages/Home.tsx").read_text(encoding="utf-8")
    assert "/api/agent-console" in source
    assert "/api/autonomy/${action}" in source
    assert "action: 'start' | 'stop'" in source
    assert "Enable Freya Autonomy?" in source
    assert "Task state is not exposed by the current frontend API bridge." not in source
    assert "Memory retrieval details are not exposed by the current safe UI bridge." not in source
