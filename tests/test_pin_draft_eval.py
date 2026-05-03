from __future__ import annotations

import json
import unittest

from pathlib import Path


class PinDraftEvalTest(unittest.TestCase):
    def test_eval_samples_have_real_inputs(self) -> None:
        samples = json.loads((Path(__file__).resolve().parents[1] / "evals" / "pin_draft_samples.json").read_text())

        self.assertGreaterEqual(len(samples), 5)
        for sample in samples:
            self.assertTrue(sample["product_name"])
            self.assertTrue(sample["product_link"].startswith("https://"))
            self.assertTrue(sample["expected_facts"])


if __name__ == "__main__":
    unittest.main()
