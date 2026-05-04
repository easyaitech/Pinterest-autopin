"""Feishu Base schema setup for the Pinterest workflow."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from .worker_config import DEFAULT_STATUS_VALUES


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class FeishuSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class FieldSpec:
    logical_name: str
    display_name: str
    body: Mapping[str, Any]


@dataclass(frozen=True)
class TableSpec:
    logical_name: str
    display_name: str
    fields: tuple[FieldSpec, ...]


@dataclass(frozen=True)
class SetupResult:
    ok: bool
    base_token: str
    config_path: str
    created_tables: tuple[str, ...]
    created_fields: tuple[str, ...]
    tables: Mapping[str, Any]
    usage: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": "setup-base",
            "baseToken": self.base_token,
            "configPath": self.config_path,
            "createdTables": list(self.created_tables),
            "createdFields": list(self.created_fields),
            "tables": dict(self.tables),
            "usage": list(self.usage),
        }


PIN_STATUSES = tuple(DEFAULT_STATUS_VALUES.values())


def _field(
    logical_name: str,
    display_name: str,
    field_type: str,
    description: str,
    *,
    style: Mapping[str, Any] | None = None,
) -> FieldSpec:
    body: dict[str, Any] = {"type": field_type, "name": display_name, "description": description}
    if style:
        body["style"] = dict(style)
    return FieldSpec(logical_name, display_name, body)


def _status_hue(value: str) -> str:
    if value in {"已发布", "已批准待发布"}:
        return "Green"
    if value in {"生成失败", "发布失败"}:
        return "Red"
    if value in {"已暂停", "已废弃"}:
        return "Gray"
    if value in {"待人工审核", "退回 AI 重写"}:
        return "Orange"
    return "Blue"


PINS_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "product",
        "商品",
        {
            "type": "link",
            "name": "商品",
            "link_table": "$products",
            "description": "必须关联 Products 表中的商品记录；prepare 会从商品表读取商品事实",
        },
    ),
    _field("product_name", "商品名称", "text", "用于生成 Pin 标题的主要商品名"),
    _field("product_description", "商品描述", "text", "用于生成 Pin 描述的商品卖点、材质、用途等信息"),
    _field("product_link", "商品链接", "text", "发布到 Pinterest 的落地页链接", style={"type": "url"}),
    _field("pinterest_board", "Pinterest 画板", "text", "默认发布画板；人工终稿可用 final_board 覆盖"),
    _field("brand_name", "品牌名称", "text", "可选；存在时会前置到草稿标题"),
    _field("keywords", "关键词", "text", "可选；用于草稿标签"),
    _field("notes", "备注", "text", "可选；补充生成要求、禁用词或人工说明"),
    _field("source_image", "原始图片", "attachment", "准备阶段下载并处理的原图附件"),
    FieldSpec(
        "status",
        "状态",
        {
            "type": "select",
            "name": "状态",
            "multiple": False,
            "options": [
                {"name": value, "hue": _status_hue(value), "lightness": "Light"}
                for value in PIN_STATUSES
            ],
            "description": "工作流状态；待 AI 生成/退回 AI 重写进入 prepare，已批准待发布进入 publish",
        },
    ),
    _field("scheduled_at", "计划发布时间", "datetime", "到这个时间后，已批准待发布的 Pin 才会被发布"),
    _field("processed_image", "处理后图片", "attachment", "prepare 阶段上传的处理后图片"),
    _field("draft_title", "草稿标题", "text", "prepare 阶段写入，人工可复制到终稿标题"),
    _field("draft_description", "草稿描述", "text", "prepare 阶段写入，人工可复制到终稿描述"),
    _field("draft_tags", "草稿标签", "text", "prepare 阶段写入，发布时会拼到描述末尾"),
    _field("draft_alt_text", "草稿 Alt 文本", "text", "prepare 阶段写入，人工可复制到终稿 Alt 文本"),
    _field("final_title", "终稿标题", "text", "人工审核后的最终 Pinterest 标题"),
    _field("final_description", "终稿描述", "text", "人工审核后的最终 Pinterest 描述"),
    _field("final_tags", "终稿标签", "text", "人工审核后的最终标签，发布时会拼到描述末尾"),
    _field("final_alt_text", "终稿 Alt 文本", "text", "人工审核后的最终 Alt 文本"),
    _field("final_board", "终稿画板", "text", "人工审核后的最终画板；为空则使用 Pinterest 画板"),
    _field("final_image", "终稿图片", "attachment", "发布阶段只使用这个审核后的图片附件"),
    _field("pin_url", "Pinterest 链接", "text", "发布成功后回写", style={"type": "url"}),
    _field("published_at", "实际发布时间", "datetime", "发布成功后回写"),
    _field("publisher_run_id", "发布运行 ID", "text", "系统字段：发布认领用"),
    _field("claim_expires_at", "发布认领过期时间", "datetime", "系统字段：发布认领用"),
    _field("last_attempt_at", "最近尝试时间", "datetime", "系统字段：发布尝试记录"),
    _field("publish_attempts", "发布尝试次数", "number", "系统字段：发布尝试次数", style={"type": "plain", "precision": 0}),
    _field("prepare_run_id", "生成运行 ID", "text", "系统字段：prepare 认领用"),
    _field("prepare_expires_at", "生成认领过期时间", "datetime", "系统字段：prepare 认领用"),
    _field("last_error", "最近错误", "text", "prepare 或 publish 失败时回写"),
)


PRODUCTS_FIELDS: tuple[FieldSpec, ...] = (
    _field("product_name", "商品名称", "text", "必填；商品事实源，用于 Pinterest 标题和搜索意图"),
    _field("product_description", "商品描述", "text", "必填；商品卖点、材质、用途、适用场景"),
    _field("product_link", "商品链接", "text", "必填；Etsy listing 链接", style={"type": "url"}),
    _field("brand_name", "品牌名称", "text", "可选；品牌或店铺名"),
    _field("keywords", "关键词", "text", "可选；搜索词、风格词、人群词、节日词"),
    _field("notes", "备注", "text", "可选；禁用词、人工说明、转化重点"),
)


BRANDS_FIELDS: tuple[FieldSpec, ...] = (
    _field("brand_id", "品牌 ID", "text", "可选品牌主键"),
    _field("brand_name", "品牌名称", "text", "品牌显示名称"),
    _field("tone", "品牌语气", "text", "可选；给 Hermes 生成文案时参考"),
)


RUNS_FIELDS: tuple[FieldSpec, ...] = (
    _field("run_id", "运行 ID", "text", "系统字段：本次 Hermes 运行 ID"),
    _field("pin", "Pin 记录", "text", "系统字段：对应 Pins 记录 ID"),
    _field("action", "动作", "text", "prepare 或 publish"),
    _field("ok", "是否成功", "checkbox", "系统字段：运行结果"),
    _field("input_snapshot", "输入快照", "text", "系统字段：运行输入快照"),
    _field("output_snapshot", "输出快照", "text", "系统字段：运行输出快照"),
    _field("error", "错误", "text", "系统字段：运行错误"),
    _field("worker_version", "Worker 版本", "text", "系统字段：worker 版本"),
    _field("hermes_run_id", "Hermes Run ID", "text", "系统字段：Hermes run id"),
    _field("hermes_agent_id", "Hermes Agent ID", "text", "系统字段：Hermes agent id"),
    _field("hermes_job_id", "Hermes Job ID", "text", "系统字段：Hermes job id"),
)


LOCK_FIELDS: tuple[FieldSpec, ...] = (
    _field("lock_name", "锁名称", "text", "系统字段：锁名称"),
    _field("owner_run_id", "占用运行 ID", "text", "系统字段：当前占用运行"),
    _field("owner_hermes_run_id", "占用 Hermes Run ID", "text", "系统字段：当前占用 Hermes 运行"),
    _field("lock_expires_at", "锁过期时间", "datetime", "系统字段：锁租约过期时间"),
    _field("locked_at", "加锁时间", "datetime", "系统字段：加锁时间"),
    _field("last_error", "锁错误", "text", "系统字段：锁错误"),
)


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("products", "Products", PRODUCTS_FIELDS),
    TableSpec("pins", "Pins", PINS_FIELDS),
    TableSpec("brands", "Brands", BRANDS_FIELDS),
    TableSpec("runs", "Runs", RUNS_FIELDS),
    TableSpec("runtime_locks", "Runtime Locks", LOCK_FIELDS),
)


def setup_feishu_base(
    *,
    base_url: str,
    config_path: str | Path,
    feishu_cli: str = "lark-cli",
    feishu_cli_flavor: str = "lark",
    worker_version: str = "dev",
    command_runner: CommandRunner | None = None,
) -> SetupResult:
    run = command_runner or subprocess.run
    base_token = resolve_base_token(base_url, feishu_cli=feishu_cli, command_runner=run)
    tables = _ensure_tables(base_token, feishu_cli, run)
    _ensure_runtime_lock(base_token, feishu_cli, run, tables["runtime_locks"])
    config = _config_payload(
        base_token=base_token,
        tables=tables,
        feishu_cli=feishu_cli,
        feishu_cli_flavor=feishu_cli_flavor,
        worker_version=worker_version,
    )
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SetupResult(
        ok=True,
        base_token=base_token,
        config_path=str(path),
        created_tables=tuple(
            table["displayName"] for table in tables.values() if table.get("created")
        ),
        created_fields=tuple(
            f'{table["displayName"]}.{field_name}'
            for table in tables.values()
            for field_name in table.get("createdFields", [])
        ),
        tables=tables,
        usage=_usage_lines(str(path)),
    )


def resolve_base_token(
    value: str,
    *,
    feishu_cli: str = "lark-cli",
    command_runner: CommandRunner | None = None,
) -> str:
    parsed = _parse_shared_url(value)
    if parsed["kind"] == "base":
        return parsed["token"]
    if parsed["kind"] == "wiki":
        run = command_runner or subprocess.run
        payload = _run_json(
            run,
            [
                feishu_cli,
                "wiki",
                "spaces",
                "get_node",
                "--params",
                json.dumps({"token": parsed["token"], "obj_type": "wiki"}, ensure_ascii=True),
            ],
        )
        node = _data(payload).get("node") or payload.get("node") or {}
        if not isinstance(node, Mapping):
            raise FeishuSchemaError("wiki node response is missing node data")
        if str(node.get("obj_type", "")).lower() != "bitable":
            raise FeishuSchemaError("the shared wiki URL does not point to a Base/Bitable document")
        token = str(node.get("obj_token", "")).strip()
        if not token:
            raise FeishuSchemaError("wiki node response does not contain Base obj_token")
        return token
    raise FeishuSchemaError("could not find a Feishu Base token in the shared URL")


def _ensure_tables(base_token: str, feishu_cli: str, run: CommandRunner) -> dict[str, dict[str, Any]]:
    existing_tables = _list_tables(base_token, feishu_cli, run)
    table_by_name = {table["name"]: table for table in existing_tables if table.get("name")}
    results: dict[str, dict[str, Any]] = {}
    for spec in TABLE_SPECS:
        created = False
        table = table_by_name.get(spec.display_name)
        if not table:
            first_field = next((field for field in spec.fields if field.body.get("type") != "link"), spec.fields[0])
            payload = _run_json(
                run,
                [
                    feishu_cli,
                    "base",
                    "+table-create",
                    "--base-token",
                    base_token,
                    "--name",
                    spec.display_name,
                    "--fields",
                    json.dumps([dict(first_field.body)], ensure_ascii=True),
                ],
            )
            table = _table_from_payload(payload)
            created = True
        table_id = str(table.get("id", "")).strip()
        if not table_id:
            raise FeishuSchemaError(f"could not determine table id for {spec.display_name}")
        results[spec.logical_name] = {
            "tableId": table_id,
            "displayName": spec.display_name,
            "fields": {},
            "created": created,
            "createdFields": [],
        }
    for spec in TABLE_SPECS:
        table = results[spec.logical_name]
        field_map, created_fields = _ensure_fields(
            base_token,
            feishu_cli,
            run,
            str(table["tableId"]),
            spec.fields,
            results,
        )
        table["fields"] = field_map
        table["createdFields"] = created_fields
    return results


def _ensure_fields(
    base_token: str,
    feishu_cli: str,
    run: CommandRunner,
    table_id: str,
    fields: Sequence[FieldSpec],
    tables: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    existing = _list_fields(base_token, feishu_cli, run, table_id)
    by_name = {field["name"]: field for field in existing if field.get("name")}
    created_fields: list[str] = []
    field_map: dict[str, str] = {}
    for spec in fields:
        field = _find_field(by_name, spec)
        if not field:
            body = _field_body(spec, tables)
            payload = _run_json(
                run,
                [
                    feishu_cli,
                    "base",
                    "+field-create",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--json",
                    json.dumps(body, ensure_ascii=True),
                ],
            )
            field = _field_from_payload(payload)
            created_fields.append(spec.display_name)
            by_name[spec.display_name] = field
        field_id = str(field.get("id", "")).strip()
        if not field_id:
            raise FeishuSchemaError(f"could not determine field id for {spec.display_name}")
        field_map[spec.logical_name] = field_id
    return field_map, created_fields


def _field_body(spec: FieldSpec, tables: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    body = dict(spec.body)
    link_table = body.get("link_table")
    if isinstance(link_table, str) and link_table.startswith("$"):
        logical_name = link_table[1:]
        linked = tables.get(logical_name) or {}
        table_id = str(linked.get("tableId") or "").strip()
        if not table_id:
            raise FeishuSchemaError(f"linked table is not ready: {logical_name}")
        body["link_table"] = table_id
    return body


def _ensure_runtime_lock(base_token: str, feishu_cli: str, run: CommandRunner, lock_table: Mapping[str, Any]) -> None:
    table_id = str(lock_table["tableId"])
    lock_name_field = str(lock_table["fields"]["lock_name"])
    payload = _run_json(
        run,
        [
            feishu_cli,
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--field-id",
            lock_name_field,
            "--limit",
            "100",
            "--format",
            "json",
        ],
    )
    records = _records_from_payload(payload)
    for record in records:
        fields = _record_fields(record)
        if fields.get(lock_name_field) == "pinterest_profile_publish" or fields.get("锁名称") == "pinterest_profile_publish":
            return
    _run_json(
        run,
        [
            feishu_cli,
            "base",
            "+record-upsert",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps({lock_name_field: "pinterest_profile_publish"}, ensure_ascii=True),
        ],
    )


def _config_payload(
    *,
    base_token: str,
    tables: Mapping[str, Mapping[str, Any]],
    feishu_cli: str,
    feishu_cli_flavor: str,
    worker_version: str,
) -> dict[str, Any]:
    return {
        "app_token": base_token,
        "feishu_cli": feishu_cli,
        "feishu_cli_flavor": feishu_cli_flavor,
        "prepare_lock_mode": "hermes_singleton",
        "publish_lock_mode": "hermes_singleton",
        "worker_version": worker_version,
        "required_hermes_secrets": [],
        "tables": {
            name: {
                "table_id": str(table["tableId"]),
                "fields": dict(table["fields"]),
            }
            for name, table in tables.items()
        },
    }


def _usage_lines(config_path: str) -> tuple[str, ...]:
    return (
        "先在 Products 表维护商品，至少填写 商品名称、商品描述、商品链接。",
        "在 Pins 表新增一行，关联 Products 表里的 商品，填写 Pinterest 画板、原始图片，并把 状态 设为 待 AI 生成。",
        f"生成草稿：python3 tools/feishu_pinterest_worker.py prepare --config {config_path} --limit 10 --prepare-singleton-confirmed",
        "人工审核后填写 终稿标题、终稿描述、终稿标签、终稿 Alt 文本、终稿画板、终稿图片、计划发布时间，并把 状态 设为 已批准待发布。",
        f"正式发布：python3 tools/feishu_pinterest_worker.py publish --config {config_path} --limit 1 --publish-singleton-confirmed",
        "发布成功后系统会回写 Pinterest 链接、实际发布时间，并把状态改为 已发布。",
    )


def _parse_shared_url(value: str) -> dict[str, str]:
    raw = value.strip()
    if not raw:
        return {"kind": "", "token": ""}
    parsed = urlparse(raw if "://" in raw else f"https://dummy.local/{raw.lstrip('/')}")
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        lowered = part.lower()
        if lowered in {"base", "bitable"}:
            return {"kind": "base", "token": parts[index + 1]}
        if lowered == "wiki":
            return {"kind": "wiki", "token": parts[index + 1]}
    query = parse_qs(parsed.query)
    for key in ("base_token", "app_token"):
        if query.get(key):
            return {"kind": "base", "token": query[key][0]}
    token_match = re.search(r"\bapp[A-Za-z0-9_-]{6,}\b", raw)
    if token_match:
        return {"kind": "base", "token": token_match.group(0)}
    wiki_match = re.search(r"\bwik[A-Za-z0-9_-]{6,}\b", raw)
    if wiki_match:
        return {"kind": "wiki", "token": wiki_match.group(0)}
    return {"kind": "", "token": ""}


def _list_tables(base_token: str, feishu_cli: str, run: CommandRunner) -> list[dict[str, str]]:
    payload = _run_json(
        run,
        [feishu_cli, "base", "+table-list", "--base-token", base_token, "--offset", "0", "--limit", "50"],
    )
    items = _items_from_payload(payload)
    return [_table_from_mapping(item) for item in items if isinstance(item, Mapping)]


def _list_fields(base_token: str, feishu_cli: str, run: CommandRunner, table_id: str) -> list[dict[str, str]]:
    payload = _run_json(
        run,
        [
            feishu_cli,
            "base",
            "+field-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--offset",
            "0",
            "--limit",
            "200",
        ],
    )
    items = _items_from_payload(payload)
    return [_field_from_mapping(item) for item in items if isinstance(item, Mapping)]


def _find_field(by_name: Mapping[str, Mapping[str, str]], spec: FieldSpec) -> Mapping[str, str] | None:
    return by_name.get(spec.display_name) or by_name.get(spec.logical_name)


def _run_json(run: CommandRunner, command: Sequence[str]) -> dict[str, Any]:
    completed = run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Feishu CLI command failed").strip()
        raise FeishuSchemaError(message)
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FeishuSchemaError(f"Feishu CLI returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise FeishuSchemaError("Feishu CLI JSON output must be an object")
    return payload


def _data(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return dict(data) if isinstance(data, Mapping) else dict(payload)


def _items_from_payload(payload: Mapping[str, Any]) -> list[Any]:
    data = _data(payload)
    for key in ("items", "tables", "fields", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    value = payload.get("items")
    return value if isinstance(value, list) else []


def _records_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = _data(payload)
    records = data.get("items") or data.get("records") or []
    return [record for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []


def _record_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", record)
    return dict(fields) if isinstance(fields, Mapping) else {}


def _table_from_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    data = _data(payload)
    table = data.get("table") or payload.get("table") or payload
    if not isinstance(table, Mapping):
        raise FeishuSchemaError("table-create response does not contain table data")
    return _table_from_mapping(table)


def _table_from_mapping(table: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": str(table.get("table_id") or table.get("id") or table.get("tableId") or "").strip(),
        "name": str(table.get("table_name") or table.get("name") or table.get("tableName") or "").strip(),
    }


def _field_from_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    data = _data(payload)
    field = data.get("field") or payload.get("field") or payload
    if not isinstance(field, Mapping):
        raise FeishuSchemaError("field-create response does not contain field data")
    return _field_from_mapping(field)


def _field_from_mapping(field: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": str(field.get("field_id") or field.get("id") or field.get("fieldId") or "").strip(),
        "name": str(field.get("field_name") or field.get("name") or field.get("fieldName") or "").strip(),
    }
