# ui/settings/page_about.py
VERSION = "0.1.0"


def build_about_page(parent_view) -> None:
    try:
        import AppKit
        for i, text in enumerate([
            f"VoiceDesk v{VERSION}",
            "macOS Voice-Controlled AI Agent",
            "MIT License",
            "github.com/your-org/voicedesk",
        ]):
            lbl = AppKit.NSTextField.labelWithString_(text)
            lbl.setFrame_(AppKit.NSMakeRect(20, 440 - i * 36, 400, 22))
            parent_view.addSubview_(lbl)
    except ImportError:
        pass
