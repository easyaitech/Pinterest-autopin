"""Feishu CLI subprocess boundary.

The real Feishu command name is configurable. Unit tests mock this layer; worker
code should never shell out to Feishu directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


class FeishuCliError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class FeishuCli:
    binary: str = "feishu"
    app_token: str = ""
    flavor: str = "auto"
    timeout: int = 60
    retries: int = 2
    backoff_seconds: float = 0.2

    def available(self) -> bool:
        return bool(shutil.which(self.binary))

    @property
    def resolved_flavor(self) -> str:
        if self.flavor and self.flavor != "auto":
            return self.flavor
        name = Path(self.binary).name.lower()
        if name == "lark-cli" or "lark" in name:
            return "lark"
        return "bitable"

    def run_json(self, args: Sequence[str], *, retryable: bool = True) -> dict[str, Any]:
        command = [self.binary, *args]
        attempt = 0
        while True:
            attempt += 1
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            if completed.returncode == 0:
                try:
                    payload = json.loads(completed.stdout or "{}")
                except json.JSONDecodeError as exc:
                    raise FeishuCliError(f"Feishu CLI returned non-JSON output: {exc}") from exc
                if not isinstance(payload, dict):
                    raise FeishuCliError("Feishu CLI JSON output must be an object")
                return payload

            message = (completed.stderr or completed.stdout or "Feishu CLI command failed").strip()
            should_retry = retryable and _is_retryable_message(message) and attempt <= self.retries
            if not should_retry:
                raise FeishuCliError(message, retryable=_is_retryable_message(message))
            time.sleep(self.backoff_seconds * attempt)

    def list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict[str, Any]]:
        if self.resolved_flavor == "lark":
            return self._lark_list_records(table_id, filter_expr=filter_expr, page_size=page_size)
        return self._bitable_list_records(table_id, filter_expr=filter_expr, page_size=page_size)

    def _bitable_list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            command = [
                "bitable",
                "records",
                "list",
                "--app-token",
                self.app_token,
                "--table-id",
                table_id,
                "--page-size",
                str(page_size),
                "--filter",
                filter_expr,
                "--format",
                "json",
            ]
            if page_token:
                command.extend(["--page-token", page_token])
            payload = self.run_json(command)
            page_records = _records_from_payload(payload)
            records.extend(record for record in page_records if isinstance(record, dict))
            page_token = _next_page_token(payload)
            if not page_token:
                return records

    def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if self.resolved_flavor == "lark":
            return self.run_json(
                [
                    "base",
                    "+record-upsert",
                    "--base-token",
                    self.app_token,
                    "--table-id",
                    table_id,
                    "--record-id",
                    record_id,
                    "--json",
                    json.dumps(fields, ensure_ascii=True),
                ]
            )
        return self.run_json(
            [
                "bitable",
                "records",
                "update",
                "--app-token",
                self.app_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--fields-json",
                json.dumps(fields, ensure_ascii=True),
                "--format",
                "json",
            ]
        )

    def compare_update_record(
        self,
        table_id: str,
        record_id: str,
        *,
        expected_fields: dict[str, Any],
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if self.resolved_flavor == "lark":
            return {
                "updated": False,
                "matched": False,
                "error": "lark-cli does not expose atomic compare-update",
            }
        return self.run_json(
            [
                "bitable",
                "records",
                "compare-update",
                "--app-token",
                self.app_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--expected-fields-json",
                json.dumps(expected_fields, ensure_ascii=True),
                "--fields-json",
                json.dumps(fields, ensure_ascii=True),
                "--format",
                "json",
            ]
        )

    def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if self.resolved_flavor == "lark":
            return self.run_json(
                [
                    "base",
                    "+record-upsert",
                    "--base-token",
                    self.app_token,
                    "--table-id",
                    table_id,
                    "--json",
                    json.dumps(fields, ensure_ascii=True),
                ]
            )
        return self.run_json(
            [
                "bitable",
                "records",
                "create",
                "--app-token",
                self.app_token,
                "--table-id",
                table_id,
                "--fields-json",
                json.dumps(fields, ensure_ascii=True),
                "--format",
                "json",
            ]
        )

    def upload_attachment(self, file_path: str) -> str:
        if self.resolved_flavor == "lark":
            payload = self.run_json(
                [
                    "drive",
                    "+upload",
                    "--file",
                    file_path,
                    "--name",
                    Path(file_path).name,
                ]
            )
            token = _file_token_from_payload(payload)
            if not token:
                raise FeishuCliError("Lark Drive upload returned no file token")
            return token
        payload = self.run_json(["bitable", "attachments", "upload", "--file", file_path, "--format", "json"])
        token = str(payload.get("file_token", "")).strip()
        if not token:
            raise FeishuCliError("Feishu attachment upload returned no file_token")
        return token

    def upload_record_attachment(
        self,
        table_id: str,
        record_id: str,
        field_id: str,
        file_path: str,
    ) -> str:
        if self.resolved_flavor != "lark":
            return self.upload_attachment(file_path)
        payload = self.run_json(
            [
                "base",
                "+record-upload-attachment",
                "--base-token",
                self.app_token,
                "--table-id",
                table_id,
                "--record-id",
                record_id,
                "--field-id",
                field_id,
                "--file",
                file_path,
                "--name",
                Path(file_path).name,
            ]
        )
        token = _file_token_from_payload(payload)
        if not token:
            raise FeishuCliError("Lark Base attachment upload returned no file token")
        return token

    def download_attachment(self, file_token: str, output_path: str) -> str:
        if self.resolved_flavor == "lark":
            self.run_json(
                [
                    "drive",
                    "+download",
                    "--file-token",
                    file_token,
                    "--output",
                    output_path,
                    "--overwrite",
                ]
            )
            return output_path
        self.run_json(
            [
                "bitable",
                "attachments",
                "download",
                "--file-token",
                file_token,
                "--output",
                output_path,
                "--format",
                "json",
            ]
        )
        return output_path

    def _lark_list_records(self, table_id: str, *, filter_expr: str = "", page_size: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.run_json(
                [
                    "base",
                    "+record-list",
                    "--base-token",
                    self.app_token,
                    "--table-id",
                    table_id,
                    "--limit",
                    str(page_size),
                    "--offset",
                    str(offset),
                    "--format",
                    "json",
                ]
            )
            page_records = [
                record
                for record in _records_from_payload(payload)
                if isinstance(record, dict) and _matches_filter(record, filter_expr)
            ]
            raw_count = len(_records_from_payload(payload))
            records.extend(page_records)
            if not _has_more(payload, raw_count=raw_count, page_size=page_size):
                return records
            offset += raw_count or page_size


def _is_retryable_message(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("429", "rate limit", "timeout", " 5", "5xx", "temporarily"))


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _records_from_payload(payload: dict[str, Any]) -> list[Any]:
    data = _data(payload)
    records = data.get("records", data.get("items", []))
    if not isinstance(records, list):
        raise FeishuCliError("Feishu CLI records payload must contain a records/items list")
    return records


def _next_page_token(payload: dict[str, Any]) -> str:
    data = _data(payload)
    if not data.get("has_more"):
        return ""
    return str(data.get("page_token") or data.get("next_page_token") or "").strip()


def _has_more(payload: dict[str, Any], *, raw_count: int, page_size: int) -> bool:
    data = _data(payload)
    if "has_more" in data:
        return bool(data.get("has_more"))
    if "has_more" in payload:
        return bool(payload.get("has_more"))
    return raw_count >= page_size and page_size > 0


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or record.get("id") or "").strip()


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", record)
    return fields if isinstance(fields, dict) else {}


def _matches_filter(record: dict[str, Any], filter_expr: str) -> bool:
    expr = filter_expr.strip()
    if not expr:
        return True
    if expr.startswith("record_id="):
        return _record_id(record) == _quoted_value(expr)

    fields = _fields(record)
    if " in [" in expr and expr.endswith("]"):
        field, raw_values = expr.split(" in [", 1)
        values = [
            item.strip().strip('"')
            for item in raw_values[:-1].split(",")
            if item.strip()
        ]
        return str(fields.get(field.strip(), "")) in values
    if "=" in expr:
        field, raw_value = expr.split("=", 1)
        return str(fields.get(field.strip(), "")) == raw_value.strip().strip('"')
    return True


def _quoted_value(expr: str) -> str:
    if '"' not in expr:
        return ""
    return expr.split('"', 2)[1]


def _file_token_from_payload(payload: dict[str, Any]) -> str:
    direct = str(payload.get("file_token") or payload.get("fileToken") or "").strip()
    if direct:
        return direct
    data = payload.get("data")
    if isinstance(data, dict):
        token = _file_token_from_payload(data)
        if token:
            return token
    for value in payload.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    token = _file_token_from_payload(item)
                    if token:
                        return token
    return ""
