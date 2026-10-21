"""Escalation API — POST /escalate, POST /flags, GET /healthz.

/escalate is called by web/src/api.ts only when local retrieval confidence
is below threshold and the browser is online. Answers via a Tier 2
cross-check of two independent Gemini models (docs/architecture.md §1/§3)
and labels the result "AI-generated, pending verification" — never
"verified", that label is reserved for item-bank matches. Every agreed or
disagreed outcome is recorded in flagged_questions (api/db.py) for Tier 3
review; an agreed answer is then served from there on repeat questions
without calling Gemini again.

/flags receives questions the device queued because they ended with no
answer that the server didn't already record (web/src/flagQueue.ts).
"""
import logging
import os
import threading
import time
from collections import deque
from typing import Annotated, Literal

from dotenv import load_dotenv

load_dotenv()  # must run before importing db/gemini_client — both read
# env vars (DATABASE_URL, FLAGGED_ITEMS_DB, GEMINI_MODEL) at module import time.

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
from gemini_client import GeminiError, GeminiRefusal, cross_check_answer

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="NEET Prep Engine — Escalation API")

_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("flagged-question storage backend: %s", db.backend())
    try:
        db.init_db()
    except Exception as exc:
        # Best effort: answering must work without the database. Tables are
        # created lazily on the first successful connection instead.
        logger.warning("database init failed (%s); continuing without it", type(exc).__name__)


def _db_best_effort(action: str, fn, *args, **kwargs):
    """Runs a database call for /escalate; on any failure logs one line
    (exception type only — never connection details) and returns None, so
    a database problem can never break answering."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("database %s failed (%s); continuing without it", action, type(exc).__name__)
        return None


class EscalateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class EscalateResponse(BaseModel):
    answer: str | None = None
    label: str = "AI-GENERATED — PENDING VERIFICATION"
    refused: bool = False
    # True when both models answered but substantively disagreed — distinct
    # from `refused` (a model explicitly declining). Same "no answer served"
    # outcome client-side, but kept separate so logs/analytics don't conflate
    # "the model doesn't know" with "the two models contradicted each other".
    disagreed: bool = False


@app.post("/escalate", response_model=EscalateResponse)
def escalate(payload: EscalateRequest) -> EscalateResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    stored = _db_best_effort("lookup", db.get_question, question)
    if stored is not None:
        if stored["status"] == "rejected":
            # A reviewer rejected this question's candidate answers — don't
            # spend Gemini calls producing more of them.
            return EscalateResponse(disagreed=True)
        if stored["tier2_outcome"] == "agreed" and stored["primary_answer"]:
            _db_best_effort("ask-count update", db.bump_ask_count, question)
            return EscalateResponse(answer=stored["primary_answer"])

    try:
        result = cross_check_answer(question)
    except GeminiRefusal:
        # Either model correctly declined (e.g. out-of-domain question) —
        # not a failure, reported to the caller as a refusal. Not recorded
        # here: the device queues it with reason "model_refused" and syncs
        # it via POST /flags, so reviewers can filter or bulk-reject those.
        return EscalateResponse(refused=True)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Per docs/architecture.md's cross-check rule: disagreement means
    # neither candidate is served as an answer. Both are still recorded so a
    # human reviewer can see what each model said and adjudicate.
    _db_best_effort(
        "write", db.record_escalation, question,
        agreed=result.agreed,
        primary_answer=result.primary_answer,
        secondary_answer=result.secondary_answer,
    )
    if not result.agreed:
        return EscalateResponse(disagreed=True)
    return EscalateResponse(answer=result.primary_answer)


# --- POST /flags -------------------------------------------------------------

MAX_FLAGS_PER_REQUEST = 50
FLAGS_RATE_LIMIT = 30  # requests per client IP per window
FLAGS_RATE_WINDOW_SECONDS = 60

_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class Flag(BaseModel):
    flag_id: Annotated[str, Field(pattern=_UUID_PATTERN)]
    question_text: str = Field(min_length=1, max_length=2000)
    reason: Literal["model_refused", "offline", "api_error"]


class FlagsRequest(BaseModel):
    flags: list[Flag] = Field(min_length=1, max_length=MAX_FLAGS_PER_REQUEST)


class FlagsResponse(BaseModel):
    accepted: list[str]


# Best-effort, in-memory, PER-INSTANCE rate limit: each Render instance (and
# each restart) has its own counters, so it only blunts abuse rather than
# enforcing a global limit. X-Forwarded-For is client-controllable too.
_rate_lock = threading.Lock()
_rate_hits: dict[str, deque] = {}


def _client_ip(request: Request) -> str:
    # Render's proxy sets X-Forwarded-For; the first entry is the client.
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - FLAGS_RATE_WINDOW_SECONDS
    with _rate_lock:
        if len(_rate_hits) > 10_000:  # drop idle clients so memory stays bounded
            for key in [k for k, hits in _rate_hits.items() if not hits or hits[-1] < cutoff]:
                del _rate_hits[key]
        hits = _rate_hits.setdefault(ip, deque())
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= FLAGS_RATE_LIMIT:
            return True
        hits.append(now)
        return False


@app.post("/flags", response_model=FlagsResponse)
def flags(payload: FlagsRequest, request: Request) -> FlagsResponse:
    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many flag sync requests; try again later")
    try:
        accepted = db.record_flags([flag.model_dump() for flag in payload.flags])
    except Exception as exc:
        # Unlike /escalate there's nothing to fall back to: report failure so
        # the device keeps its queue and retries later.
        logger.warning("database flag sync failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="flag storage unavailable") from exc
    return FlagsResponse(accepted=accepted)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "db": db.backend()}
