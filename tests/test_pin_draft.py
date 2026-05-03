from __future__ import annotations

import unittest

from pinterest_autopin.pin_draft import DraftError, combined_description, validate_draft


class PinDraftTest(unittest.TestCase):
    def test_validates_structured_draft(self) -> None:
        draft = validate_draft(
            {
                "title": "Lamp",
                "description": "Warm lamp",
                "tags": ["#decor"],
                "altText": "Lamp on a table",
                "riskNotes": ["no obvious risk"],
                "confidence": "high",
            }
        )

        self.assertEqual("Lamp", draft.title)
        self.assertEqual(("#decor",), draft.tags)

    def test_missing_risk_notes_fails(self) -> None:
        with self.assertRaisesRegex(DraftError, "riskNotes"):
            validate_draft({"title": "x", "description": "y", "tags": ["z"], "altText": "a"})

    def test_combined_description_trims_tags_first(self) -> None:
        self.assertEqual("desc", combined_description("desc", ["#tag"], limit=5))


if __name__ == "__main__":
    unittest.main()
