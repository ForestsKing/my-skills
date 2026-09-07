from pathlib import Path

from .constants import REQUIRED_SKILL_FILES

_FORBIDDEN_DIRS = {"agents", "assets", "__pycache__"}
_FORBIDDEN_FILES = {"." + "DS_Store"}


def validate_skill_tree(skill_root: str) -> dict:
    """检查 skill 目录结构完整性，返回 {ok, root, errors}。"""
    root = Path(skill_root).expanduser().resolve()
    errors = []
    if not root.exists():
        return {"ok": False, "root": str(root), "errors": ["skill 根目录不存在：" + str(root)]}
    if not root.is_dir():
        return {"ok": False, "root": str(root), "errors": ["skill 根路径不是目录：" + str(root)]}

    for path in root.rglob("*"):
        if any(part in _FORBIDDEN_DIRS for part in path.parts):
            errors.append("正式 skill 不应包含：" + str(path))
        if path.name in _FORBIDDEN_FILES:
            errors.append("正式 skill 不应包含平台垃圾文件：" + str(path))
        if path.suffix.lower() == ".pdf":
            errors.append("正式 skill 不应包含测试 PDF：" + str(path))
    for rel in REQUIRED_SKILL_FILES:
        if not (root / rel).exists():
            errors.append("缺少正式文件：" + rel + "（检查根目录：" + str(root) + "）")
    return {"ok": not errors, "root": str(root), "errors": errors}
