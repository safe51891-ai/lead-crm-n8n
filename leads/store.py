"""Durable record of processed leads. Survives restarts, so a webhook retried after a crash does not create a second contact."""
import sqlite3
from pathlib import Path


class LeadStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS processed (
                email TEXT PRIMARY KEY,
                crm_contact_id TEXT NOT NULL,
                alerted INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS dead_letter (
                email TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1
            )"""
        )
        self.conn.commit()

    def queue_failed(self, email: str, payload: dict) -> None:
        import json

        self.conn.execute(
            "INSERT INTO dead_letter (email, payload) VALUES (?, ?) "
            "ON CONFLICT(email) DO UPDATE SET attempts = attempts + 1",
            (email, json.dumps(payload)),
        )
        self.conn.commit()

    def pending(self) -> list[tuple[str, dict]]:
        import json

        return [(e, json.loads(p)) for e, p in self.conn.execute("SELECT email, payload FROM dead_letter")]

    def clear_queued(self, email: str) -> None:
        self.conn.execute("DELETE FROM dead_letter WHERE email = ?", (email,))
        self.conn.commit()

    def get(self, email: str) -> str | None:
        row = self.conn.execute("SELECT crm_contact_id FROM processed WHERE email = ?", (email,)).fetchone()
        return row[0] if row else None

    def save(self, email: str, contact_id: str, alerted: bool) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO processed (email, crm_contact_id, alerted) VALUES (?, ?, ?)",
            (email, contact_id, int(alerted)),
        )
        self.conn.commit()
