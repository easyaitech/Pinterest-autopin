from __future__ import annotations

import json
import subprocess
import unittest

from unittest.mock import patch

from pinterest_autopin.feishu_cli import FeishuCli, FeishuCliError


class FeishuCliTest(unittest.TestCase):
    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_run_json_parses_output(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["feishu"], 0, stdout='{"ok": true}', stderr="")

        payload = FeishuCli(binary="feishu", retries=0).run_json(["x"])

        self.assertEqual({"ok": True}, payload)

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_non_json_output_fails(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["feishu"], 0, stdout="not json", stderr="")

        with self.assertRaisesRegex(FeishuCliError, "non-JSON"):
            FeishuCli(binary="feishu", retries=0).run_json(["x"])

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_create_record_sends_fields_json(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["feishu"], 0, stdout='{"record_id": "1"}', stderr="")

        FeishuCli(binary="feishu", app_token="app", retries=0).create_record("tbl", {"a": "b"})

        command = run_mock.call_args.args[0]
        self.assertIn("--fields-json", command)
        self.assertIn(json.dumps({"a": "b"}, ensure_ascii=True), command)

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_list_records_follows_page_tokens(self, run_mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(
                ["feishu"],
                0,
                stdout='{"records": [{"record_id": "1"}], "has_more": true, "page_token": "next"}',
                stderr="",
            ),
            subprocess.CompletedProcess(
                ["feishu"],
                0,
                stdout='{"records": [{"record_id": "2"}], "has_more": false}',
                stderr="",
            ),
        ]

        records = FeishuCli(binary="feishu", app_token="app", retries=0).list_records("tbl", page_size=1)

        self.assertEqual(["1", "2"], [record["record_id"] for record in records])
        second_command = run_mock.call_args_list[1].args[0]
        self.assertIn("--page-token", second_command)
        self.assertIn("next", second_command)

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_compare_update_sends_expected_fields(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["feishu"], 0, stdout='{"updated": true}', stderr="")

        FeishuCli(binary="feishu", app_token="app", retries=0).compare_update_record(
            "tbl",
            "rec",
            expected_fields={"owner": ""},
            fields={"owner": "run-1"},
        )

        command = run_mock.call_args.args[0]
        self.assertIn("compare-update", command)
        self.assertIn("--expected-fields-json", command)
        self.assertIn(json.dumps({"owner": ""}, ensure_ascii=True), command)

    def test_lark_cli_is_detected_from_binary_name(self) -> None:
        self.assertEqual("lark", FeishuCli(binary="/opt/homebrew/bin/lark-cli").resolved_flavor)

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_lark_list_records_uses_base_record_list_and_filters_locally(self, run_mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(
                ["lark-cli"],
                0,
                stdout=json.dumps(
                    {
                        "data": {
                            "items": [
                                {"record_id": "1", "fields": {"fld_status": "ready"}},
                                {"record_id": "2", "fields": {"fld_status": "paused"}},
                            ],
                            "has_more": True,
                        }
                    }
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                ["lark-cli"],
                0,
                stdout=json.dumps(
                    {
                        "data": {
                            "items": [
                                {"record_id": "3", "fields": {"fld_status": "ready"}},
                            ],
                            "has_more": False,
                        }
                    }
                ),
                stderr="",
            ),
        ]

        records = FeishuCli(binary="lark-cli", app_token="app", retries=0).list_records(
            "tbl", filter_expr='fld_status="ready"', page_size=2
        )

        self.assertEqual(["1", "3"], [record["record_id"] for record in records])
        first_command = run_mock.call_args_list[0].args[0]
        second_command = run_mock.call_args_list[1].args[0]
        self.assertIn("+record-list", first_command)
        self.assertIn("--base-token", first_command)
        self.assertIn("app", first_command)
        self.assertIn("--offset", second_command)
        self.assertIn("2", second_command)

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_lark_list_records_normalizes_table_shaped_output(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            ["lark-cli"],
            0,
            stdout=json.dumps(
                {
                    "data": {
                        "data": [["NO.001", ["pinterest_profile_publish"]]],
                        "field_id_list": ["fld_auto", "fld_lock_name"],
                        "fields": ["ID", "lock_name"],
                        "record_id_list": ["rec-1"],
                        "has_more": False,
                    }
                }
            ),
            stderr="",
        )

        records = FeishuCli(binary="lark-cli", app_token="app", retries=0).list_records(
            "tbl", filter_expr='fld_lock_name="pinterest_profile_publish"', page_size=20
        )

        self.assertEqual("rec-1", records[0]["record_id"])
        self.assertEqual("pinterest_profile_publish", records[0]["fields"]["fld_lock_name"])
        self.assertEqual("pinterest_profile_publish", records[0]["fields"]["lock_name"])

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_lark_update_uses_record_upsert(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["lark-cli"], 0, stdout='{"record_id": "1"}', stderr="")

        FeishuCli(binary="lark-cli", app_token="app", retries=0).update_record(
            "tbl", "rec", {"fld_status": "done"}
        )

        command = run_mock.call_args.args[0]
        self.assertIn("+record-upsert", command)
        self.assertIn("--record-id", command)
        self.assertIn("rec", command)
        self.assertIn(json.dumps({"fld_status": "done"}, ensure_ascii=True), command)

    def test_lark_compare_update_fails_closed_because_it_is_not_atomic(self) -> None:
        result = FeishuCli(binary="lark-cli", app_token="app").compare_update_record(
            "tbl",
            "rec",
            expected_fields={"owner": ""},
            fields={"owner": "run-1"},
        )

        self.assertFalse(result["updated"])
        self.assertIn("atomic compare-update", result["error"])

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_lark_record_attachment_upload_returns_file_token(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            ["lark-cli"],
            0,
            stdout='{"data": {"file_token": "token-1"}}',
            stderr="",
        )

        token = FeishuCli(binary="lark-cli", app_token="app", retries=0).upload_record_attachment(
            "tbl", "rec", "fld_file", "/tmp/image.png"
        )

        self.assertEqual("token-1", token)
        command = run_mock.call_args.args[0]
        self.assertIn("+record-upload-attachment", command)
        self.assertIn("--field-id", command)
        self.assertIn("fld_file", command)
        self.assertIn("image.png", command)
        self.assertNotIn("/tmp/image.png", command)
        self.assertEqual("/tmp", str(run_mock.call_args.kwargs["cwd"]))

    @patch("pinterest_autopin.feishu_cli.subprocess.run")
    def test_lark_download_uses_drive_download(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(["lark-cli"], 0, stdout='{"ok": true}', stderr="")

        FeishuCli(binary="lark-cli", app_token="app", retries=0).download_attachment(
            "token-1", "/tmp/out.png"
        )

        command = run_mock.call_args.args[0]
        self.assertIn("api", command)
        self.assertIn("GET", command)
        self.assertIn("/open-apis/drive/v1/medias/token-1/download", command)
        self.assertIn("out.png", command)
        self.assertNotIn("/tmp/out.png", command)
        self.assertEqual("/tmp", str(run_mock.call_args.kwargs["cwd"]))


if __name__ == "__main__":
    unittest.main()
