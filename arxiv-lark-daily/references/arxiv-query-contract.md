# arXiv 查询约定

## 默认筛选

默认查询标题中包含短语 `time series` 或 `time-series`，不限制分类并包含 cross-list。对应 API 查询为：

```text
(ti:"time series" OR ti:"time-series")
```

按 `lastUpdatedDate` 降序排列。

## submitted_date

使用 Atom `<updated>` 的 UTC 日期作为 `submitted_date`，对应 arXiv Advanced Search 中“Submission date (most recent)”的语义。

从新到旧找到第一篇尚未存在于飞书表格的论文，以其 UTC 日期为本批 `submitted_date`。继续读取，直到已完整覆盖该日期，再保留该日所有未归档论文。

## 分类

配置为空分类列表时不限制分类。指定分类后，API 使用分类条件缩小候选集：

- `include_cross_list=true`：论文任一分类命中即可；
- `include_cross_list=false`：返回后再次检查主分类，仅保留主分类命中者。

分类支持精确值和以 `.*` 结尾的大类形式。

## 分页与限流

- API 请求串行执行；
- 两次请求至少间隔 3 秒；
- 有上限地重试连接失败、超时、HTTP 429 和 5xx；
- 校验 `totalResults`、`startIndex` 和 Atom 错误条目；
- 跨页按规范化 arXiv ID 去重；
- 无法在 30,000 条可访问窗口内证明目标日期完整时停止并要求缩小筛选。

## ID 与链接

新式 ID 和旧式分类 ID 均规范化为不含版本号的 ID。飞书保存规范化 abs URL 的 Markdown 链接形式：

```text
[链接](https://arxiv.org/abs/<canonical_id>)
```

读取已有记录时，脚本会从原始 URL 或 Markdown 链接中提取 URL，并统一规范化为不含版本号的 abs URL。
