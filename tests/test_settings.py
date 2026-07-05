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
    appkit.NSTextAlignmentRight = 1
    appkit.NSButtonTypeMomentaryPushIn = 1
    appkit.NSSwitchButton = 3
    appkit.NSBezelStyleRounded = 1
    appkit.NSImageAbove = 5
    appkit.NSBoxSeparator = 2
    appkit.NSFontWeightRegular = 400

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
    appkit.NSButton.alloc.return_value.initWithFrame_.return_value = MagicMock()
    appkit.NSButton.buttonWithTitle_target_action_.return_value = MagicMock()

    appkit.NSPopUpButton = MagicMock()
    appkit.NSPopUpButton.alloc.return_value.initWithFrame_pullsDown_.return_value = MagicMock()

    appkit.NSSegmentSwitchTrackingSelectOne = 0
    appkit.NSSegmentedControl = MagicMock()
    appkit.NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_.return_value = MagicMock()

    appkit.NSView = MagicMock()
    view = MagicMock()
    view.subviews.return_value = []
    appkit.NSView.alloc.return_value.initWithFrame_.return_value = view

    appkit.NSBox = MagicMock()
    appkit.NSBox.alloc.return_value.initWithFrame_.return_value = MagicMock()

    appkit.NSColor = MagicMock()
    appkit.NSColor.secondaryLabelColor.return_value = MagicMock()
    appkit.NSColor.tertiaryLabelColor.return_value = MagicMock()
    appkit.NSColor.systemBlueColor.return_value = MagicMock()

    appkit.NSFont = MagicMock()
    appkit.NSFont.systemFontOfSize_.return_value = MagicMock()
    appkit.NSFont.boldSystemFontOfSize_.return_value = MagicMock()

    appkit.NSImageSymbolConfiguration = MagicMock()
    appkit.NSImageSymbolConfiguration.configurationWithPointSize_weight_.return_value = MagicMock()
    appkit.NSImage = MagicMock()
    img = MagicMock()
    img.imageWithSymbolConfiguration_.return_value = img
    appkit.NSImage.imageWithSystemSymbolName_accessibilityDescription_.return_value = img

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
    missing = object()
    previous = sys.modules.get("AppKit", missing)
    mock = _make_appkit_mock()
    sys.modules["AppKit"] = mock
    yield mock
    if previous is missing:
        sys.modules.pop("AppKit", None)
    else:
        sys.modules["AppKit"] = previous


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
        assert SettingsWindow.PAGES == [
            "General", "STT", "LLM", "TTS", "Routines", "Profile", "Metrics",
            "Permissions", "About"
        ]


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


class TestSettingsWindowEditMenu:
    def test_show_installs_edit_menu_for_text_field_paste(self, appkit_mock, default_config):
        app = MagicMock()
        app.mainMenu.return_value = None
        appkit_mock.NSApp = MagicMock(return_value=app)

        main_menu = MagicMock()
        main_menu.itemWithTitle_.return_value = None
        edit_menu = MagicMock()
        edit_menu.itemWithTitle_.return_value = None
        appkit_mock.NSMenu = MagicMock()
        appkit_mock.NSMenu.alloc.return_value.init.return_value = main_menu
        appkit_mock.NSMenu.alloc.return_value.initWithTitle_.return_value = edit_menu

        menu_item = MagicMock()
        menu_item.submenu.return_value = None
        appkit_mock.NSMenuItem = MagicMock()
        appkit_mock.NSMenuItem.alloc.return_value \
            .initWithTitle_action_keyEquivalent_.return_value = menu_item
        appkit_mock.NSEventModifierFlagCommand = 1
        appkit_mock.NSEventModifierFlagShift = 2

        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw.show()

        app.setMainMenu_.assert_called_once_with(main_menu)
        created_items = [
            call.args
            for call in appkit_mock.NSMenuItem.alloc.return_value
            .initWithTitle_action_keyEquivalent_.call_args_list
        ]
        assert ("Paste", "paste:", "v") in created_items
        assert ("Copy", "copy:", "c") in created_items
        assert ("Select All", "selectAll:", "a") in created_items


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
        assert parent.addSubview_.call_count >= 12

    def test_about_page_adds_four_labels(self, appkit_mock):
        from ui.settings.page_about import build_about_page
        parent = MagicMock()
        build_about_page(parent)
        assert parent.addSubview_.call_count >= 8

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
        secure_field.setStringValue_.assert_any_call("sk-test")


# ---------------------------------------------------------------------------
# New blocker fixes — save button wiring, missing pages, nav, ollama field
# ---------------------------------------------------------------------------

class TestSaveButtonWired:
    def test_action_handler_exposes_appkit_selectors(self):
        objc = pytest.importorskip("objc")
        from ui.settings.actions import make_action_handler

        calls = []
        handler = make_action_handler(lambda sender: calls.append(sender))

        for name in (b"click:", b"save:", b"providerChanged:", b"act:", b"selectTab:"):
            assert handler.respondsToSelector_(objc.selector(None, selector=name).selector)

        handler.save_("sender")
        assert calls == ["sender"]

    def test_save_button_is_wired_to_save_action(self, appkit_mock, default_config):
        from ui.settings.page_general import build_general_page
        builder = build_general_page(MagicMock(), default_config, MagicMock())
        button = appkit_mock.NSButton.buttonWithTitle_target_action_.return_value
        button.setTarget_.assert_called_with(builder._save_handler)
        assert button.setAction_.call_args[0][0] == "save:"

    def test_save_handler_invokes_save_fn(self, appkit_mock, default_config, tmp_path):
        from ui.settings.page_general import build_general_page
        calls = []
        builder = build_general_page(MagicMock(), default_config, lambda: calls.append(1))
        builder._save_handler.save_(None)
        assert calls == [1]

    def test_general_save_handler_updates_config(self, appkit_mock, default_config):
        from ui.settings.page_general import build_general_page
        builder = build_general_page(MagicMock(), default_config, MagicMock())
        builder._wake_check = MagicMock()
        builder._wake_field = MagicMock()
        builder._hotkey_check = MagicMock()
        builder._hotkey_field = MagicMock()
        builder._safety_check = MagicMock()
        builder._wake_check.state.return_value = 0
        builder._wake_field.stringValue.return_value = "desk"
        builder._hotkey_check.state.return_value = 1
        builder._hotkey_field.stringValue.return_value = "cmd+space"
        builder._safety_check.state.return_value = 0

        builder._save_handler.save_(None)

        assert default_config.activation.wake_word is False
        assert default_config.activation.wake_phrase == "desk"
        assert default_config.activation.hotkey is True
        assert default_config.activation.hotkey_binding == "cmd+space"
        assert default_config.safety.require_confirmation is False


class TestWindowNewPages:
    def test_init_stores_routines_path(self, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml", routines_path="/tmp/r.json")
        assert sw._routines_path == "/tmp/r.json"

    def test_init_stores_db_path(self, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml", db_path="/tmp/m.db")
        assert sw._db_path == "/tmp/m.db"

    def test_load_page_routines(self, appkit_mock, default_config, tmp_path):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml",
                            routines_path=str(tmp_path / "routines.json"))
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("Routines")
        assert sw._current_page == "Routines"

    def test_load_page_metrics(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        fake_summary = {
            "recognition_rate": 1.0, "success_rate": 1.0, "avg_retry": 0,
            "dangerous_count": 0, "avg_response_ms": 100, "repeated_count": 0,
        }
        with patch("ui.settings.page_metrics.get_today_summary", return_value=fake_summary):
            sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
            sw._window = appkit_mock.NSWindow.alloc() \
                .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
            sw._load_page("Metrics")
        assert sw._current_page == "Metrics"

    def test_load_page_about(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw._window = appkit_mock.NSWindow.alloc() \
            .initWithContentRect_styleMask_backing_defer_(None, None, None, None)
        sw._load_page("About")
        assert sw._current_page == "About"

    def test_build_window_creates_icon_nav_buttons(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw.show()
        assert appkit_mock.NSButton.alloc.return_value.initWithFrame_.call_count >= len(SettingsWindow.PAGES)

    def test_tab_button_handler_selects_matching_page(self, appkit_mock, default_config):
        from ui.settings.window import SettingsWindow
        sw = SettingsWindow(default_config, "/tmp/cfg.yaml")
        sw.show()
        sender = MagicMock()
        sender.tag.return_value = SettingsWindow.PAGES.index("Permissions")
        sw._tab_handler.selectTab_(sender)
        assert sw._current_page == "Permissions"


class TestSettingsButtonActions:
    def test_stt_provider_handler_updates_visible_section(self, appkit_mock, default_config):
        from ui.settings.page_stt import build_stt_page
        builder = build_stt_page(MagicMock(), default_config, MagicMock())
        sender = MagicMock()
        sender.selectedItem.return_value.title.return_value = "whisper_api"

        builder._provider_handler.providerChanged_(sender)

        builder._api_field.setHidden_.assert_called_with(False)
        builder._model_popup.setHidden_.assert_called_with(True)

    def test_stt_save_handler_updates_config(self, appkit_mock, default_config):
        from ui.settings.page_stt import build_stt_page
        save_fn = MagicMock()
        builder = build_stt_page(MagicMock(), default_config, save_fn)
        builder._popup = MagicMock()
        builder._api_field = MagicMock()
        builder._model_popup = MagicMock()
        builder._popup.selectedItem.return_value.title.return_value = "whisper_local"
        builder._api_field.stringValue.return_value = "whisper-key"
        builder._model_popup.selectedItem.return_value.title.return_value = "small"

        builder._save_handler.save_(None)

        assert default_config.stt.provider == "whisper_local"
        assert default_config.stt.whisper_api_key == "whisper-key"
        assert default_config.stt.whisper_local_model == "small"
        save_fn.assert_called_once()

    def test_llm_provider_handler_updates_visible_section(self, appkit_mock, default_config):
        from ui.settings.page_llm import build_llm_page
        builder = build_llm_page(MagicMock(), default_config, MagicMock())
        builder._info_lbl = MagicMock()
        builder._ollama_url = MagicMock()
        builder._claude_key = MagicMock()
        builder._openai_key = MagicMock()
        builder._ollama_views = [builder._ollama_url]
        builder._claude_views = [builder._claude_key]
        builder._openai_views = [builder._openai_key]
        sender = MagicMock()
        sender.selectedItem.return_value.title.return_value = "claude"

        builder._provider_handler.providerChanged_(sender)

        builder._claude_key.setHidden_.assert_called_with(False)
        builder._ollama_url.setHidden_.assert_called_with(True)
        builder._openai_key.setHidden_.assert_called_with(True)

    def test_llm_save_handler_updates_config(self, appkit_mock, default_config):
        from ui.settings.page_llm import build_llm_page
        save_fn = MagicMock()
        builder = build_llm_page(MagicMock(), default_config, save_fn)
        builder._popup = MagicMock()
        builder._ollama_url = MagicMock()
        builder._ollama_model = MagicMock()
        builder._claude_key = MagicMock()
        builder._claude_model = MagicMock()
        builder._openai_key = MagicMock()
        builder._openai_model = MagicMock()
        builder._popup.selectedItem.return_value.title.return_value = "openai"
        builder._ollama_url.stringValue.return_value = "http://localhost:11434"
        builder._ollama_model.stringValue.return_value = "mistral"
        builder._claude_key.stringValue.return_value = "claude-key"
        builder._claude_model.selectedItem.return_value.title.return_value = "claude-sonnet-4-6"
        builder._openai_key.stringValue.return_value = "openai-key"
        builder._openai_model.selectedItem.return_value.title.return_value = "gpt-4o-mini"

        builder._save_handler.save_(None)

        assert default_config.llm.provider == "openai"
        assert default_config.llm.ollama_url == "http://localhost:11434"
        assert default_config.llm.ollama_model == "mistral"
        assert default_config.llm.claude_api_key == "claude-key"
        assert default_config.llm.openai_api_key == "openai-key"
        assert default_config.llm.openai_model == "gpt-4o-mini"
        save_fn.assert_called_once()

    def test_llm_provider_handler_shows_nvidia_section(self, appkit_mock, default_config):
        from ui.settings.page_llm import build_llm_page
        builder = build_llm_page(MagicMock(), default_config, MagicMock())
        builder._info_lbl = MagicMock()
        builder._ollama_url = MagicMock()
        builder._nvidia_key = MagicMock()
        builder._ollama_views = [builder._ollama_url]
        builder._nvidia_views = [builder._nvidia_key]
        sender = MagicMock()
        sender.selectedItem.return_value.title.return_value = "nvidia"

        builder._provider_handler.providerChanged_(sender)

        builder._nvidia_key.setHidden_.assert_called_with(False)
        builder._ollama_url.setHidden_.assert_called_with(True)

    def test_llm_save_handler_persists_nvidia_fields(self, appkit_mock, default_config):
        from ui.settings.page_llm import build_llm_page
        save_fn = MagicMock()
        builder = build_llm_page(MagicMock(), default_config, save_fn)
        builder._popup = MagicMock()
        builder._ollama_url = MagicMock(); builder._ollama_url.stringValue.return_value = ""
        builder._ollama_model = MagicMock(); builder._ollama_model.stringValue.return_value = ""
        builder._claude_key = MagicMock(); builder._claude_key.stringValue.return_value = ""
        builder._claude_model = MagicMock()
        builder._claude_model.selectedItem.return_value.title.return_value = "claude-sonnet-4-6"
        builder._openai_key = MagicMock(); builder._openai_key.stringValue.return_value = ""
        builder._openai_model = MagicMock()
        builder._openai_model.selectedItem.return_value.title.return_value = "gpt-4o"
        builder._nvidia_key = MagicMock()
        builder._nvidia_model = MagicMock()
        builder._popup.selectedItem.return_value.title.return_value = "nvidia"
        builder._nvidia_key.stringValue.return_value = "nvapi-test"
        builder._nvidia_model.stringValue.return_value = "minimaxai/minimax-m3"

        builder._save_handler.save_(None)

        assert default_config.llm.provider == "nvidia"
        assert default_config.llm.nvidia_api_key == "nvapi-test"
        assert default_config.llm.nvidia_model == "minimaxai/minimax-m3"
        save_fn.assert_called_once()

    def test_tts_page_defaults_to_macos_provider(self, appkit_mock, default_config):
        from ui.settings.page_tts import build_tts_page
        default_config.tts.provider = "macos"
        builder = build_tts_page(MagicMock(), default_config, MagicMock())
        assert builder._info_lbl.setStringValue_.call_args_list[-1][0][0] == \
            "로컬 실행 — 인터넷 없이 즉시 사용 가능"

    def test_tts_provider_handler_shows_nvidia_section(self, appkit_mock, default_config):
        from ui.settings.page_tts import build_tts_page
        builder = build_tts_page(MagicMock(), default_config, MagicMock())
        builder._info_lbl = MagicMock()
        builder._voice_field = MagicMock()
        builder._nvidia_key = MagicMock()
        builder._macos_views = [builder._voice_field]
        builder._nvidia_views = [builder._nvidia_key]
        sender = MagicMock()
        sender.selectedItem.return_value.title.return_value = "nvidia"

        builder._provider_handler.providerChanged_(sender)

        builder._nvidia_key.setHidden_.assert_called_with(False)
        builder._voice_field.setHidden_.assert_called_with(True)

    def test_tts_save_handler_persists_macos_fields(self, appkit_mock, default_config):
        from ui.settings.page_tts import build_tts_page
        save_fn = MagicMock()
        builder = build_tts_page(MagicMock(), default_config, save_fn)
        builder._popup = MagicMock()
        builder._popup.selectedItem.return_value.title.return_value = "macos"
        builder._voice_field = MagicMock(); builder._voice_field.stringValue.return_value = "Juna"
        builder._rate_field = MagicMock(); builder._rate_field.stringValue.return_value = "180"
        builder._nvidia_key = MagicMock(); builder._nvidia_key.stringValue.return_value = ""
        builder._nvidia_function_id = MagicMock(); builder._nvidia_function_id.stringValue.return_value = ""
        builder._nvidia_voice = MagicMock(); builder._nvidia_voice.stringValue.return_value = ""

        builder._save_handler.save_(None)

        assert default_config.tts.provider == "macos"
        assert default_config.tts.voice == "Juna"
        assert default_config.tts.rate == 180
        save_fn.assert_called_once()

    def test_tts_save_handler_persists_nvidia_fields(self, appkit_mock, default_config):
        from ui.settings.page_tts import build_tts_page
        save_fn = MagicMock()
        builder = build_tts_page(MagicMock(), default_config, save_fn)
        builder._popup = MagicMock()
        builder._popup.selectedItem.return_value.title.return_value = "nvidia"
        builder._voice_field = MagicMock(); builder._voice_field.stringValue.return_value = "Yuna"
        builder._rate_field = MagicMock(); builder._rate_field.stringValue.return_value = "200"
        builder._nvidia_key = MagicMock(); builder._nvidia_key.stringValue.return_value = "nvapi-test"
        builder._nvidia_function_id = MagicMock()
        builder._nvidia_function_id.stringValue.return_value = "abc-123-func-id"
        builder._nvidia_voice = MagicMock()
        builder._nvidia_voice.stringValue.return_value = "Chatterbox-Multilingual.ko-KR.Male"

        builder._save_handler.save_(None)

        assert default_config.tts.provider == "nvidia"
        assert default_config.tts.nvidia_api_key == "nvapi-test"
        assert default_config.tts.nvidia_function_id == "abc-123-func-id"
        assert default_config.tts.nvidia_voice == "Chatterbox-Multilingual.ko-KR.Male"
        save_fn.assert_called_once()

    def test_permissions_button_handlers_open_expected_preferences(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=3), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=False), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=False), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"), \
             patch("ui.settings.page_permissions._open_prefs") as open_prefs:
            builder = build_permissions_page(parent)
            builder._handlers[0].act_(None)
            builder._handlers[1].act_(None)
            builder._handlers[2].act_(None)

            open_prefs.assert_any_call("Privacy_Microphone")
            open_prefs.assert_any_call("Privacy_Accessibility")
            open_prefs.assert_any_call("Privacy_ScreenCapture")

    def test_permissions_mic_request_also_opens_settings(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=0), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=True), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=True), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"), \
             patch("ui.settings.page_permissions._request_mic_access") as request_mic, \
             patch("ui.settings.page_permissions._open_prefs") as open_prefs:
            builder = build_permissions_page(parent)
            builder._handlers[0].act_(None)

            request_mic.assert_called_once()
            open_prefs.assert_called_with("Privacy_Microphone")

    def test_privacy_url_prefers_current_system_settings_extension(self):
        from ui.settings.page_permissions import _pref_urls
        urls = _pref_urls("Privacy_Microphone")
        assert urls[0] == (
            "x-apple.systempreferences:"
            "com.apple.settings.PrivacySecurity.extension?Privacy_Microphone"
        )
        assert "com.apple.preference.security?Privacy_Microphone" in urls[1]

    def test_permissions_refresh_updates_badges(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=0), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=False), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=False), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"):
            builder = build_permissions_page(parent)

        # Simulate permissions being granted
        with patch("ui.settings.page_permissions._mic_status", return_value=3), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=True), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=True):
            builder.refresh()

        builder._mic_badge.setStringValue_.assert_called_with("✅ 허용됨")
        builder._acc_badge.setStringValue_.assert_called_with("✅ 허용됨")
        builder._scr_badge.setStringValue_.assert_called_with("✅ 허용됨")

    def test_permissions_refresh_shows_denied(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=3), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=True), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=True), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"):
            builder = build_permissions_page(parent)

        # Simulate permissions being revoked
        with patch("ui.settings.page_permissions._mic_status", return_value=2), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=False), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=False):
            builder.refresh()

        builder._mic_badge.setStringValue_.assert_called_with("❌ 미허용")
        builder._acc_badge.setStringValue_.assert_called_with("❌ 미허용")
        builder._scr_badge.setStringValue_.assert_called_with("❌ 미허용")

    def test_permissions_refresh_button_triggers_refresh(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=0), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=False), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=False), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"):
            builder = build_permissions_page(parent)

        # The refresh handler is the 4th handler (index 3)
        with patch("ui.settings.page_permissions._mic_status", return_value=3), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=True), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=True):
            builder._handlers[3].act_(None)

        builder._mic_badge.setStringValue_.assert_called_with("✅ 허용됨")

    def test_permissions_teardown_removes_observer(self, appkit_mock):
        from ui.settings.page_permissions import build_permissions_page
        parent = MagicMock()
        with patch("ui.settings.page_permissions._mic_status", return_value=3), \
             patch("ui.settings.page_permissions._accessibility_granted", return_value=True), \
             patch("ui.settings.page_permissions._screen_recording_granted", return_value=True), \
             patch.object(__import__("ui.settings.page_permissions", fromlist=["_PermissionsPageBuilder"])._PermissionsPageBuilder,
                          "_register_activation_observer"):
            builder = build_permissions_page(parent)

        fake_obs = MagicMock()
        builder._observer = fake_obs
        builder.teardown()
        assert builder._observer is None


class TestLLMOllamaField:
    def test_ollama_uses_text_field_not_model_popup(self, appkit_mock):
        from ui.settings.page_llm import build_llm_page
        config = Config()
        config.llm.provider = "ollama"
        build_llm_page(MagicMock(), config, MagicMock())
        # Provider/model popups for hidden provider sections may exist, but the
        # active Ollama model control stays a free-form text field.
        appkit_mock.NSTextField.alloc.return_value.initWithFrame_.return_value \
            .setStringValue_.assert_any_call(config.llm.ollama_model)

    def test_ollama_model_field_uses_ollama_model_value(self, appkit_mock):
        from ui.settings.page_llm import build_llm_page
        config = Config()
        config.llm.provider = "ollama"
        config.llm.ollama_model = "llama3"
        # Other provider sections (e.g. NVIDIA) also build plain NSTextField model
        # controls sharing this same mocked instance, so capture every value set
        # rather than assuming Ollama's is the last one.
        captured = []
        text_field = MagicMock()
        text_field.setStringValue_.side_effect = lambda v: captured.append(v)
        appkit_mock.NSTextField.alloc.return_value.initWithFrame_.return_value = text_field
        build_llm_page(MagicMock(), config, MagicMock())
        assert "llama3" in captured


# ---------------------------------------------------------------------------
# Permissions page logic (연결 로직)
# ---------------------------------------------------------------------------

def test_open_prefs_uses_url_scheme_before_applescript(mocker):
    """URL scheme needs no Automation permission — must be tried first."""
    import ui.settings.page_permissions as pp
    order = []
    mocker.patch.object(pp, "_open_url", side_effect=lambda u: order.append("url") or True)
    mocker.patch.object(pp, "_open_prefs_applescript",
                        side_effect=lambda k: order.append("applescript") or True)
    assert pp._open_prefs("Privacy_Accessibility") is True
    assert order == ["url"]                      # AppleScript never reached


def test_open_prefs_falls_back_to_applescript(mocker):
    import ui.settings.page_permissions as pp
    mocker.patch.object(pp, "_open_url", return_value=False)
    mock_as = mocker.patch.object(pp, "_open_prefs_applescript", return_value=True)
    assert pp._open_prefs("Privacy_Accessibility") is True
    mock_as.assert_called_once()


def test_pref_urls_target_privacy_panes():
    import ui.settings.page_permissions as pp
    urls = pp._pref_urls("Privacy_Accessibility")
    assert all(u.startswith("x-apple.systempreferences:") for u in urls)
    assert "Privacy_Accessibility" in urls[0]


def test_request_accessibility_uses_ax_trusted_prompt(mocker):
    """Must call AXIsProcessTrustedWithOptions (registers app in the list),
    NOT an AppleScript/System Events call (that prompts Automation instead)."""
    import sys
    import ui.settings.page_permissions as pp
    calls = {}
    fake = type(sys)("ApplicationServices")
    fake.kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
    fake.AXIsProcessTrustedWithOptions = lambda opts: calls.setdefault("opts", opts)
    mocker.patch.dict(sys.modules, {"ApplicationServices": fake})
    mock_sub = mocker.patch.object(pp.subprocess, "run")

    assert pp._request_accessibility_access() is True
    assert calls["opts"] == {"AXTrustedCheckOptionPrompt": True}
    mock_sub.assert_not_called()                 # no osascript involved
