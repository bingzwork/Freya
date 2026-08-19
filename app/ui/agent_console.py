"""Safe operational aggregation for Freya's Agent Console.

This module is deliberately read-oriented: it adapts existing canonical services
into bounded UI metadata and never exposes prompts, memory records, credentials,
or hidden reasoning.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, Iterable, List, Optional

try:
    import psutil
except ImportError:  # pragma: no cover - the monitoring stack already owns this dependency
    psutil = None


_STATUS_MAP = {
    "pending": "QUEUED",
    "scheduled": "QUEUED",
    "queued": "QUEUED",
    "planning": "PLANNING",
    "running": "RUNNING",
    "retrying": "RUNNING",
    "paused": "PAUSED",
    "waiting": "WAITING",
    "waiting_for_approval": "WAITING_FOR_APPROVAL",
    "completed": "COMPLETED",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "interrupted": "INTERRUPTED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = 180) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] if value else None


def _status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return _STATUS_MAP.get(raw, raw.upper() if raw else "UNKNOWN")


def _duration(started_at: Any, completed_at: Any, fallback: Any = None) -> Optional[float]:
    if fallback is not None:
        try:
            return round(float(fallback), 3)
        except (TypeError, ValueError):
            pass
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00")) if completed_at else datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return round(max(0.0, (end - start).total_seconds()), 3)
    except (TypeError, ValueError):
        return None


def _origin(record: Dict[str, Any]) -> Optional[str]:
    if bool(record.get("autonomous")):
        return "AUTONOMY"
    raw = str(record.get("origin") or "").strip().lower()
    if raw in {"autonomy", "autonomous"}:
        return "AUTONOMY"
    if raw in {"schedule", "scheduled", "cron"}:
        return "SCHEDULE"
    if raw in {"maintenance", "system"}:
        return raw.upper()
    if raw in {"user", "chat"}:
        return "USER"
    return raw.upper() if raw else None


def _task_from_job(job: Dict[str, Any]) -> Dict[str, Any]:
    record = dict(job)
    return {
        "task_id": _text(record.get("id"), 120),
        "title": _text(record.get("name"), 180) or "Background job",
        "type": _text(record.get("type"), 60) or "background_job",
        "origin": _origin(record),
        "status": _status(record.get("status")),
        "created_at": record.get("created_at"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "duration": _duration(record.get("started_at"), record.get("completed_at")),
        "progress": None,
        "goal_id": _text(record.get("goal_id"), 120),
        "workflow_id": _text(record.get("workflow_id"), 120),
        "trace_id": _text(record.get("trace_id"), 120),
        "waiting_reason": _text(record.get("waiting_reason"), 240),
        "approval_required": record.get("approval_required") if isinstance(record.get("approval_required"), bool) else None,
        "failure_summary": _text(record.get("last_error"), 300),
        "autonomous": bool(record.get("autonomous")),
        "source": "background_job_service",
    }


def _task_from_history(record: Dict[str, Any]) -> Dict[str, Any]:
    success = record.get("success") is True
    status = "COMPLETED" if success else "FAILED"
    return {
        "task_id": _text(record.get("job_id"), 120),
        "title": _text(record.get("job_name"), 180) or "Background job",
        "type": "background_job",
        "origin": None,
        "status": status,
        "created_at": None,
        "started_at": None,
        "completed_at": record.get("timestamp"),
        "duration": _duration(None, None, record.get("duration_seconds")),
        "progress": None,
        "goal_id": None,
        "workflow_id": None,
        "trace_id": None,
        "waiting_reason": None,
        "approval_required": None,
        "failure_summary": _text(record.get("error"), 300),
        "autonomous": False,
        "source": "background_job_history",
    }


def _task_from_work(item: Any, source: str) -> Dict[str, Any]:
    metadata = dict(getattr(item, "metadata", {}) or {})
    source_value = str(getattr(item, "source", "") or source).strip().lower()
    autonomous = True
    origin = "MAINTENANCE" if source_value == "maintenance" else "AUTONOMY"
    title = getattr(item, "description", None) or metadata.get("goal_name") or metadata.get("maintenance_task_name") or "Autonomous work"
    return {
        "task_id": _text(getattr(item, "id", None), 120),
        "title": _text(title, 180),
        "type": "maintenance" if source_value == "maintenance" else "autonomous_work",
        "origin": origin,
        "status": _status(getattr(item, "status", None)),
        "created_at": getattr(item, "created_at", None),
        "started_at": metadata.get("started_at"),
        "completed_at": metadata.get("completed_at"),
        "duration": _duration(metadata.get("started_at"), metadata.get("completed_at")),
        "progress": None,
        "goal_id": _text(getattr(item, "goal_id", None) or metadata.get("goal_id"), 120),
        "workflow_id": _text(getattr(item, "workflow_execution_id", None), 120),
        "trace_id": _text(metadata.get("trace_id"), 120),
        "waiting_reason": _text(metadata.get("waiting_reason"), 240),
        "approval_required": metadata.get("approval_required") if isinstance(metadata.get("approval_required"), bool) else None,
        "failure_summary": _text((metadata.get("completion_details") or {}).get("error") if isinstance(metadata.get("completion_details"), dict) else None, 300),
        "autonomous": autonomous,
        "source": source_value or source,
    }


def _workflow_tasks(system: Any) -> List[Dict[str, Any]]:
    orchestrator = getattr(system, "orchestrator", None)
    executor = getattr(orchestrator, "_task_executor", None)
    if executor is None or not callable(getattr(executor, "list_active_workflows", None)):
        return []
    output: List[Dict[str, Any]] = []
    try:
        workflow_ids = executor.list_active_workflows()
    except Exception:
        return []
    for workflow_id in workflow_ids[:30]:
        context = executor.get_context(workflow_id) if callable(getattr(executor, "get_context", None)) else None
        metadata = dict(getattr(context, "metadata", {}) or {}) if context is not None else {}
        state = executor.get_status(workflow_id) if callable(getattr(executor, "get_status", None)) else None
        raw_state = getattr(state, "value", state)
        output.append({
            "task_id": _text(workflow_id, 120),
            "title": _text(metadata.get("safe_title") or metadata.get("task_title"), 180) or "Workflow execution",
            "type": "workflow",
            "origin": _origin(metadata),
            "status": _status(raw_state),
            "created_at": metadata.get("created_at"),
            "started_at": metadata.get("started_at"),
            "completed_at": metadata.get("completed_at"),
            "duration": _duration(metadata.get("started_at"), metadata.get("completed_at")),
            "progress": None,
            "goal_id": _text(metadata.get("goal_id"), 120),
            "workflow_id": _text(workflow_id, 120),
            "trace_id": _text(metadata.get("trace_id") or metadata.get("correlation_id"), 120),
            "waiting_reason": _text(metadata.get("waiting_reason"), 240),
            "approval_required": metadata.get("approval_required") if isinstance(metadata.get("approval_required"), bool) else None,
            "failure_summary": _text(metadata.get("failure_summary"), 300),
            "autonomous": bool(metadata.get("autonomous")),
            "source": "workflow_orchestrator",
        })
    return output


def get_tasks_snapshot(system: Any, limit: int = 50) -> Dict[str, Any]:
    infra = getattr(system, "infra", None)
    job_service = getattr(infra, "job_service", None)
    if job_service is None:
        return {"available": False, "tasks": [], "active_count": None, "updated_at": _now(), "error": "Background task service unavailable"}

    tasks: List[Dict[str, Any]] = []
    try:
        tasks.extend(_task_from_job(item) for item in job_service.list_jobs(limit=max(limit, 30)))
        known = {item.get("task_id") for item in tasks}
        for record in job_service.get_job_history(limit=max(limit, 30)):
            item = _task_from_history(record)
            if item.get("task_id") not in known:
                tasks.append(item)
                known.add(item.get("task_id"))
    except Exception as exc:
        return {"available": False, "tasks": [], "active_count": None, "updated_at": _now(), "error": "Task state could not be read safely"}

    autonomy = getattr(system, "autonomy", None)
    if autonomy is not None:
        for owner, source in ((getattr(autonomy, "self_initiated", None), "self_initiated"), (getattr(autonomy, "maintenance", None), "maintenance")):
            try:
                for item in (owner.get_active_work() if owner is not None else [])[:limit]:
                    normalized = _task_from_work(item, source)
                    if normalized.get("task_id") not in {task.get("task_id") for task in tasks}:
                        tasks.append(normalized)
            except Exception:
                continue
    tasks.extend(_workflow_tasks(system))
    deduped: Dict[str, Dict[str, Any]] = {}
    for task in tasks:
        key = task.get("task_id") or f"{task.get('source')}:{task.get('title')}"
        deduped[key] = task
    ordered = list(deduped.values())[:max(1, limit)]
    active_states = {"QUEUED", "PLANNING", "RUNNING", "WAITING", "WAITING_FOR_APPROVAL", "PAUSED"}
    return {
        "available": True,
        "tasks": ordered,
        "active_count": sum(1 for item in ordered if item.get("status") in active_states),
        "updated_at": _now(),
        "source": "BackgroundJobService + canonical workflow/autonomy owners",
    }


def get_memory_snapshot(system: Any) -> Dict[str, Any]:
    memory = getattr(system, "memory", None)
    if memory is None or not callable(getattr(memory, "get_status_snapshot", None)):
        return {"available": False, "error": "Memory coordinator unavailable", "updated_at": _now()}
    try:
        snapshot = dict(memory.get_status_snapshot())
    except Exception:
        return {"available": False, "error": "Memory metadata could not be read safely", "updated_at": _now()}
    pipeline = getattr(system, "learning_pipeline", None)
    if pipeline is not None:
        snapshot["learning_pipeline_ready"] = bool(getattr(pipeline, "is_running", lambda: False)())
        pending = getattr(pipeline, "_pending_candidates", None)
        snapshot["pending_learning_count"] = len(pending) if pending is not None else None
    snapshot["available"] = True
    snapshot["updated_at"] = _now()
    return snapshot


def _component_status(readiness: Dict[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    entries = {str(item.get("name", "")).lower(): item for item in readiness.get("dependencies", []) if isinstance(item, dict)}
    for name in names:
        item = entries.get(name.lower())
        if item:
            raw = str(item.get("status") or "unknown").lower()
            ready = raw in {"healthy", "ready", "ok"}
            return {"status": "Ready" if ready else raw.title(), "ready": ready, "source": item.get("name")}
    return {"status": "Unavailable", "ready": False, "source": None}


def _browser_component_status(system: Any, readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Report Browser from the canonical BrowserCapability, not a missing readiness dependency."""
    capability = getattr(system, "browser_capability", None)
    if capability is None:
        try:
            from app.orchestrator.capability_registry import CapabilityRegistry
            capability = CapabilityRegistry().get_capability("browser_capability")
        except Exception:
            capability = None
    if capability is not None:
        state = getattr(getattr(capability, "state", None), "value", getattr(capability, "state", ""))
        executable = bool(getattr(capability, "is_executable", lambda: False)())
        adapter = getattr(capability, "_adapter", None)
        context_active = bool(getattr(adapter, "_context", None) is not None)
        owner_thread = getattr(adapter, "_owner_thread", None)
        owner_active = bool(owner_thread is not None and owner_thread.is_alive())
        active = context_active and owner_active
        ready = executable and state not in {"error", "deactivating"}
        if active:
            status = "Active"
        elif ready:
            status = "Ready"
        else:
            status = "Unavailable"
        return {"status": status, "ready": ready, "active": active, "source": "browser_capability"}
    return _component_status(readiness, ("browser", "browser_capability", "playwright_browser"))


def _metric(metrics: Any, *paths: str) -> Any:
    for path in paths:
        if isinstance(metrics, dict) and path in metrics:
            return metrics[path]
        value = metrics
        try:
            for part in path.split("."):
                value = value[part] if isinstance(value, dict) else getattr(value, part)
            if value is not None:
                return value
        except (KeyError, AttributeError, TypeError):
            continue
    return None


def get_system_snapshot(system: Any, autonomy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    infra = getattr(system, "infra", None)
    observability = getattr(infra, "observability", None)
    if observability is None:
        return {"available": False, "error": "Observability service unavailable", "updated_at": _now()}
    try:
        readiness = observability.get_readiness_status(initialized=True)
        metrics = observability.get_system_metrics()
    except Exception:
        return {"available": False, "error": "System status could not be read safely", "updated_at": _now()}

    memory = get_memory_snapshot(system)
    provider = getattr(system, "priority_llm", None)
    llm = getattr(provider, "_llm", None)
    model_name = _text(getattr(llm, "model", None), 120)
    provider_health = {}
    try:
        provider_health = dict(llm.get_provider_health()) if llm is not None and callable(getattr(llm, "get_provider_health", None)) else {}
    except Exception:
        provider_health = {}
    model_ready = any(bool(item.get("reachable") or item.get("healthy") or item.get("ready") or str(item.get("status", "")).lower() in {"healthy", "ready", "ok"}) for item in provider_health.values() if isinstance(item, dict)) if provider_health else False
    if not model_ready:
        model_ready = _component_status(readiness, ("llm_providers", "agent_facade"))["ready"]

    memory_status = "Ready" if memory.get("available") and memory.get("memory_system_ready") else "Unavailable"
    components = {
        "freya_core": _component_status(readiness, ("agent_facade",)),
        "local_model": {"status": "Ready" if model_ready else "Unavailable", "ready": model_ready, "model": model_name},
        "memory": {"status": "Ready" if memory_status == "Ready" else "Unavailable", "ready": memory_status == "Ready"},
        "database": _component_status(readiness, ("database", "memory_coordinator")),
        "browser": _browser_component_status(system, readiness),
        "safety_gate": _component_status(readiness, ("safety_gate", "safetygate")),
    }
    safety_gate = getattr(getattr(system, "orchestrator", None), "_safety_gate", None)
    if safety_gate is not None:
        try:
            safety_stats = dict(safety_gate.get_stats()) if callable(getattr(safety_gate, "get_stats", None)) else {}
            components["safety_gate"] = {
                "status": "Ready",
                "ready": True,
                "mode": safety_stats.get("policy_mode") or "balanced",
                "total_assessments": safety_stats.get("total_assessments", 0),
                "pending_approvals": safety_stats.get("pending_approvals", 0),
            }
        except Exception:
            pass
    cpu = _metric(metrics, "system.cpu.percent", "cpu_percent", "cpu.percent", "cpu.usage_percent")
    memory_total = _metric(metrics, "system.memory.total_gb", "memory_total_gb", "memory.total_gb", "memory.total")
    memory_used = _metric(metrics, "system.memory.used_gb", "memory_used_gb", "memory.used_gb", "memory.used")
    memory_percent = _metric(metrics, "system.memory.percent", "memory_percent", "memory.percent")
    gpu = _metric(metrics, "gpu", "gpus")
    if not gpu:
        try:
            from app.monitoring.gpu_monitor import get_gpu_monitor
            gpu_summary = get_gpu_monitor().get_summary()
            if isinstance(gpu_summary, dict) and gpu_summary.get("total_gpus", 0):
                gpu = gpu_summary
        except Exception:
            gpu = None
    uptime = _metric(metrics, "uptime_seconds", "system.uptime_seconds")
    if uptime is None and psutil is not None:
        try:
            uptime = max(0.0, time.time() - psutil.Process().create_time())
        except Exception:
            uptime = None
    return {
        "available": True,
        "updated_at": _now(),
        "readiness": readiness,
        "components": components,
        "hardware": {
            "cpu_percent": cpu,
            "memory_used_gb": memory_used,
            "memory_total_gb": memory_total,
            "memory_percent": memory_percent,
            "gpu": gpu if gpu else None,
            "disk_percent": _metric(metrics, "system.disk.percent", "disk_percent", "disk.percent"),
            "process_memory_mb": _metric(metrics, "system.process.memory_mb", "process_memory_mb", "process.memory_mb"),
            "uptime_seconds": uptime,
        },
        "autonomy": autonomy or {"state": "OFF", "running": False, "active_autonomous_tasks": 0},
    }


def get_autonomy_snapshot(system: Any) -> Dict[str, Any]:
    manager = getattr(system, "autonomy", None)
    if manager is None or not callable(getattr(manager, "get_status", None)):
        return {"available": False, "state": "OFF", "running": False, "active_autonomous_tasks": None, "last_error": "Autonomy manager unavailable", "updated_at": _now()}
    try:
        status = dict(manager.get_status())
        status["available"] = True
        status["updated_at"] = _now()
        return status
    except Exception:
        return {"available": False, "state": "ERROR", "running": False, "active_autonomous_tasks": None, "last_error": "Autonomy status unavailable", "updated_at": _now()}


def get_agent_console_snapshot(system: Any) -> Dict[str, Any]:
    autonomy = get_autonomy_snapshot(system)
    return {
        "tasks": get_tasks_snapshot(system),
        "memory": get_memory_snapshot(system),
        "system": get_system_snapshot(system, autonomy=autonomy),
        "autonomy": autonomy,
        "updated_at": _now(),
    }
