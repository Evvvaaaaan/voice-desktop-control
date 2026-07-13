# ui/settings/page_stt.py
from config.loader import Config
from ui.settings.actions import make_action_handler, wire_action, make_link_button

WHISPER_API_KEY_URL = "https://platform.openai.com/api-keys"

WHISPER_MODELS = ["tiny", "base", "small", "medium"]

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


def _popup(parent, items, current, y, w=220):
    import AppKit
    p = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22), False
    )
    for item in items:
        p.addItemWithTitle_(item)
    if current in items:
        p.selectItemWithTitle_(current)
    parent.addSubview_(p)
    return p


def _secure_field(parent, value, y, w=300):
    import AppKit
    f = AppKit.NSSecureTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22)
    )
    f.setStringValue_(value)
    parent.addSubview_(f)
    return f


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)
    return line


class _STTPageBuilder:
    def __init__(self, parent, config, save_fn):
        self._parent = parent
        self._config = config
        self._save_fn = save_fn
        self._build()

    def _build(self):
        import AppKit
        y = 358

        # ── 프로바이더 ─────────────────────────────────────────────────────────
        _cat(self._parent, "프로바이더:", y)
        self._popup = _popup(
            self._parent,
            ["macos", "whisper_api", "whisper_local"],
            self._config.stt.provider, y
        )
        self._provider_handler = make_action_handler(self.providerChanged_)
        wire_action(self._popup, self._provider_handler, "providerChanged:")
        y -= _ROW

        self._info_lbl = _lbl(self._parent, "", y, small=True, w=_CTRL_W)
        y -= 20

        _sep(self._parent, y)
        y -= 18

        # ── Whisper API ────────────────────────────────────────────────────────
        self._api_cat = _cat(self._parent, "API 키:", y)
        self._api_field = _secure_field(self._parent, self._config.stt.whisper_api_key, y)
        self._api_link, self._api_link_handler = make_link_button(
            self._parent, "발급받기", WHISPER_API_KEY_URL, _CTRL_X + 306, y)
        y -= _ROW

        self._api_note = _lbl(
            self._parent,
            "OpenAI Whisper API — platform.openai.com에서 발급",
            y, small=True
        )
        y -= 20

        self._sep1 = _sep(self._parent, y)
        y -= 18

        # ── Whisper Local ──────────────────────────────────────────────────────
        self._local_cat = _cat(self._parent, "로컬 모델:", y)
        self._model_popup = _popup(
            self._parent, WHISPER_MODELS, self._config.stt.whisper_local_model, y, w=160
        )
        y -= _ROW

        self._local_note = _lbl(
            self._parent,
            "첫 실행 시 자동 다운로드 (tiny ≈ 75 MB, base ≈ 140 MB)",
            y, small=True
        )
        y -= 20

        self._sep2 = _sep(self._parent, y)
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

        self._update_visibility(self._config.stt.provider)

    def _update_visibility(self, provider):
        _notes = {
            "macos":        "시스템 내장 음성 인식 — 별도 API 키 불필요",
            "whisper_api":  "OpenAI Whisper API — 인터넷 연결 필요, 저장 후 재시작",
            "whisper_local": "로컬 실행 — 인터넷 없이 사용 가능, 저장 후 재시작",
        }
        self._info_lbl.setStringValue_(_notes.get(provider, ""))

        show_api = provider == "whisper_api"
        show_local = provider == "whisper_local"

        for v in (self._api_cat, self._api_field, self._api_link, self._api_note, self._sep1):
            v.setHidden_(not show_api)
        for v in (self._local_cat, self._model_popup, self._local_note, self._sep2):
            v.setHidden_(not show_local)

    def providerChanged_(self, sender):
        self._update_visibility(sender.selectedItem().title())

    def save_(self, _sender):
        provider = self._popup.selectedItem().title()
        self._config.stt.provider = provider
        self._config.stt.whisper_api_key = self._api_field.stringValue()
        self._config.stt.whisper_local_model = self._model_popup.selectedItem().title()
        self._save_fn()
        self._status_lbl.setStringValue_("✅ 저장 완료 (즉시 적용)")


def build_stt_page(parent_view, config: Config, save_fn):
    try:
        import AppKit  # noqa: F401
        return _STTPageBuilder(parent_view, config, save_fn)
    except ImportError:
        return None
