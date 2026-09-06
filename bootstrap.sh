#!/usr/bin/env bash
# office-kit 一键初始化脚本（Unix / macOS / Linux）
#
# 用途：从零重建或修复 office-kit 运行环境，幂等、可重复执行：
#   1) 创建 uv 管理的虚拟环境 .venv（Python 3.13）
#   2) 修复/补齐组件（缺失/损坏时在线下载，复用 kit.py repair；与 kit.py check/upgrade 同一套远程源设计）
#   3) 合并各组件 requirements.txt 并安装全部依赖
#   4) 校验组件 + 补齐 workbench 阶段子目录
#   5) 部署用户级技能与常驻 DESEN 闸门（office-kit 元技能 + desen-trigger 触发壳 → ~/.workbuddy/skills/；desen-stop Stop Hook → ~/.workbuddy/hooks/，幂等强制）
#
# 前置：已安装 uv（https://docs.astral.sh/uv/）。脚本依赖 uv 管理 .venv 与依赖。
# 用法：
#   ./bootstrap.sh            # 常规初始化（.venv 已存在则跳过创建）
#   ./bootstrap.sh --force-venv   # 强制删除并重建 .venv
#
# 注意：本脚本动 .venv / 组件目录 / 用户级 ~/.workbuddy/skills（office-kit 元技能 + desen-trigger 触发壳）与 ~/.workbuddy/hooks（desen-stop 常驻闸门），不会触碰 .git 或 workbench 内产物。
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
echo "     国内源: PyPI=$INDEX_URL  HF=$HF_MIRROR（如需官方源：OFFICE_KIT_PYPI_MIRROR=https://pypi.org/simple）"

PY_BIN="3.13"
FORCE_VENV=0
for arg in "$@"; do
  case "$arg" in
    --force-venv) FORCE_VENV=1 ;;
    -h|--help) echo "用法: ./bootstrap.sh [--force-venv]"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

echo ">>> office-kit 初始化开始：KIT_DIR=$KIT_DIR"

# ---------- 1. 创建虚拟环境 ----------
echo "[1/5] 创建虚拟环境 (uv venv --python $PY_BIN)..."
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
echo "[2/5] 修复/补齐组件（缺失/损坏时在线下载）..."
if command -v python3 >/dev/null 2>&1 && [ -f "$KIT_DIR/kit.py" ]; then
  python3 "$KIT_DIR/kit.py" repair --yes \
    || echo "      ⚠ 在线修复未完全成功（请检查网络或远程源）。可稍后手动：python3 kit.py repair"
else
  echo "      ⚠ 未找到 python3 / kit.py，跳过在线修复（仅作目录存在性校验）："
  for comp in info-extract desensitization-sop summarize doc-layout-aesthetics; do
    if [ -d "components/$comp" ]; then
      echo "      ✓ $comp 存在"
    else
      echo "      ⚠ 缺失组件 $comp：请从 office-kit 发布包/源恢复到 components/$comp" >&2
    fi
  done
fi

# ---------- 3. 安装依赖 ----------
echo "[3/5] 合并并安装组件依赖 (uv pip install)..."
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
ls components/*/requirements.txt 2>/dev/null | sed 's/^/        - /'
uv pip install --index-url "$INDEX_URL" -r "$REQ_TMP"
rm -f "$REQ_TMP"

# ---------- 4. 校验组件 + 补齐 workbench 目录 ----------
echo "[4/5] 校验组件 + 补齐 workbench 目录..."
for comp in info-extract desensitization-sop summarize doc-layout-aesthetics; do
  if [ -d "components/$comp" ]; then
    echo "      ✓ $comp 存在"
  else
    echo "      ⚠ 仍缺失组件 $comp：在线修复未成功，请从 office-kit 发布包/源恢复到 components/$comp" >&2
  fi
done

# 补齐 workbench 阶段子目录（.gitignore 忽略产物但保留结构，供流水线串接）
for d in inbox extract desen summary render archive logs; do
  if [ ! -d "workbench/$d" ]; then
    mkdir -p "workbench/$d"
    echo "      + 创建 workbench/$d"
  fi
done

# ---------- 5. 部署用户级技能 + 常驻 DESEN 闸门（强制，幂等覆盖） ----------
echo "[5/5] 部署用户级技能与常驻 DESEN 闸门..."
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

# 5c. 常驻闸门：desen-stop Stop Hook（会话结束兜底拦截「无脱敏留痕的外发」）
if [ -d "$KIT_DIR/hooks/desen-stop" ]; then
  rm -rf "$HOOKS_DIR/desen-stop"
  cp -R "$KIT_DIR/hooks/desen-stop" "$HOOKS_DIR/"
  echo "      ✓ 已部署常驻闸门: desen-stop Stop Hook -> $HOOKS_DIR/desen-stop/"
  echo "        提示：若平台需手动启用插件，请在插件/钩子管理页激活 desen-stop（默认 warn 仅提示；"
  echo "              设 DESEN_STOP_HOOK_MODE=block 可升级为命中即阻断）。"
else
  echo "      ⚠ 仓库缺失 hooks/desen-stop，跳过" >&2
fi
echo "      （技能与闸门均为幂等覆盖：重跑 bootstrap.sh 即同步仓库最新版，避免版本漂移）"

echo ">>> 初始化完成。"
echo "    运行 ./office-kit.sh --help 试用各组件；检查组件完整性/升级：./office-kit.sh check"
echo "    已强制部署技能(office-kit/desen-trigger)与常驻闸门(desen-stop)到 ~/.workbuddy/，确保 DESEN 触发有效。"
