# 生成或更新研究画像

## 触发条件

用户明确要求生成或更新研究画像、研究概述或研究方向总结时使用。

画像生成或更新是独立流程；读论文、讨论或上传时不要自动触发。

执行前读取：

- `references/lark-workflows.md`
- `references/command-pitfalls.md`

## 硬性规则

画像只能来自：

- 用户提供的研究领域关键词。
- 现有 `研究概述` 中已沉淀的研究关键词和画像级概括。
- 已归档 Base 论文索引字段：`Title`、`Abstract`、`标签`、`年份`、`出版`。

不得读取本地 `*.paper-note.md`、PDF 抽取文本、`*.context.json`、`*.text.json` 或任何单篇全文笔记来扩写画像。

## 前置检查

```bash
python3 scripts/paper_lark_cli.py check
```

定位 skill 根目录：包含 `SKILL.md` 的 `paper-lark-reader/` 目录。读取 `<SKILL_ROOT>/config/defaults.json`，不要读取当前项目目录下的同名文件。若 `space_id`、`app_token` 或 `table_id` 缺失，停止并提示用户先执行建库流程。

## 步骤

### 1. 收集用户关键词

提示用户提供研究领域关键词。若用户已在请求中给出关键词，直接使用。

### 2. 获取已有论文索引

```bash
lark-cli base +record-list \
  --base-token <app_token> \
  --table-id <table_id> \
  --field-id Title \
  --field-id Abstract \
  --field-id 标签 \
  --field-id 年份 \
  --field-id 出版 \
  --limit 200
```

若记录不足，只基于用户关键词和现有 Base 字段生成初始画像，并注明数据不足。

如已有 `研究概述` 文档，可只读获取其正文作为画像延续上下文；不要把其中无法被用户关键词或 Base 索引支持的单篇论文细节继续放大。

### 3. 生成画像内容

使用 `templates/research-profile.md`，只生成以下内容：

- 研究领域关键词。
- 数据来源。
- 关注问题。
- 常见数据与任务。
- 方法偏好。

记录数量不足时，对应章节写 `待补充（已读论文不足）`。

预览确认后，将画像 Markdown 保存为当前工作目录下的 `研究概述.md`。不要写到 `/tmp` 或其他目录。

### 4. 预览并确认

在对话中展示画像预览。覆盖已有 `研究概述` 前必须获得用户确认。

### 5. 写入飞书

新建 `研究概述` 前，必须展示画像预览并获得用户确认。覆盖已有 `研究概述` 前，还必须说明将覆盖原文档正文并同步标题。

执行 `docs +update` 时必须位于 `研究概述.md` 所在目录；`--content @研究概述.md` 使用当前工作目录内的相对路径，不要使用绝对路径。

列出知识库根节点：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","page_size":50}'
```

若找到标题为 `研究概述` 且 `obj_type` 为 `docx` 的节点，确认覆盖影响后写入：

```bash
lark-cli docs +update \
  --api-version v2 \
  --doc <doc_token> \
  --command overwrite \
  --doc-format markdown \
  --content @研究概述.md

lark-cli drive files patch \
  --params '{"file_token":"<doc_token>","type":"docx"}' \
  --data '{"new_title":"研究概述"}'
```

若未找到，创建节点：

```bash
lark-cli wiki +node-create \
  --space-id <space_id> \
  --obj-type docx \
  --title "研究概述"
```

记录 `obj_token` 为 `doc_token`，`node_token` 为 `node_token`，再写入正文并修正标题：

```bash
lark-cli docs +update \
  --api-version v2 \
  --doc <doc_token> \
  --command overwrite \
  --doc-format markdown \
  --content @研究概述.md

lark-cli drive files patch \
  --params '{"file_token":"<doc_token>","type":"docx"}' \
  --data '{"new_title":"研究概述"}'
```

回读验证标题：

```bash
lark-cli wiki spaces get_node --params '{"token":"<node_token>"}'
```

## 输出

返回：

- `node_token`
- `obj_token`
- Wiki 链接优先使用命令返回的 URL；若返回值缺失，fallback 为 `https://www.feishu.cn/wiki/<node_token>`

不要尝试通过 CLI 反查不存在的 URL 命令。

## 验收

- 画像只使用允许来源。
- 覆盖已有 `研究概述` 前已确认。
- 文档标题回读为 `研究概述`。

## 反例

- 不要在用户未提供关键词时编造研究领域。
- 不要把单篇论文标签当作长期画像。
- 不要读取本地论文笔记、PDF 正文或抽取中间文件来扩写画像。
- 不要生成无法从摘要和标签推断的章节。
