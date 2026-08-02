"""SQLite-backed queue of escalated questions/answers for human review.

Table: flagged_items — the Tier 3 human review queue per
docs/architecture.md §1/§4. Every escalation gets written here so nothing
is lost, whether or not it's ever promoted into the permanent item bank.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DB_PATH = Path(
    os.environ.get("FLAGGED_ITEMS_DB", Path(__file__).resolve().parent / "flagged_items.db")
)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flagged_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                answer_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def insert_flagged_item(question_text: str, answer_text: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO flagged_items (question_text, answer_text, created_at) VALUES (?, ?, ?)",
            (question_text, answer_text, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
