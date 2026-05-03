"""Feishu-backed runtime lock for the shared Pinterest Chrome profile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from .worker_state import iso, parse_time, utcnow


class LockStore(Protocol):
    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict[str, Any]]:
        ...

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        ...

    def compare_update_record(
        self,
        table_id: str,
        record_id: str,
        *,
        expected_fields: dict[str, Any],
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    record_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RuntimeLock:
    store: LockStore
    table_id: str
    lock_name: str = "pinterest_profile_publish"
    lease_minutes: int = 30
    fields: dict[str, str] | None = None

    def acquire(self, *, owner_run_id: str, owner_hermes_run_id: str, now: datetime | None = None) -> LockResult:
        current = now or utcnow()
        record = self._find_lock()
        if not record:
            return LockResult(False, reason=f"runtime lock row not found: {self.lock_name}")

        fields = _logical_fields(record, self.fields or {})
        record_id = _record_id(record)
        expires_at = parse_time(fields.get("lock_expires_at"))
        owner = str(fields.get("owner_run_id", "")).strip()
        if owner and expires_at and expires_at > current and owner != owner_run_id:
            return LockResult(False, record_id=record_id, reason=f"lock held by {owner}")

        expected = _mapped_fields(self.fields or {}, {
            "lock_name": self.lock_name,
            "owner_run_id": owner,
            "lock_expires_at": fields.get("lock_expires_at", ""),
        })
        compare_update = getattr(self.store, "compare_update_record", None)
        if not callable(compare_update):
            return LockResult(False, record_id=record_id, reason="runtime lock store does not support atomic compare-update")
        updated = compare_update(
            self.table_id,
            record_id,
            expected_fields=expected,
            fields=_mapped_fields(self.fields or {}, {
                "owner_run_id": owner_run_id,
                "owner_hermes_run_id": owner_hermes_run_id,
                "locked_at": iso(current),
                "lock_expires_at": iso(current + timedelta(minutes=self.lease_minutes)),
                "last_error": "",
            }),
        )
        if _compare_missed(updated):
            return LockResult(False, record_id=record_id, reason="runtime lock compare-update missed")

        refetched = self._find_lock()
        if not refetched:
            return LockResult(False, record_id=record_id, reason="runtime lock row disappeared after acquire")
        refetched_fields = _logical_fields(refetched, self.fields or {})
        if refetched_fields.get("owner_run_id") != owner_run_id:
            return LockResult(False, record_id=record_id, reason="runtime lock owner verification failed")
        return LockResult(True, record_id=record_id)

    def release(self, *, owner_run_id: str, now: datetime | None = None) -> bool:
        current = now or utcnow()
        record = self._find_lock()
        if not record:
            return False
        fields = _logical_fields(record, self.fields or {})
        if fields.get("owner_run_id") != owner_run_id:
            return False
        compare_update = getattr(self.store, "compare_update_record", None)
        if not callable(compare_update):
            return False
        updated = compare_update(
            self.table_id,
            _record_id(record),
            expected_fields=_mapped_fields(self.fields or {}, {"owner_run_id": owner_run_id}),
            fields=_mapped_fields(self.fields or {}, {
                "owner_run_id": "",
                "owner_hermes_run_id": "",
                "lock_expires_at": iso(current),
            }),
        )
        return not _compare_missed(updated)

    def _find_lock(self) -> dict[str, Any] | None:
        records = self.store.list_records(
            self.table_id,
            filter_expr=_field_equals_expr(self.fields or {}, "lock_name", self.lock_name),
            page_size=10,
        )
        for record in records:
            if _logical_fields(record, self.fields or {}).get("lock_name") == self.lock_name:
                return record
        return None


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", record)
    return fields if isinstance(fields, dict) else {}


def _logical_fields(record: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    raw = _fields(record)
    logical: dict[str, Any] = {}
    for key, value in raw.items():
        logical[key] = value
    for logical_name, field_id in field_map.items():
        if field_id in raw:
            logical[logical_name] = raw[field_id]
    return logical


def _mapped_fields(field_map: dict[str, str], fields: dict[str, Any]) -> dict[str, Any]:
    return {field_map.get(key, key): value for key, value in fields.items()}


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def _field_equals_expr(field_map: dict[str, str], logical_name: str, value: str) -> str:
    field = field_map.get(logical_name, logical_name)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{field}="{escaped}"'


def _compare_missed(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    compare_payload = data if isinstance(data, dict) else payload
    if compare_payload.get("updated") is False or compare_payload.get("matched") is False:
        return True
    if compare_payload.get("ok") is False:
        return True
    return False
