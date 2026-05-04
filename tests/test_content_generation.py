from __future__ import annotations

import struct
import tempfile
import unittest

from pathlib import Path

from pinterest_autopin.content_generation import analyze_image, generate_pin_draft, quality_gate


def png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


class ContentGenerationTest(unittest.TestCase):
    def test_generates_search_intent_etsy_conversion_and_quality_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "blue-ceramic-mug-gift.png"
            image.write_bytes(png_header(1000, 1500))

            draft = generate_pin_draft(
                {
                    "product_name": "Handmade Mug",
                    "product_description": "A ceramic mug for quiet mornings.",
                    "keywords": "coffee gift cozy",
                },
                image,
            )

        self.assertIn("Mug", draft.title)
        self.assertIn("Gift", draft.title)
        self.assertIn("Etsy", draft.description)
        self.assertIn("#EtsyFinds", draft.tags)
        self.assertGreaterEqual(draft.quality_score, 80)
        self.assertEqual("portrait", draft.image_signals.orientation)

    def test_image_analysis_uses_dimensions_and_filename_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "minimal-wall-art-print.png"
            image.write_bytes(png_header(900, 1200))

            signals = analyze_image(image)

        self.assertEqual((900, 1200), (signals.width, signals.height))
        self.assertIn("print", signals.product_terms)
        self.assertIn("minimal", signals.style_terms)

    def test_product_name_is_source_of_truth_over_old_draft_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "ceramic-mug.png"
            image.write_bytes(png_header(1000, 1500))

            draft = generate_pin_draft(
                {
                    "product_name": "Ceramic Coffee Mug",
                    "draft_title": "Old Generic Draft",
                    "product_description": "A ceramic mug for quiet mornings.",
                },
                image,
            )

        self.assertIn("Ceramic Coffee Mug", draft.title)
        self.assertNotIn("Old Generic Draft", draft.title)

    def test_quality_gate_rejects_generic_non_etsy_copy(self) -> None:
        score, notes = quality_gate(
            {
                "title": "Nice Product",
                "description": "Pretty thing.",
                "tags": "#Product",
                "alt_text": "",
            },
            product_terms={"mug"},
        )

        self.assertLess(score, 80)
        self.assertTrue(any("Etsy" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
