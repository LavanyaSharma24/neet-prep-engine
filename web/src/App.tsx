import { useEffect, useState, type FormEvent } from "react";
import type { Item } from "./types";
import { match } from "./retrieval";
import { decide, CONFIDENCE_THRESHOLD } from "./refusal";
import { escalateIfNeeded } from "./api";
import { getCachedAnswer, putCachedAnswer } from "./answerCache";
import { CheckCircleIcon, SparkleIcon, FlagIcon } from "./icons";

type Label =
  | "VERIFIED"
  | "AI-GENERATED — PENDING VERIFICATION"
  | "NO VERIFIED ANSWER — flagged";

interface ChatEntry {
  id: number;
  question: string;
  label: Label;
  answerText: string;
  confidence: number;
  source?: string;
}

function stateClass(label: Label): "verified" | "pending" | "flagged" {
  if (label === "VERIFIED") return "verified";
  if (label === "AI-GENERATED — PENDING VERIFICATION") return "pending";
  return "flagged";
}

function StateIcon({ label }: { label: Label }) {
  const state = stateClass(label);
  if (state === "verified") return <CheckCircleIcon />;
  if (state === "pending") return <SparkleIcon />;
  return <FlagIcon />;
}

export default function App() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [nextId, setNextId] = useState(0);

  useEffect(() => {
    fetch("/item_bank.json")
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load item bank (${res.status})`);
        return res.json();
      })
      .then((data: Item[]) => setItems(data))
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = query.trim();
    if (!question || !items || busy) return;

    setQuery("");
    setBusy(true);
    const id = nextId;
    setNextId((n) => n + 1);

    const { item, confidence } = match(question, items);
    const decision = decide(question, item, confidence);

    if (decision.action === "answer") {
      setEntries((prev) => [
        ...prev,
        {
          id,
          question,
          label: "VERIFIED",
          answerText: decision.item.answer_text,
          confidence,
          source: decision.item.source,
        },
      ]);
      setBusy(false);
      return;
    }

    // From here on we're resolving asynchronously (cache lookup, maybe a
    // real network call) — show the loading skeleton for that window so
    // it's visible that something is actually happening, not just a
    // frozen UI.
    setPendingQuestion(question);

    // Check the device-local answer cache before hitting the network at
    // all — this also means a previously-escalated question can still be
    // answered while offline, unlike a fresh escalation.
    const cached = await getCachedAnswer(question);
    if (cached) {
      setEntries((prev) => [
        ...prev,
        {
          id,
          question,
          label: "AI-GENERATED — PENDING VERIFICATION",
          answerText: cached.answer,
          confidence,
        },
      ]);
      setPendingQuestion(null);
      setBusy(false);
      return;
    }

    const escalation = await escalateIfNeeded(question, confidence, CONFIDENCE_THRESHOLD);

    if (escalation.status === "ok") {
      await putCachedAnswer(question, escalation.answer);
      setEntries((prev) => [
        ...prev,
        {
          id,
          question,
          label: "AI-GENERATED — PENDING VERIFICATION",
          answerText: escalation.answer,
          confidence,
        },
      ]);
    } else {
      setEntries((prev) => [
        ...prev,
        {
          id,
          question,
          label: "NO VERIFIED ANSWER — flagged",
          answerText: decision.message,
          confidence,
        },
      ]);
    }
    setPendingQuestion(null);
    setBusy(false);
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>NEET Prep Engine</h1>
        <p className="subtitle">v0 web prototype — NEET Biology &amp; Chemistry</p>
      </header>

      {loadError && (
        <div className="banner error">Could not load item bank: {loadError}</div>
      )}
      {!items && !loadError && <div className="banner">Loading item bank…</div>}

      <main className="chat">
        {entries.length === 0 && !pendingQuestion && items && (
          <p className="empty-state">Ask a NEET Biology or Chemistry question to get started.</p>
        )}
        {entries.map((entry) => {
          const state = stateClass(entry.label);
          return (
            <div className={`entry entry-${state}`} key={entry.id}>
              <div className="question">{entry.question}</div>
              <div className={`label label-${state}`}>
                <StateIcon label={entry.label} />
                {entry.label}
              </div>
              <div className="answer">{entry.answerText}</div>
              <div className="meta">
                confidence: {entry.confidence.toFixed(2)}
                {entry.source ? ` · source: ${entry.source}` : ""}
              </div>
            </div>
          );
        })}
        {pendingQuestion && (
          <div className="entry entry-loading">
            <div className="question">{pendingQuestion}</div>
            <div className="skeleton-label">
              <span className="skeleton-dots">
                <span />
                <span />
                <span />
              </span>
              Checking for a verified or AI-generated answer…
            </div>
            <div className="skeleton-line" />
            <div className="skeleton-line" />
            <div className="skeleton-line" />
          </div>
        )}
      </main>

      <form className="composer" onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a NEET Biology or Chemistry question…"
          disabled={!items || busy}
        />
        <button type="submit" disabled={!items || busy || !query.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </form>
    </div>
  );
}
