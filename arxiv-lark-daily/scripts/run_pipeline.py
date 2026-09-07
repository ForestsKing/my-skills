#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from common import SkillError, load_json, save_json

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:%|‰)?")
NEGATION_EN = re.compile(r"\b(?:no|not|without|neither|cannot|can't|fail(?:s|ed)?|limited)\b", re.I)
MODAL_EN = re.compile(r"\b(?:may|might|could|suggest(?:s|ed)?|potentially)\b", re.I)
NEGATION_ZH = re.compile(r"不|无|未|不能|无法|没有|有限")
MODAL_ZH = re.compile(r"可能|或许|可以|可|提示|表明|潜在")
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_PATTERN = re.compile(r"^[A-Za-z0-9_+\-/. ]+$")
SENTENCE_MARK_PATTERN = re.compile(r"[。！？!?；;，,]")


def validate_tags(tags: Any, paper: dict[str, Any]) -> list[str]:
    canonical_id = paper.get("canonical_id", "未知论文")
    if not isinstance(tags, list):
        raise SkillError(f"标签必须是数组: {canonical_id}")
    cleaned = []
    seen = set()
    for value in tags:
        if not isinstance(value, str):
            raise SkillError(f"标签必须是字符串: {canonical_id}")
        tag = " ".join(value.strip().split())
        if not tag:
            raise SkillError(f"标签不能为空: {canonical_id}")
        if tag in seen:
            raise SkillError(f"标签重复: {canonical_id}: {tag}")
        if not CHINESE_PATTERN.search(tag):
            raise SkillError(f"标签必须包含中文字符: {canonical_id}: {tag}")
        if ASCII_WORD_PATTERN.fullmatch(tag):
            raise SkillError(f"标签不能是纯英文或纯 ASCII: {canonical_id}: {tag}")
        if SENTENCE_MARK_PATTERN.search(tag):
            raise SkillError(f"标签应是简短主题词，不能是句子: {canonical_id}: {tag}")
        if len(tag) > 6:
            raise SkillError(f"标签最长不超过 6 个字: {canonical_id}: {tag}")
        title = str(paper.get("title", "")).strip()
        if title and tag.lower() == title.lower():
            raise SkillError(f"标签不能直接使用论文标题: {canonical_id}")
        seen.add(tag)
        cleaned.append(tag)
    if not 2 <= len(cleaned) <= 4:
        raise SkillError(f"每篇论文必须有 2–4 个标签: {canonical_id}")
    return cleaned


def apply_enrichment(state: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    values = enrichment.get("papers", {})
    for paper in state.get("papers", []):
        item = values.get(paper["canonical_id"])
        if not item:
            raise SkillError(f"缺少论文 enrichment: {paper['canonical_id']}")
        translation = str(item.get("abstract_zh", "")).strip()
        if not translation:
            raise SkillError(f"缺少中文摘要: {paper['canonical_id']}")
        paper["abstract_zh"] = translation
        paper["tags"] = validate_tags(item.get("tags"), paper)
    return state


def fidelity_warnings(paper: dict[str, Any]) -> list[str]:
    source = paper.get("abstract_en", "")
    translated = paper.get("abstract_zh", "")
    warnings = []
    source_numbers = NUMBER_PATTERN.findall(source)
    translated_numbers = NUMBER_PATTERN.findall(translated)
    if sorted(source_numbers) != sorted(translated_numbers):
        warnings.append("数字、百分比或带数字单位可能未完整保留")
    if NEGATION_EN.search(source) and not NEGATION_ZH.search(translated):
        warnings.append("原文含否定或限制，译文未检测到对应表达")
    if MODAL_EN.search(source) and not MODAL_ZH.search(translated):
        warnings.append("原文含不确定性或模态语气，译文可能被强化")
    forbidden = [word for word in ("革命性", "遥遥领先", "彻底解决", "必然", "首次证明") if word in translated]
    if forbidden:
        warnings.append("译文含需核对的强化词: " + ", ".join(forbidden))
    if len(translated) < max(20, len(source) * 0.18):
        warnings.append("译文相对原摘要过短，可能发生概括或截断")
    return warnings


def validate_state(state: dict[str, Any]) -> dict[str, list[str]]:
    result = {}
    for paper in state.get("papers", []):
        issues = []
        if not paper.get("abstract_zh"):
            issues.append("缺少中文摘要")
        try:
            validate_tags(paper.get("tags"), paper)
        except SkillError as exc:
            issues.append(str(exc))
        issues.extend(fidelity_warnings(paper))
        if issues:
            result[paper["canonical_id"]] = issues
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply and validate semantic enrichment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply-enrichment")
    apply_parser.add_argument("--papers", required=True)
    apply_parser.add_argument("--enrichment", required=True)
    validate_parser = subparsers.add_parser("validate-enrichment")
    validate_parser.add_argument("--papers", required=True)
    args = parser.parse_args()
    try:
        state = load_json(args.papers)
        if args.command == "apply-enrichment":
            state = apply_enrichment(state, load_json(args.enrichment))
            save_json(args.papers, state)
            print(json.dumps({"ok": True, "paper_count": len(state.get("papers", []))}, ensure_ascii=False))
            return 0
        warnings = validate_state(state)
        print(json.dumps({"ok": not warnings, "warnings": warnings}, ensure_ascii=False, indent=2))
        return 1 if warnings else 0
    except SkillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
