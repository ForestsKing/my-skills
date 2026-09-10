#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (
    FIELDS,
    SkillError,
    canonical_abs_url,
    find_dicts,
    first_string,
    load_config,
    load_json,
    markdown_abs_link,
    parse_iso_date,
    prune_manifest_file,
    run_command,
    save_json,
    walk_values,
)
from run_pipeline import validate_keywords


ID_KEY_ALIASES = {
    "base": ("base_token", "app_token", "appToken", "token"),
    "table": ("table_id", "tableId", "id"),
    "field": ("field_id", "fieldId", "id"),
    "view": ("view_id", "viewId", "id"),
    "record": ("record_id", "recordId", "id"),
}


def value_for_keys(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


FIELD_TYPE_ALIASES = {
    "1": "text",
    "text": "text",
    "multiline": "text",
    "url": "text",
    "5": "datetime",
    "datetime": "datetime",
    "date": "datetime",
    "3": "select",
    "4": "select",
    "select": "select",
    "singleSelect": "select",
    "single_select": "select",
    "multiSelect": "select",
    "multi_select": "select",
}


def cli(*args: str, cwd: str | Path | None = None) -> dict[str, Any]:
    return run_command(["lark-cli", *args], cwd=cwd)


def unique_dicts(payload: Any, id_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    found = []
    seen = set()
    for item in walk_values(payload):
        if not isinstance(item, dict):
            continue
        identifier = value_for_keys(item, id_keys)
        if identifier and identifier not in seen:
            found.append(item)
            seen.add(identifier)
    return found


def exact_named(items: list[dict[str, Any]], expected: str) -> list[dict[str, Any]]:
    names = ("name", "title", "base_name", "table_name", "field_name")
    return [item for item in items if any(item.get(key) == expected for key in names)]


def public_base_url(payload: Any, base_token: str, config: dict[str, Any] | None = None) -> str:
    value = first_string(payload, ("base_url", "url", "app_url", "web_url", "link", "share_url"))
    if value:
        return value
    template = ""
    if config:
        template = str(config.get("destination", {}).get("base_url_template", "")).strip()
    if template:
        return template.format(base_token=base_token)
    return f"https://www.larksuite.com/base/{base_token}"


def resolve_or_create_base(config: dict[str, Any]) -> tuple[str, str, str]:
    destination = config["destination"]
    base_token = destination.get("base_token", "")
    table_id = destination.get("table_id", "")
    if base_token:
        return base_token, table_id, destination.get("base_url", public_base_url({}, base_token, config))
    resolve_keyword = destination["base_name"][:30]
    payload = cli("base", "+title-resolve", "--title", resolve_keyword, "--as", destination["identity"], "--json")
    candidates = exact_named(unique_dicts(payload, ID_KEY_ALIASES["base"]), destination["base_name"])
    if len(candidates) > 1:
        raise SkillError(f"找到多个同名 Base“{destination['base_name']}”，请将 base_name 改为唯一名称后重试")
    if len(candidates) == 1:
        candidate = candidates[0]
        token = value_for_keys(candidate, ID_KEY_ALIASES["base"])
        return token, table_id, public_base_url(candidate, token, config)
    fields_json = json.dumps(config["fields"], ensure_ascii=False, separators=(",", ":"))
    created = cli(
        "base", "+base-create",
        "--name", destination["base_name"],
        "--table-name", destination["table_name"],
        "--fields", fields_json,
        "--time-zone", destination["time_zone"],
        "--as", destination["identity"],
        "--json",
    )
    base_token = first_string(created, ID_KEY_ALIASES["base"])
    table_id = first_string(created, ID_KEY_ALIASES["table"])
    if not base_token:
        raise SkillError("Base 创建成功响应中未找到 base_token")
    return base_token, table_id, public_base_url(created, base_token, config)


def resolve_table(base_token: str, configured_table_id: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if configured_table_id:
        return configured_table_id, {}
    destination = config["destination"]
    payload = cli("base", "+table-list", "--base-token", base_token, "--limit", "100", "--as", destination["identity"], "--json")
    matches = exact_named(unique_dicts(payload, ID_KEY_ALIASES["table"]), destination["table_name"])
    if len(matches) != 1:
        raise SkillError(f"Base 中应且仅应存在一个名为“{destination['table_name']}”的表，当前匹配数: {len(matches)}")
    table_id = value_for_keys(matches[0], ID_KEY_ALIASES["table"])
    if not table_id:
        raise SkillError(f"数据表“{destination['table_name']}”响应中缺少可用 ID")
    return table_id, matches[0]


def field_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("field_name") or "")


def field_type(item: dict[str, Any]) -> str:
    value = item.get("type") or item.get("field_type") or item.get("ui_type")
    text = str(value)
    return FIELD_TYPE_ALIASES.get(text, FIELD_TYPE_ALIASES.get(text.lower(), text))


def field_style(item: dict[str, Any]) -> dict[str, Any]:
    style = item.get("style") or item.get("property", {}).get("style") or {}
    return style if isinstance(style, dict) else {}


def is_multiple_select(item: dict[str, Any]) -> bool:
    prop = item.get("property") if isinstance(item.get("property"), dict) else {}
    return item.get("multiple") is True or prop.get("multiple") is True


def field_options(item: dict[str, Any]) -> list[Any]:
    prop = item.get("property") if isinstance(item.get("property"), dict) else {}
    options = item.get("options") if isinstance(item.get("options"), list) else prop.get("options")
    return copy.deepcopy(options) if isinstance(options, list) else []


def option_name(option: Any) -> str:
    if isinstance(option, str):
        return option
    if isinstance(option, dict):
        for key in ("name", "text", "value", "label"):
            value = option.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def clean_options(options: list[Any]) -> list[dict[str, Any]]:
    cleaned = []
    for option in options:
        name = option_name(option)
        if not name:
            continue
        item = {"name": name}
        if isinstance(option, dict):
            for key in ("hue", "lightness"):
                if isinstance(option.get(key), str) and option[key]:
                    item[key] = option[key]
        cleaned.append(item)
    return cleaned


def normalize_field_definition(definition: dict[str, Any]) -> dict[str, Any]:
    name = definition.get("name") or definition.get("field_name")
    kind = field_type(definition)
    if kind == "text":
        result: dict[str, Any] = {"type": "text", "name": name}
        style = field_style(definition)
        if style:
            result["style"] = style
        return result
    if kind == "datetime":
        result = {"type": "datetime", "name": name}
        style = field_style(definition)
        if style:
            result["style"] = style
        return result
    if kind == "select":
        return {"type": "select", "name": name, "multiple": is_multiple_select(definition), "options": clean_options(field_options(definition))}
    result = {"type": kind, "name": name}
    return result


def field_id(item: dict[str, Any]) -> str:
    return value_for_keys(item, ID_KEY_ALIASES["field"])


def remote_fields(payload: Any) -> list[dict[str, Any]]:
    return unique_dicts(payload, ID_KEY_ALIASES["field"])


def schema_names_match(payload: Any, expected_fields: list[dict[str, Any]]) -> bool:
    actual_names = {field_name(item) for item in remote_fields(payload) if field_name(item)}
    return actual_names == {item["name"] for item in expected_fields}


def validate_remote_fields(payload: Any, expected_fields: list[dict[str, Any]]) -> dict[str, str]:
    fields = remote_fields(payload)
    by_name = {field_name(item): item for item in fields}
    expected_names = [item["name"] for item in expected_fields]
    missing = [name for name in expected_names if name not in by_name]
    extra = [name for name in by_name if name and name not in expected_names]
    if missing or extra:
        raise SkillError(f"现有表字段名称不符合契约。缺少 {missing}，多余 {extra}")
    for expected in expected_fields:
        actual = by_name[expected["name"]]
        if field_type(actual) != expected["type"]:
            raise SkillError(f"字段“{expected['name']}”类型不符合契约。期望 {expected['type']}，实际 {field_type(actual)}")
    link_style = field_style(by_name["链接"])
    date_style = field_style(by_name["日期"])
    if link_style.get("type") != "url":
        raise SkillError("现有“链接”字段不是 URL 样式文本字段")
    if date_style.get("format") != "yyyy-MM-dd":
        raise SkillError("现有“日期”字段显示格式不是 yyyy-MM-dd")
    field_ids = {name: field_id(item) for name, item in by_name.items()}
    missing_ids = [name for name, value in field_ids.items() if not value]
    if missing_ids:
        raise SkillError("字段响应缺少可用 ID: " + "、".join(missing_ids))
    return field_ids


def has_records(base_token: str, table_id: str, config: dict[str, Any]) -> bool:
    payload = cli(
        "base", "+record-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--offset", "0",
        "--limit", "1",
        "--format", "json",
        "--as", config["destination"]["identity"],
    )
    return bool(extract_records(payload))


def update_field(base_token: str, table_id: str, field_id: str, definition: dict[str, Any], config: dict[str, Any]) -> None:
    cli(
        "base", "+field-update",
        "--base-token", base_token,
        "--table-id", table_id,
        "--field-id", field_id,
        "--json", json.dumps(normalize_field_definition(definition), ensure_ascii=False, separators=(",", ":")),
        "--yes",
        "--as", config["destination"]["identity"],
    )
    time.sleep(2)


def create_field(base_token: str, table_id: str, definition: dict[str, Any], config: dict[str, Any]) -> None:
    cli(
        "base", "+field-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(normalize_field_definition(definition), ensure_ascii=False, separators=(",", ":")),
        "--as", config["destination"]["identity"],
    )
    time.sleep(2)


def delete_field(base_token: str, table_id: str, field_id: str, config: dict[str, Any]) -> None:
    cli(
        "base", "+field-delete",
        "--base-token", base_token,
        "--table-id", table_id,
        "--field-id", field_id,
        "--yes",
        "--as", config["destination"]["identity"],
    )
    time.sleep(2)


def repair_empty_schema(base_token: str, table_id: str, fields_payload: Any, config: dict[str, Any]) -> None:
    if has_records(base_token, table_id, config):
        raise SkillError("修订前检测到表内已有记录，停止修改字段")
    fields = remote_fields(fields_payload)
    if len(fields) == 5:
        for item, definition in zip(fields, config["fields"]):
            update_field(base_token, table_id, field_id(item), definition, config)
        return
    if not fields:
        for definition in config["fields"]:
            create_field(base_token, table_id, definition, config)
        return
    update_field(base_token, table_id, field_id(fields[0]), config["fields"][0], config)
    for item in fields[1:]:
        delete_field(base_token, table_id, field_id(item), config)
    for definition in config["fields"][1:]:
        create_field(base_token, table_id, definition, config)


def order_default_view(base_token: str, table_id: str, config: dict[str, Any]) -> tuple[str, bool]:
    destination = config["destination"]
    if destination.get("view_id"):
        view_id = destination["view_id"]
    else:
        views = cli("base", "+view-list", "--base-token", base_token, "--table-id", table_id, "--limit", "200", "--as", destination["identity"], "--json")
        view_items = unique_dicts(views, ID_KEY_ALIASES["view"])
        view_id = value_for_keys(view_items[0], ID_KEY_ALIASES["view"]) if view_items else ""
    if view_id:
        visible = json.dumps({"visible_fields": [item["name"] for item in config["fields"]]}, ensure_ascii=False, separators=(",", ":"))
        cli("base", "+view-set-visible-fields", "--base-token", base_token, "--table-id", table_id, "--view-id", view_id, "--json", visible, "--as", destination["identity"])
        return view_id, True
    return "", False


def field_list(base_token: str, table_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return cli("base", "+field-list", "--base-token", base_token, "--table-id", table_id, "--limit", "200", "--as", config["destination"]["identity"], "--json")


def prepare(config: dict[str, Any]) -> dict[str, Any]:
    base_token, table_id, base_url = resolve_or_create_base(config)
    table_id, _ = resolve_table(base_token, table_id, config)
    fields_payload = field_list(base_token, table_id, config)
    try:
        field_ids = validate_remote_fields(fields_payload, config["fields"])
    except SkillError:
        if has_records(base_token, table_id, config):
            raise
        repair_empty_schema(base_token, table_id, fields_payload, config)
        fields_payload = field_list(base_token, table_id, config)
        field_ids = validate_remote_fields(fields_payload, config["fields"])
    view_id, view_order_applied = order_default_view(base_token, table_id, config)
    return {
        "base_token": base_token,
        "table_id": table_id,
        "view_id": view_id,
        "view_order_applied": view_order_applied,
        "base_url": base_url,
        "base_name": config["destination"]["base_name"],
        "table_name": config["destination"]["table_name"],
        "field_ids": field_ids,
    }


def response_body(payload: Any) -> Any:
    return payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload


def row_values(body: dict[str, Any]) -> list[Any]:
    for key in ("data", "rows", "items"):
        value = body.get(key)
        if isinstance(value, list):
            return value
    return []


def field_keys(fields: list[Any]) -> list[list[str]]:
    keys: list[list[str]] = []
    for index, field in enumerate(fields):
        names: list[str] = []
        if isinstance(field, str) and field:
            names.append(field)
        elif isinstance(field, dict):
            for key in ("name", "field_name"):
                value = field.get(key)
                if isinstance(value, str) and value:
                    names.append(value)
            identifier = field_id(field)
            if identifier:
                names.append(identifier)
        if not names:
            names.append(str(index))
        keys.append(list(dict.fromkeys(names)))
    return keys


def record_ids_from_body(body: dict[str, Any]) -> list[str]:
    for key in ("record_id_list", "record_ids", "recordIds"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str) and item]
    return []


def row_record_id(mapped: dict[str, Any]) -> str:
    for key in ("record_id", "recordId", "id", "记录ID"):
        value = mapped.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def records_from_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    fields = body.get("fields", [])
    rows = row_values(body)
    if not isinstance(fields, list) or not isinstance(rows, list) or not fields:
        return []
    keys = field_keys(fields)
    record_ids = record_ids_from_body(body)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        mapped: dict[str, Any] = {}
        for aliases, value in zip(keys, row):
            for alias in aliases:
                mapped[alias] = value
        record_id = record_ids[index] if index < len(record_ids) else row_record_id(mapped)
        if record_id:
            records.append({"record_id": record_id, "fields": mapped})
    return records


def extract_records(payload: Any) -> list[dict[str, Any]]:
    body = response_body(payload)
    if isinstance(body, dict):
        row_records = records_from_rows(body)
        if row_records:
            return row_records
    records = unique_dicts(payload, ID_KEY_ALIASES["record"])
    normalized = []
    for record in records:
        record_id = value_for_keys(record, ID_KEY_ALIASES["record"])
        if record_id:
            item = dict(record)
            item["record_id"] = record_id
            normalized.append(item)
    if normalized:
        return normalized
    record_ids = pagination_value(payload, ("record_id_list", "record_ids", "recordIds"), [])
    if isinstance(record_ids, list):
        return [{"record_id": item} for item in record_ids if isinstance(item, str) and item]
    return []


def cell_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("link", "url", "text", "value"):
            if isinstance(value.get(key), str):
                return value[key]
    if isinstance(value, list):
        for item in value:
            text = cell_text(item)
            if text:
                return text
    return ""


def record_field(record: dict[str, Any], base_state: dict[str, Any], name: str) -> Any:
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else record
    if not isinstance(fields, dict):
        return None
    candidates = [name]
    field_ids = base_state.get("field_ids")
    if isinstance(field_ids, dict) and field_ids.get(name):
        candidates.append(field_ids[name])
    for key in candidates:
        if key in fields:
            return fields[key]
    return None


def record_link(record: dict[str, Any], base_state: dict[str, Any] | None = None) -> str:
    if not base_state:
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else record
        return cell_text(fields.get("链接")) if isinstance(fields, dict) else ""
    return cell_text(record_field(record, base_state, "链接"))


def normalize_date_cell(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError) as exc:
            raise SkillError(f"日期格式无效: {value}") from exc
    if isinstance(value, str):
        text = value.strip()
        return parse_iso_date(text).isoformat() if text else ""
    if isinstance(value, dict):
        for key in ("date", "datetime", "timestamp", "value", "text"):
            if key in value:
                date_value = normalize_date_cell(value[key])
                if date_value:
                    return date_value
        return ""
    if isinstance(value, list):
        for item in value:
            date_value = normalize_date_cell(item)
            if date_value:
                return date_value
    return ""


def record_date(record: dict[str, Any], base_state: dict[str, Any]) -> str:
    return normalize_date_cell(record_field(record, base_state, "日期"))


def pagination_value(payload: Any, keys: tuple[str, ...], default: Any = None) -> Any:
    for item in walk_values(payload):
        if isinstance(item, dict):
            for key in keys:
                if key in item:
                    return item[key]
    return default


def list_records(config: dict[str, Any], base_state: dict[str, Any], field_names: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    offset = 0
    seen_records = set()
    while True:
        command = [
            "base", "+record-list",
            "--base-token", base_state["base_token"],
            "--table-id", base_state["table_id"],
        ]
        for name in field_names:
            command.extend(("--field-id", base_state["field_ids"].get(name, name)))
        command.extend((
            "--offset", str(offset),
            "--limit", "200",
            "--format", "json",
            "--as", config["destination"]["identity"],
        ))
        payload = cli(*command)
        records = extract_records(payload)
        for record in records:
            record_id = record["record_id"]
            if record_id in seen_records:
                continue
            seen_records.add(record_id)
            result.append(record)
        has_more = bool(pagination_value(payload, ("has_more",), False))
        if not has_more or not records:
            break
        next_offset = pagination_value(payload, ("next_offset", "offset"), None)
        offset = int(next_offset) if next_offset is not None and int(next_offset) > offset else offset + len(records)
    return result


def list_link_records(config: dict[str, Any], base_state: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for record in list_records(config, base_state, ("链接",)):
        link = record_link(record, base_state)
        if link:
            result.append((record["record_id"], link))
    return result


def export_state(config: dict[str, Any], base_state: dict[str, Any]) -> dict[str, Any]:
    records = list_records(config, base_state, ("日期", "链接"))
    links = set()
    latest_date = ""
    for record in records:
        submitted_date = record_date(record, base_state)
        if not submitted_date:
            raise SkillError(f"飞书记录缺少有效日期: {record['record_id']}")
        latest_date = max(latest_date, submitted_date)
        link = record_link(record, base_state)
        if link:
            try:
                links.add(canonical_abs_url(link))
            except SkillError:
                continue
    return {"record_count": len(records), "latest_date": latest_date, "links": sorted(links)}


def find_existing_record(config: dict[str, Any], base_state: dict[str, Any], link: str) -> str:
    expected = canonical_abs_url(link)
    matches = []
    for record_id, existing in list_link_records(config, base_state):
        try:
            if canonical_abs_url(existing) == expected:
                matches.append(record_id)
        except SkillError:
            continue
    if len(set(matches)) > 1:
        raise SkillError(f"链接字段存在重复记录，无法安全写入: {expected}")
    return matches[0] if matches else ""


def created_record_ids(payload: Any) -> list[str]:
    body = response_body(payload)
    ids: list[str] = []
    if isinstance(body, dict):
        for key in ("record_id_list", "record_ids", "recordIds"):
            value = body.get(key)
            if isinstance(value, list):
                ids.extend(item for item in value if isinstance(item, str) and item)
        for key in ("records", "items", "data"):
            value = body.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        record_id = value_for_keys(item, ("record_id", "recordId", "id"))
                        if record_id:
                            ids.append(record_id)
    if not ids:
        for item in walk_values(payload):
            if isinstance(item, dict):
                record_id = value_for_keys(item, ("record_id", "recordId"))
                if record_id:
                    ids.append(record_id)
    return list(dict.fromkeys(ids))


def create_record(config: dict[str, Any], base_state: dict[str, Any], paper: dict[str, Any]) -> str:
    submitted_date = paper.get("submitted_date")
    if not submitted_date:
        raise SkillError(f"论文缺少 submitted_date: {paper['canonical_id']}")
    parse_iso_date(submitted_date)
    fields = ["标题", "摘要", "关键词", "日期", "链接"]
    row = [
        paper["title"],
        paper["abstract_zh"],
        "、".join(paper["keywords"]),
        submitted_date + "T00:00:00Z",
        markdown_abs_link(paper["abs_url"]),
    ]
    body = {"fields": fields, "rows": [row]}
    payload = cli(
        "base", "+record-batch-create",
        "--base-token", base_state["base_token"],
        "--table-id", base_state["table_id"],
        "--json", json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        "--as", config["destination"]["identity"],
    )
    record_ids = created_record_ids(payload)
    if len(record_ids) != 1:
        raise SkillError(f"记录创建响应缺少唯一 record_id: {paper['canonical_id']}")
    return record_ids[0]


def write_papers(config: dict[str, Any], base_state: dict[str, Any], state: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    papers = state.get("papers", [])
    if state.get("submitted_date"):
        prune_manifest_file(manifest_path, state["submitted_date"], config["retention_days"])
    manifest = load_json(manifest_path) if manifest_path.exists() else {"papers": {}}
    completed = manifest.setdefault("papers", {})
    written_count = 0
    for paper in papers:
        if not paper.get("abstract_zh"):
            raise SkillError(f"缺少中文摘要，停止写入: {paper['canonical_id']}")
        paper["keywords"] = validate_keywords(paper.get("keywords"), paper)
        progress = completed.setdefault(paper["canonical_id"], {"submitted_date": paper.get("submitted_date", "")})
        record_id = find_existing_record(config, base_state, paper["abs_url"])
        if not record_id:
            record_id = progress.get("record_id") or create_record(config, base_state, paper)
        progress["record_id"] = record_id
        progress["submitted_date"] = paper.get("submitted_date", "")
        paper["record_id"] = record_id
        save_json(manifest_path, manifest)
        written_count += 1
    state.setdefault("stats", {})["written_count"] = written_count
    state["stats"]["failure_count"] = sum(bool(paper.get("errors")) for paper in papers)
    save_json(Path(manifest_path).parent / "base.json", base_state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and write the Feishu/Lark Base")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--config", required=True)
    prepare_parser.add_argument("--output", required=True)
    export_parser = subparsers.add_parser("export-state")
    export_parser.add_argument("--config", required=True)
    export_parser.add_argument("--base-state", required=True)
    export_parser.add_argument("--output", required=True)
    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("--config", required=True)
    write_parser.add_argument("--base-state", required=True)
    write_parser.add_argument("--papers", required=True)
    write_parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "prepare":
            state = prepare(config)
            save_json(args.output, state)
            result = {"ok": True, "output": args.output, "base_name": state["base_name"], "table_name": state["table_name"], "base_url": state["base_url"]}
        elif args.command == "export-state":
            state = export_state(config, load_json(args.base_state))
            save_json(args.output, state)
            result = {
                "ok": True,
                "output": args.output,
                "record_count": state["record_count"],
                "latest_date": state["latest_date"],
                "link_count": len(state["links"]),
            }
        else:
            state = write_papers(config, load_json(args.base_state), load_json(args.papers), Path(args.manifest))
            save_json(args.papers, state)
            result = {"ok": True, "written_count": state["stats"]["written_count"], "manifest": args.manifest}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SkillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
