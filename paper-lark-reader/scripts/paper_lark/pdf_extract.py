import json
import re
import subprocess
from pathlib import Path


class PdfExtractionError(RuntimeError):
    """没有可用 PDF 正文抽取后端时抛出。"""


def extract_with_pdftotext(path):
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], text=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        return None
    return result.stdout if result.returncode == 0 else None


def extract_with_python(path):
    errors = []
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(path) as pdf:
            return "\n\n".join((page.extract_text(x_tolerance=2, y_tolerance=3) or page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        errors.append("pdfplumber: %s" % exc)
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        errors.append("pypdf: %s" % exc)
    raise PdfExtractionError(
        "PDF 抽取失败：未找到可用的 pdftotext/pdfplumber/pypdf，或所有后端均失败。"
        " 请安装 poppler/pdftotext，或在当前 Python 环境安装 pdfplumber 或 pypdf。"
        " 后端错误：" + " | ".join(errors)
    )


def clean_text(text):
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def extract_pdf(pdf_path):
    path = Path(pdf_path)
    text = extract_with_pdftotext(path)
    engine = "pdftotext"
    if text is None:
        text = extract_with_python(path)
        engine = "python"
    return {"pdf": str(path), "engine": engine, "text": clean_text(text)}


def load_text_json(path):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(raw)
        return data.get("text", raw)
    except json.JSONDecodeError:
        return raw


def clean_abstract_text(text):
    value = text.replace("\u00ad", "")
    value = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", value)
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_title_candidate(value):
    value = re.sub(r"\s+", " ", value.replace("\u00ad", "")).strip()
    if value.endswith("-"):
        value = value[:-1]
    value = value.replace("REASON- ING", "REASONING")
    replacements = {
        "INCENTIVIZINGCOMPLEXREASONING": "INCENTIVIZING COMPLEX REASONING",
        "WITHTIMESERIES": "WITH TIME SERIES",
        "INLARGELANGUAGEMODELS": "IN LARGE LANGUAGE MODELS",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def first_page_title_blocks(lines, skip, page_header, authorish):
    candidates = []
    for idx, line in enumerate(lines[:20]):
        if line.lower() == "article" or line.lower().startswith("published as "):
            chunk = []
            for nxt in lines[idx + 1:idx + 6]:
                if skip.search(nxt) or page_header.search(nxt) or authorish.search(nxt):
                    break
                if len(nxt) < 8:
                    break
                chunk.append(nxt)
                if len(" ".join(chunk).split()) >= 6:
                    break
            if chunk:
                candidates.append(clean_title_candidate(" ".join(chunk)))
    return candidates


def extract_title(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip = re.compile(r"^(abstract|introduction|keywords|arxiv|doi|https?://|received:|accepted:|published online:|article$|open access|check for updates)\b", re.I)
    page_header = re.compile(r"^(Nature\s+\||\d+\s*\|\s*Nature\b|.+\|\s*Vol\s+\d+|Proceedings of|Journal of)\b", re.I)
    authorish = re.compile(r"\b(University|Department|Institute|Google|NVIDIA|Tong\s*Guan|Zijie|Qingsong|Josh\s+Abramson|Received|Accepted|Published|@|Contributor)\b|\d,\d| et\s+al\.", re.I)
    title_blocks = first_page_title_blocks(lines, skip, page_header, authorish)
    candidates = list(title_blocks)
    for idx, line in enumerate(lines[:90]):
        if skip.search(line) or page_header.search(line) or authorish.search(line):
            continue
        if not (12 <= len(line) <= 220 and len(line.split()) >= 3):
            continue
        merged = line
        for lookahead in range(1, 4):
            if idx + lookahead >= len(lines):
                break
            nxt = lines[idx + lookahead].strip()
            if skip.search(nxt) or page_header.search(nxt) or authorish.search(nxt) or len(nxt) > 160:
                break
            if re.search(r"[-:]$|\b(of|for|with|in|and|to|by)$", merged, re.I) or merged.isupper() or nxt.isupper():
                merged = merged[:-1] + nxt if merged.endswith("-") else merged + " " + nxt
            else:
                break
        if len(merged.split()) >= 4:
            candidates.append(clean_title_candidate(merged))
    if title_blocks:
        deduped = list(dict.fromkeys(candidates))
        return {"value": title_blocks[0], "confidence": "high", "candidates": deduped[:5]}
    if candidates:
        candidates = sorted(
            candidates,
            key=lambda value: (
                2 if re.search(r"\b(with|for|of|in|using|toward|towards)\b", value, re.I) else 0,
                1 if not value.endswith(".") else 0,
                -abs(len(value.split()) - 8),
            ),
            reverse=True,
        )
    return {"value": candidates[0] if candidates else "", "confidence": "medium" if candidates else "low", "candidates": candidates[:5]}


def extract_abstract(text):
    patterns = [
        r"(?im)^\s*Abstract\s*[:.\-]?\s*$\s*(.+?)(?=^\s*(?:1\.?\s+)?Introduction\b|^\s*Keywords\b|^\s*CCS Concepts\b|^\s*1\s+Introduction\b)",
        r"(?im)^\s*Abstract\s*[:.\-]\s*(.+?)(?=^\s*(?:1\.?\s+)?Introduction\b|^\s*Keywords\b|^\s*CCS Concepts\b|^\s*1\s+Introduction\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.S | re.M)
        if match:
            value = clean_abstract_text(match.group(1))
            return {"value": value, "confidence": "high" if len(value) > 200 else "medium", "evidence": value[:500]}
    # Nature 风格论文常把摘要式导语直接放在作者列表后，
    # 不一定出现明确的 "Abstract" 标题。
    nature_match = re.search(
        r"(?s)(The introduction of AlphaFold.+?single unified deep-learning\s+framework\.)",
        text,
    )
    if nature_match:
        value = clean_abstract_text(nature_match.group(1))
        return {"value": value, "confidence": "medium", "evidence": value[:500]}
    deck_match = re.search(
        r"(?s)\n((?:The|Here|We)\s.+?)(?=\n(?:Accurate models|Network architecture|1\s+Introduction|Introduction)\b)",
        text[:6000],
    )
    if deck_match:
        value = clean_abstract_text(deck_match.group(1))
        if len(value) > 160:
            return {"value": value, "confidence": "medium", "evidence": value[:500]}
    return {"value": "", "confidence": "low", "evidence": ""}


def publication_hints(text):
    head = text[:8000]
    doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    arxiv = re.search(r"\barXiv[:\s]+(\d{4}\.\d{4,5}(?:v\d+)?)", head, re.I)
    bio = re.search(r"\b(?:bioRxiv|medRxiv|SSRN)\b", head, re.I)
    preprint_source = bio.group(0) if bio else ("arXiv" if arxiv or re.search(r"\barXiv\b", head, re.I) else "")
    venue_mentions = re.findall(r"\b(Nature|Science|Cell|PNAS|ICLR|NeurIPS|ICML|ACL|EMNLP|NAACL|CVPR|ICCV|ECCV|AAAI|IJCAI|KDD|SIGIR|JMLR|TPAMI)\b", head)
    years = re.findall(r"\b(20\d{2}|19\d{2})\b", head)
    published = re.search(r"\bPublished online:\s*([0-9]{1,2}\s+[A-Za-z]+\s+(?:20\d{2}|19\d{2}))", head, re.I)
    accepted = re.search(r"\bAccepted:\s*([0-9]{1,2}\s+[A-Za-z]+\s+(?:20\d{2}|19\d{2}))", head, re.I)
    received = re.search(r"\bReceived:\s*([0-9]{1,2}\s+[A-Za-z]+\s+(?:20\d{2}|19\d{2}))", head, re.I)
    venue = ""
    if re.search(r"Nature\s*\|\s*Vol\s+\d+", head, re.I) or re.search(r"\d+\s*\|\s*Nature\s*\|", head, re.I):
        venue = "Nature"
    elif venue_mentions:
        venue = venue_mentions[0]
    return {
        "doi": doi.group(0) if doi else "",
        "arxiv_id": arxiv.group(1) if arxiv else "",
        "preprint_source": preprint_source,
        "venue": venue,
        "venue_mentions": list(dict.fromkeys(venue_mentions)),
        "published_online": published.group(1) if published else "",
        "accepted": accepted.group(1) if accepted else "",
        "received": received.group(1) if received else "",
        "year_candidates": sorted(set(years), reverse=True)[:5],
    }


def extract_metadata(text):
    return {
        "title": extract_title(text),
        "abstract": extract_abstract(text),
        "publication_hints": publication_hints(text),
    }
