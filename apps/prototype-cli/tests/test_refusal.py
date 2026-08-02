"""Tests for refusal.py: the answer/refuse-and-flag decision."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import refusal  # noqa: E402

SAMPLE_ITEM = {
    "id": "bio-0001",
    "answer_text": "Mitochondria is the powerhouse of the cell.",
    "source": "NCERT Class 11 Biology, Ch 8",
}


class RefusalTests(unittest.TestCase):
    def setUp(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.log_path = Path(tmp_dir.name) / "flagged_questions.jsonl"

    def test_high_confidence_match_is_answered(self):
        result = refusal.decide(
            "What is the powerhouse of the cell?",
            SAMPLE_ITEM,
            confidence=0.9,
            log_path=self.log_path,
        )
        self.assertEqual(result["action"], "answer")
        self.assertEqual(result["item"]["id"], "bio-0001")
        self.assertFalse(self.log_path.exists())

    def test_low_confidence_is_refused_and_logged(self):
        result = refusal.decide(
            "What is the capital city of France?",
            None,
            confidence=0.1,
            log_path=self.log_path,
        )
        self.assertEqual(result["action"], "refuse")
        self.assertIsNone(result["item"])

        self.assertTrue(self.log_path.exists())
        with self.log_path.open(encoding="utf-8") as f:
            logged = json.loads(f.readline())
        self.assertEqual(logged["question_text"], "What is the capital city of France?")


if __name__ == "__main__":
    unittest.main()
