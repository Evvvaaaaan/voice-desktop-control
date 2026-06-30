import sqlite3
from datetime import datetime, timezone


def get_today_summary(db_path: str = "data/command_history.db") -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events WHERE timestamp LIKE ?", (f"{today}%",)
        ).fetchall()

    if not rows:
        return {
            "recognition_rate": 0.0, "success_rate": 0.0,
            "avg_retry": 0.0, "dangerous_count": 0,
            "avg_response_ms": 0, "repeated_count": 0,
        }

    total = len(rows)
    high_conf = sum(1 for r in rows if r["stt_confidence"] >= 0.7)
    successes = sum(1 for r in rows if r["success"])
    return {
        "recognition_rate": round(high_conf / total, 4),
        "success_rate": round(successes / total, 4),
        "avg_retry": round(sum(r["retry_count"] for r in rows) / total, 2),
        "dangerous_count": sum(r["dangerous"] for r in rows),
        "avg_response_ms": round(sum(r["response_ms"] for r in rows) / total),
        "repeated_count": sum(r["is_repeated"] for r in rows),
    }
