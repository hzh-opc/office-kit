# office-kit 一键初始化脚本（Windows PowerShell）
#
# 用途：从零重建或修复 office-kit 运行环境，三步幂等、可重复执行：
#   1) 创建 uv 管理的虚拟环境 .venv（Python 3.13）
#   2) 合并各组件 requirements.txt 并安装全部依赖
#   3) 校验/修复组件（缺失则从 ~/.workbuddy/skills 重新复制）
#
# 前置：已安装 uv（https://docs.astral.sh/uv/）。
# 用法（PowerShell）：
#   .\bootstrap.ps1                 # 常规初始化
#   .\bootstrap.ps1 -ForceVenv      # 强制重建 .venv
param(
  [switch]$ForceVenv
)

$ErrorActionPreference = "Stop"
$KIT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $KIT_DIR

# 显式锁定 venv 路径，避免被宿主环境的 UV_PROJECT_ENVIRONMENT 劫持到全局 venv。
$env:UV_PROJECT_ENVIRONMENT = ".venv"

# ---------- 国内源优先（规划文档 L18，可用环境变量覆盖） ----------
$INDEX_URL = if ($env:OFFICE_KIT_PYPI_MIRROR) { $env:OFFICE_KIT_PYPI_MIRROR } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
$HF_MIRROR = if ($env:OFFICE_KIT_HF_MIRROR) { $env:OFFICE_KIT_HF_MIRROR } else { "https://hf-mirror.com" }
$env:PIP_INDEX_URL = $INDEX_URL
$env:UV_INDEX_URL = $INDEX_URL
$env:HF_ENDPOINT = $HF_MIRROR
Write-Host "     国内源: PyPI=$INDEX_URL  HF=$HF_MIRROR（如需官方源：\$env:OFFICE_KIT_PYPI_MIRROR='https://pypi.org/simple'）"

$PY_BIN = "3.13"
Write-Host ">>> office-kit 初始化开始：KIT_DIR=$KIT_DIR"

# ---------- 1. 创建虚拟环境 ----------
Write-Host "[1/3] 创建虚拟环境 (uv venv --python $PY_BIN)..."
if (Test-Path ".venv") {
  if (-not $ForceVenv) {
    Write-Host "      .venv 已存在，跳过创建（用 -ForceVenv 可重建）"
  } else {
    Write-Host "      -ForceVenv：移除旧 .venv 并重建"
    Remove-Item -Recurse -Force .venv
    uv venv --python $PY_BIN
  }
} else {
  uv venv --python $PY_BIN .venv
}

# ---------- 2. 安装依赖 ----------
Write-Host "[2/3] 合并并安装组件依赖 (uv pip install)..."
$REQ_TMP = Join-Path $env:TEMP "ok_reqs_$(Get-Random).txt"
"" | Set-Content $REQ_TMP
$reqFiles = Get-ChildItem components\*\requirements.txt -ErrorAction SilentlyContinue
if (-not $reqFiles) {
  Write-Error "      ⚠ 未发现任何组件 requirements.txt，无法安装依赖"
  exit 1
}
foreach ($f in $reqFiles) {
  Write-Host "        - $($f.FullName)"
  Get-Content $f.FullName | Add-Content $REQ_TMP
}
uv pip install --index-url $INDEX_URL -r $REQ_TMP
Remove-Item $REQ_TMP -Force

# ---------- 3. 校验 / 修复组件 ----------
Write-Host "[3/3] 校验/修复组件..."
$SRC_ROOT = Join-Path $HOME ".workbuddy\skills"
$COMPONENTS = @("info-extract", "desensitization-sop", "summarize", "doc-layout-aesthetics")
foreach ($comp in $COMPONENTS) {
  if (Test-Path "components\$comp") {
    Write-Host "      ✓ $comp 存在"
  } else {
    $src = Join-Path $SRC_ROOT $comp
    if (Test-Path $src) {
      Write-Host "      + 缺失 $comp，从 $src 重新复制"
      Copy-Item -Recurse $src "components\$comp"
      Get-ChildItem "components\$comp" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    } else {
      Write-Warning "      ⚠ 缺失 $comp，且源 $src 不存在，请手动放入该组件"
    }
  }
}

Write-Host ">>> 初始化完成。"
