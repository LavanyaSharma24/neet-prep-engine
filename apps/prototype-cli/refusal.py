"""Answer vs. refuse-and-flag decision.

Non-negotiable per docs/architecture.md: no confident wrong answers.
Below the confidence threshold, refuse and log instead of guessing.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

CONFIDENCE_THRESHOLD = 0.55
DEFAULT_FLAG_LOG = Path(__file__).resolve().parent / "flagged_questions.jsonl"
REFUSAL_MESSAGE = "No verified answer found for this question. It has been flagged for review."


def decide(query, item, confidence, threshold=CONFIDENCE_THRESHOLD, log_path=DEFAULT_FLAG_LOG):
    """Return a dict describing the action: 'answer' or 'refuse'."""
    if item is not None and confidence >= threshold:
        return {
            "action": "answer",
            "item": item,
            "confidence": confidence,
        }

    log_flagged(query, confidence, log_path)
    return {
        "action": "refuse",
        "item": None,
        "confidence": confidence,
        "message": REFUSAL_MESSAGE,
    }


def log_flagged(query, confidence, log_path=DEFAULT_FLAG_LOG):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "question_text": query,
        "confidence": confidence,
        "flagged_at": datetime.now(timezone.utc).isoformat(),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
