#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import http.client
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

from common import SkillError, canonical_abs_url, load_config, load_json, parse_iso_date, prune_manifest_file, save_json

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


@dataclass
class WebSearchPage:
    entries: list[dict[str, Any]]
    total_results: int


class ArxivTransportError(SkillError):
    pass


class SearchHtmlParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, Any]] = []
        self.page_text: list[str] = []
        self.current: dict[str, Any] | None = None
        self.title_active = False
        self.authors_active = False
        self.author_active = False
        self.abstract_active = False
        self.abstract_link_active = False
        self.date_active = False
        self.tags_active = False
        self.category_active = False
        self.category_primary = False

    @staticmethod
    def _classes(attrs: dict[str, str | None]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = self._classes(attrs)
        if tag == "li" and "arxiv-result" in classes:
            self.current = {
                "canonical_id": "",
                "title_parts": [],
                "authors": [],
                "author_parts": [],
                "abstract_parts": [],
                "date_parts": [],
                "categories": [],
                "primary_category": "",
                "category_parts": [],
            }
            return
        if self.current is None:
            return
        if tag == "a":
            href = attrs.get("href") or ""
            match = re.search(r"/abs/([^?#]+)", href)
            if match and not self.current["canonical_id"]:
                self.current["canonical_id"] = normalize_id(match.group(1))[0]
            if self.authors_active and "searchtype=author" in href:
                self.author_active = True
                self.current["author_parts"] = []
            if self.abstract_active:
                self.abstract_link_active = True
        elif tag == "p":
            if "title" in classes:
                self.title_active = True
            elif "authors" in classes:
                self.authors_active = True
            elif "is-size-7" in classes:
                self.date_active = True
        elif tag == "span" and "abstract-full" in classes:
            self.abstract_active = True
        elif tag == "div" and "tags" in classes:
            self.tags_active = True
        elif tag == "span" and self.tags_active and "tag" in classes:
            self.category_active = True
            self.category_primary = "is-link" in classes
            self.current["category_parts"] = []

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == "a":
            if self.author_active:
                author = normalize_space("".join(self.current["author_parts"]))
                if author:
                    self.current["authors"].append(author)
                self.author_active = False
            if self.abstract_link_active:
                self.abstract_link_active = False
        elif tag == "p":
            self.title_active = False
            self.authors_active = False
            self.date_active = False
        elif tag == "span":
            if self.category_active:
                category = normalize_space("".join(self.current["category_parts"]))
                if category:
                    self.current["categories"].append(category)
                    if self.category_primary:
                        self.current["primary_category"] = category
                self.category_active = False
                self.category_primary = False
            elif self.abstract_active and not self.abstract_link_active:
                self.abstract_active = False
        elif tag == "div" and self.tags_active:
            self.tags_active = False
        elif tag == "li":
            self._finish_result()

    def handle_data(self, data: str) -> None:
        self.page_text.append(data)
        if self.current is None:
            return
        if self.title_active:
            self.current["title_parts"].append(data)
        if self.author_active:
            self.current["author_parts"].append(data)
        if self.abstract_active and not self.abstract_link_active:
            self.current["abstract_parts"].append(data)
        if self.date_active:
            self.current["date_parts"].append(data)
        if self.category_active:
            self.current["category_parts"].append(data)

    def _finish_result(self) -> None:
        if self.current is None:
            return
        date_text = normalize_space("".join(self.current["date_parts"]))
        match = re.search(r"Submitted\s+(\d{1,2}\s+[A-Za-z]+,\s+\d{4})", date_text)
        if self.current["canonical_id"] and match:
            submitted = datetime.strptime(match.group(1), "%d %B, %Y").date().isoformat()
            self.entries.append({
                "canonical_id": self.current["canonical_id"],
                "title": normalize_space("".join(self.current["title_parts"])),
                "authors": self.current["authors"],
                "abstract_en": normalize_space("".join(self.current["abstract_parts"])),
                "submitted_date": submitted,
                "primary_category": self.current["primary_category"],
                "categories": self.current["categories"],
            })
        self.current = None
        self.title_active = False
        self.authors_active = False
        self.author_active = False
        self.abstract_active = False
        self.abstract_link_active = False
        self.date_active = False
        self.tags_active = False
        self.category_active = False


class AbsHtmlParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, list[str]] = {}
        self.submission_active = False
        self.submission_div_depth = 0
        self.submission_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if tag == "meta":
            name = attrs.get("name") or ""
            content = attrs.get("content") or ""
            if name.startswith("citation_") and content:
                self.metadata.setdefault(name, []).append(content)
        if tag == "div":
            classes = set((attrs.get("class") or "").split())
            if self.submission_active:
                self.submission_div_depth += 1
            elif "submission-history" in classes:
                self.submission_active = True
                self.submission_div_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.submission_active:
            self.submission_div_depth -= 1
            if self.submission_div_depth == 0:
                self.submission_active = False

    def handle_data(self, data: str) -> None:
        if self.submission_active:
            self.submission_parts.append(data)


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
            "keywords": [],
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


def parse_web_search(xml_bytes: bytes) -> WebSearchPage:
    parser = SearchHtmlParser()
    try:
        parser.feed(xml_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SkillError(f"arXiv 搜索网页解析失败: {exc}") from exc
    page_text = normalize_space("".join(parser.page_text))
    total_match = re.search(r"Showing\s+[\d,]+[–-][\d,]+\s+of\s+([\d,]+)\s+results", page_text)
    if not total_match:
        no_results = "Sorry, your query for" in page_text and "produced no results" in page_text
        if no_results:
            return WebSearchPage(entries=[], total_results=0)
        raise SkillError("arXiv 搜索网页缺少结果总数")
    return WebSearchPage(entries=parser.entries, total_results=int(total_match.group(1).replace(",", "")))


def parse_abs_page(xml_bytes: bytes, search_entry: dict[str, Any]) -> dict[str, Any]:
    parser = AbsHtmlParser()
    try:
        parser.feed(xml_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SkillError(f"arXiv 摘要网页解析失败: {exc}") from exc
    metadata = parser.metadata
    canonical_id, _ = normalize_id((metadata.get("citation_arxiv_id") or [search_entry["canonical_id"]])[0])
    if canonical_id != search_entry["canonical_id"]:
        raise SkillError(f"arXiv 摘要网页 ID 不一致: 期望 {search_entry['canonical_id']}，得到 {canonical_id}")
    history = normalize_space("".join(parser.submission_parts))
    versions = re.findall(
        r"\[v(\d+)\]\s*([A-Z][a-z]{2},\s+\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+UTC)",
        history,
    )
    if not versions:
        raise SkillError(f"arXiv 摘要网页缺少提交历史: {canonical_id}")
    parsed_versions = [
        (int(version), datetime.strptime(value, "%a, %d %b %Y %H:%M:%S UTC").replace(tzinfo=timezone.utc))
        for version, value in versions
    ]
    version, updated_at = parsed_versions[-1]
    published_at = parsed_versions[0][1]
    if updated_at.date().isoformat() != search_entry["submitted_date"]:
        raise SkillError(
            f"arXiv 搜索页与摘要页日期不一致: {canonical_id}，"
            f"搜索页 {search_entry['submitted_date']}，摘要页 {updated_at.date().isoformat()}"
        )
    title = normalize_space((metadata.get("citation_title") or [search_entry["title"]])[0])
    abstract = normalize_space((metadata.get("citation_abstract") or [search_entry["abstract_en"]])[0])
    return {
        "canonical_id": canonical_id,
        "version": version,
        "title": title,
        "abstract_en": abstract,
        "abstract_zh": "",
        "published": published_at.isoformat().replace("+00:00", "Z"),
        "updated": updated_at.isoformat().replace("+00:00", "Z"),
        "submitted_date": updated_at.date().isoformat(),
        "abs_url": f"https://arxiv.org/abs/{canonical_id}",
        "authors": search_entry["authors"] or metadata.get("citation_author", []),
        "primary_category": search_entry["primary_category"],
        "categories": search_entry["categories"],
        "keywords": [],
        "record_id": "",
        "errors": [],
    }


def build_web_query(config: dict[str, Any]) -> tuple[str, str]:
    terms = config.get("terms", [])
    if not terms:
        raise SkillError("至少需要一个非空 arXiv 搜索词")
    fields = {item.get("field", "all") for item in terms}
    if len(fields) != 1:
        raise SkillError("搜索网页备用通道要求所有检索词使用同一个字段")
    field = fields.pop()
    search_types = {
        "all": "all",
        "title": "title",
        "author": "author",
        "abstract": "abstract",
        "comment": "comments",
        "journal_reference": "journal_ref",
        "report_number": "report_num",
        "category": "all",
    }
    if field not in search_types:
        raise SkillError(f"搜索网页备用通道不支持字段: {field}")
    parts: list[str] = []
    for index, item in enumerate(terms):
        term = normalize_space(item.get("term"))
        if not term:
            continue
        operator = str(item.get("operator", "AND")).upper()
        if index:
            parts.append(operator)
        parts.append(quote_term(term))
    return " ".join(parts), search_types[field]


def paper_matches_web_filters(paper: dict[str, Any], config: dict[str, Any]) -> bool:
    configured = config.get("categories", [])
    if configured:
        if config.get("include_cross_list", True):
            if not any(category_matches(value, configured) for value in paper.get("categories", [])):
                return False
        elif not category_matches(paper.get("primary_category", ""), configured):
            return False
    values = {
        "title": paper.get("title", ""),
        "author": " ".join(paper.get("authors", [])),
        "abstract": paper.get("abstract_en", ""),
        "category": " ".join(paper.get("categories", [])),
    }
    values["all"] = " ".join(values.values())
    result: bool | None = None
    for item in config.get("terms", []):
        field = item.get("field", "all")
        if field not in values:
            return True
        matched = normalize_space(item.get("term")).casefold() in values[field].casefold()
        operator = str(item.get("operator", "AND")).upper()
        if result is None:
            result = matched
        elif operator == "OR":
            result = result or matched
        elif operator == "NOT":
            result = result and not matched
        else:
            result = result and matched
    return bool(result)


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
        retries = int(self.config.get("atom_max_retries", 1))
        timeout = float(self.config.get("atom_timeout_seconds", 15))
        for attempt in range(retries + 1):
            try:
                self.last_request_at = time.monotonic()
                return parse_feed(self.opener(request, timeout))
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise SkillError(f"arXiv HTTP 错误: {exc.code}") from exc
                if attempt >= retries:
                    raise ArxivTransportError(f"arXiv HTTP 错误: {exc.code}") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleeper(max(interval, float(retry_after or 0)))
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
                if attempt >= retries:
                    raise ArxivTransportError(f"arXiv 网络请求失败: {exc}") from exc
                self.sleeper(interval)
        raise ArxivTransportError("arXiv 请求重试耗尽")

    def _fetch_latest_day_atom(self, existing_links: set[str], latest_date: str = "") -> dict[str, Any]:
        query = build_search_query(self.config)
        latest_archived = parse_iso_date(latest_date) if latest_date else None
        page_size = int(self.config.get("page_size", 200))
        cap = int(self.config.get("max_accessible_results", 30000))
        start = 0
        submitted_date = ""
        selected: dict[str, dict[str, Any]] = {}
        observed: set[str] = set()
        total_results = None

        def result() -> dict[str, Any]:
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
                if not submitted_date:
                    submitted_date = day
                    if latest_archived and parse_iso_date(day) <= latest_archived:
                        return result()
                canonical = paper["canonical_id"]
                if canonical in observed:
                    continue
                observed.add(canonical)
                if day == submitted_date and paper["abs_url"] not in existing_links:
                    selected[canonical] = paper
            if stop_after_page:
                break
            start += len(page.entries)
            if start >= page.total_results or len(page.entries) < page_size:
                break
        return result()

    def _request_web_bytes(self, request: urllib.request.Request, label: str) -> bytes:
        interval = max(3.0, float(self.config.get("request_interval_seconds", 3.0)))
        retries = int(self.config.get("max_retries", 3))
        timeout = float(self.config.get("timeout_seconds", 45))
        for attempt in range(retries + 1):
            elapsed = time.monotonic() - self.last_request_at
            if self.last_request_at and elapsed < interval:
                self.sleeper(interval - elapsed)
            try:
                self.last_request_at = time.monotonic()
                return self.opener(request, timeout)
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                    raise SkillError(f"arXiv {label} HTTP 错误: {exc.code}") from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleeper(max(interval, float(retry_after or 0)))
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
                if attempt >= retries:
                    raise SkillError(f"arXiv {label}请求失败: {exc}") from exc
                self.sleeper(interval)
        raise SkillError(f"arXiv {label}请求重试耗尽")

    def _request_web_search(self, start: int) -> WebSearchPage:
        query, search_type = build_web_query(self.config)
        params = urllib.parse.urlencode({
            "query": query,
            "searchtype": search_type,
            "abstracts": "show",
            "order": "-submitted_date",
            "size": min(200, int(self.config.get("page_size", 200))),
            "start": start,
        })
        request = urllib.request.Request(
            self.config.get("web_search_url", "https://arxiv.org/search/") + "?" + params,
            headers={"User-Agent": self.config.get("user_agent", "arxiv-lark-daily/1.0")},
        )
        return parse_web_search(self._request_web_bytes(request, "搜索网页"))

    def _request_abs_page(self, paper: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://arxiv.org/abs/{paper['canonical_id']}",
            headers={"User-Agent": self.config.get("user_agent", "arxiv-lark-daily/1.0")},
        )
        return parse_abs_page(self._request_web_bytes(request, "摘要网页"), paper)

    def _fetch_latest_day_web(self, existing_links: set[str], latest_date: str = "") -> dict[str, Any]:
        query = build_search_query(self.config)
        latest_archived = parse_iso_date(latest_date) if latest_date else None
        page_size = min(200, int(self.config.get("page_size", 200)))
        cap = int(self.config.get("max_accessible_results", 30000))
        start = 0
        submitted_date = ""
        selected: dict[str, dict[str, Any]] = {}
        observed: set[str] = set()
        total_results: int | None = None

        def result(papers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            items = papers or []
            return {
                "status": "ok" if items else "no_new_papers",
                "date_semantics": "submitted_date_from_atom_updated_utc",
                "submitted_date": submitted_date,
                "filter_summary": query,
                "query": query,
                "total_results": total_results or 0,
                "papers": items,
                "stats": {"discovered_count": len(items), "written_count": 0, "failure_count": 0},
            }

        while True:
            if start >= cap:
                raise SkillError("网页备用通道需要访问超过 30,000 条结果，请缩小筛选条件")
            page = self._request_web_search(start)
            if total_results is None:
                total_results = page.total_results
            elif page.total_results != total_results:
                raise SkillError(f"arXiv 搜索网页结果总数跨页不一致: 首页 {total_results}，当前 {page.total_results}")
            if not page.entries:
                if start < (total_results or 0):
                    raise SkillError(f"arXiv 搜索网页在 start={start} 没有可解析结果")
                break
            stop_after_page = False
            for paper in page.entries:
                if not paper_matches_web_filters(paper, self.config):
                    continue
                day = paper["submitted_date"]
                if submitted_date and day < submitted_date:
                    stop_after_page = True
                    break
                if not submitted_date:
                    submitted_date = day
                    if latest_archived and parse_iso_date(day) <= latest_archived:
                        return result()
                canonical = paper["canonical_id"]
                if canonical in observed:
                    continue
                observed.add(canonical)
                abs_url = f"https://arxiv.org/abs/{canonical}"
                if day == submitted_date and abs_url not in existing_links:
                    selected[canonical] = paper
            if stop_after_page:
                break
            start += len(page.entries)
            if start >= (total_results or 0) or len(page.entries) < page_size:
                break
        papers = [self._request_abs_page(paper) for paper in selected.values()]
        papers.sort(key=lambda item: (item["updated"], item["canonical_id"]), reverse=True)
        return result(papers)

    def fetch_latest_day(self, existing_links: set[str], latest_date: str = "") -> dict[str, Any]:
        try:
            return self._fetch_latest_day_atom(existing_links, latest_date)
        except ArxivTransportError as exc:
            print(f"Atom API 不可用，改用 arXiv 搜索网页: {exc}", file=sys.stderr)
            return self._fetch_latest_day_web(existing_links, latest_date)


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


def normalize_archive_state(data: Any) -> tuple[set[str], str]:
    if not isinstance(data, dict):
        raise SkillError("归档状态必须是 JSON 对象")
    record_count = data.get("record_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
        raise SkillError("归档状态 record_count 无效")
    latest_date = data.get("latest_date", "")
    if not isinstance(latest_date, str):
        raise SkillError("归档状态 latest_date 无效")
    latest_date = latest_date.strip()
    if record_count == 0 and latest_date:
        raise SkillError("空表归档状态不应包含 latest_date")
    if record_count > 0 and not latest_date:
        raise SkillError("非空表归档状态缺少 latest_date")
    if latest_date:
        latest_date = parse_iso_date(latest_date).isoformat()
    links = data.get("links", [])
    if not isinstance(links, list):
        raise SkillError("归档状态 links 必须是数组")
    return normalize_existing_links(links), latest_date


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the latest arXiv submitted_date after the archive boundary")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--config", required=True)
    fetch.add_argument("--archive-state", required=True)
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--manifest")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        existing_links, latest_date = normalize_archive_state(load_json(args.archive_state))
        state = ArxivClient(config["arxiv"]).fetch_latest_day(existing_links, latest_date)
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
