from __future__ import annotations

import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pinterest_autopin.hermes_runtime import RuntimeContext
from pinterest_autopin.publisher import PublisherResult
from pinterest_autopin.worker import FeishuPinterestWorker
from pinterest_autopin.worker_config import WorkerConfig, TableConfig


class FakeStore:
    def __init__(
        self,
        *,
        lock_owner: str = "",
        pin_status: str = "已批准待发布",
        pins: list[dict] | None = None,
        products: list[dict] | None = None,
    ) -> None:
        lock_expires_at = "2000-01-01T00:00:00Z"
        if lock_owner:
            lock_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        self.lock = {
            "record_id": "lock-1",
            "fields": {
                "lock_name": "pinterest_profile_publish",
                "owner_run_id": lock_owner,
                "lock_expires_at": lock_expires_at,
            },
        }
        self.pin = pins[0] if pins else {
            "record_id": "pin-1",
            "fields": {
                "status": pin_status,
                "scheduled_at": "2000-01-01T00:00:00Z",
                "final_image": [{"file_token": "final-token", "name": "image.jpg"}],
                "final_title": "Title",
                "final_board": "Board",
                "product": [{"record_id": "product-1"}],
                "final_description": "Desc",
                "final_alt_text": "Alt",
                "publish_attempts": 2,
            },
        }
        self.pins = pins or [self.pin]
        self.products = products or [
            {
                "record_id": "product-1",
                "fields": {
                    "product_name": "Product",
                    "product_description": "A product description with enough detail.",
                    "product_link": "https://www.etsy.com/listing/123/product",
                },
            }
        ]
        self.updates: list[tuple[str, str, dict]] = []
        self.downloads: list[tuple[str, str]] = []

    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict]:
        if table_id == "locks":
            return [self.lock]
        if table_id == "products":
            if "record_id=" in filter_expr:
                record_id = filter_expr.split('"')[1]
                return [product for product in self.products if product["record_id"] == record_id]
            return self.products
        if "record_id=" in filter_expr:
            record_id = filter_expr.split('"')[1]
            return [pin for pin in self.pins if pin["record_id"] == record_id]
        return self.pins

    def update_record(self, table_id: str, record_id: str, fields: dict) -> dict:
        self.updates.append((table_id, record_id, fields))
        target = self.lock if table_id == "locks" else next(pin for pin in self.pins if pin["record_id"] == record_id)
        target["fields"].update(fields)
        return target

    def compare_update_record(self, table_id: str, record_id: str, *, expected_fields: dict, fields: dict) -> dict:
        current = self.lock["fields"]
        for key, value in expected_fields.items():
            if current.get(key, "") != value:
                return {"updated": False}
        current.update(fields)
        return {"updated": True}

    def create_record(self, table_id: str, fields: dict) -> dict:
        return {"record_id": "run-1", "fields": fields}

    def download_attachment(self, file_token: str, output_path: str) -> str:
        Path(output_path).write_text(f"downloaded:{file_token}", encoding="utf-8")
        self.downloads.append((file_token, output_path))
        return output_path


class FakePublisher:
    def __init__(self, *, login_ok: bool = True, publish_ok: bool = True) -> None:
        self.login_ok = login_ok
        self.publish_ok = publish_ok
        self.published = False
        self.last_request = {}
        self.login_cdp = False
        self.publish_cdp = False

    def check_login(self, *, chrome_profile: str = "", use_chrome_cdp: bool = False) -> PublisherResult:
        self.login_cdp = use_chrome_cdp
        if self.login_ok:
            return PublisherResult(True, "check-login")
        return PublisherResult(False, "check-login", errors=("login required",))

    def publish(
        self,
        request,
        *,
        input_path: Path,
        chrome_profile: str = "",
        use_chrome_cdp: bool = False,
    ) -> PublisherResult:
        self.published = True
        self.last_request = dict(request)
        self.publish_cdp = use_chrome_cdp
        if self.publish_ok:
            return PublisherResult(True, "final", pin_url="https://www.pinterest.com/pin/123/")
        return PublisherResult(False, "final", errors=("publish failed",))


def config(**kwargs) -> WorkerConfig:
    return WorkerConfig(
        app_token="app",
        pins=TableConfig("pins", fields={}),
        brands=TableConfig("brands", fields={}),
        runs=TableConfig("runs", fields={}),
        runtime_locks=TableConfig("locks", fields={}),
        products=TableConfig("products", fields={}),
        **kwargs,
    )


def runtime(temp_dir: str) -> RuntimeContext:
    return RuntimeContext(
        run_id="run-1",
        hermes_run_id="run-1",
        hermes_agent_id="agent-1",
        hermes_job_id="job-1",
        temp_dir=Path(temp_dir),
        chrome_profile="/tmp/profile",
    )


def cdp_runtime(temp_dir: str) -> RuntimeContext:
    return RuntimeContext(
        run_id="run-1",
        hermes_run_id="run-1",
        hermes_agent_id="agent-1",
        hermes_job_id="job-1",
        temp_dir=Path(temp_dir),
        chrome_profile="/tmp/profile",
        chrome_cdp=True,
    )


class WorkerPublishTest(unittest.TestCase):
    def test_lock_unavailable_does_not_claim_or_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore(lock_owner="other")
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(config(), runtime(temp_dir), store, publisher)

            result = worker.publish()

        self.assertTrue(result.ok)
        self.assertFalse(publisher.published)
        self.assertFalse(any(update[0] == "pins" for update in store.updates))

    def test_check_login_failure_releases_lock_and_does_not_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore()
            publisher = FakePublisher(login_ok=False)
            worker = FeishuPinterestWorker(config(), runtime(temp_dir), store, publisher)

            result = worker.publish()

        self.assertFalse(result.ok)
        self.assertFalse(publisher.published)
        self.assertFalse(any(update[0] == "pins" for update in store.updates))
        self.assertEqual("", store.lock["fields"]["owner_run_id"])

    def test_success_claims_then_writes_published(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore()
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(config(), runtime(temp_dir), store, publisher)

            result = worker.publish()

        self.assertTrue(result.ok)
        self.assertTrue(publisher.published)
        self.assertEqual("已发布", store.pin["fields"]["status"])
        self.assertEqual("https://www.pinterest.com/pin/123/", store.pin["fields"]["pin_url"])
        self.assertEqual(3, store.pin["fields"]["publish_attempts"])
        self.assertEqual("final-token", store.downloads[0][0])
        self.assertTrue(publisher.last_request["image"].endswith("pin-1-image.jpg"))
        self.assertEqual("Alt", publisher.last_request["altText"])

    def test_publish_passes_multiple_final_images_as_carousel_request(self) -> None:
        pins = [
            {
                "record_id": "pin-carousel",
                "fields": {
                    "status": "已批准待发布",
                    "scheduled_at": "2000-01-01T00:00:00Z",
                    "final_image": [
                        {"file_token": "front-token", "name": "front.jpg"},
                        {"file_token": "detail-token", "name": "detail.jpg"},
                    ],
                    "final_title": "Carousel Title",
                    "final_board": "Board",
                    "product": [{"record_id": "product-1"}],
                    "final_description": "Desc",
                    "final_alt_text": "Front view\nDetail view",
                    "publish_attempts": 0,
                },
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore(pins=pins)
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(config(), runtime(temp_dir), store, publisher)

            result = worker.publish()

        self.assertTrue(result.ok)
        self.assertNotIn("image", publisher.last_request)
        self.assertEqual(
            ["front-token", "detail-token"],
            [token for token, _path in store.downloads],
        )
        self.assertEqual(
            [
                {
                    "path": str(Path(temp_dir) / "final-images" / "pin-carousel-1-front.jpg"),
                    "altText": "Front view",
                },
                {
                    "path": str(Path(temp_dir) / "final-images" / "pin-carousel-2-detail.jpg"),
                    "altText": "Detail view",
                },
            ],
            publisher.last_request["images"],
        )

    def test_publish_scans_past_first_ineligible_record(self) -> None:
        pins = [
            {
                "record_id": "pin-skip",
                "fields": {
                    "status": "已暂停",
                    "scheduled_at": "2000-01-01T00:00:00Z",
                },
            },
            {
                "record_id": "pin-2",
                "fields": {
                    "status": "已批准待发布",
                    "scheduled_at": "2000-01-01T00:00:00Z",
                    "final_image": [{"file_token": "final-token-2", "name": "image2.jpg"}],
                    "final_title": "Title",
                    "final_board": "Board",
                    "product": [{"record_id": "product-1"}],
                    "final_description": "Desc",
                    "final_alt_text": "Alt",
                    "publish_attempts": 0,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore(pins=pins)
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(config(), runtime(temp_dir), store, publisher)

            result = worker.publish(limit=1)

        self.assertTrue(result.ok)
        self.assertTrue(publisher.published)
        self.assertEqual("已发布", pins[1]["fields"]["status"])

    def test_publish_with_hermes_singleton_skips_feishu_runtime_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore(lock_owner="other")
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(
                config(publish_lock_mode="hermes_singleton"),
                runtime(temp_dir),
                store,
                publisher,
            )

            result = worker.publish()

        self.assertTrue(result.ok)
        self.assertTrue(publisher.published)
        self.assertEqual("已发布", store.pin["fields"]["status"])

    def test_publish_passes_cdp_mode_to_login_and_final_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FakeStore()
            publisher = FakePublisher()
            worker = FeishuPinterestWorker(config(), cdp_runtime(temp_dir), store, publisher)

            result = worker.publish()

        self.assertTrue(result.ok)
        self.assertTrue(publisher.login_cdp)
        self.assertTrue(publisher.publish_cdp)


if __name__ == "__main__":
    unittest.main()
