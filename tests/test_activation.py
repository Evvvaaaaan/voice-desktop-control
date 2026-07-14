import pytest
from unittest.mock import patch, MagicMock
from activation.hotkey import HotkeyListener
from activation.wake_word import (
    WakeWordListener,
    _resolve_targets,
    _phrase_matches,
)


def test_hotkey_listener_calls_callback(mocker):
    triggered = []
    listener = HotkeyListener("alt+space", lambda: triggered.append(True))
    mock_listener_cls = mocker.patch("activation.hotkey.kb.Listener")
    mock_listener_cls.return_value = MagicMock()
    listener.start()
    mock_listener_cls.assert_called_once()


def test_wake_word_listener_init():
    listener = WakeWordListener("hey desk", lambda: None)
    assert listener._phrase == "hey desk"


def test_resolve_targets_splits_model_and_stt_phrases():
    # "hey jarvis" has a pre-trained model; "hey desk" falls back to STT.
    models, stt = _resolve_targets(["hey desk", "hey jarvis"])
    assert models == ["hey_jarvis"]
    assert stt == ["hey desk"]


def test_resolve_targets_dedupes_and_ignores_blank():
    models, stt = _resolve_targets(["Hey Jarvis", "hey jarvis", ""])
    assert models == ["hey_jarvis"]
    assert stt == []


def test_hey_desk_alone_uses_stt_not_a_bogus_model():
    # Regression: "hey desk" must NOT be silently mapped to the hey_jarvis model.
    models, stt = _resolve_targets(["hey desk"])
    assert models == []
    assert stt == ["hey desk"]


def test_phrase_matches_is_loose_and_case_insensitive():
    assert _phrase_matches("okay Hey, Desk please", ["hey desk"]) is True
    assert _phrase_matches("hello there", ["hey desk"]) is False


def test_wake_word_listener_accepts_list_and_resolves_targets():
    listener = WakeWordListener(["hey desk", "hey jarvis"], lambda: None)
    assert listener._models == ["hey_jarvis"]
    assert listener._stt_phrases == ["hey desk"]


# ---------------------------------------------------------------------------
# Korean transliteration matching + refractory debounce
# ---------------------------------------------------------------------------

def test_phrase_matches_korean_transliteration():
    # ko-KR STT renders "hey desk" in Hangul — both spaced and tight forms.
    assert _phrase_matches("헤이 데스크 크롬 열어줘", ["hey desk"]) is True
    assert _phrase_matches("헤이데스크", ["hey desk"]) is True
    assert _phrase_matches("헤이 자비스", ["hey jarvis"]) is True
    assert _phrase_matches("안녕하세요", ["hey desk"]) is False


def test_fire_debounces_within_refractory_window():
    calls = []
    listener = WakeWordListener("hey desk", lambda: calls.append(1))
    assert listener._fire() is True
    assert listener._fire() is False     # immediate repeat suppressed
    assert calls == [1]


def test_fire_allows_after_refractory_window():
    calls = []
    listener = WakeWordListener("hey desk", lambda: calls.append(1))
    listener._fire()
    listener._last_fire -= 10.0          # simulate 10s passing
    assert listener._fire() is True
    assert calls == [1, 1]


# ---------------------------------------------------------------------------
# Hotkey edge-trigger (no repeat-fire while chord is held)
# ---------------------------------------------------------------------------

def _chord_listener():
    calls = []
    listener = HotkeyListener("alt+space", lambda: calls.append(1))
    listener._keys = listener._parse_binding()
    listener._pressed = set()
    listener._fired = False
    listener._listener = None            # _canonical falls back to identity
    return listener, calls


def test_hotkey_fires_once_per_chord_press():
    from pynput import keyboard as kb
    listener, calls = _chord_listener()
    listener._on_press(kb.Key.alt)
    listener._on_press(kb.Key.space)
    assert calls == [1]
    # macOS auto-repeat: space delivered again while chord held
    listener._on_press(kb.Key.space)
    listener._on_press(kb.Key.space)
    assert calls == [1]


def test_hotkey_refires_after_release():
    from pynput import keyboard as kb
    listener, calls = _chord_listener()
    listener._on_press(kb.Key.alt)
    listener._on_press(kb.Key.space)
    listener._on_release(kb.Key.space)
    listener._on_press(kb.Key.space)
    assert calls == [1, 1]


# ---------------------------------------------------------------------------
# Wake stream pause/resume and starvation watchdog
# ---------------------------------------------------------------------------

def test_pause_sets_flag_and_returns_when_no_stream_open():
    listener = WakeWordListener("hey desk", lambda: None)
    listener.pause(timeout=0.2)     # no stream open → returns immediately
    assert listener._pause_requested.is_set()
    listener.resume()
    assert not listener._pause_requested.is_set()


def test_stop_pauses_stream_and_joins_listener_thread():
    class FakeThread:
        def __init__(self):
            self.join_timeout = None
            self._alive = True

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self.join_timeout = timeout
            self._alive = False

    listener = WakeWordListener("hey desk", lambda: None)
    thread = FakeThread()
    listener._thread = thread
    listener._stream_closed.set()

    listener.stop(timeout=0.2)

    assert listener._running is False
    assert listener._pause_requested.is_set()
    assert thread.join_timeout == 0.2
    assert listener._thread is None


def test_module_helpers_control_active_listener():
    from activation.wake_word import (
        set_active_listener, pause_listening, resume_listening,
    )
    m = MagicMock()
    set_active_listener(m)
    try:
        pause_listening()
        m.pause.assert_called_once()
        resume_listening()
        m.resume.assert_called_once()
    finally:
        set_active_listener(None)
    pause_listening()   # no active listener → must be a silent no-op
    resume_listening()


class _FakeInputStream:
    """Context-manager stub whose callback is never invoked → no frames."""
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_sounddevice(monkeypatch):
    import sys
    import types
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _FakeInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)


def test_stream_session_returns_when_stream_starves(monkeypatch):
    """A stream that stops delivering frames must end the session (so the
    listener reopens it) instead of blocking forever."""
    import time
    import activation.wake_word as ww
    _fake_sounddevice(monkeypatch)
    monkeypatch.setattr(ww, "_STARVATION_TIMEOUT_SEC", 0.05)

    listener = WakeWordListener("hey desk", lambda: None)
    listener._running = True
    start = time.monotonic()
    listener._stream_session(None)      # no frames ever arrive
    assert time.monotonic() - start < 1.0
    assert listener._stream_closed.is_set()


def test_stream_session_exits_promptly_on_pause(monkeypatch):
    import activation.wake_word as ww
    _fake_sounddevice(monkeypatch)
    monkeypatch.setattr(ww, "_STARVATION_TIMEOUT_SEC", 5.0)

    listener = WakeWordListener("hey desk", lambda: None)
    listener._running = True
    listener._pause_requested.set()
    listener._stream_session(None)      # must not wait out the 5s timeout
    assert listener._stream_closed.is_set()
