import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np


_DDL = """
CREATE TABLE IF NOT EXISTS user_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    confidence REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS behavior_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    command TEXT NOT NULL,
    action TEXT,
    target TEXT,
    success INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_behavior_ts ON behavior_log(timestamp);
CREATE TABLE IF NOT EXISTS conversation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversation_log(timestamp);
CREATE TABLE IF NOT EXISTS long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    embeddable INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS memory_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dim INTEGER NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vec_source ON memory_vectors(source_type, source_id);
CREATE TABLE IF NOT EXISTS pattern_data (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suggestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    suggestion_key TEXT NOT NULL,
    hour INTEGER NOT NULL,
    outcome TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suggestion_ts ON suggestion_log(timestamp);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_day(utc_iso: str) -> str:
    """Local 'YYYY-MM-DD' for a stored UTC ISO timestamp."""
    return datetime.fromisoformat(utc_iso).astimezone().strftime("%Y-%m-%d")


class MemoryStore:
    """5-tier user-information store sharing the app's sqlite file.

    Tier 1 user_profile / tier 2 behavior_log + conversation_log /
    tier 3 long_term_memory / tier 4 memory_vectors / tier 5 pattern_data.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        parent = os.path.dirname(os.path.abspath(self._db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_DDL)
            try:
                conn.execute("ALTER TABLE long_term_memory "
                             "ADD COLUMN embeddable INTEGER NOT NULL DEFAULT 1")
            except sqlite3.OperationalError:
                pass  # column already exists (fresh DDL or migrated earlier)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    # ----- tier 1: user profile -----

    def set_profile(self, key: str, value: str, source: str = "auto",
                    confidence: float = 1.0) -> None:
        with self._conn() as conn:
            # An auto-extracted fact must never clobber a user-entered one.
            conn.execute(
                """INSERT INTO user_profile VALUES (?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value, source=excluded.source,
                     confidence=excluded.confidence, updated_at=excluded.updated_at
                   WHERE user_profile.source != 'user' OR excluded.source = 'user'""",
                (key, value, source, confidence, _now()),
            )

    def get_profile(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile ORDER BY key").fetchall()
        return dict(rows)

    def get_profile_ranked(self, limit: int) -> list[tuple[str, str]]:
        """Top profile rows for prompt injection: user-entered facts first,
        then by confidence, then recency — NOT alphabetical, so accumulated
        low-value auto-extracted keys can't crowd out the facts that matter."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT key, value FROM user_profile "
                "ORDER BY (source='user') DESC, confidence DESC, updated_at DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()

    def get_profile_sources(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, source FROM user_profile").fetchall()
        return dict(rows)

    def delete_profile(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM user_profile WHERE key=?", (key,))

    # ----- tier 2: behavior + conversation logs -----

    def log_action(self, command: str, action: str, target: str,
                   success: bool, detail: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO behavior_log VALUES (NULL,?,?,?,?,?,?,?)",
                (_now(), "action", command, action, target, int(success), detail),
            )

    def log_command(self, command: str, success: bool, response_ms: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO behavior_log VALUES (NULL,?,?,?,?,?,?,?)",
                (_now(), "command", command, None, None, int(success),
                 json.dumps({"response_ms": response_ms})),
            )

    def log_conversation(self, user_text: str, assistant_text: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO conversation_log VALUES (NULL,?,?,?)",
                (_now(), user_text, assistant_text),
            )
            return cur.lastrowid

    # ----- tier 3: long-term memory -----

    def add_daily_summary(self, day: str, summary: str,
                          embeddable: bool = True) -> int:
        """embeddable=False stores the day (so it never re-loops) while
        keeping its text out of vector search — used for raw LLM replies
        that failed summary parsing."""
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO long_term_memory (day, summary, created_at, embeddable)
                   VALUES (?,?,?,?)
                   ON CONFLICT(day) DO UPDATE SET summary=excluded.summary,
                     embeddable=excluded.embeddable""",
                (day, summary, _now(), int(embeddable)),
            )
            return cur.lastrowid

    def get_recent_summaries(self, n: int = 7) -> list[tuple[str, str]]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT day, summary FROM long_term_memory ORDER BY day DESC LIMIT ?",
                (n,),
            ).fetchall()

    def unsummarized_days(self, before_day: str, limit: int = 7) -> list[str]:
        """Local dates < before_day with activity but no long_term_memory row."""
        with self._conn() as conn:
            ts_rows = conn.execute("SELECT timestamp FROM conversation_log").fetchall()
            ts_rows += conn.execute("SELECT timestamp FROM behavior_log").fetchall()
            done = {d for (d,) in conn.execute("SELECT day FROM long_term_memory")}
        days = {_local_day(ts) for (ts,) in ts_rows}
        pending = sorted(d for d in days if d < before_day and d not in done)
        return pending[:limit]

    def get_day_conversations(self, day: str) -> list[tuple[int, str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, user_text, assistant_text FROM conversation_log"
            ).fetchall()
        return [(i, u, a) for (i, ts, u, a) in rows if _local_day(ts) == day]

    def get_day_behavior(self, day: str) -> list[tuple[str, str, int]]:
        """(action, target, success) rows for the given local day."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, action, target, success FROM behavior_log "
                "WHERE event_type='action'"
            ).fetchall()
        return [(a, t, s) for (ts, a, t, s) in rows if _local_day(ts) == day]

    # ----- tier 4: vectors -----

    def add_vector(self, source_type: str, source_id: int | None,
                   content: str, embedding: list[float], model: str) -> None:
        blob = np.asarray(embedding, dtype=np.float32).tobytes()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO memory_vectors VALUES (NULL,?,?,?,?,?,?,?)",
                (source_type, source_id, content, blob, len(embedding), model, _now()),
            )

    # Short Korean commands cluster closely in embedding space, so a loose
    # threshold matches nearly every stored memory and the LLM starts pulling
    # params out of unrelated past commands. 0.5 keeps only genuinely related
    # content.
    def search_vectors(self, query_vec: list[float], model: str,
                       top_k: int = 3, min_sim: float = 0.5
                       ) -> list[tuple[float, str, str]]:
        """Top-k cosine matches as (similarity, source_type, content)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_type, content, embedding FROM memory_vectors WHERE model=?",
                (model,),
            ).fetchall()
        if not rows:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        scored = []
        for source_type, content, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape != q.shape:
                continue
            denom = q_norm * np.linalg.norm(v)
            if denom == 0:
                continue
            sim = float(np.dot(q, v) / denom)
            if sim >= min_sim:
                scored.append((sim, source_type, content))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[:top_k]

    def rows_missing_vectors(self, source_type: str, limit: int = 200
                             ) -> list[tuple[int, str]]:
        """(source_id, content) rows of the backing table not yet embedded."""
        table = {"conversation": "conversation_log", "daily_summary": "long_term_memory"}
        if source_type not in table:
            return []
        content_expr = ("user_text || ' / ' || assistant_text"
                        if source_type == "conversation" else "summary")
        embeddable_filter = (" AND t.embeddable=1"
                             if source_type == "daily_summary" else "")
        with self._conn() as conn:
            return conn.execute(
                f"""SELECT t.id, {content_expr} FROM {table[source_type]} t
                    WHERE t.id NOT IN (
                      SELECT source_id FROM memory_vectors
                      WHERE source_type=? AND source_id IS NOT NULL)
                      {embeddable_filter}
                    ORDER BY t.id LIMIT ?""",
                (source_type, limit),
            ).fetchall()

    # ----- suggestions -----

    def log_suggestion(self, key: str, hour: int, outcome: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO suggestion_log VALUES (NULL,?,?,?,?)",
                (_now(), key, hour, outcome),
            )

    def last_suggestion_at(self) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(timestamp) FROM suggestion_log").fetchone()
        return row[0] if row else None

    def suggestion_declined_on(self, key: str, local_day: str) -> bool:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT timestamp FROM suggestion_log "
                "WHERE suggestion_key=? AND outcome='declined'",
                (key,),
            ).fetchall()
        return any(_local_day(ts) == local_day for (ts,) in rows)

    def command_seen_since(self, command: str, since_utc_iso: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM behavior_log "
                "WHERE event_type='command' AND command=? AND timestamp>=? LIMIT 1",
                (command, since_utc_iso),
            ).fetchone()
        return row is not None

    # ----- tier 5: pattern data -----

    def set_patterns(self, patterns: dict) -> None:
        now = _now()
        with self._conn() as conn:
            for key, value in patterns.items():
                conn.execute(
                    """INSERT INTO pattern_data VALUES (?,?,?)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value, computed_at=excluded.computed_at""",
                    (key, json.dumps(value, ensure_ascii=False), now),
                )

    def get_patterns(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM pattern_data").fetchall()
        out = {}
        for key, value in rows:
            try:
                out[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        return out
