---
name: arxiv-lark-daily
description: 每日检索指定主题的最新 arXiv 论文，仅在 arXiv 最近 submitted_date 严格晚于飞书多维表格最新日期时归档该整日论文；表为空时直接归档 arXiv 最近一天。忠实翻译摘要，生成中文技术关键词，写入飞书多维表格，并输出包含日期、数量、表格链接、今日要点和具体阅读建议的中文日报。用户提到 arXiv 日报、论文监控、主题论文订阅、同步论文到飞书多维表格或重新执行最近一期论文归档时应使用本 skill，即使用户没有明确说出 skill 名称。
---

# arXiv 每日论文归档

使用这个 skill 时，模型负责组织运行流程、生成忠实中文摘要、中文技术关键词、今日要点和具体阅读建议；确定性的配置校验、arXiv 查询、去重、飞书多维表格 schema 管理、记录写入和日报渲染交给随 skill 分发的脚本执行。每次运行最多归档以 Atom `<updated>` 的 UTC 日期定义的最近一个 `submitted_date`。

## 组件分工

- `SKILL.md`：入口和调度说明。只描述运行顺序、何时读取组件、模型负责哪些判断，以及遇到哪些情况停止。
- `config/default.json`：默认公开配置。用户要改主题、目标 Base、表名或本地状态保留期时，读取 `config/README.md`。
- `scripts/`：可执行实现。所有会改变本地状态或飞书多维表格的确定性动作都通过脚本完成，不在对话中临时重写同类逻辑。
- `templates/daily-summary.md`：日报最终输出格式的唯一模板。不要把模板正文复制到 `SKILL.md`；渲染时由 `render_summary.py` 读取该文件。
- `references/`：细节契约。需要字段定义、写入载荷、enrichment 结构、arXiv 日期口径或失败恢复规则时，读取对应 reference，而不是在 `SKILL.md` 中展开。

## 路径约定

将 `SKILL_DIR` 设为本 `SKILL.md` 所在目录。所有相对路径均从 `SKILL_DIR` 解析。运行产物保存在用户当前目录的 `.arxiv-lark-daily/` 中。

## 运行前检查

读取 `$SKILL_DIR/config/README.md`，确认配置含义后运行：

```bash
python "$SKILL_DIR/scripts/preflight.py" --config "$SKILL_DIR/config/default.json"
```

检查失败时立即停止。不要自动发起飞书登录，不输出 token、App Secret、device code 或完整认证响应。需要判断失败后的处理方式时读取 `$SKILL_DIR/references/failure-and-recovery.md`。

## 执行流程

### 1. 定位或创建飞书多维表格

先读取 `$SKILL_DIR/references/lark-base-contract.md`，再运行：

```bash
python "$SKILL_DIR/scripts/lark_base.py" prepare \
  --config "$SKILL_DIR/config/default.json" \
  --output .arxiv-lark-daily/base.json
```

脚本按配置精确匹配 Base 和数据表，创建或复用资源，验收固定五列 schema，并把字段 ID、Base URL 和 View ID 写入 `.arxiv-lark-daily/base.json`。具体字段契约和安全修订规则以 `references/lark-base-contract.md` 为准。

### 2. 导出表格归档状态

```bash
python "$SKILL_DIR/scripts/lark_base.py" export-state \
  --config "$SKILL_DIR/config/default.json" \
  --base-state .arxiv-lark-daily/base.json \
  --output .arxiv-lark-daily/archive-state.json
```

脚本读取整表的“日期”和“链接”列，输出实际记录数、最新有效日期和规范化 arXiv abs URL 集合。实际记录数用于判断表是否为空，最新日期用于确定归档边界，链接只用于目标日内去重。非空表存在空日期或无效日期时停止。

### 3. 获取严格晚于归档边界的 arXiv 最近一天

读取 `$SKILL_DIR/references/arxiv-query-contract.md`，再运行：

```bash
python "$SKILL_DIR/scripts/arxiv_client.py" fetch \
  --config "$SKILL_DIR/config/default.json" \
  --archive-state .arxiv-lark-daily/archive-state.json \
  --manifest .arxiv-lark-daily/write-manifest.json \
  --output .arxiv-lark-daily/papers.json
```

脚本使用 Atom `<updated>` 的 UTC 日期作为 `submitted_date`，并以通过完整筛选的第一篇论文确定 arXiv 最近一天。表为空时收集该日全部论文；表非空时，仅当该日严格晚于表格最新日期才收集。链接去重只作用于这个目标日，不得转向相同或更早日期查找论文。

如果 arXiv 没有匹配论文、最近一天没有严格晚于表格最新日期，或目标日去重后没有论文，直接转述脚本输出的固定无新论文消息。此时停止后续步骤，不要翻译、写表或生成日报。本地 manifest 的保留期清理由脚本按 `retention_days` 执行，只影响本地恢复状态，不删除飞书多维表格历史记录。

### 4. 生成摘要翻译和论文关键词

读取 `$SKILL_DIR/references/workflow.md`，按其中的 enrichment 结构生成 enrichment 文件。内部 `keywords` 字段表示论文关键词数组，由脚本校验并在写入时转换为“关键词”文本单元格。

翻译对象只能是 Atom `<summary>` 原摘要。保留数字、百分比、单位、方法名、数据集名、缩写、否定、限制、不确定语气和 LaTeX；不要概括、评价或补充原文没有的信息。

每篇论文生成 2–4 个关键词，优先 2–3 个。关键词应是简短、稳定的中文或中英混合技术主题词；每个关键词最长 6 个字且至少包含一个中文字符；不允许纯英文、空关键词、重复关键词、完整句子、作者名或论文标题直抄。

应用并校验：

```bash
python "$SKILL_DIR/scripts/run_pipeline.py" apply-enrichment \
  --papers .arxiv-lark-daily/papers.json \
  --enrichment enrichment.json

python "$SKILL_DIR/scripts/run_pipeline.py" validate-enrichment \
  --papers .arxiv-lark-daily/papers.json
```

出现忠实性警告或论文关键词错误时停止，不要进入写入步骤。核对原文并修正 `enrichment.json`，重新执行 `apply-enrichment` 和 `validate-enrichment`；只有两项命令均成功后才能继续。

### 5. 写入飞书多维表格

```bash
python "$SKILL_DIR/scripts/lark_base.py" write \
  --config "$SKILL_DIR/config/default.json" \
  --base-state .arxiv-lark-daily/base.json \
  --papers .arxiv-lark-daily/papers.json \
  --manifest .arxiv-lark-daily/write-manifest.json
```

脚本校验关键词数组后，用中文顿号 `、` 连接为文本并写入“关键词”列。写入载荷格式、创建响应解析和恢复去重规则以 `references/lark-base-contract.md` 为准。

### 6. 输出日报

结合本批全部论文，生成精炼的 `daily-highlights.md` 和 `reading-recommendations.md`。今日要点和阅读建议的内容契约以 `references/workflow.md` 为准；其中阅读建议可以引用本批论文的 arXiv abs 链接。

```bash
python "$SKILL_DIR/scripts/render_summary.py" \
  --config "$SKILL_DIR/config/default.json" \
  --papers .arxiv-lark-daily/papers.json \
  --base-state .arxiv-lark-daily/base.json \
  --daily-highlights-file daily-highlights.md \
  --reading-recommendations-file reading-recommendations.md
```

日报格式由 `templates/daily-summary.md` 唯一定义。脚本会把日期、数量和多维表格链接渲染为一句自然语言；除多维表格链接外，阅读建议中允许出现本批论文的 arXiv abs 链接。

## 必须停止的情况

遇到以下情况时停止并说明原因，不进行猜测或静默降级：

- `lark-cli` 不存在或 user 登录验证失败；
- 目标 Base 同名不唯一；
- 已有数据表 schema 不符合契约且表内已有记录；
- 空表 schema 修订或修订后验收失败；
- 配置中的检索字段、arXiv 检索关键词、匹配方式、分类格式或保留期无效；
- arXiv 返回错误、分页不一致或查询范围无法完整读取；
- arXiv 没有严格晚于表格最新日期的目标日时正常停止，并只输出固定无新论文消息；
- 任一待写论文缺少忠实中文摘要；
- 任一待写论文的关键词不合法；
- 写入响应无法确认唯一 `record_id`。
