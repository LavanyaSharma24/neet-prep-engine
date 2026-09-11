// Standalone prototype — NOT wired into the real app.
//
// Loads a small quantized instruction-tuned text2text model fully in the
// browser (WASM, CPU) via transformers.js and uses it to rephrase a
// verified item-bank answer in simpler words. The model is only ever told
// to rewrite the text it is given — the prompt explicitly forbids adding
// new facts, since this is a rephrasing aid, not an answer generator.
//
// Deliberately does not import anything from ../App, ../api, ../types,
// etc. This file (plus the tiny hook in main.tsx) is the entire footprint
// of the experiment; delete both to remove it completely.
import { useCallback, useRef, useState } from "react";

// Swap to "Xenova/LaMini-Flan-T5-77M" (~40MB quantized) for a faster/lower
// quality option when testing on slower phones.
const MODEL_ID = "Xenova/LaMini-Flan-T5-248M";

type Status = "idle" | "loading-model" | "ready" | "generating" | "error";

interface ProgressInfo {
  status: string;
  file?: string;
  progress?: number;
}

// Exported so it's independently testable without touching transformers.js.
export function buildRephrasePrompt(verifiedAnswer: string): string {
  return [
    "Rewrite the following answer in simpler words for a student.",
    "Do not add any new facts. Only simplify what is written.",
    "",
    `Answer: ${verifiedAnswer.trim()}`,
    "",
    "Simpler version:",
  ].join("\n");
}

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

// The transformers.js pipeline instance is cached at module scope so
// navigating away and back within the same tab session doesn't reload it.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let cachedPipeline: any = null;

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
  const pipelineRef = useRef<any>(cachedPipeline);

  const ensurePipeline = useCallback(async () => {
    if (pipelineRef.current) return pipelineRef.current;

    setStatus("loading-model");
    setError(null);
    const loadStart = performance.now();

    const { pipeline, env } = await import("@xenova/transformers");
    // Never try to resolve models from a local /models path.
    env.allowLocalModels = false;
    // Threaded WASM needs cross-origin-isolation headers this dev/preview
    // server doesn't send; force single-threaded so it just works.
    env.backends.onnx.wasm.numThreads = 1;

    const pipe = await pipeline("text2text-generation", MODEL_ID, {
      progress_callback: (info: ProgressInfo) => {
        if (!info.file) return;
        setProgressLines((prev) => ({ ...prev, [info.file as string]: info }));
      },
    });

    pipelineRef.current = pipe;
    cachedPipeline = pipe;
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

      const prompt = buildRephrasePrompt(inputText);
      const inferStart = performance.now();
      const result = await pipe(prompt, { max_new_tokens: 128 });
      setInferMs(performance.now() - inferStart);

      const text = Array.isArray(result) ? result[0]?.generated_text ?? "" : String(result);
      setOutput(text.trim());
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
