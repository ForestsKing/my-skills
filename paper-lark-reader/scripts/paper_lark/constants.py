"""paper-lark-reader 本地辅助命令共享常量。"""

BASE_NAME = "论文索引"
TABLE_NAME = "数据表"
DEFAULT_VIEW_NAME = "概览"
NOTE_PARENT_TITLE = "论文笔记"
PROFILE_TITLE = "研究概述"
DEFAULT_STATUS = "待读"
DEFAULT_SCORE = 3
MAIN_PDF_UPLOAD_NAME = "paper.pdf"

NOTE_METADATA_FIELDS = ["Title", "出版", "年份", "标签", "评分", "Abstract", "标题", "摘要"]
CORE_METADATA_FIELDS = ["Title", "Abstract", "标题", "摘要"]
NOTE_RUNTIME_FIELDS = ["状态", "创建", "附件", "笔记"]

BASE_FIELDS = [
    "Title",
    "出版",
    "年份",
    "状态",
    "标签",
    "评分",
    "创建",
    "附件",
    "笔记",
    "Abstract",
    "标题",
    "摘要",
]

NO_PLACEHOLDERS = {"待确认", "待翻译", "待补充", "TBD", "TODO", ""}

REQUIRED_SKILL_FILES = [
    "SKILL.md",
    "README.md",
    "config/defaults.json",
    "commands/kb-init.md",
    "commands/paper-read.md",
    "commands/paper-discuss.md",
    "commands/note-revise.md",
    "commands/profile-update.md",
    "commands/kb-upload.md",
    "templates/paper-note.md",
    "templates/research-profile.md",
    "templates/upload-preview.md",
    "scripts/paper_lark_cli.py",
    "scripts/paper_lark/__init__.py",
    "scripts/paper_lark/constants.py",
    "scripts/paper_lark/env.py",
    "scripts/paper_lark/pdf_extract.py",
    "scripts/paper_lark/metadata.py",
    "scripts/paper_lark/note.py",
    "scripts/paper_lark/skill_check.py",
    "references/command-pitfalls.md",
    "references/lark-workflows.md",
    "references/publication-policy.md",
    "references/note-writing-guide.md",
]
