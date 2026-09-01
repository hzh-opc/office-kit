<#
=============================================================================
doc-layout-aesthetics 字体安装脚本（Windows / PowerShell 5.1+）

安装渲染 PDF/DOCX/PPTX 所需开源可商用字体：
  思源宋体 SC（衬线正文）· 思源黑体 SC（无衬线标题）· 霞鹜文楷（楷体）
  DejaVu Sans Mono（等宽）· 文泉驿正黑（兜底）

两种模式：
  离线模式（默认）——从脚本同目录 common/ 下已下载的字体文件安装
  在线模式 -Online —— 用 curl.exe 从官方源或国内源下载 zip 后安装

安装范围 -Scope：
  User（默认）——用户级安装（%LOCALAPPDATA%\Microsoft\Windows\Fonts +
    HKCU 注册表），无需管理员权限，当前用户可用
  System       ——系统级安装（C:\Windows\Fonts + HKLM），需要管理员权限

镜像选择 -Mirror：
  official（默认）GitHub / SourceForge 官方源
  china            国内源（ghproxy.net 加速代理）

用法示例：
  .\install_fonts.ps1                       # 离线安装（本目录 common/）
  .\install_fonts.ps1 -Dir D:\fonts         # 从指定目录安装
  .\install_fonts.ps1 -Online               # 在线安装（官方源）
  .\install_fonts.ps1 -Online -Mirror china # 在线安装（国内源）
  .\install_fonts.ps1 -DryRun               # 只列出将安装的文件
  .\install_fonts.ps1 -Scope System         # 系统级安装（需管理员）
=============================================================================
#>
param(
    [switch]$Online,
    [switch]$DryRun,
    [string]$Dir = "",
    [string]$Mirror = "official",
    [ValidateSet("User", "System")]
    [string]$Scope = "User"
)
$ErrorActionPreference = "Stop"

# ---------- 确定字体来源目录 ----------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Dir) { $Dir = Join-Path $ScriptDir "common" }
if (-not (Test-Path $Dir)) {
    Write-Host "错误: 字体目录不存在: $Dir" -ForegroundColor Red
    Write-Host "离线模式请先把字体下载到 fonts\common\，或改用 -Online 在线安装。"
    exit 1
}

# ---------- 收集字体文件 ----------
$Files = Get-ChildItem -Path $Dir -Recurse -File -Include *.otf, *.ttf, *.ttc | Sort-Object Name
if ($Files.Count -eq 0) {
    Write-Host "错误: $Dir 下未找到 .otf/.ttf/.ttc 字体文件" -ForegroundColor Red
    exit 1
}

# ---------- 目标目录与注册表 ----------
if ($Scope -eq "System") {
    $TargetDir  = "$env:WINDIR\Fonts"
    $RegPath    = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    $NeedAdmin  = $true
} else {
    $TargetDir  = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
    $RegPath    = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    $NeedAdmin  = $false
}

function Write-Info { param([string]$m) Write-Host "[安装] $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "[警告] $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "[错误] $m" -ForegroundColor Red; exit 1 }

# ---------- 安装（复制 + 注册表） ----------
function Install-Files {
    param([System.IO.FileInfo[]]$SrcFiles)
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    $i = 0
    foreach ($f in $SrcFiles) {
        $i++
        $name  = $f.Name
        $dest  = Join-Path $TargetDir $name
        if ($DryRun) {
            Write-Host "  [$i/$($SrcFiles.Count)] 将安装 $name -> $dest"
            continue
        }
        Copy-Item -Force $f.FullName $dest
        # 注册表登记（TrueType/OpenType）
        $regName = if ($name -match "\.ttc$") { $name } else { "$name (TrueType)" }
        New-Item -Path $RegPath -Force | Out-Null
        Set-ItemProperty -Path $RegPath -Name $regName -Value $dest -Force
        Write-Info "[$i/$($SrcFiles.Count)] $name"
    }
    if (-not $DryRun) {
        Write-Host "安装完成，共 $($SrcFiles.Count) 个字体 -> $TargetDir" -ForegroundColor Cyan
        if ($Scope -eq "User") {
            Write-Host "提示: 当前用户已注册字体，重启相关应用后生效（无需重启系统）。"
        }
    }
}

# ---------- 在线模式：下载 + 解压 ----------
function Get-FromUrl {
    param([string]$Official, [string]$China)
    if ($Mirror -eq "china") { return $China } else { return $Official }
}

function Download-And-Install {
    Write-Host "在线下载字体（镜像: $Mirror）..." -ForegroundColor Cyan
    $tmp = Join-Path $env:TEMP ("fonts_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $curl = "curl.exe"
    if (-not (Get-Command $curl -ErrorAction SilentlyContinue)) { $curl = "curl" }

    $sansUrl = Get-FromUrl `
        "https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip" `
        "https://ghproxy.net/https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip"
    Write-Host "  [1/5] 思源黑体 SC ..."
    & $curl -fsSL --retry 2 -o "$tmp\shans.zip" $sansUrl

    $serifUrl = Get-FromUrl `
        "https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip" `
        "https://ghproxy.net/https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip"
    Write-Host "  [2/5] 思源宋体 SC ..."
    & $curl -fsSL --retry 2 -o "$tmp\sherif.zip" $serifUrl

    $kaiUrl = Get-FromUrl `
        "https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf" `
        "https://ghproxy.net/https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf"
    Write-Host "  [3/5] 霞鹜文楷 ..."
    & $curl -fsSL --retry 2 -o "$tmp\LXGWWenKai-Regular.ttf" $kaiUrl

    $dejavuUrl = Get-FromUrl `
        "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip" `
        "https://ghproxy.net/https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip"
    Write-Host "  [4/5] DejaVu ..."
    & $curl -fsSL --retry 2 -o "$tmp\dejavu.zip" $dejavuUrl

    $wqyUrl = "https://sourceforge.net/projects/wqy/files/wqy-zenhei/0.9.45%20%28Fighting-state%20RC1%29/wqy-zenhei-0.9.45.tar.gz/download"
    Write-Host "  [5/5] 文泉驿正黑 ..."
    & $curl -fsSL --retry 2 -o "$tmp\wqy.tar.gz" $wqyUrl

    # 解压
    New-Item -ItemType Directory -Path "$tmp\extract" | Out-Null
    if (Test-Path "$tmp\shans.zip")  { Expand-Archive -Force "$tmp\shans.zip"  "$tmp\extract" }
    if (Test-Path "$tmp\sherif.zip") { Expand-Archive -Force "$tmp\sherif.zip" "$tmp\extract" }
    if (Test-Path "$tmp\dejavu.zip") { Expand-Archive -Force "$tmp\dejavu.zip" "$tmp\extract" }
    if (Test-Path "$tmp\wqy.tar.gz") {
        if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
            & tar.exe -xzf "$tmp\wqy.tar.gz" -C "$tmp\extract"
        } else {
            Write-Warn "未找到 tar.exe，跳过文泉驿（可离线模式安装）。"
        }
    }

    $dl = Get-ChildItem -Path "$tmp\extract" -Recurse -File -Include *.otf, *.ttf, *.ttc | Sort-Object Name
    if ($dl.Count -eq 0) { Write-Fail "在线下载解压后未找到字体文件，请检查网络或改用离线模式。" }
    Write-Host "下载并解压到 $($dl.Count) 个字体文件，开始安装..."
    Install-Files $dl
    Remove-Item -Recurse -Force $tmp
}

# ---------- 主流程 ----------
Write-Host "模式: $(if ($Online) {'在线'} else {'离线'}) | 镜像: $Mirror | 范围: $Scope"
Write-Host "来源: $Dir（共 $($Files.Count) 个字体）目标: $TargetDir"

if ($Online) {
    Download-And-Install
} else {
    Install-Files $Files
}
