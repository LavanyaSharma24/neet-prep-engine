"""Fuzzy/keyword matching of a typed question against the local item bank.

No LLM, no external API calls — stdlib only. v0 scope: NEET Biology, text only.
"""
import json
import string
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ITEM_BANK_GLOB = "item_bank/biology/*.jsonl"

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "in", "on", "at",
    "to", "for", "and", "or", "which", "what", "who", "whom", "does",
    "do", "did", "how", "why", "when", "where", "called", "known", "as",
    "this", "that", "these", "those", "it", "its", "with", "by", "term",
    "describes",
}


def _normalize(text):
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text


def _keywords(text):
    return {word for word in _normalize(text).split() if word and word not in _STOPWORDS}


def load_items(glob_pattern=DEFAULT_ITEM_BANK_GLOB, root=REPO_ROOT):
    """Load every item from *.jsonl files matching glob_pattern under root."""
    items = []
    for path in sorted(root.glob(glob_pattern)):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
    return items


def _fuzzy_keyword_overlap(query_kw, item_kw, threshold=0.75):
    """Jaccard-style overlap where words count as equal if they're close
    enough (handles typos like 'organel'/'organelle', 'cel'/'cell')."""
    if not query_kw or not item_kw:
        return 0.0

    remaining = set(item_kw)
    matches = 0
    for qw in query_kw:
        best_word, best_ratio = None, 0.0
        for iw in remaining:
            ratio = SequenceMatcher(None, qw, iw).ratio()
            if ratio > best_ratio:
                best_word, best_ratio = iw, ratio
        if best_ratio >= threshold:
            matches += 1
            remaining.discard(best_word)

    union = len(query_kw) + len(item_kw) - matches
    return matches / union if union else 0.0


def _score(query, item):
    query_norm = _normalize(query)
    item_norm = _normalize(item["question_text"])
    seq_ratio = SequenceMatcher(None, query_norm, item_norm).ratio()

    query_kw = _keywords(query)
    item_kw = _keywords(item["question_text"])
    overlap = _fuzzy_keyword_overlap(query_kw, item_kw)

    return 0.3 * seq_ratio + 0.7 * overlap


def match(query, items=None):
    """Return (best_item_or_None, confidence) for query against items.

    confidence is 0.0-1.0. Caller decides what to do with a low score —
    this function never refuses, it only scores.
    """
    if items is None:
        items = load_items()
    if not items or not query.strip():
        return None, 0.0

    best_item, best_score = None, 0.0
    for item in items:
        score = _score(query, item)
        if score > best_score:
            best_item, best_score = item, score

    return best_item, round(best_score, 4)
