# ui/settings/page_about.py
VERSION = "0.1.0"

_LBL_W = 155
_CTRL_X = 172
_CTRL_W = 360


def _cat(parent, text, y):
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(8, y + 2, _LBL_W, 18))
    t.setAlignment_(AppKit.NSTextAlignmentRight)
    t.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    t.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    parent.addSubview_(t)
    return t


def _lbl(parent, text, y, *, small=False, bold=False, w=None):
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, w or _CTRL_W, 18))
    if bold:
        t.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
    if small:
        t.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
        t.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
    parent.addSubview_(t)
    return t


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)


def build_about_page(parent_view) -> None:
    try:
        import AppKit  # noqa: F401
    except ImportError:
        return

    y = 340

    _cat(parent_view, "앱:", y)
    _lbl(parent_view, f"VoiceDesk  v{VERSION}", y, bold=True)
    y -= 28

    _cat(parent_view, "설명:", y)
    _lbl(parent_view, "macOS 음성 제어 AI 에이전트", y)
    y -= 28

    _sep(parent_view, y); y -= 18

    _cat(parent_view, "라이선스:", y)
    _lbl(parent_view, "MIT License", y)
    y -= 28

    _cat(parent_view, "소스코드:", y)
    _lbl(parent_view, "github.com/your-org/voicedesk", y, small=True)
    y -= 28

    _sep(parent_view, y); y -= 18

    _cat(parent_view, "환경:", y)
    import sys
    _lbl(parent_view, f"Python {sys.version.split()[0]}", y, small=True)
    y -= 22
    import platform
    _lbl(parent_view, f"macOS {platform.mac_ver()[0]}", y, small=True)
