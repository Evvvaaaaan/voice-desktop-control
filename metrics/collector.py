import sqlite3
import os
from datetime import datetime, timezone


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    stt_confidence REAL NOT NULL,
    success INTEGER NOT NULL,
    retry_count INTEGER NOT NULL,
    dangerous INTEGER NOT NULL,
    response_ms INTEGER NOT NULL,
    is_repeated INTEGER NOT NULL
)
"""


class MetricsCollector:
    def __init__(self, db_path: str = "data/command_history.db"):
        self._db_path = db_path
        parent = os.path.dirname(os.path.abspath(self._db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_TABLE)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def record(
        self,
        command: str,
        stt_confidence: float,
        success: bool,
        retry_count: int,
        dangerous: bool,
        response_ms: int,
        is_repeated: bool,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events VALUES (NULL,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    command,
                    stt_confidence,
                    int(success),
                    retry_count,
                    int(dangerous),
                    response_ms,
                    int(is_repeated),
                ),
            )
