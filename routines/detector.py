import sqlite3


class RoutineDetector:
    def __init__(self, db_path: str, threshold: int = 3):
        self._db = db_path
        self._threshold = threshold
        with sqlite3.connect(self._db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS cmd_freq "
                "(command TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)"
            )

    def record(self, command: str) -> bool:
        with sqlite3.connect(self._db) as c:
            c.execute(
                "INSERT INTO cmd_freq(command, count) VALUES(?,1) "
                "ON CONFLICT(command) DO UPDATE SET count=count+1",
                (command,)
            )
            row = c.execute(
                "SELECT count FROM cmd_freq WHERE command=?", (command,)
            ).fetchone()
            count = row[0]
            if count >= self._threshold:
                c.execute("UPDATE cmd_freq SET count=0 WHERE command=?", (command,))
                return True
        return False
