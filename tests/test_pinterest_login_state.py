from __future__ import annotations

import json
import subprocess
import textwrap
import unittest

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def classify(state: dict) -> dict:
    script = textwrap.dedent(
        f"""
        const {{ classifyPinterestLoginState }} = require('./pinterest_login_state');
        const result = classifyPinterestLoginState({json.dumps(state)});
        process.stdout.write(JSON.stringify(result));
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


class PinterestLoginStateTest(unittest.TestCase):
    def test_redirect_to_homepage_is_login_required(self) -> None:
        # Regression: ISSUE-001 - fresh Pinterest profile redirected to home but
        # check-login reported an unknown create-surface failure.
        # Found by /qa on 2026-05-03.
        result = classify(
            {
                "url": "https://www.pinterest.com/",
                "loginWall": False,
                "hasCreateSurface": False,
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual("Pinterest login required at https://www.pinterest.com/", result["reason"])

    def test_pin_builder_surface_is_ok(self) -> None:
        result = classify(
            {
                "url": "https://www.pinterest.com/pin-builder/",
                "loginWall": False,
                "hasCreateSurface": True,
            }
        )

        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
