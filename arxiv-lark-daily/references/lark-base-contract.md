# 飞书多维表格约定

## 身份

所有操作显式使用 `--as user`。运行前通过 `lark-cli auth status --json --verify` 验证登录。成功响应可能表现为退出码 0 且 `ok` 不为 `false`，或 `code/err_code` 为 `0`；失败响应可能使用 `ok=false`、`success=false`、非零 `code/err_code`、`msg/message/error/errors` 等字段。不得输出 token、App Secret 或授权码。

## 资源定位

按配置中的 Base 名称和数据表名称精确匹配。没有同名 Base 时可以创建；多个同名 Base 时停止。后续步骤使用返回的稳定 token 和 ID。

脚本读取 `lark-cli` 响应时兼容常见标识字段别名：Base 可使用 `base_token`、`app_token`、`appToken` 或 `token`；数据表可使用 `table_id`、`tableId` 或 `id`；字段可使用 `field_id`、`fieldId` 或 `id`；视图可使用 `view_id`、`viewId` 或 `id`。如果验收所需字段缺少可用 ID，应停止而不是猜测。

## 固定字段

字段名称、类型和顺序必须为：

1. `标题`：`text`；
2. `摘要`：`text`；
3. `关键词`：`text`；
4. `日期`：`datetime`，显示格式 `yyyy-MM-dd`；
5. `链接`：`text`，URL 样式。

“链接”列必须使用 URL 样式文本字段，记录值写成 Markdown 链接：

```text
[链接](https://arxiv.org/abs/2609.01234)
```

## 已有表 schema 处理

schema 正确时直接继续，并尝试为默认或首个 View 设置固定五列为可见字段。真实界面的列顺序可能受主字段和 `lark-cli` 行为影响；字段名称、类型和样式的验收结果是继续运行的依据。

schema 不正确时，先使用无 View、无过滤条件的最小记录查询判断整表是否有记录：

```bash
lark-cli base +record-list \
  --base-token <base_token> \
  --table-id <table_id> \
  --offset 0 \
  --limit 1 \
  --format json \
  --as user
```

- 至少有一条记录：立即退出，不修改任何字段；
- 没有记录：允许修订字段。

非空表不符合固定字段契约时，说明历史数据和字段均未修改。用户需要先手动迁移为最终五列 schema，或在配置中指定一张空数据表，再重新运行。

空表恰有五列时，按位置原地更新为最终五列。字段数量不符时，保留第一列主字段并更新为 `标题`，删除其余非主字段，再按顺序创建 `摘要`、`关键词`、`日期`、`链接`。每次字段更新都提交完整字段定义，并带 `--yes`。修订后必须重新读取字段并严格验收。

## 关键词文本

模型在 enrichment 中提供 2–4 个论文关键词组成的 `keywords` 数组。脚本完成格式校验后，使用中文顿号 `、` 按原顺序连接数组元素，并将结果写入“关键词”文本字段。例如 `时序、深度学习、概率建模`。飞书单元格只接收连接后的字符串。

## 归档状态与去重

`export-state` 对“日期”和“链接”列执行一次完整分页读取，并输出：

```json
{
  "record_count": 12,
  "latest_date": "2026-09-04",
  "links": ["https://arxiv.org/abs/2609.01234"]
}
```

`record_count` 是实际读取到的记录数，不以有效链接数代替。空表输出 `record_count=0` 和空 `latest_date`。非空表的每条记录都必须包含可解析日期；脚本将日期规范化为 `YYYY-MM-DD` 并取最大值，缺少日期或日期无效时停止。

链接集合只用于目标日内去重。使用规范化 abs URL 作为业务唯一键，读取“链接”列时同时支持以下单元格值：

```text
https://arxiv.org/abs/2609.01234
[链接](https://arxiv.org/abs/2609.01234)
```

两者都规范化为：

```text
https://arxiv.org/abs/2609.01234
```

`record-list --format json` 的返回可能是对象数组，也可能是 `fields` 加行数组。脚本应兼容：

```json
{
  "fields": ["日期", "链接"],
  "data": [["2026-09-04T00:00:00Z", "[链接](https://arxiv.org/abs/2609.01234)"]],
  "record_id_list": ["recxxx"]
}
```

也应兼容字段对象和字段 ID：

```json
{
  "fields": [
    {"name": "日期", "field_id": "fldDate"},
    {"name": "链接", "field_id": "fldLink"}
  ],
  "rows": [["2026-09-04T00:00:00Z", "[链接](https://arxiv.org/abs/2609.01234)"]],
  "record_ids": ["recxxx"]
}
```

如果记录 ID 作为行内列返回，字段名可能是 `record_id`、`recordId`、`id` 或 `记录ID`。“日期”和“链接”字段读取同时接受字段名以及 `base.json` 中对应的字段 ID。

## 写入载荷

记录创建使用 `lark-cli base +record-batch-create` 的行数组载荷。列顺序由 `fields` 指定，每一行的值必须与字段顺序对应：

```json
{
  "fields": ["标题", "摘要", "关键词", "日期", "链接"],
  "rows": [[
    "Original English title",
    "忠实中文翻译",
    "时序、深度学习",
    "2026-09-03T00:00:00Z",
    "[链接](https://arxiv.org/abs/2609.01234)"
  ]]
}
```

创建响应可以通过 `record_id_list`、`record_ids`、`recordIds`、`records[].record_id`、`records[].recordId` 或 `records[].id` 返回记录 ID。每完成一条记录都更新 manifest。恢复运行时先按规范化 abs URL 查询，确认不存在后才创建，避免重复数据。
