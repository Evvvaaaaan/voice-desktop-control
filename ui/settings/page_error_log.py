"""Settings page for saved VoiceDesk errors and recurring-pattern guidance."""

from datetime import datetime

from metrics.error_log import ErrorLogStore
from ui.settings.actions import make_action_handler, wire_action


_LBL_W = 155
_CTRL_X = 172
_CTRL_W = 360


def _cat(parent, text, y):
    import AppKit
    label = AppKit.NSTextField.labelWithString_(text)
    label.setFrame_(AppKit.NSMakeRect(8, y + 2, _LBL_W, 18))
    label.setAlignment_(AppKit.NSTextAlignmentRight)
    label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    label.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    parent.addSubview_(label)
    return label


def _lbl(parent, text, y, *, small=False, x=_CTRL_X, w=_CTRL_W):
    import AppKit
    label = AppKit.NSTextField.labelWithString_(text)
    label.setFrame_(AppKit.NSMakeRect(x, y + 2, w, 18))
    if small:
        label.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
        label.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
    parent.addSubview_(label)
    return label


def _sep(parent, y):
    import AppKit
    line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(0, y, 560, 1))
    line.setBoxType_(AppKit.NSBoxSeparator)
    parent.addSubview_(line)
    return line


def _short(text, limit=72):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _display_time(timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return _short(timestamp, 16).replace("T", " ")


class _ErrorLogPageBuilder:
    def __init__(self, parent_view, db_path: str):
        self._parent = parent_view
        self._store = ErrorLogStore(db_path)
        self._dynamic_views = []
        self._build()

    def _build(self):
        import AppKit

        y = 358
        _cat(self._parent, "오류 진단:", y)
        _lbl(self._parent, "반복 오류를 분류해 수정 우선순위와 확인 방법을 제안합니다.", y, small=True)
        y -= 24
        _lbl(
            self._parent,
            "오류 발생 → 저장 → 반복 패턴 분석 → 권장 조치 → 재현 검증",
            y,
            small=True,
            x=16,
            w=410,
        )
        self._refresh_handler = make_action_handler(self.refresh_)
        refresh = AppKit.NSButton.buttonWithTitle_target_action_("새로고침", None, None)
        refresh.setFrame_(AppKit.NSMakeRect(440, y - 3, 88, 24))
        refresh.setBezelStyle_(AppKit.NSBezelStyleRounded)
        refresh.setFont_(AppKit.NSFont.systemFontOfSize_(10.5))
        wire_action(refresh, self._refresh_handler, "act:")
        self._parent.addSubview_(refresh)

        y -= 22
        _sep(self._parent, y)
        self._patterns_y = y - 28

        self.refresh_(None)

    def _remove_dynamic_views(self):
        for view in self._dynamic_views:
            try:
                view.removeFromSuperview()
            except Exception:
                pass
        self._dynamic_views = []

    def _dynamic_cat(self, text, y):
        view = _cat(self._parent, text, y)
        self._dynamic_views.append(view)
        return view

    def _dynamic_lbl(self, text, y, *, small=False, x=_CTRL_X, w=_CTRL_W):
        view = _lbl(self._parent, text, y, small=small, x=x, w=w)
        self._dynamic_views.append(view)
        return view

    def _dynamic_sep(self, y):
        view = _sep(self._parent, y)
        self._dynamic_views.append(view)
        return view

    def refresh_(self, _sender):
        self._remove_dynamic_views()
        try:
            patterns = self._store.patterns(3)
            recent = self._store.recent(2)
        except Exception:
            self._dynamic_cat("로그 읽기 오류:", self._patterns_y)
            self._dynamic_lbl(
                "오류 로그를 불러오지 못했습니다. 데이터베이스 파일과 권한을 확인하세요.",
                self._patterns_y,
                small=True,
            )
            return

        y = self._patterns_y
        self._dynamic_cat("반복 패턴:", y)
        if not patterns:
            self._dynamic_lbl("저장된 오류가 없습니다.", y, small=True)
            y -= 30
        else:
            for pattern in patterns:
                self._dynamic_cat(
                    f"{pattern['category']} · {pattern['count']}회:", y
                )
                self._dynamic_lbl(
                    _short(f"{pattern['title']} · 최근 {_display_time(pattern['last_seen'])}"),
                    y,
                    small=True,
                )
                y -= 18
                self._dynamic_lbl(_short(pattern["recommendation"]), y, small=True)
                y -= 28

        self._dynamic_sep(y + 8)
        self._dynamic_cat("최근 오류 (현지 시간):", y - 12)
        if not recent:
            self._dynamic_lbl("기록이 없습니다.", y - 12, small=True)
            return
        for row in recent:
            y -= 30
            detail = row["message"] or row["title"]
            self._dynamic_lbl(
                _short(f"{_display_time(row['timestamp'])} · {detail}"),
                y,
                small=True,
                x=16,
                w=510,
            )
            y -= 16
            self._dynamic_lbl(
                f"trace: {row['trace_id']}", y, small=True, x=16, w=510
            )


def build_error_log_page(parent_view, db_path: str):
    try:
        import AppKit  # noqa: F401
        return _ErrorLogPageBuilder(parent_view, db_path)
    except ImportError:
        return None
