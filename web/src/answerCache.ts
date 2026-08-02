/**
 * Device-local cache of answers previously returned by POST /escalate
 * (Gemini), keyed by normalized question text.
 *
 * This is NOT the item bank and NOT a source of truth — it exists only to
 * avoid a repeat network call for a question this device has already asked
 * while online. The server-side flagged_items.db (api/db.py) remains the
 * permanent record of every escalation regardless of what this cache
 * evicts or loses.
 *
 * Browser storage quotas — especially iOS Safari, which aggressively clears
 * IndexedDB under storage pressure — can evict entries independently of the
 * LRU logic below. That's a known platform limitation; this module doesn't
 * attempt to work around it.
 */

const DB_NAME = "neet-prep-answer-cache";
const DB_VERSION = 1;
const STORE_NAME = "answers";
const LAST_ACCESSED_INDEX = "by_last_accessed";

export const DEFAULT_MAX_ENTRIES = 200;
export const CACHED_ANSWER_LABEL = "AI-generated-pending-verification";

export interface CachedAnswer {
  question: string;
  answer: string;
  label: string;
  last_accessed_timestamp: number;
}

function normalizeKey(question: string): string {
  return question.trim().toLowerCase().replace(/\s+/g, " ");
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDB(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB is not available"));
  }
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: "question" });
          store.createIndex(LAST_ACCESSED_INDEX, "last_accessed_timestamp");
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error ?? new Error("Failed to open answer cache"));
    });
  }
  return dbPromise;
}

/**
 * Look up a cached answer. Never throws — a missing entry, a missing
 * IndexedDB (unsupported browser, private mode), or any read error all
 * resolve to null so the caller falls back to /escalate as if there were
 * no cache at all. Updates last_accessed_timestamp on every read (not just
 * on write) so LRU eviction reflects actual usage, not just insertion order.
 */
export async function getCachedAnswer(question: string): Promise<CachedAnswer | null> {
  try {
    const db = await openDB();
    const key = normalizeKey(question);
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      const store = tx.objectStore(STORE_NAME);
      const getReq = store.get(key);
      getReq.onsuccess = () => {
        const entry = getReq.result as CachedAnswer | undefined;
        if (!entry) {
          resolve(null);
          return;
        }
        entry.last_accessed_timestamp = Date.now();
        store.put(entry);
        resolve(entry);
      };
      getReq.onerror = () => reject(getReq.error);
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    return null;
  }
}

/**
 * Store an answer returned by /escalate, then evict least-recently-used
 * entries if the store now exceeds maxEntries. Never throws — a failed
 * write just means the next identical question hits the network again,
 * which is safe (this cache is purely an optimization).
 */
export async function putCachedAnswer(
  question: string,
  answer: string,
  label: string = CACHED_ANSWER_LABEL,
  maxEntries: number = DEFAULT_MAX_ENTRIES
): Promise<void> {
  try {
    const db = await openDB();
    const entry: CachedAnswer = {
      question: normalizeKey(question),
      answer,
      label,
      last_accessed_timestamp: Date.now(),
    };
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(entry);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    await evictLeastRecentlyUsed(db, maxEntries);
  } catch {
    // best-effort only — cache write failures are non-fatal.
  }
}

function evictLeastRecentlyUsed(db: IDBDatabase, maxEntries: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const countReq = store.count();
    countReq.onsuccess = () => {
      const overBy = countReq.result - maxEntries;
      if (overBy <= 0) {
        resolve();
        return;
      }
      // Index is sorted ascending by last_accessed_timestamp, so the
      // cursor visits the least-recently-used entries first.
      const cursorReq = store.index(LAST_ACCESSED_INDEX).openCursor();
      let deleted = 0;
      cursorReq.onsuccess = () => {
        const cursor = cursorReq.result;
        if (!cursor || deleted >= overBy) {
          resolve();
          return;
        }
        cursor.delete();
        deleted += 1;
        cursor.continue();
      };
      cursorReq.onerror = () => reject(cursorReq.error);
    };
    countReq.onerror = () => reject(countReq.error);
  });
}
