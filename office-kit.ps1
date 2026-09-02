# office-kit 统一入口（Windows PowerShell）
#
# 动态分发：委托 kit.py 扫描 components/*/manifest.json 生成"功能记录"后调用对应组件。
# 与 office-kit.sh 行为一致，达成双平台入口统一（含此前缺失的 doc-layout 美化命令）。
#
# 用法:
#   .\office-kit.ps1 <command> [组件参数...]
#   抽取处理链: extract / desen / summarize
#   美化交付:   md-pdf / docx / pptx / html / render
#   治理:       list | overlaps | doctor | feedback | run <command>
param(
  [Parameter(Position=0, Mandatory=$false)] [string]$Command,
  [Parameter(Position=1, ValueFromRemainingArguments=$true)] [string[]]$Args
)
$KitDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPy = Join-Path $KitDir ".venv\Scripts\python.exe"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $KitDir ".venv"
if (Test-Path $VenvPy) { $Py = $VenvPy } else { $Py = "python" }
if (-not $Command) { $Command = "list" }
& $Py (Join-Path $KitDir "kit.py") $Command @Args
