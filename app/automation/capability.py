"""User-defined automation capability over Freya's canonical background services."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from app.core.atomic_store import AtomicJsonStore
from app.core.logger import logger
from app.core.background_jobs import (
    BackgroundJobService,
    JobPriority,
    JobStatus,
    JobTriggerConfig,
    JobTriggerType,
    NonRetryableJobError,
)
from app.orchestrator.capability_registry import CapabilityCategory, CapabilityMetadata
from app.orchestrator.capabilities import BaseCapability


_MIN_INTERVAL_SECONDS = 60.0
_MAX_RUNS = 100_000
_MAX_REQUEST_LENGTH = 20_000
_CRON_FIELD = re.compile(r"^[0-9*/,\-]+$")
_SCHEDULE_MARKER_RE = re.compile(
    r"\b(?:tomorrow|today|tonight|in\s+\d+\s+(?:minute|minutes|hour|hours|day|days)|"
    r"every\s+(?:day|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)|cron|interval|one[- ]time|delayed)\b",
    re.IGNORECASE,
)
_INTROSPECTION_MARKER_RE = re.compile(
    r"\b(?:capability|test|tests|testing|cases|scenarios|explain|response|introspection|"
    r"how\s+.*\bhandles?\b|cover\s+these)\b",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


@dataclass
class AutomationDefinition:
    """Persistable user automation definition; executable state stays in the job service."""

    id: str
    request: str
    trigger_type: str
    delay_seconds: float = 0.0
    interval_seconds: float = 0.0
    cron_expression: str = ""
    max_runs: Optional[int] = None
    name: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutomationDefinition":
        return cls(
            id=str(data["id"]),
            request=str(data["request"]),
            trigger_type=str(data["trigger_type"]),
            delay_seconds=float(data.get("delay_seconds", 0.0)),
            interval_seconds=float(data.get("interval_seconds", 0.0)),
            cron_expression=str(data.get("cron_expression", "")),
            max_runs=data.get("max_runs"),
            name=str(data.get("name", "")),
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            enabled=bool(data.get("enabled", True)),
        )


class AutomationCapability(BaseCapability):
    """Schedule safe Freya requests through the existing workflow boundary."""

    def __init__(self, workspace: Optional[str | Path] = None):
        super().__init__(CapabilityMetadata(
            name="automation",
            version="1.0.0",
            description=(
                "Create and manage one-time reminders, recurring Freya workflows, "
                "and persisted background schedules"
            ),
            category=CapabilityCategory.ORCHESTRATION,
            is_singleton=True,
            auto_discoverable=True,
            safe_query=True,
            default_action="create_schedule",
            supported_actions=[
                "create_schedule", "list_schedules", "get_status", "get_history",
                "pause", "resume", "cancel", "remove",
            ],
            tags=[
                "automation", "schedule", "scheduled", "remind", "reminder", "tomorrow",
                "recurring", "every", "monday", "workflow", "watch",
                "active jobs", "job history",
            ],
        ))
        self._workspace = Path(workspace or Path.cwd())
        self._job_service: Optional[BackgroundJobService] = None
        self._workflow_orchestrator = None
        self._store: Optional[AtomicJsonStore[AutomationDefinition]] = None
        self._lock = threading.RLock()
        self._restored = False

    def set_services(
        self,
        job_service: BackgroundJobService,
        workflow_orchestrator,
        *,
        workspace: Optional[str | Path] = None,
    ) -> None:
        self._job_service = job_service
        self._workflow_orchestrator = workflow_orchestrator
        if workspace is not None:
            self._workspace = Path(workspace)
        self._store = AtomicJsonStore(
            self._workspace / "data" / "scheduling" / "automations.json",
            AutomationDefinition,
        )

    def restore_persisted(self) -> Dict[str, Any]:
        """Re-register enabled definitions after the canonical services are bound."""
        if self._restored:
            return {"restored": 0, "skipped": 0}
        if not self._job_service or not self._workflow_orchestrator or self._store is None:
            return {"restored": 0, "skipped": 0, "error": "Automation services unavailable"}

        restored = skipped = 0
        with self._lock:
            for definition in self._store.values():
                if not definition.enabled:
                    continue
                try:
                    if self._job_service.get_job(definition.id) is None:
                        self._schedule_definition(definition, persist=False)
                    restored += 1
                except (TypeError, ValueError, RuntimeError) as error:
                    skipped += 1
                    definition.enabled = False
                    self._store.set(definition.id, definition)
                    logger.warning(
                        "Disabled invalid persisted automation %s during restore: %s",
                        definition.id,
                        error,
                    )
        self._restored = True
        return {"restored": restored, "skipped": skipped}

    def action_create_schedule(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self._job_service or not self._workflow_orchestrator:
            return self._error("Automation services are not initialized")
        request = str(inputs.get("request") or inputs.get("task") or "").strip()
        if not request:
            return self._error("request is required")
        if len(request) > _MAX_REQUEST_LENGTH:
            return self._error("request is too long")

        if self._is_capability_introspection_request(request, inputs):
            return self._error(
                "This is a capability-evaluation request, not a schedulable automation. "
                "Provide a concrete action and a trigger such as a date, time, interval, or recurrence."
            )

        trigger_type = str(inputs.get("trigger_type") or inputs.get("type") or "").lower()
        try:
            normalized_inputs = dict(inputs)
            if not trigger_type and not any(
                key in normalized_inputs for key in (
                    "delay_seconds", "interval_seconds", "cron_expression", "trigger_type", "type", "max_runs"
                )
            ):
                trigger_type, inferred = self._infer_natural_schedule(request)
                normalized_inputs.update(inferred)
            trigger_type = trigger_type or "one_time"
            definition = self._definition_from_inputs(request, trigger_type, normalized_inputs)
            self._preflight_definition(definition)
            with self._lock:
                if self._job_service.get_job(definition.id) is not None:
                    return self._error("A schedule with this id already exists")
                self._schedule_definition(definition, persist=True)
            return {
                "success": True,
                "schedule": self._summary(definition),
                "message": f"Schedule '{definition.name}' created.",
            }
        except (TypeError, ValueError, RuntimeError) as error:
            return self._error(str(error))

    def action_list_schedules(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self._job_service:
            return self._error("BackgroundJobService is not initialized")
        with self._lock:
            schedules = []
            for definition in (self._store.values() if self._store is not None else []):
                summary = self._summary(definition)
                summary["job"] = self._job_service.get_job_summary(definition.id)
                schedules.append(summary)
        return {"success": True, "schedules": schedules, "count": len(schedules)}

    def action_get_status(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self._job_service:
            return self._error("BackgroundJobService is not initialized")
        job_id = str(inputs.get("schedule_id") or inputs.get("job_id") or "").strip()
        if not job_id:
            return self._error("schedule_id is required")
        summary = self._job_service.get_job_summary(job_id)
        if summary is None:
            return self._error("Schedule not found")
        return {"success": True, "schedule": summary, "history": self._job_service.get_job_history(job_id=job_id)}

    def action_get_history(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self._job_service:
            return self._error("BackgroundJobService is not initialized")
        job_id = inputs.get("schedule_id") or inputs.get("job_id")
        limit = max(1, min(int(inputs.get("limit", 100)), 1000))
        return {"success": True, "history": self._job_service.get_job_history(job_id=job_id, limit=limit)}

    def action_pause(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._change_state(inputs, "pause")

    def action_resume(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._change_state(inputs, "resume")

    def action_cancel(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._change_state(inputs, "cancel")

    def action_remove(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self._change_state(inputs, "remove")

    def _change_state(self, inputs: Dict[str, Any], action: str) -> Dict[str, Any]:
        if not self._job_service:
            return self._error("BackgroundJobService is not initialized")
        job_id = str(inputs.get("schedule_id") or inputs.get("job_id") or "").strip()
        if not job_id:
            return self._error("schedule_id is required")
        method = {
            "pause": self._job_service.pause_job,
            "resume": self._job_service.resume_job,
            "cancel": self._job_service.cancel_job,
            "remove": self._job_service.remove_job,
        }[action]
        changed = method(job_id)
        if not changed:
            return self._error("Schedule not found or state change was not applicable")
        if action in {"cancel", "remove"} and self._store is not None:
            definition = self._store.get(job_id)
            if definition:
                definition.enabled = False
                self._store.set(job_id, definition)
        return {"success": True, "schedule_id": job_id, "action": action}

    def _schedule_definition(self, definition: AutomationDefinition, *, persist: bool) -> None:
        if not self._job_service or not self._workflow_orchestrator:
            raise RuntimeError("Automation services are not initialized")
        self._preflight_definition(definition)

        def run_workflow() -> Any:
            """Enter through WorkflowOrchestrator so routing and safety remain authoritative."""
            try:
                return self._workflow_orchestrator.execute_intent(
                    definition.request,
                    {
                        "source": "automation_capability",
                        "scheduled_job_id": definition.id,
                        "schedule_name": definition.name,
                    },
                )
            except (TypeError, ValueError) as error:
                raise NonRetryableJobError(str(error)) from error

        trigger_type = JobTriggerType(definition.trigger_type)
        trigger = JobTriggerConfig(
            type=trigger_type,
            delay_seconds=definition.delay_seconds,
            interval_seconds=definition.interval_seconds,
            cron_expression=definition.cron_expression,
            max_runs=definition.max_runs,
        )
        self._job_service.schedule(
            definition.id,
            run_workflow,
            trigger,
            priority=JobPriority.NORMAL,
            max_retries=2,
            name=definition.name,
            replace_existing=False,
            automation_id=definition.id,
            request=definition.request,
        )
        if persist and self._store is not None:
            self._store.set(definition.id, definition)

    @staticmethod
    def _is_capability_introspection_request(request: str, inputs: Dict[str, Any]) -> bool:
        text = request.strip().lower()
        if bool(inputs.get("capability_test")) or bool(inputs.get("introspection")):
            return True
        return bool(_INTROSPECTION_MARKER_RE.search(text)) and not bool(_SCHEDULE_MARKER_RE.search(text))

    @staticmethod
    def _parse_clock(text: str) -> tuple[int, int] | None:
        match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            raise ValueError("schedule time is outside the valid clock range")
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return hour, minute

    @classmethod
    def _infer_natural_schedule(cls, request: str) -> tuple[str, Dict[str, Any]]:
        text = request.lower()
        now = datetime.now().astimezone()
        clock = cls._parse_clock(text)
        relative = re.search(r"\bin\s+(\d+)\s+(minute|minutes|hour|hours|day|days)\b", text)
        if relative:
            amount = int(relative.group(1))
            unit = relative.group(2)
            multiplier = 60 if unit.startswith("minute") else 3600 if unit.startswith("hour") else 86400
            return "one_time", {"delay_seconds": float(amount * multiplier)}

        weekday_match = re.search(r"\bevery\s+(day|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text)
        if weekday_match:
            cadence = weekday_match.group(1)
            interval = 86400.0 if cadence == "day" else 604800.0
            target = now
            if clock:
                target = target.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
            if cadence in _WEEKDAYS:
                days_ahead = (_WEEKDAYS[cadence] - target.weekday()) % 7
                if days_ahead == 0 and target <= now:
                    days_ahead = 7
                target += timedelta(days=days_ahead)
            elif target <= now:
                target += timedelta(seconds=interval)
            delay = max(60.0, (target - now).total_seconds())
            return "recurring", {"delay_seconds": delay, "interval_seconds": interval}

        if re.search(r"\b(?:tomorrow|today|tonight)\b", text) or clock:
            target = now
            if clock:
                target = target.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
            if re.search(r"\btomorrow\b", text) or target <= now:
                target += timedelta(days=1)
            delay = max(60.0, (target - now).total_seconds())
            return "one_time", {"delay_seconds": delay}

        raise ValueError(
            "schedule timing is required; specify a date/time, relative delay, interval, or recurrence"
        )

    def _preflight_definition(self, definition: AutomationDefinition) -> None:
        validator = getattr(self._workflow_orchestrator, "validate_intent", None)
        if not callable(validator):
            return
        result = validator(
            definition.request,
            {
                "source": "automation_preflight",
                "scheduled_job_id": definition.id,
                "schedule_name": definition.name,
            },
        )
        if isinstance(result, dict) and int(result.get("steps", 0)) < 1:
            raise ValueError("Workflow has no executable steps")

    @staticmethod
    def _definition_from_inputs(request: str, trigger_type: str, inputs: Dict[str, Any]) -> AutomationDefinition:
        if trigger_type == "delayed":
            trigger_type = "one_time"
        if trigger_type not in {"one_time", "recurring", "cron"}:
            raise ValueError("trigger_type must be one_time, recurring, or cron")

        max_runs = inputs.get("max_runs")
        if max_runs is not None:
            max_runs = int(max_runs)
            if max_runs < 1 or max_runs > _MAX_RUNS:
                raise ValueError(f"max_runs must be between 1 and {_MAX_RUNS}")

        delay = float(inputs.get("delay_seconds", 0.0))
        if delay < 0 or delay > 31_536_000:
            raise ValueError("delay_seconds must be between 0 and one year")

        interval = float(inputs.get("interval_seconds", 0.0))
        cron = str(inputs.get("cron_expression", "")).strip()
        if trigger_type == "recurring":
            if interval < _MIN_INTERVAL_SECONDS or interval > 31_536_000:
                raise ValueError(f"recurring interval must be between {_MIN_INTERVAL_SECONDS:g} seconds and one year")
        if trigger_type == "cron":
            AutomationCapability._validate_cron(cron)
        if trigger_type == "one_time" and max_runs not in (None, 1):
            raise ValueError("one-time schedules cannot have max_runs greater than 1")

        schedule_id = str(inputs.get("schedule_id") or f"automation_{uuid4().hex[:12]}")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{3,96}", schedule_id):
            raise ValueError("schedule_id contains unsupported characters")
        name = str(inputs.get("name") or request[:80]).strip()
        return AutomationDefinition(
            id=schedule_id,
            request=request,
            trigger_type=trigger_type,
            delay_seconds=delay,
            interval_seconds=interval,
            cron_expression=cron,
            max_runs=max_runs,
            name=name,
        )

    @staticmethod
    def _validate_cron(expression: str) -> None:
        fields = expression.split()
        if len(fields) != 5 or any(not _CRON_FIELD.fullmatch(field) for field in fields):
            raise ValueError("cron_expression must contain five standard cron fields")
        for field, minimum, maximum in zip(fields, (0, 0, 1, 1, 0), (59, 23, 31, 12, 7)):
            for value in re.findall(r"\d+", field):
                if not minimum <= int(value) <= maximum:
                    raise ValueError(f"cron value {value} is outside the allowed range")

    @staticmethod
    def _summary(definition: AutomationDefinition) -> Dict[str, Any]:
        return definition.to_dict()

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message, "message": message}


__all__ = ["AutomationCapability", "AutomationDefinition"]
