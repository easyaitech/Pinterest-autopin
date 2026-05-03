from __future__ import annotations

import argparse
import importlib.util
import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "pinterest_publish_pin.py"
SPEC = importlib.util.spec_from_file_location("pinterest_publish_pin_check_login", MODULE_PATH)
assert SPEC and SPEC.loader
pinterest_publish_pin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pinterest_publish_pin)


class PinterestCheckLoginTest(unittest.TestCase):
    def args(self, chrome_profile: str) -> argparse.Namespace:
        return argparse.Namespace(
            image=None,
            title=None,
            board=None,
            link=None,
            description=None,
            alt_text=None,
            chrome_profile=chrome_profile,
            no_default_chrome_profile=True,
        )

    def test_check_login_validation_does_not_require_image_title_or_board(self) -> None:
        with tempfile.TemporaryDirectory() as profile:
            payload, _meta = pinterest_publish_pin.normalize_payload_with_meta({}, self.args(profile))
            errors, warnings = pinterest_publish_pin.validate_payload(
                payload,
                {
                    "nodeScriptExists": True,
                    "nodePath": "/usr/bin/node",
                    "sipsPath": "",
                    "playwrightInstalled": True,
                    "chromeCdp": {"reachable": False},
                },
                "check-login",
            )

        self.assertEqual([], errors)
        self.assertEqual(["sips not found; image compression will fail on macOS-only path"], warnings)

    @patch("pinterest_autopin.publisher.subprocess.run")
    def test_publisher_check_login_calls_safe_mode(self, run_mock) -> None:
        from pinterest_autopin.publisher import PinterestPublisher

        run_mock.return_value = subprocess.CompletedProcess(
            ["cmd"], 0, stdout='{"ok": true, "mode": "check-login"}', stderr=""
        )

        result = PinterestPublisher(timeout=5).check_login(chrome_profile="/tmp/profile")

        self.assertTrue(result.ok)
        command = run_mock.call_args.args[0]
        self.assertIn("--mode", command)
        self.assertIn("check-login", command)


if __name__ == "__main__":
    unittest.main()
