/**
 * TypeScript port of apps/prototype-cli/refusal.py.
 *
 * Answer vs. refuse-and-flag decision. Non-negotiable per
 * docs/architecture.md: no confident wrong answers. Below the confidence
 * threshold, refuse and log instead of guessing.
 */
import type { Item } from "./types";

export const CONFIDENCE_THRESHOLD = 0.55;
export const REFUSAL_MESSAGE =
  "No verified answer found for this question. It has been flagged for review.";

const FLAG_LOG_KEY = "neet-prep-flagged-questions";

export interface DecisionAnswer {
  action: "answer";
  item: Item;
  confidence: number;
}

export interface DecisionRefuse {
  action: "refuse";
  item: null;
  confidence: number;
  message: string;
}

export type Decision = DecisionAnswer | DecisionRefuse;

/** Best-effort local log of flagged (refused) questions, mirroring
 * refusal.py's flagged_questions.jsonl — there's no filesystem in the
 * browser, so this uses localStorage instead. Never throws. */
export function logFlagged(query: string, confidence: number): void {
  if (typeof localStorage === "undefined") return;
  const entry = {
    question_text: query,
    confidence,
    flagged_at: new Date().toISOString(),
  };
  try {
    const raw = localStorage.getItem(FLAG_LOG_KEY);
    const existing: unknown[] = raw ? JSON.parse(raw) : [];
    existing.push(entry);
    localStorage.setItem(FLAG_LOG_KEY, JSON.stringify(existing));
  } catch {
    // localStorage unavailable/full — logging is best-effort only.
  }
}

export function decide(
  query: string,
  item: Item | null,
  confidence: number,
  threshold: number = CONFIDENCE_THRESHOLD
): Decision {
  if (item !== null && confidence >= threshold) {
    return { action: "answer", item, confidence };
  }

  logFlagged(query, confidence);
  return { action: "refuse", item: null, confidence, message: REFUSAL_MESSAGE };
}
