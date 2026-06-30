# ui/settings/page_routines.py
from config.loader import Config


def build_routines_page(parent_view, config: Config, routine_manager, save_fn) -> None:
    try:
        import AppKit
        lbl = AppKit.NSTextField.labelWithString_("Saved Routines:")
        lbl.setFrame_(AppKit.NSMakeRect(20, 460, 200, 22))
        parent_view.addSubview_(lbl)
        routines = routine_manager.load_all()
        for i, r in enumerate(routines):
            row = AppKit.NSTextField.labelWithString_(f"• {r['name']} ({len(r['steps'])} steps)")
            row.setFrame_(AppKit.NSMakeRect(40, 430 - i * 28, 400, 22))
            parent_view.addSubview_(row)
    except ImportError:
        pass
