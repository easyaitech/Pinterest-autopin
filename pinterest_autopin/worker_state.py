"""Pure status transition and claim helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    if isinstance(value, str):
        cleaned = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def status_label(status_values: Mapping[str, str], status_key: str) -> str:
    return status_values[status_key]


def is_due(record: Mapping[str, Any], *, now: datetime, scheduled_field: str = "scheduled_at") -> bool:
    scheduled = parse_time(record.get(scheduled_field))
    return scheduled is not None and scheduled <= now


def build_claim(status: str, run_id: str, now: datetime, minutes: int) -> dict[str, Any]:
    return {
        "status": status,
        "publisher_run_id": run_id,
        "claim_expires_at": iso(now + timedelta(minutes=minutes)),
        "last_attempt_at": iso(now),
    }


def owns_publish_claim(record: Mapping[str, Any], status_values: Mapping[str, str], run_id: str) -> bool:
    return (
        record.get("status") == status_label(status_values, "publishing")
        and record.get("publisher_run_id") == run_id
    )


def can_reclaim(expires_at: Any, *, now: datetime) -> bool:
    parsed = parse_time(expires_at)
    return parsed is not None and parsed < now


def eligible_for_publish(record: Mapping[str, Any], status_values: Mapping[str, str], *, now: datetime) -> bool:
    return record.get("status") == status_label(status_values, "approved") and is_due(record, now=now)


def publish_success(pin_url: str, now: datetime) -> dict[str, Any]:
    return {
        "status": "已发布",
        "pin_url": pin_url,
        "published_at": iso(now),
        "last_error": "",
    }


def publish_failed(error: str) -> dict[str, Any]:
    return {
        "status": "发布失败",
        "last_error": error,
    }
