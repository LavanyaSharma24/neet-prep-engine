"""Escalation API — single POST /escalate endpoint.

Called by web/src/api.ts only when local retrieval confidence is below
threshold and the browser is online. Answers via Gemini, labels the result
"AI-generated, pending verification" (never "verified" — that label is
reserved for item-bank matches), and logs every escalation to the
flagged_items SQLite table so it can be reviewed and promoted later, per
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
from gemini_client import GeminiError, GeminiRefusal, ask_gemini

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


@app.post("/escalate", response_model=EscalateResponse)
def escalate(payload: EscalateRequest) -> EscalateResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    try:
        answer = ask_gemini(question)
    except GeminiRefusal:
        # Gemini correctly declined (e.g. out-of-domain question) — this
        # isn't a failure and isn't reviewable content, so it's reported to
        # the caller as a refusal, not logged to flagged_items.db.
        return EscalateResponse(refused=True)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    insert_flagged_item(question_text=question, answer_text=answer)

    return EscalateResponse(answer=answer)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
