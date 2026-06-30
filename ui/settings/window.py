# ui/settings/window.py
from config.loader import Config, save_config


class _NavHandler:
    def __init__(self, load_fn, pages):
        self._load_fn = load_fn
        self._pages = pages

    def select_(self, sender):
        idx = sender.selectedSegment()
        self._load_fn(self._pages[idx])


class SettingsWindow:
    PAGES = ["General", "STT", "LLM", "Routines", "Metrics", "About"]

    def __init__(self, config: Config, config_path: str, on_config_change=None,
                 routines_path: str = "", db_path: str = ""):
        self._config = config
        self._config_path = config_path
        self._on_change = on_config_change
        self._routines_path = routines_path
        self._db_path = db_path
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
        nav_handler = _NavHandler(self._load_page, self.PAGES)
        seg = AppKit.NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            self.PAGES, AppKit.NSSegmentSwitchTrackingSelectOne, nav_handler, "select:"
        )
        seg.setFrame_(AppKit.NSMakeRect(0, 470, 700, 30))
        self._window.contentView().addSubview_(seg)
        self._load_page("General")

    def _load_page(self, page_name: str) -> None:
        self._current_page = page_name
        page_map = {
            "General": self._build_general,
            "STT": self._build_stt,
            "LLM": self._build_llm,
            "Routines": self._build_routines,
            "Metrics": self._build_metrics,
            "About": self._build_about,
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

    def _build_routines(self) -> None:
        from ui.settings.page_routines import build_routines_page
        from routines.manager import RoutineManager
        try:
            mgr = RoutineManager(self._routines_path)
            build_routines_page(self._window.contentView(), self._config, mgr, self._save)
        except Exception:
            pass

    def _build_metrics(self) -> None:
        from ui.settings.page_metrics import build_metrics_page
        try:
            build_metrics_page(self._window.contentView(), self._db_path)
        except Exception:
            pass

    def _build_about(self) -> None:
        from ui.settings.page_about import build_about_page
        build_about_page(self._window.contentView())
