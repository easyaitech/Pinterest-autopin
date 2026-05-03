from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from pinterest_autopin.image_prepare import prepare_image


class ImagePrepareTest(unittest.TestCase):
    def test_copies_source_to_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.jpg"
            source.write_bytes(b"image")
            output_dir = Path(temp_dir) / "out"

            result = prepare_image(source, output_dir)

            self.assertEqual(b"image", result.output_path.read_bytes())
            self.assertEqual(output_dir, result.output_path.parent)


if __name__ == "__main__":
    unittest.main()
