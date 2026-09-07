# 命令陷阱与查阅规则

执行任何 `lark-cli` 命令前必须阅读本文件。

本 skill 不绑定固定 `lark-cli` 版本。执行前以当前环境的 `--help` 或 `schema` 确认参数；若 help 与已验证行为冲突，优先使用本文记录的已验证命令形态并记录错误。

## 查阅规则

构造命令前先确认参数格式：

```bash
# 查看原生命令请求结构
lark-cli schema <resource>.<method>

# 查看 CLI 版本；不要使用 `lark-cli version`
lark-cli --version

# 查看 shortcut 或原生命令 flag
lark-cli <resource> <cmd> --help
lark-cli <resource> +<shortcut> --help
```

| 类型 | 示例 | 参数方式 | `--format` |
|---|---|---|---|
| shortcut | `wiki +node-create` | 专属 flag，如 `--space-id` | 通常不支持 |
| 原生命令 | `wiki nodes list` | `--params '{"key":"val"}'` | 支持 |

Base 业务操作优先使用 `lark-cli base +...`。只有 shortcut 缺少必要能力时，才使用 `lark-cli api` 或原生命令，并且必须先查 schema/help。

## 已知陷阱

### P1 Wiki 原生命令参数走 `--params`

错误：

```bash
lark-cli wiki nodes list --space-id <space_id>
```

正确：

```bash
lark-cli wiki nodes list --params '{"space_id":"<space_id>","page_size":50}'
lark-cli wiki spaces get_node --params '{"token":"<wiki_node_token>"}'
```

### P2 `field-create/update` 的 `type` 使用字符串

错误：

```bash
--json '{"field_name":"Title","type":1}'
```

正确：

```bash
--json '{"name":"Title","type":"text"}'
```

### P3 `docs +update --api-version v2` 使用 `--command`

当前已验证的 v2 写 Markdown 兜底命令使用 `--command`、`--doc-format` 和 `--content`。如果 `docs +update --help` 展示 `--mode/--markdown`，但执行时报 `--command is required`，仍使用下面的已验证命令形态：

```bash
lark-cli docs +update \
  --api-version v2 \
  --doc <doc_token> \
  --command overwrite \
  --doc-format markdown \
  --content @<NOTE.md>
```

`@<file>` 按当前工作目录解析。跨目录时先 `cd` 到文件所在目录。标题同步使用 `drive files patch`。

`overwrite` 后标题可能回退为 `Untitled`。每次 `docs +update --command overwrite` 后，都要重新 `drive files patch` 并用 `wiki spaces get_node` 回读标题。

读取 docx 时不要使用不存在的 `--format markdown`；需要读取正文时使用默认 JSON、`--format pretty`，或按 `docs +fetch --help` 支持的格式选择。

### P4 `lark-cli api` 路径不加 `/open-apis`

错误：

```bash
lark-cli api GET /open-apis/<resource-path>
```

正确：

```bash
lark-cli api GET /bitable/v1/apps/...
```

CLI 会自动添加 `/open-apis` 前缀。

### P5 shortcut 不要加 `--format`

错误：

```bash
lark-cli wiki +node-create ... --format json
```

正确：

```bash
lark-cli wiki +node-create ...
```

需要结构化输出时优先使用 `-q/--jq`，或改用支持 `--format` 的原生命令。

### P6 `+record-delete` 一次只删一条

```bash
for rid in rec1 rec2; do
  lark-cli base +record-delete \
    --base-token <app_token> \
    --table-id <table_id> \
    --record-id "$rid" \
    --yes
done
```

### P7 批量删除字段要限速

```bash
for fid in fld1 fld2; do
  lark-cli base +field-delete \
    --base-token <app_token> \
    --table-id <table_id> \
    --field-id "$fid" \
    --yes
  sleep 2
done
```

连续字段删除可能触发频率限制。

### P8 创建知识库用 `--data`

```bash
lark-cli wiki spaces create \
  --data '{"name":"论文仓库","description":"学术论文管理知识库"}'
```

不要使用不存在的 `--name` 或 `--description` flag。

### P9 `+field-update` 是全量 PUT

更新选项前先读取现有字段：

```bash
lark-cli base +field-list --base-token <app_token> --table-id <table_id>
```

然后构造包含完整旧选项和新选项的 JSON：

```bash
lark-cli base +field-update \
  --base-token <app_token> \
  --table-id <table_id> \
  --field-id <field_id> \
  --json '{"name":"标签","type":"select","multiple":true,"options":[<已有选项...>,{"name":"新标签"}]}'
```

缺少 `name`、`type` 或完整 `options` 可能导致旧配置丢失。

连续更新多个字段可能触发 `OpenAPIUpdateField limited`。多个 `+field-update` 要串行执行，字段之间等待约 2 秒；限频后只重试失败字段。
