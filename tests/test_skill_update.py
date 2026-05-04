from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from pinterest_autopin import skill_update


class SkillUpdateTest(unittest.TestCase):
    def test_detects_newer_remote_skill_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "SKILL.md"
            local.write_text("---\nname: pinterest-autopin\nversion: 1.2.0\n---\n", encoding="utf-8")

            with patch(
                "pinterest_autopin.skill_update._fetch_text",
                return_value="---\nname: pinterest-autopin\nversion: 1.3.0\n---\n",
            ):
                payload = skill_update.check_skill_update(local_skill=local, update_url="https://example.com/SKILL.md")

        self.assertTrue(payload["checked"])
        self.assertTrue(payload["updateAvailable"])
        self.assertEqual("1.2.0", payload["localVersion"])
        self.assertEqual("1.3.0", payload["latestVersion"])
        self.assertIn("upgradeCommand", payload)

    def test_no_update_when_versions_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "SKILL.md"
            local.write_text("---\nname: pinterest-autopin\nversion: 1.3.0\n---\n", encoding="utf-8")

            with patch(
                "pinterest_autopin.skill_update._fetch_text",
                return_value="---\nname: pinterest-autopin\nversion: 1.3.0\n---\n",
            ):
                payload = skill_update.check_skill_update(local_skill=local, update_url="https://example.com/SKILL.md")

        self.assertTrue(payload["checked"])
        self.assertFalse(payload["updateAvailable"])

    def test_fetch_failure_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "SKILL.md"
            local.write_text("---\nname: pinterest-autopin\nversion: 1.3.0\n---\n", encoding="utf-8")

            with patch("pinterest_autopin.skill_update._fetch_text", side_effect=TimeoutError("slow")):
                payload = skill_update.check_skill_update(local_skill=local, update_url="https://example.com/SKILL.md")

        self.assertFalse(payload["checked"])
        self.assertFalse(payload["updateAvailable"])
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
