import difflib
import json
import re
import urllib.parse
import urllib.request


LOWER = {"a", "an", "the", "and", "but", "or", "for", "nor", "as", "at", "by", "in", "of", "on", "per", "to", "via", "vs", "with"}
ACRONYMS = {"AI", "LLM", "LLMs", "DNA", "RNA", "TSR", "TSRM", "TSRMs", "MSA", "PDB", "RL", "SFT", "ICLR", "GPU", "AlphaFold"}


def title_case(title):
    def norm(word, edge):
        core = word.strip(".,:;!?()[]{}")
        if re.search(r"\d|[-_/]|[α-ωΑ-Ω]", word):
            return word
        if core in ACRONYMS:
            return word
        if re.search(r"[A-Z].*[A-Z]", core) and not core.isupper():
            return word
        lower = word.lower()
        return lower if lower in LOWER and not edge else lower[:1].upper() + lower[1:]
    tokens = re.split(r"(\s+)", title.strip())
    word_indices = [i for i, tok in enumerate(tokens) if tok.strip()]
    if not word_indices:
        return title.strip()
    first, last = word_indices[0], word_indices[-1]
    return "".join(tok if not tok.strip() else norm(tok, i in {first, last}) for i, tok in enumerate(tokens))


def sanitize_title(title, max_len=120):
    value = re.sub(r"[\\/:*?\"<>|#%{}~&]", " ", title)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:max_len].rstrip() or "未命名论文"


def title_similarity(left, right):
    def norm(value):
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return round(difflib.SequenceMatcher(None, norm(left), norm(right)).ratio(), 3)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "paper-lark-reader/0.2"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def crossref_lookup(title="", doi=""):
    candidates = []
    errors = []
    if doi:
        try:
            item = get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi)).get("message", {})
            candidates.append({
                "source": "Crossref",
                "title": (item.get("title") or [""])[0],
                "venue": (item.get("container-title") or [""])[0],
                "year": (((item.get("published-print") or item.get("published-online") or item.get("created") or {}).get("date-parts") or [[None]])[0][0]),
                "doi": item.get("DOI", doi),
                "url": item.get("URL", ""),
                "title_similarity": 1.0,
            })
        except Exception as exc:
            errors.append("Crossref DOI 查询失败：%s" % exc)
    if title:
        try:
            url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.title": title, "rows": "5"})
            data = get_json(url)
            for item in data.get("message", {}).get("items", []):
                candidate_title = (item.get("title") or [""])[0]
                candidates.append({
                    "source": "Crossref",
                    "title": candidate_title,
                    "venue": (item.get("container-title") or [""])[0],
                    "year": (((item.get("published-print") or item.get("published-online") or item.get("created") or {}).get("date-parts") or [[None]])[0][0]),
                    "doi": item.get("DOI", ""),
                    "url": item.get("URL", ""),
                    "title_similarity": title_similarity(title, candidate_title),
                })
        except Exception as exc:
            errors.append("Crossref 标题查询失败：%s" % exc)
    candidates = sorted(candidates, key=lambda x: x.get("title_similarity", 0), reverse=True)
    selected = candidates[0] if candidates and candidates[0].get("title_similarity", 0) >= 0.78 else {}
    confidence = "high" if selected.get("title_similarity", 0) >= 0.92 and selected.get("venue") else ("medium" if selected.get("venue") else "low")
    reason = "" if selected.get("venue") else "missing_venue"
    return {
        "candidates": candidates,
        "selected": selected,
        "confidence": confidence,
        "needs_user_confirmation": bool(reason),
        "confirmation_reason": reason,
        "errors": errors,
    }


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def publication_conflict(selected, hints):
    hint_venue = hints.get("venue") or hints.get("preprint_source") or ((hints.get("venue_mentions") or [""])[0])
    hint_year = (hints.get("year_candidates") or [""])[0]
    selected_venue = selected.get("venue") or ""
    selected_year = str(selected.get("year") or "")
    venue_conflict = bool(hint_venue and selected_venue and _norm(hint_venue) not in _norm(selected_venue) and _norm(selected_venue) not in _norm(hint_venue))
    year_conflict = bool(hint_year and selected_year and hint_year != selected_year)
    return venue_conflict or year_conflict


def apply_publication_fallback(publication, metadata):
    """Crossref 不可用时，使用 PDF 内部出版线索作为候选。"""
    publication = publication or {}
    hints = (metadata or {}).get("publication_hints", {})
    selected = publication.get("selected") or {}
    if selected.get("venue"):
        result = dict(publication)
        if publication_conflict(selected, hints):
            result["needs_user_confirmation"] = True
            result["confirmation_reason"] = "source_conflict"
        else:
            result["needs_user_confirmation"] = False
            result["confirmation_reason"] = ""
        return result

    venue = hints.get("venue") or hints.get("preprint_source") or ((hints.get("venue_mentions") or [""])[0])
    year = (hints.get("year_candidates") or [""])[0]
    doi = hints.get("doi") or ""
    if not (venue and year):
        result = dict(publication)
        result["needs_user_confirmation"] = True
        result["confirmation_reason"] = "missing_venue"
        return result

    fallback = {
        "source": "PDF",
        "title": (metadata.get("title") or {}).get("value", ""),
        "venue": venue,
        "year": year,
        "doi": doi,
        "url": ("https://doi.org/" + doi) if doi else "",
        "title_similarity": 1.0 if (metadata.get("title") or {}).get("value") else 0,
        "evidence": "PDF 首页或正文线索",
    }
    candidates = list(publication.get("candidates") or [])
    candidates.append(fallback)
    return {
        "candidates": candidates,
        "selected": fallback,
        "confidence": "medium",
        "needs_user_confirmation": True,
        "confirmation_reason": "pdf_evidence_only",
        "errors": publication.get("errors") or [],
    }


def keyword_tags(text, existing=None):
    pairs = [
        ("protein|biomolecular", "蛋白质"),
        ("structure predict|protein fold|folding", "结构预测"),
        ("diffusion", "扩散模型"),
        ("nucleic acid|dna|rna", "核酸"),
        ("molecular|ligand|docking", "分子结合"),
        ("time series", "时序"),
        ("language model|llm", "大模型"),
        ("reason", "推理"),
        ("generat", "生成"),
        ("foundation model", "基础模型"),
        ("benchmark|dataset|data", "数据"),
    ]
    existing = existing or []
    lower = text.lower()
    tags = []
    for pattern, tag in pairs:
        if re.search(pattern, lower) and tag not in tags:
            tags.append(tag)
    if existing:
        tags = [t for t in tags if t in existing] + [t for t in tags if t not in existing]
    return tags[:4]


def infer_options(metadata, publication=None, existing_tags=None, existing_publications=None, existing_years=None):
    publication = publication or {}
    hints = metadata.get("publication_hints", {})
    selected = publication.get("selected", {})
    text = " ".join([metadata.get("title", {}).get("value", ""), metadata.get("abstract", {}).get("value", "")])
    tags = keyword_tags(text, existing_tags or [])
    venue = selected.get("venue") or hints.get("venue") or hints.get("preprint_source") or ((hints.get("venue_mentions") or [""])[0])
    year = selected.get("year") or ((hints.get("year_candidates") or [""])[0])
    existing_publications = existing_publications or []
    existing_years = existing_years or []
    return {
        "tags": tags,
        "new_tag_options": [t for t in tags if existing_tags and t not in existing_tags],
        "publication": venue or "",
        "publication_reuses_existing": bool(venue and venue in existing_publications),
        "new_publication_option": venue if venue and existing_publications and venue not in existing_publications else "",
        "year": str(year) if year else "",
        "year_reuses_existing": bool(year and str(year) in existing_years),
        "new_year_option": str(year) if year and existing_years and str(year) not in existing_years else "",
        "score": 3,
    }
