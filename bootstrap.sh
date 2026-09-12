#!/usr/bin/env bash
# office-kit 一键初始化脚本（Unix / macOS / Linux）
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
#        - CLI 真正注册：plugin marketplace add + plugin install（env -i 干净环境，详见
#          hooks/desen-stop/平台启用指引.md）；installed_plugins.json ∩ cache 副本 双校验
#   7) 可选（--inject-soul-rules）：把「敏感信息检测闸门（常驻铁律）」幂等合并到
#      ~/.workbuddy/SOUL.md（复用 desensitization-sop/install.py 的跨源去重 + 幂等机制，
#      该机制会自动跳过已被 SOUL.md / office-kit 套件等同源承接的写法）。默认 dry-run。
#
# 前置：已安装 uv（https://docs.astral.sh/uv/）。第 6 步写 settings.json 需 python3。
# 用法：
#   ./bootstrap.sh                        # 常规初始化（.venv 已存在则跳过创建）
#   ./bootstrap.sh --force-venv           # 强制删除并重建 .venv
#   ./bootstrap.sh --no-enable-desen-stop # 只做文件分发，不写 settings.json（留待人工启用）
#   ./bootstrap.sh --inject-soul-rules    # 启用第 7 步：常驻铁律合并写入 ~/.workbuddy/SOUL.md
#
# 环境变量：OFFICE_KIT_MARKETPLACE（本地市场名，默认 hzh-local）
#
# 注意：本脚本动 .venv / 组件目录 / 用户级 ~/.workbuddy/skills、~/.workbuddy/hooks、
#       ~/.workbuddy/plugins/marketplaces/<市场>/ 与 ~/.workbuddy/settings.json（第 6 步，改前备份），
#       不会触碰 .git 或 workbench 内产物。
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KIT_DIR"

# 显式锁定 venv 路径，避免被宿主环境的 UV_PROJECT_ENVIRONMENT 劫持到全局 venv。
export UV_PROJECT_ENVIRONMENT=".venv"

# ---------- 国内源优先（规划文档 L18，可用环境变量覆盖） ----------
# PyPI 镜像（依赖安装）；HuggingFace 镜像（faster-whisper 等大模型下载）。
INDEX_URL="${OFFICE_KIT_PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
HF_MIRROR="${OFFICE_KIT_HF_MIRROR:-https://hf-mirror.com}"
export PIP_INDEX_URL="$INDEX_URL"      # pip 兼容
export UV_INDEX_URL="$INDEX_URL"        # uv 兼容（若支持）
export HF_ENDPOINT="$HF_MIRROR"         # 大模型下载走镜像
# 注意：变量紧邻多字节字符时必须用 ${VAR} 花括号形式——macOS bash 3.2 会把后续
#       多字节字节序列并入变量名，导致 "unbound variable"（历史上需靠 LC_ALL=C 规避）。
echo "     国内源: PyPI=${INDEX_URL}  HF=${HF_MIRROR}（如需官方源：OFFICE_KIT_PYPI_MIRROR=https://pypi.org/simple）"

PY_BIN="3.13"
FORCE_VENV=0
ENABLE_DESEN_STOP=1
INJECT_SOUL_RULES=0   # 第 7 步常驻铁律注入默认 dry-run；显式 --inject-soul-rules 启用
for arg in "$@"; do
  case "$arg" in
    --force-venv) FORCE_VENV=1 ;;
    --no-enable-desen-stop) ENABLE_DESEN_STOP=0 ;;
    --inject-soul-rules) INJECT_SOUL_RULES=1 ;;
    -h|--help) echo "用法: ./bootstrap.sh [--force-venv] [--no-enable-desen-stop] [--inject-soul-rules]"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

echo ">>> office-kit 初始化开始：KIT_DIR=$KIT_DIR"

# ---------- 1. 创建虚拟环境 ----------
echo "[1/6] 创建虚拟环境 (uv venv --python $PY_BIN)..."
if [ -d .venv ] && [ "$FORCE_VENV" -eq 0 ]; then
  echo "      .venv 已存在，跳过创建（--force-venv 可重建）"
else
  if [ "$FORCE_VENV" -eq 1 ]; then
    echo "      --force-venv：移除旧 .venv 并重建"
    rm -rf .venv
  fi
  uv venv --python "$PY_BIN" .venv
fi

# ---------- 2. 修复/补齐组件（缺失/损坏时在线下载，复用 kit.py repair） ----------
echo "[2/6] 修复/补齐组件（缺失/损坏时在线下载）..."
if command -v python3 >/dev/null 2>&1 && [ -f "$KIT_DIR/kit.py" ]; then
  python3 "$KIT_DIR/kit.py" repair --yes \
    || echo "      ⚠ 在线修复未完全成功（请检查网络或远程源）。可稍后手动：python3 kit.py repair"
else
  echo "      ⚠ 未找到 python3 / kit.py，跳过在线修复（仅作目录存在性校验）："
  for comp in info-extract desensitization-sop summarize doc-layout-aesthetics; do
    if [ -d "components/$comp" ]; then
      echo "      ✓ $comp 存在"
    else
      echo "      ⚠ 缺失组件 ${comp}：请从 office-kit 发布包/源恢复到 components/$comp" >&2
    fi
  done
fi

# ---------- 3. 安装依赖 ----------
echo "[3/6] 合并并安装组件依赖 (uv pip install)..."
REQ_TMP="$(mktemp)"
: > "$REQ_TMP"
for f in components/*/requirements.txt; do
  [ -f "$f" ] && cat "$f" >> "$REQ_TMP"
done
if [ ! -s "$REQ_TMP" ]; then
  echo "      ⚠ 未发现任何组件 requirements.txt，无法安装依赖" >&2
  rm -f "$REQ_TMP"
  exit 1
fi
echo "      依赖清单来自："
# ⚠ `if !` 守护：set -euo pipefail 下，ls 无匹配/失败会经管道触发 set -e 中止脚本（U11 修复）
if ! ls components/*/requirements.txt 2>/dev/null | sed 's/^/        - /'; then
  echo "        - （枚举失败；不影响后续安装，依赖清单以上方合并结果为准）"
fi
uv pip install --index-url "$INDEX_URL" -r "$REQ_TMP"
rm -f "$REQ_TMP"

# ---------- 4. 校验组件 + 补齐 workbench 目录 ----------
echo "[4/6] 校验组件 + 补齐 workbench 目录..."
for comp in info-extract desensitization-sop summarize doc-layout-aesthetics; do
  if [ -d "components/$comp" ]; then
    echo "      ✓ $comp 存在"
  else
    echo "      ⚠ 仍缺失组件 ${comp}：在线修复未成功，请从 office-kit 发布包/源恢复到 components/$comp" >&2
  fi
done

# 补齐 workbench 阶段子目录（.gitignore 忽略产物但保留结构，供流水线串接）
for d in inbox extract desen summary render archive logs; do
  if [ ! -d "workbench/$d" ]; then
    mkdir -p "workbench/$d"
    echo "      + 创建 workbench/$d"
  fi
done

# ---------- 5. 部署用户级技能 + 插件包分发（强制，幂等覆盖） ----------
echo "[5/6] 部署用户级技能与插件包（文件分发）..."
SKILLS_DIR="${HOME}/.workbuddy/skills"
HOOKS_DIR="${HOME}/.workbuddy/hooks"
mkdir -p "$SKILLS_DIR" "$HOOKS_DIR"

# 5a. office-kit 元技能（统一编排入口，门禁覆盖 office-kit 命令）
if [ -d "$KIT_DIR/skills/office-kit" ]; then
  rm -rf "$SKILLS_DIR/office-kit"
  cp -R "$KIT_DIR/skills/office-kit" "$SKILLS_DIR/"
  echo "      ✓ 已部署/更新技能: office-kit ($(grep -m1 '^version' "$SKILLS_DIR/office-kit/SKILL.md" 2>/dev/null | tr -d 'version: '))"
else
  echo "      ⚠ 仓库缺失 skills/office-kit，跳过（请确认仓库完整性）" >&2
fi

# 5b. desen-trigger 跨场景触发壳（覆盖非办公场景：云端生成/邮件/表格云解析/联网等）
if [ -d "$KIT_DIR/skills/desen-trigger" ]; then
  rm -rf "$SKILLS_DIR/desen-trigger"
  cp -R "$KIT_DIR/skills/desen-trigger" "$SKILLS_DIR/"
  echo "      ✓ 已部署/更新技能: desen-trigger ($(grep -m1 '^version' "$SKILLS_DIR/desen-trigger/SKILL.md" 2>/dev/null | tr -d 'version: '))"
else
  echo "      ⚠ 仓库缺失 skills/desen-trigger，跳过" >&2
fi

# 5c. desen-stop Stop Hook 插件包（会话结束兜底拦截「无脱敏留痕的外发」）
#     desen-stop 是标准 Hook 插件包（.codebuddy-plugin/plugin.json 契约）。
#     本步只做「文件分发」到 ~/.workbuddy/hooks/（供查阅 / 手动导入）；
#     真正让平台加载其 Stop hook 的是【第 6 步】（本地市场 + enabledPlugins 启用）。
if [ -d "$KIT_DIR/hooks/desen-stop" ]; then
  rm -rf "$HOOKS_DIR/desen-stop"
  cp -R "$KIT_DIR/hooks/desen-stop" "$HOOKS_DIR/"
  echo "      ✓ 已分发 desen-stop 插件包 -> $HOOKS_DIR/desen-stop/"
else
  echo "      ⚠ 仓库缺失 hooks/desen-stop，跳过" >&2
fi
echo "      （技能为幂等覆盖、重跑即同步仓库最新版）"

# 5d. skills-registry 登记（U7/B2 上游化：自动生成/更新，幂等；人工备注区块保留）
if command -v python3 >/dev/null 2>&1; then
  if ! python3 "${KIT_DIR}/kit.py" register; then
    echo "      ⚠ skills-registry 自动生成失败（可稍后手动：python3 ${KIT_DIR}/kit.py register）" >&2
  fi
else
  echo "      ⚠ 未找到 python3，跳过 skills-registry 自动登记（部署 Agent 按 6 字段手工登记）" >&2
fi

# ---------- 6. 平台生效：注册本地市场 + 启用 desen-stop（幂等） ----------
#     ⚠️ 机制（2026-09-12 实证，详见 troubleshooting/plugin-enable.md）：
#       仅写 `enabledPlugins` +「市场目录」是「假闸门」——平台只计数、市场未注册，
#       插件从不真正执行。真正生效必须靠官方 CLI：
#         ① `plugin marketplace add <市场目录>`  → 在 known_marketplaces.json 注册（type:directory）
#         ② `plugin install <插件>@<市场>`       → 写 installed_plugins.json 并在
#                                                   plugins/cache/<市场>/<插件>/<版本>/ 生成执行副本
#       本步先文件分发（市场目录 + marketplace.json + enabledPlugins 登记，作为清单/兜底），
#       再用 CLI 真正注册并安装（③）；CLI 须用 `env -i` 完全干净环境运行（否则继承沙箱代理变量会静默挂起）。
#       详见 hooks/desen-stop/平台启用指引.md / troubleshooting/plugin-enable.md。
echo "[6/6] 注册本地市场并启用 desen-stop 插件..."
if [ "$ENABLE_DESEN_STOP" -eq 0 ]; then
  echo "      · 已按 --no-enable-desen-stop 跳过（仅完成文件分发；启用指引见 hooks/desen-stop/平台启用指引.md）"
elif [ ! -d "$KIT_DIR/hooks/desen-stop" ]; then
  echo "      ⚠ 仓库缺失 hooks/desen-stop，跳过启用" >&2
else
  PLUGINS_ROOT="${HOME}/.workbuddy/plugins"
  MARKET_NAME="${OFFICE_KIT_MARKETPLACE:-hzh-local}"
  MARKET_DIR="$PLUGINS_ROOT/marketplaces/$MARKET_NAME"
  mkdir -p "$MARKET_DIR/.codebuddy-plugin" "$MARKET_DIR/plugins"
  rm -rf "$MARKET_DIR/plugins/desen-stop"
  cp -R "$KIT_DIR/hooks/desen-stop" "$MARKET_DIR/plugins/desen-stop/"
  # 清理复制带入的运行时残留（不影响插件契约文件）
  find "$MARKET_DIR/plugins/desen-stop" -name ".DS_Store" -delete 2>/dev/null || true
  rm -rf "$MARKET_DIR/plugins/desen-stop/.in_use" 2>/dev/null || true
  echo "      ✓ 市场目录: $MARKET_DIR"
  if command -v python3 >/dev/null 2>&1; then
    MARKET_NAME="$MARKET_NAME" MARKET_DIR="$MARKET_DIR" python3 - <<'PY'
import json, os, shutil, sys
from datetime import date
from pathlib import Path

PLUGIN = "desen-stop"
market = os.environ["MARKET_NAME"]
market_dir = Path(os.environ["MARKET_DIR"])
base = Path(os.path.expanduser("~/.workbuddy"))

# ---- ① 市场清单（按插件名合并，保留既有其它插件条目；幂等覆盖） ----
manifest = market_dir / ".codebuddy-plugin" / "marketplace.json"
doc = {
    "name": market,
    "description": "本机自建插件市场（本地目录源）",
    "owner": {"name": os.environ.get("USER") or os.environ.get("USERNAME") or "local"},
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
        print(f"      ⚠ 市场清单解析失败（将重建）: {exc}")
entry = {
    "name": PLUGIN,
    "description": "Stop Hook 插件：会话结束前检测「上云/外发已做却无 desen 脱敏留痕」",
    "source": f"./plugins/{PLUGIN}",
    "category": "security",
    "version": "1.0.0",
}
doc["plugins"] = [p for p in doc["plugins"] if p.get("name") != PLUGIN] + [entry]
manifest.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"      ✓ 市场清单: {manifest}")

# ---- ② settings.json 启用登记（幂等；改动前备份；原子替换；不动其它键） ----
settings = base / "settings.json"
plugin_key = f"{PLUGIN}@{market}"
if settings.is_file():
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"      ⚠ settings.json 解析失败，跳过启用（未改动原文件）: {exc}")
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
    print(f"      · settings.json 已登记 {plugin_key}（无需写入）")
else:
    if not created:
        bak = settings.with_name(f"{settings.name}.bak-{date.today().isoformat()}-desen")
        if not bak.exists():
            shutil.copy2(settings, bak)
            print(f"      ✓ 已备份 settings.json -> {bak.name}")
    enabled[plugin_key] = True
    tmp = settings.with_name(f"{settings.name}.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, settings)
    print(f"      ✓ 已启用 {plugin_key}（settings.json{'（本次新建）' if created else ''}）")
    print("      ⚠ 插件在【会话启动时】加载：请重启 WorkBuddy / 新开会话后生效")
PY
  else
    echo "      ⚠ 未找到 python3：市场目录已就绪，但未写入 settings.json。"
    echo "        请手动在 ~/.workbuddy/settings.json 的 enabledPlugins 加一行："
    echo "          \"desen-stop@$MARKET_NAME\": true"
    echo "        重启 WorkBuddy 后生效；完整指引见 hooks/desen-stop/平台启用指引.md"
  fi

  # ---- ③ CLI 真正注册（关键：仅 enabledPlugins + 市场目录 = 假闸门，平台不执行）----
  register_desen_stop_cli() {
    local cli=""
    if command -v codebuddy >/dev/null 2>&1; then
      cli="$(command -v codebuddy)"
    else
      for cand in \
        "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy" \
        "$HOME/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy" \
        "/Applications/CodeBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy" \
        "$HOME/Applications/CodeBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy" ; do
        [ -x "$cand" ] && { cli="$cand"; break; }
      done
    fi
    if [ -z "$cli" ]; then
      echo "      ⚠ 未找到 codebuddy CLI：跳过 CLI 注册。插件处于「假闸门」状态（enabledPlugins 已登记但不触发）。"
      echo "        请手动：在 WorkBuddy 终端执行  plugin marketplace add '$MARKET_DIR' && plugin install desen-stop@$MARKET_NAME"
      return 1
    fi
    local ndir=""
    if command -v node >/dev/null 2>&1; then
      ndir="$(dirname "$(command -v node)")"
    else
      for d in "$HOME/.workbuddy/binaries/node/versions"/*/bin; do
        [ -x "$d/node" ] && { ndir="$d"; break; }
      done
    fi
    if [ -z "$ndir" ]; then
      echo "      ⚠ 未找到 node：无法运行 codebuddy CLI，跳过 CLI 注册（插件处于假闸门状态）。"
      return 1
    fi
    # 必须用 env -i 完全干净环境：继承父环境的沙箱代理变量（CODEBUDDY_SANDBOX_BROKER_* 等）
    # 会让 CLI 静默挂起（实测 6 分钟无输出）。env -i 仅保留下列显式变量。
    local cenv=( HOME="$HOME" CODEBUDDY_CONFIG_DIR="$HOME/.workbuddy" LANG="${LANG:-zh_CN.UTF-8}" TERM="${TERM:-dumb}" PATH="$ndir:/usr/bin:/bin" )
    echo "      · CLI: $cli  (node: $ndir/node)"
    # ⚠ 必须用 `if !` 守护：本脚本是 set -euo pipefail，裸管道 `cmd | sed` 一旦 cmd 非零
    #   会因 pipefail 使整条管道失败，进而被 set -e 直接终止脚本——那样下方的降级提示与
    #   校验块都不会执行，用户只会看到一个无解释的中途退出。`if !` 上下文对 set -e 免疫。
    echo "      · 注册本地市场: plugin marketplace add"
    if ! env -i "${cenv[@]}" "$ndir/node" "$cli" plugin marketplace add "$MARKET_DIR" 2>&1 | sed 's/^/        /'; then
      echo "      ⚠ marketplace add 失败（详见上方输出）"
    fi
    echo "      · 安装插件: plugin install"
    if ! env -i "${cenv[@]}" "$ndir/node" "$cli" plugin install "desen-stop@$MARKET_NAME" 2>&1 | sed 's/^/        /'; then
      echo "      ⚠ plugin install 失败（详见上方输出）"
    fi
    # 校验：installed_plugins.json 含条目 + cache 副本存在
    local ok=1
    local ipf="$HOME/.workbuddy/plugins/installed_plugins.json"
    local cachep="$HOME/.workbuddy/plugins/cache/$MARKET_NAME/desen-stop"
    if [ -f "$ipf" ] && command -v python3 >/dev/null 2>&1; then
      if ! python3 - "$MARKET_NAME" "$ipf" <<'PY'
import json, sys
m, p = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p, encoding="utf-8"))
    if any(k == "desen-stop@%s" % m for k in d.get("plugins", {})):
        print("      ✓ installed_plugins.json 含 desen-stop@%s" % m); sys.exit(0)
except Exception as e:
    print("      ⚠ 读取 installed_plugins.json 失败: %s" % e)
print("      ⚠ installed_plugins.json 未含 desen-stop@%s（CLI 注册可能未生效）" % m); sys.exit(1)
PY
      then ok=0; fi
    fi
    if [ ! -d "$cachep" ]; then
      echo "      ⚠ cache 副本缺失：${cachep}（CLI install 可能未生效）"; ok=0
    else
      echo "      ✓ cache 副本存在: $cachep"
    fi
    if [ "$ok" -eq 1 ]; then
      echo "      ✅ desen-stop 已通过 CLI 真正注册并启用（重启会话后 Stop hook 生效）"
    else
      echo "      ⚠ 注册校验未全过；详见 troubleshooting/plugin-enable.md §3 / 平台启用指引.md"
    fi
  }
  # ⚠ 必须用 `|| true` 守护：函数在「未找到 CLI / node」两种降级路径下 `return 1`，
  #   直接调用会被 set -e 判定为失败而终止脚本，导致收尾摘要不打印、用户误判初始化失败。
  register_desen_stop_cli || true

fi

# ---------- 7. （可选）常驻铁律注入 ~/.workbuddy/SOUL.md ----------
# 默认 dry-run：仅提示当前是否需要/被允许注入；--inject-soul-rules 显式启用时调用
# desensitization-sop/install.py --memory-file ~/.workbuddy/SOUL.md --skip-venv --skip-tests，
# 由 install.py 内部的跨源去重 + 幂等机制保护（自动跳过 SOUL.md/office-kit 套件已承接的等同源规则）。
# 实测注意：本机 SOUL.md 可能已被 system prompt 注入「常驻铁律」段（属脱敏组件跨会话登记的副作用），
# 此时 install.py 会判定「等价来源已存在」自动跳过写入——也是预期行为。
echo "[7/7] 常驻铁律注入 ~/.workbuddy/SOUL.md..."
SOUL_FILE="$HOME/.workbuddy/SOUL.md"
SOUL_DESEN="$KIT_DIR/components/desensitization-sop"
if [ "$INJECT_SOUL_RULES" -ne 1 ]; then
  echo "      · 默认 dry-run：跳过实际写入。启用：./bootstrap.sh --inject-soul-rules  或  INJECT_SOUL_RULES=1"
  echo "        目标落点：$SOUL_FILE"
  if [ -f "$SOUL_FILE" ] && grep -qE "敏感信息检测闸门|常驻铁律" "$SOUL_FILE" 2>/dev/null; then
    echo "      ✓ 检测到既有常驻铁律段——即使启用第 7 步，install.py 也会跨源去重并跳过写入（幂等安全）"
  else
    echo "      · 未检测到既有常驻铁律段；启用第 7 步将新建一段。"
  fi
else
  if [ ! -f "$SOUL_DESEN/install.py" ]; then
    echo "      ⚠ 未找到 $SOUL_DESEN/install.py：跳过（请先用 ./bootstrap.sh 或 kit.py repair 补齐组件）"
  else
    VENV_PY="$KIT_DIR/.venv/bin/python"
    if [ ! -x "$VENV_PY" ]; then
      echo "      ⚠ office-kit .venv 解释器未就绪（${VENV_PY}）；跳过"
    else
      echo "      · 调用 install.py --memory-file $SOUL_FILE --skip-venv --skip-tests"
      # ⚠ 必须用 `if !` 守护：set -euo pipefail 下，install.py 异常退出 + sed 管道会因
      #   pipefail 触发 set -e 中止脚本。`if ! … | sed` 上下文对 set -e 免疫。
      if ! "$VENV_PY" "$SOUL_DESEN/install.py" --memory-file "$SOUL_FILE" --skip-venv --skip-tests 2>&1 | sed 's/^/        /'; then
        echo "      ⚠ install.py 异常退出（详见上方）；SOUL.md 未受影响（install.py 仅在跨源去重通过后才追加）"
      fi
    fi
  fi
fi

# ---------- 8. 部署验收（U10/B6 上游化：跨平台统一验收闸门） ----------
if command -v python3 >/dev/null 2>&1; then
  echo "[验收] python3 ${KIT_DIR}/kit.py verify ..."
  # ⚠ `if !` 守护：verify 返回非零（验收未全绿）时不得中止脚本，交由收尾提示
  if ! python3 "${KIT_DIR}/kit.py" verify; then
    echo "      ⚠ 验收未全绿：请按上方输出修复后重跑（python3 ${KIT_DIR}/kit.py verify）" >&2
  fi
else
  echo "[验收] 未找到 python3，跳过自动验收（可手动：python3 ${KIT_DIR}/kit.py verify）"
fi

echo ">>> 初始化完成。"
echo "    运行 ./office-kit.sh --help 试用各组件；检查组件完整性/升级：./office-kit.sh check"
echo "    已强制部署技能 office-kit/desen-trigger 到 ~/.workbuddy/skills/（部署即生效）；"
echo "    desen-stop 已分发到 ~/.workbuddy/hooks/desen-stop/ 并通过 CLI 真正注册为本地市场插件（第 6 步 ③）"
echo "    （<市场> 可用 OFFICE_KIT_MARKETPLACE 覆盖；--no-enable-desen-stop 可只分发不启用，启用须手动跑 CLI）；"
echo "    重启 WorkBuddy / 新开会话后 Stop hook 生效。校验："
echo "      cat ~/.workbuddy/plugins/installed_plugins.json | grep desen-stop@<市场>   # 应含条目"
echo "      ls  ~/.workbuddy/plugins/cache/<市场>/desen-stop/                          # 应有执行副本"
echo "    详见 hooks/desen-stop/平台启用指引.md §6 / troubleshooting/plugin-enable.md。"
