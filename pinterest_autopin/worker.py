"""Hermes-native Feishu Pinterest worker orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Protocol

from .feishu_cli import FeishuCli
from .hermes_runtime import RuntimeContext, RuntimeErrorConfig, build_runtime_context
from .image_prepare import prepare_image
from .publisher import PinterestPublisher, PublisherResult
from .runtime_lock import RuntimeLock
from .worker_config import WorkerConfig, validate_worker_config
from .worker_state import build_claim, eligible_for_publish, iso, owns_publish_claim, utcnow


class WorkerError(RuntimeError):
    pass


class RecordStore(Protocol):
    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict[str, Any]]:
        ...

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        ...

    def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        ...

    def upload_attachment(self, file_path: str) -> str:
        ...

    def download_attachment(self, file_token: str, output_path: str) -> str:
        ...


class PublisherBoundary(Protocol):
    def check_login(self, *, chrome_profile: str = "") -> PublisherResult:
        ...

    def publish(self, request: Mapping[str, Any], *, input_path: Path, chrome_profile: str = "") -> PublisherResult:
        ...


@dataclass(frozen=True)
class WorkerResult:
    ok: bool
    action: str
    processed: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttachmentRef:
    token: str
    filename: str = ""


@dataclass
class FeishuPinterestWorker:
    config: WorkerConfig
    runtime: RuntimeContext
    store: RecordStore
    publisher: PublisherBoundary

    @classmethod
    def from_config(
        cls,
        config: WorkerConfig,
        *,
        local_dev: bool = False,
        chrome_profile: str = "",
    ) -> "FeishuPinterestWorker":
        runtime = build_runtime_context(
            local_dev=local_dev,
            required_secrets=config.required_hermes_secrets,
            chrome_profile=chrome_profile or None,
        )
        store = FeishuCli(
            binary=config.feishu_cli,
            app_token=config.app_token,
            flavor=config.feishu_cli_flavor,
        )
        publisher = PinterestPublisher()
        return cls(config=config, runtime=runtime, store=store, publisher=publisher)

    def doctor(self) -> WorkerResult:
        errors = validate_worker_config(self.config)
        feishu_missing = isinstance(self.store, FeishuCli) and not self.store.available()
        if feishu_missing:
            errors.append(f"Feishu CLI not found: {self.config.feishu_cli}")
        if not feishu_missing:
            try:
                lock_records = self.store.list_records(
                    self.config.runtime_locks.table_id,
                    filter_expr=_field_equals_expr(
                        dict(self.config.runtime_locks.fields),
                        "lock_name",
                        self.config.publish_lock_name,
                    ),
                    page_size=10,
                )
                lock_found = any(
                    _logical_fields(record, dict(self.config.runtime_locks.fields)).get("lock_name")
                    == self.config.publish_lock_name
                    for record in lock_records
                )
                if not lock_found:
                    errors.append(f"runtime lock row not found: {self.config.publish_lock_name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"failed to verify runtime lock row: {exc}")
        if not self.runtime.hermes_run_id:
            errors.append("Hermes run identity is missing")
        if errors:
            return WorkerResult(False, "doctor", errors=tuple(errors))
        return WorkerResult(True, "doctor")

    def publish(self, *, limit: int | None = None) -> WorkerResult:
        if not self.runtime.hermes_run_id:
            raise RuntimeErrorConfig("Hermes run identity is required before publish")

        lock = RuntimeLock(
            self.store,
            self.config.runtime_locks.table_id,
            lock_name=self.config.publish_lock_name,
            lease_minutes=self.config.claim_minutes,
            fields=dict(self.config.runtime_locks.fields),
        )
        lock_result = lock.acquire(
            owner_run_id=self.runtime.run_id,
            owner_hermes_run_id=self.runtime.hermes_run_id,
        )
        if not lock_result.acquired:
            return WorkerResult(True, "publish", skipped=1, errors=(lock_result.reason,))

        processed = 0
        errors: list[str] = []
        try:
            login = self.publisher.check_login(chrome_profile=self.runtime.chrome_profile)
            if not login.ok:
                errors.extend(login.errors or ("Pinterest check-login failed",))
                self._create_run("publish", ok=False, error="; ".join(errors))
                return WorkerResult(False, "publish", errors=tuple(errors))

            target = limit or self.config.publish_limit
            records = self._list_publish_candidates(target)
            for record in records:
                if processed >= target:
                    break
                fields = self._pin_fields(record)
                if not eligible_for_publish(fields, self.config.status_values, now=utcnow()):
                    continue
                record_id = _record_id(record)
                claim = build_claim(
                    self.config.status_values["publishing"],
                    self.runtime.run_id,
                    utcnow(),
                    self.config.claim_minutes,
                )
                claim["publish_attempts"] = _next_int(fields.get("publish_attempts"))
                self._update_pin(record_id, claim)
                refetched = self._refetch(record_id)
                if not owns_publish_claim(self._pin_fields(refetched), self.config.status_values, self.runtime.run_id):
                    continue
                try:
                    request = self._publisher_request(record_id, self._pin_fields(refetched))
                    result = self.publisher.publish(
                        request,
                        input_path=self.runtime.temp_dir / f"{record_id}-publish.json",
                        chrome_profile=self.runtime.chrome_profile,
                    )
                except Exception as exc:  # noqa: BLE001
                    result = PublisherResult(False, "final", errors=(str(exc),))
                if result.ok:
                    self._update_pin(
                        record_id,
                        {
                            "status": self.config.status_values["published"],
                            "pin_url": result.pin_url,
                            "published_at": iso(utcnow()),
                            "last_error": "",
                        },
                    )
                    self._create_run(
                        "publish",
                        pin=record_id,
                        ok=True,
                        output_snapshot={"pin_url": result.pin_url},
                    )
                    processed += 1
                else:
                    error_text = "; ".join(result.errors) or "Pinterest publish failed"
                    self._update_pin(
                        record_id,
                        {
                            "status": self.config.status_values["publish_failed"],
                            "last_error": error_text,
                        },
                    )
                    self._create_run("publish", pin=record_id, ok=False, error=error_text)
                    errors.append(error_text)
            return WorkerResult(not errors, "publish", processed=processed, errors=tuple(errors))
        finally:
            lock.release(owner_run_id=self.runtime.run_id)

    def prepare(self, *, limit: int | None = None) -> WorkerResult:
        if not self.runtime.hermes_run_id:
            raise RuntimeErrorConfig("Hermes run identity is required before prepare")

        target = limit or self.config.prepare_limit
        processed = 0
        skipped = 0
        errors: list[str] = []
        records = self._list_prepare_candidates(target)
        for record in records:
            if processed >= target:
                break
            fields = self._pin_fields(record)
            if not _eligible_for_prepare(fields, self.config.status_values):
                skipped += 1
                continue
            record_id = _record_id(record)
            self._update_pin(record_id, _prepare_claim(self.config.status_values["preparing"], self.runtime.run_id, self.config.claim_minutes))
            refetched = self._refetch(record_id)
            refetched_fields = self._pin_fields(refetched)
            if not _owns_prepare_claim(refetched_fields, self.config.status_values, self.runtime.run_id):
                skipped += 1
                continue
            try:
                update = self._prepare_pin(record_id, refetched_fields)
                update.update({"status": self.config.status_values["review"], "last_error": ""})
                self._update_pin(record_id, update)
                self._create_run(
                    "prepare",
                    pin=record_id,
                    ok=True,
                    output_snapshot={
                        "draft_title": update.get("draft_title", ""),
                        "processed_image": update.get("processed_image", ""),
                    },
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                self._update_pin(
                    record_id,
                    {
                        "status": self.config.status_values["prepare_failed"],
                        "last_error": error_text,
                    },
                )
                self._create_run("prepare", pin=record_id, ok=False, error=error_text)
                errors.append(error_text)
        return WorkerResult(not errors, "prepare", processed=processed, skipped=skipped, errors=tuple(errors))

    def _list_publish_candidates(self, target: int) -> list[dict[str, Any]]:
        return self.store.list_records(
            self.config.pins.table_id,
            filter_expr=_field_equals_expr(
                dict(self.config.pins.fields),
                "status",
                self.config.status_values["approved"],
            ),
            page_size=max(target, 50),
        )

    def _list_prepare_candidates(self, target: int) -> list[dict[str, Any]]:
        return self.store.list_records(
            self.config.pins.table_id,
            filter_expr=_field_in_expr(
                dict(self.config.pins.fields),
                "status",
                [
                    self.config.status_values["ready_for_ai"],
                    self.config.status_values["rewrite_requested"],
                ],
            ),
            page_size=max(target, 50),
        )

    def _prepare_pin(self, record_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        source_path = self._prepare_source_image(record_id, fields)
        prepared = prepare_image(source_path, self.runtime.temp_dir / "prepared-images")
        processed_ref: list[dict[str, str]] = []
        record_upload = getattr(self.store, "upload_record_attachment", None)
        if callable(record_upload):
            token = record_upload(
                self.config.pins.table_id,
                record_id,
                dict(self.config.pins.fields).get("processed_image", "processed_image"),
                str(prepared.output_path),
            )
            processed_ref = [{"file_token": token, "name": prepared.output_path.name}]
        else:
            upload = getattr(self.store, "upload_attachment", None)
            if callable(upload):
                token = upload(str(prepared.output_path))
                processed_ref = [{"file_token": token, "name": prepared.output_path.name}]
        draft = _draft_from_fields(fields)
        update: dict[str, Any] = {
            "draft_title": draft["title"],
            "draft_description": draft["description"],
            "draft_tags": draft["tags"],
            "draft_alt_text": draft["alt_text"],
            "processed_image_path": str(prepared.output_path),
        }
        if processed_ref:
            update["processed_image"] = processed_ref
        return update

    def _prepare_source_image(self, record_id: str, fields: Mapping[str, Any]) -> str:
        ref = _attachment_ref(fields.get("source_image"))
        if ref:
            return self._download_attachment(record_id, ref, "source-images")
        path = str(fields.get("source_image_path") or "").strip()
        if path:
            return path
        raise WorkerError("source_image attachment is required before prepare")

    def _publisher_request(self, record_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        image_path = self._publish_image(record_id, fields)
        return _publisher_request(fields, image_path)

    def _publish_image(self, record_id: str, fields: Mapping[str, Any]) -> str:
        ref = _attachment_ref(fields.get("final_image"))
        if ref:
            return self._download_attachment(record_id, ref, "final-images")
        path = str(fields.get("final_image_path") or fields.get("processed_image_path") or "").strip()
        if path:
            return path
        raise WorkerError("final_image attachment is required before publish")

    def _download_attachment(self, record_id: str, ref: AttachmentRef, subdir: str) -> str:
        download = getattr(self.store, "download_attachment", None)
        if not callable(download):
            raise WorkerError("Feishu attachment download is not available through the CLI boundary")
        output_dir = self.runtime.temp_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{record_id}-{_safe_filename(ref.filename or ref.token)}"
        return str(download(ref.token, str(output_path)))

    def _refetch(self, record_id: str) -> dict[str, Any]:
        records = self.store.list_records(self.config.pins.table_id, filter_expr=f'record_id="{record_id}"', page_size=1)
        return records[0] if records else {"record_id": record_id, "fields": {}}

    def _pin_fields(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return _logical_fields(record, dict(self.config.pins.fields))

    def _update_pin(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.store.update_record(
            self.config.pins.table_id,
            record_id,
            _mapped_fields(dict(self.config.pins.fields), fields),
        )

    def _create_run(
        self,
        action: str,
        *,
        pin: str = "",
        ok: bool,
        input_snapshot: Mapping[str, Any] | None = None,
        output_snapshot: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> None:
        fields = {
            "run_id": self.runtime.run_id,
            "pin": pin,
            "action": action,
            "ok": ok,
            "input_snapshot": dict(input_snapshot or {}),
            "output_snapshot": dict(output_snapshot or {}),
            "error": error,
            "worker_version": self.config.worker_version,
            "hermes_run_id": self.runtime.hermes_run_id,
            "hermes_agent_id": self.runtime.hermes_agent_id,
            "hermes_job_id": self.runtime.hermes_job_id,
        }
        try:
            self.store.create_record(
                self.config.runs.table_id,
                _mapped_fields(dict(self.config.runs.fields), fields),
            )
        except Exception:
            return


def _fields(record: Mapping[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", record)
    return dict(fields) if isinstance(fields, Mapping) else {}


def _logical_fields(record: Mapping[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    raw = _fields(record)
    logical = dict(raw)
    for logical_name, field_id in field_map.items():
        if field_id in raw:
            logical[logical_name] = raw[field_id]
    return logical


def _mapped_fields(field_map: dict[str, str], fields: dict[str, Any]) -> dict[str, Any]:
    return {field_map.get(key, key): value for key, value in fields.items()}


def _record_id(record: Mapping[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "")


def _publisher_request(fields: Mapping[str, Any], image_path: str) -> dict[str, Any]:
    description = str(fields.get("final_description") or fields.get("draft_description") or "")
    tags = str(fields.get("final_tags") or fields.get("draft_tags") or "").strip()
    if tags:
        description = f"{description}\n\n{tags}".strip()
    return {
        "image": image_path,
        "title": str(fields.get("final_title") or fields.get("draft_title") or ""),
        "board": str(fields.get("final_board") or fields.get("pinterest_board") or ""),
        "link": str(fields.get("product_link") or ""),
        "description": description,
        "altText": str(fields.get("final_alt_text") or fields.get("draft_alt_text") or ""),
    }


def _prepare_claim(status: str, run_id: str, minutes: int) -> dict[str, Any]:
    current = utcnow()
    return {
        "status": status,
        "prepare_run_id": run_id,
        "prepare_expires_at": iso(current + timedelta(minutes=minutes)),
        "last_error": "",
    }


def _eligible_for_prepare(record: Mapping[str, Any], status_values: Mapping[str, str]) -> bool:
    return record.get("status") in {
        status_values["ready_for_ai"],
        status_values["rewrite_requested"],
    }


def _owns_prepare_claim(record: Mapping[str, Any], status_values: Mapping[str, str], run_id: str) -> bool:
    return record.get("status") == status_values["preparing"] and record.get("prepare_run_id") == run_id


def _field_equals_expr(field_map: dict[str, str], logical_name: str, value: str) -> str:
    field = field_map.get(logical_name, logical_name)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{field}="{escaped}"'


def _field_in_expr(field_map: dict[str, str], logical_name: str, values: list[str]) -> str:
    field = field_map.get(logical_name, logical_name)
    escaped = [value.replace("\\", "\\\\").replace('"', '\\"') for value in values]
    quoted = ", ".join(f'"{value}"' for value in escaped)
    return f"{field} in [{quoted}]"


def _next_int(value: Any) -> int:
    try:
        return int(value or 0) + 1
    except (TypeError, ValueError):
        return 1


def _attachment_ref(value: Any) -> AttachmentRef | None:
    if isinstance(value, str) and value.strip():
        return AttachmentRef(token=value.strip(), filename="")
    if isinstance(value, Mapping):
        return _attachment_ref_from_mapping(value)
    if isinstance(value, list):
        for item in value:
            ref = _attachment_ref(item)
            if ref:
                return ref
    return None


def _attachment_ref_from_mapping(value: Mapping[str, Any]) -> AttachmentRef | None:
    token = str(
        value.get("file_token")
        or value.get("fileToken")
        or value.get("token")
        or value.get("id")
        or ""
    ).strip()
    if not token:
        return None
    filename = str(value.get("name") or value.get("file_name") or value.get("filename") or token).strip()
    return AttachmentRef(token=token, filename=filename)


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ".-_" else "-" for char in value).strip(".-")
    return cleaned or "attachment"


def _draft_from_fields(fields: Mapping[str, Any]) -> dict[str, str]:
    product_name = str(fields.get("product_name") or fields.get("title") or fields.get("source_title") or "").strip()
    brand_name = str(fields.get("brand_name") or "").strip()
    title = str(fields.get("draft_title") or product_name or "Pinterest Pin").strip()
    if brand_name and brand_name.lower() not in title.lower():
        title = f"{brand_name} {title}".strip()
    title = title[:100]

    description = str(
        fields.get("draft_description")
        or fields.get("product_description")
        or fields.get("source_description")
        or fields.get("notes")
        or title
    ).strip()
    tags = str(fields.get("draft_tags") or fields.get("keywords") or fields.get("tags") or "").strip()
    if not tags:
        tags = "#Pinterest"
    alt_text = str(fields.get("draft_alt_text") or fields.get("alt_text") or f"{title} product image").strip()
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "alt_text": alt_text,
    }
