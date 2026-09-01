# Windows 平台字体安装

本目录是 `doc-layout-aesthetics` 字体包在 **Windows** 平台上的**专用安装资源**。
跨平台共用的字体二进制（OTF/TTF/TTC）在 `..\common\` 下，跨平台安装脚本在
`..\install_fonts.ps1`。

## 推荐方式：winget（Windows 10/11 自带）

```powershell
# 注意 winget 字体包多为 CFF/OTF，reportlab PDF 不能嵌入——
# 主要用于 Word/PPT/HTML 与系统显示；PDF 仍用文楷 + 文泉驿
winget install Adobe.SourceHanSerifSC
winget install Adobe.SourceHanSansSC
winget install LXGW.LXGWWenKai
winget install --id=Dejavu.Font -e
```

## 离线安装（推荐，零依赖、用户级免管理员）

```powershell
# 用户级安装：%LOCALAPPDATA%\Microsoft\Windows\Fonts + HKCU 注册表
powershell -ExecutionPolicy Bypass -File ..\install_fonts.ps1

# 系统级安装（需管理员 PowerShell）
Start-Process powershell -Verb runAs -ArgumentList "-ExecutionPolicy Bypass -File ..\install_fonts.ps1 -Scope System"

# 验证
powershell -ExecutionPolicy Bypass -File ..\install_fonts.ps1 -DryRun
```

## 手动安装（图形化）

1. 在文件资源管理器打开 `..\common\`
2. 选中所有 `.otf` / `.ttf` / `.ttc` 文件
3. 右键 → "为所有用户安装"（需管理员）或直接双击逐个安装（当前用户）

> **重要提示：reportlab 仅支持 TrueType 轮廓**
>
> 思源宋体/黑体 SC 安装后是 **OTF（CFF）**，**不能被** `build_pdf.py` / `build_md_pdf.py`
> 嵌入 PDF。脚本会自动跳过 CFF 改用文楷（TrueType）+ 文泉驿（TrueType）。
> 思源 OTF 仍可用于 Word/PPT/HTML。

## 验证安装

```powershell
# PowerShell
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\Fonts" | Where-Object { $_.Extension -in ".otf",".ttf",".ttc" } | Select-Object Name
```
