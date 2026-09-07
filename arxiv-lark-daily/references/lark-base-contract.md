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
3. `标签`：`select`，`multiple=true`，静态多选；
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

空表恰有五列时，按位置原地更新为最终五列。字段数量不符时，保留第一列主字段并更新为 `标题`，删除其余非主字段，再按顺序创建 `摘要`、`标签`、`日期`、`链接`。每次字段更新都提交完整字段定义，并带 `--yes`。修订后必须重新读取字段并严格验收。

## 标签选项

`prepare` 阶段读取“标签”字段全部静态选项并写入 `base.json` 的 `tag_options`。模型生成标签前必须读取该列表，语义合适时原样复用已有名称。

写入记录前，脚本重新读取“标签”字段完整定义，按精确名称找出缺失标签，保留已有选项顺序和元数据，将缺失标签追加到末尾，执行完整字段更新，然后读回确认所有标签均存在。同一次运行只集中更新一次标签字段。

## 去重

使用规范化 abs URL 作为业务唯一键。读取“链接”列时必须处理分页，并同时支持以下单元格值：

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
  "fields": ["链接"],
  "data": [["[链接](https://arxiv.org/abs/2609.01234)"]],
  "record_id_list": ["recxxx"]
}
```

也应兼容字段对象和字段 ID：

```json
{
  "fields": [{"name": "链接", "field_id": "fldxxx"}],
  "rows": [["[链接](https://arxiv.org/abs/2609.01234)"]],
  "record_ids": ["recxxx"]
}
```

如果记录 ID 作为行内列返回，字段名可能是 `record_id`、`recordId`、`id` 或 `记录ID`。链接字段读取同时接受字段名 `链接` 和 `base.json` 中记录的链接字段 ID。

## 写入载荷

记录创建使用 `lark-cli base +record-batch-create` 的行数组载荷。列顺序由 `fields` 指定，每一行的值必须与字段顺序对应：

```json
{
  "fields": ["标题", "摘要", "标签", "日期", "链接"],
  "rows": [[
    "Original English title",
    "忠实中文翻译",
    ["时间序列预测", "深度学习"],
    "2026-09-03T00:00:00Z",
    "[链接](https://arxiv.org/abs/2609.01234)"
  ]]
}
```

创建响应可以通过 `record_id_list`、`record_ids`、`recordIds`、`records[].record_id`、`records[].recordId` 或 `records[].id` 返回记录 ID。每完成一条记录都更新 manifest。恢复运行时先按规范化 abs URL 查询，确认不存在后才创建，避免重复数据。
