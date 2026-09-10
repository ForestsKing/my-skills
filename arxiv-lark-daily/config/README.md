# 配置说明

`default.json` 只包含运行者可以安全修改、也可以随 skill 公开的项目；不要在配置文件中保存飞书凭据、真实测试 Base token、租户专属域名、用户本机路径或其他私密信息：

```json
{
  "base_name": "arXiv 每日论文",
  "table_name": "论文清单",
  "search": {
    "field": "title",
    "keywords": ["time series", "time-series"],
    "match": "any",
    "categories": [],
    "include_cross_list": true
  },
  "retention_days": 30
}
```

- `base_name`：飞书多维表格名称。按精确名称查找；存在多个同名 Base 时会停止。
- `table_name`：多维表格中的数据表名称。Base 中应且仅应存在一个同名数据表。
- `search.field`：检索字段，可选 `all`、`title`、`author`、`abstract`、`comment`、`journal_reference`、`report_number`、`category`。
- `search.keywords`：一个或多个非空 arXiv 检索关键词。
- `search.match`：`any` 表示任一关键词匹配；`all` 表示所有关键词同时匹配。
- `search.categories`：arXiv 分类列表；空数组表示不限分类，例如 `[
  "cs.LG", "stat.ML"
]`。
- `search.include_cross_list`：`true` 时任一分类命中即可；`false` 时仅接受主分类命中。
- `retention_days`：本地运行状态保留天数，默认 30。脚本根据本次最新 `submitted_date` 清理本地 manifest 中过期论文条目，不删除飞书表格中的历史记录。

表格字段、字段类型、日期口径、论文关键词规则、API 限流、分页上限、schema 修订策略、日报模板路径和内部状态文件路径属于 skill 的固定运行契约，不放入用户配置。配置中不保存 arXiv Advanced Search URL。
