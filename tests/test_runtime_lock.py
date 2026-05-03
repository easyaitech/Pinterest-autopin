from __future__ import annotations

import unittest

from datetime import datetime, timedelta, timezone

from pinterest_autopin.runtime_lock import RuntimeLock


class FakeStore:
    def __init__(self, record: dict) -> None:
        self.record = record
        self.updates: list[dict] = []

    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict]:
        return [self.record]

    def update_record(self, table_id: str, record_id: str, fields: dict) -> dict:
        self.updates.append(fields)
        self.record.setdefault("fields", {}).update(fields)
        return self.record

    def compare_update_record(self, table_id: str, record_id: str, *, expected_fields: dict, fields: dict) -> dict:
        current = self.record.setdefault("fields", {})
        for key, value in expected_fields.items():
            if current.get(key, "") != value:
                return {"updated": False}
        self.updates.append(fields)
        current.update(fields)
        return {"updated": True}


class RuntimeLockTest(unittest.TestCase):
    def test_acquire_empty_lock_succeeds(self) -> None:
        store = FakeStore({"record_id": "lock-1", "fields": {"lock_name": "pinterest_profile_publish"}})
        lock = RuntimeLock(store, "locks")

        result = lock.acquire(owner_run_id="run-1", owner_hermes_run_id="run-1")

        self.assertTrue(result.acquired)
        self.assertEqual("run-1", store.record["fields"]["owner_run_id"])

    def test_non_expired_foreign_lock_blocks(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        store = FakeStore(
            {
                "record_id": "lock-1",
                "fields": {
                    "lock_name": "pinterest_profile_publish",
                    "owner_run_id": "other",
                    "lock_expires_at": future.isoformat(),
                },
            }
        )

        result = RuntimeLock(store, "locks").acquire(owner_run_id="run-1", owner_hermes_run_id="run-1")

        self.assertFalse(result.acquired)
        self.assertEqual([], store.updates)

    def test_stale_lock_can_be_replaced_and_owner_can_release(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        store = FakeStore(
            {
                "record_id": "lock-1",
                "fields": {
                    "lock_name": "pinterest_profile_publish",
                    "owner_run_id": "old",
                    "lock_expires_at": past.isoformat(),
                },
            }
        )
        lock = RuntimeLock(store, "locks")

        self.assertTrue(lock.acquire(owner_run_id="run-1", owner_hermes_run_id="run-1").acquired)
        self.assertTrue(lock.release(owner_run_id="run-1"))

    def test_field_id_mapping_is_used_for_updates(self) -> None:
        store = FakeStore({"record_id": "lock-1", "fields": {"fld_lock": "pinterest_profile_publish"}})
        lock = RuntimeLock(store, "locks", fields={"lock_name": "fld_lock", "owner_run_id": "fld_owner"})

        self.assertTrue(lock.acquire(owner_run_id="run-1", owner_hermes_run_id="run-1").acquired)

        self.assertEqual("run-1", store.record["fields"]["fld_owner"])

    def test_compare_update_miss_does_not_acquire(self) -> None:
        store = FakeStore(
            {
                "record_id": "lock-1",
                "fields": {
                    "lock_name": "pinterest_profile_publish",
                    "owner_run_id": "old",
                    "lock_expires_at": "2000-01-01T00:00:00Z",
                },
            }
        )

        original_compare = store.compare_update_record

        def racing_compare(table_id: str, record_id: str, *, expected_fields: dict, fields: dict) -> dict:
            store.record["fields"]["owner_run_id"] = "other"
            return original_compare(table_id, record_id, expected_fields=expected_fields, fields=fields)

        store.compare_update_record = racing_compare  # type: ignore[method-assign]

        result = RuntimeLock(store, "locks").acquire(owner_run_id="run-1", owner_hermes_run_id="run-1")

        self.assertFalse(result.acquired)
        self.assertEqual("other", store.record["fields"]["owner_run_id"])


if __name__ == "__main__":
    unittest.main()
