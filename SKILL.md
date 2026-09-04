---
name: office-kit
description: "合并办公工具包（元技能 / 编排层）：统一编排 info-extract（转录/OCR/视频文案/画面解读/文档文本提取）、desensitization-sop（本地脱敏）、summarize（摘要/提炼/关键词）、doc-layout-aesthetics（排版美化：Markdown→PDF/Word/PPT/HTML）四大组件。本地优先、隐私闭环、跨平台可移植。触发词：转录/转写/语音转文字/听写/字幕/提取文字/OCR/扫描件转文字/画面解读/图片理解/视频文案/视频转文字/在线视频/加密视频/抖音/小红书/bilibili/脱敏/去标识/PII/密级/密钥/摘要/提炼/要点/关键词/排版/美化/版面/Markdown转PDF/Word/PPT/HTML/PDF。办公类任务优先走本技能统一入口 kit.py，自动享受跨组件功能重叠仲裁与 extract→desen→summarize→doc-layout 流水线串联；子组件技能（info-extract 等）均已并入本技能，触发时一律走本统一入口。"
version: "0.1.0"
agent_created: true
tags: [office, transcription, ocr, video, desen, summarize, doc-layout, 办公, 转录, 脱敏, 摘要, 排版, 本地优先, 隐私, 跨平台]
---

# office-kit · 合并办公工具包（元技能 / 编排层）

## 概述
office-kit 把 `info-extract`（转录 / OCR / 视频文案 / 画面解读 / 文档文本提取）、`desensitization-sop`（本地脱敏）、`summarize`（摘要 / 提炼 / 关键词）、`doc-layout-aesthetics`（排版美化交付）合并为一个按办公业务流程组织的工作台。

**本技能是它们的统一编排入口（元技能）**：触发任一办公类能力时，一律走本技能的统一入口，由 `kit.py` 扫描 `components/*/manifest.json` 动态分发到对应组件，并自动享受跨组件功能重叠仲裁与流水线串联。

设计特征：可拆卸模块化（`kit.py` 动态注册，无需静态 case 分发）、本地优先 / 隐私闭环、跨平台可移植（macOS / Linux `office-kit.sh`、Windows `office-kit.ps1`）。

## 路由定位（重要）

`info-extract` / `desensitization-sop` / `summarize` / `doc-layout-aesthetics` 四个子组件各自**独立完整实现**（自带 SKILL.md + scripts + install/upgrade 脚本，独立上游仓库 `hzh-opc/<name>`），同时**并入本套件**（权威副本在 `components/<name>/`）。两种身份并存，入口优先级取决于部署场景：

| 场景 | 组件入口 | 说明 |
|------|----------|------|
| S1 便携版（纯 CLI，不装技能） | `kit.py <command>` / `office-kit.sh <command>` | `components/` 为唯一权威 |
| S2 套件作 Agent Skill | 本技能统一入口 | Agent 只读本 SKILL.md，经 `kit.py` 分发到组件 |
| S3 套件 + 组件技能共存 | **一律走 `kit.py`**（`components/` 为权威） | 独立技能副本仅作参考，避免双副本漂移 |
| S4 仅组件（不装套件） | 组件自身 SKILL.md / install·upgrade 脚本 | 组件回归自述身份，不依赖套件 |

- 触发办公类能力时，**优先走本统一入口** `kit.py`，自动享受跨组件功能重叠仲裁与流水线串联。
- 已装套件（S3）时，组件独立副本仅 S4 场景生效；请勿在套件内直接调用 `~/.workbuddy/skills/<name>/` 的独立副本，以免双副本版本漂移。

## 统一调用方式
主入口（macOS / Linux）：`~/office-kit/office-kit.sh`；Windows：`~/office-kit/office-kit.ps1`。
它委托 `kit.py` 扫描 `components/<component>/manifest.json`，动态分发到组件入口（等价于 `python3 ~/office-kit/kit.py <command>`）。

```bash
KIT=~/office-kit
$KIT/office-kit.sh list                 # 列出全部已注册命令
$KIT/office-kit.sh doctor               # 环境与组件自检
$KIT/office-kit.sh overlaps             # 列出跨组件功能重叠
$KIT/office-kit.sh check                # 检测组件完整性 + 远程新版本（只读）
$KIT/office-kit.sh upgrade              # 在线升级组件到远程最新版
$KIT/office-kit.sh repair               # 在线修复损坏/缺失组件
# 抽取处理链
$KIT/office-kit.sh extract   --type transcript 录音.mp3   --out $KIT/workbench/extract/
$KIT/office-kit.sh extract   --type ocr 图片.png
$KIT/office-kit.sh extract   --type video 课程.mp4
$KIT/office-kit.sh extract   --type vision 截图.png
$KIT/office-kit.sh extract   --type video_online "https://www.bilibili.com/video/BV1xx"
$KIT/office-kit.sh desen     run <敏感文档> --out $KIT/workbench/desen/
$KIT/office-kit.sh summarize <文本/文档> --out $KIT/workbench/summary/
# 美化交付
$KIT/office-kit.sh md-pdf  -i 文章.md -o $KIT/workbench/render/文章.pdf
$KIT/office-kit.sh render   --out $KIT/workbench/render/        # docx/pptx/html [--pdf]
$KIT/office-kit.sh pdf      --docx 稿件.docx --out $KIT/workbench/render/
$KIT/office-kit.sh tencent-doc 文章.md --title "标题"          # Markdown→腾讯文档云端
```

> 也可用 `python3 $KIT/kit.py <command> [参数]` 直接调用（与 `office-kit.sh` 等价）。

## 能力 → 组件 → 命令 映射

| 能力域 | 组件 | 命令 | 说明 |
|--------|------|------|------|
| 音频转录 / OCR / 视频文案 / 画面解读 / 文档文本提取 / 在线·加密视频 | info-extract | `extract` | `--type`：transcript / ocr / video / vision / doc_extract / video_online / video_online_enum（Whisper / rapidocr / VLM / yt-dlp） |
| 本地脱敏（PII / 密级 / 密钥）+ 自动解密 + OCR 后处理 | desensitization-sop | `desen` | 子命令：scan 检测 / run 脱敏 / decrypt 解密 / restore 还原 / audit 审计 / preprocess 预处理 / status 索引 / guide 指引；读取即脱敏，默认不落明文 |
| 摘要 / 提炼 / 关键词 | summarize | `summarize` | 纯标准库、离线优先 |
| Markdown→PDF / docx→PDF / 腾讯文档（通用转换）；Word / PPT / HTML（内置样例） | doc-layout-aesthetics | `md-pdf` `pdf` `tencent-doc` `docx` `pptx` `html` `render` | 中文排版美学渲染与交付；`docx`/`pptx`/`html`/`render` 当前以内置《版面美学观》样例为输入，待扩展 `-i` 后方为通用转换器 |

> 命令名互不冲突，`kit.py` 分发无歧义。重叠能力（如 `pdf-text-extract` / `office-text-extract` 同时被 info-extract 与 desensitization-sop 声明）按下方仲裁规则处理。
> 各组件完整触发词、子命令速查与协同语义详见 `components/<name>/SKILL.md`（S2 下 Agent 如需细节可直接读取该文件）。

## 编排流水线与重叠仲裁
标准办公流水线：`extract → desen → summarize → doc-layout`（doc-layout 把上游产物美化为交付物）。

跨组件功能重叠裁决（详见 `规划文档/功能重叠比对.md`）：

- **目标含敏感信息 / 需要脱敏 → 优先 `desen`**：`desen` 内部先解密再读取、读取后即脱敏，避免明文中间文件落地；**禁止先 `extract` 再 `desen`**（会造成二次读取与明文暴露）。
- **目标为纯内容提取（不涉敏）→ 优先 `extract`**：多源能力更全、OCR 协同更丰富、输出格式更灵活。
- **新增组件触发重叠时**：在 `manifest.json` 复用既有 `capabilities` 标签 → `kit.py overlaps` 自动检出 → 按比对表补裁决。

## 环境与虚拟环境
- 运行时统一以 `UV_PROJECT_ENVIRONMENT=<kit>/.venv` 为虚拟环境唯一真相源（`office-kit.sh` / `kit.py` 已显式注入），组件层不再写死布局特定路径。
- 首次使用需初始化 `.venv`：`cd ~/office-kit && ./bootstrap.sh`（uv 管理，Python 3.13，依赖优先国内源）。
- 自检：`~/office-kit/office-kit.sh doctor`。

## 组件版本快照
本集成包当前快照的四组件版本（追溯「本包集成的是哪版组件」用）：

| 组件 | 版本 |
|------|------|
| info-extract | 0.6.3 |
| desensitization-sop | 2.11.1 |
| summarize | 1.0.0 |
| doc-layout-aesthetics | 1.0.0 |

## 组件独立更新与可移植
- 各组件位于 `components/<name>/`，可独立替换更新；`kit.py` 扫描 manifest 动态注册，无需改动分发逻辑。
- 每个组件在 `manifest.json` 声明 `version`；`kit.py check` 检测损坏与远程新版本，`upgrade`/`repair` 在线下载修复，更新后自动重识能力并记录上下游对接（`workbench/logs/component-registry.json` + `component-events.log`），旧版归档到 `workbench/archive/components/`。
- `workbench/` 按业务流程阶段组织（inbox / extract / desen / summary / render / archive / logs），便于串接流水线。

---

## 外发必扫 DESEN 铁律（最高优先级，硬约束）

**凡外发信息必先 `desen scan`，未扫即阻断。** 本铁律适用于一切把信息送出本机的动作，包括显式外发与隐性外发。**2026-09-04 L4 硬化版：隐性外发命中敏感 → `kit.py` 代码级硬阻断（exit≠0），不再仅提示。**

- **显式外发**（`kit.py` `EXPLICIT_EXTERNAL`，用户主动、明显上云意图，直接放行不打扰）：`tencent-doc`（Markdown→腾讯文档云端）。
- **隐性外发**（`kit.py` `IMPLICIT_EXTERNAL`，非用户明显意图的上云/联网，命中敏感即硬阻断）：`summarize --mode cloud/hybrid`（摘要上云）、`podcast --tts`、多语翻译（translation）、联网补全（search）、网页抓取、要点沉淀进知识库、识别稿外发等。
- **逃生口**：环境变量 `OFFICE_KIT_SKIP_EXTERNAL_GATE=1` 显式跳过全部门禁（等价 security-scan Skip 档，风险自负）。

执行规则（分「DESEN 已装 / 未装」两路）：

| 情形 | 行为 |
|------|------|
| **DESEN 已装**（或已装任意脱敏技能/工具） | 隐性外发命令执行前**强制前置 `desen scan`**（`kit.py` 代码级门禁，自动仅扫真实输入文件）：命中敏感 → **硬阻断**（exit 3，须先 `desen run` 出脱敏副本再重试）；无敏感 → 静默放行；扫描异常 → fail-safe 保守阻断。各组件单独调用（S4）时由 `skill_bridge.py` 强制「已装即必扫」 |
| **DESEN 未装**（用户未装/不愿装） | **不随意阻断任务**（无工具可强制，阻断会卡死任务），改为**显式提醒**（"未检测到脱敏技能，本次外发未经完整 desen 扫描，请自行确认是否含敏感信息"）+ **组件自带最小脱敏兜底**（本地 PII 预检/掩码），让用户在知情前提下继续 |

> 组件升级/修复（`upgrade`/`repair`）属「组件自更新」联网，非外发用户信息，不触发本铁律。`desen` 自身「脱敏副本上云」已有确认闸门 + 清单，是铁律的正确实现范本。表格云解析（sheetagent）等 **office-kit 之外的插件通道不经过本铁律门禁**，须在业务层约定「送云前先 `desen scan`」兜底。

## 面向一般用户的展示规范（一致性底线 + 指针）

套件层只规定**跨组件一致性底线**，具体呈现细节由各组件 `SKILL.md`「交付物范式」节定义（组件定义、套件继承，S4 单独装组件时同样生效）：

1. **结论先行**：任务完成后，先用一句话说清「做了什么、结果如何、产物在哪」。
2. **降级显式提示**：任何能力降级（无纠正模型 / 无 VLM / 无浏览器技能 / 脱敏未通过）都须对话内显式告知，不静默。
3. **长文不刷屏**：正文超过阈值（建议 >~30 行 / >~500 字，逐字稿 / 审计报告 / 长原文回放均适用）时，默认不贴全文，改用「摘要置顶 + 分块预览 + 全文落盘兜底」，用户要哪段给哪段。
4. **流水线含 desen 环节时**，Agent 必须输出「脱敏审计卡片」（识别清单 + 外发边界 + 风险自评），再继续后续 summarize / doc-layout。
5. **产物导航一句话**：交付时对话内给出产物定位（如"你的纠正稿在 `<workbench>/extract/交付/`，原始识别在 `<workbench>/extract/存档/`"）。

## 交付物红线

任何 OCR / 语音 / 视觉识别类能力，**交付物一律为「纠正版稿件」**；原始识别仅作存档备查（`raw_text` / 存档区），**不得作为交付物直接呈现**；无纠正能力时必须显式降级提示。
