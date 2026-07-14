import json
from unittest.mock import MagicMock

from agent.core import Agent
from diagnostics import command_trace, trace
from metrics.error_log import ErrorLogStore


def _trace_events(stderr: str) -> list[dict]:
    prefix = "[VoiceDeskTrace] "
    return [json.loads(line[len(prefix):]) for line in stderr.splitlines()
            if line.startswith(prefix)]


def test_voice_trace_correlates_capture_transcription_and_result(mocker, capsys, tmp_path):
    mocker.patch.dict("os.environ", {
        "VOICEDESK_TRACE": "1", "VOICEDESK_DB": str(tmp_path / "events.db"),
    })
    mocker.patch("main.record_audio", return_value=b"wav")
    mocker.patch("main.pause_listening")
    mocker.patch("main.resume_listening")
    mocker.patch("time.sleep")
    from main import _record_command

    hud = MagicMock()
    stt = MagicMock()
    stt.transcribe.return_value = "메일을 작성해줘"
    agent = MagicMock()
    agent.run.return_value = "수신자와 제목을 알려주세요."

    _record_command(agent, hud, stt)

    events = _trace_events(capsys.readouterr().err)
    names = [event["event"] for event in events]
    assert names == [
        "command.started",
        "audio.capture.started",
        "audio.capture.completed",
        "stt.transcription.started",
        "stt.transcription.completed",
        "agent.route",
        "command.result",
        "command.finished",
    ]
    assert events[4]["transcript"] == "메일을 작성해줘"
    assert events[5]["route"] == "react"
    assert len({event["trace_id"] for event in events}) == 1


def test_agent_trace_records_model_decision_and_tool_result(mocker, capsys, tmp_path):
    mocker.patch.dict("os.environ", {
        "VOICEDESK_TRACE": "1", "VOICEDESK_DB": str(tmp_path / "events.db"),
    })
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.complete.return_value = (
        '{"action":"speak_only","params":{},"done":true,'
        '"response":"수신자와 제목을 알려주세요."}'
    )
    guard = MagicMock()
    guard.check.return_value = True
    guard.is_dangerous.return_value = False
    detector = MagicMock()
    detector.record.return_value = False
    agent = Agent(mock_llm, guard, MagicMock(), detector, MagicMock(voice="Yuna", rate=200))
    mocker.patch("agent.core.speak")

    with command_trace("test"):
        result = agent.run("메일을 작성해줘")

    events = _trace_events(capsys.readouterr().err)
    by_name = {event["event"]: event for event in events}
    assert result == "수신자와 제목을 알려주세요."
    assert by_name["agent.decision"]["action"] == "speak_only"
    assert by_name["tool.dispatch.completed"]["dispatch_result"] == ""
    assert by_name["agent.run.completed"]["success"] is True
    assert len({event["trace_id"] for event in events}) == 1


def test_trace_saves_failure_when_console_trace_is_disabled(mocker, capsys, tmp_path):
    db_path = str(tmp_path / "events.db")
    mocker.patch.dict("os.environ", {
        "VOICEDESK_TRACE": "0", "VOICEDESK_DB": db_path,
    })

    trace(
        "llm.request.failed",
        error_type="ConnectionError",
        error="local model is unavailable",
        command="private voice command",
        raw_response="private model response",
    )

    assert _trace_events(capsys.readouterr().err) == []
    rows = ErrorLogStore(db_path).recent()
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "llm.request.connectionerror"
    assert "private voice command" not in rows[0]["context_json"]
    assert "private model response" not in rows[0]["context_json"]


def test_empty_voice_transcript_is_saved_as_an_stt_pattern(mocker, tmp_path):
    db_path = str(tmp_path / "events.db")
    mocker.patch.dict("os.environ", {
        "VOICEDESK_TRACE": "0", "VOICEDESK_DB": db_path,
    })
    mocker.patch("main.record_audio", return_value=b"wav")
    mocker.patch("main.pause_listening")
    mocker.patch("main.resume_listening")
    mocker.patch("time.sleep")
    from main import _record_command

    hud = MagicMock()
    stt = MagicMock()
    stt.transcribe.return_value = ""

    _record_command(MagicMock(), hud, stt)

    patterns = ErrorLogStore(db_path).patterns()
    assert patterns[0]["fingerprint"] == "stt.empty_transcript"
    assert patterns[0]["count"] == 1
