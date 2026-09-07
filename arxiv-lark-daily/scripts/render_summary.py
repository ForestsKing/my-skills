#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import load_config, load_json


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def normalize_block(text: str, fallback: str) -> str:
    value = text.strip()
    return value if value else fallback


def intro_sentence(submitted_date: str, paper_count: int, base_url: str) -> str:
    if base_url:
        return f"{submitted_date} 新增 {paper_count} 篇论文，已归档到多维表格：[查看论文归档]({base_url})。"
    return f"{submitted_date} 新增 {paper_count} 篇论文，已完成归档。"


def build_summary(config: dict, state: dict, base_state: dict, daily_highlights: str, recommendations: str, template_text: str) -> str:
    if not state.get("papers"):
        return config["summary"]["no_new_message"] + "\n"
    submitted_date = str(state.get("submitted_date") or state["papers"][0].get("submitted_date") or "").strip()
    paper_count = int(state.get("stats", {}).get("written_count") or sum(1 for paper in state.get("papers", []) if paper.get("record_id")) or len(state.get("papers", [])))
    base_url = str(base_state.get("base_url") or "")
    values = {
        "submitted_date": submitted_date,
        "paper_count": str(paper_count),
        "base_url": base_url,
        "intro_sentence": intro_sentence(submitted_date, paper_count, base_url),
        "daily_highlights": normalize_block(daily_highlights, "- 本批论文已完成归档，请结合论文清单补充今日要点。"),
        "domain_overview": normalize_block(daily_highlights, "- 本批论文已完成归档，请结合论文清单补充今日要点。"),
        "reading_recommendations": normalize_block(recommendations, "| 方法 | 论文 | 推荐理由 |\n| --- | --- | --- |\n| 待补充 | 待补充 | 请结合本批论文补充具体阅读建议。 |"),
    }
    return render_template(template_text, values).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the fixed arXiv daily summary")
    parser.add_argument("--config", required=True)
    parser.add_argument("--papers", required=True)
    parser.add_argument("--base-state", required=True)
    parser.add_argument("--daily-highlights-file")
    parser.add_argument("--domain-overview-file")
    parser.add_argument("--reading-recommendations-file", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    if not args.daily_highlights_file and not args.domain_overview_file:
        parser.error("one of --daily-highlights-file or --domain-overview-file is required")

    config = load_config(args.config)
    state = load_json(args.papers)
    base_state = load_json(args.base_state)
    skill_dir = Path(__file__).resolve().parents[1]
    template_path = skill_dir / config["summary"]["template"]
    highlights_path = Path(args.daily_highlights_file or args.domain_overview_file)
    result = build_summary(
        config,
        state,
        base_state,
        highlights_path.read_text(encoding="utf-8"),
        Path(args.reading_recommendations_file).read_text(encoding="utf-8"),
        template_path.read_text(encoding="utf-8"),
    )
    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
