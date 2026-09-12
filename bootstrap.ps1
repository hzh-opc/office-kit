# office-kit 一键初始化脚本（Windows PowerShell）
#
# 用途：从零重建或修复 office-kit 运行环境，幂等、可重复执行：
#   1) 创建 uv 管理的虚拟环境 .venv（Python 3.13）
#   2) 修复/补齐组件（缺失/损坏时在线下载，复用 kit.py repair；与 kit.py check/upgrade 同一套远程源设计）
#   3) 合并各组件 requirements.txt 并安装全部依赖
#   4) 校验组件 + 补齐 workbench 阶段子目录
#   5) 部署用户级技能与插件包（「文件分发」阶段）：
#        - office-kit 元技能 + desen-trigger 触发壳 → ~/.workbuddy/skills/（强制、幂等，
#          skills/ 为平台技能加载根，部署即被识别生效）
#        - desen-stop Stop Hook 插件包 → ~/.workbuddy/hooks/（强制分发文件）
#   6) 平台生效：把 desen-stop 注册为「本地市场插件」并在 settings.json 启用
#        - 市场目录 ~/.workbuddy/plugins/marketplaces/<市场>/（清单 + 插件副本）
#        - settings.json 的 enabledPlugins 加一行 "<插件>@<市场>": true（幂等，改前自动备份）
#        说明：平台加载插件只需「enabledPlugins 登记 + 能从市场目录解析到插件目录」，
#              无需改 known_marketplaces.json，更无需碰 installed_plugins.json。
#
# 前置：已安装 uv（https://docs.astral.sh/uv/）。第 6 步写 settings.json 需 python。
# 用法（PowerShell）：
#   .\bootstrap.ps1                        # 常规初始化
#   .\bootstrap.ps1 -ForceVenv              # 强制重建 .venv
#   .\bootstrap.ps1 -NoEnableDesenStop      # 只做文件分发，不写 settings.json
#
# 环境变量：OFFICE_KIT_MARKETPLACE（本地市场名，默认 hzh-local）
#
# 注意：本脚本动 .venv / 组件目录 / 用户级 ~/.workbuddy/skills、~/.workbuddy/hooks、
#       ~/.workbuddy/plugins/marketplaces/<市场>/ 与 ~/.workbuddy/settings.json（第 6 步，改前备份），
#       不会触碰 .git 或 workbench 内产物。
#
# 与 bootstrap.sh 的关系：两者行为一致（见 config/skill-dev.md §默认跨平台：shell 须 sh/ps1 双套）。
#   ⚠ 本 ps1 版本未在 Windows 实机验证（维护者仅于 macOS 维护），逻辑与 bootstrap.sh 逐条对齐，
#     如遇差异以 bootstrap.sh 为准并回修本文件。
param(
  [switch]$ForceVenv,
  [switch]$NoEnableDesenStop
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
Write-Host "     国内源: PyPI=$INDEX_URL  HF=$HF_MIRROR（如需官方源：`$env:OFFICE_KIT_PYPI_MIRROR='https://pypi.org/simple'）"

$PY_BIN = "3.13"
Write-Host ">>> office-kit 初始化开始：KIT_DIR=$KIT_DIR"

# ---------- 1. 创建虚拟环境 ----------
Write-Host "[1/6] 创建虚拟环境 (uv venv --python $PY_BIN)..."
if (Test-Path ".venv") {
  if (-not $ForceVenv) {
    Write-Host "      .venv 已存在，跳过创建（用 -ForceVenv 可重建）"
  } else {
    Write-Host "      -ForceVenv：移除旧 .venv 并重建"
    Remove-Item -Recurse -Force .venv
    uv venv --python $PY_BIN .venv
  }
} else {
  uv venv --python $PY_BIN .venv
}

# ---------- 2. 修复/补齐组件（缺失/损坏时在线下载，复用 kit.py repair） ----------
Write-Host "[2/6] 修复/补齐组件（缺失/损坏时在线下载）..."
if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Path "kit.py")) {
  python kit.py repair --yes
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "      ⚠ 在线修复未完全成功（请检查网络或远程源）。可稍后手动：python kit.py repair"
  }
} else {
  Write-Host "      ⚠ 未找到 python / kit.py，跳过在线修复（仅作目录存在性校验）："
  foreach ($comp in @("info-extract", "desensitization-sop", "summarize", "doc-layout-aesthetics")) {
    if (Test-Path "components\$comp") {
      Write-Host "      ✓ $comp 存在"
    } else {
      Write-Warning "      ⚠ 缺失组件 ${comp}：请从 office-kit 发布包/源恢复到 components\$comp"
    }
  }
}

# ---------- 3. 安装依赖 ----------
Write-Host "[3/6] 合并并安装组件依赖 (uv pip install)..."
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

# ---------- 4. 校验组件 + 补齐 workbench 目录 ----------
Write-Host "[4/6] 校验组件 + 补齐 workbench 目录..."
foreach ($comp in @("info-extract", "desensitization-sop", "summarize", "doc-layout-aesthetics")) {
  if (Test-Path "components\$comp") {
    Write-Host "      ✓ $comp 存在"
  } else {
    Write-Warning "      ⚠ 仍缺失组件 ${comp}：在线修复未成功，请从 office-kit 发布包/源恢复到 components\$comp"
  }
}

# 补齐 workbench 阶段子目录（.gitignore 忽略产物但保留结构，供流水线串接）
$WB_DIRS = @("inbox", "extract", "desen", "summary", "render", "archive", "logs")
foreach ($d in $WB_DIRS) {
  $dir = Join-Path "workbench" $d
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Write-Host "      + 创建 workbench/$d"
  }
}

# ---------- 5. 部署用户级技能 + 插件包分发（强制，幂等覆盖） ----------
Write-Host "[5/6] 部署用户级技能与插件包（文件分发）..."
$WB_HOME = Join-Path $env:USERPROFILE ".workbuddy"
$SKILLS_DIR = Join-Path $WB_HOME "skills"
$HOOKS_DIR = Join-Path $WB_HOME "hooks"
New-Item -ItemType Directory -Force -Path $SKILLS_DIR, $HOOKS_DIR | Out-Null

function Install-SkillFromKit {
  param([string]$Name)
  $src = Join-Path $KIT_DIR "skills\$Name"
  if (-not (Test-Path $src)) {
    Write-Warning "      ⚠ 仓库缺失 skills\$Name，跳过"
    return
  }
  $dst = Join-Path $SKILLS_DIR $Name
  if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
  Copy-Item -Recurse -Force $src $dst
  $ver = ""
  $skillMd = Join-Path $dst "SKILL.md"
  if (Test-Path $skillMd) {
    $line = Select-String -Path $skillMd -Pattern '^version' -List | Select-Object -First 1
    if ($line) { $ver = $line.Line -replace '^version:\s*', '' }
  }
  Write-Host "      ✓ 已部署/更新技能: $Name ($ver)"
}

# 5a. office-kit 元技能（统一编排入口，门禁覆盖 office-kit 命令）
Install-SkillFromKit -Name "office-kit"

# 5b. desen-trigger 跨场景触发壳（覆盖非办公场景：云端生成/邮件/表格云解析/联网等）
Install-SkillFromKit -Name "desen-trigger"

# 5c. desen-stop Stop Hook 插件包（会话结束兜底拦截「无脱敏留痕的外发」）
#     desen-stop 是标准 Hook 插件包（.codebuddy-plugin/plugin.json 契约）。
#     本步只做「文件分发」到 ~/.workbuddy/hooks/（供查阅 / 手动导入）；
#     真正让平台加载其 Stop hook 的是【第 6 步】（本地市场 + enabledPlugins 启用）。
if (Test-Path (Join-Path $KIT_DIR "hooks\desen-stop")) {
  $hookDst = Join-Path $HOOKS_DIR "desen-stop"
  if (Test-Path $hookDst) { Remove-Item -Recurse -Force $hookDst }
  Copy-Item -Recurse -Force (Join-Path $KIT_DIR "hooks\desen-stop") $hookDst
  Write-Host "      ✓ 已分发 desen-stop 插件包 -> $hookDst"
} else {
  Write-Warning "      ⚠ 仓库缺失 hooks\desen-stop，跳过"
}
Write-Host "      （技能为幂等覆盖、重跑即同步仓库最新版）"

# ---------- 6. 平台生效：注册本地市场 + 启用 desen-stop（幂等） ----------
#     ⚠️ 机制（2026-09-12 实证，详见 troubleshooting/plugin-enable.md）：
#       仅写 `enabledPlugins` +「市场目录」是「假闸门」——平台只计数、市场未注册，
#       插件从不真正执行。真正生效必须靠官方 CLI：
#         ① `plugin marketplace add <市场目录>`  → 在 known_marketplaces.json 注册（type:directory）
#         ② `plugin install <插件>@<市场>`       → 写 installed_plugins.json 并在
#                                                   plugins/cache/<市场>/<插件>/<版本>/ 生成执行副本
#       本步先文件分发（市场目录 + marketplace.json + enabledPlugins 登记，作为清单/兜底），
#       再用 CLI 真正注册并安装（③）；CLI 须在干净环境运行（剥离 SANDBOX_BROKER 变量，否则静默挂起）。
#       详见 hooks/desen-stop/平台启用指引.md / troubleshooting/plugin-enable.md。
Write-Host "[6/6] 注册本地市场并启用 desen-stop 插件..."
if ($NoEnableDesenStop) {
  Write-Host "      · 已按 -NoEnableDesenStop 跳过（仅完成文件分发；启用指引见 hooks\desen-stop\平台启用指引.md）"
} elseif (-not (Test-Path (Join-Path $KIT_DIR "hooks\desen-stop"))) {
  Write-Warning "      ⚠ 仓库缺失 hooks\desen-stop，跳过启用"
} else {
  $MARKET_NAME = if ($env:OFFICE_KIT_MARKETPLACE) { $env:OFFICE_KIT_MARKETPLACE } else { "hzh-local" }
  $MARKET_DIR = Join-Path (Join-Path $WB_HOME "plugins\marketplaces") $MARKET_NAME
  New-Item -ItemType Directory -Force -Path (Join-Path $MARKET_DIR ".codebuddy-plugin") | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $MARKET_DIR "plugins") | Out-Null
  $pluginDst = Join-Path $MARKET_DIR "plugins\desen-stop"
  if (Test-Path $pluginDst) { Remove-Item -Recurse -Force $pluginDst }
  Copy-Item -Recurse -Force (Join-Path $KIT_DIR "hooks\desen-stop") $pluginDst
  # 清理复制带入的运行时残留（不影响插件契约文件）
  Get-ChildItem -Recurse -Force -File $pluginDst -Filter ".DS_Store" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
  $inUse = Join-Path $pluginDst ".in_use"
  if (Test-Path $inUse) { Remove-Item -Recurse -Force $inUse -ErrorAction SilentlyContinue }
  Write-Host "      ✓ 市场目录: $MARKET_DIR"

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    # 用独立脚本文件承载逻辑（PowerShell 无 heredoc；避免行内长代码与引号转义问题）
    $pyScript = @'
import json, os, shutil, sys
from datetime import date
from pathlib import Path

PLUGIN = "desen-stop"
market = os.environ["OFFICE_KIT_MARKET_NAME"]
market_dir = Path(os.environ["OFFICE_KIT_MARKET_DIR"])
base = Path(os.path.expanduser("~/.workbuddy"))

# ---- ① 市场清单（按插件名合并，保留既有其它插件条目；幂等覆盖） ----
manifest = market_dir / ".codebuddy-plugin" / "marketplace.json"
doc = {
    "name": market,
    "description": "本机自建插件市场（本地目录源）",
    "owner": {"name": os.environ.get("USERNAME") or os.environ.get("USER") or "local"},
    "plugins": [],
}
if manifest.is_file():
    try:
        old = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(old.get("plugins"), list):
            doc["plugins"] = [p for p in old["plugins"] if isinstance(p, dict)]
        for key in ("description", "owner"):
            if old.get(key):
                doc[key] = old[key]
    except Exception as exc:  # 清单损坏则重建，不阻塞
        print("      ⚠ 市场清单解析失败（将重建）: %s" % exc)
entry = {
    "name": PLUGIN,
    "description": "Stop Hook 插件：会话结束前检测「上云/外发已做却无 desen 脱敏留痕」",
    "source": "./plugins/%s" % PLUGIN,
    "category": "security",
    "version": "1.0.0",
}
doc["plugins"] = [p for p in doc["plugins"] if p.get("name") != PLUGIN] + [entry]
manifest.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("      ✓ 市场清单: %s" % manifest)

# ---- ② settings.json 启用登记（幂等；改动前备份；原子替换；不动其它键） ----
settings = base / "settings.json"
plugin_key = "%s@%s" % (PLUGIN, market)
if settings.is_file():
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8"))
    except Exception as exc:
        print("      ⚠ settings.json 解析失败，跳过启用（未改动原文件）: %s" % exc)
        sys.exit(0)
    created = False
else:
    cfg, created = {}, True
if not isinstance(cfg, dict):
    print("      ⚠ settings.json 顶层不是对象，跳过启用（未改动原文件）")
    sys.exit(0)
enabled = cfg.get("enabledPlugins")
if not isinstance(enabled, dict):
    enabled = {}
    cfg["enabledPlugins"] = enabled

if enabled.get(plugin_key) is True:
    print("      · settings.json 已登记 %s（无需写入）" % plugin_key)
else:
    if not created:
        bak = settings.with_name("%s.bak-%s-desen" % (settings.name, date.today().isoformat()))
        if not bak.exists():
            shutil.copy2(settings, bak)
            print("      ✓ 已备份 settings.json -> %s" % bak.name)
    enabled[plugin_key] = True
    tmp = settings.with_name(settings.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(settings))
    print("      ✓ 已启用 %s（settings.json%s）" % (plugin_key, "（本次新建）" if created else ""))
    print("      ⚠ 插件在【会话启动时】加载：请重启 WorkBuddy / 新开会话后生效")
'@
    $pyFile = Join-Path $env:TEMP "office_kit_register_desen_stop.py"
    # 显式 UTF-8 无 BOM 落盘（PS 5.1 的 -Encoding UTF8 会带 BOM）
    [System.IO.File]::WriteAllText($pyFile, $pyScript, (New-Object System.Text.UTF8Encoding($false)))
    $env:OFFICE_KIT_MARKET_NAME = $MARKET_NAME
    $env:OFFICE_KIT_MARKET_DIR = $MARKET_DIR
    & $pythonCmd.Source $pyFile
    $rc = $LASTEXITCODE
    Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
    if ($rc -ne 0) {
      Write-Warning "      ⚠ 注册脚本返回码 $rc（市场目录已就绪；请检查 settings.json 后重跑）"
    }
  } else {
    Write-Host "      ⚠ 未找到 python：市场目录已就绪，但未写入 settings.json。"
    Write-Host "        请手动在 ~/.workbuddy/settings.json 的 enabledPlugins 加一行："
    Write-Host "          `"desen-stop@$MARKET_NAME`": true"
    Write-Host "        重启 WorkBuddy 后生效；完整指引见 hooks\desen-stop\平台启用指引.md"
  }

  # ---- ③ CLI 真正注册（关键：仅 enabledPlugins + 市场目录 = 假闸门，平台不执行）----
  function Register-DesenStopCli {
    $cli = $null
    $cliCmd = Get-Command codebuddy -ErrorAction SilentlyContinue
    if ($cliCmd) { $cli = $cliCmd.Source }
    if (-not $cli) {
      $cands = @(
        "$env:LOCALAPPDATA\Programs\WorkBuddy\cli\bin\codebuddy.exe",
        "${env:ProgramFiles}\WorkBuddy\cli\bin\codebuddy.exe",
        "$env:LOCALAPPDATA\Programs\CodeBuddy\cli\bin\codebuddy.exe",
        "${env:ProgramFiles}\CodeBuddy\cli\bin\codebuddy.exe",
        "$env:USERPROFILE\WorkBuddy\cli\bin\codebuddy.exe"
      )
      foreach ($c in $cands) { if (Test-Path $c) { $cli = $c; break } }
    }
    if (-not $cli) {
      Write-Warning "      ⚠ 未找到 codebuddy CLI：跳过 CLI 注册。插件处于「假闸门」状态（enabledPlugins 已登记但不触发）。请手动在 WorkBuddy 终端执行：plugin marketplace add '$MARKET_DIR' ; plugin install desen-stop@$MARKET_NAME"
      return
    }
    $node = $null
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCmd) { $node = $nodeCmd.Source }
    if (-not $node) {
      $n = Get-ChildItem "$env:USERPROFILE\.workbuddy\binaries\node\versions\*\bin\node.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($n) { $node = $n.FullName }
    }
    if (-not $node) {
      Write-Warning "      ⚠ 未找到 node：无法运行 codebuddy CLI，跳过 CLI 注册（插件处于假闸门状态）。"
      return
    }
    $env:HOME = $env:USERPROFILE
    $env:CODEBUDDY_CONFIG_DIR = "$env:USERPROFILE\.workbuddy"
    if (-not $env:LANG) { $env:LANG = "zh_CN.UTF-8" }
    if (-not $env:TERM) { $env:TERM = "dumb" }
    $env:PATH = "$(Split-Path $node);$env:PATH"
    # 剥离可能继承的 sandbox broker 变量（否则 CLI 静默挂起）
    foreach ($b in @("CODEBUDDY_SANDBOX_BROKER_IPC_ADDRESS","CODEBUDDY_BROKERED","CODEBUDDY_SESSION_ID")) {
      if (Test-Path "env:$b") { Remove-Item "env:$b" }
    }
    Write-Host "      · CLI: $cli  (node: $node)"
    Write-Host "      · 注册本地市场: plugin marketplace add"
    & $node $cli plugin marketplace add "$MARKET_DIR" 2>&1 | ForEach-Object { "        $_" }
    Write-Host "      · 安装插件: plugin install"
    & $node $cli plugin install "desen-stop@$MARKET_NAME" 2>&1 | ForEach-Object { "        $_" }
    # 校验
    $ok = $true
    $ipf = "$env:USERPROFILE\.workbuddy\plugins\installed_plugins.json"
    $cachep = "$env:USERPROFILE\.workbuddy\plugins\cache\$MARKET_NAME\desen-stop"
    if (Test-Path $ipf) {
      try {
        $d = Get-Content $ipf -Raw | ConvertFrom-Json
        $has = $false
        if ($d.plugins) {
          foreach ($k in $d.plugins.PSObject.Properties.Name) { if ($k -eq "desen-stop@$MARKET_NAME") { $has = $true } }
        }
        if ($has) { Write-Host "      ✓ installed_plugins.json 含 desen-stop@$MARKET_NAME" }
        else { Write-Warning "      ⚠ installed_plugins.json 未含 desen-stop@$MARKET_NAME（CLI 注册可能未生效）"; $ok = $false }
      } catch { Write-Warning "      ⚠ 读取 installed_plugins.json 失败: $_"; $ok = $false }
    } else { Write-Warning "      ⚠ 未找到 installed_plugins.json"; $ok = $false }
    if (Test-Path $cachep) { Write-Host "      ✓ cache 副本存在: $cachep" }
    else { Write-Warning "      ⚠ cache 副本缺失：$cachep（CLI install 可能未生效）"; $ok = $false }
    if ($ok) { Write-Host "      ✅ desen-stop 已通过 CLI 真正注册并启用（重启会话后 Stop hook 生效）" }
    else { Write-Warning "      ⚠ 注册校验未全过；详见 troubleshooting/plugin-enable.md §3 / 平台启用指引.md" }
  }
  Register-DesenStopCli
}

Write-Host ">>> 初始化完成。"
Write-Host "    运行 .\office-kit.ps1 --help 试用各组件；检查组件完整性/升级：.\office-kit.ps1 check"
Write-Host "    已强制部署技能 office-kit/desen-trigger 到 ~/.workbuddy/skills/（部署即生效）；"
Write-Host "    desen-stop 已分发到 ~/.workbuddy/hooks/desen-stop/ 并通过 CLI 真正注册为本地市场插件（第 6 步 ③）"
Write-Host "    （<市场> 可用 OFFICE_KIT_MARKETPLACE 覆盖；-NoEnableDesenStop 可只分发不启用，启用须手动跑 CLI）；"
Write-Host "    重启 WorkBuddy / 新开会话后 Stop hook 生效。校验："
Write-Host "      (Get-Content ~\.workbuddy\plugins\installed_plugins.json) -match 'desen-stop@<市场>'   # 应含条目"
Write-Host "      Test-Path ~\.workbuddy\plugins\cache\<市场>\desen-stop\                                # 应有执行副本"
Write-Host "    详见 hooks\desen-stop\平台启用指引.md §6 / troubleshooting/plugin-enable.md。"
