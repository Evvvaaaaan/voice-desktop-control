"""Persistent, privacy-conscious error events and recurring-pattern summaries."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS error_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    event TEXT NOT NULL,
    category TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT NOT NULL
)
"""

_CREATE_FINGERPRINT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_error_events_fingerprint
ON error_events (fingerprint, timestamp)
"""

_MAX_EVENTS = 500
_SAFE_CONTEXT_KEYS = (
    "action", "reason", "error_type", "provider", "iteration",
    "json_retries", "max_iterations", "duration_ms",
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[ _-]?key|token|password|authorization)\s*[=:]\s*"
    r"(?:bearer\s+)?[^\s,;]+"
)
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]+")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_WRITE_LOCK = threading.Lock()
_SCHEMA_LOCK = threading.Lock()
_READY_SCHEMA_PATHS: set[str] = set()
_DB_TIMEOUT_SECONDS = 0.05


def _short_text(value, limit: int = 280) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    text = _SECRET_VALUE_RE.sub(r"\1=***", text)
    text = _BEARER_TOKEN_RE.sub("Bearer ***", text)
    text = _OPENAI_KEY_RE.sub("sk-***", text)
    return text if len(text) <= limit else text[:limit] + "…"


def _fingerprint_part(value, fallback: str = "unknown") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return text[:48] or fallback


def _analysis_for(event: str, fields: dict) -> dict | None:
    """Return a stable, user-actionable category for real failures only."""
    error_type = _fingerprint_part(fields.get("error_type"), "runtime")
    action = _fingerprint_part(fields.get("action"), "unknown")

    if event == "command.aborted" and fields.get("reason") == "empty_transcript":
        return {
            "category": "음성 인식",
            "fingerprint": "stt.empty_transcript",
            "title": "음성 명령을 인식하지 못했습니다",
            "recommendation": "마이크 권한, 입력 레벨, 무음 종료 시간, STT 공급자를 확인하세요.",
            "message": "empty_transcript",
        }
    if event == "llm.request.failed":
        return {
            "category": "LLM 연결/설정",
            "fingerprint": f"llm.request.{error_type}",
            "title": "LLM 요청에 실패했습니다",
            "recommendation": "LLM 제공자 설정, API 키, 로컬 서버 상태와 네트워크를 확인하세요.",
            "message": f"error_type={error_type}",
        }
    if event == "llm.response.invalid_json":
        return {
            "category": "LLM 응답 형식",
            "fingerprint": "llm.invalid_json",
            "title": "LLM이 필요한 JSON 형식으로 응답하지 않았습니다",
            "recommendation": "모델을 변경하거나 ReAct 프롬프트와 JSON 재시도 정책을 검토하세요.",
            "message": "invalid_json",
        }
    if event in {
        "tool.dispatch.completed", "agent.fast_path.completed", "agent.cache.completed",
    } and fields.get("failed"):
        return {
            "category": "도구 실행",
            "fingerprint": f"tool.{action}",
            "title": f"{action} 동작 실행에 실패했습니다",
            "recommendation": "손쉬운 사용·화면 기록 권한, 대상 앱 상태, 동작 인자를 확인하세요.",
            "message": f"action={action}",
        }
    if event == "agent.cache.blocked":
        return {
            "category": "도구 실행",
            "fingerprint": f"cache.{action}.{_fingerprint_part(fields.get('reason'))}",
            "title": "캐시된 명령을 안전하게 실행할 수 없습니다",
            "recommendation": "저장된 명령을 다시 실행해 새 캐시를 만들고, 대상 앱 이름을 확인하세요.",
            "message": _short_text(fields.get("reason")),
        }
    if event == "agent.run.exhausted":
        return {
            "category": "명령 계획",
            "fingerprint": "agent.exhausted",
            "title": "명령을 제한 횟수 안에 완료하지 못했습니다",
            "recommendation": "명령을 더 구체적으로 말하고, 반복되는 경우 계획·도구 선택 로직을 검토하세요.",
            "message": "max_iterations=" + _short_text(fields.get("max_iterations"), 20),
        }
    if event == "memory.retrieval.failed":
        return {
            "category": "메모리",
            "fingerprint": f"memory.retrieval.{error_type}",
            "title": "메모리 조회에 실패했습니다",
            "recommendation": "명령은 계속 실행되지만, 메모리 데이터베이스와 임베딩 설정을 확인하세요.",
            "message": f"error_type={error_type}",
        }
    if event == "command.exception":
        return {
            "category": "실행 오류",
            "fingerprint": f"runtime.{error_type}",
            "title": "처리 중 예상하지 못한 오류가 발생했습니다",
            "recommendation": "trace ID로 콘솔 로그를 찾아 재현한 뒤 해당 예외를 처리하세요.",
            "message": f"error_type={error_type}",
        }
    return None


class ErrorLogStore:
    """SQLite-backed error log. Writes are serialized and never shared by connection."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._memory_connection = None
        if db_path == ":memory:":
            self._memory_connection = sqlite3.connect(
                db_path, timeout=_DB_TIMEOUT_SECONDS, check_same_thread=False
            )
            self._memory_schema_ready = False
        else:
            self._schema_key = os.path.abspath(db_path)

    def _conn(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        return sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT_SECONDS)

    def _ensure_schema(self) -> None:
        if self._memory_connection is not None:
            if self._memory_schema_ready:
                return
            with self._conn() as conn:
                conn.execute(_CREATE_TABLE)
                conn.execute(_CREATE_FINGERPRINT_INDEX)
            self._memory_schema_ready = True
            return
        with _SCHEMA_LOCK:
            if self._schema_key in _READY_SCHEMA_PATHS:
                return
            if self._memory_connection is None:
                parent = os.path.dirname(os.path.abspath(self._db_path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
            with self._conn() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(_CREATE_TABLE)
                conn.execute(_CREATE_FINGERPRINT_INDEX)
            _READY_SCHEMA_PATHS.add(self._schema_key)

    def _exists(self) -> bool:
        return self._memory_connection is not None or os.path.exists(self._db_path)

    def record_event(
        self,
        event: str,
        trace_id: str,
        timestamp: str | None = None,
        fields: dict | None = None,
    ) -> bool:
        fields = fields or {}
        analysis = _analysis_for(event, fields)
        if analysis is None:
            return False
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        context = {
            key: _short_text(fields[key], 120)
            for key in _SAFE_CONTEXT_KEYS if fields.get(key) is not None
        }
        with _WRITE_LOCK:
            self._ensure_schema()
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO error_events
                    (timestamp, trace_id, event, category, fingerprint, title,
                     recommendation, message, context_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        timestamp, trace_id, event, analysis["category"],
                        analysis["fingerprint"], analysis["title"],
                        analysis["recommendation"], analysis["message"],
                        json.dumps(context, ensure_ascii=False, sort_keys=True),
                    ),
                )
                conn.execute(
                    """DELETE FROM error_events
                    WHERE id NOT IN (
                        SELECT id FROM error_events ORDER BY id DESC LIMIT ?
                    )""",
                    (_MAX_EVENTS,),
                )
        return True

    def recent(self, limit: int = 5) -> list[dict]:
        if limit <= 0 or not self._exists():
            return []
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT timestamp, trace_id, event, category, fingerprint,
                              title, recommendation, message, context_json
                       FROM error_events ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [dict(row) for row in rows]

    def patterns(self, limit: int = 5) -> list[dict]:
        if limit <= 0 or not self._exists():
            return []
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT fingerprint, category, title, recommendation,
                              COUNT(*) AS count, MAX(timestamp) AS last_seen
                       FROM error_events
                       GROUP BY fingerprint, category, title, recommendation
                       ORDER BY count DESC, last_seen DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [dict(row) for row in rows]


def record_trace_failure(payload: dict) -> bool:
    """Persist a trace failure only when the running app supplied its DB path.

    The command loop must never fail because diagnostics storage is unavailable.
    """
    db_path = os.environ.get("VOICEDESK_DB")
    if not db_path:
        return False
    try:
        return ErrorLogStore(db_path).record_event(
            payload.get("event", ""), payload.get("trace_id", "standalone"),
            payload.get("timestamp"), payload,
        )
    except Exception as exc:
        print(f"[VoiceDeskErrorLog] 저장 실패: {type(exc).__name__}", file=sys.stderr)
        return False
