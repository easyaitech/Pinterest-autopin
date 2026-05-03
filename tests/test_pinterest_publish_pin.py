from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "pinterest_publish_pin.py"
SPEC = importlib.util.spec_from_file_location("pinterest_publish_pin", MODULE_PATH)
assert SPEC and SPEC.loader
pinterest_publish_pin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pinterest_publish_pin)


def fake_checks(chrome_cdp_reachable: bool = True) -> dict:
    return {
        "nodeScriptExists": True,
        "nodePath": "/usr/bin/node",
        "sipsPath": "/usr/bin/sips",
        "playwrightInstalled": True,
        "chromeCdp": {"reachable": chrome_cdp_reachable},
    }


class PinterestPublishPinValidationTest(unittest.TestCase):
    def args(self, *, chrome_profile: str | None = None, no_default: bool = True) -> argparse.Namespace:
        return argparse.Namespace(
            image=None,
            title=None,
            board=None,
            link=None,
            description=None,
            alt_text=None,
            chrome_profile=chrome_profile,
            no_default_chrome_profile=no_default,
        )

    def make_image(self) -> str:
        image = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image.write(b"not a real image, but validate only checks path existence")
        image.close()
        self.addCleanup(lambda: Path(image.name).unlink(missing_ok=True))
        return image.name

    def valid_payload(self) -> dict:
        return {
            "image": self.make_image(),
            "title": "QA Pin",
            "board": "Home Decor",
            "link": "https://example.com",
            "description": "Description",
            "altText": "Alt text",
            "chromeProfile": "",
        }

    def test_valid_payload_passes_validate_mode(self) -> None:
        errors, warnings = pinterest_publish_pin.validate_payload(
            self.valid_payload(), fake_checks(), "validate"
        )

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_non_string_fields_fail_before_publish(self) -> None:
        payload = self.valid_payload()
        payload["title"] = 123

        errors, warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(), "validate"
        )

        self.assertIn("title must be a string", errors)
        self.assertEqual([], warnings)

    def test_image_path_must_be_absolute(self) -> None:
        payload = self.valid_payload()
        payload["image"] = "relative.png"

        errors, _warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(), "validate"
        )

        self.assertIn("image must be an absolute path: relative.png", errors)

    def test_link_must_be_absolute_http_url(self) -> None:
        payload = self.valid_payload()
        payload["link"] = "example.com/product"

        errors, _warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(), "validate"
        )

        self.assertIn("link must be an absolute http(s) URL: example.com/product", errors)

    def test_chrome_profile_must_be_absolute(self) -> None:
        payload = self.valid_payload()
        payload["chromeProfile"] = "profile"

        errors, _warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(chrome_cdp_reachable=False), "test"
        )

        self.assertIn("chromeProfile must be an absolute path: profile", errors)

    def test_chrome_profile_allows_test_mode_without_cdp(self) -> None:
        with tempfile.TemporaryDirectory() as profile_dir:
            payload = self.valid_payload()
            payload["chromeProfile"] = profile_dir

            errors, warnings = pinterest_publish_pin.validate_payload(
                payload, fake_checks(chrome_cdp_reachable=False), "test"
            )

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_missing_chrome_profile_and_cdp_fails_in_test_mode(self) -> None:
        payload = self.valid_payload()

        errors, _warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(chrome_cdp_reachable=False), "test"
        )

        self.assertIn(
            "chromeProfile is required in test/final mode unless an existing "
            "Chrome CDP session is reachable",
            errors,
        )

    def test_missing_chrome_profile_directory_warns_but_can_be_created(self) -> None:
        with tempfile.TemporaryDirectory() as parent_dir:
            payload = self.valid_payload()
            payload["chromeProfile"] = str(Path(parent_dir) / "missing-pinterest-profile")

            errors, warnings = pinterest_publish_pin.validate_payload(
                payload, fake_checks(chrome_cdp_reachable=False), "test"
            )

        self.assertEqual([], errors)
        self.assertIn(
            "chromeProfile directory does not exist yet; it will be created, "
            "but Pinterest login may be required",
            warnings,
        )

    def test_missing_board_warns_in_validate_but_fails_in_execution_modes(self) -> None:
        payload = self.valid_payload()
        payload["board"] = ""

        validate_errors, validate_warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(), "validate"
        )
        test_errors, test_warnings = pinterest_publish_pin.validate_payload(
            payload, fake_checks(), "test"
        )

        self.assertEqual([], validate_errors)
        self.assertIn(
            "board is empty; validate mode allows this, but real execution requires it",
            validate_warnings,
        )
        self.assertIn(
            "board is required in test/final mode to avoid posting to the wrong board",
            test_errors,
        )
        self.assertEqual([], test_warnings)

    def test_normalize_payload_preserves_bad_types_for_validation(self) -> None:
        payload = pinterest_publish_pin.normalize_payload({"title": 123}, self.args())

        self.assertEqual(123, payload["title"])

    def test_normalize_payload_accepts_chrome_profile_alias(self) -> None:
        payload = pinterest_publish_pin.normalize_payload(
            {"chrome_profile": "/tmp/profile"}, self.args()
        )

        self.assertEqual("/tmp/profile", payload["chromeProfile"])

    def test_normalize_payload_uses_default_profile_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            default_profile = Path(temp_dir) / "default-profile"
            config_path = Path(temp_dir) / "config.json"
            with patch.object(pinterest_publish_pin, "DEFAULT_CHROME_PROFILE", default_profile):
                with patch.object(pinterest_publish_pin, "CONFIG_PATH", config_path):
                    with patch.dict(
                        os.environ, {pinterest_publish_pin.PROFILE_ENV_VAR: ""}, clear=False
                    ):
                        payload, profile_meta = pinterest_publish_pin.normalize_payload_with_meta(
                            {}, self.args(no_default=False)
                        )

        self.assertEqual(str(default_profile), payload["chromeProfile"])
        self.assertEqual("default", profile_meta["source"])

    def test_normalize_payload_uses_env_profile_before_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_profile = str(Path(temp_dir) / "env-profile")
            config_path = Path(temp_dir) / "config.json"
            with patch.object(pinterest_publish_pin, "CONFIG_PATH", config_path):
                with patch.dict(
                    os.environ, {pinterest_publish_pin.PROFILE_ENV_VAR: env_profile}, clear=False
                ):
                    payload, profile_meta = pinterest_publish_pin.normalize_payload_with_meta(
                        {}, self.args(no_default=False)
                    )

        self.assertEqual(env_profile, payload["chromeProfile"])
        self.assertEqual(
            f"env:{pinterest_publish_pin.PROFILE_ENV_VAR}",
            profile_meta["source"],
        )

    def test_normalize_payload_uses_config_profile_before_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_profile = str(Path(temp_dir) / "config-profile")
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"chromeProfile": config_profile}), encoding="utf-8"
            )
            with patch.object(pinterest_publish_pin, "CONFIG_PATH", config_path):
                with patch.dict(
                    os.environ, {pinterest_publish_pin.PROFILE_ENV_VAR: ""}, clear=False
                ):
                    payload, profile_meta = pinterest_publish_pin.normalize_payload_with_meta(
                        {}, self.args(no_default=False)
                    )

        self.assertEqual(config_profile, payload["chromeProfile"])
        self.assertEqual(f"config:{config_path}", profile_meta["source"])

    def test_no_default_chrome_profile_preserves_empty_profile(self) -> None:
        payload, profile_meta = pinterest_publish_pin.normalize_payload_with_meta({}, self.args())

        self.assertEqual("", payload["chromeProfile"])
        self.assertEqual("none", profile_meta["source"])

    def test_expand_profile_path_accepts_tilde_and_environment_variables(self) -> None:
        with patch.dict(os.environ, {"PIN_PROFILE_ROOT": "/tmp/pinterest"}, clear=False):
            payload = pinterest_publish_pin.normalize_payload(
                {"chromeProfile": "$PIN_PROFILE_ROOT/profile"}, self.args()
            )

        self.assertEqual("/tmp/pinterest/profile", payload["chromeProfile"])

    def test_init_chrome_profile_creates_directory_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "profile"
            config_path = Path(temp_dir) / "config.json"

            with patch.object(pinterest_publish_pin, "CONFIG_PATH", config_path):
                pinterest_publish_pin.init_chrome_profile(str(profile_dir))

            self.assertTrue(profile_dir.is_dir())
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual({"chromeProfile": str(profile_dir)}, config_payload)


if __name__ == "__main__":
    unittest.main()
