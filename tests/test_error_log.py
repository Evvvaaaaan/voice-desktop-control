import json
import sqlite3
import time

from metrics.error_log import ErrorLogStore, record_trace_failure


def test_error_log_groups_repeated_failures_and_keeps_safe_context(tmp_path):
    store = ErrorLogStore(str(tmp_path / "commands.db"))
    fields = {
        "error_type": "ConnectionError",
        "error": "connection refused",
        "provider": "ollama",
        "command": "send a private email",
        "transcript": "private transcript",
        "raw_response": "private LLM response",
        "params": {"body": "private email body"},
    }

    assert store.record_event("llm.request.failed", "trace-a", "2026-07-14T10:00:00+00:00", fields)
    assert store.record_event("llm.request.failed", "trace-b", "2026-07-14T10:01:00+00:00", fields)

    patterns = store.patterns()
    assert patterns == [{
        "fingerprint": "llm.request.connectionerror",
        "category": "LLM 연결/설정",
        "title": "LLM 요청에 실패했습니다",
        "recommendation": "LLM 제공자 설정, API 키, 로컬 서버 상태와 네트워크를 확인하세요.",
        "count": 2,
        "last_seen": "2026-07-14T10:01:00+00:00",
    }]

    recent = store.recent()
    assert [row["trace_id"] for row in recent] == ["trace-b", "trace-a"]
    context = json.loads(recent[0]["context_json"])
    assert context == {"error_type": "ConnectionError", "provider": "ollama"}
    assert recent[0]["message"] == "error_type=connectionerror"
    assert "private" not in recent[0]["message"]


def test_error_log_ignores_successful_trace_events(tmp_path):
    store = ErrorLogStore(str(tmp_path / "commands.db"))

    assert not store.record_event(
        "tool.dispatch.completed", "trace-a", fields={"action": "launch_app", "failed": False}
    )
    assert store.recent() == []
    assert store.patterns() == []


def test_error_log_drops_raw_error_text_and_bearer_tokens(tmp_path):
    store = ErrorLogStore(str(tmp_path / "commands.db"))
    secret = "Authorization: Bearer super-secret-token"

    assert store.record_event(
        "command.exception",
        "trace-a",
        fields={"error_type": "RuntimeError", "error": secret},
    )

    row = store.recent()[0]
    saved = row["message"] + row["context_json"]
    assert row["message"] == "error_type=runtimeerror"
    assert "super-secret-token" not in saved
    assert "Authorization" not in saved


def test_error_log_supports_in_memory_store():
    store = ErrorLogStore(":memory:")

    assert store.record_event(
        "command.aborted", "trace-a", fields={"reason": "empty_transcript"}
    )
    assert store.recent()[0]["fingerprint"] == "stt.empty_transcript"


def test_error_log_retains_only_the_most_recent_events(mocker, tmp_path):
    mocker.patch("metrics.error_log._MAX_EVENTS", 2)
    store = ErrorLogStore(str(tmp_path / "commands.db"))
    for index in range(3):
        store.record_event(
            "command.exception",
            f"trace-{index}",
            fields={"error_type": "RuntimeError"},
        )

    assert [row["trace_id"] for row in store.recent(10)] == ["trace-2", "trace-1"]


def test_error_log_returns_quickly_when_database_is_locked(monkeypatch, tmp_path, capsys):
    db_path = str(tmp_path / "commands.db")
    ErrorLogStore(db_path).record_event(
        "command.aborted", "seed", fields={"reason": "empty_transcript"}
    )
    lock = sqlite3.connect(db_path)
    lock.execute("BEGIN EXCLUSIVE")
    monkeypatch.setenv("VOICEDESK_DB", db_path)
    try:
        started = time.monotonic()
        saved = record_trace_failure({
            "event": "llm.request.failed",
            "trace_id": "trace-a",
            "error_type": "ConnectionError",
        })
        elapsed = time.monotonic() - started
    finally:
        lock.rollback()
        lock.close()

    assert not saved
    assert elapsed < 0.5
    assert "[VoiceDeskErrorLog] 저장 실패: OperationalError" in capsys.readouterr().err
