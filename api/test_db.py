"""Tests for api/db.py — flagged_questions storage.

Run against a throwaway SQLite file. The same tests also run against
Postgres when TEST_DATABASE_URL is set (skipped otherwise); they only touch
rows for their own uniquely-named questions and delete them afterwards.
"""
import os
import uuid

import pytest

import db

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        if not TEST_DATABASE_URL:
            pytest.skip("TEST_DATABASE_URL not set")
        monkeypatch.setattr(db, "DATABASE_URL", TEST_DATABASE_URL)
    else:
        monkeypatch.setattr(db, "DATABASE_URL", None)
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "flagged.db")
    monkeypatch.setattr(db, "_initialized", False)
    db.init_db()
    created = []
    yield created
    if request.param == "postgres":
        with db._connect() as conn:
            for text in created:
                db._execute(conn, "DELETE FROM flagged_questions WHERE question_hash = ?",
                            (db.question_hash(text),))


def _question(store, text="What is the function of ribosomes"):
    unique = f"{text} {uuid.uuid4().hex[:8]}"
    store.append(unique)
    return unique


def _count_rows(text):
    with db._connect() as conn:
        return db._execute(
            conn, "SELECT COUNT(*) FROM flagged_questions WHERE question_hash = ?",
            (db.question_hash(text),),
        ).fetchone()[0]


# --- normalization ------------------------------------------------------------


def test_normalize_question():
    assert db.normalize_question("  What is  ATP?  ") == "what is atp"
    assert db.normalize_question("What\tis\nATP.") == "what is atp"
    assert db.normalize_question("ＡＴＰ？") == "atp"  # NFKC folds full-width forms
    assert db.normalize_question("Define pH?!.") == "define ph"
    # NFKC folds sub/superscripts: ₂ -> 2, ⁻ -> U+2212 MINUS SIGN
    assert db.normalize_question("O₂⁻ ion?") == "o2\u2212 ion"


def test_question_hash_matches_across_variants():
    assert db.question_hash("What is ATP?") == db.question_hash("  what IS   atp ")
    assert db.question_hash("What is ATP?") != db.question_hash("What is ADP?")
    assert len(db.question_hash("What is ATP?")) == 64


def test_question_hash_none_when_nothing_left():
    assert db.question_hash("  ??? ") is None


# --- upserts -------------------------------------------------------------------


def test_repeat_question_increments_ask_count_without_new_row(store):
    q = _question(store)
    db.record_escalation(q, agreed=True, primary_answer="A", secondary_answer="B")
    db.record_escalation(q.upper() + "?", agreed=True, primary_answer="A2", secondary_answer="B2")

    row = db.get_question(q)
    assert row["ask_count"] == 2
    assert _count_rows(q) == 1
    assert row["question_text"] == q  # first wording kept
    assert (row["primary_answer"], row["secondary_answer"]) == ("A", "B")
    assert row["status"] == "new"
    assert row["source"] == "escalation"
    assert row["last_seen"] >= row["first_seen"]


def test_agreed_overwrites_answers_from_earlier_disagreement(store):
    q = _question(store)
    db.record_escalation(q, agreed=False, primary_answer="wrong A", secondary_answer="wrong B")
    db.record_escalation(q, agreed=True, primary_answer="right A", secondary_answer="right B")

    row = db.get_question(q)
    assert row["tier2_outcome"] == "agreed"
    assert (row["primary_answer"], row["secondary_answer"]) == ("right A", "right B")


def test_agreed_is_never_downgraded(store):
    q = _question(store)
    db.record_escalation(q, agreed=True, primary_answer="A", secondary_answer="B")
    db.record_escalation(q, agreed=False, primary_answer="X", secondary_answer="Y")

    row = db.get_question(q)
    assert row["tier2_outcome"] == "agreed"
    assert (row["primary_answer"], row["secondary_answer"]) == ("A", "B")


def test_disagreed_answers_only_filled_if_unset(store):
    q = _question(store)
    db.record_escalation(q, agreed=False, primary_answer="A1", secondary_answer="B1")
    db.record_escalation(q, agreed=False, primary_answer="A2", secondary_answer="B2")

    row = db.get_question(q)
    assert row["tier2_outcome"] == "disagreed"
    assert (row["primary_answer"], row["secondary_answer"]) == ("A1", "B1")


# --- record_flags -----------------------------------------------------------------


def _flag(text, reason="offline", flag_id=None):
    return {"flag_id": flag_id or str(uuid.uuid4()), "question_text": text, "reason": reason}


def test_record_flags_is_idempotent_by_flag_id(store):
    q = _question(store)
    flag = _flag(q)

    assert db.record_flags([flag]) == [flag["flag_id"]]
    assert db.record_flags([flag]) == [flag["flag_id"]]  # re-send: accepted, not re-counted

    row = db.get_question(q)
    assert row["ask_count"] == 1
    assert row["source"] == "offline-sync"
    assert row["tier2_outcome"] == "none"
    assert row["reason"] == "offline"


def test_record_flags_keeps_existing_outcome_and_updates_reason(store):
    q = _question(store)
    db.record_escalation(q, agreed=False, primary_answer="A", secondary_answer="B")
    db.record_flags([_flag(q, reason="model_refused")])

    row = db.get_question(q)
    assert row["ask_count"] == 2
    assert row["tier2_outcome"] == "disagreed"
    assert row["source"] == "escalation"
    assert row["reason"] == "model_refused"


def test_record_flags_accepts_but_skips_empty_after_normalizing(store):
    flag = _flag("???")
    assert db.record_flags([flag]) == [flag["flag_id"]]
