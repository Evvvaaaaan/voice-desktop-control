# ui/settings/page_permissions.py
import subprocess

from ui.settings.actions import make_action_handler, wire_action

_LBL_W = 155
_CTRL_X = 172
_CTRL_W = 360
_ROW = 28
_PRIVACY_EXTENSION_ID = "com.apple.settings.PrivacySecurity.extension"
_LEGACY_SECURITY_PANE_ID = "com.apple.preference.security"
_SYSTEM_SETTINGS_BUNDLE_ID = "com.apple.systempreferences"


def _mic_status():
    try:
        import AVFoundation
        return int(AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_("soun"))
    except Exception:
        return -1


def _accessibility_granted():
    """AXIsProcessTrusted is the authoritative check for what pyautogui needs.

    (An event-tap fallback was removed: listen-only key taps succeed with the
    Input Monitoring permission alone, showing a false '허용됨' while event
    POSTING — what click/type_text actually do — stays blocked.)
    """
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        pass
    try:
        import ctypes
        lib = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        return False


def _screen_recording_granted():
    try:
        import Quartz
        if bool(Quartz.CGPreflightScreenCaptureAccess()):
            return True
        # Fallback cross-check: try capturing a tiny 1x1 image.
        # On some macOS versions (Sonoma/Sequoia), preflight APIs can return False due to TCC bugs,
        # but the actual capture succeeds if permission is active.
        rect = Quartz.CGRectMake(0, 0, 1, 1)
        img = Quartz.CGWindowListCreateImage(
            rect,
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
            Quartz.kCGWindowImageDefault
        )
        return img is not None
    except Exception:
        return False


def _pref_urls(pref_key):
    return [
        f"x-apple.systempreferences:{_PRIVACY_EXTENSION_ID}?{pref_key}",
        f"x-apple.systempreferences:{_LEGACY_SECURITY_PANE_ID}?{pref_key}",
        f"x-apple.systempreferences:{_PRIVACY_EXTENSION_ID}",
        f"x-apple.systempreferences:{_LEGACY_SECURITY_PANE_ID}",
    ]


def _open_url(url):
    try:
        import AppKit
        ns_url = AppKit.NSURL.URLWithString_(url)
        if ns_url and AppKit.NSWorkspace.sharedWorkspace().openURL_(ns_url):
            return True
    except Exception:
        pass

    for command in (
        ["open", "-b", _SYSTEM_SETTINGS_BUNDLE_ID, url],
        ["open", url],
    ):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue

    return False


def _open_prefs_applescript(pref_key):
    # Ventura+ AppleScript method to open specific privacy anchors
    script = f'''
    tell application "System Settings"
        activate
        try
            reveal anchor "{pref_key}" of pane id "{_PRIVACY_EXTENSION_ID}"
        on error
            reveal pane id "{_PRIVACY_EXTENSION_ID}"
        end try
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def _open_prefs(pref_key):
    # URL scheme first: it needs no Automation permission, unlike the
    # AppleScript path, which otherwise fires a confusing extra prompt.
    for url in _pref_urls(pref_key):
        if _open_url(url):
            return True

    if _open_prefs_applescript(pref_key):
        return True

    print(f"[Settings] Failed to open System Settings privacy pane: {pref_key}")
    return False


def _request_mic_access():
    try:
        import AVFoundation
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            "soun", lambda granted: None
        )
        return True
    except Exception:
        return False


def _request_accessibility_access():
    """Show the system Accessibility prompt and register this app in the list.

    AXIsProcessTrustedWithOptions(prompt=True) is the only API that both asks
    AND adds the process to 설정 → 손쉬운 사용 so the user just flips the
    toggle. (The previous AppleScript/System Events call prompted the wrong
    permission — Automation, not Accessibility.)
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        return True
    except Exception:
        return False


def _request_screen_recording_access():
    try:
        import Quartz
        # CGRequestScreenCaptureAccess naturally prompts screen recording permission
        return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception:
        # Fallback: Trigger TCC popup by capturing a 1x1 image of the screen
        try:
            rect = Quartz.CGRectMake(0, 0, 1, 1)
            Quartz.CGWindowListCreateImage(
                rect,
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
                Quartz.kCGWindowImageDefault
            )
            return True
        except Exception:
            return False


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


def _status_badge(parent, ok, y):
    import AppKit
    text = "✅ 허용됨" if ok else "❌ 미허용"
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, 100, 18))
    parent.addSubview_(t)
    return t


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)


class _PermissionsPageBuilder:
    """Builder that owns ObjC action-handler references so they survive GC.

    Monitors app-activation events to auto-refresh permission badges when
    the user returns from System Settings.
    """

    def __init__(self, parent_view):
        self._handlers = []
        self._parent_view = parent_view
        self._mic_badge = None
        self._acc_badge = None
        self._scr_badge = None
        self._observer = None
        self._build(parent_view)
        self._register_activation_observer()

    # ── public ------------------------------------------------------------

    def refresh(self, _notification=None):
        """Re-check all permissions and update badge labels in-place."""
        self._update_badge(self._mic_badge, _mic_status() == 3)
        self._update_badge(self._acc_badge, _accessibility_granted())
        self._update_badge(self._scr_badge, _screen_recording_granted())

    def teardown(self):
        """Remove the activation observer (called when the page is destroyed)."""
        if self._observer is not None:
            try:
                import AppKit
                AppKit.NSWorkspace.sharedWorkspace().notificationCenter() \
                    .removeObserver_(self._observer)
            except Exception:
                pass
            self._observer = None

    # ── private -----------------------------------------------------------

    @staticmethod
    def _update_badge(badge, ok):
        if badge is None:
            return
        text = "✅ 허용됨" if ok else "❌ 미허용"
        try:
            badge.setStringValue_(text)
        except Exception:
            pass

    def _register_activation_observer(self):
        """Watch for app-became-active so we can refresh badges automatically."""
        try:
            import AppKit
            import objc

            # Create a tiny helper that the notification center can call
            class _ActivationObserver(AppKit.NSObject):
                _refresh_fn = None

                @objc.typedSelector(b"v@:@")
                def appDidActivate_(self, notification):
                    if self._refresh_fn is not None:
                        self._refresh_fn()

            obs = _ActivationObserver.alloc().init()
            obs._refresh_fn = self.refresh

            AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
                obs,
                "appDidActivate:",
                AppKit.NSWorkspaceDidActivateApplicationNotification,
                None,
            )
            self._observer = obs
        except Exception:
            pass

    def _build(self, parent_view):
        import AppKit

        y = 350

        # ── 마이크 ──────────────────────────────────────────────────────────
        mic = _mic_status()
        mic_ok = mic == 3
        _cat(parent_view, "🎤  마이크:", y)
        self._mic_badge = _status_badge(parent_view, mic_ok, y)

        if mic == 0:
            _lbl(parent_view, "아래 버튼을 누르면 권한 요청 대화상자가 나타납니다.",
                 y - 16, small=True, w=_CTRL_W - 110)
            btn_title = "권한 요청"
        elif mic == 2:
            _lbl(parent_view, "시스템 설정에서 직접 허용해 주세요.",
                 y - 16, small=True, w=_CTRL_W - 110)
            btn_title = "시스템 설정 열기"
        elif not mic_ok:
            btn_title = "시스템 설정 열기"
        else:
            btn_title = "시스템 설정 열기"

        def open_mic():
            if _mic_status() == 0:
                _request_mic_access()
            _open_prefs("Privacy_Microphone")

        h1 = make_action_handler(lambda _sender: open_mic())
        self._handlers.append(h1)
        b1 = AppKit.NSButton.buttonWithTitle_target_action_(btn_title, None, None)
        wire_action(b1, h1, "act:")
        b1.setFrame_(AppKit.NSMakeRect(_CTRL_X + 108, y - 2, 150, 26))
        b1.setBezelStyle_(AppKit.NSBezelStyleRounded)
        parent_view.addSubview_(b1)

        y -= 52
        _sep(parent_view, y); y -= 18

        # ── 손쉬운 사용 ──────────────────────────────────────────────────────
        acc = _accessibility_granted()
        _cat(parent_view, "♿  손쉬운 사용:", y)
        self._acc_badge = _status_badge(parent_view, acc, y)

        _lbl(parent_view, "클릭·키보드 자동화에 필요합니다.",
             y - 16, small=True, w=_CTRL_W - 110)

        def open_acc():
            if not _accessibility_granted():
                _request_accessibility_access()
            _open_prefs("Privacy_Accessibility")

        h2 = make_action_handler(lambda _sender: open_acc())
        self._handlers.append(h2)
        b2 = AppKit.NSButton.buttonWithTitle_target_action_("시스템 설정 열기", None, None)
        wire_action(b2, h2, "act:")
        b2.setFrame_(AppKit.NSMakeRect(_CTRL_X + 108, y - 2, 150, 26))
        b2.setBezelStyle_(AppKit.NSBezelStyleRounded)
        parent_view.addSubview_(b2)

        y -= 52
        _sep(parent_view, y); y -= 18

        # ── 화면 녹화 ─────────────────────────────────────────────────────────
        scr = _screen_recording_granted()
        _cat(parent_view, "🖥️  화면 녹화:", y)
        self._scr_badge = _status_badge(parent_view, scr, y)

        _lbl(parent_view, "화면 캡처 기반 동작 확인에 필요합니다.",
             y - 16, small=True, w=_CTRL_W - 110)

        def open_scr():
            if not _screen_recording_granted():
                _request_screen_recording_access()
            _open_prefs("Privacy_ScreenCapture")

        h3 = make_action_handler(lambda _sender: open_scr())
        self._handlers.append(h3)
        b3 = AppKit.NSButton.buttonWithTitle_target_action_("시스템 설정 열기", None, None)
        wire_action(b3, h3, "act:")
        b3.setFrame_(AppKit.NSMakeRect(_CTRL_X + 108, y - 2, 150, 26))
        b3.setBezelStyle_(AppKit.NSBezelStyleRounded)
        parent_view.addSubview_(b3)

        y -= 52
        _sep(parent_view, y); y -= 14

        # ── 새로고침 + 안내 ──────────────────────────────────────────────────
        _cat(parent_view, "상태:", y)

        h_refresh = make_action_handler(lambda _sender: self.refresh())
        self._handlers.append(h_refresh)
        refresh_btn = AppKit.NSButton.buttonWithTitle_target_action_(
            "🔄 상태 새로고침", None, None
        )
        wire_action(refresh_btn, h_refresh, "act:")
        refresh_btn.setFrame_(AppKit.NSMakeRect(_CTRL_X, y - 2, 140, 26))
        refresh_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        parent_view.addSubview_(refresh_btn)

        _lbl(parent_view, "앱으로 돌아오면 자동 갱신됩니다.",
             y - 20, small=True)


def build_permissions_page(parent_view):
    try:
        import AppKit  # noqa: F401
        return _PermissionsPageBuilder(parent_view)
    except ImportError:
        return None
