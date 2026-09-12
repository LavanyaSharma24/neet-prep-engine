// Shared Tier 1 logic: on-device rephrasing of an already-verified answer
// via transformers.js. Used by both the real "Simplify this explanation"
// feature (see ./Simplify.tsx) and the standalone diagnostic prototype
// (see ./prototypes/Tier1Test.tsx) — no duplicated model-loading or prompt
// logic between the two.
//
// No React import: this module is plain browser/JS, independently
// testable and reusable outside any particular UI. @xenova/transformers
// itself is only ever reached via the dynamic import() inside
// ensureTier1Pipeline, so importing this module does not pull the model
// runtime into the main bundle — that only happens once a caller actually
// invokes ensureTier1Pipeline (e.g. on a button click).

// Swap to "Xenova/LaMini-Flan-T5-77M" (~40MB quantized) for a faster/lower
// quality option when testing on slower phones.
export const MODEL_ID = "Xenova/LaMini-Flan-T5-248M";

export interface ProgressInfo {
  status: string;
  file?: string;
  progress?: number;
}

// The transformers.js pipeline object has no published TS types we depend
// on beyond "callable with a prompt string" — kept as `any` at the
// boundary, same as the prototype did.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Tier1Pipeline = any;

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

// Cached at module scope so every caller within the same tab session
// (prototype and real app alike) shares one loaded model instead of each
// downloading/initializing its own.
let cachedPipeline: Tier1Pipeline | null = null;

export async function ensureTier1Pipeline(
  onProgress?: (info: ProgressInfo) => void
): Promise<Tier1Pipeline> {
  if (cachedPipeline) return cachedPipeline;

  const { pipeline, env } = await import("@xenova/transformers");
  // Never try to resolve models from a local /models path.
  env.allowLocalModels = false;
  // Threaded WASM needs cross-origin-isolation headers this dev/preview
  // server doesn't send; force single-threaded so it just works.
  env.backends.onnx.wasm.numThreads = 1;

  const pipe = await pipeline("text2text-generation", MODEL_ID, {
    progress_callback: (info: ProgressInfo) => {
      if (!info.file) return;
      onProgress?.(info);
    },
  });

  cachedPipeline = pipe;
  return pipe;
}

export async function rephrase(pipe: Tier1Pipeline, verifiedAnswer: string): Promise<string> {
  const prompt = buildRephrasePrompt(verifiedAnswer);
  const result = await pipe(prompt, { max_new_tokens: 128 });
  const text = Array.isArray(result) ? result[0]?.generated_text ?? "" : String(result);
  return text.trim();
}
