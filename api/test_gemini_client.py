"""Tests for the Tier 2 cross-check logic in gemini_client.py.

No real Gemini API calls happen here — genai.Client is never constructed;
_client()/ask_gemini()/_ask_judge() are monkeypatched directly so these
run offline and deterministically.
"""
import pytest

import gemini_client
from gemini_client import CrossCheckResult, GeminiError, GeminiRefusal, ask_gemini


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def _fake_client(text: str):
    """Builds a fake genai.Client stand-in whose generate_content always
    returns `text`, regardless of which model was asked."""

    class _Models:
        def generate_content(self, model, contents, config):
            return _FakeResponse(text)

    class _Client:
        models = _Models()

    return _Client()


# --- ask_gemini ---------------------------------------------------------


def test_ask_gemini_returns_stripped_text(monkeypatch):
    monkeypatch.setattr(gemini_client, "_client", lambda: _fake_client("  An answer.  "))
    assert ask_gemini("What is X?", model_name="any-model") == "An answer."


def test_ask_gemini_raises_refusal_on_sentinel(monkeypatch):
    monkeypatch.setattr(
        gemini_client, "_client", lambda: _fake_client(gemini_client.REFUSAL_TEXT)
    )
    with pytest.raises(GeminiRefusal):
        ask_gemini("An out-of-domain question", model_name="any-model")


def test_ask_gemini_raises_error_on_empty_response(monkeypatch):
    monkeypatch.setattr(gemini_client, "_client", lambda: _fake_client(""))
    with pytest.raises(GeminiError):
        ask_gemini("What is X?", model_name="any-model")


# --- _ask_judge ----------------------------------------------------------


def test_ask_judge_true_on_yes(monkeypatch):
    monkeypatch.setattr(gemini_client, "_client", lambda: _fake_client("YES"))
    assert gemini_client._ask_judge("Q", "answer a", "answer b") is True


def test_ask_judge_false_on_no(monkeypatch):
    monkeypatch.setattr(gemini_client, "_client", lambda: _fake_client("NO"))
    assert gemini_client._ask_judge("Q", "answer a", "answer b") is False


def test_ask_judge_fails_closed_on_error(monkeypatch):
    def _raise():
        raise RuntimeError("network blip")

    monkeypatch.setattr(gemini_client, "_client", _raise)
    # A broken judge call must never be silently treated as agreement —
    # serving an unverified answer is the one outcome the architecture
    # doc rules out entirely.
    assert gemini_client._ask_judge("Q", "answer a", "answer b") is False


# --- cross_check_answer ---------------------------------------------------


def _stub_ask_gemini(monkeypatch, *, primary=None, secondary=None):
    """primary/secondary are each either a return string or an exception
    instance to raise, keyed by which model_name cross_check_answer calls
    them with."""

    def fake(question, model_name):
        outcome = primary if model_name == gemini_client.PRIMARY_MODEL else secondary
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gemini_client, "ask_gemini", fake)


def test_cross_check_agrees(monkeypatch):
    _stub_ask_gemini(monkeypatch, primary="Mitochondria is the powerhouse.", secondary="Mitochondria powers the cell.")
    monkeypatch.setattr(gemini_client, "_ask_judge", lambda q, a, b: True)

    result = gemini_client.cross_check_answer("Q")

    assert result == CrossCheckResult(
        agreed=True,
        primary_answer="Mitochondria is the powerhouse.",
        secondary_answer="Mitochondria powers the cell.",
    )


def test_cross_check_disagrees(monkeypatch):
    _stub_ask_gemini(monkeypatch, primary="Answer A.", secondary="A contradicting answer.")
    monkeypatch.setattr(gemini_client, "_ask_judge", lambda q, a, b: False)

    result = gemini_client.cross_check_answer("Q")

    assert result.agreed is False
    assert result.primary_answer == "Answer A."
    assert result.secondary_answer == "A contradicting answer."


def test_cross_check_either_refusing_is_overall_refusal(monkeypatch):
    _stub_ask_gemini(monkeypatch, primary=GeminiRefusal("nope"), secondary="An answer.")

    with pytest.raises(GeminiRefusal):
        gemini_client.cross_check_answer("Q")


def test_cross_check_hard_error_takes_priority_over_refusal(monkeypatch):
    """If one side refuses and the other genuinely fails, the failure must
    surface — it must not be masked by treating the pair as a mere
    refusal."""
    _stub_ask_gemini(
        monkeypatch,
        primary=GeminiRefusal("nope"),
        secondary=GeminiError("upstream broke"),
    )

    with pytest.raises(GeminiError) as excinfo:
        gemini_client.cross_check_answer("Q")
    assert not isinstance(excinfo.value, GeminiRefusal)


def test_cross_check_both_error_raises(monkeypatch):
    _stub_ask_gemini(
        monkeypatch,
        primary=GeminiError("primary broke"),
        secondary=GeminiError("secondary broke"),
    )

    with pytest.raises(GeminiError):
        gemini_client.cross_check_answer("Q")
