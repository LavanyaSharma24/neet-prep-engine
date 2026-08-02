"""Tests for retrieval.py: fuzzy/keyword matching against the item bank."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import retrieval  # noqa: E402


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.items = retrieval.load_items()

    def test_item_bank_loads(self):
        ids = {item["id"] for item in self.items}
        self.assertEqual(
            ids,
            {"bio-0001", "bio-0002", "bio-0003", "bio-0004", "bio-0005"},
        )

    def test_clear_match_returns_correct_item_with_high_confidence(self):
        item, confidence = retrieval.match(
            "Which organelle is known as the powerhouse of the cell?",
            self.items,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], "bio-0001")
        self.assertGreaterEqual(confidence, 0.55)

    def test_near_miss_typo_still_matches_correct_item(self):
        item, confidence = retrieval.match(
            "which organel is powerhoose of the cel",
            self.items,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], "bio-0001")
        self.assertGreaterEqual(confidence, 0.55)

    def test_unrelated_query_returns_low_confidence(self):
        item, confidence = retrieval.match(
            "What is the capital city of France?",
            self.items,
        )
        self.assertLess(confidence, 0.55)


if __name__ == "__main__":
    unittest.main()
