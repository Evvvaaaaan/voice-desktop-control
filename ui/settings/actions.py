# ui/settings/actions.py
try:
    from Foundation import NSObject
    import objc
except ImportError:  # pragma: no cover - exercised only without PyObjC
    NSObject = None
    objc = None

_ACTION_SIGNATURE = b"v@:@"


def _selector_bytes(name):
    if isinstance(name, bytes):
        return name
    return name.encode("ascii")


if NSObject is not None:
    class ActionHandler(NSObject):
        def initWithCallback_(self, callback):
            self = objc.super(ActionHandler, self).init()
            if self is None:
                return None
            self._callback = callback
            return self

        @objc.typedSelector(_ACTION_SIGNATURE)
        def click_(self, sender):
            self._callback(sender)

        @objc.typedSelector(_ACTION_SIGNATURE)
        def save_(self, sender):
            self._callback(sender)

        @objc.typedSelector(_ACTION_SIGNATURE)
        def providerChanged_(self, sender):
            self._callback(sender)

        @objc.typedSelector(_ACTION_SIGNATURE)
        def act_(self, sender):
            self._callback(sender)

        @objc.typedSelector(_ACTION_SIGNATURE)
        def selectTab_(self, sender):
            self._callback(sender)

    def action_selector(name):
        return name.decode("ascii") if isinstance(name, bytes) else name

    def make_action_handler(callback):
        return ActionHandler.alloc().initWithCallback_(callback)

else:
    class ActionHandler:
        def __init__(self, callback):
            self._callback = callback

        def click_(self, sender):
            self._callback(sender)

        def save_(self, sender):
            self._callback(sender)

        def providerChanged_(self, sender):
            self._callback(sender)

        def act_(self, sender):
            self._callback(sender)

        def selectTab_(self, sender):
            self._callback(sender)

    def action_selector(name):
        return name.decode("ascii") if isinstance(name, bytes) else name

    def make_action_handler(callback):
        return ActionHandler(callback)


def wire_action(control, target, selector_name):
    control.setTarget_(target)
    control.setAction_(action_selector(selector_name))


def open_url_in_browser(url):
    """Open `url` in the user's default browser. Best-effort — a missing
    browser or malformed URL must never crash the settings UI."""
    try:
        import AppKit
        ns_url = AppKit.NSURL.URLWithString_(url)
        if ns_url:
            AppKit.NSWorkspace.sharedWorkspace().openURL_(ns_url)
    except Exception:
        pass


def make_link_button(parent, title, url, x, y, w=78):
    """A small button that opens `url` in the browser when clicked — used
    next to API key fields so the user can jump straight to the provider's
    key page instead of hunting it down themselves.

    Returns (button, handler); the caller must keep `handler` alive as an
    instance attribute — PyObjC's setTarget_ does not retain the target, so
    a handler with no other reference gets garbage-collected and the button
    silently stops doing anything."""
    import AppKit
    btn = AppKit.NSButton.buttonWithTitle_target_action_(title, None, None)
    btn.setFrame_(AppKit.NSMakeRect(x, y, w, 22))
    btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
    btn.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
    handler = make_action_handler(lambda _sender: open_url_in_browser(url))
    wire_action(btn, handler, "act:")
    parent.addSubview_(btn)
    return btn, handler
