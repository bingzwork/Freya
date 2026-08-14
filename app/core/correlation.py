"""Lightweight request and workflow correlation helpers for the canonical runtime."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional
from uuid import uuid4


_correlation_id: ContextVar[Optional[str]] = ContextVar("freya_correlation_id", default=None)


def new_correlation_id(prefix: str = "request") -> str:
    """Return a compact opaque identifier suitable for event metadata."""
    return f"{prefix}_{uuid4().hex}"


def get_correlation_id() -> Optional[str]:
    """Return the identifier active for the current synchronous execution path."""
    return _correlation_id.get()


@contextmanager
def correlation_scope(
    correlation_id: Optional[str] = None,
    *,
    prefix: str = "request",
) -> Iterator[str]:
    """Make one identifier available to nested event publishers.

    Callers may supply a previously propagated identifier.  When absent, a new
    opaque identifier is generated at the canonical conversation or workflow
    boundary.  The context is intentionally local to the caller; asynchronous
    owners retain the value in their existing context payloads.
    """
    active_id = correlation_id or get_correlation_id() or new_correlation_id(prefix)
    token = _correlation_id.set(active_id)
    try:
        yield active_id
    finally:
        _correlation_id.reset(token)


def with_correlation_metadata(metadata: Optional[dict] = None) -> dict:
    """Copy metadata and attach the active identifier when one exists."""
    result = dict(metadata or {})
    correlation_id = get_correlation_id()
    if correlation_id:
        result.setdefault("correlation_id", correlation_id)
    return result


__all__ = [
    "correlation_scope",
    "get_correlation_id",
    "new_correlation_id",
    "with_correlation_metadata",
]
