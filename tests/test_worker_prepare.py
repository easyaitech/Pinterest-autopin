from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from pinterest_autopin.hermes_runtime import RuntimeContext
from pinterest_autopin.publisher import PublisherResult
from pinterest_autopin.worker import FeishuPinterestWorker
from pinterest_autopin.worker_config import TableConfig, WorkerConfig


class FakeStore:
    def __init__(self, records: list[dict] | None = None, products: list[dict] | None = None) -> None:
        self.records = records or []
        self.products = products or []
        self.updates: list[tuple[str, str, dict]] = []
        self.uploaded: list[str] = []

    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict]:
        records = self.products if table_id == "products" else self.records
        if "record_id=" in filter_expr:
            record_id = filter_expr.split('"')[1]
            return [record for record in records if record["record_id"] == record_id]
        return records

    def update_record(self, table_id: str, record_id: str, fields: dict) -> dict:
        self.updates.append((table_id, record_id, fields))
        record = next(item for item in self.records if item["record_id"] == record_id)
        record["fields"].update(fields)
        return record

    def compare_update_record(self, table_id: str, record_id: str, *, expected_fields: dict, fields: dict) -> dict:
        record = next(item for item in self.records if item["record_id"] == record_id)
        current = record["fields"]
        for key, value in expected_fields.items():
            if current.get(key, "") != value:
                return {"updated": False}
        self.updates.append((table_id, record_id, fields))
        current.update(fields)
        return {"updated": True}

    def create_record(self, table_id: str, fields: dict) -> dict:
        return {}

    def download_attachment(self, file_token: str, output_path: str) -> str:
        Path(output_path).write_text(f"source:{file_token}", encoding="utf-8")
        return output_path

    def upload_attachment(self, file_path: str) -> str:
        self.uploaded.append(file_path)
        return "processed-token"


class NoopPublisher:
    def check_login(self, *, chrome_profile: str = "", use_chrome_cdp: bool = False) -> PublisherResult:
        return PublisherResult(True, "check-login")

    def publish(
        self,
        request,
        *,
        input_path: Path,
        chrome_profile: str = "",
        use_chrome_cdp: bool = False,
    ) -> PublisherResult:
        return PublisherResult(True, "final")


def config() -> WorkerConfig:
    return WorkerConfig(
        "app",
        TableConfig("pins"),
        TableConfig("brands"),
        TableConfig("runs"),
        TableConfig("locks"),
        products=TableConfig("products"),
    )


def product_config() -> WorkerConfig:
    return WorkerConfig(
        "app",
        TableConfig("pins", {"product": "product", "status": "status"}),
        TableConfig("brands"),
        TableConfig("runs"),
        TableConfig("locks"),
        products=TableConfig(
            "products",
            {
                "product_name": "product_name",
                "product_description": "product_description",
                "product_link": "product_link",
            },
        ),
    )


class WorkerPrepareTest(unittest.TestCase):
    def test_prepare_with_no_records_reports_no_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = FeishuPinterestWorker(
                config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                FakeStore(),
                NoopPublisher(),
            )

            result = worker.prepare(limit=3)

        self.assertTrue(result.ok)
        self.assertEqual(0, result.processed)

    def test_prepare_claims_builds_draft_uploads_image_and_moves_to_review(self) -> None:
        record = {
            "record_id": "pin-1",
            "fields": {
                "status": "待 AI 生成",
                "product": [{"record_id": "product-1"}],
                "source_image": [{"file_token": "source-token", "name": "source.jpg"}],
            },
        }
        product = {
            "record_id": "product-1",
            "fields": {
                "product_name": "Handmade Mug",
                "product_description": "A ceramic mug for quiet mornings.",
                "product_link": "https://example.etsy.com/listing/1",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore([record], [product])
            worker = FeishuPinterestWorker(
                config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                store,
                NoopPublisher(),
            )

            result = worker.prepare(limit=1)

        self.assertTrue(result.ok)
        self.assertEqual(1, result.processed)
        self.assertEqual("待人工审核", record["fields"]["status"])
        self.assertIn("Handmade Mug", record["fields"]["draft_title"])
        self.assertIn("Gift", record["fields"]["draft_title"])
        self.assertIn("Etsy", record["fields"]["draft_description"])
        self.assertIn("#EtsyFinds", record["fields"]["draft_tags"])
        self.assertEqual("processed-token", record["fields"]["processed_image"][0]["file_token"])
        self.assertTrue(store.uploaded)

    def test_prepare_atomic_claim_miss_skips_record(self) -> None:
        record = {
            "record_id": "pin-1",
            "fields": {
                "status": "待 AI 生成",
                "source_image": [{"file_token": "source-token", "name": "source.jpg"}],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore([record])

            def racing_compare(table_id: str, record_id: str, *, expected_fields: dict, fields: dict) -> dict:
                record["fields"]["status"] = "AI 生成中"
                return {"updated": False}

            store.compare_update_record = racing_compare  # type: ignore[method-assign]
            worker = FeishuPinterestWorker(
                config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                store,
                NoopPublisher(),
            )

            result = worker.prepare(limit=1)

        self.assertTrue(result.ok)
        self.assertEqual(0, result.processed)
        self.assertEqual(1, result.skipped)

    def test_product_check_requires_linked_complete_etsy_product(self) -> None:
        record = {
            "record_id": "pin-1",
            "fields": {
                "status": "待 AI 生成",
                "product": [{"record_id": "product-1"}],
                "source_image": [{"file_token": "source-token", "name": "source.jpg"}],
            },
        }
        product = {
            "record_id": "product-1",
            "fields": {
                "product_name": "Handmade Mug",
                "product_description": "Too short",
                "product_link": "https://example.com/listing/1",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = FeishuPinterestWorker(
                product_config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                FakeStore([record], [product]),
                NoopPublisher(),
            )

            result = worker.product_check()

        self.assertFalse(result.ok)
        self.assertIn("Products table has no complete product records", result.errors)
        self.assertTrue(any("must be an Etsy URL" in error for error in result.errors))

    def test_product_check_requires_pin_product_relation(self) -> None:
        record = {
            "record_id": "pin-1",
            "fields": {
                "status": "待 AI 生成",
                "source_image": [{"file_token": "source-token", "name": "source.jpg"}],
            },
        }
        product = {
            "record_id": "product-1",
            "fields": {
                "product_name": "Handmade Mug",
                "product_description": "A ceramic mug for quiet mornings.",
                "product_link": "https://www.etsy.com/listing/1/handmade-mug",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = FeishuPinterestWorker(
                product_config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                FakeStore([record], [product]),
                NoopPublisher(),
            )

            result = worker.product_check()

        self.assertFalse(result.ok)
        self.assertIn("Pin pin-1 is not linked to a Products record", result.errors)

    def test_product_check_requires_approved_pin_product_relation(self) -> None:
        record = {
            "record_id": "pin-1",
            "fields": {
                "status": "已批准待发布",
                "scheduled_at": "2000-01-01T00:00:00Z",
                "source_image": [{"file_token": "source-token", "name": "source.jpg"}],
            },
        }
        product = {
            "record_id": "product-1",
            "fields": {
                "product_name": "Handmade Mug",
                "product_description": "A ceramic mug for quiet mornings.",
                "product_link": "https://www.etsy.com/listing/1/handmade-mug",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = FeishuPinterestWorker(
                product_config(),
                RuntimeContext("run-1", "run-1", "agent-1", "job-1", Path(temp_dir), ""),
                FakeStore([record], [product]),
                NoopPublisher(),
            )

            result = worker.product_check()

        self.assertFalse(result.ok)
        self.assertIn("Pin pin-1 is not linked to a Products record", result.errors)


if __name__ == "__main__":
    unittest.main()
