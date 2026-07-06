# ui/settings/page_tts.py
from config.loader import Config
from ui.settings.actions import make_action_handler, wire_action

_LBL_W = 155
_CTRL_X = 172
_CTRL_W = 360
_ROW = 28


def _cat(parent, text, y):
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(8, y + 2, _LBL_W, 18))
    t.setAlignment_(AppKit.NSTextAlignmentRight)
    t.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    t.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    parent.addSubview_(t)
    return t


def _lbl(parent, text, y, *, small=False, w=None):
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, w or _CTRL_W, 18))
    if small:
        t.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
        t.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
    parent.addSubview_(t)
    return t


def _field(parent, value, y, w=280):
    import AppKit
    f = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22)
    )
    f.setStringValue_(str(value))
    parent.addSubview_(f)
    return f


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)
    return line


class _TTSPageBuilder:
    def __init__(self, parent, config, save_fn):
        self._parent = parent
        self._config = config
        self._save_fn = save_fn
        self._build()

    def _build(self):
        import AppKit
        y = 358

        v = _cat(self._parent, "음성:", y)
        self._voice_field = _field(self._parent, self._config.tts.voice, y, w=200)
        y -= _ROW

        _cat(self._parent, "속도:", y)
        self._rate_field = _field(self._parent, str(self._config.tts.rate), y, w=80)
        y -= _ROW

        _lbl(self._parent, "로컬 실행(macOS say) — 무료·오프라인·즉시 재생", y, small=True)
        y -= 20
        _sep(self._parent, y)
        y -= 18

        # ── 저장 ───────────────────────────────────────────────────────────────
        _cat(self._parent, "기타:", y)
        self._save_handler = make_action_handler(self.save_)
        save_btn = AppKit.NSButton.buttonWithTitle_target_action_(
            "저장", None, None
        )
        wire_action(save_btn, self._save_handler, "save:")
        save_btn.setFrame_(AppKit.NSMakeRect(_CTRL_X, y - 3, 72, 28))
        save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._parent.addSubview_(save_btn)

        self._status_lbl = AppKit.NSTextField.labelWithString_("")
        self._status_lbl.setFrame_(AppKit.NSMakeRect(_CTRL_X + 80, y + 2, 260, 18))
        self._parent.addSubview_(self._status_lbl)

    def save_(self, _sender):
        self._config.tts.voice = self._voice_field.stringValue()
        try:
            self._config.tts.rate = int(self._rate_field.stringValue())
        except ValueError:
            pass
        self._save_fn()
        # TTS reads its config live on every speak() call (unlike the LLM
        # adapter, which is a constructed object swapped in on config change),
        # so no restart is needed here.
        self._status_lbl.setStringValue_("✅ 저장 완료 — 즉시 적용")


def build_tts_page(parent_view, config: Config, save_fn):
    try:
        import AppKit  # noqa: F401
        return _TTSPageBuilder(parent_view, config, save_fn)
    except ImportError:
        return None
