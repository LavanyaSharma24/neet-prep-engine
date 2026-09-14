"""Escalation API — single POST /escalate endpoint.

Called by web/src/api.ts only when local retrieval confidence is below
threshold and the browser is online. Answers via a Tier 2 cross-check of
two independent Gemini models (docs/architecture.md §1/§3) and labels the
result "AI-generated, pending verification" — never "verified", that
label is reserved for item-bank matches. Every escalation outcome
(agreed or disagreed) is logged to the flagged_items SQLite table so it
can be reviewed and, if appropriate, promoted later, per
docs/architecture.md Tier 3.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before importing db/gemini_client — both read
# env vars (FLAGGED_ITEMS_DB, GEMINI_MODEL) at module import time.

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import init_db, insert_flagged_item
from gemini_client import PRIMARY_MODEL, SECONDARY_MODEL, GeminiError, GeminiRefusal, cross_check_answer

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
    init_db()


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

    try:
        result = cross_check_answer(question)
    except GeminiRefusal:
        # Either model correctly declined (e.g. out-of-domain question) —
        # this isn't a failure and isn't reviewable content, so it's
        # reported to the caller as a refusal, not logged to flagged_items.db.
        return EscalateResponse(refused=True)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not result.agreed:
        # Per docs/architecture.md's cross-check rule: disagreement means
        # neither candidate is served as an answer. Both are still logged
        # (as one blob — flagged_items has no second answer column; see the
        # decision log for the schema-migration follow-up) so a human
        # reviewer can see what each model said and adjudicate.
        insert_flagged_item(
            question_text=question,
            answer_text=(
                "[DISAGREEMENT]\n"
                f"Model A ({PRIMARY_MODEL}): {result.primary_answer}\n"
                f"Model B ({SECONDARY_MODEL}): {result.secondary_answer}"
            ),
        )
        return EscalateResponse(disagreed=True)

    insert_flagged_item(question_text=question, answer_text=result.primary_answer)

    return EscalateResponse(answer=result.primary_answer)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
