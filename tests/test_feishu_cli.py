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


if __name__ == "__main__":
    unittest.main()
