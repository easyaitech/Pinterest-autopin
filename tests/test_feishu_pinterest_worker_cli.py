from __future__ import annotations

import json
import subprocess
import tempfile
import unittest

from pathlib import Path


class FeishuPinterestWorkerCliTest(unittest.TestCase):
    def test_help_documents_chrome_cdp_mode(self) -> None:
        completed = subprocess.run(
            [
                "python3",
                "tools/feishu_pinterest_worker.py",
                "--help",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode)
        self.assertIn("--use-chrome-cdp", completed.stdout)

    def test_missing_hermes_identity_fails_before_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "app_token": "app",
                        "tables": {
                            "pins": {
                                "table_id": "pins",
                                "fields": {
                                    "status": "status",
                                    "scheduled_at": "scheduled_at",
                                    "publisher_run_id": "publisher_run_id",
                                    "claim_expires_at": "claim_expires_at",
                                    "prepare_run_id": "prepare_run_id",
                                    "prepare_expires_at": "prepare_expires_at",
                                    "last_error": "last_error",
                                },
                            },
                            "brands": {"table_id": "brands", "fields": {}},
                            "runs": {"table_id": "runs", "fields": {}},
                            "runtime_locks": {
                                "table_id": "locks",
                                "fields": {
                                    "lock_name": "lock_name",
                                    "owner_run_id": "owner_run_id",
                                    "owner_hermes_run_id": "owner_hermes_run_id",
                                    "lock_expires_at": "lock_expires_at",
                                    "locked_at": "locked_at",
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    "tools/feishu_pinterest_worker.py",
                    "doctor",
                    "--config",
                    str(config_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("Hermes run identity is required", completed.stdout)


if __name__ == "__main__":
    unittest.main()
