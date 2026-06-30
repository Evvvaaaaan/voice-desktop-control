# ui/settings/page_stt.py
from config.loader import Config


def build_stt_page(parent_view, config: Config, save_fn) -> None:
    try:
        import AppKit
        _build_provider_popup(parent_view, config, save_fn)
        _build_api_key_field(parent_view, config, save_fn)
        _build_test_button(parent_view, config)
    except ImportError:
        pass


def _build_provider_popup(parent, config, save_fn):
    import AppKit
    lbl = AppKit.NSTextField.labelWithString_("Provider:")
    lbl.setFrame_(AppKit.NSMakeRect(20, 440, 100, 22))
    parent.addSubview_(lbl)

    popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
        AppKit.NSMakeRect(140, 440, 200, 22), False
    )
    for opt in ["macos", "whisper_api", "whisper_local"]:
        popup.addItemWithTitle_(opt)
    popup.selectItemWithTitle_(config.stt.provider)
    parent.addSubview_(popup)


def _build_api_key_field(parent, config, save_fn):
    import AppKit
    lbl = AppKit.NSTextField.labelWithString_("API Key:")
    lbl.setFrame_(AppKit.NSMakeRect(20, 400, 100, 22))
    parent.addSubview_(lbl)

    field = AppKit.NSSecureTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(140, 400, 300, 22)
    )
    field.setStringValue_(config.stt.whisper_api_key)
    parent.addSubview_(field)


def _build_test_button(parent, config):
    import AppKit
    btn = AppKit.NSButton.buttonWithTitle_target_action_("Test Connection", None, None)
    btn.setFrame_(AppKit.NSMakeRect(140, 360, 150, 32))
    parent.addSubview_(btn)
