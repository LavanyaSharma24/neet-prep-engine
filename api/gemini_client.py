"""Thin wrapper around the Gemini API for escalated NEET Biology/Chemistry
questions. Reads GEMINI_API_KEY from the environment (see .env.example).

Grounds answers to NEET syllabus content and instructs the model to say so
— never guess — when it isn't confident, matching the non-negotiable in
docs/architecture.md §6 ("no confident wrong answers").

Tier 2 cross-check (docs/architecture.md §1/§3): two independently-called
models must substantively agree before an answer is served as
"AI-generated, pending verification". The original design intent was a
genuine cross-tier pair (Flash + Pro); the current API key has zero
free-tier quota for any Pro-class model (verified directly against the
Gemini API, not assumed — see docs/architecture.md decision log), so both
models here are same-family Flash variants until billing unlocks Pro.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from google import genai
from google.genai import errors, types

# Both default to the two models confirmed working against this project's
# actual API key (direct generateContent calls, not just listed as
# available — see docs/architecture.md decision log). Every gemini-2.5-*
# model and any Pro-class model 404s/429s on this key; do not reintroduce
# them as defaults without re-verifying against the live API first.
PRIMARY_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
SECONDARY_MODEL = os.environ.get("GEMINI_SECONDARY_MODEL", "gemini-flash-lite-latest")

REFUSAL_TEXT = "I don't have a confident answer."

SYSTEM_PROMPT = (
    "You are answering NEET (India) Biology and Chemistry exam-prep questions "
    "only. Ground every answer in standard NCERT syllabus content. If you are "
    f"not confident in a correct, precise answer, respond exactly with: "
    f"\"{REFUSAL_TEXT}\" Do not guess or invent facts."
)

_JUDGE_SYSTEM_PROMPT = (
    "You are checking whether two candidate answers to the same exam "
    "question substantively agree on the facts — wording differences don't "
    "matter, only whether the underlying claims match. Respond with exactly "
    "one word: YES if they agree, NO if they contradict each other or "
    "differ on a material fact."
)

# 503 UNAVAILABLE is Gemini's transient "high demand" response — worth a
# quick retry. 429 (quota exhaustion) is a hard cap that won't clear in
# seconds, so it deliberately is NOT retried here — retrying it would just
# burn more of a quota that's already at zero.
MAX_503_RETRIES = 2
RETRY_BACKOFF_SECONDS = (1, 2)


class GeminiError(RuntimeError):
    """Raised when the Gemini API call fails or is misconfigured."""


class GeminiRefusal(GeminiError):
    """Raised when Gemini explicitly declines (e.g. an out-of-domain
    question) rather than failing. Distinct from GeminiError so callers can
    tell "the model correctly said it doesn't know" apart from "the request
    broke" — those need different HTTP status codes, UI labels, and
    flagged_items.db treatment (a decline isn't reviewable content)."""


@dataclass(frozen=True)
class CrossCheckResult:
    """Outcome of asking both Tier 2 models independently. `agreed` gates
    whether an answer is servable at all — see docs/architecture.md's
    cross-check rule: disagreement means neither answer is served, not
    "pick one and hope"."""

    agreed: bool
    primary_answer: str
    secondary_answer: str


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def ask_gemini(
    question: str, model_name: str = PRIMARY_MODEL, system_prompt: str = SYSTEM_PROMPT
) -> str:
    attempt = 0
    while True:
        try:
            client = _client()
            response = client.models.generate_content(
                model=model_name,
                contents=question,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            break
        except GeminiError:
            raise
        except errors.ServerError as exc:
            if exc.code == 503 and attempt < MAX_503_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
                attempt += 1
                continue
            raise GeminiError(f"Gemini request failed ({model_name}): {exc}") from exc
        except Exception as exc:  # network/SDK errors — surface as a clean 502 upstream
            raise GeminiError(f"Gemini request failed ({model_name}): {exc}") from exc

    text = (response.text or "").strip()
    if not text:
        raise GeminiError(f"Gemini returned an empty response ({model_name})")
    if text == REFUSAL_TEXT:
        raise GeminiRefusal(text)
    return text


def _ask_judge(question: str, answer_a: str, answer_b: str) -> bool:
    """Asks the (cheaper) secondary model whether two candidate answers
    substantively agree. A judge failure fails closed — treated as
    disagreement, never as a silent agreement — since serving an unverified
    answer is the one outcome the architecture doc rules out entirely."""
    prompt = (
        f"Question: {question.strip()}\n\n"
        f"Answer A: {answer_a.strip()}\n\n"
        f"Answer B: {answer_b.strip()}\n\n"
        "Do these substantively agree?"
    )
    try:
        verdict = ask_gemini(
            prompt, model_name=SECONDARY_MODEL, system_prompt=_JUDGE_SYSTEM_PROMPT
        )
    except Exception:
        return False

    return verdict.strip().upper() == "YES"


def cross_check_answer(question: str) -> CrossCheckResult:
    """Calls both Tier 2 models independently (in parallel, so total
    latency stays ~1 round trip rather than 2+ sequential ones) and judges
    whether their answers substantively agree.

    Either model refusing (GeminiRefusal) is treated as an overall refusal
    — there's nothing to cross-check if one side has no answer. Either
    model failing outright (GeminiError) propagates as-is; a real failure
    shouldn't be silently downgraded to "disagreement".

    Both futures are always awaited before anything is raised — checking
    primary's result and returning early would silently swallow a genuine
    error on the secondary side if primary happened to merely refuse.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        primary_future = pool.submit(ask_gemini, question, PRIMARY_MODEL)
        secondary_future = pool.submit(ask_gemini, question, SECONDARY_MODEL)

        primary_answer = primary_error = None
        secondary_answer = secondary_error = None
        try:
            primary_answer = primary_future.result()
        except GeminiError as exc:
            primary_error = exc
        try:
            secondary_answer = secondary_future.result()
        except GeminiError as exc:
            secondary_error = exc

    # A hard failure on either side takes priority over a mere refusal —
    # it's more actionable and shouldn't be masked by the other side simply
    # declining to answer.
    for err in (primary_error, secondary_error):
        if err is not None and not isinstance(err, GeminiRefusal):
            raise err
    if primary_error is not None or secondary_error is not None:
        raise primary_error or secondary_error

    agreed = _ask_judge(question, primary_answer, secondary_answer)
    return CrossCheckResult(
        agreed=agreed, primary_answer=primary_answer, secondary_answer=secondary_answer
    )
