---
name: summarize
description: "为长文本、文档、网页、OCR 识别稿、音频转录稿、视频文案提取稿等自动生成摘要、提取要点与关键词，支持自定义摘要长度。优先本地离线处理（零依赖、跨平台），并支持「云端取方法、本地处理信息」以省 TOKEN、护隐私；可与 desensitization-sop 协同完成脱敏/处理/回填/复核闭环。当用户要求「总结/摘要/概括/提炼要点/提取关键词/归纳」任意形态的长内容时，应使用本技能。"
version: "1.0.0"
agent_created: true
pip_dependencies: ["jieba"]
---

# 智能摘要技能（summarize）

> 版本 v1.0.0 · 署名 hzh.opc（由 WorkBuddy 协助实现） · 兼容智能体：WorkBuddy / Claude / Codex / OpenClaw 等 · 跨平台：Windows / macOS / Linux。

## 定位与目标

自动为长内容生成摘要、提取要点与关键词，让用户在更少时间内理解信息、减少冗余干扰。两条核心诉求：

1. **把正确的（紧凑）中间结果交给智能体/云端处理**，在取得正确结果的前提下节约 TOKEN。
2. **把摘要交给用户阅读**，减少冗余信息干扰。

两条设计铁律：
- **本地优先**：完整的本地处理能力（离线、零依赖）优先；云端仅用于「取方法/做抽象」，原始长文默认不出本机。
- **源文忠实（展开优先索引原文，补全须标记）**：对摘要做**后续处理**（展开 / 细化 / 追问 / 多语翻译 / 要点沉淀等）时，若需补充细节或溯源，必须先在**原文**中通过索引、定位、回查取用相关片段；**默认不脱离原文联网搜索或引用外部资料**。仅当原文确实不足以满足本次需求时方可联网补全，且须明确区分**原文内容 / 联网补全内容 / 处理结果**三类，不得让外部内容混入看似原文。任何展开内容都应能标回具体原文句 / 段落。

## 何时使用

- 用户要求「总结 / 摘要 / 概括 / 提炼要点 / 提取关键词 / 归纳」长文本、文档、网页、OCR 稿、音视频转录/文案提取稿。
- 用户希望缩短阅读时间、去除冗余、抓住核心结论。
- 需要在离线环境或对隐私敏感的场景下做摘要。

## 支持的信息形态与取文方式

> 本技能**只消费纯文本**：所有「非文本输入 → 文本」的环节都通过外部协同技能完成。因此外部技能缺失只影响「能否获取文本」，不影响「摘要」本身——拿到文本即可摘要，拿不到则明确降级而非崩溃（详见下方「协同技能检测、对接与容错」）。

| 形态 | 取文方式（动态对接，见「协同技能检测、对接与容错」） |
|---|---|
| 直接文本（粘贴/对话） | 直接使用 |
| `.txt` / `.md` 文件 | `Read` 读取或 `summarize.py <文件>` |
| `.docx` / `.pdf` | 检测 `document_text` 能力：命中则调用该技能落地文本；缺失则 `ask` 降级（请用户导出 .txt/.md） |
| 网页 URL | 检测 `web_fetch` 能力：命中则调用，否则回退内置 `WebFetch` 工具（仍需过脱敏协同） |
| 图片 / 扫描件 | 检测 `ocr` 能力：命中则调用 OCR 技能转文字；缺失则 `ask` 降级 |
| 音频 | 检测 `speech_transcription` 能力：命中则转文字；缺失则 `ask` 降级 |
| 视频 | 检测 `video_transcript` 能力：命中则转文字/字幕；缺失则 `ask` 降级 |

## CLI 用法（S1 便携版：不经过智能体、直接命令行）

> 若你是**直接拿本技能脚本在终端用**（S1 便携版，不通过智能体加载），本节可快速上手。所有脚本**纯标准库、Python 3.8+**，Windows / macOS / Linux 通用，无需安装任何第三方包即可运行（安装 `jieba` 仅用于提升中文分词质量，可跳过）。

### 快速开始（最常用）

```bash
# 1) 本地摘要 + 关键词（零依赖，开箱即用）
python3 scripts/summarize.py 输入.txt --length 5 --keywords 8 --format md

# 2) 一句话核心结论
python3 scripts/summarize.py 输入.txt --tldr

# 3) 带原文溯源标注（每句标回「见原文第P段·句S」）
python3 scripts/summarize.py 输入.txt --cite --format txt

# 4) 质量评估（压缩比 / 关键词覆盖 / 综合评分 0~100）
python3 scripts/summarize.py 输入.txt --eval --format json

# 5) 可选增强：安装 jieba 提升中文分词（不装也自动回退内置分词、不报错）
./install.sh
```

### 脚本一览（13 个，均纯标准库、零依赖）

| 脚本 | 用途 | 关键参数 |
|---|---|---|
| `summarize.py` | **核心**：抽取式摘要 + 关键词 + 质量评估 | `--length/--ratio/--chars`、`--cite`、`--tldr`、`--brief`、`--eval` |
| `compare.py` | 本地 × 云端摘要对比 + 改进建议 | `--local`、`--cloud`、`--feedback` |
| `skill_bridge.py` | 协同技能检测（扫描本机已装技能能力） | `--map`、`--exclude summarize`、`--cap`、`--save-cache` |
| `diff_summary.py` | 两份文档差异 / 变更摘要 | `--threshold` |
| `batch_summary.py` | 目录批量摘要 + 索引页 | `--length`、`--out` |
| `consistency_check.py` | 摘要-原文一致性自检（防幻觉） | `--original`、`--summary`、`--threshold` |
| `pii_precheck.py` | 上云前 PII 预检 | `--categories`、`--no-context` |
| `hierarchical_summary.py` | 层级摘要（概览→要点→细节） | `--l2`、`--l3`、`--cite` |
| `structured_summary.py` | 结构化抽取（问答/列表/定义/表格） | `--mode` |
| `mindmap_import.py` | 思维导图反向导入 | `--re-summarize`、`--markmap` |
| `qa_router.py` | 多轮问答状态机 | `--session`、`--question` |
| `podcast.py` | 口播稿生成 | `--tts`、`--voice`、`--audio` |
| `spreadsheet.py` | 表格生成 / 解析 | `--format csv/html/md/xlsx`、`--from-json` |

- `summarize.py` / `compare.py` / `skill_bridge.py` 为**核心三脚本**；其余 10 个为**原生增强**（无需外部技能，默认不主动触发，用户要求时即用）。
- 每个脚本的完整参数：运行 `python3 scripts/<脚本>.py --help`，或见本文件第 4.8 节与 `DEVELOPMENT.md` §6。

## 处理流程（务必遵循）

### 0. 读配置
读取配置（搜索顺序：`<工作区>/summarize.config.yaml` → 本技能 `assets/summarize.config.yaml`）。
配置项含义见 `references/config.md`（按需 Read）。

### 0.5 检测协同技能并完成取文（健壮性关键环节）
按下方「协同技能检测、对接与容错」章节：先用 `skill_bridge.py --exclude summarize` 检测本机已安装能力；再按输入形态分派——命中则调用对应协同技能把输入转为纯文本，缺失则按 `fallback`（`ask`/`tool`/`local`）降级。**拿到纯文本后再进入第 1 步**；若某输入形态降级为 `ask` 且用户无法提供文本，则跳过该输入、不中断整体流程。

### 1. 本地优先：抽取式摘要 + 关键词（离线、零依赖）
运行本技能脚本（纯标准库，Windows/macOS/Linux 通用；**未安装 jieba 时自动回退内置分词，不报错**）：

> **依赖与安装（可选增强，现已支持「安装即默认启用」）**：本技能默认零第三方依赖；中文分词默认用内置二元/三元组，**安装 `jieba` 后自动启用、质量更高**。仓库已含 `requirements.txt` 与 `install.sh`——**安装技能后运行 `./install.sh` 即默认启用 jieba**（可选 `PYTHON=/path/to/python ./install.sh` 指定解释器，须与运行 `summarize.py` 的 python 一致）。未安装则自动回退内置分词，不报错。
```bash
PY=<受管 python3 绝对路径，或用系统 python3>
$PY <技能目录>/scripts/summarize.py <输入1> [<输入2> ...] \
    [--length N | --ratio R | --chars C] [--keywords K] \
    [--lang auto|zh|en] [--tone neutral|concise|professional|casual] \
    [--max-input-chars N] [--format json|md|txt] [--eval] [--brief] [--cite] [--tldr] [--out PATH]
```
- `<输入>`：一个或多个文本文件路径；或 `-` 表示读 stdin（多文档时每个位置独立）。多文档将跨文档统一提取关键词与候选句，产出联合摘要并标注 `[文档N]` 来源。
- 长度三选一：`--length`(句数) / `--ratio`(比例) / `--chars`(字数)。
- `--tone`：调节喂给云端模型的摘要语气（neutral/concise/professional/casual），影响 `brief.instruction`。
- `--max-input-chars N`：超长文本阈值（默认 200000）。输入超过该长度时**自动滑动窗口分块抽取后合并**，全程离线。
- `--eval`：输出质量评估（压缩比、关键词覆盖、综合评分 0~100，方法见 `references/quality-eval.md`）。
- `--brief`：**关键**。输出「关键词 + 候选句(含分值) + 结构骨架」的紧凑中间产物，仅此中间产物送云端——实现「云端取方法、本地处理信息」。
- `--cite`：摘要每句句末附**原文溯源标注**（`见原文第P段·句S`），落实「源文忠实」铁律，让每条摘要都能标回具体原文位置（见第 4.8 节 H）。
- `--tldr`：仅输出**一句话核心结论**（取打分最高句截断为单行），适合快读/标题场景（见第 4.8 节 I）。

### 2. 模式分支（由 `mode` 决定）
- **local**（默认）：第 1 步结果即最终摘要，直接呈现用户。原始文本全程不出本机。
- **cloud / hybrid**：用第 1 步的 `--brief` 中间产物提交云端大模型，要求其产出连贯的**抽象式**摘要（指出核心结论与要点），并明确「不要复述原文、不要引入候选句之外的未核实信息」。hybrid 额外保留本地副本用于对比。
  - 此步**仅上云 brief（紧凑中间产物），原始长文不上云**——省 TOKEN 且护隐私。
  - **遵守「源文忠实」铁律**：云端只允许基于 `brief` 候选句做抽象归纳，**不得为「展开/补全」而自行联网检索或引用外部资料**；用户后续要求展开时优先回原文索引，确需联网补全的按下方专节执行并明确标记【原文】/【联网补全】/【处理结果】。

### 3. 呈现与质量评估
- 向用户输出：摘要正文 + 关键词 +（可选）质量评估。
- 质量评估指标与评分见 `references/quality-eval.md`。
- 若用户要求「沉淀到知识库 / 出多语版本」，转入第 4.5 节的输出后协同分支（该分支默认不主动触发）。
- **隔离原则**：摘要正文是用户交付物，应独立、干净地呈现；质量评估 / 对比改进建议属诊断信息，篇幅较长时落盘（`feedback_dir` / 审计报告文件），对话内仅给结论与关键分数，**不与摘要正文混排、不把审计长文铺进对话**。
- **交付物参考样式**（面向最终用户，非技术用户可直接阅读，无需关心命令与脚本）：

```markdown
## 摘要

（摘要正文，每条要点可用一句原文支撑，需要溯源时附「见原文第 N 段」）

**关键词**：关键词1 · 关键词2 · 关键词3

**一句话核心**：（TL;DR 结论，可选）
```

> 质量评估、脱敏审计等诊断信息**不进入**上面的交付物，另见 `references/quality-eval.md`。

### 4. 云端结果对比与改进闭环（可选，建议开启）
若 `compare_cloud: true` 或曾走 cloud/hybrid，运行：
```bash
$PY <技能目录>/scripts/compare.py --local <本地摘要> --cloud <云端摘要> \
    [--original <原文>] [--format md] [--feedback <feedback_dir>/fb_YYYYMMDD.json]
```
- 产出关键词 Jaccard、本地独有/云端独有项、可执行改进建议。
- 改进建议落盘 `feedback_dir`，周期可打包反馈开发者（`feedback_email`，默认 `hzh.opc@foxmail.com`）。
- 依据建议迭代 `scripts/summarize.py` 的打分权重/停用词/候选词规则，使本地能力逐步逼近云端。

### 源文忠实：后续处理展开时必守（重要）

摘要是原文的「压缩投影」，不是独立知识源。当用户对摘要做**后续处理**（追问细节、要求展开某要点、要更长版本、要举原文例子、要翻译 / 沉淀时补充背景）时：

- **先看原文，再展开**：用原文的索引 / 段落定位 / 关键句回查，从原文抽取相关片段作为展开依据；展开内容必须能标回具体原文位置（如「见原文第 N 段 / 句子 X」）。
- **原文不足才联网补全**：默认**不**为「补全摘要」直接联网搜索或引用外部资料。仅当**原文确实不足以满足本次后续处理的需求**（如用户主动要求、或澄清歧义所需背景超出原文范围）时，方可联网补全。
- **联网补全须明确标记（三类分离）**：一旦执行联网补全，输出中必须清晰区分以下三类内容，不得混作一处、不得让外部内容看似出自原文：
  1. **【原文】**：来自原文、可溯源到具体句 / 段落的内容；
  2. **【联网补全】**：来自联网检索 / 外部资料的补充内容，附来源链接或出处，并标注获取时间；
  3. **【处理结果】**：基于以上两者得出的结论 / 综合判断，明确其分别依赖了哪些原文、哪些联网补全。
- 这与「本地优先 / 云端取方法」一致：扩充细节**优先以原文为权威来源**；联网补全只是原文不足时的受控补充，且全程可追溯。

### 隐性外发确认闸口（2026-09-04 政策细化 · 重要）

凡把内容送出本机的隐性外发动作（非用户明显意图的上云 / 第三方调用），执行前**必须用户确认，否则阻断**：

- **`podcast --tts`**：讲稿全文将送第三方 TTS（edge / openai / azure）语音合成。运行 `podcast.py` 时由 `skill_bridge.request_external_confirmation` 触发确认闸口——先本地 PII 预检（命中仅增强提示），再要求确认；**未确认按安全默认阻断（exit 3）**，口播稿仍照常生成。
- **确认语义（confirm-or-block）**：`OFFICE_KIT_EXTERNAL_CONFIRM=allow` → 放行（agent 已在对话中代用户确认）；`=deny` → 阻断；未设且交互终端（CLI 用户）→ 提示 `y/N`；未设且非交互（agent / 管道调用）→ 安全默认阻断。
- **agent 调用契约**：agent 在触发 `--tts` / 联网补全 / 翻译等隐性外发前，**须先以 AskUserQuestion 向用户确认**；用户同意后以 `OFFICE_KIT_EXTERNAL_CONFIRM=allow` 运行组件，否则不触发外发。显式外发（用户主动 `tencent-doc` 上云等）按套件政策不主动脱敏，由用户与平台负责。

## 与「协同技能」检测、对接与容错（健壮性核心）

> **设计原则**：本技能**不假定任何协同技能已安装**。开始处理前先动态检测本机/工作区已安装的技能能力，按检测结果决定取文路径与上云前脱敏；任一能力缺失时按 `fallback` 策略降级，**绝不因依赖缺失而报错中断**。检测基于**关键词泛匹配** SKILL.md 的 name/description/tags，**不限定具体技能名**——因此无论用户安装的是 `desensitization-sop`、自研脱敏技能，还是任意第三方 OCR / 语音 / 视频技能，都能被识别并对接（"非限定本机已安装技能"）。

### 1. 协同技能检测（用 skill_bridge.py）

调用零依赖检测脚本（扫描用户级 `~/.workbuddy/skills` 与项目级 `./.workbuddy/skills`，按 `assets/capabilities.json` 关键词泛匹配）：
```bash
PY=<受管 python3 绝对路径，或用系统 python3>
SKILL_DIR=<技能目录>
# 全量检测（txt 易读）
$PY $SKILL_DIR/scripts/skill_bridge.py --map $SKILL_DIR/assets/capabilities.json --exclude summarize --format txt
# 单能力查询（exit 0=可用 / 1=缺失，便于条件分支）
$PY $SKILL_DIR/scripts/skill_bridge.py --exclude summarize --cap ocr --quiet && echo 有OCR || echo 无OCR
```
- `--exclude summarize`：**必须**。排除调用方自身，避免本技能描述中的「输入形态」被误判为自身提供该能力。
- 命中结果给出 `skill`（目录名）、`path`、`score`、以及 `alternatives`（同能力下的其它候选技能）。
- 能力清单与候选关键词定义在 `assets/capabilities.json`（数据驱动、可扩展，见第 5 节）。

### 2. 协同矩阵（能力 → 用途 → 对接方式 → 缺失降级）

| 能力 | 用途 | 命中后对接方式 | 缺失降级 `fallback` |
|---|---|---|---|
| `desensitization` | 上云前脱敏闭环 | 用 **Skill 工具**加载该技能并执行脱敏/回填/复核 | `local`：仅本地处理；强制上云只送 `brief` 并提示风险 |
| `ocr` | 图片/扫描件转文字 | 用 **Skill 工具**加载该 OCR 技能产出文本 | `ask`：请用户贴文本或安装 OCR 技能 |
| `speech_transcription` | 音频转文字 | 用 **Skill 工具**加载该语音技能产出文本 | `ask`：请用户提供文字稿 |
| `video_transcript` | 视频转文字/字幕 | 用 **Skill 工具**加载该视频技能产出文本 | `ask`：请用户提供文字稿/字幕 |
| `document_text` | docx/pdf 落地文本 | 用 **Skill 工具**加载该文档技能（如 `tencent-local-office-edit`） | `ask`：请导出 .txt/.md |
| `web_fetch` | 网页抓文本 | 用 **Skill 工具**加载该技能；未命中则回退内置 `WebFetch` 工具 | `tool`：回退 `WebFetch`（仍过脱敏协同） |
| `knowledge_base` | 摘要/要点沉淀进知识库 | 用 **Skill 工具**加载该技能，把「摘要+要点+来源」入库（见第 4.5 节） | `local`：沉淀到本地 `./要点沉淀/YYYYMMDD.md` |
| `translation` | 多语摘要 / 翻译 | 用 **Skill 工具**加载该技能，对摘要做目标语翻译（见第 4.5 节） | `tool`：仅对 brief/短摘要送云端翻译，原始长文不上云 |
| `rag` | 基于原文的问答式展开（检索增强/局部精准问答） | 用 **Skill 工具**加载 RAG 技能，在**原文**上建索引做溯源式追问（见第 4.7 节） | `local`：本技能「源文忠实」索引回查即轻量 RAG，按关键词在原文取片段 |
| `search` | 受控联网补全（外部补充） | 用 **Skill 工具**加载搜索技能；联网补全须按三段标记（见第 4.7 节） | `tool`：回退内置 `WebSearch`，仍须三段标记 |
| `mindmap` | 摘要要点可视化思维导图 | 用 **Skill 工具**加载脑图技能产出导图（见第 4.7 节） | `local`：输出层级要点大纲（md/mermaid），可导入脑图工具 |
| `diagram` | 摘要结构/流程可视化（流程图/架构图/时序图等） | 用 **Skill 工具**加载图示技能产出结构化图（见第 4.7 节） | `local`：输出 mermaid 代码块（flowchart/sequence/class）或 drawio 文本 |
| `graph` | 摘要要点关系图谱/知识图谱（实体-关系网络） | 用 **Skill 工具**加载图谱技能抽取实体关系并可视化（见第 4.7 节） | `local`：输出 mermaid graph（graph TD）或 markdown 邻接表 |
| `entity_extract` | 摘要/原文实体·关系抽取（NER/信息抽取） | 用 **Skill 工具**加载抽取技能产出实体-关系清单（见第 4.7 节） | `local`：用关键词/正则做轻量实体候选列表（实体—类型—出现句） |
| `ppt` | 摘要/要点生成演示文稿（pptx/幻灯片） | 用 **Skill 工具**加载演示文稿技能渲染成 PPT（见第 4.7 节） | `local`：输出结构化 PPT 大纲（每页标题+要点+备注的 markdown） |
| `chart` | 摘要数据/对比项渲染图表（柱状/折线/饼图等） | 用 **Skill 工具**加载图表技能渲染（见第 4.7 节） | `local`：输出 markdown 数据表+趋势文字，或 mermaid xychart |
| `qa_router` | 把摘要/要点路由到合适的问答技能做多轮追问与分派（基于原文） | 用 **Skill 工具**加载问答路由技能做问题分发/多轮问答（见第 4.7 节） | `local`：用「源文忠实」索引/回查 + `--cite` 在原文做局部问答 |
| `podcast` | 把摘要/要点转为播客/口播音频（文本→语音），放大可听性 | 用 **Skill 工具**加载音频/播客生成技能（见第 4.7 节） | `local`：输出口播稿（纯文本/markdown 分级讲稿），可导入 TTS 工具；可选 `--tts` 直接合成音频 |
| `spreadsheet` | 把摘要中的结构化数据/对比项生成或解析表格（电子表格/CSV/多维表） | 用 **Skill 工具**加载表格处理技能（见第 4.7 节） | `local`：输出 markdown 表格/CSV（可由 `structured_summary.py` 预抽取）；可选 `--format xlsx` 导出 .xlsx |

> 对接外部技能的标准动作：用 **Skill 工具**加载其 `SKILL.md` → 遵循其流程产出文本 → 把文本作为本技能 `summarize.py` 的输入。**本技能脚本只消费纯文本**，因此外部技能缺失只阻断「取文」、不阻断「摘要」。

### 3. 取文分派（按输入形态）

1. 直接文本 / `.txt` / `.md` → 直接用 `summarize.py` 处理（无需任何外部技能）。
2. 图片/扫描件 → 检测 `ocr`：可用则调用 OCR 技能转文字；缺失 → `ask` 降级（不强行处理二进制）。
3. 音频 → 检测 `speech_transcription`：可用则转文字；缺失 → `ask` 降级。
4. 视频 → 检测 `video_transcript`：可用则转文字；缺失 → `ask` 降级。
5. `.docx` / `.pdf` → 检测 `document_text`：可用则落地文本；缺失 → `ask` 降级。宿主若自带文档处理工具/插件（如 WorkBuddy 的 `tencent-local-office-edit`、`tencent-docs-routing` 等，位于插件/连接器目录、不经 `skill_bridge` 扫描），也可直接用于落地文本，取文结果同样只作 `summarize.py` 的输入。
6. 网页 URL → 检测 `web_fetch`：可用则调用，否则回退 `WebFetch` 工具。抓取内容可能含敏感信息，须过第 4 节脱敏协同。

### 4. 脱敏协同（通用检测，零耦合）

> **零耦合保证**：本技能的脚本（`scripts/summarize.py`、`scripts/compare.py`、`scripts/skill_bridge.py`）**不导入、不调用**任何外部技能。脱敏协同完全在「智能体层」按条件执行——外部技能缺失时脚本天然不会出错。
> **未检出脱敏技能 = 正常降级，非环境异常**：在「仅组件」场景（S4）下若本机未安装任何脱敏技能（如 `desensitization-sop`），`skill_bridge.py --cap desensitization` 会返回「缺失」，此时**自动降级、不报错、不中断**——脱敏由智能体层按下方 `absent` 分支处理（本地处理，或提示用户确认上云风险）。这是**预期行为**，智能体**不应据此误判为环境异常或报错**。

在执行任何上云操作前，用 `skill_bridge.py` **泛匹配**检测脱敏能力（兼容任意脱敏技能名，而非硬编码 `desensitization-sop` 目录）：
```bash
$PY $SKILL_DIR/scripts/skill_bridge.py --exclude summarize --cap desensitization --quiet \
  && echo "脱敏可用: $($PY $SKILL_DIR/scripts/skill_bridge.py --exclude summarize --cap desensitization | python3 -c 'import sys,json;print(json.load(sys.stdin)["skill"])')" \
  || echo "脱敏缺失"
```
- **absent（未安装）**：跳过所有脱敏步骤，直接走本地处理（`mode=local` 默认安全，原始文本不出本机）。若用户要求 `cloud`/`hybrid`，仅上云 `summarize.py --brief` 产出的紧凑中间产物，并明确提示用户：未做脱敏、存在隐私风险，需用户自行确认。**此时「提醒」须有实际兜底支撑**——外发前先跑本技能内置 `pii_precheck.py` 做本地 PII 预检（见 §4.8 M），把命中清单与脱敏预览一并呈现，而非空口提示。
- **available（已安装）**：用 **Skill 工具**加载该脱敏技能，**「已装即必扫」为代码级强制（「仅组件场景安全审计」P0-①）**——凡外发（含隐性外发：翻译/TTS/联网补全/知识库沉淀，见 §4.5/§4.7/§4.8）前，必须真跑该技能的 `scan`/`run` 闸门，未扫即阻断，不得靠文字约定自觉跳过。按其上云前/后闭环执行「脱敏、处理、回填、复核」：
  1. **上云前**：凡要把任何内容送云端模型，先跑该技能的「输入检测闸门 → 脱敏 → 上云前自查 → 用户确认」。仅可上云的是脱敏副本或 `brief` 紧凑中间产物。
  2. **本地处理豁免**：若 `mode=local` 且声明「仅本地处理·无需外发」，走该技能的「本地处理豁免（三条护栏）」——原始数据留本机、不脱敏、绝不外发。
  3. **任务后**：按该技能模板**自动生成脱敏审计文档并写入文件**（`desensitize_audit.md` / `06_审计与回填/审计记录.md`），原始文件与映射表永远留本地且分离。
     - **审计隔离铁律（必须遵守）**：脱敏审计属「审计类长文本」，按 SOUL.md 常驻铁律**一律写入文件**；对话内**仅给一句话结论 + 文件路径**（如「✅ 脱敏审计已生成：<路径>」），**严禁把整篇审计原文铺进对话与摘要回复混淆**。单次任务对话中审计相关内容篇幅 ≤ 任务对话 1/3。
  4. **回填/复核**：云端结果若需还原映射（去标识回填），在本地完成，云端不留敏感原文。

> 红线：脱敏副本可上云，原始文件与映射表留本地且分离；自动化识别非 100%，禁止「一键脱敏即上云」，必须人工复核。

### 4.5 输出后协同：要点沉淀（knowledge_base）与多语摘要（translation）

这两类能力发生在**摘要产出之后**（而非取文阶段），用于放大摘要价值。同样先经 `skill_bridge.py` 检测，命中即用 **Skill 工具**加载对应技能对接，缺失则按 `fallback` 降级。

**A. 要点沉淀 knowledge_base**
- **available**：用 **Skill 工具**加载该知识库/笔记技能，把 `summarize.py` 产出的「摘要正文 + 关键词 + 来源路径/链接」作为一条结构化要点写入（建议带上 `来源: <原始文件名或 URL>` 与 `生成于: <日期>`，便于回溯）。若该技能要求先建库/建空间，提示用户或按其特征词自动匹配。
- **absent（fallback=local）**：本技能在本工作区创建 `./要点沉淀/YYYYMMDD.md`，写入同样的「摘要 + 要点 + 来源」纯 markdown。**这样即使用户未装任何知识库技能，要点也不会丢失，日后可一键导入 Obsidian / Notion / 语雀等任意知识库**。

**B. 多语摘要 translation**
- **available**：用 **Skill 工具**加载该翻译技能，对（本地或云端的）摘要做目标语言翻译；可询问用户目标语言。原始长文不上云，仅翻译短摘要。**翻译属隐性外发**：送云端翻译前，已装脱敏技能则必先 `scan` 未扫即阻断；未装则跑 `pii_precheck.py` 本地预检 + 显式提醒。
- **absent（fallback=tool）**：若用户确实需要多语摘要，仅把 `--brief` 紧凑中间产物或本地短摘要送云端翻译（**原始长文仍留本机**），并提示未做脱敏的隐私风险；若用户不需要翻译，则跳过。**外发前同样须 `pii_precheck.py` 预检兜底**，不得裸发。

> 这两条分支与主流程解耦：用户不要求沉淀/翻译时，即使对应技能可用也**不主动触发**，避免副作用。

### 4.6 安装新的协同技能后：及时刷新检测（更新设置）

本技能对协同能力的检测**默认每次调用都 live 重扫** `~/.workbuddy/skills` 与 `./.workbuddy/skills`，因此用户**新安装的协同技能在下一轮对话/调用即自动生效**，无需手动改配置。为便于把「能力→技能」映射固化成可读的协同设置快照，并提供显式刷新入口，可用 `--save-cache`：

```bash
PY=<受管 python3>
SKILL_DIR=<技能目录>
# 安装/卸载任意协同技能后，刷新映射快照（写入 assets/capabilities.detected.json）
$PY $SKILL_DIR/scripts/skill_bridge.py --map $SKILL_DIR/assets/capabilities.json \
    --exclude summarize --save-cache --format txt
# 下次需要加速时读缓存（缓存缺失自动回退 live）
$PY $SKILL_DIR/scripts/skill_bridge.py --exclude summarize --use-cache --format txt
```

- `--save-cache` 产出的 `capabilities.detected.json` 即本技能的**协同设置快照**：记录每个能力命中了哪个技能（含 score）、缺失时走哪种 `fallback`。它既能作为审计/排查依据，也是「用户装了新技能后更新设置」的显式动作。
- 智能体在「处理流程 0.5」每次仍走 live 重扫；`--use-cache` 仅在明确要跳过重扫、且已 `save-cache` 过时作为加速手段。

### 4.7 输出后协同：问答 / 补全 / 可视化 / 抽取 / 演示 / 图表（rag · search · mindmap · diagram · graph · entity_extract · ppt · chart）

这些能力同样发生在**摘要产出之后**，用于放大摘要的「可探索性 / 可用性 / 可呈现性 / 可结构化性」。先经 `skill_bridge.py` 检测，命中即用 **Skill 工具**加载对接，缺失则按 `fallback` 降级。与主流程解耦：用户不要求时即使技能可用也**不主动触发**。

**C. 基于原文的问答式展开 rag（检索增强 / 局部精准问答）**
- **available**：用 **Skill 工具**加载 RAG 技能，把摘要在**原文**上建索引，让用户就摘要要点做「溯源式」追问（问某要点在原文哪、原文怎么说的）。RAG 检索范围必须是**原文**，与「源文忠实」原则一致。
- **absent（fallback=local）**：本技能「源文忠实」的索引 / 定位 / 回查机制即轻量本地 RAG——用关键词 / 句在原文中精准取片段，直接回答局部追问，无需外部 RAG 技能。

**D. 受控联网补全 search**
- **available**：用 **Skill 工具**加载搜索技能做外部补全。
- **absent（fallback=tool）**：回退内置 `WebSearch` 工具。
- **无论 available / absent，凡联网补全必须严格按「源文忠实」专节执行三段标记**：【原文】可溯源句 / 段落 ·【联网补全】附来源链接 / 出处 + 获取时间 ·【处理结果】分别依赖了哪些原文与补全；外部内容**不得混入看似原文**。**默认不联网**，仅当原文确实不足以满足本次后续处理需求时才走此分支。
- **外发前约束（search 属隐性外发）**：搜索 query 若含敏感原文同样外发——送 search 前，已装脱敏技能则必先 `scan`；未装则对 query 做 `pii_precheck.py` 预检，命中敏感项须先脱敏/替换再发，不得把敏感原文直接塞进 query。

**E. 要点可视化 mindmap（含反向导入）**
- **available**：用 **Skill 工具**加载脑图技能，把「摘要 + 层级要点」渲染为思维导图 / 结构化脑图。
- **absent（fallback=local）**：本技能直接输出带层级的要点大纲（markdown 缩进或 mermaid 代码块），用户可一键粘贴进 markmap / XMind / 语雀等任意脑图工具，**无需外部技能**。
- **反向导入（原生脚本 `mindmap_import.py`，见第 4.8 节 P）**：用户从脑图工具导出的大纲（markdown 标题层级 / 嵌套列表 / mermaid `mindmap` 块）可**反向导入**回本技能——解析为带层级的节点树，输出嵌套大纲 / 树状 JSON / 展平文本，并可选 `--re-summarize` 把展平文本喂回 `summarize.py` 引擎还原成摘要。这是「摘要→脑图」的**双向闭环**，让脑图也能重新成为可摘要、可检索、可追问的文本。

**F. 结构/流程可视化 diagram**
- **available**：用 **Skill 工具**加载图示技能，把摘要中的流程 / 结构 / 架构渲染为流程图 / 时序图 / 架构图 / 类图等。
- **absent（fallback=local）**：本技能直接输出 mermaid 代码块（`flowchart` / `sequence` / `class`）或 drawio 文本，用户可在任何支持 mermaid 的渲染器（如 markmap / Typora / VS Code 插件）或 drawio 中预览，**无需外部技能**。

**G. 关系图谱 graph（实体-关系网络）**
- **available**：用 **Skill 工具**加载图谱 / 知识图谱技能，从「摘要 + 原文」抽取实体与关系，构建节点-边可视化（知识图谱 / 关系网络）。
- **absent（fallback=local）**：本技能直接输出 mermaid `graph TD` 代码块或 markdown 邻接表（实体 → 关系 → 实体），标注要点之间的关联，用户可一键导入 neo4j / 图数据库 / 可视化工具，**无需外部技能**。

**H. 问答路由 qa_router（基于原文的多轮追问分派 · 多轮状态机）**
- **available**：用 **Skill 工具**加载问答路由技能，把摘要要点拆为可追问的子问题，路由到合适的问答 / RAG 技能做多轮作答。
- **absent（fallback=local）**：本技能用「源文忠实」索引 / 定位 / 回查 + `--cite` 溯源标注，在**原文**上做局部问答——用户就摘要某要点提问时，按关键词在原文精准取片段作答并可标回具体句 / 段落，无需外部问答路由技能（与 `rag` 的本地兜底同源）。
- **多轮状态机（原生脚本 `qa_router.py`，见第 4.8 节 Q）**：在外部问答路由技能缺失时，本技能提供**本地多轮兜底**——用 JSON session 文件持久化每轮上下文，对追问自动做**指代消解**（结合上一轮 topic / 上下文，消解「那这个 / 它 / 为什么 / 举个例子」等代词），按关键词在原文精准取片段作答并附溯源标注；若问题疑似需要外部信息则标记 `needs_external` 并建议走 `search`（须三段标记）/ `rag`。纯本地、零依赖。

**I. 播客 / 口播音频 podcast（放大摘要可听性）**
- **available**：用 **Skill 工具**加载音频 / 播客生成技能，把摘要 / 要点转为播客或有声稿。
- **absent（fallback=local）**：本技能输出分级**口播稿**（markdown 讲稿：标题 + 要点 + 过渡语），用户可一键粘贴进任意 TTS / 播客工具生成音频，**无需外部技能**。
- **本地兜底（原生脚本 `podcast.py`，见第 4.8 节 R）**：在外部音频 / 播客技能缺失时，本技能直接把「原文 / 摘要」转为可播报讲稿——复用 `summarize.py` 抽取核心句作章节要点（不编造），组织为开场白 / 主体 / 结尾并附 `[停顿]` 标记，估算字数与口播时长，输出 markdown / 纯文本 / json，纯本地、零依赖；并支持 `--tts` 可选直接合成音频（edge-tts 免费 / openai / azure，均优雅降级）。

**J. 表格处理 spreadsheet（放大摘要可计算性）**
- **available**：用 **Skill 工具**加载表格处理技能，把摘要中的结构化数据 / 对比项生成 Excel / CSV / 多维表，或解析已有表格。
- **absent（fallback=local）**：本技能先用 `structured_summary.py` 预抽取结构化条目（问答 / 列表 / 定义 / 表格行），再输出 markdown 表格 / CSV 文本，用户可粘贴进 Excel / 飞书多维表，**无需外部技能**。
- **本地兜底（原生脚本 `spreadsheet.py`，见第 4.8 节 S）**：在外部表格技能缺失时，本技能把结构化条目转为 CSV（可直接粘贴进 Excel / 飞书多维表）、自包含 HTML（每类一段 `<table>`，浏览器打开即渲染）、或 markdown 表格；也支持读 `structured_summary.py --format json` 的产物续接，**无需外部技能、零依赖**；并支持 `--format xlsx` 经 openpyxl 生成真正 .xlsx 工作簿（未装则优雅降级）。

### 4.8 原生增强功能（溯源标注 / TL;DR / 差异摘要 / 批量索引 / 一致性自检 / PII 预检 / 层级摘要 / 结构化抽取 / mindmap 反向导入（含 markmap 渲染）/ qa_router 多轮状态机 / podcast 口播稿（可选 TTS 合成）/ spreadsheet 表格（可选 .xlsx 导出））

这些是本技能**内置**能力（由脚本直接实现，不依赖任何外部协同技能，纯本地、零依赖），用于放大摘要的「可核查性 / 快读性 / 可对比性 / 批量可用性 / 双向可探索性 / 多轮可问答性」。用户要求时即用，默认不主动触发。

**H. 溯源标注 `--cite`（落实「源文忠实」铁律）**
- 在 `summarize.py` 加 `--cite`：摘要每句句末自动附原文定位，格式 `（见原文第P段·句S）`（多文档时为 `（见第N篇·第P段·句S）`）。
- 定位来自抽取阶段记录的「全局句索引 → 段落号 / 句内序号」映射，纯本地即可溯源，**让每条摘要都能标回具体原文位置**，与第「源文忠实」专节一致。
```bash
$PY $SKILL_DIR/scripts/summarize.py <输入> --cite --format txt [--length N]
```

**I. 一句话 TL;DR `--tldr`**
- 在 `summarize.py` 加 `--tldr`：仅输出一句话核心结论（取打分最高的候选句截断为单行，≤80 中文字 / ≤140 英文字），适合快读 / 标题场景。
```bash
$PY $SKILL_DIR/scripts/summarize.py <输入> --tldr --format txt
```

**J. 差异 / 变更摘要 `diff_summary.py`（本地、零依赖）**
- 对「旧版 A」与「新版 B」做句级相似度比对（CJK 二元组 + 拉丁词 Jaccard），识别新增 / 删除 / 修改，输出变更日志 changelog。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/diff_summary.py A.txt B.txt [--format md|json|txt] [--out PATH] [--threshold F]
# 输出：相对旧版：新增 N 句、删除 M 句、修改 K 处；并分「➕新增 / ➖删除 / ✏️修改」列出
```
- 阈值：`--threshold`（默认 0.3）界定新增 / 删除；`[threshold, 0.85)` 区间判为「修改」（旧→新配对）。

**K. 批量目录摘要 + 索引 `batch_summary.py`（本地、零依赖）**
- 对目录下每个 `.txt/.md` 文件逐一摘要，汇总为带关键词的索引 markdown（与「多文档联合摘要」互补：联合是「合并为一份」，批量是「分别摘要 + 索引」）。
```bash
$PY $SKILL_DIR/scripts/batch_summary.py <目录> [--out index.md] [--length N] [--format md|json]
```
- 复用同目录 `summarize.py` 引擎；非文本文件自动跳过，单篇失败不中断整体。

**L. 一致性自检 `consistency_check.py`（守护「源文忠实」铁律，本地、零依赖）**
- 对「原文 + 摘要」逐句比对（CJK 二元组 + 拉丁词 Jaccard 句级相似度），判定摘要每句是否能在原文中找到支撑。不可追溯句（相似度 < 阈值）标为「疑似外部引入 / 幻觉」，须人工复核。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/consistency_check.py --original 原文.txt --summary 摘要.txt \
    [--format md|json|txt] [--out PATH] [--threshold F]
# 输出：verdict(consistent/inconsistent) + 可追溯/不可追溯计数与清单；exit 0=一致，非0=存在不可追溯句（可接入 CI / 自动门禁）
```
- 这是「源文忠实」铁律（D8）的**自动化守护**：任何把摘要交给云端做抽象 / 展开前，先用它核验摘要未引入原文外内容。

**M. 上云前 PII 预检 `pii_precheck.py`（隐私守门员，本地、零依赖）**
- 送云端前在本地用正则 + 词典模式扫描文本中的疑似 PII：手机号 / 邮箱 / 身份证 / 银行卡 / 网址 / 金额 / 疑似地址 / 疑似姓名，输出命中统计、上下文片段与**脱敏预览（mask）**。**不修改、不覆盖原文件**。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/pii_precheck.py <输入.txt> [-] [--format md|json|txt] \
    [--categories phone,email,idcard] [--out PATH]
# 输出：命中统计 + 明细（类别/风险/行号/原文/mask 预览）；exit 0=无 PII，非0=有 PII（可接入上云前自动门禁，建议配合脱敏协同做人工复核）
```
- 与 `desensitization` 协同呼应：脱敏技能缺失或仅送 `brief` 时，本工具帮助用户快速发现风险点，再决定上云范围。

**N. 层级摘要 `hierarchical_summary.py`（概览 → 要点 → 细节，本地、零依赖）**
- 复用 `summarize.py` 引擎生成多层嵌套摘要：L1 一句话核心（来自 `--tldr`）→ L2 核心要点 → L3 细节支撑句（可带 `--cite` 溯源）。便于结构化阅读与一键导入脑图 / 大纲工具。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/hierarchical_summary.py <输入.txt> [-] [--l2 N] [--l3 N] \
    [--cite] [--keywords K] [--format md|json|txt] [--out PATH]
# 输出：L1 概览 / L2 要点 / L3 细节 三级嵌套（md 默认带标题层级，json 含 l1/l2/l3/keywords）
```

**O. 结构化抽取 `structured_summary.py`（问答/列表/定义/表格，本地、零依赖）**
- 从文本启发式抽取结构化条目：**问答对**（问句 + 作答 / 「问：答：」成对）、**列表项**（`-`/`1.`/`（1）` 等）、**定义/要点说明**（短主语 + 冒号/破折号/「是指」）、**表格行**（markdown `|` 分隔）。与 `chart` / `entity_extract` 协同呼应。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/structured_summary.py <输入.txt> [-] \
    [--mode auto|qa|list|definition|table] [--format md|json] [--out PATH]
# 输出：按类型分组的结构化条目（md）或 items/stats（json）；可作为 spreadsheet / chart 协同的输入
```

**P. 思维导图反向导入 `mindmap_import.py`（脑图 / 大纲 → 嵌套结构，双向闭环）**
- 把「脑图 / 大纲」**反向导入**回摘要生态：解析 markdown 标题层级 / 嵌套列表 / mermaid `mindmap` 块，保留层级构建节点树，输出嵌套大纲（md）/ 树状结构（json）/ 展平文本（txt）。可选 `--re-summarize` 把展平文本喂回 `summarize.py` 引擎，还原成一份摘要。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/mindmap_import.py <脑图.md> [-] \
    [--format md|json|txt] [--re-summarize] [--length N] [--keywords K] [--out PATH]
# 输出：嵌套大纲 / 树(json) / 展平文本；--re-summarize 时追加「由脑图还原的摘要」
# 支持形态：# 标题层级、-/* 嵌套列表、```mermaid mindmap ... ``` 块（自动剥离 id[text] 等语法噪音）
```
- 这是 `mindmap` 协同能力（摘要→脑图）的**反向闭环**：用户从脑图工具导出的大纲也能重新成为可摘要、可检索、可追问的文本。
- **接 markmap 直接渲染**：加 `--markmap` 生成自包含 HTML（嵌入 markmap-autoloader），把节点树渲染为可交互思维导图，浏览器打开即见——实现「反向导入→直接渲染」闭环。查看时需联网加载 markmap 查看器（仅查看器来自 CDN，数据本地生成）。
```bash
$PY $SKILL_DIR/scripts/mindmap_import.py <脑图.md> --markmap [--title 标题] [--out 渲染.html]
# 输出：<脑图>.mm.html（自包含，浏览器打开即渲染交互脑图）
```

**Q. 问答路由多轮状态机 `qa_router.py`（本地、源文忠实、零依赖）**
- 在外部问答路由技能缺失时，本技能提供**本地多轮兜底**：用 JSON session 文件持久化每轮上下文，对追问自动做**指代消解**（结合上一轮 topic / 上下文），按关键词在原文（及可选摘要）精准取片段作答并附溯源标注；若问题疑似需要外部信息则标记 `needs_external` 并建议走 `search`（须三段标记）/ `rag`。每轮一次调用、复用同一 `--session` 文件即形成多轮。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/qa_router.py --session state.json --original 原文.txt \
    [--summary 摘要.txt] --question "..." [--k 3] [--format md|json|txt] [--out PATH] [--reset]
# 输出：本轮问答（依据原文的证据句 + 溯源标注 + 建议下一步）；session 文件持续写回，下轮复用即多轮
# 多轮示例：首轮 --question "量子计算是什么？" → 次轮 --question "它有什么风险？"（自动消解「它」=上一轮 topic）
```

**R. 播客 / 口播稿生成 `podcast.py`（本地兜底，零依赖；可选 TTS 合成）**
- 在外部音频 / 播客生成技能缺失时，本技能把「原文 / 摘要」转为可播报讲稿：复用 `summarize.py` 引擎抽取核心句作为章节要点（**不编造，全部来自原文**），组织为开场白 → 主体（每章标题 + 口播稿 + `[停顿]` 标记）→ 结尾（总结 + 行动号召），并估算总字数与口播时长（中文 ~220 字/分钟、英文 ~150 wpm）。输出 markdown 分级讲稿 / 纯文本口播稿（便于直接粘贴进 TTS）/ json。
- **可选直接合成音频（`--tts`）**：讲稿产出后，可用 `--tts` 把全文直接合成音频，无需手动粘贴进 TTS 工具。支持三类 provider，均以 import guard 优雅降级（**未装对应包 / 缺密钥时不崩溃，给出安装提示并退出，零依赖默认不受影响**）：
  - `edge` —— `edge-tts`，**免费、无需 API Key**（中文推荐 `zh-CN-XiaoxiaoNeural`）；
  - `openai` —— OpenAI TTS，需 `OPENAI_API_KEY`（或 `--api-key`），模型默认 `tts-1`；
  - `azure` —— Azure 语音服务，需 `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION`（纯标准库联网，无第三方包）。
- **`--tts` 是最隐蔽的隐性外发（讲稿全文直送第三方 TTS）**：合成前**必须**先过外发门禁——已装脱敏技能则必先 `scan`（未扫即阻断）；未装则先跑 `pii_precheck.py` 对讲稿全文做 PII 预检，命中敏感项须先脱敏/确认再合成，并对话内显式提示「讲稿全文将外发至 <provider>」。**不得未经扫描直接 `--tts` 合成**。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/podcast.py <输入.txt> [-] \
    [--title 主题] [--host 节目名] [--chapters N] [--keywords K] \
    [--format md|txt|json] [--out PATH] \
    [--tts none|edge|openai|azure] [--voice 语音名] [--audio 输出.mp3] \
    [--api-key KEY] [--region 区域] [--model tts-1]
# 输出：分级口播稿（md）/ 纯文本口播稿（txt，直接喂 TTS）/ 结构化（json）；附预计时长
# 示例：--tts edge --voice zh-CN-YunxiNeural（中文男声，免费）；--tts openai --voice nova
```

**S. 表格生成 / 解析 `spreadsheet.py`（本地兜底，零依赖；可选 .xlsx 导出）**
- 在外部表格处理技能缺失时，本技能把「原文 / 摘要」中的结构化数据转为电子表格可消费的形态：复用 `structured_summary.py` 的启发式抽取问答对 / 列表项 / 定义说明 / 表格行，输出 CSV（可直接粘贴进 Excel / 飞书多维表 / Numbers）、自包含 HTML（每类一段 `<table>`，浏览器打开即渲染）、或 markdown 表格。也支持读 `structured_summary.py --format json` 的产物续接（`--from-json`），**无需外部技能、零依赖**。
- **可选生成真正 .xlsx（`--format xlsx`）**：经 `openpyxl` 生成多 sheet 工作簿（每类数据一个表：问答对 / 列表项 / 定义说明 / 表格，表头加粗 + 自动列宽 + 单元格换行），可直接双击打开。**未安装 openpyxl 时优雅降级**：打印 `pip install openpyxl` 提示并退出，不影响 CSV/HTML/md 默认路径。
- 用法与输出：
```bash
$PY $SKILL_DIR/scripts/spreadsheet.py <输入.txt> [-] \
    [--from-json] [--mode auto|qa|list|definition|table] \
    [--format csv|html|md|xlsx] [--out PATH]
# 输出：CSV 文本 / 自包含 HTML 多表格（直接渲染）/ markdown 表 / .xlsx 工作簿；--from-json 时接 structured_summary 的 JSON 产物
```

### 5. 扩展：接入「用户其它已安装技能」

`assets/capabilities.json` 是**开放清单**，本机制天然兼容用户未来安装的任何协同技能：
- **已落地能力**（共 19 项）：`desensitization` / `ocr` / `speech_transcription` / `video_transcript` / `document_text` / `web_fetch` / `knowledge_base`(要点沉淀) / `translation`(多语摘要) / `rag`(基于原文的问答式展开) / `search`(受控联网补全) / `mindmap`(要点可视化) / `diagram`(结构/流程可视化) / `graph`(关系图谱/知识图谱) / `entity_extract`(实体·关系抽取) / `ppt`(演示文稿生成) / `chart`(图表可视化) / `qa_router`(问答路由) / `podcast`(播客/口播音频) / `spreadsheet`(表格处理)。其中 `knowledge_base`/`translation` 对接见第 4.5 节，`rag`/`search`/`mindmap`/`diagram`/`graph`/`entity_extract`/`ppt`/`chart`/`qa_router`/`podcast`/`spreadsheet` 对接见第 4.7 节。
- **新增能力**：在 JSON 的 `capabilities` 下追加任意键（如未来可加 `qa_router`、`podcast`、`spreadsheet` 等），给出 `purpose`、`keywords`（候选关键词）、`fallback` 与 `fallback_note`。`skill_bridge.py` 会自动识别匹配到的技能，无需改脚本。
- **触发新能力**：`skill_bridge.py --cap <新能力>` 检测 → 命中则按对应分支用 **Skill 工具**加载该技能并遵循其流程；未命中则按该能力的 `fallback` 降级。若属输出后协同（如沉淀/多语），仿第 4.5 节在 SKILL.md 补一段对接分支即可。
- **关键词调优**：若某技能未被识别（描述措辞不同），只需在其 `keywords` 中补充该技能描述里的特征词即可，零代码改动。
- **刷新设置**：安装/卸载协同技能后运行 `skill_bridge.py --save-cache`（见第 4.6 节），把「能力→技能」映射固化为 `capabilities.detected.json` 快照；本技能默认每次 live 重扫，新技能即时生效。
- 这样既"非限定本机已安装技能"，也为未来任意协同技能预留统一入口，持续提升健壮性。

## 跨智能体 / 跨平台说明

- 本技能为纯文本驱动的本地脚本 + 指令，不依赖特定宿主。供 Claude / Codex / OpenClaw 等使用时，复制技能目录（含 `scripts/`、`references/`、`assets/`、`requirements.txt`、`install.sh`）即可，运行 `scripts/summarize.py` 需 Python 3.8+。
- **默认零第三方依赖**；可选 `jieba` 中文分词增强通过 `./install.sh`（读 `requirements.txt`）安装，未安装自动回退内置分词。Windows/macOS/Linux 均直接 `python3 summarize.py` 运行。

## 可扩展方向（按需补充）

根据日常工作需求，参考市场同类技能，可继续补充：更长上下文的滑动窗口摘要（已支持）、多文档联合摘要（已支持）、按用户画像调节摘要语气（已支持 `--tone`）、与 `rag`/`search` 类技能联动做「摘要即检索」（已支持 `rag`/`search` 协同）。

**已落地的原生增强功能**（无需外部技能，见第 4.8 节）：`--cite` 原文溯源标注、`--tldr` 一句话核心结论、`diff_summary.py` 差异/变更摘要、`batch_summary.py` 批量目录摘要+索引、`consistency_check.py` 摘要-原文一致性自检、`pii_precheck.py` 上云前 PII 预检、`hierarchical_summary.py` 层级摘要、`structured_summary.py` 结构化抽取、`mindmap_import.py` 思维导图反向导入（含 `--markmap` 直接渲染）、`qa_router.py` 问答路由多轮状态机、`podcast.py` 口播稿生成（可选 `--tts` 合成音频）、`spreadsheet.py` 表格生成/解析（可选 `--format xlsx` 导出 .xlsx）。
