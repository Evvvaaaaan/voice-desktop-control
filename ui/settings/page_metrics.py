# ui/settings/page_metrics.py
from metrics.aggregator import get_today_summary


def build_metrics_page(parent_view, db_path: str) -> None:
    try:
        import AppKit
        summary = get_today_summary(db_path)
        labels = [
            f"Recognition Rate: {summary['recognition_rate']*100:.1f}%",
            f"Success Rate: {summary['success_rate']*100:.1f}%",
            f"Avg Retries: {summary['avg_retry']}",
            f"Dangerous Actions: {summary['dangerous_count']}",
            f"Avg Response: {summary['avg_response_ms']}ms",
            f"Repeated Commands: {summary['repeated_count']}",
        ]
        for i, text in enumerate(labels):
            lbl = AppKit.NSTextField.labelWithString_(text)
            lbl.setFrame_(AppKit.NSMakeRect(20, 440 - i * 36, 400, 22))
            parent_view.addSubview_(lbl)
    except ImportError:
        pass
