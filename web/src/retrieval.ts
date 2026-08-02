/**
 * TypeScript port of apps/prototype-cli/retrieval.py.
 *
 * Fuzzy/keyword matching of a typed question against the local item bank.
 * No LLM, no network calls — pure client-side logic, subject-agnostic (it
 * only ever looks at question_text, so it works for biology, chemistry, or
 * any future subject folder without changes).
 */
import type { Item } from "./types";

const STOPWORDS = new Set([
  "a", "an", "the", "is", "are", "was", "were", "of", "in", "on", "at",
  "to", "for", "and", "or", "which", "what", "who", "whom", "does",
  "do", "did", "how", "why", "when", "where", "called", "known", "as",
  "this", "that", "these", "those", "it", "its", "with", "by", "term",
  "describes",
]);

// Matches Python's string.punctuation.
const PUNCTUATION_RE = /[!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~]/g;

function normalize(text: string): string {
  return text.toLowerCase().replace(PUNCTUATION_RE, "");
}

function keywords(text: string): Set<string> {
  const words = normalize(text)
    .split(/\s+/)
    .filter((word) => word.length > 0 && !STOPWORDS.has(word));
  return new Set(words);
}

/**
 * Ratcliff/Obershelp ratio, matching Python's difflib.SequenceMatcher.ratio()
 * (autojunk is not implemented — Python only applies it to strings >= 200
 * chars with a popular single character, which never applies to question
 * text or single keywords here).
 */
function findLongestMatch(
  a: string,
  b: string,
  alo: number,
  ahi: number,
  blo: number,
  bhi: number,
  b2j: Map<string, number[]>
): { a: number; b: number; size: number } {
  let besti = alo;
  let bestj = blo;
  let bestsize = 0;
  let j2len = new Map<number, number>();

  for (let i = alo; i < ahi; i++) {
    const newj2len = new Map<number, number>();
    const indices = b2j.get(a[i]) ?? [];
    for (const j of indices) {
      if (j < blo) continue;
      if (j >= bhi) break;
      const k = (j2len.get(j - 1) ?? 0) + 1;
      newj2len.set(j, k);
      if (k > bestsize) {
        besti = i - k + 1;
        bestj = j - k + 1;
        bestsize = k;
      }
    }
    j2len = newj2len;
  }

  return { a: besti, b: bestj, size: bestsize };
}

function getMatchingBlocks(a: string, b: string): Array<[number, number, number]> {
  const b2j = new Map<string, number[]>();
  for (let j = 0; j < b.length; j++) {
    const c = b[j];
    const list = b2j.get(c);
    if (list) list.push(j);
    else b2j.set(c, [j]);
  }

  const queue: Array<[number, number, number, number]> = [[0, a.length, 0, b.length]];
  const blocks: Array<[number, number, number]> = [];

  while (queue.length > 0) {
    const [alo, ahi, blo, bhi] = queue.pop()!;
    const { a: i, b: j, size: k } = findLongestMatch(a, b, alo, ahi, blo, bhi, b2j);
    if (k > 0) {
      blocks.push([i, j, k]);
      if (alo < i && blo < j) queue.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
    }
  }

  blocks.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return blocks;
}

export function sequenceMatcherRatio(a: string, b: string): number {
  const total = a.length + b.length;
  if (total === 0) return 1.0;
  const blocks = getMatchingBlocks(a, b);
  let matches = 0;
  for (const [, , size] of blocks) matches += size;
  return (2.0 * matches) / total;
}

/** Jaccard-style overlap where words count as equal if they're close enough
 * (handles typos like 'organel'/'organelle', 'cel'/'cell'). */
function fuzzyKeywordOverlap(
  queryKw: Set<string>,
  itemKw: Set<string>,
  threshold = 0.75
): number {
  if (queryKw.size === 0 || itemKw.size === 0) return 0.0;

  const remaining = new Set(itemKw);
  let matches = 0;
  for (const qw of queryKw) {
    let bestWord: string | null = null;
    let bestRatio = 0.0;
    for (const iw of remaining) {
      const ratio = sequenceMatcherRatio(qw, iw);
      if (ratio > bestRatio) {
        bestWord = iw;
        bestRatio = ratio;
      }
    }
    if (bestRatio >= threshold && bestWord !== null) {
      matches += 1;
      remaining.delete(bestWord);
    }
  }

  const union = queryKw.size + itemKw.size - matches;
  return union > 0 ? matches / union : 0.0;
}

function score(query: string, item: Item): number {
  const queryNorm = normalize(query);
  const itemNorm = normalize(item.question_text);
  const seqRatio = sequenceMatcherRatio(queryNorm, itemNorm);

  const queryKw = keywords(query);
  const itemKw = keywords(item.question_text);
  const overlap = fuzzyKeywordOverlap(queryKw, itemKw);

  return 0.3 * seqRatio + 0.7 * overlap;
}

export interface MatchResult {
  item: Item | null;
  confidence: number;
}

/** Return the best-matching item and a 0.0-1.0 confidence score. Never
 * refuses on its own — the caller (refusal.ts) decides what to do with a
 * low score. */
export function match(query: string, items: Item[]): MatchResult {
  if (items.length === 0 || query.trim().length === 0) {
    return { item: null, confidence: 0.0 };
  }

  let bestItem: Item | null = null;
  let bestScore = 0.0;
  for (const item of items) {
    const s = score(query, item);
    if (s > bestScore) {
      bestItem = item;
      bestScore = s;
    }
  }

  return { item: bestItem, confidence: Math.round(bestScore * 10000) / 10000 };
}
