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
from typing import Any, Sequence


class FeishuCliError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class FeishuCli:
    binary: str = "feishu"
    app_token: str = ""
    timeout: int = 60
    retries: int = 2
    backoff_seconds: float = 0.2

    def available(self) -> bool:
        return bool(shutil.which(self.binary))

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
        payload = self.run_json(["bitable", "attachments", "upload", "--file", file_path, "--format", "json"])
        token = str(payload.get("file_token", "")).strip()
        if not token:
            raise FeishuCliError("Feishu attachment upload returned no file_token")
        return token

    def download_attachment(self, file_token: str, output_path: str) -> str:
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
