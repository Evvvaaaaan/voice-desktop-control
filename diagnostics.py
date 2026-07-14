"""Compact, correlated console diagnostics for a single VoiceDesk request."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator

from metrics.error_log import record_trace_failure


_TRACE_ID: ContextVar[str | None] = ContextVar("voicedesk_trace_id", default=None)
_TRACE_STARTED: ContextVar[float | None] = ContextVar("voicedesk_trace_started", default=None)
_VALUE_LIMIT = 600


def _trace_enabled() -> bool:
    return os.environ.get("VOICEDESK_TRACE", "1").strip().lower() not in {"0", "false", "off"}


def _safe_value(value):
    """Keep one JSON-line event readable even when a model returns large text."""
    if isinstance(value, str):
        return value if len(value) <= _VALUE_LIMIT else value[:_VALUE_LIMIT] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return _safe_value(str(value))


def trace(event: str, /, **fields) -> None:
    """Emit a machine-readable line that can be grouped by ``trace_id``."""
    started = _TRACE_STARTED.get()
    payload = {
        "event": event,
        "trace_id": _TRACE_ID.get() or "standalone",
        "thread": threading.current_thread().name,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    if started is not None:
        payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    payload.update({key: _safe_value(value) for key, value in fields.items()})
    # Error retention is intentionally independent of console tracing.  A
    # user can silence JSON lines without losing the failures needed by the
    # Settings > Errors page.  The store itself drops user commands, STT text,
    # raw LLM output, and action parameters before writing to disk.
    record_trace_failure(payload)
    if not _trace_enabled():
        return
    print("[VoiceDeskTrace] " + json.dumps(payload, ensure_ascii=False, sort_keys=True),
          file=sys.stderr, flush=True)


@contextmanager
def command_trace(source: str, /, **fields) -> Iterator[str]:
    """Scope all events from one captured command under a fresh trace ID."""
    trace_id = uuid.uuid4().hex[:10]
    started = time.monotonic()
    id_token = _TRACE_ID.set(trace_id)
    started_token = _TRACE_STARTED.set(started)
    trace("command.started", source=source, **fields)
    try:
        yield trace_id
    except BaseException as exc:
        trace("command.exception", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        trace("command.finished", duration_ms=int((time.monotonic() - started) * 1000))
        _TRACE_STARTED.reset(started_token)
        _TRACE_ID.reset(id_token)
