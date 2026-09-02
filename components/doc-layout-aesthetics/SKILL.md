---
name: doc-layout-aesthetics
description: 提炼自侯捷《Word 排版艺术》的中文排版美学规范，覆盖"对齐/对比/亲密性/重复/留白/节制/中英文混排"七大原则，并扩展至常见纸型(含手账)、网页(响应式)、幻灯片与平板/手机多终端显示优化。This skill should be used when generating or polishing Chinese documents, reports, theses, manuals, proposals, slides, web pages, HTML, or PDFs, or whenever a task asks to make output more professional, readable, typographically correct, or multi-device friendly. 同时提供 Markdown→PDF 直转、Word→PDF、PPT、响应式 HTML、腾讯文档云端路径等一站式排版交付。触发词：排版、版面、格式、美化、Word、文档、幻灯片、PPT、PDF、网页、HTML、响应式、手账、纸型、对齐、留白、字体、行距、中英文混排、目录、样式、多终端、手机、平板、腾讯文档、云端文档、Markdown 转 PDF、md 转 pdf、markdown to pdf。
agent_created: true
version: "1.0.0"
---

# 版面美学观 · 中文排版规范

将侯捷《Word 排版艺术》的版面美学沉淀为可复用规则，在任何中文文档 / 幻灯片 / 网页 / 多终端产出前主动套用，使输出在易读性、一致性与专业感上达标，并在手机、平板、桌面都有好体验。

## 何时使用

- 生成或润色 Word 文档、报告、论文、说明书、方案、长文档。
- 制作中文 PPT / 幻灯片（16:9 演示）。
- 搭建网页 / HTML / 响应式页面，或任何需要移动优先、多终端适配的版面。
- 排版手账 / 笔记 / 名片 / 明信片 / 小开本等多纸型印刷物。
  - 导出 PDF 或任何需要"更专业、更易读、跨终端一致"的版式优化请求。
  - 把成果直接落到「腾讯文档」云端（docs.qq.com）在线文档。
  - **把 Markdown（.md）直接转成排版良好的中文 PDF**（无需先建 docx，保留同一套美学规范）。
  - 用户提到排版、格式、对齐、留白、字体、行距、中英文混排、目录、样式、响应式、手账、纸型、腾讯文档、云端文档、Markdown 转 PDF、md 转 pdf、markdown to pdf 等。

## 如何使用

1. **先读规范**：在开始排版前，阅读 `references/aesthetics-spec.md` 获取完整原则、参数表、自查清单与反模式。该文件是知识核心，含七大原则细节、可套用参数、交付前自查项、反模式，以及「常见纸型(含手账) / 网页 / 幻灯片 / 多终端」四大跨媒介章节。
2. **定媒介**：先确定产出媒介，再选对应章节——
   - 文档 / 手账 → 第三节参数规范 + 第八节纸型；
   - 网页 / HTML → 第九节响应式原则；
   - 幻灯片 → 第十节幻灯片原则；
   - 手机 / 平板 → 第十一节多终端优化。
   - 腾讯文档云端 → 第十二节云端路径（`create_with_markdown` 建结构 + `update_text_property` 设字体 / 颜色 + `set_table_properties` 美化表格；四类 Word 专属能力暂缺，见该节规避方案）。
3. **定基调**：确定定位（正式印刷 / 屏幕阅读 / 演示 / 移动），据此选字体搭配与参数。
4. **建立样式**：先用「样式」定义正文与各级标题（链接多级列表自动编号），再写内容；严禁手动局部格式。
5. **套用七大原则**：对齐统一、对比制造焦点、亲密性分组、重复统一元素、留白给呼吸感、节制字体与颜色、中英文混排处理字号 / 间距 / 标点。
6. **交付前自查**：逐条核对 `references/aesthetics-spec.md` 的「排版自查清单」并排查「反模式」。
7. **自动化收尾**：编号 / 目录 / 页码 / 页眉用域自动生成；网页输出关闭不必要的动效并满足对比度；输出 PDF 前关闭编辑标记。

## CLI 用法（命令行直跑脚本）

本技能既可被 Agent 按触发词调用（上方「如何使用」），也可作为命令行工具直接跑脚本，二者视角不同：

| 能力 | 命令（WorkBuddy 宿主） | 说明 |
|---|---|---|
| Markdown → 排版 PDF | `<默认环境>/bin/python scripts/build_md_pdf.py -i in.md -o out.pdf` | **真实能力**，`-i` 接受任意 Markdown |
| docx → PDF | `<默认环境>/bin/python scripts/build_pdf.py --docx in.docx --out <目录>` | **真实能力**，自动探测引擎 |
| 精排 Word 样例 | `<默认环境>/bin/python scripts/build_docx.py --out <目录>` | 内置《版面美学观》样例 |
| PPT 样例 | `<默认环境>/bin/python scripts/build_pptx.py --out <目录>` | 内置《版面美学观》样例 |
| 响应式 HTML 样例 | `<默认环境>/bin/python scripts/build_html.py --out <目录>` | 内置《版面美学观》样例 |
| 一键四件套 | `<默认环境>/bin/python scripts/build_all.py --pdf --out <目录>` | 内置《版面美学观》样例 |
| 冒烟自检 | `<默认环境>/bin/python scripts/selfcheck.py --build` | 安装后自检 |

> 非宿主（Claude/Codex/OpenClaw）把 `<默认环境>/bin/python` 换成 `uv run python` 或已激活 `.venv` 的 `python`。
> `<默认环境>` = `~/.workbuddy/binaries/python/envs/default`（详见 [`AGENT_INSTALL.md`](./AGENT_INSTALL.md)）。
> 一键装依赖并自检：`bash install.sh`。

## 关键约束（速记）

- 字体 ≤ 3 种；颜色 ≤ 主色 + 3 辅助色。
- 正文两端对齐（纯中文）/ 左对齐（混排）；标题可居中或左对齐。
- 首行缩进 2 字符（用特殊格式，非空格）；行距 1.5 倍或固定值 28 磅。
- 中英文之间、中文与数字之间加半角空格；开启避头尾与标点悬挂。
- 中文不用斜体；强调用加粗。
- 网页 / 多终端：移动优先、流式单位(clamp)、触控目标 ≥44px、视口 meta、对比度 WCAG AA。
- 幻灯片：16:9、字号 ≥18pt、每页一观点、安全区 ≥0.5in。
- 所有编号 / 目录 / 页码自动化，绝不手填。

## 资源

> **能力边界（重要，勿误读为通用交付）**：本仓库的 `build_docx.py` / `build_pptx.py` / `build_html.py` /
> `build_all.py` **当前以内置《版面美学观》为输入生成演示样例**，尚未支持传入用户自有内容
> （通用转换 = 待扩展 `-i` 入参）。真正「吃任意输入」的能力目前是：
> `build_md_pdf.py`（Markdown → PDF，`-i` 输入）、`build_pdf.py`（docx → PDF，`--docx` 输入）、
> `build_tencent_doc.py`（Markdown → 腾讯文档，`<输入.md>`）。

> **多 Agent 平台安装**：WorkBuddy / Claude Code / Codex / OpenClaw 的安装步骤、venv 两种路线（uv / pip）、字体安装、自检与 FAQ 见 **[`AGENT_INSTALL.md`](./AGENT_INSTALL.md)**。

> **环境（uv 项目）**：本技能的生成脚本依赖 Python 库（python-docx / python-pptx / reportlab），由 **uv** 管理虚拟环境。技能根目录含 `pyproject.toml` + `uv.lock`。可选依赖：`docx2pdf`（仅 Windows/macOS 需本机 Word，用 `uv sync --extra word` 安装）。
> - **虚拟环境位置（可移植，优先级从高到低）**：① 环境变量 `UV_PROJECT_ENVIRONMENT`（用户/宿主显式指定，**脚本绝不覆盖**）；② `VIRTUAL_ENV`（已激活的 venv）；②.5 `<OFFICE_KIT_ROOT>/.venv`（若经 office-kit 部署、且其 `.venv` 存在，覆盖裸跑脚本落到宿主全局默认环境与 kit 隔离环境不一致的困惑）；③ 平台默认——WorkBuddy 宿主（存在 `~/.workbuddy`）→ **全局共享默认环境** `~/.workbuddy/binaries/python/envs/default`（所有技能依赖并入此处、不另建 venv、禁用 `uv sync`）；其他平台 → 项目内 `.venv`。解析逻辑统一在 `scripts/_venv.py`。
> - **首次使用（WorkBuddy 宿主）**：依赖已并入全局共享默认环境 `~/.workbuddy/binaries/python/envs/default`，**直接用该环境 python 运行脚本即可**（无需 `uv sync`、不另建 venv）。如需（重）并入依赖（追加式，绝不裁剪他技能）：`uv pip install --python ~/.workbuddy/binaries/python/envs/default/bin/python python-docx python-pptx reportlab pytest`。其他平台（Claude/Codex/OpenClaw）仍用 `uv sync` 建项目内 `.venv`；⚠️ **Windows + Git Bash** 下 `~` 会被展开成 POSIX 路径被 Windows 原生 uv 误解析，请改用显式 Windows 原生路径（PowerShell / CMD / WSL / macOS / Linux 无此问题）。
> - **运行**：直接 `<默认环境>/bin/python scripts/build_all.py` 即可（宿主自动复用共享默认环境 python、不走 `uv run --project` 以免裁剪他技能依赖）；单独跑某脚本用 `<默认环境>/bin/python scripts/build_pdf.py --out <目录>`（宿主）或 `uv run python scripts/build_pdf.py --out <目录>`（非宿主）。**多平台安装与运行详见 [`AGENT_INSTALL.md`](./AGENT_INSTALL.md)**。

- `references/aesthetics-spec.md` — 完整美学规范（原则详解、参数表、自查清单、反模式、Word 工程实现、常见纸型含手账、网页 / 幻灯片 / 多终端跨媒介要点、**第十二节「腾讯文档云端路径」能力边界与落地**、来源）。排版前必读。
- `scripts/build_all.py` — **统一入口**：一键构建 docx + pptx + html 三份本地交付物；加 `--pdf` 可额外把 docx 转 PDF。`<默认环境>/bin/python scripts/build_all.py --pdf --out <目录>`（不指定 `--out` 时输出到当前目录）。**（当前=内置《版面美学观》样例演示，通用转换待扩展 `-i` 入参）**
- `scripts/build_docx.py` — 精排 Word 文档生成脚本（含表格跨页保护：长表 cantSplit、短表 keepNext）。`<默认环境>/bin/python scripts/build_docx.py --out <目录>`。**（当前=内置《版面美学观》样例演示，通用转换待扩展 `-i` 入参）**
- `scripts/build_pptx.py` — PPTX 对照演示生成脚本（本身即七大原则范例：统一色板 / 字体 / 装饰线示范重复，左右对照页示范对比，网格总览示范对齐 + 亲密性，安全区与 ≥18pt 字号示范幻灯片规范）。`<默认环境>/bin/python scripts/build_pptx.py --out <目录>`。**（当前=内置《版面美学观》样例演示，通用转换待扩展 `-i` 入参）**
- `scripts/build_html.py` — 响应式 HTML 参考生成脚本（本身即移动优先、多终端自适应演示；用 CSS 容器查询在手机 / 平板 / 桌面三档真实重排）。`<默认环境>/bin/python scripts/build_html.py --out <目录>`。**（当前=内置《版面美学观》样例演示，通用转换待扩展 `-i` 入参）**
- `scripts/build_pdf.py` — 把 docx 转成 PDF，**尽量保证与 Word 文档页面统一**。转换引擎按优先级自动探测（可用 `--engine` 强制）：
  1. **LibreOffice** (`soffice`/`libreoffice`)：直接把真实 docx 转 PDF，保真度最高；
  2. **docx2pdf**（需本机安装 Microsoft Word）：调用 Word 转 PDF；
  3. **WPS Office 命令行**（可选引擎）：Linux/Windows 的 `wps --headless --convert-to pdf` 自动可用；macOS/Windows 的 `wpscli word2pdf`（kpdfcli 契约）需登录 WPS 账号且具备 VIP，**不进 auto，仅 `--engine wps` 强制**（macOS 实测该契约崩溃退出码 133，不可用时自动回退）；
  4. **纯 Python reportlab**：仅当上述引擎都缺失时启用，读取 docx 真实页型/页边距与字体配对（思源宋体衬线正文 + 思源黑体无衬线标题）重排，并落实表格跨页保护。
  `<默认环境>/bin/python scripts/build_pdf.py --out <目录>`（默认 auto 探测）；也可 `--engine libreoffice|docx2pdf|wps|reportlab` 强制。
- `scripts/build_md_pdf.py` — **Markdown → PDF 直转**（不经过 docx），纯 reportlab 渲染，与本技能美学规范一致：思源宋体衬线正文 + 思源黑体无衬线标题、主题深蓝、**正文左对齐**（规避中英混排"河流"效应）、行距 1.5 倍、首行缩进 2 字符、表格深蓝表头 + 斑马纹 + 跨页 repeatRows、短表 KeepTogether。**标题孤行（orphan heading）保护**：标题必须与其后「直到下一标题之前」的全部内容同页，禁止"标题在页底、内容在页首"的割裂。实现要点——**不要依赖 `keepWithNext` 链式传递**（H1/H2 后紧跟的 `HRFlowable` 分隔线会让保护链断裂，实测 `keepWithNext` 对 HRFlowable 无效）；正确做法是由 `build_flowables` 用 while 收集「标题 + 分隔线 + 同章节后续 block」，整段用 `KeepTogether` 包裹。剩余空间不足容纳整段时整段下移；若整段超过一页，reportlab 自动拆分为多页（不会无限溢出），标题始终落在章节起始处而非页底。三平台字体探测（**开源优先**：思源宋体/黑体、Noto CJK、文泉驿，系统字体 Songti/STHeiti/SimSun/SimHei 仅兜底并告警）。支持 Markdown 标题（#~###）、粗斜、行内代码 `` `code` ``、无序/有序/任务列表、代码块（``` 围栏 + 浅灰底，**保留缩进**）、本地相对路径图片（按版心宽度等比缩放、居中）、链接（保留 text 去掉 URL）、**列表项/任务项续行**（2+ 空格缩进挂到上一项）、**段落硬换行**（行尾两空格 / 反斜杠 → `<br/>`）、**多行引用**（`> ` 连续行，行内保留换行 + 左边深蓝竖线 + 浅蓝底 + 灰色字）。**符号安全机制**：列表项目符号 / 任务标记在渲染前用 `TTFont.face.charWidths` 运行时验证字形（首选 `●/√/□`，思源宋体缺失时自动降级到 `·/✓/○` 乃至 ASCII 兜底并告警），杜绝因字体缺字形导致的"无标记"空白。`<默认环境>/bin/python scripts/build_md_pdf.py -i in.md [-o out.pdf] [-t 标题] [--subtitle 副标题] [--author 作者] [--no-cover]`（不指定 `--out` 时输出到输入同目录同名 .pdf）。**两种 PDF 路径的取舍**：先有 Markdown 源、需要快速直转 → `build_md_pdf.py`；已经在做《版面美学观》docx 交付、需要与 Word 页面完全一致 → `build_pdf.py`。
- `scripts/build_tencent_doc.py` — 腾讯文档云端路径 helper：把 Markdown 落到 `docs.qq.com` 并自动套用美学（标题 思源黑体 + 深蓝 + 加粗、表格边框 + 表头底色 + 斑马纹）。需 `tencent-docs` 插件且宿主已连接腾讯文档。示例：`<默认环境>/bin/python scripts/build_tencent_doc.py scripts/sample_tencent.md --title 版面美学观`。
- `scripts/sample_tencent.md` — 腾讯文档云端路径的示例输入 Markdown，供 `build_tencent_doc.py` 直接调用。
- `scripts/upgrade_skill.sh` / `scripts/upgrade_skill.ps1` — **升级脚本**（macOS/Linux + Windows）：从 GitHub 远程仓库拉取最新版并同步到技能副本，副本保持干净（不含 `.git` / 缓存 / 字体二进制）。用法：`bash scripts/upgrade_skill.sh [--target DIR] [--check] [--dry-run]`；Windows `powershell -ExecutionPolicy Bypass -File scripts\upgrade_skill.ps1 [-Check] [-DryRun]`。详见 [`AGENT_INSTALL.md`](./AGENT_INSTALL.md) 第 6 节。
- `scripts/render_pdf.swift` — **macOS 平台首选**的 PDF 高保真渲染器（PDF → PNG），用于人工视觉核验排版效果。走 PDFKit + CoreGraphics（系统原生渲染管线，与 Preview 一致），规避 sips / qlmanage 对 reportlab 子集化字体缺字形的局限。**仅 macOS**（依赖系统框架 + swift），零第三方包。`swift scripts/render_pdf.swift <input.pdf>`（第 1 页 → 同目录 `.png`）；`-o` 指定输出、`-p` 指定页码、`--all` 渲染全部页、`-s` 缩放倍率。**Linux / Windows 无此工具**——在那些平台做视觉核验请直接打开 PDF 查看。

**跨平台说明**：所有脚本在 macOS / Linux / Windows 均可运行——默认输出目录为当前目录（`--out` 覆盖）；venv python 路径按平台取 `bin/python` 或 `Scripts/python.exe`；CJK 字体探测**开源优先**（思源宋体/黑体、Noto CJK、文泉驿 + 霞鹜文楷，系统字体 Songti/STHeiti/SimSun/SimHei 仅兜底并告警）；**`detect_fonts` 自动跳过 CFF/PostScript 轮廓字体**（reportlab `TTFont` 不支持嵌入思源/Noto `.otf`，会打印可读告警并改用文楷/文泉驿）；PDF 输出已把 stdout 统一为 UTF-8，避免 Windows GBK 控制台对 emoji 报错。docx/pptx 里的字体名为**开源可商用**字体名（思源宋体/思源黑体/霞鹜文楷），渲染由打开文档的软件按本机字体回退。**字体安装详见 [`FONTS.md`](./FONTS.md) 与 `fonts/install_fonts.sh|ps1`**。

## 字体安装

本技能默认所有中文字体走**开源可商用**路线（思源宋体/黑体、霞鹜文楷、文泉驿、DejaVu），**禁止**宋体/黑体/微软雅黑/苹方/楷体/Arial/Times New Roman 等商业系统字体。

> **默认安装不包含字体**：仓库不捆绑字体二进制（~150MB 不入 git，见 `.gitignore`）。
> 未装开源字体时脚本自动回退系统字体并打印版权告警（功能可用）；需要 PDF 最佳渲染时，
> 可让 AI Agent 执行下方脚本，或按 [`FONTS.md`](./FONTS.md) 手动安装。

- **官方与国内源清单 + 离线字体包 + 许可协议** → 根目录 [`FONTS.md`](./FONTS.md)
- **跨平台安装脚本**（在线包管理器 / 离线本地 common 两种模式 + 官方/国内镜像可选）：
  - `bash fonts/install_fonts.sh [--online|--dir <path>|--dry-run]` — macOS / Linux
  - `powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1 [-Online -Mirror china|-DryRun]` — Windows
- **平台专用安装指南**（Homebrew / apt / dnf / pacman / winget） → `fonts/{macos,linux,windows}/README.md`
- **reportlab CFF 限制**：思源/Noto 的 `.otf` 与多数 Linux 发行版 `.ttc` 为 CFF 轮廓，**不能**被 `build_pdf.py` / `build_md_pdf.py` 嵌入 PDF；脚本自动跳过 CFF 改用文楷（衬线/楷体）+ 文泉驿（无衬线）。思源 OTF 仍可用于 Word/PPT/HTML 与系统显示。

## 目录与版本

本技能采用「三目录」架构，职责分离：

| 目录 | 职责 | 说明 |
|---|---|---|
| `~/.workbuddy/skills/doc-layout-aesthetics/` | **干净的技能副本** | 可复用、可打包；不在副本里做开发实验 |
| `~/WorkBuddy/Skill-Dev/doc-layout-aesthetics/` | **工作空间**（开发参考） | 交付物、`DEVELOPMENT.md` 开发记录、测试样例 |
| `~/Repositories/doc-layout-aesthetics/` | **本地 git 仓库** | 版本管理；与技能副本独立 |

- **远程仓库**：<https://github.com/hzh-opc/doc-layout-aesthetics>（Apache-2.0，作者 hzh.opc / Huang Zenghao，由 WorkBuddy 协助整理）。
- **默认安装不包含字体**：仓库不捆绑字体二进制（~150MB 不入 git）；需要 PDF 最佳渲染时按 [`FONTS.md`](./FONTS.md) 或 `fonts/install_fonts.sh|ps1` 安装开源字体（可让 AI Agent 代为执行）。
- **同步约定**：仓库 ↔ 技能副本之间用 `rsync` 同步，**仅由用户主动发起**；开发迭代先在仓库进行，稳定后再手动同步到技能副本。
- **office-kit 套件主从关系（2026-09-02 定）**：本独立仓库是**唯一上游**。若本机已装 office-kit 套件，组件权威副本位于套件 `components/doc-layout-aesthetics/`，技能副本 `~/.workbuddy/skills/doc-layout-aesthetics/` 是**转向器**（`redirect_to ~/office-kit/`），升级请用套件统一入口 `python kit.py upgrade doc-layout-aesthetics`，**勿跑 `scripts/upgrade_skill.sh`**（会覆盖转向器、造成双源漂移）。`upgrade_skill.sh` 仅用于 S4「仅组件独立部署」场景。
- 技能副本本身不建 git；版本历史以仓库为准。`scripts/__pycache__`、`.venv`、`.DS_Store` 不入库（见 `.gitignore`）。
