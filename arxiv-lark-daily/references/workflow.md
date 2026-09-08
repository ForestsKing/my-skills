# 流程状态约定

## 运行产物

运行产物保存在当前目录的 `.arxiv-lark-daily/`：

- `base.json`：Base、数据表、默认 View、字段标识、Base 链接和已有标签选项；
- `archive-state.json`：表格实际记录数、最大有效日期和已归档论文的规范化 abs URL；
- `papers.json`：本批 `submitted_date` 的论文及处理状态；
- `write-manifest.json`：记录创建进度，用于中断恢复。

不要在这些文件中保存飞书凭据。

## 论文状态

每篇论文状态只保存归档需要的信息：

```json
{
  "canonical_id": "2609.01234",
  "version": 2,
  "title": "Original English title",
  "abstract_en": "Original abstract",
  "abstract_zh": "忠实中文翻译",
  "published": "2026-09-01T10:00:00Z",
  "updated": "2026-09-03T11:00:00Z",
  "submitted_date": "2026-09-03",
  "abs_url": "https://arxiv.org/abs/2609.01234",
  "authors": [],
  "primary_category": "cs.LG",
  "categories": ["cs.LG", "stat.ML"],
  "tags": [],
  "record_id": "",
  "errors": []
}
```

表格实际记录数用于判断空表，最大有效日期用于确定归档边界。飞书链接集合只在目标日内去重，使用不含版本号的规范化 abs URL；标题不能作为去重键。

## enrichment 文件

生成 enrichment 前先读取 `.arxiv-lark-daily/base.json` 中的 `tag_options`。语义合适时复用已有标签名称。

```json
{
  "papers": {
    "2609.01234": {
      "abstract_zh": "忠实中文翻译",
      "tags": ["时序", "深度学习", "概率建模"]
    }
  }
}
```

- `abstract_zh` 必填；
- `tags` 必填，必须是 2–4 个合法中文或中英混合技术标签。

## 翻译要求

翻译 Atom 原摘要，不将其改写成摘要总结。必须保留数字、百分比、单位、模型和数据集名称、缩写、公式、否定、限制和不确定语气。不得加入评价、背景、贡献要点或阅读建议。

## 标签要求

标签应优先覆盖研究任务、方法类别、数据或应用领域、关键学习范式。每篇论文生成 2–4 个标签，优先 2–3 个；只有存在明确且互不重复的补充维度时才使用 4 个。每个标签最长 6 个字，至少包含一个中文字符；优先使用短中文技术词，允许 `时序`、`时序LLM`、`3D视觉` 这类缩写或中英混合词；不为了凑数生成 `时间序列`、`机器学习` 等过宽泛标签。标签不允许纯英文、空值、重复值、完整句子、作者名或论文标题直抄。

## 本地状态保留

配置项 `retention_days` 默认 30。脚本以本次最新 `submitted_date` 为基准，清理本地 manifest 中早于“最新 `submitted_date` 往前 `retention_days` 天”的论文条目；保留窗口两端均为闭区间。该清理只影响本地恢复状态，不删除飞书多维表格中的历史记录。

## 总结输入

正常日报由 `templates/daily-summary.md` 定义版式，由 `scripts/render_summary.py` 渲染。模型只需要准备以下输入文件。

### 今日要点

`daily-highlights.md` 是“今日要点”的输入文件。为了兼容旧调用，`domain-overview.txt` 也可作为同一内容输入，但语义仍是今日要点而不是泛泛主题概述。

今日要点应满足：

- 3–5 条 Markdown bullet；
- 每条尽量不超过 35 个汉字；
- 每条聚焦具体研究任务、方法、数据或应用场景；
- 覆盖本批论文的主要聚类，不要求逐篇覆盖；
- 不写“领域发展迅速”“值得关注”“趋势明显”这类空泛判断；
- 不虚构论文没有的信息。

### 阅读建议

`reading-recommendations.md` 使用紧凑 Markdown 表格，建议列为：`方法`、`论文`、`推荐理由`。

- `论文` 列使用 `[方法名](abs链接)`；方法名优先来自论文标题中的方法、框架、模型或数据集名称；没有明确方法名时，用精炼主题名代替；
- 可以在日报中出现 arXiv abs 链接，链接应指向本批 `papers.json` 中的 `abs_url`；
- 推荐 3–5 篇或 3–5 组论文，不需要覆盖全部论文；
- 推荐理由说明适合谁先读、解决什么判断问题或为什么与其他论文形成互补；
- 不使用“这篇论文”“相关工作”“值得阅读”这类缺乏信息量的表述；
- 不虚构论文内容，不引用本批以外论文。
