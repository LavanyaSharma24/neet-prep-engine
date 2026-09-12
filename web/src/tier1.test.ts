import { describe, it, expect } from "vitest";
import { buildRephrasePrompt } from "./tier1";

describe("buildRephrasePrompt", () => {
  it("embeds the trimmed answer and forbids adding new facts", () => {
    const prompt = buildRephrasePrompt("  Some verified answer.  ");

    expect(prompt).toContain("Answer: Some verified answer.");
    expect(prompt).toContain("Do not add any new facts.");
    expect(prompt.trim().endsWith("Simpler version:")).toBe(true);
  });
});
