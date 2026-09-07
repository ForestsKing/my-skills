---
name: paper-lark-reader
description: 阅读学术论文 PDF，生成结构化中文论文笔记，围绕论文追问和修订笔记，并将论文笔记、PDF 与索引记录归档到飞书论文知识库。 | Read academic paper PDFs, generate structured Chinese paper notes, discuss and revise notes, and archive notes, PDFs, and index records into a Lark paper knowledge base.
---

# Paper Lark Reader

当用户正在处理学术论文，并需要建库、论文阅读、结构化笔记、追问讨论、笔记修订、上传归档或用户触发的研究画像更新时，使用本 skill。

本 skill 的飞书命令以当前环境的 `--help` / `schema` 为准；执行写入前必须确认命令参数形态，并在遇到 help 与实际行为不一致时优先使用已验证命令形态。

## 触发范围

用户提出以下需求时触发：

- 初始化、检查或维护飞书论文知识库。
- 阅读、精读、总结或分析学术论文 PDF；默认等价于生成结构化本地论文笔记。
- 生成结构化中文论文笔记。
- 解释论文的方法、数据、实验、结论、局限或启发。
- 讨论论文与用户研究方向的关系。
- 将追问、纠错或启发写回已有论文笔记。
- 上传或归档论文笔记、PDF 和 Base 索引记录。
- 生成或更新研究画像文档 `研究概述`。

以下情况不要触发：

- 普通 PDF、OCR 或文档处理，除非用户明确进入学术论文阅读流程。
- 普通飞书 Wiki、Base、Doc 管理，除非目标属于论文知识库流程。
- 泛泛找论文或文献检索，除非后续进入阅读、笔记、修订或归档。

当用户给出论文 PDF 并要求“阅读、精读、总结、分析、帮我看下”等首次阅读动作时，不得降级为仅聊天摘要；必须进入论文阅读流程并默认生成本地 Markdown 笔记。只有用户明确要求“只要聊天总结”“不生成笔记”“离线口头总结”时，才可不生成笔记，并必须说明未使用飞书标签、出版选项和研究画像。

如果意图不明确，先确认用户是否需要“论文阅读与飞书论文库”工作流。

## 依赖技能

涉及飞书操作时按需使用：

- `lark-shared`：认证、身份、scope 和权限问题。
- `lark-wiki`：知识库空间和 Wiki 节点。
- `lark-doc`：Docx 读取、更新和 Markdown 写入。
- `lark-base`：Base 表、字段、视图、记录、选项和附件。
- `lark-drive`：文档标题修正和文件元信息处理。

`scripts/` 中的 Python 命令只处理本地文件，不执行飞书写入。

## 工作流路由

执行前必须读取匹配的 command 文件。只有 command 指向共享规则，或确实需要共享规则时，才读取 `references/`。

| 用户意图 | 读取文件 | 共享规则 |
|---|---|---|
| 初始化论文知识库 | `commands/kb-init.md` | `references/lark-workflows.md`、`references/command-pitfalls.md` |
| 阅读/总结/分析 PDF 论文，默认生成 Markdown 笔记 | `commands/paper-read.md` | `references/note-writing-guide.md`、`references/publication-policy.md`、`references/command-pitfalls.md` |
| 回答追问或讨论启发 | `commands/paper-discuss.md` | 需要笔记结构时读取 `references/note-writing-guide.md` |
| 根据讨论或纠错修订笔记 | `commands/note-revise.md` | `references/note-writing-guide.md` |
| 生成或更新 `研究概述` | `commands/profile-update.md` | `references/lark-workflows.md`、`references/command-pitfalls.md` |
| 上传归档笔记、PDF 和 Base 记录 | `commands/kb-upload.md` | `references/lark-workflows.md`、`references/note-writing-guide.md`、`references/command-pitfalls.md` |

## 全局规则

1. 执行任何 `lark-cli` 命令前，必须先读取 `references/command-pitfalls.md`。
2. 本 skill 中的相对路径均以 skill 根目录为基准；skill 根目录是包含 `SKILL.md` 的 `paper-lark-reader/` 目录。读取或写入配置时，必须使用 `<SKILL_ROOT>/config/defaults.json`，不要在用户项目目录新建或读取同名文件。
3. 除纯讨论外，依赖飞书论文库的流程开始前必须检查 `lark-cli`、`<SKILL_ROOT>/config/defaults.json` 和目标库可访问性。
4. 论文阅读、精读、总结或生成笔记默认依赖飞书只读上下文；生成笔记前必须读取 Base `标签` 和 `出版` 字段已有选项，并读取 `研究概述`。不需要为阅读流程读取已有论文索引记录或 `年份` 选项。
5. 本地只缓存面向用户的知识库配置；不要把字段 ID、选项 ID、标签、出版或年份作为长期事实缓存。
6. 初始化时若存在同名知识库，必须暂停、展示复用风险，并等待用户明确选择候选或改用新名称。
7. 缺少 `lark-cli`、未登录、配置缺失或目标库不可访问时，依赖库的流程必须停止；阅读流程只有进入离线确认门并获得用户确认后，才可改为本地离线笔记。
8. 第一次阅读论文在完成飞书标签、出版选项和研究画像读取后，默认生成本地 Markdown 笔记；检测到已有本地笔记时，必须先展示将更新或覆盖的影响，获得用户确认后才可修改既有笔记。
9. 讨论论文时只回答并记录候选补充；不得自动修改本地笔记、云端文档、Base 记录或研究画像。
10. 研究画像独立于读论文和上传主线；只有用户明确要求生成或更新画像时，才执行 `profile-update.md`。
11. 写入 Base 前，必须先生成并校验 Markdown 笔记。
12. 上传时，`Title`、`Abstract`、`标题`、`摘要` 必须从笔记 `## 元数据` 表复制。
13. `标题` 必须是 `Title` 的忠实中文翻译；`摘要` 必须是 `Abstract` 的忠实中文翻译，不能写成总结或评价。
14. 飞书论文库结构固定：知识库、Base `论文索引`、表 `数据表`、默认视图 `概览`、父文档 `论文笔记`、画像文档 `研究概述`。
15. `论文笔记` 父文档必须包含真实的飞书子文档列表组件，并用 `<folder_manager>` 验证。
16. 论文子文档标题不能保持为 `Untitled`；写入后必须修正并回读验证标题。
17. 主 PDF 只上传到 Base 附件字段一次，文件名固定为 `paper.pdf`。
18. 新增 `标签`、`出版` 或 `年份` 选项前，必须展示理由并获得用户确认。
19. 默认联网搜索只用于出版元数据核验；除非用户明确要求，不用于扩写论文内容。
20. 任何可能造成信息损失的操作都必须先展示影响并获得用户明确确认，包括覆盖、更新、删除、移动、合并、清理、重构、重新上传、同步写回、重命名已有资源，或改变已有本地/云端内容。

## 确认门

以下动作必须先暂停并获得用户确认：

- 复用同名知识库。
- 论文阅读流程无法读取飞书 `标签`、`出版` 选项或 `研究概述`，需要离线继续生成本地笔记。
- 修改、覆盖或重写已有本地 Markdown 笔记。
- 云端已有同题论文记录或子文档，需要更新而不是新增。
- 覆盖已有 `研究概述`。
- 新增 `标签`、`出版` 或 `年份` 选项。
- 覆盖、更新、重命名或同步已有飞书文档、Base 记录、字段、附件或链接。
- 删除、移动、合并、清理或重构已有本地或飞书资源。

检测到云端重复论文时，先提示重复并等待确认；确认后走更新流程。只有用户明确要求新增时，才新增云端记录或子文档。

## 本地命令

飞书工作流由执行者调用 `lark-*` skills 完成。Python 命令只处理本地文件：

```bash
python3 scripts/paper_lark_cli.py check [--output FILE]
python3 scripts/paper_lark_cli.py paper-prep --pdf paper.pdf [--doi 10.xxxx/xxx] [--write-intermediates] --output paper.context.json
python3 scripts/paper_lark_cli.py extract paper.pdf --output paper.text.json
python3 scripts/paper_lark_cli.py metadata paper.text.json --output paper.metadata.json
python3 scripts/paper_lark_cli.py lookup --title "Paper Title" --doi "10.xxxx/xxxxx"
python3 scripts/paper_lark_cli.py infer --metadata paper.metadata.json [--publication paper.publication.json] --output paper.options.json
python3 scripts/paper_lark_cli.py title "paper title" --title-case
python3 scripts/paper_lark_cli.py note-check paper.paper-note.md
python3 scripts/paper_lark_cli.py validate-tree .
```

## 输出文件

- PDF 正文抽取：`*.text.json`
- 统一论文上下文：`*.context.json`
- 元数据抽取：`*.metadata.json`
- 选项推断：`*.options.json`
- 论文笔记：`*.paper-note.md`，通常与源 PDF 同目录
- 研究画像文件：Markdown，通常命名为 `研究概述.md`

## 安全边界

只有通过相应飞书回读命令验证后，才能声称字段、视图、子文档列表、标题、附件或 Base 记录已经创建、清理或更新。
