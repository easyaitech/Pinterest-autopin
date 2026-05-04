"""Config loading for the Feishu Pinterest worker."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


DEFAULT_STATUS_VALUES = {
    "needs_material": "待补充素材",
    "ready_for_ai": "待 AI 生成",
    "preparing": "AI 生成中",
    "review": "待人工审核",
    "approved": "已批准待发布",
    "publishing": "发布中",
    "published": "已发布",
    "rewrite_requested": "退回 AI 重写",
    "paused": "已暂停",
    "discarded": "已废弃",
    "prepare_failed": "生成失败",
    "publish_failed": "发布失败",
}

LOCK_MODE_FEISHU_ATOMIC = "feishu_atomic"
LOCK_MODE_HERMES_SINGLETON = "hermes_singleton"
LOCK_MODES = {LOCK_MODE_FEISHU_ATOMIC, LOCK_MODE_HERMES_SINGLETON}


class ConfigError(ValueError):
    """Raised when worker config is unsafe or incomplete."""


@dataclass(frozen=True)
class TableConfig:
    table_id: str
    fields: Mapping[str, str] = field(default_factory=dict)

    def require_fields(self, names: list[str]) -> list[str]:
        return [name for name in names if not self.fields.get(name)]


@dataclass(frozen=True)
class WorkerConfig:
    app_token: str
    pins: TableConfig
    brands: TableConfig
    runs: TableConfig
    runtime_locks: TableConfig
    feishu_cli: str = "feishu"
    feishu_cli_flavor: str = "auto"
    status_values: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_STATUS_VALUES))
    required_hermes_secrets: tuple[str, ...] = ()
    worker_version: str = "dev"
    publish_lock_name: str = "pinterest_profile_publish"
    prepare_lock_mode: str = LOCK_MODE_FEISHU_ATOMIC
    publish_lock_mode: str = LOCK_MODE_FEISHU_ATOMIC
    claim_minutes: int = 30
    publish_limit: int = 1
    prepare_limit: int = 10


def _placeholder(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("<") and stripped.endswith(">")


def _table(payload: Mapping[str, Any], name: str) -> TableConfig:
    raw = payload.get(name)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"missing table config: {name}")
    table_id = str(raw.get("table_id", "")).strip()
    fields = raw.get("fields") or {}
    if not table_id:
        raise ConfigError(f"missing table_id for {name}")
    if not isinstance(fields, Mapping):
        raise ConfigError(f"fields for {name} must be an object")
    return TableConfig(table_id=table_id, fields={str(k): str(v) for k, v in fields.items()})


def load_worker_config(path: str | Path) -> WorkerConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ConfigError("worker config must be a JSON object")
    return worker_config_from_dict(payload)


def worker_config_from_dict(payload: Mapping[str, Any]) -> WorkerConfig:
    tables = payload.get("tables") if isinstance(payload.get("tables"), Mapping) else payload
    required = payload.get("required_hermes_secrets") or ()
    if not isinstance(required, (list, tuple)):
        raise ConfigError("required_hermes_secrets must be a list")

    status_values = dict(DEFAULT_STATUS_VALUES)
    raw_status = payload.get("status_values") or {}
    if not isinstance(raw_status, Mapping):
        raise ConfigError("status_values must be an object")
    status_values.update({str(k): str(v) for k, v in raw_status.items()})

    return WorkerConfig(
        app_token=str(payload.get("app_token", "")).strip(),
        pins=_table(tables, "pins"),
        brands=_table(tables, "brands"),
        runs=_table(tables, "runs"),
        runtime_locks=_table(tables, "runtime_locks"),
        feishu_cli=str(payload.get("feishu_cli", "feishu")),
        feishu_cli_flavor=str(payload.get("feishu_cli_flavor", "auto")),
        status_values=status_values,
        required_hermes_secrets=tuple(str(name) for name in required),
        worker_version=str(payload.get("worker_version", "dev")),
        publish_lock_name=str(payload.get("publish_lock_name", "pinterest_profile_publish")),
        prepare_lock_mode=str(payload.get("prepare_lock_mode", LOCK_MODE_FEISHU_ATOMIC)),
        publish_lock_mode=str(payload.get("publish_lock_mode", LOCK_MODE_FEISHU_ATOMIC)),
        claim_minutes=int(payload.get("claim_minutes", 30)),
        publish_limit=int(payload.get("publish_limit", 1)),
        prepare_limit=int(payload.get("prepare_limit", 10)),
    )


def validate_worker_config(config: WorkerConfig) -> list[str]:
    errors: list[str] = []
    if not config.app_token:
        errors.append("app_token is required")
    elif _placeholder(config.app_token):
        errors.append("app_token must be replaced in a local ignored config file")
    for table_name, table in {
        "brands": config.brands,
        "pins": config.pins,
        "runs": config.runs,
        "runtime_locks": config.runtime_locks,
    }.items():
        if _placeholder(table.table_id):
            errors.append(f"{table_name}.table_id must be replaced in a local ignored config file")
        for field_name, field_id in table.fields.items():
            if _placeholder(field_id):
                errors.append(
                    f"{table_name}.fields.{field_name} must be replaced in a local ignored config file"
                )
    required_pin_fields = [
        "status",
        "scheduled_at",
        "publisher_run_id",
        "claim_expires_at",
        "last_attempt_at",
        "publish_attempts",
        "prepare_run_id",
        "prepare_expires_at",
        "last_error",
        "source_image",
        "processed_image",
        "draft_title",
        "draft_description",
        "draft_tags",
        "draft_alt_text",
        "final_image",
        "final_title",
        "final_description",
        "final_tags",
        "final_alt_text",
        "final_board",
        "product_link",
        "pin_url",
        "published_at",
    ]
    for missing in config.pins.require_fields(required_pin_fields):
        errors.append(f"pins.fields.{missing} is required")
    for missing in config.runtime_locks.require_fields(
        ["lock_name", "owner_run_id", "owner_hermes_run_id", "lock_expires_at", "locked_at"]
    ):
        errors.append(f"runtime_locks.fields.{missing} is required")
    for status_key in DEFAULT_STATUS_VALUES:
        if not config.status_values.get(status_key):
            errors.append(f"status_values.{status_key} is required")
    if config.prepare_lock_mode not in LOCK_MODES:
        errors.append("prepare_lock_mode must be feishu_atomic or hermes_singleton")
    if config.publish_lock_mode not in LOCK_MODES:
        errors.append("publish_lock_mode must be feishu_atomic or hermes_singleton")
    return errors
