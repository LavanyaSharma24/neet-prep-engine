"""Tests for api/main.py's endpoints. SQLite only, Gemini fully stubbed:
cross_check_answer is replaced in main's namespace, so no network call can
happen."""
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

import db
import main
from gemini_client import CrossCheckResult, GeminiError, GeminiRefusal

LABEL = "AI-GENERATED — PENDING VERIFICATION"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_URL", None)  # never a real DB, even if api/.env sets one
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "flagged.db")
    monkeypatch.setattr(db, "_initialized", False)
    monkeypatch.setattr(main, "_rate_hits", {})
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def gemini(monkeypatch):
    """Stubs cross_check_answer; set .outcome to a CrossCheckResult or an
    exception instance. .calls counts invocations."""

    class _Stub:
        outcome = CrossCheckResult(agreed=True, primary_answer="Protein synthesis.",
                                   secondary_answer="They make proteins.")
        calls = 0

        def __call__(self, question):
            self.calls += 1
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    stub = _Stub()
    monkeypatch.setattr(main, "cross_check_answer", stub)
    return stub


def _escalate(client, question="What is the function of ribosomes?"):
    return client.post("/escalate", json={"question": question})


# --- /escalate ----------------------------------------------------------------------


def test_agreed_answer_is_stored_then_served_without_gemini(client, gemini):
    first = _escalate(client)
    assert first.status_code == 200
    assert first.json() == {"answer": "Protein synthesis.", "label": LABEL,
                            "refused": False, "disagreed": False}

    second = _escalate(client, "  what is the FUNCTION of ribosomes ")
    assert second.json() == first.json()
    assert gemini.calls == 1  # second answer came from the database

    row = db.get_question("What is the function of ribosomes?")
    assert row["ask_count"] == 2
    assert row["tier2_outcome"] == "agreed"
    assert row["secondary_answer"] == "They make proteins."


def test_disagreement_stored_with_both_answers(client, gemini):
    gemini.outcome = CrossCheckResult(agreed=False, primary_answer="36", secondary_answer="30")

    res = _escalate(client)

    assert res.json()["disagreed"] is True
    assert res.json()["answer"] is None
    row = db.get_question("What is the function of ribosomes?")
    assert (row["tier2_outcome"], row["primary_answer"], row["secondary_answer"]) == ("disagreed", "36", "30")
    assert "[DISAGREEMENT]" not in row["primary_answer"]


def test_disagreed_question_is_retried_with_gemini(client, gemini):
    gemini.outcome = CrossCheckResult(agreed=False, primary_answer="36", secondary_answer="30")
    _escalate(client)
    gemini.outcome = CrossCheckResult(agreed=True, primary_answer="38", secondary_answer="38 ATP")

    res = _escalate(client)

    assert res.json()["answer"] == "38"
    assert gemini.calls == 2


def test_rejected_question_returns_disagreed_without_gemini(client, gemini):
    _escalate(client)
    with db._connect() as conn:
        db._execute(conn, "UPDATE flagged_questions SET status = 'rejected'")
    calls_before = gemini.calls

    res = _escalate(client)

    assert res.json() == {"answer": None, "label": LABEL, "refused": False, "disagreed": True}
    assert gemini.calls == calls_before


def test_refusal_is_not_recorded(client, gemini):
    gemini.outcome = GeminiRefusal("I don't have a confident answer.")

    res = _escalate(client, "Who won the 2011 cricket world cup?")

    assert res.json()["refused"] is True
    assert db.get_question("Who won the 2011 cricket world cup?") is None


def test_gemini_error_is_502(client, gemini):
    gemini.outcome = GeminiError("Gemini cross-check timed out")
    res = _escalate(client)
    assert res.status_code == 502
    assert "timed out" in res.json()["detail"]


def test_database_failure_still_returns_the_answer(client, gemini, monkeypatch):
    def broken_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "_connect", broken_connect)

    res = _escalate(client)

    assert res.status_code == 200
    assert res.json()["answer"] == "Protein synthesis."
    assert gemini.calls == 1


# --- /flags ----------------------------------------------------------------------


def _flags(*texts, reason="offline"):
    return {"flags": [{"flag_id": str(uuid.uuid4()), "question_text": t, "reason": reason}
                      for t in texts]}


def test_flags_are_stored_and_idempotent(client):
    body = _flags("Why is the sky blue?", "What is a gene?", reason="model_refused")
    ids = [f["flag_id"] for f in body["flags"]]

    first = client.post("/flags", json=body)
    again = client.post("/flags", json=body)

    assert first.status_code == 200
    assert first.json() == {"accepted": ids}
    assert again.json() == {"accepted": ids}
    row = db.get_question("What is a gene?")
    assert row["ask_count"] == 1
    assert (row["source"], row["reason"], row["tier2_outcome"]) == ("offline-sync", "model_refused", "none")


def test_flags_batch_limit(client):
    assert client.post("/flags", json=_flags(*[f"q{i}" for i in range(50)])).status_code == 200
    assert client.post("/flags", json=_flags(*[f"q{i}" for i in range(51)])).status_code == 422


@pytest.mark.parametrize("flag", [
    {"flag_id": "not-a-uuid", "question_text": "Q", "reason": "offline"},
    {"flag_id": str(uuid.uuid4()), "question_text": "", "reason": "offline"},
    {"flag_id": str(uuid.uuid4()), "question_text": "x" * 2001, "reason": "offline"},
    {"flag_id": str(uuid.uuid4()), "question_text": "Q", "reason": "bored"},
    {"flag_id": str(uuid.uuid4()), "question_text": "Q"},
])
def test_flags_malformed_is_422(client, flag):
    assert client.post("/flags", json={"flags": [flag]}).status_code == 422


def test_flags_empty_or_missing_list_is_422(client):
    assert client.post("/flags", json={"flags": []}).status_code == 422
    assert client.post("/flags", json={}).status_code == 422


def test_flags_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(main, "FLAGS_RATE_LIMIT", 3)
    a = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
    b = {"X-Forwarded-For": "198.51.100.7"}

    statuses = [client.post("/flags", json=_flags("Q"), headers=a).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    assert client.post("/flags", json=_flags("Q"), headers=b).status_code == 200


def test_flags_database_failure_is_503(client, monkeypatch):
    def broken(_flags):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "record_flags", broken)
    assert client.post("/flags", json=_flags("Q")).status_code == 503


# --- /healthz -----------------------------------------------------------------------


def test_healthz_reports_backend(client):
    assert client.get("/healthz").json() == {"status": "ok", "db": "sqlite"}
