export interface ItemOption {
  id: string;
  text: string;
  is_correct: boolean;
}

/** One verified item bank entry — mirrors item_bank/schema.json, plus the
 * "subject" field derived at build time by scripts/build_item_bank_json.py
 * (not part of schema.json itself). */
export interface Item {
  id: string;
  question_text: string;
  options?: ItemOption[];
  answer_text: string;
  concept_tag: string;
  subconcept_tag: string;
  misconception_tags: Record<string, string>;
  difficulty: "easy" | "medium" | "hard";
  source: string;
  verified_by: string;
  exam_tier: "NEET";
  language: "en" | "hi";
  subject: string;
}
