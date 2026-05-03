from __future__ import annotations

import unittest

from datetime import datetime, timedelta, timezone

from pinterest_autopin.worker_config import DEFAULT_STATUS_VALUES
from pinterest_autopin.worker_state import can_reclaim, eligible_for_publish, owns_publish_claim


class WorkerStateTest(unittest.TestCase):
    def test_due_approved_record_is_eligible(self) -> None:
        record = {"status": "已批准待发布", "scheduled_at": "2000-01-01T00:00:00Z"}

        self.assertTrue(
            eligible_for_publish(record, DEFAULT_STATUS_VALUES, now=datetime.now(timezone.utc))
        )

    def test_future_record_is_not_eligible(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=1)
        record = {"status": "已批准待发布", "scheduled_at": future.isoformat()}

        self.assertFalse(
            eligible_for_publish(record, DEFAULT_STATUS_VALUES, now=datetime.now(timezone.utc))
        )

    def test_ownership_check(self) -> None:
        record = {"status": "发布中", "publisher_run_id": "run-1"}

        self.assertTrue(owns_publish_claim(record, DEFAULT_STATUS_VALUES, "run-1"))
        self.assertFalse(owns_publish_claim(record, DEFAULT_STATUS_VALUES, "run-2"))

    def test_stale_claim_can_reclaim(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(minutes=1)

        self.assertTrue(can_reclaim(past.isoformat(), now=datetime.now(timezone.utc)))


if __name__ == "__main__":
    unittest.main()
