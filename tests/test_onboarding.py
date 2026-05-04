from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pinterest_autopin.onboarding import run_onboarding


def completed(stdout: dict, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=json.dumps(stdout), stderr="")


def no_update() -> dict:
    return {
        "checked": True,
        "updateAvailable": False,
        "localVersion": "1.3.0",
        "latestVersion": "1.3.0",
        "reason": "Pinterest AutoPin skill is current at 1.3.0.",
    }


def config_payload() -> dict:
    return {
        "app_token": "app",
        "feishu_cli": "lark-cli",
        "feishu_cli_flavor": "lark",
        "required_hermes_secrets": [],
        "tables": {
            "pins": {
                "table_id": "pins",
                "fields": {
                    "status": "fld_status",
                    "scheduled_at": "fld_scheduled",
                    "publisher_run_id": "fld_publisher",
                    "claim_expires_at": "fld_claim",
                    "last_attempt_at": "fld_last_attempt",
                    "publish_attempts": "fld_attempts",
                    "prepare_run_id": "fld_prepare",
                    "prepare_expires_at": "fld_prepare_expires",
                    "last_error": "fld_error",
                    "source_image": "fld_source_image",
                    "processed_image": "fld_processed_image",
                    "draft_title": "fld_draft_title",
                    "draft_description": "fld_draft_description",
                    "draft_tags": "fld_draft_tags",
                    "draft_alt_text": "fld_draft_alt_text",
                    "final_image": "fld_final_image",
                    "final_title": "fld_final_title",
                    "final_description": "fld_final_description",
                    "final_tags": "fld_final_tags",
                    "final_alt_text": "fld_final_alt_text",
                    "final_board": "fld_final_board",
                    "product_link": "fld_product_link",
                    "pin_url": "fld_pin_url",
                    "published_at": "fld_published_at",
                },
            },
            "brands": {"table_id": "brands", "fields": {}},
            "runs": {"table_id": "runs", "fields": {}},
            "runtime_locks": {
                "table_id": "locks",
                "fields": {
                    "lock_name": "fld_lock_name",
                    "owner_run_id": "fld_owner",
                    "owner_hermes_run_id": "fld_hermes_owner",
                    "lock_expires_at": "fld_expires",
                    "locked_at": "fld_locked",
                },
            },
        },
    }


class OnboardingTest(unittest.TestCase):
    def test_missing_config_returns_guided_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = run_onboarding(
                config_path=Path(temp_dir) / "missing.json",
                local_dev=True,
                check_pinterest_login=False,
                which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                command_runner=lambda *args, **kwargs: completed(
                    {"ok": True, "chromeProfile": str(Path(temp_dir) / "profile")}
                ),
                cdp_reachable=lambda: False,
                update_checker=no_update,
            )

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["readyForPrepare"])
        self.assertIn("feishu_config", [item["id"] for item in payload["nextActions"]])

    def test_ready_for_prepare_but_publish_requires_singleton_and_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config_payload()), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()

            def runner(command, **_kwargs):
                joined = " ".join(str(item) for item in command)
                if "auth check" in joined:
                    return completed({"ok": True, "missing": None})
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                payload = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    check_pinterest_login=False,
                    prepare_singleton_confirmed=True,
                    target="prepare",
                    which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                    command_runner=runner,
                    cdp_reachable=lambda: False,
                    update_checker=no_update,
                )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readyForPrepare"])
        self.assertFalse(payload["readyForPublish"])
        self.assertIn("pinterest_login", [item["id"] for item in payload["nextActions"]])
        self.assertIn("publish_singleton", [item["id"] for item in payload["nextActions"]])

    def test_ready_for_publish_when_login_and_singleton_are_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config_payload()), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()
            login_commands = []

            def runner(command, **_kwargs):
                joined = " ".join(str(item) for item in command)
                if "auth check" in joined:
                    return completed({"ok": True, "missing": None})
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                if "--mode" in command and "check-login" in command:
                    login_commands.append(command)
                    return completed({"ok": True})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                payload = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    prepare_singleton_confirmed=True,
                    publish_singleton_confirmed=True,
                    use_chrome_cdp=True,
                    which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                    command_runner=runner,
                    cdp_reachable=lambda: True,
                    update_checker=no_update,
                )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readyForPrepare"])
        self.assertTrue(payload["readyForPublish"])
        self.assertEqual([], payload["nextActions"])
        self.assertIn("--no-default-chrome-profile", login_commands[0])
        self.assertNotIn("--chrome-profile", login_commands[0])
        login_step = next(step for step in payload["steps"] if step["id"] == "pinterest_login")
        self.assertEqual(["--use-chrome-cdp"], login_step["details"]["publishArgs"])

    def test_onboarding_uses_profile_login_when_cdp_is_reachable_but_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config_payload()), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()
            login_commands = []

            def runner(command, **_kwargs):
                joined = " ".join(str(item) for item in command)
                if "auth check" in joined:
                    return completed({"ok": True, "missing": None})
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                if "--mode" in command and "check-login" in command:
                    login_commands.append(command)
                    return completed({"ok": True})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                payload = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    prepare_singleton_confirmed=True,
                    publish_singleton_confirmed=True,
                    which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                    command_runner=runner,
                    cdp_reachable=lambda: True,
                    update_checker=no_update,
                )

        self.assertTrue(payload["readyForPublish"])
        self.assertEqual(
            str(profile),
            login_commands[0][login_commands[0].index("--chrome-profile") + 1],
        )
        self.assertNotIn("--no-default-chrome-profile", login_commands[0])
        login_step = next(step for step in payload["steps"] if step["id"] == "pinterest_login")
        self.assertEqual([], login_step["details"]["publishArgs"])

    def test_onboarding_blocks_requested_cdp_when_port_is_not_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config_payload()), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()
            login_commands = []

            def runner(command, **_kwargs):
                joined = " ".join(str(item) for item in command)
                if "auth check" in joined:
                    return completed({"ok": True, "missing": None})
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                if "--mode" in command and "check-login" in command:
                    login_commands.append(command)
                    return completed({"ok": True})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                payload = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    prepare_singleton_confirmed=True,
                    publish_singleton_confirmed=True,
                    use_chrome_cdp=True,
                    which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                    command_runner=runner,
                    cdp_reachable=lambda: False,
                    update_checker=no_update,
                )

        self.assertFalse(payload["readyForPublish"])
        self.assertEqual([], login_commands)
        login_step = next(step for step in payload["steps"] if step["id"] == "pinterest_login")
        self.assertIn("Chrome CDP is not reachable", login_step["details"]["reason"])

    def test_onboarding_uses_profile_login_when_cdp_is_not_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config_payload()), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()
            login_commands = []

            def runner(command, **_kwargs):
                joined = " ".join(str(item) for item in command)
                if "auth check" in joined:
                    return completed({"ok": True, "missing": None})
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                if "--mode" in command and "check-login" in command:
                    login_commands.append(command)
                    return completed({"ok": True})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                payload = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    prepare_singleton_confirmed=True,
                    publish_singleton_confirmed=True,
                    which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                    command_runner=runner,
                    cdp_reachable=lambda: False,
                    update_checker=no_update,
                )

        self.assertTrue(payload["readyForPublish"])
        self.assertEqual(
            str(profile),
            login_commands[0][login_commands[0].index("--chrome-profile") + 1],
        )
        self.assertNotIn("--no-default-chrome-profile", login_commands[0])

    def test_bitable_prepare_does_not_require_lark_auth_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = config_payload()
            payload["feishu_cli"] = "feishu"
            payload["feishu_cli_flavor"] = "bitable"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            profile = Path(temp_dir) / "profile"
            profile.mkdir()

            def runner(command, **_kwargs):
                if "--print-chrome-profile" in command:
                    return completed({"ok": True, "chromeProfile": str(profile), "chromeProfileSource": "test"})
                return completed({"ok": True})

            with patch("pinterest_autopin.onboarding.FeishuPinterestWorker") as worker_cls:
                worker_cls.from_config.return_value.doctor.return_value.errors = ()
                onboarded = run_onboarding(
                    config_path=config_path,
                    local_dev=True,
                    check_pinterest_login=False,
                    target="prepare",
                    which=lambda name: "/usr/bin/" + name if name in {"node", "feishu"} else None,
                    command_runner=runner,
                    update_checker=no_update,
                )

        self.assertTrue(onboarded["ok"])
        self.assertTrue(onboarded["readyForPrepare"])
        self.assertNotIn("feishu_auth", [item["id"] for item in onboarded["steps"]])

    def test_update_available_returns_nonblocking_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = run_onboarding(
                config_path=Path(temp_dir) / "missing.json",
                local_dev=True,
                check_pinterest_login=False,
                which=lambda name: "/usr/bin/" + name if name in {"node", "lark-cli"} else None,
                command_runner=lambda *args, **kwargs: completed(
                    {"ok": True, "chromeProfile": str(Path(temp_dir) / "profile")}
                ),
                update_checker=lambda: {
                    "checked": True,
                    "updateAvailable": True,
                    "localVersion": "1.2.0",
                    "latestVersion": "1.3.0",
                    "reason": "Pinterest AutoPin skill 1.2.0 can be upgraded to 1.3.0.",
                    "upgradeCommand": "git pull --ff-only && npm install",
                },
            )

        update_step = next(step for step in payload["steps"] if step["id"] == "skill_update")
        self.assertEqual("action_required", update_step["status"])
        self.assertFalse(update_step["blocking"])
        self.assertIn("skill_update", [item["id"] for item in payload["nextActions"]])


if __name__ == "__main__":
    unittest.main()
