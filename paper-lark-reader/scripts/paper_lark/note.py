import re
from pathlib import Path

from .constants import CORE_METADATA_FIELDS, NO_PLACEHOLDERS, NOTE_METADATA_FIELDS, NOTE_RUNTIME_FIELDS
from .metadata import title_case


def parse_note_metadata(note_path):
    text = Path(note_path).read_text(encoding="utf-8")
    match = re.search(r"^##\s*元数据\s*\n(?P<body>.*?)(?=^##\s+|\Z)", text, re.S | re.M)
    if not match:
        raise ValueError("笔记中缺少“## 元数据”章节。")
    values = {}
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] != "字段":
            values[cells[0]] = " | ".join(cells[1:]).strip()
    return values


def validate_note_metadata(values):
    errors = []
    missing = [field for field in NOTE_METADATA_FIELDS if not values.get(field)]
    if missing:
        errors.append("缺少字段或内容为空：" + ", ".join(missing))
    bad = [field for field in CORE_METADATA_FIELDS if values.get(field, "").strip() in NO_PLACEHOLDERS]
    if bad:
        errors.append("核心元数据不能使用占位值：" + ", ".join(bad))
    extra = [field for field in NOTE_RUNTIME_FIELDS if field in values]
    if extra:
        errors.append("笔记元数据表不应包含运行时字段：" + ", ".join(extra))
    if values.get("Title"):
        values["Title"] = title_case(values["Title"])
    return {"ok": not errors, "errors": errors, "values": values}


def validate_note_file(note_path):
    values = parse_note_metadata(note_path)
    return validate_note_metadata(values)
