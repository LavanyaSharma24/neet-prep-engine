/**
 * TypeScript port of apps/prototype-cli/refusal.py.
 *
 * Answer vs. refuse-and-flag decision. Non-negotiable per
 * docs/architecture.md: no confident wrong answers. Below the confidence
 * threshold, refuse instead of guessing. Flagging happens later, in
 * App.tsx via flagQueue.ts, and only if no other tier answers either.
 */
import type { Item } from "./types";

export const CONFIDENCE_THRESHOLD = 0.55;
export const REFUSAL_MESSAGE =
  "No verified answer found for this question. It has been flagged for review.";

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

export function decide(
  query: string,
  item: Item | null,
  confidence: number,
  threshold: number = CONFIDENCE_THRESHOLD
): Decision {
  if (item !== null && confidence >= threshold) {
    return { action: "answer", item, confidence };
  }

  return { action: "refuse", item: null, confidence, message: REFUSAL_MESSAGE };
}
