# ui/settings/window.py
from config.loader import Config, save_config


class SettingsWindow:
    PAGES = ["General", "STT", "LLM", "Routines", "Metrics", "About"]

    def __init__(self, config: Config, config_path: str, on_config_change=None):
        self._config = config
        self._config_path = config_path
        self._on_change = on_config_change
        self._window = None
        self._current_page = "General"

    def _save(self):
        save_config(self._config, self._config_path)
        if self._on_change:
            self._on_change(self._config)

    def show(self) -> None:
        try:
            import AppKit
            self._build_window()
            self._window.makeKeyAndOrderFront_(None)
        except ImportError:
            print("[Settings] PyObjC not available — CLI mode")
            self._cli_mode()

    def _cli_mode(self) -> None:
        print(f"Current config: STT={self._config.stt.provider}, LLM={self._config.llm.provider}")

    def _build_window(self) -> None:
        import AppKit
        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(200, 200, 700, 500),
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskResizable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("VoiceDesk Settings")
        self._load_page("General")

    def _load_page(self, page_name: str) -> None:
        self._current_page = page_name
        page_map = {
            "General": self._build_general,
            "STT": self._build_stt,
            "LLM": self._build_llm,
        }
        builder = page_map.get(page_name)
        if builder:
            builder()

    def _build_general(self) -> None:
        from ui.settings.page_general import build_general_page
        build_general_page(self._window.contentView(), self._config, self._save)

    def _build_stt(self) -> None:
        from ui.settings.page_stt import build_stt_page
        build_stt_page(self._window.contentView(), self._config, self._save)

    def _build_llm(self) -> None:
        from ui.settings.page_llm import build_llm_page
        build_llm_page(self._window.contentView(), self._config, self._save)
