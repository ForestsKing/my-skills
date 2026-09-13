# arXiv 查询约定

## 默认筛选

默认查询标题中包含短语 `time series` 或 `time-series`，不限制分类并包含 cross-list。对应 API 查询为：

```text
(ti:"time series" OR ti:"time-series")
```

按 `lastUpdatedDate` 降序排列。

## submitted_date 与归档边界

使用 Atom `<updated>` 的 UTC 日期作为 `submitted_date`，对应 arXiv Advanced Search 中“Submission date (most recent)”的语义。

按 `lastUpdatedDate` 降序读取结果。第一篇通过查询条件和分类模式检查的论文确定 arXiv 最近 `submitted_date`，已有链接不参与这个日期的确定。

表格归档状态按以下规则决定是否处理该日：

- 表格没有记录：处理 arXiv 最近 `submitted_date`；
- 表格有记录且 arXiv 最近 `submitted_date` 严格晚于表格 `latest_date`：处理 arXiv 最近 `submitted_date`；
- arXiv 最近 `submitted_date` 等于或早于表格 `latest_date`：返回无新论文。

确定目标日后，继续读取直到完整覆盖该日期，只保留该日满足筛选条件且链接尚未存在的论文。目标日去重后为空时返回无新论文，不读取相同或更早日期作为替代批次。

## 分类

配置为空分类列表时不限制分类。指定分类后，API 使用分类条件缩小候选集：

- `include_cross_list=true`：论文任一分类命中即可；
- `include_cross_list=false`：返回后再次检查主分类，仅保留主分类命中者。

分类支持精确值和以 `.*` 结尾的大类形式。

## 数据源、分页与限流

默认使用 arXiv Atom API。只有连接失败、超时、HTTP 429 或 5xx 在有限重试后仍未恢复时，才切换到 `arxiv.org/search/` 搜索网页；其他 HTTP 错误、Atom 解析错误和分页一致性错误仍直接停止。

网页备用通道使用“Submission date (newest first)”排序和完整摘要，按与 API 相同的关键词、布尔关系和分类模式筛选。搜索结果页用于确定最近目标日和完整覆盖该日，随后逐篇读取 arXiv 摘要页的 citation metadata 与 Submission history，恢复精确版本号、首次提交时间和最后版本更新时间。搜索页日期必须与摘要页最后版本日期一致，否则停止。

- 所有请求串行执行；
- 两次请求至少间隔 3 秒；
- 有上限地重试连接失败、超时、HTTP 429 和 5xx；
- Atom 通道校验 `totalResults`、`startIndex` 和 Atom 错误条目；
- 网页通道校验结果总数跨页一致，并拒绝缺少结果数、提交日期或版本历史的页面；
- 跨页按规范化 arXiv ID 去重；
- 无法在 30,000 条可访问窗口内证明目标日期完整时停止并要求缩小筛选。

## ID 与链接

新式 ID 和旧式分类 ID 均规范化为不含版本号的 ID。飞书保存规范化 abs URL 的 Markdown 链接形式：

```text
[链接](https://arxiv.org/abs/<canonical_id>)
```

读取已有记录时，脚本会从原始 URL 或 Markdown 链接中提取 URL，并统一规范化为不含版本号的 abs URL。
