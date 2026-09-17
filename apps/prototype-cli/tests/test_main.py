"""Tests for main.py's format_answer: the CLI has no image support, so a
diagram-bearing item gets a text note instead of the diagram itself."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import format_answer  # noqa: E402

BASE_ITEM = {
    "id": "bio-0001",
    "answer_text": "Mitochondria is the powerhouse of the cell.",
    "source": "NCERT Class 11 Biology, Ch 8",
}


class FormatAnswerTests(unittest.TestCase):
    def test_no_diagram_field_has_no_diagram_note(self):
        result = {"item": BASE_ITEM, "confidence": 0.9}
        output = format_answer(result)
        self.assertNotIn("diagram", output.lower())

    def test_diagram_field_adds_a_text_note(self):
        item_with_diagram = {**BASE_ITEM, "diagram": "bio-0001-mitochondria.svg"}
        result = {"item": item_with_diagram, "confidence": 0.9}
        output = format_answer(result)
        self.assertIn("diagram is available", output.lower())
        self.assertIn("web app", output.lower())


if __name__ == "__main__":
    unittest.main()
