# AGENT_INSTALL.md · 跨平台安装与使用指南

> 本文件面向 **AI Agent（智能体）平台接入**：WorkBuddy / Claude Code / Codex / OpenClaw 等。
> 覆盖：各平台技能安装方式、依赖环境搭建（uv / venv 两种路线）、开源字体安装、功能自检与常见问题。
> 与 [`FONTS.md`](./FONTS.md)（字体资源包）配合使用。
> 仓库：<https://github.com/hzh-opc/doc-layout-aesthetics> · Apache-2.0 · 作者 hzh.opc（Huang Zenghao，由 WorkBuddy 协助整理）

> **默认安装不包含字体**：仓库不捆绑字体二进制。PDF 渲染需要 TrueType 轮廓的开源中文字体；
> 未安装时脚本自动回退系统字体并打印版权告警（功能可用，但商用分发建议安装开源字体）。
> 需要字体时，可让 AI Agent 直接执行第 4 节安装脚本。

---

## 1. 平台支持矩阵

| 平台 | 技能目录（推荐） | 触发方式 | 备注 |
|---|---|---|---|
| **WorkBuddy** | `~/.workbuddy/skills/doc-layout-aesthetics/` | 对话触发（描述含"排版/版面/美化/PDF"等触发词） | **S4 组件独立安装**；支持腾讯文档云端路径 |
| **Claude Code** | `~/.claude/skills/doc-layout-aesthetics/` 或项目 `.claude/skills/` | `/skills` 或对话上下文 | 支持 `uv`；无 WorkBuddy 专属能力 |
| **Codex（OpenAI）** | `~/.codex/skills/` 或项目 `.codex/skills/` | 对话上下文 / `$doc-layout-aesthetics` | 同上 |
| **OpenClaw** | `~/.openclaw/skills/` 或工作区 `skills/` | 对话上下文 / 斜杠命令 | 同上 |

> **各平台一致点**：技能本体 = `SKILL.md` + `references/` + `scripts/` + `tests/` + `pyproject.toml`，
> 是**平台无关**的目录。任意平台只要把整个目录放到对应技能目录即可识别。
>
> ⚠️ **已装 office-kit 套件的机器无需按上表独立安装**：组件权威副本位于
> `~/office-kit/components/doc-layout-aesthetics/`，统一经 `Skill: office-kit`（`kit.py`）分发；
> `~/.workbuddy/skills/doc-layout-aesthetics/` 已退役。上表仅适用于 S4「仅组件独立部署」。

---

## 2. 前置依赖（三平台通用）

| 依赖 | 版本要求 | 用途 | 安装 |
|---|---|---|---|
| Python | ≥ 3.11 | 运行构建脚本 | 官方安装包 / 包管理器 |
| uv（推荐） | ≥ 0.4 | 管理虚拟环境与依赖 | 见下 |
| 开源中文字体 | 建议安装 | PDF 嵌入 / docx/pptx/html 渲染 | 见 [`FONTS.md`](./FONTS.md) 与第 4 节 |

### 2.1 安装 uv（跨平台）

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows（PowerShell）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

> 若不便安装 uv，第 3.2 节提供 **标准 venv + pip 路线**，脚本自动兼容。

---

## 3. 安装到各 Agent 平台

### 3.1 WorkBuddy

```bash
# 方式一：本地复制（技能已在本机其他位置/仓库时）
cp -r <doc-layout-aesthetics路径> ~/.workbuddy/skills/doc-layout-aesthetics

# 方式二：从 GitHub 仓库克隆
git clone https://github.com/hzh-opc/doc-layout-aesthetics \
  ~/.workbuddy/skills/doc-layout-aesthetics
```

首次使用（技能目录内执行一次）：

```bash
cd ~/.workbuddy/skills/doc-layout-aesthetics

# WorkBuddy 宿主：依赖已并入全局共享默认环境，无需自建 venv、禁用 uv sync
DEF=~/.workbuddy/binaries/python/envs/default/bin/python   # 共享默认环境 python
# 直接用该环境 python 运行（依赖已就位）；如需（重）并入依赖（追加式、不裁剪他技能）：
#   uv pip install --python $DEF python-docx python-pptx reportlab pytest
```

> WorkBuddy 宿主下**不另建 venv**：所有技能依赖并入全局共享默认环境
> `~/.workbuddy/binaries/python/envs/default`（见 `config/python-env.md` 治理），
> `build_all.py` 自动复用其 python 直跑（不走 `uv run --project`，以免按本技能
> pyproject 裁剪默认环境中他技能依赖）。**venv 位置优先级**：`UV_PROJECT_ENVIRONMENT`
> （显式，最高）> `VIRTUAL_ENV`（已激活）> 平台默认（WorkBuddy → 共享默认环境；其他 → 项目内 `.venv`）。
> 脚本**绝不覆盖你显式设置的 `UV_PROJECT_ENVIRONMENT`**。

### 3.2 Claude Code / Codex / OpenClaw（通用流程）

```bash
# 1) 克隆仓库并放到对应平台的技能目录（以 Claude Code 为例）
git clone https://github.com/hzh-opc/doc-layout-aesthetics
mkdir -p ~/.claude/skills
cp -r doc-layout-aesthetics ~/.claude/skills/
# Codex:    ~/.codex/skills/        或项目 .codex/skills/
# OpenClaw: ~/.openclaw/skills/     或工作区 skills/

# 2) 在技能目录内建虚拟环境（uv 路线，推荐）
cd ~/.claude/skills/doc-layout-aesthetics
uv sync                      # 默认在 ./.venv（项目内，平台无关）

# 2') 或标准 venv + pip 路线（无 uv 时）
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install python-docx python-pptx reportlab pytest   # 与 pyproject.toml 依赖一致
```

> 这三个平台无 `~/.workbuddy`，`build_all.py` 自动改用项目内 `.venv`，
> 无需任何配置，直接运行脚本即可。

### 3.3 运行方式（各平台一致）

```bash
# WorkBuddy 宿主：直接用共享默认环境 python（推荐，无冗余 venv）
DEF=~/.workbuddy/binaries/python/envs/default/bin/python
$DEF scripts/build_all.py --pdf --out ./out

# 非宿主（Claude/Codex/OpenClaw）：uv run 走项目内 .venv
uv run python scripts/build_all.py --pdf --out ./out
```

> `build_all.py` 在 WorkBuddy 宿主下自动复用共享默认环境 python 直跑（不走 `uv run --project`，
> 以免裁剪他技能依赖）；非宿主（uv 可用时）走 `uv run --project <技能根目录>`（自有 `.venv`），
> 或回退到已装依赖的解释器。**只要依赖已装进对应环境，就会复用，不会重建**。

---

## 4. 安装开源中文字体（强烈建议）

**仓库默认不包含字体二进制**（体积 ~150MB，不入 git）。PDF 渲染需要 TrueType 轮廓的中文字体。
**不装也能跑**（脚本自动回退系统字体并打印版权告警），但为了 PDF 商用分发无版权风险，建议安装。
可直接让 AI Agent 执行以下命令，或手动运行：

```bash
# macOS / Linux
bash fonts/install_fonts.sh --online          # 自动走包管理器或国内镜像下载

# Windows（PowerShell）
powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1 -Online
```

各平台手动安装命令与字体清单见 [`FONTS.md`](./FONTS.md)。

---

## 5. 功能自检（安装完成后必跑）

```bash
cd <技能目录>

# 1) pytest（17 例：表格跨页保护 / PDF 引擎回退链）
uv run python -m pytest -q

# 2) 冒烟自检（依赖 / 字体 / 引擎 / 端到端构建）
uv run python scripts/selfcheck.py --build

# 3) 端到端构建（产出 docx/pptx/html/pdf 四件套）
uv run python scripts/build_all.py --pdf --out /tmp/dla_verify

# 4) Markdown → PDF 直转
uv run python scripts/build_md_pdf.py -i scripts/sample_tencent.md -o /tmp/sample.pdf
```

期望结果：
- `pytest` → `17 passed`
- `selfcheck --build` → `通过 7 项，失败 0 项 / 结果：PASS`
- 构建 → 四件套产物齐全；`sample.pdf` 正常生成

---

## 6. 升级技能（从 GitHub 拉取最新版）

技能发布在 GitHub（`hzh-opc/doc-layout-aesthetics`）。升级脚本从远程拉取最新版并
同步到技能副本，**副本保持干净**：不含 `.git` / `__pycache__` / `.pytest_cache` /
`.DS_Store` / 字体二进制（`fonts/common/`、`fonts/SHA256SUMS` 由用户按需另装）。

```bash
# macOS / Linux —— 升级到 WorkBuddy 技能副本（默认）
bash scripts/upgrade_skill.sh

# 指定目标目录（Claude Code / Codex / OpenClaw 等）
bash scripts/upgrade_skill.sh --target ~/.claude/skills/doc-layout-aesthetics

# 只检查远程是否有新版本（不实际同步）
bash scripts/upgrade_skill.sh --check

# 演练：只看将同步的内容，不实际同步
bash scripts/upgrade_skill.sh --dry-run

# Windows（PowerShell）——默认 WorkBuddy 技能副本
powershell -ExecutionPolicy Bypass -File scripts\upgrade_skill.ps1

# Windows 指定目标 / 只检查
powershell -ExecutionPolicy Bypass -File scripts\upgrade_skill.ps1 -Target "$HOME\.claude\skills\doc-layout-aesthetics"
powershell -ExecutionPolicy Bypass -File scripts\upgrade_skill.ps1 -Check
```

> 依赖：macOS/Linux 需 `git` + `rsync`（系统通常自带）；Windows 需 `git`（robocopy 系统内置）。
> 升级脚本位于 `scripts/upgrade_skill.sh`（macOS/Linux）与 `scripts/upgrade_skill.ps1`（Windows）。

---

## 7. 平台差异与注意事项

| 能力 | WorkBuddy | Claude/Codex/OpenClaw | 说明 |
|---|---|---|---|
| 腾讯文档云端路径（`build_tencent_doc.py`） | ✅ | ⚠️ 不可用 | 依赖 WorkBuddy 的 tencent-docs 插件与票据注入，其他平台无插件会报"未找到 tencentdocs.py" |
| PDF 视觉核验（`render_pdf.swift`） | ✅ macOS | ⚠️ 仅 macOS | 依赖 Swift + PDFKit；Linux/Windows 直接打开 PDF 查看 |
| `docx2pdf` 引擎（Word→PDF） | ✅ Win/macOS | ✅ Win/macOS | 需本机安装 Microsoft Word，`uv sync --extra word` 安装 |
| LibreOffice / WPS 引擎 | ✅ 三平台 | ✅ 三平台 | 自动探测，缺失时回退纯 Python reportlab |

### 7.1 无 uv 时的行为

- `build_all.py` 已做 **uv 缺失回退**：按 `scripts/_venv.py` 解析出的 venv
  （`UV_PROJECT_ENVIRONMENT` > `VIRTUAL_ENV` > 平台默认）→ 当前解释器 → `python3`
  依次探测，只要依赖已装进任一候选即可直接运行。
- 文档内示例命令优先展示 `uv run`，若用 venv 路线，把 `uv run python` 换成
  `python`（在已激活的 venv 中）即可。

### 7.2 常见问题（FAQ）

| 问题 | 原因与解决 |
|---|---|
| `postscript outlines are not supported` | reportlab 不支持 CFF 轮廓字体（思源/Noto 的 .otf）。脚本已自动跳过 CFF 改用它字体（文楷/文泉驿），属**正常告警**，无需处理 |
| `未检测到开源可商用中文字体` | 本机未装开源字体，回退系统字体并告警。按第 4 节安装即可消除 |
| `❌ 依赖缺失: docx(...)` | venv 未建好。按第 3.2 节执行 `uv sync` 或 `pip install python-docx python-pptx reportlab pytest` |
| Windows 控制台 emoji 乱码 | 脚本已统一 stdout 为 UTF-8；若仍异常请确认终端为 UTF-8（`chcp 65001`） |
| `git clone 失败` | 网络不通或仓库地址错误。检查网络后重试；`--repo` 可指定镜像地址 |
| venv 出现在 `C:\c\Users\...`（多一层 `c\`） | 仅 **Windows + Git Bash**：手动 `uv sync` 时 `~` 被展开成 POSIX 路径 `/c/Users/...`，被 Windows 版 uv 误解析为 `C:\c\Users\...`。改用显式 Windows 原生路径 `UV_PROJECT_ENVIRONMENT=C:/Users/$USER/.workbuddy/caches/doc-layout-aesthetics/.venv uv sync`，或加 `MSYS_NO_PATHCONV=1` 前缀。走 `python scripts/build_all.py` 不受影响 |

---

## 8. 目录速览

```
doc-layout-aesthetics/
├── SKILL.md                    # 技能定义（frontmatter + 使用说明）
├── pyproject.toml              # Python 项目定义（依赖 / pytest 配置）
├── uv.lock                     # uv 锁定依赖
├── references/
│   └── aesthetics-spec.md      # 完整美学规范（七大原则 + 自查清单 + 反模式）
├── scripts/
│   ├── _venv.py                # 虚拟环境解析（UV_PROJECT_ENVIRONMENT > VIRTUAL_ENV > 平台默认）
│   ├── build_all.py            # 统一入口（docx/pptx/html/pdf）
│   ├── build_docx.py           # Word 精排（表格跨页保护）
│   ├── build_pptx.py           # PPT 对照演示
│   ├── build_html.py           # 响应式 HTML
│   ├── build_pdf.py            # docx→PDF（引擎链 LibreOffice>docx2pdf>WPS>reportlab）
│   ├── build_md_pdf.py         # Markdown→PDF 直转（纯 reportlab）
│   ├── build_tencent_doc.py    # 腾讯文档云端（仅 WorkBuddy）
│   ├── sample_tencent.md       # 腾讯文档示例输入
│   ├── selfcheck.py            # 冒烟自检
│   ├── upgrade_skill.sh        # 升级脚本（macOS/Linux，从 GitHub 拉取并同步副本）
│   ├── upgrade_skill.ps1       # 升级脚本（Windows PowerShell）
│   └── render_pdf.swift        # PDF→PNG 视觉核验（仅 macOS）
├── tests/                      # pytest 用例（17 例）
├── fonts/                      # 字体安装脚本 + 平台指南
└── FONTS.md                    # 字体清单（官方源 + 国内源 + 许可）
```
