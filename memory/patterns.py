import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from memory.store import MemoryStore


def compute_patterns(store: MemoryStore, days: int = 30) -> dict:
    """Tier-5 aggregates over the last `days` of behavior_log.

    Returns {} when there is no data; never raises on a missing/empty DB.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with store._conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, event_type, command, action, target "
                "FROM behavior_log WHERE timestamp >= ?",
                (since,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    if not rows:
        return {}

    app_counts: Counter = Counter()
    hour_counts: Counter = Counter()
    command_counts: Counter = Counter()
    weekday_counts: Counter = Counter()
    command_days: set[str] = set()

    for ts, event_type, command, action, target in rows:
        local = datetime.fromisoformat(ts).astimezone()
        if event_type == "command":
            hour_counts[str(local.hour)] += 1
            command_counts[command] += 1
            weekday_counts[local.strftime("%a")] += 1
            command_days.add(local.strftime("%Y-%m-%d"))
        elif action == "launch_app" and target:
            app_counts[target] += 1

    total_commands = sum(command_counts.values())
    patterns: dict = {}
    if app_counts:
        patterns["top_apps"] = [list(t) for t in app_counts.most_common(5)]
    if total_commands:
        patterns["active_hours"] = dict(hour_counts)
        patterns["top_commands"] = [list(t) for t in command_counts.most_common(5)]
        patterns["avg_commands_per_day"] = round(total_commands / max(len(command_days), 1), 1)
        patterns["most_active_weekday"] = weekday_counts.most_common(1)[0][0]
    return patterns
