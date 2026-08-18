"""Canonical per-request context shared by conversation and execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    """Immutable identity and provenance for one user or autonomous request."""

    trace_id: str
    session_id: str
    original_message: str
    attachments: tuple[str, ...] = ()
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "conversation"
    channel: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        original_message: str,
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        attachments: Optional[Iterable[str]] = None,
        source: str = "conversation",
        channel: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "RequestContext":
        return cls(
            trace_id=trace_id or f"request_{uuid4().hex}",
            session_id=session_id or f"session_{uuid4().hex}",
            original_message=str(original_message or ""),
            attachments=tuple(str(item) for item in (attachments or ())),
            source=str(source or "conversation"),
            channel=str(channel or "unknown"),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_mapping(cls, value: Optional[Dict[str, Any]], *, original_message: str = "") -> "RequestContext":
        data = dict(value or {})
        return cls(
            trace_id=str(data.get("trace_id") or data.get("correlation_id") or f"request_{uuid4().hex}"),
            session_id=str(data.get("session_id") or f"session_{uuid4().hex}"),
            original_message=str(data.get("original_message") or data.get("original_request") or original_message or ""),
            attachments=tuple(str(item) for item in (data.get("attachments") or data.get("attachment_paths") or ())),
            timestamp=str(data.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            source=str(data.get("source") or "conversation"),
            channel=str(data.get("channel") or "unknown"),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe mapping for existing router and event contracts."""
        return {
            "trace_id": self.trace_id,
            "correlation_id": self.trace_id,
            "request_id": self.trace_id,
            "session_id": self.session_id,
            "original_message": self.original_message,
            "original_request": self.original_message,
            "attachments": list(self.attachments),
            "timestamp": self.timestamp,
            "source": self.source,
            "channel": self.channel,
            "metadata": dict(self.metadata),
        }


__all__ = ["RequestContext"]
