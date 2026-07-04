# ui/settings/page_llm.py
from config.loader import Config
from ui.settings.actions import make_action_handler, wire_action

CLAUDE_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"]
OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini"]

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


class _LLMPageBuilder:
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
            self._parent, ["ollama", "claude", "openai", "nvidia"],
            self._config.llm.provider, y
        )
        self._provider_handler = make_action_handler(self.providerChanged_)
        wire_action(self._popup, self._provider_handler, "providerChanged:")
        y -= _ROW

        self._info_lbl = _lbl(self._parent, "", y, small=True)
        y -= 20
        _sep(self._parent, y)
        y -= 18

        # ── Three provider sections, all at the same y-range (hide/show) ──────
        # Row 1: API key / Ollama URL  (all at same y)
        y1 = y       # first data row
        y2 = y - _ROW   # second data row
        y3 = y - _ROW * 2 - 4  # note row

        # Ollama
        self._ollama_views = []
        v = _cat(self._parent, "Ollama URL:", y1); self._ollama_views.append(v)
        self._ollama_url = _field(self._parent, self._config.llm.ollama_url, y1)
        self._ollama_views.append(self._ollama_url)
        v = _cat(self._parent, "모델:", y2); self._ollama_views.append(v)
        self._ollama_model = _field(self._parent, self._config.llm.ollama_model, y2, w=200)
        self._ollama_views.append(self._ollama_model)
        v = _lbl(self._parent, "로컬 실행 — ollama serve 가 실행 중이어야 합니다 (brew install ollama)", y3, small=True)
        self._ollama_views.append(v)

        # Claude (same y positions)
        self._claude_views = []
        v = _cat(self._parent, "API 키:", y1); self._claude_views.append(v)
        self._claude_key = _secure_field(self._parent, self._config.llm.claude_api_key, y1)
        self._claude_views.append(self._claude_key)
        v = _cat(self._parent, "모델:", y2); self._claude_views.append(v)
        self._claude_model = _popup(self._parent, CLAUDE_MODELS, self._config.llm.claude_model, y2, w=300)
        self._claude_views.append(self._claude_model)
        v = _lbl(self._parent, "Anthropic Claude API — console.anthropic.com에서 API 키 발급 | 저장 후 재시작", y3, small=True)
        self._claude_views.append(v)

        # OpenAI (same y positions)
        self._openai_views = []
        v = _cat(self._parent, "API 키:", y1); self._openai_views.append(v)
        self._openai_key = _secure_field(self._parent, self._config.llm.openai_api_key, y1)
        self._openai_views.append(self._openai_key)
        v = _cat(self._parent, "모델:", y2); self._openai_views.append(v)
        self._openai_model = _popup(self._parent, OPENAI_MODELS, self._config.llm.openai_model, y2, w=200)
        self._openai_views.append(self._openai_model)
        v = _lbl(self._parent, "OpenAI GPT API — platform.openai.com에서 API 키 발급 | 저장 후 재시작", y3, small=True)
        self._openai_views.append(v)

        # NVIDIA NIM (same y positions)
        self._nvidia_views = []
        v = _cat(self._parent, "API 키:", y1); self._nvidia_views.append(v)
        self._nvidia_key = _secure_field(self._parent, self._config.llm.nvidia_api_key, y1)
        self._nvidia_views.append(self._nvidia_key)
        v = _cat(self._parent, "모델:", y2); self._nvidia_views.append(v)
        self._nvidia_model = _field(self._parent, self._config.llm.nvidia_model, y2, w=280)
        self._nvidia_views.append(self._nvidia_model)
        v = _lbl(self._parent, "NVIDIA NIM (무료) — build.nvidia.com에서 API 키 발급 | 저장 후 재시작", y3, small=True)
        self._nvidia_views.append(v)

        # ── 저장 ───────────────────────────────────────────────────────────────
        y_save = y3 - 22
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

        self._update_visibility(self._config.llm.provider)

    def _update_visibility(self, provider):
        _notes = {
            "ollama":  "로컬 실행 — 인터넷 없이 사용 가능",
            "claude":  "Anthropic Claude API — 저장 후 재시작 필요",
            "openai":  "OpenAI GPT API — 저장 후 재시작 필요",
            "nvidia":  "NVIDIA NIM API (무료) — 저장 후 재시작 필요",
        }
        self._info_lbl.setStringValue_(_notes.get(provider, ""))

        for v in self._ollama_views:
            v.setHidden_(provider != "ollama")
        for v in self._claude_views:
            v.setHidden_(provider != "claude")
        for v in self._openai_views:
            v.setHidden_(provider != "openai")
        for v in self._nvidia_views:
            v.setHidden_(provider != "nvidia")

    def providerChanged_(self, sender):
        self._update_visibility(sender.selectedItem().title())

    def save_(self, _sender):
        provider = self._popup.selectedItem().title()
        self._config.llm.provider = provider
        self._config.llm.ollama_url = self._ollama_url.stringValue()
        self._config.llm.ollama_model = self._ollama_model.stringValue()
        self._config.llm.claude_api_key = self._claude_key.stringValue()
        self._config.llm.claude_model = self._claude_model.selectedItem().title()
        self._config.llm.openai_api_key = self._openai_key.stringValue()
        self._config.llm.openai_model = self._openai_model.selectedItem().title()
        self._config.llm.nvidia_api_key = self._nvidia_key.stringValue()
        self._config.llm.nvidia_model = self._nvidia_model.stringValue()
        self._save_fn()
        needs_restart = provider in ("claude", "openai", "nvidia")
        self._status_lbl.setStringValue_(
            "✅ 저장 완료 — 재시작 후 적용" if needs_restart else "✅ 저장 완료"
        )


def build_llm_page(parent_view, config: Config, save_fn):
    try:
        import AppKit  # noqa: F401
        return _LLMPageBuilder(parent_view, config, save_fn)
    except ImportError:
        return None
