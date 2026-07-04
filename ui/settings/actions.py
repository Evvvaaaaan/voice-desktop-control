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
