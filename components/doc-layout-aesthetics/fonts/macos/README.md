# macOS 平台字体安装

本目录是 `doc-layout-aesthetics` 字体包在 **macOS** 平台上的**专用安装资源**。
跨平台共用的字体二进制（OTF/TTF/TTC）在 `../common/` 下，跨平台安装脚本在
`../install_fonts.sh` / `../install_fonts.ps1`。

## 推荐方式：Homebrew Cask

```bash
# 开源可商用中文字体（TrueType/CFF 注意）
brew install --cask font-source-han-serif-sc font-source-han-sans-sc
brew install --cask font-lxgw-wenkai font-wqy-zenhei
brew install --cask font-dejavu-sans-mono
```

> **重要提示：reportlab 仅支持 TrueType 轮廓**
>
> `font-source-han-serif-sc` / `font-source-han-sans-sc` cask 安装的是 **OTF（CFF）**
> 字体，**不能被** `build_pdf.py` / `build_md_pdf.py`（reportlab）嵌入 PDF——
> 脚本会自动跳过 CFF 改用文楷/文泉驿。思源 OTF 仍可用于 Word/PPT/HTML（仅字体名引用）。
>
> **PDF 嵌入必须用文楷（TrueType）+ 文泉驿（TrueType）**。

## 离线安装（无网络环境）

```bash
bash ../install_fonts.sh   # 从 ../common/ 复制到 ~/Library/Fonts
```

## Homebrew 字体下载慢/失败时

设置 `HOMEBREW_BOTTLE_DOMAIN` 走国内镜像：

```bash
# 清华 TUNA
export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles
# 中科大 USTC
export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.ustc.edu.cn/homebrew-bottles

# cask 下载镜像
export HOMEBREW_API_DOMAIN=https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api
```

## 验证安装

```bash
ls -la ~/Library/Fonts/LXGWWenKai-Regular.ttf ~/Library/Fonts/wqy-zenhei.ttc
# 任意应用（如 TextEdit）切换到 LXGW WenKai 或 WenQuanYi Zen Hei 查看
```
