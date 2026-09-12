# doc-layout-aesthetics · 中文排版美学技能

> 仓库：<https://github.com/hzh-opc/doc-layout-aesthetics> · Apache-2.0
> 作者：hzh.opc（Huang Zenghao，由 WorkBuddy 协助整理）

提炼自侯捷《Word 排版艺术》的中文排版美学规范，覆盖 **对齐 / 对比 / 亲密性 / 重复 / 留白 / 节制 / 中英文混排** 七大原则，并扩展至常见纸型（含手账）、网页（响应式）、幻灯片与平板/手机多终端显示优化。

同时提供一站式排版交付能力：**docx 精排、PPT 对照演示、响应式 HTML、docx→PDF、Markdown→PDF 直转、腾讯文档云端路径**（依赖宿主插件）。

> **默认安装不包含字体**：本仓库不捆绑字体二进制（体积 ~150MB）。需要 PDF 最佳渲染时，
> 可让 AI Agent 执行安装脚本，或按 [`FONTS.md`](./FONTS.md) / [`AGENT_INSTALL.md`](./AGENT_INSTALL.md) 手动安装开源字体。

## 快速开始

```bash
# 1) 环境（WorkBuddy 宿主：依赖已并入全局共享默认环境，无需自建 venv）
DEF=~/.workbuddy/binaries/python/envs/default/bin/python   # 共享默认环境 python
#    如需（重）并入依赖（追加式，不裁剪他技能）：
#    uv pip install --python $DEF python-docx python-pptx reportlab pytest
#    其他平台（Claude/Codex/OpenClaw，无 ~/.workbuddy）：uv sync（建项目内 .venv）

# 2) 构建全部交付物（docx / pptx / html / pdf）
$DEF scripts/build_all.py --pdf --out ./out

# 3) Markdown → PDF 直转
$DEF scripts/build_md_pdf.py -i scripts/sample_tencent.md -o /tmp/sample.pdf

# 4) 自检
$DEF -m pytest -q
$DEF scripts/selfcheck.py --build

# 5) 升级技能（从 GitHub 拉取最新版并同步副本，副本保持干净）
bash scripts/upgrade_skill.sh                # macOS / Linux（默认 WorkBuddy 副本）
powershell -ExecutionPolicy Bypass -File scripts\upgrade_skill.ps1   # Windows
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [`SKILL.md`](./SKILL.md) | 技能本体：使用方式、资源清单、跨平台说明、字体安装 |
| [`AGENT_INSTALL.md`](./AGENT_INSTALL.md) | **多 Agent 平台安装指南**（WorkBuddy / Claude Code / Codex / OpenClaw），含 venv 两种路线、**升级技能**、自检、FAQ |
| [`references/aesthetics-spec.md`](./references/aesthetics-spec.md) | 完整美学规范（七大原则、参数表、自查清单、反模式、跨媒介章节） |
| [`FONTS.md`](./FONTS.md) | 字体资源包清单（官方源 + 国内源、许可、reportlab CFF 限制） |
| [`tests/`](./tests/) | pytest 用例（17 例：表格跨页保护 / PDF 引擎回退链） |

## 多 Agent 平台

本技能是**平台无关**的目录结构（`SKILL.md` + `scripts/` + `references/` + `tests/` + `pyproject.toml`），可安装到：

- **WorkBuddy**：`~/.workbuddy/skills/doc-layout-aesthetics/`（**仅 S4「组件独立安装」场景**；含腾讯文档路径）
- **Claude Code**：`~/.claude/skills/` 或项目 `.claude/skills/`
- **Codex（OpenAI）**：`~/.codex/skills/` 或项目 `.codex/skills/`
- **OpenClaw**：`~/.openclaw/skills/` 或工作区 `skills/`

> ⚠️ **本机已装 office-kit 套件时，不走上述独立安装**：组件权威副本位于 `~/office-kit/components/doc-layout-aesthetics/`，统一经 `Skill: office-kit`（`kit.py`）分发；`~/.workbuddy/skills/doc-layout-aesthetics/` 已退役。上表仅适用于 S4「仅组件独立部署」。

详细步骤见 [`AGENT_INSTALL.md`](./AGENT_INSTALL.md)。

## 目录结构

```
├── SKILL.md                # 技能定义
├── AGENT_INSTALL.md        # 多 Agent 平台安装指南
├── README.md               # 本文件（仓库门面）
├── LICENSE                 # Apache-2.0 许可
├── NOTICE                  # 署名与版权声明
├── pyproject.toml          # Python 项目（依赖 / pytest 配置）
├── uv.lock                 # uv 锁定依赖
├── references/
│   └── aesthetics-spec.md  # 完整美学规范
├── scripts/
│   ├── _venv.py             # 虚拟环境解析（UV_PROJECT_ENVIRONMENT > VIRTUAL_ENV > OFFICE_KIT_ROOT/.venv(若部署) > 平台默认）
│   ├── build_all.py        # 统一入口
│   ├── build_docx.py       # Word 精排（表格跨页保护）
│   ├── build_pptx.py       # PPT 对照演示
│   ├── build_html.py       # 响应式 HTML
│   ├── build_pdf.py        # docx→PDF（引擎链）
│   ├── build_md_pdf.py     # Markdown→PDF 直转
│   ├── build_tencent_doc.py# 腾讯文档云端（仅 WorkBuddy）
│   ├── selfcheck.py        # 冒烟自检
│   ├── upgrade_skill.sh    # 升级脚本（macOS/Linux）
│   ├── upgrade_skill.ps1   # 升级脚本（Windows）
│   └── render_pdf.swift    # PDF→PNG 视觉核验（仅 macOS）
├── tests/                  # pytest 用例
├── fonts/                  # 字体安装脚本 + 平台指南（不含字体二进制）
└── FONTS.md                # 字体清单
```

## 许可

- 代码：**Apache-2.0**（见 [`LICENSE`](./LICENSE)，署名见 [`NOTICE`](./NOTICE)）
- 作者：hzh.opc（Huang Zenghao），由 WorkBuddy 协助整理
- 字体：SIL OFL 1.1 / GPLv2+font exception 等开源许可（**默认不包含字体**，详见 [`FONTS.md`](./FONTS.md)）
- 排版美学规范：提炼自侯捷《Word 排版艺术》公开出版内容，仅作学习参考
