# ui/settings/page_tts.py
from config.loader import Config
from ui.settings.actions import make_action_handler, wire_action, make_link_button

NVIDIA_TTS_KEY_URL = "https://build.nvidia.com/resembleai/chatterbox-multilingual-tts"

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


def _field(parent, value, y, w=280):
    import AppKit
    f = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22)
    )
    f.setStringValue_(str(value))
    parent.addSubview_(f)
    return f


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


class _TTSPageBuilder:
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
            self._parent, ["macos", "nvidia"],
            self._config.tts.provider, y
        )
        self._provider_handler = make_action_handler(self.providerChanged_)
        wire_action(self._popup, self._provider_handler, "providerChanged:")
        y -= _ROW

        self._info_lbl = _lbl(self._parent, "", y, small=True)
        y -= 20
        _sep(self._parent, y)
        y -= 18

        y1 = y
        y2 = y - _ROW
        y3 = y - _ROW * 2 - 4
        y4 = y - _ROW * 3 - 4

        # macOS `say`
        self._macos_views = []
        v = _cat(self._parent, "음성:", y1); self._macos_views.append(v)
        self._voice_field = _field(self._parent, self._config.tts.voice, y1, w=200)
        self._macos_views.append(self._voice_field)
        v = _cat(self._parent, "속도:", y2); self._macos_views.append(v)
        self._rate_field = _field(self._parent, str(self._config.tts.rate), y2, w=80)
        self._macos_views.append(self._rate_field)
        v = _lbl(self._parent, "로컬 실행 — 무료·오프라인·즉시 재생", y3, small=True)
        self._macos_views.append(v)

        # NVIDIA Riva TTS (Chatterbox Multilingual)
        self._nvidia_views = []
        v = _cat(self._parent, "API 키:", y1); self._nvidia_views.append(v)
        self._nvidia_key = _secure_field(self._parent, self._config.tts.nvidia_api_key, y1)
        self._nvidia_views.append(self._nvidia_key)
        v, self._nvidia_key_link_handler = make_link_button(
            self._parent, "발급받기", NVIDIA_TTS_KEY_URL, _CTRL_X + 306, y1)
        self._nvidia_views.append(v)
        v = _cat(self._parent, "Function ID:", y2); self._nvidia_views.append(v)
        self._nvidia_function_id = _field(self._parent, self._config.tts.nvidia_function_id, y2, w=280)
        self._nvidia_views.append(self._nvidia_function_id)
        v, self._nvidia_fid_link_handler = make_link_button(
            self._parent, "Deploy 탭", NVIDIA_TTS_KEY_URL, _CTRL_X + 286, y2)
        self._nvidia_views.append(v)
        v = _cat(self._parent, "음성:", y3); self._nvidia_views.append(v)
        self._nvidia_voice = _field(self._parent, self._config.tts.nvidia_voice, y3, w=280)
        self._nvidia_views.append(self._nvidia_voice)
        v = _lbl(
            self._parent,
            "NVIDIA NIM (무료) — build.nvidia.com에서 API 키와 Function ID 발급. "
            "매 발화마다 네트워크 필요 — 실패 시 자동으로 로컬 음성으로 전환됩니다.",
            y4, small=True,
        )
        self._nvidia_views.append(v)

        # ── 저장 ───────────────────────────────────────────────────────────────
        y_save = y4 - 22
        _sep(self._parent, y_save)
        y_save -= 18

        _cat(self._parent, "기타:", y_save)
        self._save_handler = make_action_handler(self.save_)
        save_btn = AppKit.NSButton.buttonWithTitle_target_action_(
            "저장", None, None
        )
        wire_action(save_btn, self._save_handler, "save:")
        save_btn.setFrame_(AppKit.NSMakeRect(_CTRL_X, y_save - 3, 72, 28))
        save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._parent.addSubview_(save_btn)

        self._status_lbl = AppKit.NSTextField.labelWithString_("")
        self._status_lbl.setFrame_(AppKit.NSMakeRect(_CTRL_X + 80, y_save + 2, 260, 18))
        self._parent.addSubview_(self._status_lbl)

        self._update_visibility(self._config.tts.provider)

    def _update_visibility(self, provider):
        _notes = {
            "macos":  "로컬 실행 — 인터넷 없이 즉시 사용 가능",
            "nvidia": "NVIDIA NIM Riva TTS (무료) — 즉시 적용, 매 발화마다 네트워크 필요",
        }
        self._info_lbl.setStringValue_(_notes.get(provider, ""))

        for v in self._macos_views:
            v.setHidden_(provider != "macos")
        for v in self._nvidia_views:
            v.setHidden_(provider != "nvidia")

    def providerChanged_(self, sender):
        self._update_visibility(sender.selectedItem().title())

    def save_(self, _sender):
        provider = self._popup.selectedItem().title()
        self._config.tts.provider = provider
        self._config.tts.voice = self._voice_field.stringValue()
        try:
            self._config.tts.rate = int(self._rate_field.stringValue())
        except ValueError:
            pass
        self._config.tts.nvidia_api_key = self._nvidia_key.stringValue()
        self._config.tts.nvidia_function_id = self._nvidia_function_id.stringValue()
        self._config.tts.nvidia_voice = self._nvidia_voice.stringValue()
        self._save_fn()
        # TTS reads its config live on every speak() call (unlike the LLM
        # adapter, which is a constructed object swapped in on config change),
        # so no restart is needed for any provider here.
        self._status_lbl.setStringValue_("✅ 저장 완료 — 즉시 적용")


def build_tts_page(parent_view, config: Config, save_fn):
    try:
        import AppKit  # noqa: F401
        return _TTSPageBuilder(parent_view, config, save_fn)
    except ImportError:
        return None
