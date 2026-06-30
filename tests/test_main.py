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
        mocks["guard"].assert_called_once_with(
            require_confirmation=mocks["config"].safety.require_confirmation
        )

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
        mock_llm = mocker.patch("main.get_llm_adapter", return_value=MagicMock())
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

        captured_callback["fn"](new_config)
        assert mock_llm.call_count == 2
        last_call_config = mock_llm.call_args[0][0]
        assert last_call_config is new_config


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------

def test_main_module_safe_to_import():
    """Importing main.py must not crash and must not call main()."""
    import main  # already imported; just assert module attributes exist
    assert callable(main.record_audio)
    assert callable(main.main)
    assert callable(main._record_command)
