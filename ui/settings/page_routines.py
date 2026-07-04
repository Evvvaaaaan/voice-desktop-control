# ui/settings/page_routines.py
from config.loader import Config

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


def _lbl(parent, text, y, *, small=False, w=None):
    import AppKit
    t = AppKit.NSTextField.labelWithString_(text)
    t.setFrame_(AppKit.NSMakeRect(_CTRL_X, y + 2, w or _CTRL_W, 18))
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


def build_routines_page(parent_view, config: Config, routine_manager, save_fn) -> None:
    try:
        import AppKit  # noqa: F401
    except ImportError:
        return

    y = 358
    routines = []
    try:
        routines = routine_manager.load_all()
    except Exception:
        pass

    _cat(parent_view, "저장된 루틴:", y)
    if not routines:
        _lbl(parent_view, "저장된 루틴이 없습니다.", y, small=True)
        return

    for i, r in enumerate(routines):
        if i > 0:
            y -= 4
            _sep(parent_view, y)
            y -= 8

        steps = len(r.get("steps", []))
        _cat(parent_view, f"{r.get('name', '?')}:", y)
        _lbl(parent_view, f"{steps}단계", y, small=True)
        y -= 28
