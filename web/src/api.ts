/**
 * Calls the api/ backend's POST /escalate endpoint — and only that, only
 * when local retrieval confidence was below threshold.
 *
 * navigator.onLine is not trusted as an upfront gate: it's known to report
 * incorrect values in some browsers/dev environments, and trusting it
 * meant a reachable backend could get silently skipped. Instead, the call
 * is always attempted; only an actual network-level failure (connection
 * refused, DNS failure, CORS block, timeout) falls back to the offline
 * message. An HTTP-level failure (backend reachable but erroring, e.g. a
 * bad Gemini key) is a distinct case, not "offline" — see EscalationResult.
 *
 * Every failure is logged to the console with its real cause so it's
 * diagnosable instead of silently indistinguishable from being offline.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 15000;

export interface EscalateApiResponse {
  answer: string | null;
  label: string;
  refused: boolean;
}

export type EscalationResult =
  | { status: "skipped-confident" }
  | { status: "skipped-offline" }
  | { status: "ok"; answer: string }
  | { status: "refused" }
  | { status: "error"; error: string };

class EscalateHttpError extends Error {}

async function escalate(question: string): Promise<EscalateApiResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE_URL}/escalate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = body?.detail ? `: ${body.detail}` : "";
      } catch {
        // response wasn't JSON — ignore, use the status code alone
      }
      throw new EscalateHttpError(`Escalation request failed (${res.status})${detail}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}

/** Gate on confidence, then always attempt /escalate. Never throws — every
 * failure mode comes back as a typed result and is logged to the console
 * with the real underlying error. */
export async function escalateIfNeeded(
  question: string,
  confidence: number,
  threshold: number
): Promise<EscalationResult> {
  if (confidence >= threshold) {
    return { status: "skipped-confident" };
  }
  try {
    const response = await escalate(question);
    // Gemini correctly declining (out-of-domain question) is a successful
    // request, not an error — but it's not an answer either. Report it as
    // its own status so the UI shows the honest refusal, not a fabricated
    // "AI-generated" answer.
    if (response.refused || !response.answer) {
      return { status: "refused" };
    }
    return { status: "ok", answer: response.answer };
  } catch (err) {
    console.error(`[escalate] request failed for question "${question}":`, err);
    // fetch() itself rejects with a TypeError for network-level failures
    // (connection refused, DNS failure, CORS block); AbortController's
    // abort on timeout throws a DOMException named "AbortError". Both mean
    // "couldn't reach the backend at all" — the honest offline case.
    // EscalateHttpError means the backend WAS reached but returned a
    // non-2xx response — a real, diagnosable server-side error, not offline.
    if (err instanceof EscalateHttpError) {
      return { status: "error", error: err.message };
    }
    return { status: "skipped-offline" };
  }
}
