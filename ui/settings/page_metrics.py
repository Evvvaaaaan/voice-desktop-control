# ui/settings/page_metrics.py
from metrics.aggregator import get_today_summary

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


def build_metrics_page(parent_view, db_path: str) -> None:
    try:
        import AppKit  # noqa: F401
    except ImportError:
        return

    y = 358

    try:
        summary = get_today_summary(db_path)
    except Exception:
        _cat(parent_view, "오류:", y)
        _lbl(parent_view, "메트릭 데이터를 불러올 수 없습니다.", y, small=True)
        return

    rows = [
        ("인식률:",       f"{summary['recognition_rate'] * 100:.1f}%"),
        ("성공률:",       f"{summary['success_rate'] * 100:.1f}%"),
        ("평균 재시도:",  str(summary['avg_retry'])),
        ("위험 작업:",    str(summary['dangerous_count'])),
        ("평균 응답:",    f"{summary['avg_response_ms']} ms"),
        ("반복 명령:",    str(summary['repeated_count'])),
    ]

    _cat(parent_view, "오늘 요약:", y)
    _lbl(parent_view, "오늘의 VoiceDesk 사용 통계입니다.", y, small=True)
    y -= 24
    _sep(parent_view, y); y -= 18

    for label, value in rows:
        _cat(parent_view, label, y)
        _lbl(parent_view, value, y)
        y -= 28
