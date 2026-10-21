/**
 * Device-local queue of flagged questions waiting to reach the server's
 * Tier 3 review queue (POST /flags → flagged_questions in api/db.py).
 *
 * Only questions whose final outcome had no answer AND that the server
 * didn't already record are queued: a Tier 2 refusal, no connection, or an
 * API error. (Disagreements are recorded server-side by /escalate itself.)
 * Each question is queued at most once per device, keyed by the same
 * normalization the server uses. Sync is opportunistic per
 * docs/architecture.md §5: on app load, on the 'online' event, and after a
 * successful /escalate — never blocking the UI.
 *
 * Same defensive style as answerCache.ts: nothing here throws, and without
 * IndexedDB (unsupported browser, private mode) it silently does nothing.
 */
import { API_BASE_URL } from "./api";

const DB_NAME = "neet-prep-flag-queue";
const DB_VERSION = 1;
const STORE_NAME = "flags";
const QUEUED_AT_INDEX = "by_queued_at";

export const MAX_FLAGS_PER_SYNC = 50; // POST /flags batch limit
const MAX_QUESTION_LENGTH = 2000; // POST /flags rejects longer questions
const SYNC_TIMEOUT_MS = 10000;
const MAX_BATCHES_PER_FLUSH = 5;
// After a failed sync, skip flushes for 30s, doubling up to 10 minutes.
const BACKOFF_BASE_MS = 30_000;
const BACKOFF_MAX_MS = 10 * 60_000;

export type FlagReason = "model_refused" | "offline" | "api_error";

export interface QueuedFlag {
  flag_id: string;
  question_text: string;
  key: string;
  reason: FlagReason;
  queued_at: number;
}

/** Mirrors api/db.py normalize_question: NFKC, lowercase, collapse
 * whitespace, trim, strip trailing punctuation. */
export function normalizeFlagKey(question: string): string {
  return question
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[?.!,;:\s]+$/, "");
}

function newFlagId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // randomUUID needs a secure context; build a v4 UUID by hand otherwise.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDB(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB is not available"));
  }
  if (!dbPromise) {
    dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: "key" });
          store.createIndex(QUEUED_AT_INDEX, "queued_at");
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error ?? new Error("Failed to open flag queue"));
    }).catch((err) => {
      dbPromise = null; // let a later call try again
      throw err;
    });
  }
  return dbPromise;
}

/** Queue a question for review unless this device already queued it.
 * Never throws. */
export async function enqueueFlag(question: string, reason: FlagReason): Promise<void> {
  try {
    const text = question.trim();
    const key = normalizeFlagKey(text);
    if (!key || text.length > MAX_QUESTION_LENGTH) return; // the server would reject it
    const db = await openDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      const store = tx.objectStore(STORE_NAME);
      const getReq = store.get(key);
      getReq.onsuccess = () => {
        if (getReq.result) return; // already queued — keep the original flag_id
        const flag: QueuedFlag = {
          flag_id: newFlagId(),
          question_text: text,
          key,
          reason,
          queued_at: Date.now(),
        };
        store.put(flag);
      };
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // best-effort only — losing a flag never affects answering.
  }
}

/** Every queued flag, oldest first (at most `limit`). Never throws. */
export async function getQueuedFlags(limit: number = Infinity): Promise<QueuedFlag[]> {
  try {
    const db = await openDB();
    return await new Promise((resolve, reject) => {
      const flags: QueuedFlag[] = [];
      const tx = db.transaction(STORE_NAME, "readonly");
      const cursorReq = tx.objectStore(STORE_NAME).index(QUEUED_AT_INDEX).openCursor();
      cursorReq.onsuccess = () => {
        const cursor = cursorReq.result;
        if (!cursor || flags.length >= limit) {
          resolve(flags);
          return;
        }
        flags.push(cursor.value as QueuedFlag);
        cursor.continue();
      };
      cursorReq.onerror = () => reject(cursorReq.error);
    });
  } catch {
    return [];
  }
}

async function deleteFlags(keys: string[]): Promise<void> {
  const db = await openDB();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    for (const key of keys) store.delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function postFlags(batch: QueuedFlag[]): Promise<string[]> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SYNC_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE_URL}/flags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        flags: batch.map(({ flag_id, question_text, reason }) => ({ flag_id, question_text, reason })),
      }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`Flag sync failed (${res.status})`);
    const body = await res.json();
    return Array.isArray(body?.accepted) ? body.accepted : [];
  } finally {
    clearTimeout(timeout);
  }
}

let inFlight: Promise<number> | null = null;
let consecutiveFailures = 0;
let nextAttemptAt = 0;

/**
 * Send queued flags to POST /flags in batches of up to 50 and delete
 * exactly the ones the server accepted. Resolves to how many were
 * accepted. Never throws. A no-op when the browser reports being offline,
 * while backing off after a failure, or if a flush is already running.
 */
export function flushFlags(): Promise<number> {
  if (!inFlight) {
    inFlight = doFlush().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

async function doFlush(): Promise<number> {
  // navigator.onLine === true isn't trustworthy (see api.ts), but false
  // reliably means there's no network at all — don't bother trying.
  if (typeof navigator !== "undefined" && navigator.onLine === false) return 0;
  if (Date.now() < nextAttemptAt) return 0;

  let accepted = 0;
  try {
    for (let i = 0; i < MAX_BATCHES_PER_FLUSH; i++) {
      const batch = await getQueuedFlags(MAX_FLAGS_PER_SYNC);
      if (batch.length === 0) break;
      const acceptedIds = new Set(await postFlags(batch));
      const done = batch.filter((flag) => acceptedIds.has(flag.flag_id));
      if (done.length > 0) await deleteFlags(done.map((flag) => flag.key));
      accepted += done.length;
      if (batch.length < MAX_FLAGS_PER_SYNC || done.length === 0) break;
    }
    consecutiveFailures = 0;
    nextAttemptAt = 0;
  } catch (err) {
    console.warn("[flagQueue] sync failed; will retry later:", err);
    consecutiveFailures += 1;
    nextAttemptAt =
      Date.now() + Math.min(BACKOFF_BASE_MS * 2 ** (consecutiveFailures - 1), BACKOFF_MAX_MS);
  }
  return accepted;
}
