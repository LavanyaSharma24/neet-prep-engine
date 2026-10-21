"""Storage for flagged questions — the Tier 3 human review queue
(docs/architecture.md §1/§4) and the server-side cache of agreed Tier 2
answers.

Two backends behind the same functions:
- Postgres (Neon) when DATABASE_URL is set — production, since Render's
  free tier wipes local files on every restart;
- SQLite at FLAGGED_ITEMS_DB otherwise — local dev and all tests.

Tables:
- flagged_questions: one row per distinct question, keyed by the sha256 of
  its normalized text (see normalize_question), with an ask count, review
  status and the Tier 2 candidate answers.
- flag_receipts: flag_ids already received via POST /flags, so a device
  re-sending the same queued flag is a no-op.

The legacy flagged_items table is left untouched (no migration) and no
longer written to.

Every function opens its own short-lived connection. Postgres connects
with a short connect timeout and statement timeout so a slow database can
never hang a request; callers decide whether a failure is fatal.
"""
import hashlib
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DATABASE_URL = os.environ.get("DATABASE_URL") or None
DB_PATH = Path(
    os.environ.get("FLAGGED_ITEMS_DB", Path(__file__).resolve().parent / "flagged_items.db")
)
CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MS = 5000

STATUSES = ("new", "in_review", "approved", "rejected", "promoted")
FLAG_REASONS = ("model_refused", "offline", "api_error")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS flagged_questions (
        question_hash TEXT PRIMARY KEY,
        question_text TEXT NOT NULL,
        ask_count INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        tier2_outcome TEXT NOT NULL DEFAULT 'none',
        primary_answer TEXT,
        secondary_answer TEXT,
        source TEXT NOT NULL,
        reason TEXT,
        cluster_of TEXT,
        reviewer TEXT,
        review_notes TEXT,
        reviewed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS flag_receipts (
        flag_id TEXT PRIMARY KEY,
        received_at TEXT NOT NULL
    )
    """,
)

# Atomic insert-or-bump. Rules on conflict:
# - ask_count + 1, last_seen updated; question_text and source keep their
#   first values.
# - An 'agreed' result overwrites the outcome and both answers unless the
#   row is already 'agreed' (answers from an earlier disagreement must never
#   be served as the agreed answer). An 'agreed' row is never downgraded,
#   and 'none' (an offline-sync flag) never replaces a real outcome.
# - Otherwise answers are only filled in if not already set.
# - reason: the latest non-null one wins.
_UPSERT_SQL = """
    INSERT INTO flagged_questions (
        question_hash, question_text, ask_count, first_seen, last_seen,
        tier2_outcome, primary_answer, secondary_answer, source, reason
    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (question_hash) DO UPDATE SET
        ask_count = flagged_questions.ask_count + 1,
        last_seen = excluded.last_seen,
        primary_answer = CASE
            WHEN excluded.tier2_outcome = 'agreed' AND flagged_questions.tier2_outcome <> 'agreed'
                THEN excluded.primary_answer
            ELSE COALESCE(flagged_questions.primary_answer, excluded.primary_answer)
        END,
        secondary_answer = CASE
            WHEN excluded.tier2_outcome = 'agreed' AND flagged_questions.tier2_outcome <> 'agreed'
                THEN excluded.secondary_answer
            ELSE COALESCE(flagged_questions.secondary_answer, excluded.secondary_answer)
        END,
        tier2_outcome = CASE
            WHEN flagged_questions.tier2_outcome = 'agreed' THEN 'agreed'
            WHEN excluded.tier2_outcome = 'none' THEN flagged_questions.tier2_outcome
            ELSE excluded.tier2_outcome
        END,
        reason = COALESCE(excluded.reason, flagged_questions.reason)
"""

_COLUMNS = (
    "question_hash", "question_text", "ask_count", "first_seen", "last_seen",
    "status", "tier2_outcome", "primary_answer", "secondary_answer", "source",
    "reason", "cluster_of", "reviewer", "review_notes", "reviewed_at",
)

_initialized = False


def backend() -> str:
    return "postgres" if DATABASE_URL else "sqlite"


def normalize_question(text: str) -> str:
    """NFKC, lowercase, collapse whitespace, trim, and strip trailing
    punctuation — so "What is ATP?" and "  what is  ATP " are one row."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip("?.!,;: ").strip()


def question_hash(text: str) -> str | None:
    """sha256 of the normalized question, or None if nothing is left
    after normalizing (e.g. "???")."""
    normalized = normalize_question(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[Any]:
    """Yields a connection inside a transaction: committed on success,
    rolled back on error, always closed. SQL in this module is written with
    '?' placeholders; _execute translates them for Postgres."""
    global _initialized
    if DATABASE_URL:
        import psycopg  # imported lazily: only needed when Postgres is configured

        # prepare_threshold=None: no server-side prepared statements, which
        # Neon's transaction-mode pooler may not support.
        conn = psycopg.connect(
            DATABASE_URL, connect_timeout=CONNECT_TIMEOUT_SECONDS, prepare_threshold=None
        )
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        _begin(conn)
        if not _initialized:
            # Lazily, so a database that was down at startup still gets its
            # tables on the first request after it comes back.
            for statement in _SCHEMA:
                _execute(conn, statement)
            conn.commit()
            _begin(conn)
            _initialized = True
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception:
            pass  # connection already broken; the original error matters more
        raise
    finally:
        conn.close()


def _begin(conn: Any) -> None:
    # SET LOCAL lasts only for the current transaction, so it's safe behind
    # a pooler (a startup "options" parameter is rejected by Neon's pooler).
    if DATABASE_URL:
        conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")


def _execute(conn: Any, sql: str, params: tuple = ()) -> Any:
    if DATABASE_URL:
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def init_db() -> None:
    """Creates the tables if missing. Idempotent."""
    global _initialized
    _initialized = False
    with _connect():
        pass


def get_question(question_text: str) -> dict | None:
    qhash = question_hash(question_text)
    if qhash is None:
        return None
    with _connect() as conn:
        row = _execute(
            conn,
            f"SELECT {', '.join(_COLUMNS)} FROM flagged_questions WHERE question_hash = ?",
            (qhash,),
        ).fetchone()
    return dict(zip(_COLUMNS, row)) if row else None


def bump_ask_count(question_text: str) -> None:
    qhash = question_hash(question_text)
    if qhash is None:
        return
    with _connect() as conn:
        _execute(
            conn,
            "UPDATE flagged_questions SET ask_count = ask_count + 1, last_seen = ? "
            "WHERE question_hash = ?",
            (_now(), qhash),
        )


def _upsert(conn: Any, question_text: str, *, outcome: str, primary: str | None,
            secondary: str | None, source: str, reason: str | None) -> None:
    qhash = question_hash(question_text)
    if qhash is None:
        return
    now = _now()
    _execute(
        conn,
        _UPSERT_SQL,
        (qhash, question_text, now, now, outcome, primary, secondary, source, reason),
    )


def record_escalation(question_text: str, *, agreed: bool, primary_answer: str,
                      secondary_answer: str) -> None:
    """Records a Tier 2 cross-check result (agreed or disagreed)."""
    with _connect() as conn:
        _upsert(
            conn, question_text,
            outcome="agreed" if agreed else "disagreed",
            primary=primary_answer, secondary=secondary_answer,
            source="escalation", reason=None,
        )


def record_flags(flags: list[dict]) -> list[str]:
    """Records offline-synced flags ({flag_id, question_text, reason}) in
    one transaction. A flag_id already in flag_receipts is skipped but
    still reported as accepted, so re-sends are harmless. Returns the
    accepted flag_ids; raises on a database error (nothing is committed)."""
    accepted = []
    with _connect() as conn:
        for flag in flags:
            inserted = _execute(
                conn,
                "INSERT INTO flag_receipts (flag_id, received_at) VALUES (?, ?) "
                "ON CONFLICT (flag_id) DO NOTHING",
                (flag["flag_id"], _now()),
            ).rowcount
            if inserted:
                _upsert(
                    conn, flag["question_text"],
                    outcome="none", primary=None, secondary=None,
                    source="offline-sync", reason=flag["reason"],
                )
            accepted.append(flag["flag_id"])
    return accepted
