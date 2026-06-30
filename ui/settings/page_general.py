# ui/settings/page_general.py
from config.loader import Config


class _SaveHandler:
    def __init__(self, fn):
        self._fn = fn

    def save_(self, sender):
        self._fn()


def build_general_page(parent_view, config: Config, save_fn) -> None:
    try:
        import AppKit
        _build_label(parent_view, "Wake Word:", 20, 440)
        wake_field = _build_text_field(parent_view, config.activation.wake_phrase, 140, 440)

        _build_label(parent_view, "Hotkey:", 20, 400)
        hotkey_field = _build_text_field(parent_view, config.activation.hotkey_binding, 140, 400)

        _build_label(parent_view, "TTS Voice:", 20, 360)
        voice_field = _build_text_field(parent_view, config.tts.voice, 140, 360)

        def on_save():
            config.activation.wake_phrase = wake_field.stringValue()
            config.activation.hotkey_binding = hotkey_field.stringValue()
            config.tts.voice = voice_field.stringValue()
            save_fn()

        save_handler = _SaveHandler(on_save)
        save_btn = AppKit.NSButton.buttonWithTitle_target_action_("Save", save_handler, "save:")
        save_btn.setFrame_(AppKit.NSMakeRect(550, 20, 100, 32))
        parent_view.addSubview_(save_btn)
    except ImportError:
        pass


def _build_label(parent, text, x, y):
    import AppKit
    lbl = AppKit.NSTextField.labelWithString_(text)
    lbl.setFrame_(AppKit.NSMakeRect(x, y, 120, 22))
    parent.addSubview_(lbl)
    return lbl


def _build_text_field(parent, value, x, y):
    import AppKit
    field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, 200, 22))
    field.setStringValue_(value)
    parent.addSubview_(field)
    return field
