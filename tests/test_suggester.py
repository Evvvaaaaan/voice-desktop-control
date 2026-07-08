from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from config.loader import SuggestionConfig
from memory.store import MemoryStore
from memory.suggester import SuggestionEngine, _parse_answer


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def store(db_path):
    return MemoryStore(db_path)


# Today's date so day-based checks (declined-today) match rows the store
# writes with wall-clock timestamps; fixed 9:30 for hour matching.
NOW = datetime.now().astimezone().replace(hour=9, minute=30, second=0,
                                          microsecond=0)


def _set_last_suggestion_ts(store, dt):
    with store._conn() as conn:
        conn.execute("UPDATE suggestion_log SET timestamp=?",
                     (dt.astimezone(timezone.utc).isoformat(),))


def _seed_pattern(store, command="크롬 열어줘", hour=9, days=4):
    store.set_patterns({"hourly_commands": {str(hour): [[command, days]]}})


def _make_engine(store, listen="네", config=None, begin=True):
    engine = SuggestionEngine(
        store,
        config or SuggestionConfig(),
        speak_fn=MagicMock(),
        run_command_fn=MagicMock(),
        begin_session=MagicMock(return_value=begin),
        end_session=MagicMock(),
        listen_fn=MagicMock(return_value=listen),
        hud=MagicMock(),
    )
    return engine


def test_tick_no_patterns_noop(store):
    engine = _make_engine(store)
    assert engine.tick(NOW) is False
    engine._speak.assert_not_called()


def test_tick_wrong_hour_noop(store):
    _seed_pattern(store, hour=14)
    engine = _make_engine(store)
    assert engine.tick(NOW) is False


def test_tick_below_min_days_noop(store):
    _seed_pattern(store, days=2)
    engine = _make_engine(store)  # min_pattern_days=3
    assert engine.tick(NOW) is False


def test_accept_runs_command_and_logs(store):
    _seed_pattern(store)
    engine = _make_engine(store, listen="네")

    assert engine.tick(NOW) is True

    spoken = [c.args[0] for c in engine._speak.call_args_list]
    assert any("크롬 열어줘" in s and "할까요" in s for s in spoken)
    assert "네, 바로 할게요." in spoken
    engine._run_command.assert_called_once_with("크롬 열어줘")
    engine._begin_session.assert_called_once()
    engine._end_session.assert_called_once()
    with store._conn() as conn:
        rows = conn.execute("SELECT suggestion_key, hour, outcome FROM suggestion_log").fetchall()
    assert rows == [("크롬 열어줘", 9, "accepted")]


def test_decline_suppressed_rest_of_day_across_restart(store, db_path):
    _seed_pattern(store)
    engine = _make_engine(store, listen="아니")
    assert engine.tick(NOW) is True
    engine._run_command.assert_not_called()
    spoken = [c.args[0] for c in engine._speak.call_args_list]
    assert any("다시 제안하지 않을게요" in s for s in spoken)

    # New engine over the same DB (restart), later hour but pattern re-seeded
    # for that hour, same day → suppressed even without the cooldown.
    store2 = MemoryStore(db_path)
    _seed_pattern(store2, hour=13)
    later = NOW.replace(hour=13)
    engine2 = _make_engine(store2, listen="네",
                           config=SuggestionConfig(cooldown_min=0))
    assert engine2.tick(later) is False

    # Next day the command is eligible again.
    next_day = NOW + timedelta(days=1)
    _seed_pattern(store2, hour=9)
    assert engine2.tick(next_day) is True


def test_global_cooldown_one_per_hour(store):
    _seed_pattern(store, command="크롬 열어줘", hour=9)
    engine = _make_engine(store, listen="네")
    assert engine.tick(NOW) is True
    _set_last_suggestion_ts(store, NOW)

    # A DIFFERENT qualifying command 30 minutes later is still blocked.
    store.set_patterns({"hourly_commands": {"10": [["메일 확인해줘", 5]]}})
    assert engine.tick(NOW.replace(hour=10, minute=0)) is False
    # 61+ minutes later it goes through.
    assert engine.tick(NOW.replace(hour=10, minute=35)) is True


def test_timeout_silent_but_burns_cooldown(store):
    _seed_pattern(store)
    engine = _make_engine(store, listen="")

    assert engine.tick(NOW) is True

    spoken = [c.args[0] for c in engine._speak.call_args_list]
    assert len(spoken) == 1  # only the suggestion itself — no ack on silence
    engine._run_command.assert_not_called()
    with store._conn() as conn:
        outcome = conn.execute("SELECT outcome FROM suggestion_log").fetchone()[0]
    assert outcome == "timeout"
    # HUD returned to idle
    states = [c.args[0] for c in engine._hud.set_state.call_args_list]
    assert states[-1] == "idle"
    # cooldown burned
    _set_last_suggestion_ts(store, NOW)
    _seed_pattern(store, command="메일 확인해줘")
    assert engine.tick(NOW.replace(minute=45)) is False


def test_busy_session_skips_without_logging(store):
    _seed_pattern(store)
    engine = _make_engine(store, begin=False)

    assert engine.tick(NOW) is False

    engine._speak.assert_not_called()
    engine._end_session.assert_not_called()
    with store._conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM suggestion_log").fetchone()[0]
    assert count == 0  # cooldown not burned — candidate stays eligible


def test_recently_run_command_not_suggested(store):
    _seed_pattern(store)
    store.log_command("크롬 열어줘", True, 100)
    with store._conn() as conn:  # executed 10 min before NOW
        conn.execute("UPDATE behavior_log SET timestamp=?",
                     ((NOW - timedelta(minutes=10))
                      .astimezone(timezone.utc).isoformat(),))
    engine = _make_engine(store)
    assert engine.tick(NOW) is False


def test_disabled_noop(store):
    _seed_pattern(store)
    engine = _make_engine(store, config=SuggestionConfig(enabled=False))
    assert engine.tick(NOW) is False


def test_listen_failure_counts_as_timeout(store):
    _seed_pattern(store)
    engine = _make_engine(store)
    engine._listen = MagicMock(side_effect=RuntimeError("mic busy"))

    assert engine.tick(NOW) is True

    engine._run_command.assert_not_called()
    with store._conn() as conn:
        outcome = conn.execute("SELECT outcome FROM suggestion_log").fetchone()[0]
    assert outcome == "timeout"


def test_delivery_crash_burns_cooldown_and_resets_hud(store):
    """The 'ANY outcome burns the hourly budget' invariant must hold even when
    delivery itself crashes (a broken speak_fn once did) — otherwise the same
    suggestion re-fires every tick and the HUD stays stuck on the prompt."""
    _seed_pattern(store)
    engine = _make_engine(store)
    engine._speak = MagicMock(side_effect=TypeError("stale kwarg"))

    with pytest.raises(TypeError):
        engine.tick(NOW)

    engine._end_session.assert_called_once()
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT suggestion_key, outcome FROM suggestion_log").fetchall()
    assert rows == [("크롬 열어줘", "error")]
    states = [c.args[0] for c in engine._hud.set_state.call_args_list]
    assert states[-1] == "idle"
    transcripts = [c.args[0] for c in engine._hud.set_transcript.call_args_list]
    assert transcripts[-1] == ""

    # The crashed attempt burned the cooldown: no re-nag on the next tick.
    _set_last_suggestion_ts(store, NOW)
    engine._speak = MagicMock()
    assert engine.tick(NOW.replace(minute=45)) is False


@pytest.mark.parametrize("text,expected", [
    ("네", True),
    ("네, 해줘", True),
    ("응", True),
    ("어", True),
    ("좋아", True),
    ("그래 해줘", True),
    ("네네", True),
    ("아니", False),
    ("아니요, 됐네요", False),
    ("나중에 할게", False),
    ("하지 마", False),
    ("안돼", False),
    ("안 돼요", False),
    ("괜찮아요", False),
    ("싫은데", False),
    ("", None),
    ("글쎄", None),
    ("오늘 날씨 어때", None),
    # '네'/'어' as syllables inside unrelated speech must not read as a yes.
    ("네이버 켜줘", None),
    ("어 잠깐만", None),
])
def test_parse_answer(text, expected):
    assert _parse_answer(text) is expected
