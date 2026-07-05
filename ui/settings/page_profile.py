# ui/settings/page_profile.py
from memory.store import MemoryStore
from ui.settings.actions import make_action_handler, wire_action

_LBL_W = 155
_CTRL_X = 172
_CTRL_W = 360
_ROW = 30

# Canonical editable fields: (profile key, Korean label)
_FIELDS = [
    ("name", "이름:"),
    ("job", "직업:"),
    ("sleep_hours", "수면 시간:"),
    ("preferred_ide", "선호 IDE:"),
]


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


def _field(parent, value, y, w=200):
    import AppKit
    f = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(_CTRL_X, y, w, 22)
    )
    f.setStringValue_(str(value))
    parent.addSubview_(f)
    return f


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)


class _ProfilePageBuilder:
    def __init__(self, parent, db_path: str):
        self._parent = parent
        self._store = MemoryStore(db_path)
        self._fields = {}
        self._build()

    def _build(self):
        import AppKit
        y = 358
        profile = self._store.get_profile()

        _cat(self._parent, "사용자 프로필:", y)
        _lbl(self._parent, "비서가 참고하는 내 정보입니다. 대화에서 자동으로 채워지기도 합니다.",
             y, small=True)
        y -= 24
        _sep(self._parent, y)
        y -= 24

        for key, label in _FIELDS:
            _cat(self._parent, label, y)
            self._fields[key] = _field(self._parent, profile.get(key, ""), y)
            y -= _ROW

        # Auto-extracted extras beyond the canonical fields, read-only.
        extras = [(k, v) for k, v in profile.items()
                  if k not in {key for key, _ in _FIELDS}]
        if extras:
            y -= 4
            _sep(self._parent, y)
            y -= 22
            _cat(self._parent, "자동 수집:", y)
            for k, v in extras[:6]:
                _lbl(self._parent, f"{k}: {v}", y, small=True)
                y -= 20

        y -= 12
        _sep(self._parent, y)
        y -= 24

        self._save_handler = make_action_handler(self.save_)
        save_btn = AppKit.NSButton.buttonWithTitle_target_action_("저장", None, None)
        wire_action(save_btn, self._save_handler, "save:")
        save_btn.setFrame_(AppKit.NSMakeRect(_CTRL_X, y - 3, 72, 28))
        save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._parent.addSubview_(save_btn)

        self._status_lbl = _lbl(self._parent, "", y, w=260)
        self._status_lbl.setFrame_(
            AppKit.NSMakeRect(_CTRL_X + 80, y + 2, 260, 18)
        )

    def save_(self, _sender):
        for key, field in self._fields.items():
            value = str(field.stringValue()).strip()
            if value:
                self._store.set_profile(key, value, source="user")
            else:
                self._store.delete_profile(key)
        self._status_lbl.setStringValue_("✅ 저장 완료")


def build_profile_page(parent_view, db_path: str):
    try:
        import AppKit  # noqa: F401
        return _ProfilePageBuilder(parent_view, db_path)
    except ImportError:
        return None
