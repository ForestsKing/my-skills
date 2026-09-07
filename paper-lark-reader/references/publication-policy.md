# 出版核验策略

联网检索默认只用于出版元数据核验，不用于扩写论文内容。除非用户明确要求，不要把联网检索结果写成论文内容补充或替代正文依据。

## 必须核验

以下情况必须核验出版信息：

- PDF 来自 arXiv、bioRxiv、medRxiv、SSRN 或其他预印本平台。
- PDF 缺少明确出版来源或年份。
- PDF 同时出现预印本和正式 venue 信息。
- 文件名、PDF metadata、首页信息互相冲突。
- 用户明确要求核验出版信息。

## 优先级

1. DOI / Crossref。
2. arXiv 页面及 DOI / journal reference。
3. Semantic Scholar 或 OpenAlex。
4. 出版社、会议、期刊官网。
5. Google Scholar 只能作弱辅助线索。

## 输出要求

出版候选必须包含：

- `出版` 候选。
- `年份` 候选。
- 来源链接。
- 证据摘要。
- 置信度。
- 是否需要用户确认。

如果正式发表版本与预印本标题略有差异，必须提示用户确认是否同一篇。

## 出版简称

`出版` 字段使用常用简称，不带年份、卷期、页码或 workshop/session 信息。会议使用通用 acronym，例如 `NeurIPS`、`ICML`、`ICLR`、`CVPR`、`ACL`、`EMNLP`、`KDD`；期刊使用通用短名，例如 `Nature`、`Science`、`Cell`、`PNAS`、`JMLR`、`TPAMI`；预印本使用平台短名，例如 `arXiv`、`bioRxiv`、`medRxiv`。

若 Crossref 或 PDF 给出长名，但 Base `出版` 现有选项中存在对应简称，必须复用现有简称。若无法可靠映射，保留最短且可识别的 venue 名称；上传或新增 `出版` 选项前仍需确认。

## 写入边界

- 可以把已确认的 `出版` 和 `年份` 写入笔记元数据。
- 上传或新增 Base 选项前仍需确认。
- 不要用联网结果补写论文方法、实验或结论。
