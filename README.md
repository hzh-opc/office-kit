# office-kit · 合并办公工具包

把 `info-extract`（转录/OCR/视频/画面解读）、`desensitization-sop`（脱敏）、`summarize`（摘要/提炼）、
`doc-layout-aesthetics`（排版美化交付）合并为一个按办公业务流程组织的工作台，组件可独立更新，跨平台可移植。
由 `uv` 管理虚拟环境。

## 目录结构

```
office-kit/
├── pyproject.toml            # uv 项目文件（uv add 管理依赖）
├── uv.lock                   # 锁定依赖版本
├── .venv/                    # uv 创建的虚拟环境（不入库，按机器重建）
├── components/               # 组件（可独立替换更新）
│   ├── info-extract/         #   转录 / OCR / 视频 / 画面解读
│   ├── desensitization-sop/  #   脱敏（本地优先、数据不出本机）
│   ├── summarize/            #   摘要 / 提炼（纯本地、零依赖可选增强）
│   └── doc-layout-aesthetics/#   排版美化交付（docx / pptx / html / pdf，Markdown→PDF 直转）
├── workbench/                # 单一工作台，按业务流程阶段组织
│   ├── inbox/                #   待处理输入
│   ├── extract/              #   抽取产物
│   ├── desen/                #   脱敏产物
│   ├── summary/              #   摘要产物
│   ├── render/               #   排版美化后的交付物（PDF/PPT/Word/HTML）
│   ├── archive/              #   归档
│   └── logs/                 #   运行日志
├── config/                   # 本地配置（.env.example 为样例，.env 不入库）
├── hooks/                    # 安全钩子（desen-stop：Stop 时扫描外发动作的兜底检测）
│   └── desen-stop/
├── skills/                   # 触发壳资产（随仓库分发，可选部署到 ~/.workbuddy/skills/）
│   └── desen-trigger/        #   跨场景 DESEN 触发壳（非办公场景的敏感/外发闸门入口）
├── office-kit.sh             # 统一入口（macOS / Linux）
├── office-kit.ps1            # 统一入口（Windows）
├── kit.py                    # 动态注册与分发器（扫描 manifest.json，生成"功能记录"）
├── bootstrap.sh              # 一键初始化（macOS / Linux）：建 venv + 装依赖 + 修复组件
├── bootstrap.ps1             # 一键初始化（Windows）
└── ogit                      # git 包装器（统一入口，已配置免锁）
```

## 环境要求

- Python 3.10–3.13（受管解释器已用 3.13.12；`onnxruntime`/`faster-whisper` 无 free-threaded wheel，故锁 <3.14）
- [uv](https://github.com/astral-sh/uv)（跨平台包/环境管理器）
- 可选：ollama（画面解读 VLM）、yt-dlp（在线视频下载）
- 可选（Word→PDF）：`docx2pdf`（Windows/macOS 需本机安装 Word；Linux 不可用）

## 安装 / 重建环境（一键初始化）

提供幂等、可重复执行的一键脚本，自动完成"创建 venv → 安装依赖 → 校验/修复组件"三步：

```bash
# macOS / Linux
cd office-kit
./bootstrap.sh                 # 常规初始化（.venv 已存在则跳过创建）
./bootstrap.sh --force-venv    # 强制删除并重建 .venv

# Windows (PowerShell)
.\bootstrap.ps1
.\bootstrap.ps1 -ForceVenv
```

脚本行为：
1. 用 `uv venv --python 3.13` 创建 `.venv`（显式锁定 `UV_PROJECT_ENVIRONMENT=.venv`，避免被宿主环境劫持到全局 venv）；
2. 修复/补齐组件：缺失/损坏时在线下载（复用 `kit.py repair`，与 `check`/`upgrade` 同一套远程源设计）；
3. 合并 `components/*/requirements.txt` 并 `uv pip install --index-url <国内源>` 安装全部依赖；
4. 校验四个组件目录，并补齐 `workbench/` 阶段子目录（inbox/extract/desen/summary/render/archive/logs）。

> **国内源优先**（规划文档 L18）：默认 PyPI 走清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`、HuggingFace 走 `https://hf-mirror.com`（供 `faster-whisper` 等大模型下载）。
> 可用环境变量覆盖：`OFFICE_KIT_PYPI_MIRROR`（PyPI）、`OFFICE_KIT_HF_MIRROR`（HF）。恢复官方源：`OFFICE_KIT_PYPI_MIRROR=https://pypi.org/simple`。

> 注：三组件 requirements.txt 已合并去重装进同一个 `.venv`；doc-layout 仅新增 `reportlab`。
> 如需 Word→PDF 的 `docx2pdf`（Windows/macOS 需本机安装 Word），可单独 `uv pip install docx2pdf`。

## 使用（统一入口）

```bash
# macOS / Linux
./office-kit.sh extract   --type transcript audio.mp3 --out workbench/extract/
./office-kit.sh desen     scan  workbench/extract/report.docx
./office-kit.sh summarize workbench/desen/report.txt --brief --tldr

# 排版美化交付（doc-layout-aesthetics）
./office-kit.sh md-pdf -i workbench/summary/report.md -o workbench/render/report.pdf -t "报告标题"
./office-kit.sh docx   --out workbench/render/     # 生成《版面美学观》精排 Word 样例
./office-kit.sh pptx   --out workbench/render/     # 生成精排 PPT 样例
./office-kit.sh html   --out workbench/render/     # 生成响应式 HTML 样例
./office-kit.sh render --out workbench/render/     # 一键构建 docx/pptx/html（加 --pdf 含 PDF）

# Windows (PowerShell)
.\office-kit.ps1 extract   --type ocr image.png
.\office-kit.ps1 desen     run    workbench/inbox/doc.pdf
.\office-kit.ps1 md-pdf    -i workbench/summary/doc.md -o workbench/render/doc.pdf
```

也可直接调用组件脚本（需显式用 `.venv/bin/python`）：

```bash
.venv/bin/python components/doc-layout-aesthetics/scripts/build_md_pdf.py \
  -i workbench/summary/doc.md -o workbench/render/doc.pdf -t "标题"
```

> 说明：`md-pdf` 是通用转换器（读外部 Markdown → 排版 PDF，reportlab 内置 CJK 字体，跨平台开箱即用）；
> `docx`/`pptx`/`html`/`render` 当前以内置《版面美学观》样例为输入生成演示交付物，若要转用户自有内容，
> 需扩展对应脚本使其接受 `-i` 输入（沿用 `build_md_pdf.py` 的入参范式即可）。

## 组件治理（动态注册 / 重叠比对 / 反馈）

工具包采用「可拆卸」模块化：`kit.py` 启动时**扫描 `components/*/manifest.json`**，自动生成"功能记录"
（命令 → 组件 → 入口的映射），取代手写静态分发。新增/移除组件只需增删其目录与 `manifest.json`，无需改入口脚本。

```bash
python kit.py                 # 列出全部已注册命令（含入口路径）
python kit.py list            # 同上
python kit.py overlaps        # 列出跨组件功能重叠（capabilities 标签比对）
python kit.py doctor          # 环境与组件自检：venv 解释器 + 各组件/入口完整性
python kit.py check           # 检测组件完整性（本地）+ 新版本（远程），只读、不下载
python kit.py upgrade         # 在线升级组件到远程最新版（--force 强制同步 / --yes 跳过确认）
python kit.py repair          # 在线修复损坏/缺失组件（--yes 跳过确认）
python kit.py run extract ... # 显式分发（run 可省略，直接 <command> 即可）
python kit.py extract ... --dry-run   # 仅打印将执行的命令，不真正运行

# 组件问题反馈（规划文档 L13）：生成含组件名的反馈文档到 workbench/feedback/
python kit.py feedback --component info-extract \
  --title "OCR 中文标点丢失" --detail "..." --severity high --repro "router.py 扫描件.pdf"
```

- **动态注册**：每个组件在 `manifest.json` 声明 `component` / `capabilities` / `commands`（含 `name`、`aliases`、`entry`、`category`、`description`）。`kit.py` 据此分发，双平台入口 `office-kit.sh` / `office-kit.ps1` 均委托它，行为一致。
- **重叠比对**：`capabilities` 标签被 ≥2 个组件声明即判为重叠，`python kit.py overlaps` 自动检出；逐项比对与"更佳调用方案"裁决见开发工作区 `规划文档/功能重叠比对.md`（如 `pdf-text-extract` / `office-text-extract` 在 `info-extract` 与 `desensitization-sop` 重叠，敏感文档优先 `desen`）。
- **反馈文档**：调用组件发现问题（不改组件本体）时，用 `feedback` 生成带组件名、时间、严重度、环境、复现步骤的结构化文档，便于反馈给组件开发者；分发/自检失败时也会提示使用该命令。
- **升级/修复**：`check` 检测组件损坏（manifest/入口/标志文件缺失）与远程新版本；`upgrade` / `repair` 在线下载修复，更新后自动重识能力并记录上下游对接（`workbench/logs/component-registry.json`）与操作流水（`component-events.log`），旧版自动归档到 `workbench/archive/components/`。详见下方「组件升级 / 修复」。

## 跨组件闭环

`summarize` 会自动发现同包内的 `desensitization-sop`（扫描 `components/` 目录），
实现「脱敏 → 处理 → 回填 → 复核」链路。合并包内已内置该发现逻辑，无需 WorkBuddy。

## DESEN 跨场景触发壳（skills/desen-trigger）

套件内的外发门禁（`kit.py` 按 `manifest` 的 `commands[].external` 建门禁）覆盖「办公抽取」链路；
但「非办公场景」的敏感动作（表格云解析 sheetagent、发邮件、联网搜索、纯对话中的 PII、财务/审计底稿等）
不在办公元技能 description 触发词内，Agent 可能不联想 desen → 静默失效。

`skills/desen-trigger/` 是为此准备的**触发转发壳**（纯 SKILL.md，无组件本体，不复制 desen、不双轨）：
把「脱敏 / 上云 / 财务敏感」从办公抽取词里拆出单列，让 desen 可被任意场景独立命中，命中后转发到
`components/desensitization-sop` 权威实现。

- **可选部署**：把 `skills/desen-trigger/` 整目录 copy 到用户级技能目录 `~/.workbuddy/skills/`
  （实目录 copy，非 symlink）。不部署不影响套件内门禁；部署后可让非办公场景的敏感动作也能被准确触发。
- **权威实现唯一**：始终走 `components/desensitization-sop/`（勿调用旧独立副本）。

## 组件升级 / 修复（在线）

`kit.py` 内置远程源（默认 `hzh-opc/office-kit@main`，公开仓库匿名下载；可用环境变量 `OFFICE_KIT_REPO` / `OFFICE_KIT_BRANCH` 覆盖为私有仓库/镜像）。每个组件在 `manifest.json` 声明 `version`，据此做版本比对与损坏检测。

```bash
python kit.py check                      # 检测：本地完整性 + 远程新版本（只读）
python kit.py check --offline            # 仅本地完整性检测（不联网）
python kit.py upgrade                    # 升级全部组件到远程最新版
python kit.py upgrade info-extract --yes # 只升级指定组件，跳过交互确认
python kit.py upgrade --force            # 即使本地已最新也强制重下载同步
python kit.py repair                     # 修复损坏/缺失组件（默认：本地目录 ∪ 远程清单）
python kit.py repair summarize --yes     # 修复指定组件
```

- **检测**：`check` 比对 `components/*/manifest.json` 的 `version` 与远程 `main` 分支同名清单；本地损坏 = 目录缺失 / manifest 无法解析 / 命令入口缺失 / 标志文件（`SKILL.md`）缺失。
- **下载**：`upgrade` / `repair` 从远程 tarball 抽取目标组件覆盖安装；旧版先归档到 `workbench/archive/components/`（非硬删），更新后自动清理 `__pycache__`。
- **能力识别与上下游对接**：更新后重新扫描 manifest 识别组件能力（命令/能力标签），并更新 `workbench/logs/component-registry.json`（上游来源 repo/branch/version + 下游命令/能力/组件间共享能力）与 `component-events.log`（操作流水）。
- **依赖变化**：升级后若组件 `requirements.txt` 变化，需重跑 `./bootstrap.sh` 重装依赖（脚本会提示）。

> 离线场景（无网）仍可手动替换：`cp -R /path/to/new-desensitization-sop/* components/desensitization-sop/`，再 `uv add -r components/desensitization-sop/requirements.txt` 补装依赖。
> `doc-layout-aesthetics` 自带 `pyproject.toml` + `uv.lock`，与其上游同步时直接覆盖 `components/doc-layout-aesthetics/` 即可。

## 跨平台可移植

- 路径全部相对/环境变量化，未写死绝对路径
- `.venv` 不入库，按机器 `uv venv` + `uv add` 重建
- 入口脚本分别提供 `sh`（Unix）与 `ps1`（Windows），venv 解释器路径按平台自动适配
- 密钥经 `config/.env` 注入，不进仓库、不进对话
- **字体**：doc-layout 渲染依赖系统字体。跨平台首次使用请运行对应安装脚本
  （`components/doc-layout-aesthetics/fonts/install_fonts.{sh,ps1}`）；
  `md-pdf`（reportlab）内置 CJK 字体，无需额外安装即可输出中文 PDF

## Git 操作约定

工具包内置 `ogit` 包装器，统一加 `--no-optional-locks` 执行 git，以绕过环境的 lock 写保护并避免误用宿主全局 git 配置：

```bash
./ogit status
./ogit add -A
./ogit commit -m "描述"
```

> 默认分支 `main`。推送远程需显式授权：`git push -u origin main`（首次推送前请确认 origin 已指向你的仓库，且已获得授权）。
