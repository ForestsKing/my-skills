# 上传笔记到飞书

## 触发条件

用户要求上传、归档、写入论文索引、同步到飞书论文库时使用。

执行前读取：

- `references/lark-workflows.md`
- `references/note-writing-guide.md`
- `references/command-pitfalls.md`

## 硬性规则

- `Title`、`Abstract`、`标题`、`摘要` 只能从 Markdown 笔记 `## 元数据` 表复制。
- 主 PDF 只上传到 Base 附件字段一次，命名为 `paper.pdf`。
- `笔记` 字段显示文字必须是 `笔记`，链接到论文子文档。
- 子文档创建后标题不能是 `Untitled`。

## 前置检查

定位 skill 根目录：包含 `SKILL.md` 的 `paper-lark-reader/` 目录。读取 `<SKILL_ROOT>/config/defaults.json`，不要读取当前项目目录下的同名文件。

确认配置中存在：

- `space_id`
- `app_token`
- `table_id`
- `note_parent_doc_token`
- `note_parent_node_token`

运行：

```bash
python3 scripts/paper_lark_cli.py check
```

若字段缺失、目标库不可访问或权限不足，停止并提示用户先执行建库流程或修复飞书 CLI/权限。

## 步骤

### 1. 校验本地笔记

```bash
python3 scripts/paper_lark_cli.py note-check <NOTE.md>
```

若输出 `ok: false`，修正后再继续。

### 2. 重复检测

在 Base 中搜索同 Title 记录。`+record-search.keyword` 最长 50 字符；长标题截取稳定短关键词，命中后必须人工比对完整 `Title`。

```bash
lark-cli base +record-search \
  --base-token <app_token> \
  --table-id <table_id> \
  --json '{"keyword":"<Title 前 50 字符或稳定短关键词>","search_fields":["Title"]}'
```

同时在 `论文笔记` 父节点下检查是否已有同题子文档：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","parent_node_token":"<note_parent_node_token>","page_size":50}'
```

命中重复时，展示已有记录或子文档；用户确认后走更新分支。只有用户明确要求新增时才创建重复记录。

### 3. 更新已有记录

若用户确认更新已有云端记录，先展示将覆盖或保留的内容：

- 将覆盖的子文档正文和标题。
- 是否更新 Base 字段。
- 是否重新上传或替换附件。
- 是否回写或改变 `笔记` 链接。

确认后执行：

1. 从已有 `笔记` 字段或重复子文档取得 `child_node_token`。
2. 解析真实文档 token：
   ```bash
   lark-cli wiki spaces get_node --params '{"token":"<child_node_token>"}'
   ```
3. 覆盖文档正文并同步标题：
   ```bash
   lark-cli docs +update \
     --api-version v2 \
     --doc <existing_doc_token> \
     --command overwrite \
     --doc-format markdown \
     --content @<NOTE.md>

   lark-cli drive files patch \
     --params '{"file_token":"<existing_doc_token>","type":"docx"}' \
     --data '{"new_title":"<论文 Title>"}'
   ```
4. 回读验证标题：
   ```bash
   lark-cli wiki spaces get_node --params '{"token":"<child_node_token>"}'
   ```
   每次 `docs +update --command overwrite` 后都必须重新执行 `drive files patch` 并回读标题；若后续再次 overwrite，必须再次修正并验证标题。
5. 只有用户明确确认具体字段或附件变更时，才更新 Base 其他字段或重新上传附件。

### 4. 上传前预览

按 `templates/upload-preview.md` 展示：

- 目标知识库、Base、表、视图和父文档。
- 将写入 Base 的字段值。
- 将上传的附件。
- 评分，默认 `3`，可改为 `1-5` 或留空。

上传前确认字段结构：

```bash
lark-cli base +field-list --base-token <app_token> --table-id <table_id>
```

若 `出版`、`年份` 或 `标签` 缺少待写选项，先展示新增理由、当前已有选项和完整更新后的选项列表，获得确认后再用 `+field-update` 在保留已有选项的基础上追加。

多个 `+field-update` 必须串行执行，字段之间等待约 2 秒。若遇到 `OpenAPIUpdateField limited`，等待后只重试失败字段，不要重复更新已成功字段。

单选字段：

```bash
lark-cli base +field-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --field-id <field_id> \
  --json '{"name":"<字段名>","type":"select","multiple":false,"options":[<已有选项...>,{"name":"<新选项名>"}]}'
```

多选字段：

```bash
lark-cli base +field-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --field-id <field_id> \
  --json '{"name":"标签","type":"select","multiple":true,"options":[<已有选项...>,{"name":"<新标签>"}]}'
```

### 5. 创建论文子文档

```bash
lark-cli wiki +node-create \
  --space-id <space_id> \
  --parent-node-token <note_parent_node_token> \
  --obj-type docx \
  --title "<论文 Title>"
```

记录：

- `obj_token` 为 `child_doc_token`
- `node_token` 为 `child_node_token`

Wiki URL 优先使用 `wiki +node-create` 返回的 `data.url`。若返回值缺失，再使用通用 fallback：

```text
https://www.feishu.cn/wiki/<child_node_token>
```

### 6. 写入笔记并修正标题

`--content @<file>` 使用相对路径。若笔记在其他目录，先 `cd` 到文件所在目录再执行。

若目标子文档是新建空文档，可直接写入。若目标子文档已存在内容，必须先展示覆盖影响并获得用户确认。

```bash
lark-cli docs +update \
  --api-version v2 \
  --doc <child_doc_token> \
  --command overwrite \
  --doc-format markdown \
  --content @<NOTE.md>
```

同步标题：

```bash
lark-cli drive files patch \
  --params '{"file_token":"<child_doc_token>","type":"docx"}' \
  --data '{"new_title":"<论文 Title>"}'
```

回读验证标题：

```bash
lark-cli wiki spaces get_node --params '{"token":"<child_node_token>"}'
```

每次 `docs +update --command overwrite` 后都必须重新执行 `drive files patch` 并回读标题；若后续再次 overwrite，必须再次修正并验证标题。仍为 `Untitled` 时，不得继续后续步骤。

### 7. 创建 Base 记录

字段值严格来自笔记 `## 元数据` 表，`状态` 固定为 `待读`：

```bash
lark-cli base +record-batch-create \
  --base-token <app_token> \
  --table-id <table_id> \
  --json '{"fields":["Title","出版","年份","状态","标签","评分","笔记","Abstract","标题","摘要"],"rows":[["<Title>","<出版>","<年份>","待读",["<标签>"],3,"","<Abstract>","<标题>","<摘要>"]]}'
```

记录返回的 `record_id`。

### 8. 上传 PDF 附件

`--file` 使用相对路径。若 PDF 在其他目录，先 `cd` 到文件所在目录。

若记录中已有附件，重新上传前必须展示现有附件和将上传的新文件，获得用户确认后才继续。

```bash
lark-cli base +record-upload-attachment \
  --base-token <app_token> \
  --table-id <table_id> \
  --record-id <record_id> \
  --field-id "附件" \
  --file <PDF路径> \
  --name "paper.pdf"
```

如有附录，依次命名为 `appendix.pdf`、`appendix-2.pdf`。

### 9. 回写笔记链接

回写链接会更新已有 Base 记录字段；执行前必须确认目标 `record_id`、旧值和新值。新建记录且 `笔记` 字段为空时，可作为上传预览确认的一部分执行。

```bash
lark-cli base +record-batch-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --json '{"record_id_list":["<record_id>"],"patch":{"笔记":"[笔记](<child_doc_url>)"}}'
```

## 验收

- 子文档在 `论文笔记` 下，标题等于论文 `Title`，不为 `Untitled`。
- Base 记录存在，`状态 = 待读`，`评分 = 3`（除非用户修改或留空）。
- `笔记` 为 URL 样式，值为 `[笔记](<child_doc_url>)`。
- 附件里只有一个主文件 `paper.pdf`（附录除外）。
- `Title`、`Abstract`、`标题`、`摘要` 与笔记元数据表逐字一致。

## 反例

- 不要从 `metadata.json`、PDF 抽取结果或模型输出重新生成上传字段。
- 不要自动创建选项。
- 不要使用 `docs +search` 反查长标题文档。
- 不要把主 PDF 同时上传到 Drive 和 Base 附件。
