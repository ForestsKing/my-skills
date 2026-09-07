# 阅读论文

## 触发条件

用户要求阅读、精读、总结 PDF 论文，或生成论文笔记时使用。首次给出 PDF 并要求“帮我阅读下这篇论文”“总结这篇论文”“精读这个 PDF”“分析这篇论文”等，都必须进入本流程。

默认行为是生成本地 Markdown 论文笔记。不得把首次论文阅读请求降级为只在聊天里给摘要；只有用户明确要求“只要聊天总结”“不生成笔记”“离线口头总结”时，才可不生成笔记，并必须说明未使用飞书标签、出版选项和研究画像。

执行前读取：

- `references/note-writing-guide.md`
- `references/publication-policy.md`
- `references/command-pitfalls.md`

## 输入

- 一个本地 PDF 路径。
- 已初始化且可访问的飞书论文知识库；若用户明确要求离线阅读，可生成本地笔记，但必须说明未使用飞书标签、出版选项和研究画像。

## 前置检查

禁止快捷摘要：读取 PDF 后不得直接输出最终阅读总结来替代本流程。必须先完成环境检查和论文库只读上下文获取；若配置、字段选项或 `研究概述` 读取失败，进入离线确认门，获得用户明确确认后才可继续生成本地笔记。

```bash
python3 scripts/paper_lark_cli.py check
```

定位 skill 根目录：包含 `SKILL.md` 的 `paper-lark-reader/` 目录。读取 `<SKILL_ROOT>/config/defaults.json`，不要读取当前项目目录下的同名文件。确认存在 `space_id`、`app_token` 和 `table_id`，并只读验证目标库可访问。

若未能读取配置、字段选项或 `研究概述`，必须暂停并说明失败原因、缺失上下文和影响；只有用户明确确认离线继续，才可生成本地 Markdown 笔记。用户一开始明确要求离线阅读时，可跳过暂停，但输出中仍需说明未使用飞书标签、出版选项和研究画像。

## 步骤

### 1. 只读获取论文库上下文（必需）

只读获取 Base 字段配置，用于取得 `标签` 和 `出版` 现有选项。不需要读取已有论文索引记录或 `年份` 选项：

```bash
lark-cli base +field-list \
  --base-token <app_token> \
  --table-id <table_id>
```

查找 `研究概述`：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","page_size":50}'
```

找到标题为 `研究概述` 且 `obj_type` 为 `docx` 的节点后，只读获取文档内容，用于 `评价与启发`。找不到或读取失败时进入离线确认门；确认继续后，画像相关启发留空并说明。

### 2. PDF 预处理

```bash
python3 scripts/paper_lark_cli.py paper-prep \
  --pdf <paper.pdf> \
  --output <paper.context.json>
```

若后续需要单独使用 `extract` 和 `metadata` 的中间结果，可增加 `--write-intermediates`，同时写出同名 `*.text.json` 和 `*.metadata.json`。若已知 DOI，加 `--doi 10.xxxx/xxxxx` 提高出版核验准确率。若返回 `ok: false`，按错误提示修复依赖，不要把 traceback 当成用户结论。

依赖链 `extract -> metadata -> infer` 必须串行执行，禁止把依赖前一步输出文件的命令放进并行工具调用。

### 3. 判断出版信息

基于 `paper.context.json` 中的 `metadata` 和 `publication` 判断出版、年份和置信度。联网核验只用于出版元数据，不用于扩写论文内容。

若 Crossref 失败但 PDF 内部包含明确 DOI、venue 和 year，可继续生成本地笔记；上传前按 `publication.confirmation_reason` 判断风险。`pdf_evidence_only` 表示只有 PDF 证据但无来源冲突，作为低风险确认项；`source_conflict` 或 `missing_venue` 需要暂停确认。`出版` 优先复用已有选项；无合适选项时按常用简称生成候选。

### 4. 生成笔记

使用 `templates/paper-note.md`。关键规则：

- `Title`：规范为 Title Case；不破坏模型名、缩写、基因/蛋白名和连字符词。
- `Abstract`：保留英文原意，不改写成总结。
- `标题`：`Title` 的忠实中文翻译。
- `摘要`：`Abstract` 的忠实中文翻译。
- `出版`：优先复用已有出版选项；无合适选项时按 `references/publication-policy.md` 的常用简称规则生成候选。
- `标签`：结合论文内容和已有标签建议 2-4 个；优先复用已有标签选项，无合适选项时只在本地笔记中建议新标签，不向用户索要关键词，也不新增飞书选项。
- `评价与启发`：区分作者结论、阅读者推断和基于 `研究概述` 的个性化启发。

### 5. 写入本地笔记

在 PDF 同路径生成或更新 `*.paper-note.md`：

- 首次阅读默认生成新笔记。
- 已存在同题或同路径笔记时，先展示已有笔记路径、将被修改的章节和可能覆盖的内容；只有用户确认后才更新既有笔记。
- 只有用户明确要求保留旧版时，才另存新副本。

写完后校验：

```bash
python3 scripts/paper_lark_cli.py note-check <paper.paper-note.md>
```

聊天输出只作为笔记完成后的简短回报，说明笔记路径、校验结果和最关键结论；不得用聊天输出替代 `*.paper-note.md`。

## 停止条件

- `Title` 或 `Abstract` 低置信度且无法人工确认时，不上传。
- 中文标题或中文摘要缺失时，不上传。
- 出版或年份冲突且未确认时，不上传。

## 验收

- 本地笔记存在且通过 `note-check`。
- 元数据表只包含：`Title、出版、年份、标签、评分、Abstract、标题、摘要`。
- `摘要` 是英文 Abstract 的中文翻译，不是总结。
- 讨论和上传没有被自动触发。
- 若已有笔记被更新，更新前已获得用户确认。

## 反例

- 不要把 AI 总结写进 `摘要` 字段。
- 不要从文件名猜出版和年份后直接写入。
- 不要视觉解析图表；只基于正文、caption 和作者解释。
- 不要在首次给出 PDF 并要求阅读时只给聊天摘要；必须按本流程生成并校验本地笔记，除非用户明确要求不生成笔记。
