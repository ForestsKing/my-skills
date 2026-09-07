#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


class SkillError(RuntimeError):
    pass


FIELDS = [
    {"name": "标题", "type": "text"},
    {"name": "摘要", "type": "text"},
    {"name": "标签", "type": "select", "multiple": True, "options": []},
    {"name": "日期", "type": "datetime", "style": {"format": "yyyy-MM-dd"}},
    {"name": "链接", "type": "text", "style": {"type": "url"}},
]
SUPPORTED_SEARCH_FIELDS = {
    "all", "title", "author", "abstract", "comment",
    "journal_reference", "report_number", "category",
}
ID_PATTERN = re.compile(r"(?:abs/|pdf/)?(?P<id>(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5}))(?P<version>v\d+)?(?:\.pdf)?$", re.I)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\((?P<url>https?://[^)]+)\)")
URL_PATTERN = re.compile(r"https?://[^\s)]+")
CATEGORY_PATTERN = re.compile(r"^[a-z]+(?:\.[A-Z]{2})?(?:\.\*)?$")


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, target)


def load_config(path: str | Path) -> dict[str, Any]:
    raw = load_json(path)
    base_name = str(raw.get("base_name", "")).strip()
    table_name = str(raw.get("table_name", "")).strip()
    search = raw.get("search")
    if not base_name or not table_name or not isinstance(search, dict):
        raise SkillError("配置必须包含非空 base_name、table_name 和 search")
    field = str(search.get("field", "title")).strip()
    if field not in SUPPORTED_SEARCH_FIELDS:
        raise SkillError(f"search.field 不支持: {field}")
    keywords = search.get("keywords")
    if not isinstance(keywords, list) or not keywords or not all(isinstance(item, str) and item.strip() for item in keywords):
        raise SkillError("search.keywords 必须是非空字符串数组")
    match = str(search.get("match", "any")).lower()
    if match not in {"any", "all"}:
        raise SkillError("search.match 只能是 any 或 all")
    categories = search.get("categories", [])
    if not isinstance(categories, list) or not all(isinstance(item, str) and item.strip() for item in categories):
        raise SkillError("search.categories 必须是字符串数组")
    cleaned_categories = [item.strip() for item in categories]
    invalid_categories = [item for item in cleaned_categories if not CATEGORY_PATTERN.fullmatch(item)]
    if invalid_categories:
        raise SkillError("search.categories 包含非法 arXiv 分类: " + "、".join(invalid_categories))
    include_cross_list = search.get("include_cross_list", True)
    if not isinstance(include_cross_list, bool):
        raise SkillError("search.include_cross_list 必须是 true 或 false")
    retention_days = raw.get("retention_days", 30)
    if not isinstance(retention_days, int) or retention_days < 1:
        raise SkillError("retention_days 必须是正整数")
    operator = "OR" if match == "any" else "AND"
    terms = [
        {"term": keyword.strip(), "field": field, "operator": "AND" if index == 0 else operator}
        for index, keyword in enumerate(keywords)
    ]
    return {
        "source_config": raw,
        "destination": {
            "base_name": base_name,
            "table_name": table_name,
            "identity": "user",
            "time_zone": "Asia/Shanghai",
            "base_url_template": str(raw.get("base_url_template", "")).strip(),
        },
        "fields": copy.deepcopy(FIELDS),
        "retention_days": retention_days,
        "state": {
            "work_dir": ".arxiv-lark-daily",
            "manifest": ".arxiv-lark-daily/write-manifest.json",
        },
        "arxiv": {
            "api_url": "https://export.arxiv.org/api/query",
            "terms": terms,
            "categories": cleaned_categories,
            "include_cross_list": include_cross_list,
            "sort_by": "lastUpdatedDate",
            "sort_order": "descending",
            "page_size": 200,
            "max_accessible_results": 30000,
            "request_interval_seconds": 3.0,
            "timeout_seconds": 45,
            "max_retries": 3,
            "user_agent": "arxiv-lark-daily/1.0 (personal research workflow)",
        },
        "summary": {
            "template": "templates/daily-summary.md",
            "no_new_message": "今天暂未发现符合条件的新论文，可以安心跳过本次归档。",
        },
    }


def validate_fields(fields: list[dict[str, Any]]) -> None:
    if fields != FIELDS:
        raise SkillError("表格字段定义不是 skill 要求的固定五列")


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return env


def error_message(payload: dict[str, Any]) -> str:
    for key in ("message", "msg", "error_description"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error
    if isinstance(error, dict):
        nested = error_message(error)
        if nested:
            return nested
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return json.dumps(errors[:3], ensure_ascii=False)
    data = payload.get("data")
    if isinstance(data, dict):
        nested = error_message(data)
        if nested:
            return nested
    return json.dumps(payload, ensure_ascii=False)[:1000]


def response_failed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False or payload.get("success") is False:
        return True
    for key in ("code", "err_code"):
        if key in payload and str(payload.get(key)) not in {"0", ""}:
            return True
    has_success_marker = payload.get("ok") is True or payload.get("success") is True or str(payload.get("code", "")) == "0" or str(payload.get("err_code", "")) == "0"
    if ("error" in payload or "errors" in payload) and not has_success_marker:
        return True
    return False


def run_command(args: list[str], cwd: str | Path | None = None) -> dict[str, Any]:
    result = subprocess.run(args, cwd=cwd, env=command_env(), text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = sanitize(result.stderr.strip() or result.stdout.strip())
        raise SkillError(f"命令失败 ({result.returncode}): {' '.join(args[:3])}: {detail}")
    text = result.stdout.strip()
    if not text:
        return {"ok": True}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillError(f"命令未返回有效 JSON: {sanitize(text[:500])}") from exc
    if response_failed(payload):
        raise SkillError(f"lark-cli 返回失败: {sanitize(error_message(payload))}")
    return payload


def sanitize(text: str) -> str:
    cleaned = re.sub(r'(?i)(access_token|refresh_token|app_secret|device_code)\s*[=:]\s*[^\s,}\"]+', r"\1=<redacted>", text)
    return re.sub(r'(?i)Bearer\s+[A-Za-z0-9._-]+', "<redacted>", cleaned)


def walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)


def find_dicts(value: Any, required_any: set[str]) -> list[dict[str, Any]]:
    return [item for item in walk_values(value) if isinstance(item, dict) and required_any.intersection(item)]


def first_string(value: Any, keys: tuple[str, ...]) -> str:
    for item in walk_values(value):
        if not isinstance(item, dict):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return ""


def extract_url(value: str) -> str:
    text = str(value or "").strip()
    markdown = MARKDOWN_LINK_PATTERN.search(text)
    if markdown:
        return markdown.group("url").strip()
    url = URL_PATTERN.search(text)
    if url:
        return url.group(0).strip()
    return text


def normalize_id(value: str) -> tuple[str, int]:
    extracted = extract_url(value)
    path = urllib.parse.urlparse(extracted).path if "://" in extracted else extracted
    path = path.strip("/")
    match = ID_PATTERN.search(path)
    if not match:
        raise SkillError(f"无法解析 arXiv ID: {value}")
    canonical = match.group("id")
    version_text = match.group("version")
    return canonical, int(version_text[1:]) if version_text else 1


def canonical_abs_url(value: str) -> str:
    canonical, _ = normalize_id(value)
    return f"https://arxiv.org/abs/{canonical}"


def markdown_abs_link(value: str) -> str:
    return f"[链接]({canonical_abs_url(value)})"


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise SkillError(f"日期格式无效: {value}") from exc


def prune_old_paper_entries(container: Any, latest_submitted_date: str, retention_days: int) -> Any:
    cutoff = parse_iso_date(latest_submitted_date) - timedelta(days=retention_days)

    def keep(item: Any) -> bool:
        if not isinstance(item, dict):
            return True
        submitted = item.get("submitted_date") or item.get("target_date")
        if not isinstance(submitted, str) or not submitted:
            return True
        return parse_iso_date(submitted) >= cutoff

    if isinstance(container, list):
        return [item for item in container if keep(item)]
    if isinstance(container, dict):
        if isinstance(container.get("papers"), list):
            container = copy.deepcopy(container)
            container["papers"] = prune_old_paper_entries(container["papers"], latest_submitted_date, retention_days)
        elif isinstance(container.get("papers"), dict):
            container = copy.deepcopy(container)
            container["papers"] = prune_old_paper_entries(container["papers"], latest_submitted_date, retention_days)
        elif all(isinstance(value, dict) for value in container.values()):
            return {key: value for key, value in container.items() if keep(value)}
        return container
    return container


def prune_manifest_file(path: str | Path, latest_submitted_date: str, retention_days: int) -> bool:
    target = Path(path)
    if not target.exists():
        return False
    data = load_json(target)
    pruned = prune_old_paper_entries(data, latest_submitted_date, retention_days)
    if pruned != data:
        save_json(target, pruned)
        return True
    return False
