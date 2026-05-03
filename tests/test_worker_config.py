from __future__ import annotations

import unittest

from pinterest_autopin.worker_config import ConfigError, validate_worker_config, worker_config_from_dict


def config_payload() -> dict:
    return {
        "app_token": "app",
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


class WorkerConfigTest(unittest.TestCase):
    def test_loads_valid_config(self) -> None:
        config = worker_config_from_dict(config_payload())

        self.assertEqual("pins", config.pins.table_id)
        self.assertEqual("fld_status", config.pins.fields["status"])
        self.assertEqual([], validate_worker_config(config))

    def test_missing_table_fails(self) -> None:
        payload = config_payload()
        del payload["tables"]["pins"]

        with self.assertRaises(ConfigError):
            worker_config_from_dict(payload)

    def test_missing_required_field_is_reported(self) -> None:
        payload = config_payload()
        del payload["tables"]["pins"]["fields"]["status"]
        config = worker_config_from_dict(payload)

        self.assertIn("pins.fields.status is required", validate_worker_config(config))

    def test_missing_publish_attempts_is_reported(self) -> None:
        payload = config_payload()
        del payload["tables"]["pins"]["fields"]["publish_attempts"]
        config = worker_config_from_dict(payload)

        self.assertIn("pins.fields.publish_attempts is required", validate_worker_config(config))


if __name__ == "__main__":
    unittest.main()
