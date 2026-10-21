import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";

// Each test gets a fresh in-memory IndexedDB and a fresh copy of the module
// (its open-DB promise and backoff state are module-level).
async function loadQueue() {
  vi.resetModules();
  return await import("./flagQueue");
}

function respondWith(body: unknown, status = 200) {
  return vi.fn(async (_url: string, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status }));
}

function sentFlags(fetchMock: { mock: { calls: unknown[][] } }, call = 0) {
  const init = fetchMock.mock.calls[call][1] as RequestInit;
  return JSON.parse(init.body as string).flags as { flag_id: string; question_text: string; reason: string }[];
}

beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("navigator", { onLine: true });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("enqueueFlag", () => {
  it("queues a question once per normalized key", async () => {
    const q = await loadQueue();

    await q.enqueueFlag("What is ATP?", "offline");
    await q.enqueueFlag("  what IS   atp ", "api_error");
    await q.enqueueFlag("What is ADP?", "model_refused");

    const flags = await q.getQueuedFlags();
    expect(flags.map((f) => f.key).sort()).toEqual(["what is adp", "what is atp"]);
    const atp = flags.find((f) => f.key === "what is atp");
    // The first wording, reason and flag_id are kept.
    expect(atp).toMatchObject({ question_text: "What is ATP?", reason: "offline" });
    expect(atp?.flag_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("skips questions the server would reject", async () => {
    const q = await loadQueue();

    await q.enqueueFlag("???", "offline");
    await q.enqueueFlag("x".repeat(2001), "offline");

    expect(await q.getQueuedFlags()).toEqual([]);
  });

  it("never throws without IndexedDB", async () => {
    vi.stubGlobal("indexedDB", undefined);
    const q = await loadQueue();

    await expect(q.enqueueFlag("What is ATP?", "offline")).resolves.toBeUndefined();
    await expect(q.flushFlags()).resolves.toBe(0);
  });
});

describe("flushFlags", () => {
  it("deletes only the flags the server accepted", async () => {
    const q = await loadQueue();
    await q.enqueueFlag("Question one", "offline");
    await q.enqueueFlag("Question two", "model_refused");
    const queued = await q.getQueuedFlags();
    const first = queued.find((f) => f.question_text === "Question one")!;
    const second = queued.find((f) => f.question_text === "Question two")!;
    const fetchMock = respondWith({ accepted: [first.flag_id] });
    vi.stubGlobal("fetch", fetchMock);

    expect(await q.flushFlags()).toBe(1);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/flags$/);
    expect(sentFlags(fetchMock)).toEqual(expect.arrayContaining([
      { flag_id: first.flag_id, question_text: "Question one", reason: "offline" },
      { flag_id: second.flag_id, question_text: "Question two", reason: "model_refused" },
    ]));
    expect((await q.getQueuedFlags()).map((f) => f.flag_id)).toEqual([second.flag_id]);
  });

  it("keeps everything when the request fails, then backs off", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const q = await loadQueue();
    await q.enqueueFlag("Question one", "offline");
    const fetchMock = respondWith({ detail: "flag storage unavailable" }, 503);
    vi.stubGlobal("fetch", fetchMock);

    expect(await q.flushFlags()).toBe(0);
    expect(await q.getQueuedFlags()).toHaveLength(1);

    // Within the backoff window, no new request is made.
    expect(await q.flushFlags()).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps everything on a network error", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const q = await loadQueue();
    await q.enqueueFlag("Question one", "offline");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));

    expect(await q.flushFlags()).toBe(0);
    expect(await q.getQueuedFlags()).toHaveLength(1);
  });

  it("is a no-op when offline", async () => {
    vi.stubGlobal("navigator", { onLine: false });
    const q = await loadQueue();
    await q.enqueueFlag("Question one", "offline");
    const fetchMock = respondWith({ accepted: [] });
    vi.stubGlobal("fetch", fetchMock);

    expect(await q.flushFlags()).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await q.getQueuedFlags()).toHaveLength(1);
  });

  it("sends at most 50 per request and continues with the rest", async () => {
    const q = await loadQueue();
    for (let i = 0; i < 60; i++) await q.enqueueFlag(`Question ${i}`, "offline");
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const flags = JSON.parse(init.body as string).flags as { flag_id: string }[];
      return new Response(JSON.stringify({ accepted: flags.map((f) => f.flag_id) }));
    });
    vi.stubGlobal("fetch", fetchMock);

    expect(await q.flushFlags()).toBe(60);

    expect(sentFlags(fetchMock, 0)).toHaveLength(50);
    expect(sentFlags(fetchMock, 1)).toHaveLength(10);
    expect(await q.getQueuedFlags()).toEqual([]);
  });

  it("does nothing when the queue is empty", async () => {
    const q = await loadQueue();
    const fetchMock = respondWith({ accepted: [] });
    vi.stubGlobal("fetch", fetchMock);

    expect(await q.flushFlags()).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
