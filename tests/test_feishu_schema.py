from __future__ import annotations

import json
import subprocess
import tempfile
import unittest

from pathlib import Path

from pinterest_autopin.feishu_schema import resolve_base_token, setup_feishu_base


def completed(payload: dict, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=json.dumps(payload), stderr="")


class FakeLarkRunner:
    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}
        self.fields: dict[str, dict[str, dict]] = {}
        self.field_bodies: list[dict] = []
        self.records: dict[str, list[dict]] = {}
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.commands.append([str(item) for item in command])
        if "wiki" in command and "get_node" in command:
            return completed({"data": {"node": {"obj_type": "bitable", "obj_token": "app_from_wiki"}}})
        if "+table-list" in command:
            return completed({"data": {"items": list(self.tables.values())}})
        if "+table-create" in command:
            name = command[command.index("--name") + 1]
            table_id = f"tbl_{len(self.tables) + 1}"
            table = {"table_id": table_id, "table_name": name}
            self.tables[name] = table
            self.fields[table_id] = {}
            first_fields = json.loads(command[command.index("--fields") + 1])
            for body in first_fields:
                self._create_field(table_id, body)
            return completed({"data": {"table": table}})
        if "+field-list" in command:
            table_id = command[command.index("--table-id") + 1]
            return completed({"data": {"items": list(self.fields.get(table_id, {}).values())}})
        if "+field-create" in command:
            table_id = command[command.index("--table-id") + 1]
            body = json.loads(command[command.index("--json") + 1])
            return completed({"data": {"field": self._create_field(table_id, body)}})
        if "+record-list" in command:
            table_id = command[command.index("--table-id") + 1]
            return completed({"data": {"items": self.records.get(table_id, [])}})
        if "+record-upsert" in command:
            table_id = command[command.index("--table-id") + 1]
            fields = json.loads(command[command.index("--json") + 1])
            record = {"record_id": "rec_1", "fields": fields}
            self.records.setdefault(table_id, []).append(record)
            return completed({"data": {"record": record}})
        return completed({"ok": True})

    def _create_field(self, table_id: str, body: dict) -> dict:
        name = str(body["name"])
        captured = dict(body)
        captured["table_id"] = table_id
        self.field_bodies.append(captured)
        field = {"field_id": f"fld_{table_id}_{len(self.fields[table_id]) + 1}", "field_name": name}
        self.fields[table_id][name] = field
        return field


class FeishuSchemaTest(unittest.TestCase):
    def test_resolves_direct_base_url(self) -> None:
        token = resolve_base_token("https://example.feishu.cn/base/appABC123456?table=tbl1")

        self.assertEqual("appABC123456", token)

    def test_resolves_wiki_url_to_base_token(self) -> None:
        runner = FakeLarkRunner()

        token = resolve_base_token(
            "https://example.feishu.cn/wiki/wikiABC123456",
            command_runner=runner,
        )

        self.assertEqual("app_from_wiki", token)

    def test_setup_base_creates_schema_and_writes_config(self) -> None:
        runner = FakeLarkRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "feishu-worker-config.json"

            result = setup_feishu_base(
                base_url="https://example.feishu.cn/base/appABC123456",
                config_path=config_path,
                command_runner=runner,
            )

            config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual("appABC123456", config["app_token"])
        self.assertEqual("hermes_singleton", config["prepare_lock_mode"])
        self.assertEqual("hermes_singleton", config["publish_lock_mode"])
        self.assertIn("pins", config["tables"])
        self.assertIn("products", config["tables"])
        self.assertIn("product", config["tables"]["pins"]["fields"])
        self.assertNotIn("product_name", config["tables"]["pins"]["fields"])
        self.assertIn("product_name", config["tables"]["products"]["fields"])
        self.assertIn("final_image", config["tables"]["pins"]["fields"])
        self.assertIn("runtime_locks", config["tables"])
        product_link_body = next(body for body in runner.field_bodies if body["name"] == "商品")
        self.assertEqual(config["tables"]["products"]["table_id"], product_link_body["link_table"])
        self.assertTrue(any("+record-upsert" in command for command in runner.commands))
        self.assertTrue(any("prepare" in line for line in result.usage))


if __name__ == "__main__":
    unittest.main()
