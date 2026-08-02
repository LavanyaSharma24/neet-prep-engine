"""Thin wrapper around the Gemini API for escalated NEET Biology/Chemistry
questions. Reads GEMINI_API_KEY from the environment (see .env.example).

Grounds answers to NEET syllabus content and instructs the model to say so
— never guess — when it isn't confident, matching the non-negotiable in
docs/architecture.md §6 ("no confident wrong answers").
"""
import os

from google import genai
from google.genai import types

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

REFUSAL_TEXT = "I don't have a confident answer."

SYSTEM_PROMPT = (
    "You are answering NEET (India) Biology and Chemistry exam-prep questions "
    "only. Ground every answer in standard NCERT syllabus content. If you are "
    f"not confident in a correct, precise answer, respond exactly with: "
    f"\"{REFUSAL_TEXT}\" Do not guess or invent facts."
)


class GeminiError(RuntimeError):
    """Raised when the Gemini API call fails or is misconfigured."""


class GeminiRefusal(GeminiError):
    """Raised when Gemini explicitly declines (e.g. an out-of-domain
    question) rather than failing. Distinct from GeminiError so callers can
    tell "the model correctly said it doesn't know" apart from "the request
    broke" — those need different HTTP status codes, UI labels, and
    flagged_items.db treatment (a decline isn't reviewable content)."""


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def ask_gemini(question: str) -> str:
    try:
        client = _client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=question,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
    except GeminiError:
        raise
    except Exception as exc:  # network/SDK errors — surface as a clean 502 upstream
        raise GeminiError(f"Gemini request failed: {exc}") from exc

    text = (response.text or "").strip()
    if not text:
        raise GeminiError("Gemini returned an empty response")
    if text == REFUSAL_TEXT:
        raise GeminiRefusal(text)
    return text
