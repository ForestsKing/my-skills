# 建库初始化

## 触发条件

用户要求创建、初始化或重新建立飞书论文知识库时使用。若用户只是上传到已有知识库，先确认该知识库已由用户明确指定为目标，不要因为名称相同就自动补齐结构。

执行前读取：

- `references/lark-workflows.md`
- `references/command-pitfalls.md`

## 前置检查

1. 定位 skill 根目录：包含 `SKILL.md` 的 `paper-lark-reader/` 目录。后续配置读写均使用 `<SKILL_ROOT>/config/defaults.json`，不要使用当前项目目录下的同名路径。
2. 读取 `<SKILL_ROOT>/config/defaults.json`，取得目标知识库名称。
3. 运行环境检查：
   ```bash
   python3 scripts/paper_lark_cli.py check
   lark-cli --version
   ```
4. 本流程不绑定固定 `lark-cli` 版本；执行前以当前环境的 `--help` 或 `schema` 确认命令参数。
5. 若 `lark-cli` 未安装、未登录或权限不足，停止建库并提示用户先完成飞书 CLI 配置。

## 步骤

### 1. 检查同名知识库

```bash
lark-cli wiki spaces list --format json
```

在返回的 `items` 中精确匹配目标名称。

- 若存在同名知识库：展示候选的名称、`space_id`、空间类型和可区分线索，说明复用风险，等待用户确认复用哪个候选或改用新名称。
- 若不存在同名知识库：继续新建。

### 2. 创建或复用知识库

新建知识库：

```bash
lark-cli wiki spaces create \
  --data '{"name":"<知识库名称>","description":"学术论文管理知识库"}'
```

记录返回的 `space_id`。

复用知识库时，使用用户确认的 `space_id`，并先只读扫描结构；涉及覆盖、更新、删除、移动、合并、重命名或清理已有资源时另行确认。

### 3. 创建或定位 `论文索引` Base

复用知识库时先列出根节点：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","page_size":50}'
```

若存在标题为 `论文索引` 且 `obj_type` 为 `bitable` 的节点，记录其 `obj_token` 为 `app_token`。

若不存在，创建 Base 节点：

```bash
lark-cli wiki +node-create \
  --space-id <space_id> \
  --obj-type bitable \
  --title "论文索引"
```

记录 `obj_token` 为 `app_token`。

### 4. 获取并重命名默认表

```bash
lark-cli base +table-list --base-token <app_token>
```

记录默认 `table_id`，然后重命名：

```bash
lark-cli base +table-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --name "数据表"
```

### 5. 重命名默认视图

```bash
lark-cli base +view-list --base-token <app_token> --table-id <table_id>
lark-cli base +view-rename \
  --base-token <app_token> \
  --table-id <table_id> \
  --view-id <view_id> \
  --name "概览"
```

### 6. 清理默认字段并创建业务字段

先读取字段：

```bash
lark-cli base +field-list --base-token <app_token> --table-id <table_id>
```

主列只能重命名，不可删除：

```bash
lark-cli base +field-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --field-id <primary_field_id> \
  --json '{"name":"Title","type":"text"}'
```

其他默认字段逐一删除，字段删除之间保留 2 秒间隔。此操作仅适用于全新创建的空 Base；复用已有 Base 时，删除任何字段前必须展示字段清单和影响并获得用户确认。

```bash
for fid in <field_id_1> <field_id_2>; do
  lark-cli base +field-delete \
    --base-token <app_token> \
    --table-id <table_id> \
    --field-id "$fid" \
    --yes
  sleep 2
done
```

按以下顺序创建字段：

| 顺序 | 字段名 | `--json` |
|---|---|---|
| 0 | Title | 主列，已重命名 |
| 1 | 出版 | `{"name":"出版","type":"select","options":[]}` |
| 2 | 年份 | `{"name":"年份","type":"select","options":[]}` |
| 3 | 状态 | `{"name":"状态","type":"select","options":[{"name":"待读"}]}` |
| 4 | 标签 | `{"name":"标签","type":"select","multiple":true,"options":[]}` |
| 5 | 评分 | `{"name":"评分","type":"number","style":{"type":"rating","icon":"star","min":1,"max":5}}` |
| 6 | 创建 | `{"name":"创建","type":"created_at"}` |
| 7 | 附件 | `{"name":"附件","type":"attachment"}` |
| 8 | 笔记 | `{"name":"笔记","type":"text","style":{"type":"url"}}` |
| 9 | Abstract | `{"name":"Abstract","type":"text"}` |
| 10 | 标题 | `{"name":"标题","type":"text"}` |
| 11 | 摘要 | `{"name":"摘要","type":"text"}` |

创建命令：

```bash
lark-cli base +field-create \
  --base-token <app_token> \
  --table-id <table_id> \
  --json '<上表 JSON>'
```

### 7. 固定 `概览` 视图字段顺序

字段创建后，使用 `+view-set-visible-fields` 设置视图列顺序；不要依赖 `+field-list` 的返回顺序。

```bash
lark-cli base +view-set-visible-fields \
  --base-token <app_token> \
  --table-id <table_id> \
  --view-id <view_id> \
  --json '{"visible_fields":["<Title字段ID>","<出版字段ID>","<年份字段ID>","<状态字段ID>","<标签字段ID>","<评分字段ID>","<创建字段ID>","<附件字段ID>","<笔记字段ID>","<Abstract字段ID>","<标题字段ID>","<摘要字段ID>"]}'
```

回读验证：

```bash
lark-cli base +view-get-visible-fields \
  --base-token <app_token> \
  --table-id <table_id> \
  --view-id <view_id>
```

### 8. 清理默认空行

```bash
lark-cli base +record-list \
  --base-token <app_token> \
  --table-id <table_id> \
  --limit 200
```

若存在所有业务字段均为空的默认记录，逐条删除。判断默认空记录时忽略系统字段，例如 `创建/created_at`；只要论文业务字段为空，即可视为新建 Base 的默认占位行。此操作仅适用于全新创建的空 Base；复用已有 Base 时，删除任何记录前必须展示记录内容和影响并获得用户确认。

```bash
for rid in <record_id_1> <record_id_2>; do
  lark-cli base +record-delete \
    --base-token <app_token> \
    --table-id <table_id> \
    --record-id "$rid" \
    --yes
done
```

### 9. 创建或定位 `论文笔记` 父文档

复用知识库时先查根节点：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","page_size":50}'
```

若存在标题为 `论文笔记` 且 `obj_type` 为 `docx` 的节点，记录：

- `obj_token` 为 `note_parent_doc_token`
- `node_token` 为 `note_parent_node_token`

若不存在，创建文档节点：

```bash
lark-cli wiki +node-create \
  --space-id <space_id> \
  --obj-type docx \
  --title "论文笔记"
```

### 10. 插入并验证子文档列表组件

`folder_manager` 的 `block_type` 为 `51`，`wiki_token` 使用 `note_parent_node_token`：

```bash
lark-cli api POST /docx/v1/documents/<note_parent_doc_token>/blocks/<note_parent_doc_token>/children \
  --as user \
  --data '{"children":[{"block_type":51,"sub_page_list":{"wiki_token":"<note_parent_node_token>"}}]}'
```

验证：

```bash
lark-cli docs +fetch \
  --api-version v2 \
  --doc <note_parent_doc_token> \
  --format pretty
```

结果中出现 `<folder_manager>` 才算通过。若不含，停止并提示用户手动插入飞书子文档列表组件。

### 11. 保存配置

将以下字段写入 `<SKILL_ROOT>/config/defaults.json`，不得写入当前项目目录：

```json
{
  "knowledge_base_name": "<知识库名称>",
  "space_id": "<space_id>",
  "app_token": "<app_token>",
  "table_id": "<table_id>",
  "note_parent_doc_token": "<note_parent_doc_token>",
  "note_parent_node_token": "<note_parent_node_token>"
}
```

## 验收

- 知识库名称与用户确认一致。
- Base 标题为 `论文索引`，表名为 `数据表`，视图名为 `概览`。
- `概览` 视图可见字段顺序为：`Title、出版、年份、状态、标签、评分、创建、附件、笔记、Abstract、标题、摘要`。
- `评分` 为 Rating 样式，`笔记` 为 URL 样式文本字段。
- `论文笔记` 父文档存在，且 `docs +fetch` 中包含 `<folder_manager>`。
- `<SKILL_ROOT>/config/defaults.json` 包含后续流程所需 token。

## 反例

- 不要自动复用同名知识库。
- 不要删除主列。
- 不要把 `type` 写成数字。
- 不要给 shortcut 命令添加 `--format`。
- 不要在路径中写 `/open-apis` 前缀。
