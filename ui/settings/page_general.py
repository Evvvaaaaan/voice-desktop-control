# ui/settings/page_general.py
from config.loader import Config
from ui.settings.actions import make_action_handler, wire_action

# Content area: 560 × 396 (window 560×460 minus 64px toolbar)
_LBL_W = 155   # left-column label width (right-aligned)
_CTRL_X = 172  # right-column start x
_CTRL_W = 360  # right-column width
_ROW = 28      # vertical spacing between rows


def _cat(parent, text, y):
    """Right-aligned category label in left column."""
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(8, y + 2, _LBL_W, 18))
    t.setAlignment_(AppKit.NSTextAlignmentRight)
    t.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    t.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    parent.addSubview_(t)
    return t


def _lbl(parent, text, y, *, small=False, w=None):
    """Label in the right column."""
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, w or _CTRL_W, 18))
    if small:
        t.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
        t.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
    parent.addSubview_(t)
    return t


def _checkbox(parent, label, y, checked, *, x=None, w=None):
    import AppKit
    cb = AppKit.NSButton.buttonWithTitle_target_action_(label, None, None)
    cb.setButtonType_(AppKit.NSSwitchButton)
    cb.setFrame_(AppKit.NSMakeRect(x if x is not None else _CTRL_X, y, w or _CTRL_W, 18))
    cb.setState_(1 if checked else 0)
    parent.addSubview_(cb)
    return cb


def _field(parent, value, y, w=200):
    import AppKit
    f = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22)
    )
    f.setStringValue_(str(value))
    parent.addSubview_(f)
    return f


def _inline(parent, label, value, y, fw=180):
    """Inline 'label: [field]' both in right column."""
    import AppKit
    lw = len(label) * 7 + 4
    t = AppKit.NSTextField.labelWithString_(label)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, lw, 18))
    t.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    t.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    parent.addSubview_(t)
    f = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X + lw + 4, y, fw, 22)
    )
    f.setStringValue_(str(value))
    parent.addSubview_(f)
    return f


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)


class _GeneralPageBuilder:
    def __init__(self, parent, config, save_fn):
        self._parent = parent
        self._config = config
        self._save_fn = save_fn
        self._build()

    def _build(self):
        import AppKit
        y = 358

        # ── 활성화 방식 ────────────────────────────────────────────────────────
        _cat(self._parent, "활성화 방식:", y)
        self._wake_check = _checkbox(
            self._parent, "웨이크 워드 사용", y, self._config.activation.wake_word
        )
        y -= _ROW

        self._wake_field = _inline(
            self._parent, "문구:", self._config.activation.wake_phrase, y, fw=200
        )
        y -= _ROW

        self._hotkey_check = _checkbox(
            self._parent, "단축키 사용", y, self._config.activation.hotkey
        )
        y -= _ROW

        self._hotkey_field = _inline(
            self._parent, "단축키:", self._config.activation.hotkey_binding, y, fw=160
        )

        y -= _ROW + 8
        _sep(self._parent, y)
        y -= 16

        # ── 안전 ───────────────────────────────────────────────────────────────
        _cat(self._parent, "안전:", y)
        self._safety_check = _checkbox(
            self._parent, "위험 작업 확인 요청", y, self._config.safety.require_confirmation
        )
        y -= 18
        _lbl(self._parent, "위험한 명령 실행 시 확인을 요청합니다.", y, small=True)

        y -= _ROW + 18
        _sep(self._parent, y)
        y -= 16

        # ── 노치 위젯 ───────────────────────────────────────────────────────────
        # Two columns so five toggles fit in three rows.
        _col2_x = _CTRL_X + 180
        _cat(self._parent, "노치 위젯:", y)
        self._clock_check = _checkbox(
            self._parent, "시계 표시", y, self._config.hud.show_clock, w=170
        )
        self._media_check = _checkbox(
            self._parent, "재생 중인 음악 표시", y, self._config.hud.show_media, x=_col2_x, w=170
        )
        y -= _ROW
        self._battery_check = _checkbox(
            self._parent, "배터리 표시", y, self._config.hud.show_battery, w=170
        )
        self._hover_check = _checkbox(
            self._parent, "호버 시 자동 펼침", y, self._config.hud.hover_to_expand, x=_col2_x, w=170
        )
        y -= _ROW
        self._sounds_check = _checkbox(
            self._parent, "인터랙션 사운드", y, self._config.hud.interaction_sounds, w=170
        )
        y -= 18
        _lbl(self._parent, "노치를 클릭해 고정하면 표시되는 패널의 위젯입니다.",
             y, small=True)

        y -= _ROW + 8
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

        self._status_lbl = _lbl(self._parent, "", y, w=260)
        self._status_lbl.setFrame_(
            AppKit.NSMakeRect(_CTRL_X + 80, y + 2, 260, 18)
        )

    def save_(self, _sender):
        self._config.activation.wake_word = self._wake_check.state() == 1
        self._config.activation.wake_phrase = self._wake_field.stringValue()
        self._config.activation.hotkey = self._hotkey_check.state() == 1
        self._config.activation.hotkey_binding = self._hotkey_field.stringValue()
        self._config.safety.require_confirmation = self._safety_check.state() == 1
        self._config.hud.show_clock = self._clock_check.state() == 1
        self._config.hud.show_media = self._media_check.state() == 1
        self._config.hud.show_battery = self._battery_check.state() == 1
        self._config.hud.hover_to_expand = self._hover_check.state() == 1
        self._config.hud.interaction_sounds = self._sounds_check.state() == 1
        self._save_fn()
        self._status_lbl.setStringValue_("✅ 저장 완료")


def build_general_page(parent_view, config: Config, save_fn):
    try:
        import AppKit  # noqa: F401
        return _GeneralPageBuilder(parent_view, config, save_fn)
    except ImportError:
        return None
