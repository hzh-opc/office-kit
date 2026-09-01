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
2. 合并 `components/*/requirements.txt` 并 `uv pip install --index-url <国内源>` 安装全部依赖；
3. 校验四个组件目录，缺失则从 `~/.workbuddy/skills/` 重新复制。

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
python kit.py run extract ... # 显式分发（run 可省略，直接 <command> 即可）
python kit.py extract ... --dry-run   # 仅打印将执行的命令，不真正运行

# 组件问题反馈（规划文档 L13）：生成含组件名的反馈文档到 workbench/feedback/
python kit.py feedback --component info-extract \
  --title "OCR 中文标点丢失" --detail "..." --severity high --repro "router.py 扫描件.pdf"
```

- **动态注册**：每个组件在 `manifest.json` 声明 `component` / `capabilities` / `commands`（含 `name`、`aliases`、`entry`、`category`、`description`）。`kit.py` 据此分发，双平台入口 `office-kit.sh` / `office-kit.ps1` 均委托它，行为一致。
- **重叠比对**：`capabilities` 标签被 ≥2 个组件声明即判为重叠，`python kit.py overlaps` 自动检出；逐项比对与"更佳调用方案"裁决见开发工作区 `规划文档/功能重叠比对.md`（如 `pdf-text-extract` / `office-text-extract` 在 `info-extract` 与 `desensitization-sop` 重叠，敏感文档优先 `desen`）。
- **反馈文档**：调用组件发现问题（不改组件本体）时，用 `feedback` 生成带组件名、时间、严重度、环境、复现步骤的结构化文档，便于反馈给组件开发者；分发/自检失败时也会提示使用该命令。

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

## Git 操作约定

工具包内置 `ogit` 包装器，统一加 `--no-optional-locks` 执行 git，以绕过环境的 lock 写保护并避免误用宿主全局 git 配置：

```bash
./ogit status
./ogit add -A
./ogit commit -m "描述"
```

> 默认分支 `main`。推送远程需显式授权：`git push -u origin main`（首次推送前请确认 origin 已指向你的仓库，且已获得授权）。
