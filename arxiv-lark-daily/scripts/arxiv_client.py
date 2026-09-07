#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common import SkillError, canonical_abs_url, load_config, load_json, prune_manifest_file, save_json

ATOM = "http://www.w3.org/2005/Atom"
OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"
ARXIV = "http://arxiv.org/schemas/atom"
FIELD_PREFIX = {
    "all": "all",
    "title": "ti",
    "author": "au",
    "abstract": "abs",
    "comment": "co",
    "journal_reference": "jr",
    "report_number": "rn",
    "category": "cat",
}


@dataclass
class FeedPage:
    entries: list[dict[str, Any]]
    total_results: int
    start_index: int
    items_per_page: int


def normalize_space(text: str | None) -> str:
    return " ".join((text or "").split())


def normalize_id(value: str) -> tuple[str, int]:
    from common import normalize_id as common_normalize_id
    return common_normalize_id(value)


def quote_term(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if any(char.isspace() for char in term) or "-" in term else escaped


def build_search_query(arxiv_config: dict[str, Any]) -> str:
    expressions: list[tuple[str, str]] = []
    for index, item in enumerate(arxiv_config.get("terms", [])):
        field = item.get("field", "all")
        if field not in FIELD_PREFIX:
            raise SkillError(f"不支持的 arXiv 搜索字段: {field}")
        term = normalize_space(item.get("term"))
        if not term:
            continue
        operator = str(item.get("operator", "AND")).upper()
        if operator not in {"AND", "OR", "NOT"}:
            raise SkillError(f"不支持的布尔操作符: {operator}")
        expression = f"{FIELD_PREFIX[field]}:{quote_term(term)}"
        expressions.append((operator if index else "", expression))
    if not expressions:
        raise SkillError("至少需要一个非空 arXiv 搜索词")
    query = expressions[0][1]
    for operator, expression in expressions[1:]:
        api_operator = "ANDNOT" if operator == "NOT" else operator
        query = f"({query} {api_operator} {expression})"
    categories = arxiv_config.get("categories", [])
    if categories:
        category_query = " OR ".join(f"cat:{item}" for item in categories)
        query = f"({query} AND ({category_query}))"
    return query


def category_matches(value: str, configured: list[str]) -> bool:
    for category in configured:
        if category.endswith(".*") and value.startswith(category[:-1]):
            return True
        if value == category:
            return True
    return False


def paper_matches_category_mode(paper: dict[str, Any], config: dict[str, Any]) -> bool:
    categories = config.get("categories", [])
    if not categories or config.get("include_cross_list", True):
        return True
    return category_matches(paper.get("primary_category", ""), categories)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_feed(xml_bytes: bytes) -> FeedPage:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise SkillError(f"arXiv 返回了无效 Atom XML: {exc}") from exc
    entries: list[dict[str, Any]] = []
    for node in root.findall(f"{{{ATOM}}}entry"):
        title = normalize_space(node.findtext(f"{{{ATOM}}}title"))
        entry_id = normalize_space(node.findtext(f"{{{ATOM}}}id"))
        summary = normalize_space(node.findtext(f"{{{ATOM}}}summary"))
        if title == "Error" or "/api/errors#" in entry_id:
            raise SkillError(f"arXiv API Error: {summary or entry_id}")
        canonical_id, version = normalize_id(entry_id)
        published = normalize_space(node.findtext(f"{{{ATOM}}}published"))
        updated = normalize_space(node.findtext(f"{{{ATOM}}}updated"))
        if not published or not updated:
            raise SkillError(f"arXiv 条目缺少日期: {canonical_id}")
        updated_iso = parse_datetime(updated).isoformat().replace("+00:00", "Z")
        primary = node.find(f"{{{ARXIV}}}primary_category")
        entries.append({
            "canonical_id": canonical_id,
            "version": version,
            "title": title,
            "abstract_en": summary,
            "abstract_zh": "",
            "published": parse_datetime(published).isoformat().replace("+00:00", "Z"),
            "updated": updated_iso,
            "submitted_date": updated_iso[:10],
            "abs_url": f"https://arxiv.org/abs/{canonical_id}",
            "authors": [normalize_space(author.findtext(f"{{{ATOM}}}name")) for author in node.findall(f"{{{ATOM}}}author")],
            "primary_category": primary.attrib.get("term", "") if primary is not None else "",
            "categories": [item.attrib.get("term", "") for item in node.findall(f"{{{ATOM}}}category")],
            "tags": [],
            "record_id": "",
            "errors": [],
        })

    def integer(path: str) -> int:
        text = root.findtext(path)
        return int(text or 0)

    return FeedPage(
        entries=entries,
        total_results=integer(f"{{{OPENSEARCH}}}totalResults"),
        start_index=integer(f"{{{OPENSEARCH}}}startIndex"),
        items_per_page=integer(f"{{{OPENSEARCH}}}itemsPerPage"),
    )


class ArxivClient:
    def __init__(self, config: dict[str, Any], opener: Callable[[urllib.request.Request, float], bytes] | None = None, sleeper: Callable[[float], None] = time.sleep):
        self.config = config
        self.sleeper = sleeper
        self.opener = opener or self._open
        self.last_request_at = 0.0

    def _open(self, request: urllib.request.Request, timeout: float) -> bytes:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def _request_page(self, query: str, start: int) -> FeedPage:
        interval = max(3.0, float(self.config.get("request_interval_seconds", 3.0)))
        elapsed = time.monotonic() - self.last_request_at
        if self.last_request_at and elapsed < interval:
            self.sleeper(interval - elapsed)
        params = urllib.parse.urlencode({
            "search_query": query,
            "start": start,
            "max_results": int(self.config.get("page_size", 200)),
            "sortBy": self.config.get("sort_by", "lastUpdatedDate"),
            "sortOrder": self.config.get("sort_order", "descending"),
        })
        request = urllib.request.Request(
            self.config.get("api_url", "https://export.arxiv.org/api/query") + "?" + params,
            headers={"User-Agent": self.config.get("user_agent", "arxiv-lark-daily/1.0")},
        )
        retries = int(self.config.get("max_retries", 3))
        timeout = float(self.config.get("timeout_seconds", 45))
        for attempt in range(retries + 1):
            try:
                self.last_request_at = time.monotonic()
                return parse_feed(self.opener(request, timeout))
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                    raise SkillError(f"arXiv HTTP 错误: {exc.code}") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleeper(max(interval, float(retry_after or 0)))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= retries:
                    raise SkillError(f"arXiv 网络请求失败: {exc}") from exc
                self.sleeper(interval)
        raise SkillError("arXiv 请求重试耗尽")

    def fetch_newest_unseen_day(self, existing_links: set[str]) -> dict[str, Any]:
        query = build_search_query(self.config)
        page_size = int(self.config.get("page_size", 200))
        cap = int(self.config.get("max_accessible_results", 30000))
        start = 0
        submitted_date = ""
        selected: dict[str, dict[str, Any]] = {}
        observed: set[str] = set()
        total_results = None
        while True:
            if start >= cap:
                raise SkillError("为证明目标日期完整性需要访问超过 30,000 条结果，请缩小筛选条件")
            page = self._request_page(query, start)
            if page.start_index != start:
                raise SkillError(f"arXiv 分页索引不一致: 请求 {start}，返回 {page.start_index}")
            if total_results is None:
                total_results = page.total_results
            elif page.total_results != total_results:
                raise SkillError(f"arXiv totalResults 跨页不一致: 首页 {total_results}，当前 {page.total_results}")
            if page.items_per_page and page.entries and page.items_per_page != len(page.entries):
                raise SkillError(f"arXiv itemsPerPage 与实际条目数不一致: 声明 {page.items_per_page}，实际 {len(page.entries)}")
            if not page.entries:
                break
            stop_after_page = False
            for paper in page.entries:
                day = paper["submitted_date"]
                if submitted_date and day < submitted_date:
                    stop_after_page = True
                    break
                if not paper_matches_category_mode(paper, self.config):
                    continue
                canonical = paper["canonical_id"]
                if canonical in observed:
                    continue
                observed.add(canonical)
                if paper["abs_url"] in existing_links:
                    continue
                if not submitted_date:
                    submitted_date = day
                if day == submitted_date:
                    selected[canonical] = paper
            if stop_after_page:
                break
            start += len(page.entries)
            if start >= page.total_results or len(page.entries) < page_size:
                break
        papers = sorted(selected.values(), key=lambda item: (item["updated"], item["canonical_id"]), reverse=True)
        return {
            "status": "ok" if papers else "no_new_papers",
            "date_semantics": "submitted_date_from_atom_updated_utc",
            "submitted_date": submitted_date,
            "filter_summary": query,
            "query": query,
            "total_results": total_results or 0,
            "papers": papers,
            "stats": {"discovered_count": len(papers), "written_count": 0, "failure_count": 0},
        }


def normalize_existing_links(items: list[Any]) -> set[str]:
    links: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            links.add(canonical_abs_url(item))
        except SkillError:
            continue
    return links


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the newest unseen arXiv submitted_date")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--config", required=True)
    fetch.add_argument("--existing-links", required=True)
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--manifest")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        existing_data = load_json(args.existing_links)
        existing_links = normalize_existing_links(existing_data.get("links", []))
        state = ArxivClient(config["arxiv"]).fetch_newest_unseen_day(existing_links)
        if state.get("submitted_date") and args.manifest:
            prune_manifest_file(args.manifest, state["submitted_date"], config["retention_days"])
        save_json(args.output, state)
        if state["status"] == "no_new_papers":
            print(config["summary"]["no_new_message"])
        else:
            print(json.dumps({"ok": True, "status": state["status"], "submitted_date": state["submitted_date"], "paper_count": len(state["papers"]), "output": str(Path(args.output))}, ensure_ascii=False))
        return 0
    except SkillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
