import shutil
import subprocess
import sys
import importlib.util


def _command_version(cmd):
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=10)
    except Exception:
        return None
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if result.returncode == 0 and text else None


def check_environment() -> dict:
    """检查运行时依赖，返回结构化结果。"""
    has_lark_cli = bool(shutil.which("lark-cli"))
    has_pdftotext = bool(shutil.which("pdftotext"))
    has_pdfplumber = importlib.util.find_spec("pdfplumber") is not None
    has_pypdf = importlib.util.find_spec("pypdf") is not None
    pdf_extract_available = has_pdftotext or has_pdfplumber or has_pypdf
    python_ok = sys.version_info >= (3, 9)
    hints = []
    if not python_ok:
        hints.append("Python 版本过低：需要 Python 3.9+。")
    if not has_lark_cli:
        hints.append("未找到 lark-cli：建库和上传前请安装并登录 lark-cli。")
    if not has_pdftotext:
        hints.append("未找到 pdftotext：PDF 抽取会回退到 pdfplumber 或 pypdf。")
    if not pdf_extract_available:
        hints.append("PDF 抽取不可用：请安装 poppler/pdftotext，或在当前 Python 环境安装 pdfplumber 或 pypdf。")
    return {
        "ok": python_ok and pdf_extract_available,
        "checks": {
            "python_version": sys.version.split()[0],
            "python_compatible": python_ok,
            "lark_cli": has_lark_cli,
            "pdftotext": has_pdftotext,
            "pdfplumber": has_pdfplumber,
            "pypdf": has_pypdf,
            "pdf_extract_available": pdf_extract_available,
        },
        "versions": {
            "lark-cli": _command_version(["lark-cli", "--version"]) if has_lark_cli else None,
            "pdftotext": _command_version(["pdftotext", "-v"]) if has_pdftotext else None,
        },
        "hints": hints,
    }
