import { describe, it, expect } from "vitest";
import { match } from "./retrieval";
import type { Item } from "./types";

// Real bio-0001 record from item_bank/biology/neet_bio_items.jsonl, kept in
// sync by hand since this test intentionally avoids a build-time import.
const BIO_0001: Item = {
  id: "bio-0001",
  question_text: "Which organelle is known as the powerhouse of the cell?",
  options: [
    { id: "A", text: "Mitochondria", is_correct: true },
    { id: "B", text: "Ribosome", is_correct: false },
    { id: "C", text: "Golgi apparatus", is_correct: false },
    { id: "D", text: "Lysosome", is_correct: false },
  ],
  answer_text:
    "Mitochondria is known as the powerhouse of the cell because it generates ATP through oxidative phosphorylation, the cell's main energy currency.",
  concept_tag: "Cell Biology",
  subconcept_tag: "Cell Organelles",
  misconception_tags: {
    B: "confuses-protein-synthesis-site-with-energy-site",
    C: "confuses-packaging-organelle-with-energy-site",
    D: "confuses-digestive-organelle-with-energy-site",
  },
  difficulty: "easy",
  source: "NCERT Class 11 Biology, Ch 8",
  verified_by: "internal-v0-seed",
  exam_tier: "NEET",
  language: "en",
  subject: "biology",
};

// Real chem-0001 record, used purely as an unrelated decoy so a match
// against BIO_0001 is actually discriminating rather than the only option.
const CHEM_0001: Item = {
  id: "chem-0001",
  question_text: "Which of the following has the highest first ionization energy?",
  answer_text:
    "Neon has the highest first ionization energy among common examples due to its stable, fully-filled electron configuration and small atomic radius.",
  concept_tag: "periodic_trends",
  subconcept_tag: "ionization_energy",
  misconception_tags: { "0": "confuses_ionization_energy_with_electronegativity" },
  difficulty: "medium",
  source: "NCERT",
  verified_by: "internal-v0-seed",
  exam_tier: "NEET",
  language: "en",
  subject: "chemistry",
};

const items: Item[] = [BIO_0001, CHEM_0001];

describe("match", () => {
  it("matches item when the question is pasted with full A/B/C/D options", () => {
    const bare = match(
      "Which organelle is known as the powerhouse of the cell?",
      items
    );
    const pasted = match(
      "Which organelle is known as the powerhouse of the cell?\n" +
        "A) Nucleus\nB) Mitochondria\nC) Ribosome\nD) Golgi apparatus",
      items
    );
    expect(pasted.item?.id).toBe(bare.item?.id);
    expect(pasted.confidence).toBeGreaterThanOrEqual(0.55);
  });

  it("does not truncate a query containing a decimal number", () => {
    // "0.1" alone must not be mistaken for a pasted MCQ option marker —
    // there is no second, sequential marker (e.g. a following "B)") after it.
    const bare = match(
      "Which organelle is known as the powerhouse of the cell?",
      items
    );
    const withDecimal = match(
      "Which organelle is known as the powerhouse of the cell? " +
        "(Hint: it consumes O2 at a rate of 0.1 mL/min)",
      items
    );
    expect(withDecimal.item?.id).toBe(bare.item?.id);
  });
});
