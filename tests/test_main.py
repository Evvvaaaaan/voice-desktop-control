"""
Tests for main.py — record_audio, VoiceDeskMenuBar, and orchestrator wiring.

rumps and sounddevice are mocked throughout so no microphone or macOS
menu bar is required.
"""
import io
import sys
import types
import wave
import pytest
import numpy as np
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rumps_mock():
    """Minimal rumps stub: App base class, MenuItem, clicked decorator."""
    mod = types.ModuleType("rumps")

    class FakeApp:
        def __init__(self, name, icon=None, quit_button=None):
            self.name = name
            self.title = name
            self.menu = []

        def run(self):  # pragma: no cover
            pass

    class FakeMenuItem:
        def __init__(self, title, callback=None):
            self.title = title
            self.callback = callback

    def clicked(title):
        def decorator(fn):
            return fn
        return decorator

    mod.App = FakeApp
    mod.MenuItem = FakeMenuItem
    mod.clicked = clicked
    return mod


@pytest.fixture
def rumps_mock():
    """Inject a fake rumps into sys.modules for a test."""
    mod = _make_rumps_mock()
    old = sys.modules.get("rumps")
    sys.modules["rumps"] = mod
    # Force reimport of menubar with the fake rumps
    sys.modules.pop("ui.menubar", None)
    yield mod
    sys.modules.pop("ui.menubar", None)
    if old is None:
        sys.modules.pop("rumps", None)
    else:
        sys.modules["rumps"] = old


# ---------------------------------------------------------------------------
# record_audio
# ---------------------------------------------------------------------------

class TestRecordAudio:
    def test_returns_bytes(self, mocker):
        fake_audio = np.zeros((16000, 1), dtype="int16")
        mocker.patch("sounddevice.rec", return_value=fake_audio)
        mocker.patch("sounddevice.wait")
        from main import record_audio
        result = record_audio(duration=1, sample_rate=16000)
        assert isinstance(result, bytes)

    def test_wav_magic_bytes(self, mocker):
        fake_audio = np.zeros((16000, 1), dtype="int16")
        mocker.patch("sounddevice.rec", return_value=fake_audio)
        mocker.patch("sounddevice.wait")
        from main import record_audio
        result = record_audio(duration=1, sample_rate=16000)
        assert result[:4] == b"RIFF"
        assert result[8:12] == b"WAVE"

    def test_wav_params_match_expected(self, mocker):
        """WAV must be 16kHz, mono, int16."""
        sample_rate = 16000
        fake_audio = np.zeros((sample_rate * 2, 1), dtype="int16")
        mocker.patch("sounddevice.rec", return_value=fake_audio)
        mocker.patch("sounddevice.wait")
        from main import record_audio
        result = record_audio(duration=2, sample_rate=sample_rate)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2   # int16
            assert wf.getframerate() == sample_rate

    def test_rec_called_with_correct_frame_count(self, mocker):
        duration, sample_rate = 3, 16000
        fake_audio = np.zeros((duration * sample_rate, 1), dtype="int16")
        mock_rec = mocker.patch("sounddevice.rec", return_value=fake_audio)
        mocker.patch("sounddevice.wait")
        from main import record_audio
        record_audio(duration=duration, sample_rate=sample_rate)
        mock_rec.assert_called_once_with(
            duration * sample_rate,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )

    def test_wait_is_called(self, mocker):
        fake_audio = np.zeros((16000, 1), dtype="int16")
        mocker.patch("sounddevice.rec", return_value=fake_audio)
        mock_wait = mocker.patch("sounddevice.wait")
        from main import record_audio
        record_audio(duration=1, sample_rate=16000)
        mock_wait.assert_called_once()

class TestRecordAudioStreaming:
    def test_on_level_called_and_returns_wav(self, mocker):
        captured = {}
        levels = []

        class FakeStream:
            def __init__(self, **kw):
                captured.update(kw)

            def __enter__(self):
                block = (np.ones((1600, 1), dtype="int16") * 3000)
                captured["callback"](block, 1600, None, None)
                return self

            def __exit__(self, *a):
                return False

        mocker.patch("sounddevice.InputStream", FakeStream)
        mocker.patch("sounddevice.sleep")
        from main import record_audio
        result = record_audio(duration=1, sample_rate=16000, on_level=levels.append)

        assert result[:4] == b"RIFF" and result[8:12] == b"WAVE"
        assert len(levels) == 1
        assert levels[0] == pytest.approx(1.0)   # loud block → clamped to 1.0

    def test_default_path_unchanged_without_on_level(self, mocker):
        fake_audio = np.zeros((16000, 1), dtype="int16")
        mock_rec = mocker.patch("sounddevice.rec", return_value=fake_audio)
        mocker.patch("sounddevice.wait")
        mock_stream = mocker.patch("sounddevice.InputStream")
        from main import record_audio
        record_audio(duration=1, sample_rate=16000)
        mock_rec.assert_called_once()
        mock_stream.assert_not_called()   # no streaming when on_level is None


class TestProviderInfo:
    def test_selects_model_and_voice_for_active_providers(self):
        from main import _provider_info
        from config.loader import Config
        cfg = Config()
        cfg.llm.provider = "claude"
        cfg.llm.claude_model = "claude-sonnet-4-6"
        cfg.tts.provider = "nvidia"
        cfg.tts.nvidia_voice = "Chatterbox-Multilingual.ko-KR.Male"
        assert _provider_info(cfg) == (
            "macos", "claude", "claude-sonnet-4-6",
            "nvidia", "Chatterbox-Multilingual.ko-KR.Male",
        )

    def test_ollama_and_macos_defaults(self):
        from main import _provider_info
        from config.loader import Config
        cfg = Config()
        assert _provider_info(cfg) == ("macos", "ollama", "llama3", "macos", "Yuna")


def test_record_command_passes_mic_level_callback(mocker):
    rec = mocker.patch("main.record_audio", return_value=b"wav")
    hud = MagicMock()
    stt = MagicMock()
    stt.transcribe.return_value = ""   # short-circuit after processing
    from main import _record_command
    _record_command(MagicMock(), hud, stt)
    assert rec.call_args.kwargs.get("on_level") == hud.update_mic_level


# ---------------------------------------------------------------------------
# VoiceDeskMenuBar
# ---------------------------------------------------------------------------

class TestVoiceDeskMenuBar:
    def test_init_sets_active_false(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        bar = VoiceDeskMenuBar(MagicMock(), MagicMock(), MagicMock())
        assert bar._active is False

    def test_toggle_flips_active(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        hud = MagicMock()
        bar = VoiceDeskMenuBar(MagicMock(), hud, MagicMock())
        bar._toggle(None)
        assert bar._active is True
        bar._toggle(None)
        assert bar._active is False

    def test_toggle_sets_hud_listening(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        hud = MagicMock()
        bar = VoiceDeskMenuBar(MagicMock(), hud, MagicMock())
        bar._toggle(None)
        hud.set_state.assert_called_with("listening")

    def test_toggle_sets_hud_idle_on_deactivate(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        hud = MagicMock()
        bar = VoiceDeskMenuBar(MagicMock(), hud, MagicMock())
        bar._toggle(None)   # activate
        bar._toggle(None)   # deactivate
        hud.set_state.assert_called_with("idle")

    def test_toggle_changes_title(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        bar = VoiceDeskMenuBar(MagicMock(), MagicMock(), MagicMock())
        bar._toggle(None)
        assert bar.title == "🎤"
        bar._toggle(None)
        assert bar.title == "VoiceDesk"

    def test_open_settings_calls_show(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        settings = MagicMock()
        bar = VoiceDeskMenuBar(MagicMock(), MagicMock(), settings)
        bar._open_settings(None)
        settings.show.assert_called_once()

    def test_menu_items_created(self, rumps_mock):
        from ui.menubar import VoiceDeskMenuBar
        bar = VoiceDeskMenuBar(MagicMock(), MagicMock(), MagicMock())
        # menu list contains two non-None items and a separator (None)
        non_none = [item for item in bar.menu if item is not None]
        assert len(non_none) == 2


# ---------------------------------------------------------------------------
# record_command (thread target)
# ---------------------------------------------------------------------------

class TestRecordCommand:
    def test_idle_on_empty_transcript(self, mocker):
        """If STT returns empty string, hud should go back to idle."""
        mocker.patch("main.record_audio", return_value=b"wav_bytes")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "   "
        _record_command(MagicMock(), hud, stt)
        hud.set_state.assert_called_with("idle")

    def test_success_state_on_non_cancel(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav_bytes")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "open browser"
        agent = MagicMock()
        agent.run.return_value = "Done"
        _record_command(agent, hud, stt)
        hud.set_state.assert_any_call("success")

    def test_error_state_on_cancel(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav_bytes")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "delete everything"
        agent = MagicMock()
        agent.run.return_value = "취소됨"
        _record_command(agent, hud, stt)
        hud.set_state.assert_any_call("error")

    def test_hud_state_sequence(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav_bytes")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "open Finder"
        agent = MagicMock()
        agent.run.return_value = "Done"
        _record_command(agent, hud, stt)
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert states[0] == "listening"
        assert states[1] == "processing"
        assert states[2] == "executing"
        assert states[3] == "success"
        assert states[4] == "idle"

    def test_real_agent_fast_path_runs_before_llm_path(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav_bytes")
        mocker.patch("time.sleep")
        from main import _record_command
        from agent.core import Agent

        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "크롬 열어줘"
        agent = Agent(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        agent.try_fast_path = MagicMock(return_value="완료")
        agent.run = MagicMock()

        _record_command(agent, hud, stt)

        agent.try_fast_path.assert_called_once_with("크롬 열어줘")
        agent.run.assert_not_called()
        hud.set_state.assert_any_call("success")


# ---------------------------------------------------------------------------
# Orchestrator — main() wiring
# ---------------------------------------------------------------------------

class TestOrchestratorWiring:
    """
    Verify that main() initialises every component with the correct arguments
    and that on_config_change rebuilds the STT and LLM adapters.
    """

    def _patch_all(self, mocker, tmp_path):
        """Patch every external dependency used by main()."""
        cfg_path = str(tmp_path / "config.yaml")
        import yaml
        import io as _io
        from config.loader import Config
        fake_config = Config()
        # Write a minimal config file so load_config doesn't fail
        with open(cfg_path, "w") as f:
            yaml.dump({}, f)

        mocker.patch("main.CONFIG_PATH", cfg_path)
        mocker.patch("main.DB_PATH", str(tmp_path / "data" / "command_history.db"))
        mocker.patch("main.ROUTINES_PATH", str(tmp_path / "data" / "routines.json"))

        mock_load_config = mocker.patch("main.load_config", return_value=fake_config)
        mock_stt = mocker.patch("main.get_stt_adapter", return_value=MagicMock())
        mock_llm = mocker.patch("main.get_llm_adapter", return_value=MagicMock())
        mock_guard = mocker.patch("main.SafetyGuard", return_value=MagicMock())
        mock_collector = mocker.patch("main.MetricsCollector", return_value=MagicMock())
        mock_detector = mocker.patch("main.RoutineDetector", return_value=MagicMock())
        mock_manager = mocker.patch("main.RoutineManager", return_value=MagicMock())
        mock_agent = mocker.patch("main.Agent", return_value=MagicMock())
        mock_hud = mocker.patch("main.NotchHUD", return_value=MagicMock())
        mock_hotkey_cls = mocker.patch("main.HotkeyListener", return_value=MagicMock())
        mock_wakeword_cls = mocker.patch("main.WakeWordListener", return_value=MagicMock())
        mock_settings_cls = mocker.patch("main.SettingsWindow", return_value=MagicMock())
        mock_menubar_cls = mocker.patch("main.VoiceDeskMenuBar", return_value=MagicMock())

        return {
            "config": fake_config,
            "cfg_path": cfg_path,
            "load_config": mock_load_config,
            "stt": mock_stt,
            "llm": mock_llm,
            "guard": mock_guard,
            "collector": mock_collector,
            "detector": mock_detector,
            "manager": mock_manager,
            "agent": mock_agent,
            "hud": mock_hud,
            "hotkey": mock_hotkey_cls,
            "wakeword": mock_wakeword_cls,
            "settings": mock_settings_cls,
            "menubar": mock_menubar_cls,
        }

    def test_load_config_called(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        mocks["load_config"].assert_called_once()

    def test_stt_adapter_initialised(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        mocks["stt"].assert_called_once_with(mocks["config"])

    def test_llm_adapter_initialised(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        mocks["llm"].assert_called_once_with(mocks["config"])

    def test_safety_guard_uses_config_flag(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        kwargs = mocks["guard"].call_args.kwargs
        assert kwargs["require_confirmation"] == mocks["config"].safety.require_confirmation
        # HUD buttons answer danger confirmations
        assert kwargs["ui_confirm"] == mocks["hud"].return_value.arm_danger_prompt

    def test_hud_show_and_idle_called(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        hud_instance = mocks["hud"].return_value
        hud_instance.show.assert_called_once()
        hud_instance.set_state.assert_called_with("idle")

    def test_settings_window_gets_paths(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        _, kwargs = mocks["settings"].call_args
        assert "routines_path" in kwargs
        assert "db_path" in kwargs

    def test_hud_gear_icon_opens_settings(self, mocker, tmp_path):
        """The pinned panel's gear icon must open the same Settings window
        as the menu bar item."""
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        hud_instance = mocks["hud"].return_value
        settings_instance = mocks["settings"].return_value
        hud_instance.set_open_settings_callback.assert_called_once_with(
            settings_instance.show
        )

    def test_menubar_run_called(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        from main import main
        main()
        mocks["menubar"].return_value.run.assert_called_once()

    def test_hotkey_listener_started_when_enabled(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        mocks["config"].activation.hotkey = True
        from main import main
        main()
        mocks["hotkey"].return_value.start.assert_called_once()

    def test_hotkey_listener_skipped_when_disabled(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        mocks["config"].activation.hotkey = False
        from main import main
        main()
        mocks["hotkey"].assert_not_called()

    def test_wakeword_listener_started_when_enabled(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        mocks["config"].activation.wake_word = True
        from main import main
        main()
        mocks["wakeword"].return_value.start.assert_called_once()

    def test_wakeword_listener_skipped_when_disabled(self, mocker, tmp_path):
        mocks = self._patch_all(mocker, tmp_path)
        mocks["config"].activation.wake_word = False
        from main import main
        main()
        mocks["wakeword"].assert_not_called()


# ---------------------------------------------------------------------------
# Config hot-reload
# ---------------------------------------------------------------------------

class TestConfigHotReload:
    """on_config_change should rebuild STT and LLM adapters."""

    def test_on_config_change_rebuilds_stt(self, mocker, tmp_path):
        import yaml
        from config.loader import Config

        cfg_path = str(tmp_path / "config.yaml")
        with open(cfg_path, "w") as f:
            yaml.dump({}, f)

        fake_config = Config()
        new_config = Config()
        new_config.stt.provider = "whisper_api"

        mocker.patch("main.CONFIG_PATH", cfg_path)
        mocker.patch("main.DB_PATH", str(tmp_path / "data" / "cmd.db"))
        mocker.patch("main.ROUTINES_PATH", str(tmp_path / "data" / "r.json"))
        mocker.patch("main.load_config", return_value=fake_config)
        mock_stt = mocker.patch("main.get_stt_adapter", return_value=MagicMock())
        mocker.patch("main.get_llm_adapter", return_value=MagicMock())
        mocker.patch("main.SafetyGuard", return_value=MagicMock())
        mocker.patch("main.MetricsCollector", return_value=MagicMock())
        mocker.patch("main.RoutineDetector", return_value=MagicMock())
        mocker.patch("main.RoutineManager", return_value=MagicMock())
        mocker.patch("main.Agent", return_value=MagicMock())
        mocker.patch("main.NotchHUD", return_value=MagicMock())
        mocker.patch("main.HotkeyListener", return_value=MagicMock())
        mocker.patch("main.WakeWordListener", return_value=MagicMock())

        captured_callback = {}

        def capture_settings(config, path, on_change, routines_path="", db_path=""):
            captured_callback["fn"] = on_change
            return MagicMock()

        mocker.patch("main.SettingsWindow", side_effect=capture_settings)
        mocker.patch("main.VoiceDeskMenuBar", return_value=MagicMock())

        from main import main
        main()

        assert "fn" in captured_callback
        captured_callback["fn"](new_config)
        # stt was called once at init, once after hot-reload
        assert mock_stt.call_count == 2
        last_call_config = mock_stt.call_args[0][0]
        assert last_call_config is new_config

    def test_on_config_change_rebuilds_llm(self, mocker, tmp_path):
        import yaml
        from config.loader import Config

        cfg_path = str(tmp_path / "config.yaml")
        with open(cfg_path, "w") as f:
            yaml.dump({}, f)

        fake_config = Config()
        new_config = Config()
        new_config.llm.provider = "claude"

        mocker.patch("main.CONFIG_PATH", cfg_path)
        mocker.patch("main.DB_PATH", str(tmp_path / "data" / "cmd.db"))
        mocker.patch("main.ROUTINES_PATH", str(tmp_path / "data" / "r.json"))
        mocker.patch("main.load_config", return_value=fake_config)
        mocker.patch("main.get_stt_adapter", return_value=MagicMock())
        initial_llm = MagicMock()
        reloaded_llm = MagicMock()
        mock_llm = mocker.patch("main.get_llm_adapter", side_effect=[initial_llm, reloaded_llm])
        mocker.patch("main.SafetyGuard", return_value=MagicMock())
        mocker.patch("main.MetricsCollector", return_value=MagicMock())
        mocker.patch("main.RoutineDetector", return_value=MagicMock())
        mocker.patch("main.RoutineManager", return_value=MagicMock())
        agent_instance = MagicMock()
        mocker.patch("main.Agent", return_value=agent_instance)
        mocker.patch("main.NotchHUD", return_value=MagicMock())
        mocker.patch("main.HotkeyListener", return_value=MagicMock())
        mocker.patch("main.WakeWordListener", return_value=MagicMock())

        captured_callback = {}

        def capture_settings(config, path, on_change, routines_path="", db_path=""):
            captured_callback["fn"] = on_change
            return MagicMock()

        mocker.patch("main.SettingsWindow", side_effect=capture_settings)
        mocker.patch("main.VoiceDeskMenuBar", return_value=MagicMock())

        from main import main
        main()

        captured_callback["fn"](new_config)
        assert mock_llm.call_count == 2
        last_call_config = mock_llm.call_args[0][0]
        assert last_call_config is new_config
        agent_instance.set_llm.assert_called_once_with(reloaded_llm)


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------

def test_main_module_safe_to_import():
    """Importing main.py must not crash and must not call main()."""
    import main  # already imported; just assert module attributes exist
    assert callable(main.record_audio)
    assert callable(main.main)
    assert callable(main._record_command)


# ---------------------------------------------------------------------------
# Silence endpointing + crash-safety + concurrency guard
# ---------------------------------------------------------------------------

class TestStopOnSilence:
    def test_stops_early_after_speech_then_silence(self, mocker):
        """Speech followed by ~1.2s of silence ends the recording early."""
        sleeps = []

        class FakeStream:
            def __init__(self, **kw):
                self._cb = kw["callback"]

            def __enter__(self):
                loud = np.ones((1600, 1), dtype="int16") * 3000
                quiet = np.zeros((1600, 1), dtype="int16")
                self._cb(loud, 1600, None, None)
                for _ in range(12):          # 12 x 100ms = 1.2s silence
                    self._cb(quiet, 1600, None, None)
                return self

            def __exit__(self, *a):
                return False

        mocker.patch("sounddevice.InputStream", FakeStream)
        mocker.patch("sounddevice.sleep", side_effect=lambda ms: sleeps.append(ms))
        from main import record_audio
        result = record_audio(duration=10, sample_rate=16000,
                              on_level=lambda _lvl: None, stop_on_silence=True)
        assert result[:4] == b"RIFF"
        # done was set before the wait loop ran, so no sleep-out to 10s
        assert len(sleeps) <= 1

    def test_without_speech_runs_to_max_duration(self, mocker):
        class FakeStream:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        sleeps = []
        mocker.patch("sounddevice.InputStream", FakeStream)
        mocker.patch("sounddevice.sleep", side_effect=lambda ms: sleeps.append(ms))
        from main import record_audio
        record_audio(duration=2, sample_rate=16000,
                     on_level=lambda _lvl: None, stop_on_silence=True)
        assert sum(sleeps) == 2000           # waited out the full window


class TestRecordCommandRobustness:
    def test_agent_exception_recovers_hud(self, mocker):
        """A crashing agent must leave the HUD in error → idle, not stuck."""
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        mocker.patch("actions.tts.speak")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "크롬 열어줘"
        agent = MagicMock()
        agent.run.side_effect = ConnectionError("refused")
        _record_command(agent, hud, stt)
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert "error" in states
        assert states[-1] == "idle"

    def test_stt_exception_recovers_hud(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        mocker.patch("actions.tts.speak")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.side_effect = RuntimeError("stt broke")
        _record_command(MagicMock(), hud, stt)
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert "error" in states
        assert states[-1] == "idle"

    def test_error_result_shows_error_state(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "사파리 열어줘"
        agent = MagicMock()
        agent.run.return_value = "오류: LLM 서버에 연결할 수 없어요."
        _record_command(agent, hud, stt)
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert "error" in states and "success" not in states

    def test_transcript_shown_and_cleared(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = "크롬 열어줘"
        agent = MagicMock()
        agent.run.return_value = "완료"
        _record_command(agent, hud, stt)
        transcripts = [c.args[0] for c in hud.set_transcript.call_args_list]
        assert transcripts[0] == "크롬 열어줘"
        assert transcripts[-1] == ""

    def test_concurrent_activation_defers_not_overlaps(self, mocker):
        import main as main_mod
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.return_value = ""
        main_mod._COMMAND_LOCK.acquire()     # simulate a command in flight
        try:
            _record_command(MagicMock(), hud, stt)
            hud.set_state.assert_not_called()              # no overlapping session
            assert main_mod._PENDING_ACTIVATION.is_set()   # but remembered
        finally:
            main_mod._COMMAND_LOCK.release()
            main_mod._PENDING_ACTIVATION.clear()


# ---------------------------------------------------------------------------
# Continuous conversation mode (follow-up listening)
# ---------------------------------------------------------------------------

class TestContinuousMode:
    def _hud_stt_agent(self, transcripts, agent_results):
        hud = MagicMock()
        stt = MagicMock()
        stt.transcribe.side_effect = transcripts
        agent = MagicMock()
        agent.run.side_effect = agent_results
        return hud, stt, agent

    def test_follow_up_listens_again_after_success(self, mocker):
        rec = mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud, stt, agent = self._hud_stt_agent(["크롬 열어줘", "지메일 열어줘", ""],
                                              ["완료", "완료"])
        _record_command(agent, hud, stt, follow_up=True)
        assert agent.run.call_count == 2
        # follow-up rounds use the quick no-speech timeout
        assert rec.call_args_list[0].kwargs["no_speech_timeout"] is None
        assert rec.call_args_list[1].kwargs["no_speech_timeout"] == 5.0
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert states.count("listening") == 3      # 2 commands + final silent round
        assert states[-1] == "idle"

    def test_follow_up_stops_after_failure(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud, stt, agent = self._hud_stt_agent(["없는앱 열어줘"], ["오류: 실패"])
        _record_command(agent, hud, stt, follow_up=True)
        assert agent.run.call_count == 1
        states = [c.args[0] for c in hud.set_state.call_args_list]
        assert "error" in states and states[-1] == "idle"

    def test_no_follow_up_by_default(self, mocker):
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        from main import _record_command
        hud, stt, agent = self._hud_stt_agent(["크롬 열어줘"], ["완료"])
        _record_command(agent, hud, stt)
        assert agent.run.call_count == 1


class TestNoSpeechTimeout:
    def test_silence_only_stops_at_timeout(self, mocker):
        """Without any speech, no_speech_timeout ends the recording early."""
        class FakeStream:
            def __init__(self, **kw):
                self._cb = kw["callback"]

            def __enter__(self):
                quiet = np.zeros((1600, 1), dtype="int16")
                for _ in range(6):           # 0.6s of silence > 0.5s timeout
                    self._cb(quiet, 1600, None, None)
                return self

            def __exit__(self, *a):
                return False

        sleeps = []
        mocker.patch("sounddevice.InputStream", FakeStream)
        mocker.patch("sounddevice.sleep", side_effect=lambda ms: sleeps.append(ms))
        from main import record_audio
        record_audio(duration=10, sample_rate=16000, on_level=lambda _l: None,
                     stop_on_silence=True, no_speech_timeout=0.5)
        assert len(sleeps) <= 1              # stopped early, not 10s worth


class TestPendingActivation:
    def test_activation_while_busy_sets_pending(self, mocker):
        import main as main_mod
        main_mod._PENDING_ACTIVATION.clear()
        main_mod._COMMAND_LOCK.acquire()      # a command is in flight
        try:
            from main import _record_command
            _record_command(MagicMock(), MagicMock(), MagicMock())
            assert main_mod._PENDING_ACTIVATION.is_set()   # not silently dropped
        finally:
            main_mod._COMMAND_LOCK.release()
            main_mod._PENDING_ACTIVATION.clear()

    def test_pending_relistens_after_command_finishes(self, mocker):
        import main as main_mod
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        spawned = {}

        class FakeThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                spawned["target"] = target
                spawned["args"] = args

            def start(self):
                pass

        mocker.patch.object(main_mod.threading, "Thread", FakeThread)
        stt = MagicMock()
        stt.transcribe.return_value = ""       # quick session
        main_mod._PENDING_ACTIVATION.set()     # user spoke during the session
        from main import _record_command
        _record_command(MagicMock(), MagicMock(), stt)
        assert spawned.get("target") is _record_command   # re-listen scheduled
        assert not main_mod._PENDING_ACTIVATION.is_set()

    def test_no_relisten_without_pending(self, mocker):
        import main as main_mod
        mocker.patch("main.record_audio", return_value=b"wav")
        mocker.patch("time.sleep")
        spawned = {}

        class FakeThread:
            def __init__(self, *a, **kw):
                spawned["yes"] = True

            def start(self):
                pass

        mocker.patch.object(main_mod.threading, "Thread", FakeThread)
        stt = MagicMock()
        stt.transcribe.return_value = ""
        main_mod._PENDING_ACTIVATION.clear()
        from main import _record_command
        _record_command(MagicMock(), MagicMock(), stt)
        assert "yes" not in spawned
