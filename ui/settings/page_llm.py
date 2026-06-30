# ui/settings/page_llm.py
from config.loader import Config

CLAUDE_MODELS = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"]
OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini"]


def build_llm_page(parent_view, config: Config, save_fn) -> None:
    try:
        import AppKit
        lbl = AppKit.NSTextField.labelWithString_("Provider:")
        lbl.setFrame_(AppKit.NSMakeRect(20, 440, 100, 22))
        parent_view.addSubview_(lbl)

        popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            AppKit.NSMakeRect(140, 440, 200, 22), False
        )
        for opt in ["ollama", "claude", "openai"]:
            popup.addItemWithTitle_(opt)
        popup.selectItemWithTitle_(config.llm.provider)
        parent_view.addSubview_(popup)

        lbl2 = AppKit.NSTextField.labelWithString_("API Key:")
        lbl2.setFrame_(AppKit.NSMakeRect(20, 400, 100, 22))
        parent_view.addSubview_(lbl2)

        key_field = AppKit.NSSecureTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(140, 400, 300, 22)
        )
        key_val = config.llm.claude_api_key if config.llm.provider == "claude" else config.llm.openai_api_key
        key_field.setStringValue_(key_val)
        parent_view.addSubview_(key_field)

        lbl3 = AppKit.NSTextField.labelWithString_("Model:")
        lbl3.setFrame_(AppKit.NSMakeRect(20, 360, 100, 22))
        parent_view.addSubview_(lbl3)

        if config.llm.provider == "ollama":
            model_field = AppKit.NSTextField.alloc().initWithFrame_(
                AppKit.NSMakeRect(140, 360, 220, 22)
            )
            model_field.setStringValue_(config.llm.ollama_model)
            parent_view.addSubview_(model_field)
        else:
            model_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                AppKit.NSMakeRect(140, 360, 220, 22), False
            )
            models = CLAUDE_MODELS if config.llm.provider == "claude" else OPENAI_MODELS
            for m in models:
                model_popup.addItemWithTitle_(m)
            parent_view.addSubview_(model_popup)

        test_btn = AppKit.NSButton.buttonWithTitle_target_action_("Test Connection", None, None)
        test_btn.setFrame_(AppKit.NSMakeRect(140, 320, 150, 32))
        parent_view.addSubview_(test_btn)
    except ImportError:
        pass
