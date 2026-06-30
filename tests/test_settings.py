"""
Tests for ui/settings — PyObjC is mocked throughout.
Covers: config read/write on save, page selection logic, CLI fallback.
"""
import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from config.loader import Config


# ---------------------------------------------------------------------------
# Helpers — build a minimal AppKit mock so imports succeed everywhere
# ---------------------------------------------------------------------------

def _make_appkit_mock():
    appkit = types.ModuleType("AppKit")
    appkit.NSMakeRect = lambda x, y, w, h: (x, y, w, h)
    appkit.NSWindowStyleMaskTitled = 1
    appkit.NSWindowStyleMaskClosable = 2
    appkit.NSWindowStyleMaskResizable = 8
    appkit.NSBackingStoreBuffered = 2

    def _label(text):
        m = MagicMock()
        m.stringValue.return_value = text
        return m

    appkit.NSTextField = MagicMock()
    appkit.NSTextField.labelWithString_ = MagicMock(side_effect=_label)
    appkit.NSTextField.alloc.return_value.initWithFrame_.return_value = MagicMock(
        stringValue=MagicMock(return_value="")
    )

    appkit.NSSecureTextField = MagicMock()
    appkit.NSSecureTextField.alloc.return_value.initWithFrame_.return_value = MagicMock(
        stringValue=MagicMock(return_value="")
    )

    appkit.NSButton = MagicMock()
    appkit.NSButton.buttonWithTitle_target_action_.return_value = MagicMock()

    appkit.NSPopUpButton = MagicMock()
    appkit.NSPopUpButton.alloc.return_value.initWithFrame_pullsDown_.return_value = MagicMock()

    fake_window = MagicMock()
    fake_window.contentView.return_value = MagicMock()
    appkit.NSWindow = MagicMock()
    appkit.NSWindow.alloc.return_value \
        .initWithContentRect_styleMask_backing_defer_.return_value = fake_window

    return appkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def appkit_mock():
    """Inject a fake AppKit into sys.modules for the duration of a test."""
    mock = _make_appkit_mock()
    sys.modules["AppKit"] = mock
    yield mock
    # Restore: block further real imports to avoid ObjC registration conflicts.
    sys.modules["AppKit"] = None


@pytest.fixture
def default_config():
    return Config()


# ---------------------------------------------------------------------------
# SettingsWindow — unit tests
# ---------------------------------------------------------------------------

class TestSettingsWindowInit:
    def test_stores_config_and_path(self, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        assert sw._config is default_config
        assert sw._config_path == "/tmp/cfg.yaml"

    def test_default_page_is_general(self, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        assert sw._current_page == "General"

    def test_pages_list(self):
        from ui.settings.window import SettingsWindow
        assert SettingsWindow.PAGES == ["General", "STT", "LLM", "Routines", "Metrics", "About"]


class TestSettingsWindowSave:
    def test_save_calls_save_config(self, default_config, tmp_path):
        from ui.settings.window import SettingsWindow
        cfg_path = str(tmp_path / "cfg.yaml")
        sw = SettingsWindow(default_config, cfg_path)
        sw._save()
        import os
        assert os.path.exists(cfg_path)

    def test_save_calls_on_change_callback(self, default_config, tmp_path):
        from ui.settings.window import SettingsWindow
        callback = MagicMock()
        cfg_path = str(tmp_path / "cfg.yaml")
        sw = SettingsWindow(default_config, cfg_path, on_config_change=callback)
        sw._save()
        callback.assert_called_once_with(default_config)

    def test_save_without_callback_does_not_raise(self, default_config, tmp_path):
        from ui.settings.window import SettingsWindow
        cfg_path = str(tmp_path / "cfg.yaml")
        sw = SettingsWindow(default_config, cfg_path, on_config_change=None)
        sw._save()  # should not raise


class TestSettingsWindowPageSelection:
    def test_load_page_sets_current_page(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("STT")
        assert sw._current_page == "STT"

    def test_load_page_general(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("General")
        assert sw._current_page == "General"

    def test_load_page_stt(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("STT")
        assert sw._current_page == "STT"

    def test_load_page_llm(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("LLM")
        assert sw._current_page == "LLM"

    def test_load_unknown_page_does_not_raise(self, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._load_page("NonExistent")
        assert sw._current_page == "NonExistent"


class TestSettingsWindowCLIMode:
    def test_show_falls_back_to_cli_when_no_appkit(self, default_config, capsys):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.window import SettingsWindow
            sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
            sw.show()
        out = capsys.readouterr().out
        assert "[Settings] PyObjC not available" in out

    def test_cli_mode_prints_provider_info(self, default_config, capsys):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._cli_mode()
        out = capsys.readouterr().out
        assert "STT=" in out
        assert "LLM=" in out


# ---------------------------------------------------------------------------
# Page modules — smoke-test imports and no-op when AppKit blocked
# ---------------------------------------------------------------------------

class TestPageModulesNoAppKit:
    """Verify pages silently skip rendering when AppKit is unavailable."""

    def test_general_page_no_appkit(self, default_config):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_general import build_general_page
            build_general_page(MagicMock(), default_config, MagicMock())

    def test_stt_page_no_appkit(self, default_config):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_stt import build_stt_page
            build_stt_page(MagicMock(), default_config, MagicMock())

    def test_llm_page_no_appkit(self, default_config):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_llm import build_llm_page
            build_llm_page(MagicMock(), default_config, MagicMock())

    def test_routines_page_no_appkit(self, default_config):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_routines import build_routines_page
            mgr = MagicMock()
            mgr.load_all.return_value = [{"name": "test", "steps": []}]
            build_routines_page(MagicMock(), default_config, mgr, MagicMock())

    def test_metrics_page_no_appkit(self, tmp_path):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_metrics import build_metrics_page
            build_metrics_page(MagicMock(), str(tmp_path / "nonexistent.db"))

    def test_about_page_no_appkit(self):
        with patch.dict(sys.modules, {"AppKit": None}):
            from ui.settings.page_about import build_about_page
            build_about_page(MagicMock())


class TestPageModulesWithAppKit:
    """Verify pages call addSubview_ when AppKit is available."""

    def test_general_page_adds_subviews(self, appkit_mock, default_config):
        from ui.settings.page_general import build_general_page
        parent = MagicMock()
        build_general_page(parent, default_config, MagicMock())
        assert parent.addSubview_.called

    def test_stt_page_adds_subviews(self, appkit_mock, default_config):
        from ui.settings.page_stt import build_stt_page
        parent = MagicMock()
        build_stt_page(parent, default_config, MagicMock())
        assert parent.addSubview_.called

    def test_llm_page_adds_subviews(self, appkit_mock, default_config):
        from ui.settings.page_llm import build_llm_page
        parent = MagicMock()
        build_llm_page(parent, default_config, MagicMock())
        assert parent.addSubview_.called

    def test_routines_page_calls_load_all(self, appkit_mock, default_config):
        from ui.settings.page_routines import build_routines_page
        parent = MagicMock()
        mgr = MagicMock()
        mgr.load_all.return_value = [
            {"name": "morning", "steps": [{"action": "a", "params": {}}]},
        ]
        build_routines_page(parent, default_config, mgr, MagicMock())
        mgr.load_all.assert_called_once()

    def test_metrics_page_adds_six_labels(self, appkit_mock):
        from ui.settings.page_metrics import build_metrics_page
        parent = MagicMock()
        fake_summary = {
            "recognition_rate": 0.9, "success_rate": 0.85,
            "avg_retry": 0.3, "dangerous_count": 1,
            "avg_response_ms": 850, "repeated_count": 2,
        }
        with patch("ui.settings.page_metrics.get_today_summary", return_value=fake_summary):
            build_metrics_page(parent, "/fake/path.db")
        assert parent.addSubview_.call_count == 6

    def test_about_page_adds_four_labels(self, appkit_mock):
        from ui.settings.page_about import build_about_page
        parent = MagicMock()
        build_about_page(parent)
        assert parent.addSubview_.call_count == 4

    def test_about_page_version(self):
        from ui.settings.page_about import VERSION
        assert VERSION == "0.1.0"


# ---------------------------------------------------------------------------
# LLM page — model list logic
# ---------------------------------------------------------------------------

class TestLLMPageModels:
    def test_claude_models_constant(self):
        from ui.settings.page_llm import CLAUDE_MODELS
        assert "claude-sonnet-4-6" in CLAUDE_MODELS

    def test_openai_models_constant(self):
        from ui.settings.page_llm import OPENAI_MODELS
        assert "gpt-4o" in OPENAI_MODELS

    def test_llm_page_shows_claude_key_for_claude_provider(self, appkit_mock):
        from ui.settings.page_llm import build_llm_page
        config = Config()
        config.llm.provider = "claude"
        config.llm.claude_api_key = "sk-test"
        parent = MagicMock()
        captured = {}

        def capture_set(val):
            captured["key"] = val

        secure_field = MagicMock()
        secure_field.setStringValue_.side_effect = capture_set
        appkit_mock.NSSecureTextField.alloc.return_value \
            .initWithFrame_.return_value = secure_field

        build_llm_page(parent, config, MagicMock())
        assert captured.get("key") == "sk-test"
