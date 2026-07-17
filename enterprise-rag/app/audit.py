"""Append-only audit log (SQLite).

Every security-relevant event is recorded: token issuance, ingestion,
deletion, and each query (who asked, with which roles, how many chunks
came back). In production you'd ship these to your SIEM.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    actor   TEXT    NOT NULL,
    roles   TEXT    NOT NULL,
    action  TEXT    NOT NULL,
    detail  TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class AuditLog:
    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def log(self, actor: str, roles: list[str], action: str, **detail) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts, actor, roles, action, detail) VALUES (?,?,?,?,?)",
                (time.time(), actor, ",".join(roles), action, json.dumps(detail)),
            )
            self._conn.commit()

    def recent(self, limit: int = 100) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, ts, actor, roles, action, detail FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": row[0],
                "ts": row[1],
                "actor": row[2],
                "roles": row[3].split(",") if row[3] else [],
                "action": row[4],
                "detail": json.loads(row[5]),
            }
            for row in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()
