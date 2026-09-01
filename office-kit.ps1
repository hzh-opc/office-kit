# office-kit 统一入口（Windows PowerShell）
# 用法: .\office-kit.ps1 <component> [参数...]
#   extract   -> info-extract
#   desen     -> desensitization-sop
#   summarize -> summarize
param(
  [Parameter(Position=0, Mandatory=$true)] [string]$Component,
  [Parameter(Position=1, ValueFromRemainingArguments=$true)] [string[]]$Args
)
$KitDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPy = Join-Path $KitDir ".venv\Scripts\python.exe"
switch ($Component) {
  "extract"    { & $VenvPy (Join-Path $KitDir "components\info-extract\scripts\router.py") @Args }
  "desen"      { & $VenvPy (Join-Path $KitDir "components\desensitization-sop\scripts\desensitize.py") @Args }
  "summarize"  { & $VenvPy (Join-Path $KitDir "components\summarize\scripts\summarize.py") @Args }
  default {
    Write-Host "用法: .\office-kit.ps1 <extract|desen|summarize> [参数...]"
    exit 1
  }
}
