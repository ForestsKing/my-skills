#!/usr/bin/env python3
"""
paper-lark-reader 本地辅助命令。

飞书读写操作（建库、扫描、上传、画像写入）已迁移到 commands/*.md，
由 Agent 直接调用 lark-* skill 执行，不再通过本脚本。
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from paper_lark.env import check_environment
from paper_lark.metadata import apply_publication_fallback, crossref_lookup, infer_options, sanitize_title, title_case
from paper_lark.note import validate_note_file
from paper_lark.pdf_extract import PdfExtractionError, extract_metadata, extract_pdf, load_text_json
from paper_lark.skill_check import validate_skill_tree


def emit(data, output=None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)


def error(message, hint="", **extra):
    payload = {"ok": False, "error": message}
    if hint:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def intermediate_paths(pdf, output=None):
    if output:
        out = Path(output)
        name = out.name
        if name.endswith(".context.json"):
            base = name[:-len(".context.json")]
        else:
            base = out.stem
        root = out.with_name(base)
    else:
        root = Path(pdf).with_suffix("")
    return {
        "text": root.with_name(root.name + ".text.json"),
        "metadata": root.with_name(root.name + ".metadata.json"),
    }


# ── 环境 ───────────────────────────────────────────────────────────────────────

def cmd_check(args):
    emit(check_environment(), args.output)


# ── 论文数据处理 ───────────────────────────────────────────────────────────────

def cmd_paper_prep(args):
    """串行执行 extract → metadata → lookup → infer，输出统一上下文 JSON。"""
    try:
        text_data = extract_pdf(args.pdf)
    except PdfExtractionError as exc:
        emit({"ok": False, "error": str(exc), "pdf": args.pdf}, args.output)
        return
    text = text_data["text"]
    metadata = extract_metadata(text)
    title_val = metadata.get("title", {}).get("value", "")
    publication = apply_publication_fallback(crossref_lookup(title=title_val, doi=args.doi or metadata.get("publication_hints", {}).get("doi", "")), metadata)
    options = infer_options(metadata, publication=publication)
    context = {
        "ok": True,
        "pdf": args.pdf,
        "engine": text_data["engine"],
        "text_stats": {
            "chars": len(text),
            "engine": text_data["engine"],
            "title_confidence": metadata.get("title", {}).get("confidence", ""),
            "abstract_confidence": metadata.get("abstract", {}).get("confidence", ""),
        },
        "metadata": metadata,
        "publication": publication,
        "options": options,
    }
    if args.write_intermediates:
        paths = intermediate_paths(args.pdf, args.output)
        emit(text_data, paths["text"])
        emit(metadata, paths["metadata"])
        context["intermediates"] = {key: str(path) for key, path in paths.items()}
    emit(context, args.output)


def cmd_extract(args):
    try:
        emit(extract_pdf(args.pdf), args.output)
    except PdfExtractionError as exc:
        emit({"ok": False, "error": str(exc), "pdf": args.pdf}, args.output)


def cmd_metadata(args):
    path = Path(args.text_json)
    if not path.exists():
        emit(error(
            f"正文 JSON 文件不存在：{args.text_json}",
            "请先运行 `python3 scripts/paper_lark_cli.py extract <paper.pdf> --output <paper.text.json>`，或使用 `paper-prep --write-intermediates` 生成中间文件。",
            text_json=args.text_json,
        ), args.output)
        return
    try:
        emit(extract_metadata(load_text_json(args.text_json)), args.output)
    except Exception as exc:
        emit(error(
            f"元数据抽取失败：{exc}",
            "请确认输入是 `extract` 生成的 JSON，或包含可读取的 PDF 正文文本。",
            text_json=args.text_json,
        ), args.output)


def cmd_lookup(args):
    emit(crossref_lookup(title=args.title, doi=args.doi), args.output)


def cmd_infer(args):
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    publication = json.loads(Path(args.publication).read_text(encoding="utf-8")) if args.publication else {}
    emit(infer_options(metadata, publication=publication), args.output)


def cmd_title(args):
    print(title_case(args.title) if args.title_case else sanitize_title(args.title))


# ── 笔记校验 ───────────────────────────────────────────────────────────────────

def cmd_note_check(args):
    emit(validate_note_file(args.note), args.output)


# ── Skill 结构校验 ─────────────────────────────────────────────────────────────

def cmd_validate_tree(args):
    emit(validate_skill_tree(args.skill_root), args.output)


# ── CLI 注册 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="paper-lark-reader 本地辅助命令。")
    sub = parser.add_subparsers(required=True)

    # 环境
    p = sub.add_parser("check", help="检查运行环境")
    p.add_argument("--output")
    p.set_defaults(func=cmd_check)

    # 论文数据处理
    p = sub.add_parser("paper-prep", help="PDF 预处理：extract + metadata + lookup + infer 一步完成")
    p.add_argument("--pdf", required=True)
    p.add_argument("--doi", default="", help="已知 DOI（可选，提高出版核验准确率）")
    p.add_argument("--write-intermediates", action="store_true", help="同时写出同名 .text.json 和 .metadata.json")
    p.add_argument("--output")
    p.set_defaults(func=cmd_paper_prep)

    p = sub.add_parser("extract", help="抽取 PDF 正文")
    p.add_argument("pdf")
    p.add_argument("--output")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("metadata", help="从正文 JSON 抽取元数据")
    p.add_argument("text_json")
    p.add_argument("--output")
    p.set_defaults(func=cmd_metadata)

    p = sub.add_parser("lookup", help="Crossref 出版核验")
    p.add_argument("--title", default="")
    p.add_argument("--doi", default="")
    p.add_argument("--output")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("infer", help="推断标签/出版/年份选项")
    p.add_argument("--metadata", required=True)
    p.add_argument("--publication")
    p.add_argument("--output")
    p.set_defaults(func=cmd_infer)

    p = sub.add_parser("title", help="规范化论文标题")
    p.add_argument("title"); p.add_argument("--title-case", action="store_true")
    p.set_defaults(func=cmd_title)

    # 校验
    p = sub.add_parser("note-check", help="校验笔记文件元数据表")
    p.add_argument("note", metavar="NOTE_FILE")
    p.add_argument("--output")
    p.set_defaults(func=cmd_note_check)

    p = sub.add_parser("validate-tree", help="检查 skill 目录结构完整性")
    p.add_argument("skill_root", help="skill 根目录；在 skill 目录内可传 .")
    p.add_argument("--output")
    p.set_defaults(func=cmd_validate_tree)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
