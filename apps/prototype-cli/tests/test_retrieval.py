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
            {
                "bio-0001", "bio-0002", "bio-0003", "bio-0004", "bio-0005",
                "bio-0006", "bio-0007", "bio-0008", "bio-0009",
                "chem-0001", "chem-0002", "chem-0003", "chem-0004",
                "chem-0005", "chem-0006", "chem-0007", "chem-0008",
                "chem-0009", "chem-0010", "chem-0011", "chem-0012",
                "chem-0013", "chem-0014", "chem-0015", "chem-0016",
                "chem-0017", "chem-0018", "chem-0019", "chem-0020",
                "chem-0021", "chem-0022", "chem-0023", "chem-0024",
                "chem-0025", "chem-0026", "chem-0027", "chem-0028",
                "chem-0029", "chem-0030",
            },
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

    def test_pasted_mcq_options_still_matches_same_item(self):
        bare_item, bare_confidence = retrieval.match(
            "Which organelle is known as the powerhouse of the cell?",
            self.items,
        )
        pasted_item, pasted_confidence = retrieval.match(
            "Which organelle is known as the powerhouse of the cell?\n"
            "A) Nucleus\n"
            "B) Mitochondria\n"
            "C) Ribosome\n"
            "D) Golgi apparatus",
            self.items,
        )
        self.assertEqual(pasted_item["id"], bare_item["id"])
        self.assertGreaterEqual(pasted_confidence, 0.55)

    def test_decimal_number_is_not_treated_as_mcq_option(self):
        query = "What is the pH of 0.1 M HCl?"
        self.assertEqual(retrieval._strip_mcq_options(query), query)


if __name__ == "__main__":
    unittest.main()
