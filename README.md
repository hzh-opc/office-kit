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
├── office-kit.sh             # 统一入口（macOS / Linux）
├── office-kit.ps1            # 统一入口（Windows）
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
2. 合并 `components/*/requirements.txt` 并 `uv pip install -r` 安装全部依赖；
3. 校验四个组件目录，缺失则从 `~/.workbuddy/skills/` 重新复制。

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

## 跨组件闭环

`summarize` 会自动发现同包内的 `desensitization-sop`（扫描 `components/` 目录），
实现「脱敏 → 处理 → 回填 → 复核」链路。合并包内已内置该发现逻辑，无需 WorkBuddy。

## 独立更新组件

每个组件是自包含目录，可单独替换而不影响其他组件：

```bash
# 仅更新脱敏组件（例：从新版本覆盖）
cp -R /path/to/new-desensitization-sop/* components/desensitization-sop/
# 若新版本依赖变化，再补装
uv add -r components/desensitization-sop/requirements.txt
```

`doc-layout-aesthetics` 自带 `pyproject.toml` + `uv.lock`，与其上游同步时直接覆盖 `components/doc-layout-aesthetics/` 即可。

## 跨平台可移植

- 路径全部相对/环境变量化，未写死绝对路径
- `.venv` 不入库，按机器 `uv venv` + `uv add` 重建
- 入口脚本分别提供 `sh`（Unix）与 `ps1`（Windows），venv 解释器路径按平台自动适配
- 密钥经 `config/.env` 注入，不进仓库、不进对话
- **字体**：doc-layout 渲染依赖系统字体。跨平台首次使用请运行对应安装脚本
  （`components/doc-layout-aesthetics/fonts/install_fonts.{sh,ps1}`）；
  `md-pdf`（reportlab）内置 CJK 字体，无需额外安装即可输出中文 PDF

## 仓库与工作区（三仓结构定位）

office-kit 采用**三处仓库**结构，职责分离、互不污染：

- **本地仓库 `~/Repositories/office-kit`（git 源）**：工具包本体的 git 版本库，含真实 `.git`，纳入 git 管理；GitHub 为**唯一提交副本**（本地可随时删除重建，未提交改动无需保留）。
  - 入库范围：源代码、组件、配置样例、入口脚本、依赖声明（`pyproject.toml` / `uv.lock` / `requirements.txt`）、`bootstrap.*`、`ogit`。
  - **不入库**：`.venv/`、`workbench/` 运行产物、`config/.env`、密钥文件（详见 `.gitignore`）。
- **工具仓库 `~/office-kit`（部署 / 干净副本）**：由本地仓库同步而来的**真实可运行副本**，**不含 `.git`**，仅用于部署与日常调用，不承载版本历史。
- **开发工作区 `~/WorkBuddy/Skill-Dev/office-kit`**：与本地仓库平行的开发伴随区，**不含 `.git`**，仅保存开发文档与**隐私隔离**资料——`规划文档/`、`日志/`、`依赖审计报告/` 等过程性文档，不纳入代码仓库，避免污染工具包本体。

> 审计报告、架构决策、阶段性开发日志等过程性文档统一存放于开发工作区；本地仓库内仅保留可复现运行所必需的代码与配置。

### 在本地仓库执行 git 操作

环境对 `~/Repositories/office-kit` 作为工作树的 git 写操作施加了 **lock 写保护**（标准 `git add` / `commit` 会因 `index.lock` / `HEAD.lock` 无法清理而失败，只读操作如 `status` / `rev-parse` 正常）。

已落地解决方案：仓库级配置 `core.optionalLocks = false`，使所有 git 写操作跳过可选锁，无需额外标志。所有操作统一经本地仓库内的 `ogit` 包装器（等价 `git --no-optional-locks`，并避免误用宿主全局 git 配置）：

```bash
cd ~/Repositories/office-kit
./ogit status
./ogit add -A
./ogit commit -m "描述"
```

> 默认分支 `main`。如需彻底重建：删掉 `~/Repositories/office-kit`（本地仓库）与远程仓库，再 `git clone` / 重新放入代码并 `./bootstrap.sh` 即可；`~/office-kit`（部署副本）可随时由本地仓库重新同步生成，`.venv` 与未提交改动均不依赖保留。
>
> 推送 GitHub 需显式授权：`git push -u origin main`（首次推送前请确认 origin 已指向你的仓库，且已获得授权）。
