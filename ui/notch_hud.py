# ui/notch_hud.py
import threading
from ui.animations import STATE_COLORS, STATE_LABELS


class NotchHUD:
    def __init__(self):
        self._state = "idle"
        self._metrics: dict = {}
        self._window = None
        self._label_view = None
        self._initialized = False

    def _ensure_init(self):
        if self._initialized:
            return
        try:
            import AppKit
            import Quartz

            screen = AppKit.NSScreen.mainScreen()
            screen_frame = screen.frame()
            notch_w, notch_h = 126, 36
            x = (screen_frame.size.width - notch_w) / 2
            y = screen_frame.size.height - notch_h

            self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                AppKit.NSMakeRect(x, y, notch_w, notch_h),
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            self._window.setLevel_(AppKit.NSFloatingWindowLevel + 1)
            self._window.setOpaque_(False)
            self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
            self._window.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
            )

            self._label_view = AppKit.NSTextField.labelWithString_("")
            self._label_view.setFrame_(AppKit.NSMakeRect(0, 0, notch_w, notch_h))
            self._label_view.setAlignment_(AppKit.NSTextAlignmentCenter)
            self._label_view.setTextColor_(AppKit.NSColor.whiteColor())
            self._window.contentView().addSubview_(self._label_view)
            self._initialized = True
        except ImportError:
            pass

    def set_state(self, state: str) -> None:
        self._state = state
        self._ensure_init()
        try:
            import AppKit
            label = STATE_LABELS.get(state, "")
            r, g, b, a = STATE_COLORS.get(state, (0.1, 0.1, 0.1, 0.6))
            self._window.setBackgroundColor_(
                AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
            )
            self._label_view.setStringValue_(label)
        except Exception:
            pass

    def update_metrics(self, metrics: dict) -> None:
        self._metrics = metrics

    def show(self) -> None:
        self._ensure_init()
        try:
            self._window.orderFront_(None)
        except Exception:
            pass

    def hide(self) -> None:
        try:
            self._window.orderOut_(None)
        except Exception:
            pass
