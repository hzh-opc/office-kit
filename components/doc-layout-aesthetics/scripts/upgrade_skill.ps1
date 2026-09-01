<#
=============================================================================
doc-layout-aesthetics 升级脚本（Windows / PowerShell 5.1+）

从 GitHub 远程仓库拉取最新版，同步到技能副本（默认 %USERPROFILE%\.workbuddy\skills\...）。
副本保持干净：不含 .git / __pycache__ / .pytest_cache / .DS_Store /
字体二进制（fonts\common\、fonts\SHA256SUMS 由用户按需另装）。

用法：
  .\upgrade_skill.ps1                    # 默认升级到 WorkBuddy 技能副本
  .\upgrade_skill.ps1 -Target DIR        # 指定技能副本目录
  .\upgrade_skill.ps1 -Repo URL          # 指定仓库地址（默认 GitHub 官方）
  .\upgrade_skill.ps1 -Branch main       # 指定分支（默认 main）
  .\upgrade_skill.ps1 -DryRun            # 只拉取并展示将同步的内容
  .\upgrade_skill.ps1 -Check             # 只检查远程是否有新版本

兼容性：PowerShell 5.1+（Windows 10/11 自带），依赖 git + robocopy（系统内置）。
=============================================================================
#>
param(
    [switch]$DryRun,
    [switch]$Check,
    [string]$Target = "",
    [string]$Repo = "https://github.com/hzh-opc/doc-layout-aesthetics",
    [string]$Branch = "main",
    [switch]$NoClean
)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Target) {
    $Target = Join-Path $env:USERPROFILE ".workbuddy\skills\doc-layout-aesthetics"
}
if (-not $Repo) { $Repo = "https://github.com/hzh-opc/doc-layout-aesthetics" }
if (-not $Branch) { $Branch = "main" }

function Info  { Write-Host "[升级] $args" -ForegroundColor Green }
function Warn  { Write-Host "[警告] $args" -ForegroundColor Yellow }
function Fail  { Write-Host "[错误] $args" -ForegroundColor Red; exit 1 }

# ---------- 检查 git ----------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "未找到 git，请先安装 Git for Windows（https://git-scm.com/download/win）"
}

# ---------- Check 模式：比较远程与本地 ----------
if ($Check) {
    if (-not (Test-Path $Target)) {
        Write-Host "技能副本不存在: $Target（可运行 -DryRun 或直接升级完成首次安装）"
        exit 0
    }
    if (Test-Path (Join-Path $Target ".git")) {
        Push-Location $Target
        git fetch origin $Branch 2>$null | Out-Null
        $localVer = (git rev-parse --short HEAD 2>$null)
        Pop-Location
    } else {
        $localVer = "未知（副本非 git 克隆）"
    }
    $remoteVer = (git ls-remote $Repo "refs/heads/$Branch" 2>$null).Substring(0, 7)
    Write-Host "本地版本: $localVer"
    Write-Host "远程版本: $remoteVer"
    if ($localVer -ne $remoteVer) { Write-Host "有可用更新 ✅" } else { Write-Host "已是最新 ✅" }
    exit 0
}

# ---------- 拉取到临时目录 ----------
$Tmp = Join-Path $env:TEMP ("dla_upgrade_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
    $RepoDir = Join-Path $Tmp "repo"
    Info "拉取仓库: $Repo (branch=$Branch)"
    git clone --depth 1 --branch $Branch $Repo $RepoDir 2>$null
    if (-not $?) { Fail "git clone 失败：请检查网络或仓库地址" }
    $Version = (git -C $RepoDir rev-parse --short HEAD)
    Info "远程最新提交: $Version"

    # ---------- 校验结构 ----------
    if (-not (Test-Path (Join-Path $RepoDir "SKILL.md"))) {
        Fail "拉取结果缺少 SKILL.md，仓库结构异常，中止"
    }

    # ---------- 清理 ----------
    if (-not $NoClean) {
        Remove-Item -Recurse -Force (Join-Path $RepoDir ".git") -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RepoDir -Recurse -Directory -Filter "__pycache__" |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RepoDir -Recurse -Directory -Filter ".pytest_cache" |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $RepoDir -Recurse -File -Filter ".DS_Store" |
            Remove-Item -Force -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force (Join-Path $RepoDir "fonts\common") -ErrorAction SilentlyContinue
        Remove-Item -Force (Join-Path $RepoDir "fonts\SHA256SUMS") -ErrorAction SilentlyContinue
    }

    # ---------- DryRun：只展示 ----------
    if ($DryRun) {
        Write-Host "以下文件将同步到 $Target :"
        if (Test-Path $Target) {
            robocopy $RepoDir $Target /L /E /NFL /NDL /NJH /NJS /XD .git __pycache__ .pytest_cache fonts\common /XF *.pyc .DS_Store fonts\SHA256SUMS | Select-Object -First 30
        } else {
            Get-ChildItem $RepoDir -Recurse -File | ForEach-Object {
                $_.FullName.Substring($RepoDir.Length + 1)
            } | Select-Object -First 30
        }
        Write-Host "---"
        Write-Host "dry-run 完成（未实际同步）。实际升级请去掉 -DryRun。"
        exit 0
    }

    # ---------- 实际同步（robocopy 镜像，保持副本干净） ----------
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Info "同步到: $Target"
    robocopy $RepoDir $Target /MIR /NFL /NDL /NJH /XD .git __pycache__ .pytest_cache fonts\common /XF *.pyc .DS_Store fonts\SHA256SUMS
    if ($LASTEXITCODE -ge 8) { Fail "robocopy 同步失败（退出码 $LASTEXITCODE）" }

    # ---------- 收尾验证 ----------
    if (Test-Path (Join-Path $Target "SKILL.md")) {
        Info "升级完成 ✅ 版本: $Version"
        Write-Host "副本内容（不含 .git/缓存/字体）："
        Get-ChildItem $Target -Recurse -File | Where-Object { $_.FullName -notmatch '\\fonts\\' } |
            ForEach-Object { $_.FullName.Substring($Target.Length + 1) } |
            Sort-Object | Select-Object -First 25
        Write-Host ""
        Write-Host "下一步：技能副本已是最新。字体如需安装：.\fonts\install_fonts.ps1 -Online"
    } else {
        Fail "同步后缺少 SKILL.md，升级失败"
    }
}
finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
