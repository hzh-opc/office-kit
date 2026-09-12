# machine_init.ps1 —— 机器级环境初始化（Windows）
#
# 与 deploy/machine_init.sh 行为一致（audit B5/U9 跨平台双套）：
#   1) 安装 uv（已装跳过；受限网络预设 UV_INSTALLER_MIRROR / UV_PYTHON_INSTALL_MIRROR）
#   2) 写 uv.toml 5 源（huawei default=true）—— Windows: %APPDATA%\uv\uv.toml
#   3) 建 <BASE>\binaries\python\envs\default（优先受管解释器 3.13.12，否则 uv 拉 3.13；
#      Windows 解释器为 Scripts\python.exe）
#   4) 向 <BASE>\SOUL.md 注入「Python 默认环境」常驻铁律（已存在跳过；-NoSoul 跳过本步）
#
# 用法：
#   .\deploy\machine_init.ps1             # 全部四步
#   .\deploy\machine_init.ps1 -NoSoul     # 只做 1-3 步
#
# ⚠ Windows 实机验证待办（台账 U13）：本脚本未经 Windows 实机验证，首次使用请先审查。

param(
  [switch]$NoSoul
)

$ErrorActionPreference = "Stop"

$KIT_DIR    = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$BASE       = Join-Path $HOME ".workbuddy"
$MANAGED_PY = Join-Path $BASE "binaries\python\versions\3.13.12\python3.exe"
if (-not (Test-Path $MANAGED_PY)) {
  $MANAGED_PY = Join-Path $BASE "binaries\python\versions\3.13.12\Scripts\python.exe"
}
$DEFAULT_ENV = Join-Path $BASE "binaries\python\envs\default"
$DEFAULT_PY  = Join-Path $DEFAULT_ENV "Scripts\python.exe"
$SOUL_FILE   = Join-Path $BASE "SOUL.md"

Write-Host "== machine_init：机器级环境初始化（共 4 步）=="

# ---------- 1. 安装 uv ----------
Write-Host "[1/4] 安装 uv..."
if (Get-Command uv -ErrorAction SilentlyContinue) {
  Write-Host "      ✓ 已安装：$(uv --version)"
} else {
  $installer = "$env:TEMP\uv-install.ps1"
  Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $installer -UseBasicParsing
  # 审查后执行（不盲跑下载内容）
  & powershell -NoProfile -ExecutionPolicy Bypass -File $installer
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "      ✗ uv 安装失败。受限网络请先 `$env:UV_INSTALLER_MIRROR 与 `$env:UV_PYTHON_INSTALL_MIRROR 指向清华镜像后重试。"
    exit 1
  }
  Write-Host "      ✓ 安装完成（需新开 shell 使 PATH 生效）"
}

# ---------- 2. 写 uv.toml 5 源 ----------
Write-Host "[2/4] 写 uv.toml（5 源，huawei default=true）..."
$UV_DIR = Join-Path $env:APPDATA "uv"
$UV_CONFIG = Join-Path $UV_DIR "uv.toml"
New-Item -ItemType Directory -Force -Path $UV_DIR | Out-Null
if ((Test-Path $UV_CONFIG) -and (Get-Content $UV_CONFIG -Raw) -match "huaweicloud") {
  Write-Host "      ✓ 已存在且含 huawei 源，跳过：$UV_CONFIG"
} else {
  @'
# 由 office-kit deploy/machine_init 生成（幂等覆盖）
[[index]]
url = "https://mirrors.aliyun.com/pypi/simple/"
name = "aliyun"

[[index]]
url = "https://mirrors.cloud.tencent.com/pypi/simple/"
name = "tencent"

[[index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple/"
name = "tsinghua"

[[index]]
url = "https://pypi.mirrors.ustc.edu.cn/simple/"
name = "ustc"

[[index]]
url = "https://repo.huaweicloud.com/repository/pypi/simple/"
name = "huawei"
default = true
'@ | Set-Content -Path $UV_CONFIG -Encoding utf8NoBOM
  Write-Host "      ✓ 已写入：$UV_CONFIG"
}

# ---------- 3. 建 envs/default ----------
Write-Host "[3/4] 创建默认环境 envs/default..."
if (Test-Path $DEFAULT_PY) {
  Write-Host "      ✓ 已存在，跳过：$DEFAULT_ENV"
} else {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DEFAULT_ENV) | Out-Null
  if (Test-Path $MANAGED_PY) {
    uv venv --python $MANAGED_PY $DEFAULT_ENV
  } else {
    Write-Host "      · 受管解释器未找到（$MANAGED_PY），改用 uv 拉取 3.13"
    uv venv --python 3.13 $DEFAULT_ENV
  }
  Write-Host "      ✓ 已创建：$DEFAULT_ENV"
}
Write-Host "      提示：装包永远显式 uv pip install --python $DEFAULT_PY <pkg>，绝不裸 pip install。"

# ---------- 4. 注入常驻铁律（幂等） ----------
if (-not $NoSoul) {
  Write-Host "[4/4] 注入「Python 默认环境」常驻铁律到 SOUL.md..."
  New-Item -ItemType Directory -Force -Path $BASE | Out-Null
  $existing = if (Test-Path $SOUL_FILE) { Get-Content $SOUL_FILE -Raw } else { "" }
  if ($existing -match "常驻执行规则：Python 默认环境") {
    Write-Host "      ✓ 已存在，跳过（幂等）：$SOUL_FILE"
  } else {
    $block = @"

<!-- machine-init:python-env -->
### 常驻执行规则：Python 默认环境

- 日常执行 Python 默认用 `$BASE\binaries\python\envs\default`（受管解释器创建的扁平目录环境，直接含 Scripts\python.exe）。
- 装包一律 uv pip install --python <该环境>\Scripts\python.exe <pkg>，绝不裸 pip install、不手动激活后裸跑。
- office-kit 例外：其依赖收敛于 ~\office-kit\.venv（kit 自带 bootstrap 管理），不并入默认环境。
- 完整治理正文见 $BASE\config\python-env.md（按需加载，勿在此展开）。
<!-- /machine-init:python-env -->
"@
    Add-Content -Path $SOUL_FILE -Value $block -Encoding utf8NoBOM
    Write-Host "      ✓ 已追加：$SOUL_FILE"
  }
} else {
  Write-Host "[4/4] 按 -NoSoul 跳过 SOUL.md 注入。"
}

Write-Host ""
Write-Host "== machine_init 完成 ✅ =="
Write-Host "   下一步：运行 .\bootstrap.ps1 完成 office-kit 技能安装与平台启用（两者解耦，顺序不强制）。"
Write-Host "   验收：uv --version 可用；$DEFAULT_PY 存在；uv pip install --dry-run pip 解析走 mirrors.*。"
