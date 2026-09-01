# 字体清单

> 适用于 `doc-layout-aesthetics` 技能（PDF / DOCX / PPTX / HTML 渲染）。
> 全部为**开源可商用**字体（**严禁**宋体/黑体/微软雅黑/楷体/苹方/Arial/Times New Roman/Consolas 等商业系统字体）。

## 1. 概述

本目录为 `doc-layout-aesthetics` 技能配套字体资源包，覆盖脚本涉及的所有开源可商用字体：

| 字体 | 用途 | 脚本引用 | 轮廓类型 | 许可 |
|---|---|---|---|---|
| **思源宋体 SC** (Source Han Serif SC) | 衬线正文 | `build_pdf.py` / `build_md_pdf.py`（理想目标） | **CFF**（OTF） | SIL OFL 1.1 |
| **思源黑体 SC** (Source Han Sans SC) | 无衬线标题 | 同上 | **CFF**（OTF） | SIL OFL 1.1 |
| **霞鹜文楷** (LXGW WenKai) | 楷体/衬线正文 | `build_docx.py` 封面装饰 | **TrueType**（TTF） | SIL OFL 1.1 |
| **文泉驿正黑** (WenQuanYi Zen Hei) | 无衬线兜底 | `build_pdf.py` 兜底 | **TrueType**（TTC） | GPLv2 + font exception |
| **DejaVu Sans Mono** | 等宽（PPTX 代码/表格） | `build_pptx.py` | **TrueType**（TTF） | DejaVu 许可（Bitstream Vera + Arev 补充） |
| **DejaVu Serif / Sans** | 西文 | 备选 | **TrueType**（TTF） | 同上 |

> **重要提示：reportlab 仅支持 TrueType 轮廓（glyf）字体**
>
> `build_pdf.py` / `build_md_pdf.py` 用 `reportlab.pdfbase.ttfonts.TTFont` 加载字体——
> 它**不支持 CFF/PostScript 轮廓**（即 `.otf` 和多数 Linux 发行版 `.ttc`）。直接给 TTFont
> 传思源/Noto 的 .otf 会抛 `postscript outlines are not supported` 异常。
> 脚本 `detect_fonts` 已增加 CFF 检测跳过（`_truetype_outlines`），会读取文件头
> magic（`0x00010000`/ `true` = TrueType；`OTTO` = CFF；`ttcf` 读第一个表头），
> 跳过 CFF 字体并打印可读告警。因此：
> - **思源 OTF** 适用于系统安装、Word/PPT/HTML（仅引用字体名，不嵌入）
> - **PDF（reportlab）** 推荐使用 **文楷（衬线/楷体）+ 文泉驿（无衬线）**
> - macOS/Linux 上 `brew install --cask font-source-han-sans-sc` 装的也是 OTF，
>   同样无法被 reportlab 嵌入 PDF；脚本会自动跳过改用文楷/文泉驿

## 2. 目录结构

```
fonts/
├── common/                  # 跨平台共用字体（macOS/Linux/Windows 均可直接安装）
│   ├── SourceHanSerifSC/    # 思源宋体 SC（OFT/CFF，供 Word/PPT/HTML）
│   ├── SourceHanSansSC/     # 思源黑体 SC（OTF/CFF，供 Word/PPT/HTML）
│   ├── LXGWWenKai/          # 霞鹜文楷（TTF/TrueType，PDF 正文衬线/楷体）
│   ├── DejaVu/              # 等宽/西文（TTF/TrueType，PPTX 代码块）
│   └── WenQuanYi/           # 文泉驿正黑（TTC/TrueType，PDF 无衬线兜底）
├── macos/                   # macOS 平台专用（Homebrew cask 清单与脚本片段）
├── linux/                   # Linux 平台专用（apt/dnf/pacman 包名清单）
├── windows/                 # Windows 平台专用（PowerShell 安装说明）
├── install_fonts.sh         # macOS/Linux 跨平台安装脚本（在线 + 离线）
├── install_fonts.ps1        # Windows 跨平台安装脚本（在线 + 离线）
├── SHA256SUMS               # 所有字体与许可文件的 SHA-256 校验
└── ../FONTS.md              # 本文件（字体清单）
```

## 3. 下载链接（官方源 + 国内源）

### 思源宋体 SC — Source Han Serif SC（2.003R / 2024-11）

| 渠道 | 链接 |
|---|---|
| 官方（GitHub） | https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip |
| **国内 npmmirror**（推荐，**阿里 CDN 满速**） | https://registry.npmmirror.com/@fontpkg/source-han-serif-sc/-/source-han-serif-sc-2.3.1.tgz |
| 国内 ghproxy | https://ghproxy.net/https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip |
| 国内 ghfast | https://ghfast.top/https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip |
| Gitee 镜像（无 release 资产，**仅代码**） | https://gitee.com/mirrors/source-han-serif |

### 思源黑体 SC — Source Han Sans SC（2.005R / 2025-05）

| 渠道 | 链接 |
|---|---|
| 官方（GitHub） | https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip |
| **国内 npmmirror**（推荐） | https://registry.npmmirror.com/@fontpkg/source-han-sans-sc/-/source-han-sans-sc-2.5.0.tgz |
| 国内 ghproxy | https://ghproxy.net/https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip |
| 国内 ghfast | https://ghfast.top/https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip |
| Gitee 镜像（无 release 资产） | https://gitee.com/mirrors/source-han-sans |

### 霞鹜文楷 — LXGW WenKai（v1.522 / 2026-03-17）

| 渠道 | 链接（Regular） |
|---|---|
| 官方（GitHub） | https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf |
| 国内 ghproxy | https://ghproxy.net/https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf |
| 国内 ghfast | https://ghfast.top/https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf |
| Gitee 镜像 | https://gitee.com/lxgw/LxgwWenKai/（建议先确认是否同步 release 资产） |
| 备用（Medium 字重） | https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Medium.ttf |

> **注**：v1.522 release 提供 Regular / Medium / Light（无 Bold，Medium 充当粗体替代）。
> 全部 npm 上的 `lxgw-wenkai-*` 包都是 **woff2 分片**（fontsource 风格），不适合 reportlab。

### 文泉驿正黑 — WenQuanYi Zen Hei（0.9.45）

| 渠道 | 链接 |
|---|---|
| 官方（SourceForge） | https://sourceforge.net/projects/wqy/files/wqy-zenhei/0.9.45%20%28Fighting-state%20RC1%29/wqy-zenhei-0.9.45.tar.gz/download |
| Debian/Ubuntu 包 | `fonts-wqy-zenhei`（含 `wqy-zenhei.ttc`，TrueType 轮廓） |
| TUNA 镜像（apt） | https://mirrors.tuna.tsinghua.edu.cn/help/debian/ |

### DejaVu 字体（2.37 / 2016-07）

| 渠道 | 链接 |
|---|---|
| 官方（GitHub） | https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip |
| Debian/Ubuntu 包 | `fonts-dejavu-core`（含 `DejaVuSansMono.ttf` / `DejaVuSerif.ttf` / `DejaVuSans.ttf`） |
| 国内 ghproxy | https://ghproxy.net/https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip |

## 4. 安装方式

### 4.1 离线安装（推荐，本目录已下载完整字体）

```bash
# macOS / Linux：把 fonts/common/ 下的字体复制到 ~/Library/Fonts 或 ~/.local/share/fonts
bash fonts/install_fonts.sh                          # 自动从 fonts/common/ 离线安装
bash fonts/install_fonts.sh --dir /path/to/fonts    # 指定字体目录
bash fonts/install_fonts.sh --dry-run                # 只列出将安装的文件
```

```powershell
# Windows（PowerShell 5.1+，用户级安装无需管理员）
powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1
powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1 -Online   # 在线下载
powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1 -Mirror china
```

### 4.2 在线安装（包管理器优先，curl 下载兜底）

```bash
# macOS（Homebrew 优先）
bash fonts/install_fonts.sh --online                       # brew cask
bash fonts/install_fonts.sh --online --mirror china        # 失败回退 ghproxy

# Linux
bash fonts/install_fonts.sh --online                       # apt/dnf/pacman 自动检测
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File fonts\install_fonts.ps1 -Online
```

### 4.3 手动安装（验证后用 `shasum -a 256 -c fonts/SHA256SUMS` 校验）

```bash
shasum -a 256 -c fonts/SHA256SUMS  # macOS / Linux
certutil -hashfile <file> SHA256    # Windows（单文件）
```

## 5. 许可协议

| 字体 | 协议 | 商用 | 二次分发 | 链接 |
|---|---|---|---|---|
| 思源宋体/黑体 SC | **SIL OFL 1.1** | ✓ | ✓（保留版权声明即可） | https://openfontlicense.org/open-font-license-official-text/ |
| 霞鹜文楷 | **SIL OFL 1.1** | ✓ | ✓ | 同上 |
| 文泉驿正黑 | **GPLv2 + font exception** | ✓ | ✓（GPL 兼容 + 字体嵌入例外） | https://www.gnu.org/licenses/old-licenses/gpl-2.0.html |
| DejaVu | **Bitstream Vera 许可 + Arev 补充** | ✓ | ✓ | 见 `common/DejaVu/LICENSE` |

> **禁止**把这些字体的源文件当作"商业系统字体"（如宋体/黑体）出售或捆绑入闭源商业产品。
> 详细条款见各字体目录下的 `LICENSE.txt` / `COPYING` 文件。

## 6. 字体与脚本映射表

| 字体 | `build_pdf.py` | `build_md_pdf.py` | `build_docx.py` | `build_pptx.py` | `build_html.py` |
|---|---|---|---|---|---|
| 思源宋体/黑体 SC | 探测目标（CFF 跳过） | 探测目标（CFF 跳过） | 字体名引用 | 字体名引用 | CSS 字体栈 |
| **霞鹜文楷** | 衬线候选（TrueType ✓） | 衬线候选（TrueType ✓） | 装饰标题 | — | — |
| **文泉驿正黑** | 无衬线候选（TrueType ✓） | 无衬线候选（TrueType ✓） | — | — | — |
| **DejaVu Sans Mono** | — | — | — | 等宽 | — |

> 实际渲染 PDF 时，脚本会按 `detect_fonts()` 候选顺序自动选择**第一个可用**的字体。
> 建议同时安装文楷 + 文泉驿 + 思源 OTF（系统级），以兼顾 PDF 嵌入（前者）与 Word/PPT/HTML（后者）。
