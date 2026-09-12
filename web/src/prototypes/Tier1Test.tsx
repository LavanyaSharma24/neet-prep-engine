// Standalone diagnostic harness — NOT wired into the real app.
//
// Exercises the shared Tier 1 on-device rephrasing logic (../tier1.ts,
// also used by the real Simplify.tsx feature) with load/inference timing
// visible, useful for testing model swaps and checking performance on
// real devices.
//
// Deliberately does not import anything from ../App, ../api, ../types,
// etc. — only ../tier1. This file (plus the tiny hook in main.tsx) is the
// entire footprint of the experiment; delete both to remove it completely.
import { useCallback, useRef, useState } from "react";
import { ensureTier1Pipeline, rephrase, MODEL_ID, type ProgressInfo, type Tier1Pipeline } from "../tier1";

type Status = "idle" | "loading-model" | "ready" | "generating" | "error";

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function Tier1Test() {
  const [status, setStatus] = useState<Status>("idle");
  const [progressLines, setProgressLines] = useState<Record<string, ProgressInfo>>({});
  const [inputText, setInputText] = useState(
    "Neon has the highest first ionization energy among common examples due to its stable, fully-filled electron configuration and small atomic radius."
  );
  const [output, setOutput] = useState("");
  const [loadMs, setLoadMs] = useState<number | null>(null);
  const [inferMs, setInferMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pipelineRef = useRef<Tier1Pipeline | null>(null);

  const ensurePipeline = useCallback(async () => {
    if (pipelineRef.current) return pipelineRef.current;

    setStatus("loading-model");
    setError(null);
    const loadStart = performance.now();

    const pipe = await ensureTier1Pipeline((info) => {
      setProgressLines((prev) => ({ ...prev, [info.file as string]: info }));
    });

    pipelineRef.current = pipe;
    setLoadMs(performance.now() - loadStart);
    setStatus("ready");
    return pipe;
  }, []);

  const handleRephrase = useCallback(async () => {
    setError(null);
    setOutput("");
    setInferMs(null);
    try {
      const pipe = await ensurePipeline();
      setStatus("generating");

      const inferStart = performance.now();
      const text = await rephrase(pipe, inputText);
      setInferMs(performance.now() - inferStart);

      setOutput(text);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }, [ensurePipeline, inputText]);

  const isBusy = status === "loading-model" || status === "generating";

  return (
    <div style={styles.page}>
      <h1 style={styles.h1}>Tier 1 Test — in-browser rephrasing prototype</h1>
      <p style={styles.hint}>
        Isolated experiment. Model: <code>{MODEL_ID}</code>. Runs entirely on-device via
        transformers.js (WASM/CPU) — first load downloads the model, then it's cached by the
        browser.
      </p>

      <label style={styles.label} htmlFor="verified-answer">
        Verified answer text (paste from the item bank, e.g. chem-0001)
      </label>
      <textarea
        id="verified-answer"
        style={styles.textarea}
        rows={5}
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
      />

      <button style={styles.button} onClick={handleRephrase} disabled={isBusy || !inputText.trim()}>
        {status === "loading-model"
          ? "Loading model…"
          : status === "generating"
            ? "Rephrasing…"
            : "Rephrase in simpler words"}
      </button>

      {status === "loading-model" && (
        <div style={styles.progressBox}>
          <div>Downloading model files (first load only)…</div>
          {Object.values(progressLines).map((p) => (
            <div key={p.file} style={styles.progressLine}>
              {p.file}: {p.progress != null ? `${p.progress.toFixed(0)}%` : p.status}
            </div>
          ))}
        </div>
      )}

      {error && <div style={styles.error}>Error: {error}</div>}

      {output && (
        <div style={styles.outputBox}>
          <h2 style={styles.h2}>Output</h2>
          <p style={styles.outputText}>{output}</p>
        </div>
      )}

      {(loadMs != null || inferMs != null) && (
        <div style={styles.timing}>
          {loadMs != null && <div>Model load time: {formatSeconds(loadMs)}</div>}
          {inferMs != null && <div>Inference time: {formatSeconds(inferMs)}</div>}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    fontFamily: "system-ui, sans-serif",
    maxWidth: 640,
    margin: "0 auto",
    padding: "1.5rem 1rem",
    color: "#1a1a1a",
    background: "#fff",
    minHeight: "100vh",
  },
  h1: { fontSize: "1.25rem", marginBottom: "0.25rem" },
  h2: { fontSize: "1rem", margin: "0 0 0.5rem" },
  hint: { fontSize: "0.85rem", color: "#555", marginBottom: "1rem" },
  label: { display: "block", fontSize: "0.85rem", fontWeight: 600, marginBottom: "0.25rem" },
  textarea: {
    width: "100%",
    boxSizing: "border-box",
    fontSize: "0.95rem",
    padding: "0.5rem",
    marginBottom: "0.75rem",
    fontFamily: "inherit",
  },
  button: {
    padding: "0.6rem 1rem",
    fontSize: "0.95rem",
    cursor: "pointer",
    marginBottom: "1rem",
  },
  progressBox: {
    fontSize: "0.8rem",
    background: "#f3f3f3",
    padding: "0.75rem",
    borderRadius: 6,
    marginBottom: "1rem",
  },
  progressLine: { fontFamily: "monospace" },
  error: {
    color: "#a30000",
    background: "#fdeaea",
    padding: "0.75rem",
    borderRadius: 6,
    marginBottom: "1rem",
    fontSize: "0.9rem",
  },
  outputBox: {
    background: "#f0f7f0",
    padding: "0.75rem",
    borderRadius: 6,
    marginBottom: "1rem",
  },
  outputText: { margin: 0, whiteSpace: "pre-wrap" },
  timing: { fontSize: "0.85rem", color: "#333" },
};
