"""Standard macOS edit menu support for settings text fields."""


def _command_mask(AppKit):
    return getattr(AppKit, "NSEventModifierFlagCommand", getattr(AppKit, "NSCommandKeyMask", 0))


def _shift_mask(AppKit):
    return getattr(AppKit, "NSEventModifierFlagShift", getattr(AppKit, "NSShiftKeyMask", 0))


def _item_with_title(menu, title):
    try:
        return menu.itemWithTitle_(title)
    except Exception:
        return None


def _ensure_menu_item(AppKit, menu, title, action, key, modifier_mask):
    item = _item_with_title(menu, title)
    if item is not None:
        return item

    item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        title, action, key
    )
    item.setTarget_(None)  # Send cut/copy/paste/selectAll up the responder chain.
    if modifier_mask:
        item.setKeyEquivalentModifierMask_(modifier_mask)
    menu.addItem_(item)
    return item


def _current_app(AppKit):
    ns_app = getattr(AppKit, "NSApp", None)
    if ns_app is None:
        return None
    if callable(ns_app):
        return ns_app()
    return ns_app


def ensure_standard_edit_menu() -> None:
    """Install Edit menu key equivalents so NSTextField Cmd+V works.

    Status-bar apps often do not have a normal main menu. Without an Edit menu,
    AppKit may not route Command-X/C/V/A to the active NSTextField field editor.
    """
    try:
        import AppKit

        app = _current_app(AppKit)
        if app is None:
            return

        main_menu = app.mainMenu()
        if main_menu is None:
            main_menu = AppKit.NSMenu.alloc().init()
            app.setMainMenu_(main_menu)

        edit_item = _item_with_title(main_menu, "Edit")
        if edit_item is None:
            edit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Edit", None, ""
            )
            main_menu.addItem_(edit_item)

        edit_menu = edit_item.submenu()
        if edit_menu is None:
            edit_menu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
            edit_item.setSubmenu_(edit_menu)

        command = _command_mask(AppKit)
        command_shift = command | _shift_mask(AppKit)
        for title, action, key, mask in (
            ("Undo", "undo:", "z", command),
            ("Redo", "redo:", "Z", command_shift),
            ("Cut", "cut:", "x", command),
            ("Copy", "copy:", "c", command),
            ("Paste", "paste:", "v", command),
            ("Select All", "selectAll:", "a", command),
        ):
            _ensure_menu_item(AppKit, edit_menu, title, action, key, mask)
    except Exception:
        # Menu setup must never prevent the settings window from opening.
        return
