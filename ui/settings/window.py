# ui/settings/window.py
from config.loader import Config, save_config
from ui.settings.actions import make_action_handler, wire_action
from ui.settings.edit_menu import ensure_standard_edit_menu

_W = 560
_H = 460
_TB = 64           # toolbar height
_CH = _H - _TB    # content area height = 396

_TABS = [
    ("General",     "gearshape"),
    ("STT",         "mic"),
    ("LLM",         "cpu"),
    ("TTS",         "speaker.wave.2"),
    ("Routines",    "list.bullet"),
    ("Profile",     "person.crop.circle"),
    ("Metrics",     "chart.bar"),
    ("Permissions", "lock.shield"),
    ("About",       "info.circle"),
]

class SettingsWindow:
    PAGES = [t[0] for t in _TABS]

    def __init__(self, config: Config, config_path: str, on_config_change=None,
                 routines_path: str = "", db_path: str = ""):
        self._config = config
        self._config_path = config_path
        self._on_change = on_config_change
        self._routines_path = routines_path
        self._db_path = db_path
        self._window = None
        self._body = None
        self._tab_handler = None  # keep ObjC target alive
        self._tab_btns = []       # (NSButton, name) for highlight updates
        self._page_builder = None
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
        ensure_standard_edit_menu()
        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(200, 200, _W, _H),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered, False,
        )
        self._window.setTitle_("VoiceDesk 설정")
        cv = self._window.contentView()

        # ── Icon Toolbar ─────────────────────────────────────────────────────
        bar = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, _CH, _W, _TB)
        )
        cv.addSubview_(bar)

        bw = _W // len(_TABS)
        self._tab_handler = make_action_handler(self._select_tab_from_sender)
        for i, (name, sym) in enumerate(_TABS):
            btn = AppKit.NSButton.alloc().initWithFrame_(
                AppKit.NSMakeRect(i * bw, 1, bw, _TB - 1)
            )
            btn.setButtonType_(AppKit.NSButtonTypeMomentaryPushIn)
            btn.setBordered_(False)
            btn.setTitle_(name)
            btn.setFont_(AppKit.NSFont.systemFontOfSize_(10))
            btn.setImagePosition_(AppKit.NSImageAbove)
            btn.setTag_(i)
            wire_action(btn, self._tab_handler, "selectTab:")

            try:
                cfg = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                    20, AppKit.NSFontWeightRegular
                )
                img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(sym, None)
                btn.setImage_(img.imageWithSymbolConfiguration_(cfg))
            except Exception:
                pass

            bar.addSubview_(btn)
            self._tab_btns.append((btn, name))

        # Bottom separator of toolbar
        sep = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, _W, 1))
        sep.setBoxType_(AppKit.NSBoxSeparator)
        bar.addSubview_(sep)

        # ── Content Body ─────────────────────────────────────────────────────
        self._body = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _W, _CH)
        )
        cv.addSubview_(self._body)

        self._select_tab("General")

    def _select_tab_from_sender(self, sender) -> None:
        try:
            idx = int(sender.tag())
        except Exception:
            return
        if 0 <= idx < len(_TABS):
            self._select_tab(_TABS[idx][0])

    def _select_tab(self, name: str) -> None:
        import AppKit

        self._current_page = name
        for btn, n in self._tab_btns:
            if n == name:
                btn.setContentTintColor_(AppKit.NSColor.systemBlueColor())
            else:
                btn.setContentTintColor_(AppKit.NSColor.secondaryLabelColor())

        if self._body is None:
            return

        old_builder = self._page_builder
        self._page_builder = None
        if old_builder is not None and hasattr(old_builder, "teardown"):
            old_builder.teardown()
        for v in list(self._body.subviews()):
            v.removeFromSuperview()

        {
            "General":     self._build_general,
            "STT":         self._build_stt,
            "LLM":         self._build_llm,
            "TTS":         self._build_tts,
            "Routines":    self._build_routines,
            "Profile":     self._build_profile,
            "Metrics":     self._build_metrics,
            "Permissions": self._build_permissions,
            "About":       self._build_about,
        }.get(name, lambda: None)()

    def _load_page(self, page_name: str) -> None:
        try:
            self._select_tab(page_name)
        except ImportError:
            self._current_page = page_name

    def _build_general(self):
        from ui.settings.page_general import build_general_page
        self._page_builder = build_general_page(self._body, self._config, self._save)

    def _build_stt(self):
        from ui.settings.page_stt import build_stt_page
        self._page_builder = build_stt_page(self._body, self._config, self._save)

    def _build_llm(self):
        from ui.settings.page_llm import build_llm_page
        self._page_builder = build_llm_page(self._body, self._config, self._save)

    def _build_tts(self):
        from ui.settings.page_tts import build_tts_page
        self._page_builder = build_tts_page(self._body, self._config, self._save)

    def _build_routines(self):
        from ui.settings.page_routines import build_routines_page
        from routines.manager import RoutineManager
        try:
            build_routines_page(self._body, self._config, RoutineManager(self._routines_path), self._save)
        except Exception:
            pass

    def _build_profile(self):
        from ui.settings.page_profile import build_profile_page
        try:
            self._page_builder = build_profile_page(self._body, self._db_path)
        except Exception:
            pass

    def _build_metrics(self):
        from ui.settings.page_metrics import build_metrics_page
        try:
            build_metrics_page(self._body, self._db_path)
        except Exception:
            pass

    def _build_permissions(self):
        from ui.settings.page_permissions import build_permissions_page
        self._page_builder = build_permissions_page(self._body)

    def _build_about(self):
        from ui.settings.page_about import build_about_page
        build_about_page(self._body)
