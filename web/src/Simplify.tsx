// Opt-in "Simplify this explanation" control shown under a VERIFIED
// answer only (wired in App.tsx). Nothing loads or runs until the button
// is tapped: the model runtime is only reached via the dynamic import
// inside tier1.ts's ensureTier1Pipeline, so the main bundle is unaffected
// until then. The simplified output is purely additive — the verified
// answer above it is never hidden or replaced.
import { useCallback, useRef, useState } from "react";
import { ensureTier1Pipeline, rephrase, type ProgressInfo, type Tier1Pipeline } from "./tier1";

type Status = "idle" | "loading-model" | "generating" | "ready" | "error";

export default function Simplify({ answerText }: { answerText: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [output, setOutput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pipelineRef = useRef<Tier1Pipeline | null>(null);

  const handleClick = useCallback(async () => {
    setError(null);
    try {
      if (!pipelineRef.current) {
        setStatus("loading-model");
        pipelineRef.current = await ensureTier1Pipeline(setProgress);
      }
      setStatus("generating");
      const text = await rephrase(pipelineRef.current, answerText);
      setOutput(text);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }, [answerText]);

  const isBusy = status === "loading-model" || status === "generating";

  return (
    <div className="simplify">
      <button
        type="button"
        className="simplify-button"
        onClick={handleClick}
        disabled={isBusy}
      >
        {status === "loading-model"
          ? "Loading on-device model…"
          : status === "generating"
            ? "Simplifying…"
            : "Simplify this explanation"}
      </button>

      {status === "loading-model" && (
        <div className="simplify-progress">
          Downloading model files (first time only)
          {progress?.progress != null ? ` — ${progress.progress.toFixed(0)}%` : "…"}
        </div>
      )}

      {error && <div className="simplify-error">Couldn't simplify: {error}</div>}

      {output && (
        <div className="simplify-output">
          <div className="simplify-output-label">
            Simplified (on-device AI) — may reword imperfectly, original verified answer above is
            authoritative.
          </div>
          <p className="simplify-output-text">{output}</p>
        </div>
      )}
    </div>
  );
}
