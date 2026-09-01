#!/usr/bin/env bash
# office-kit 一键初始化脚本（Unix / macOS / Linux）
#
# 用途：从零重建或修复 office-kit 运行环境，三步幂等、可重复执行：
#   1) 创建 uv 管理的虚拟环境 .venv（Python 3.13）
#   2) 合并各组件 requirements.txt 并安装全部依赖
#   3) 校验/修复组件（缺失则从 ~/.workbuddy/skills 重新复制）
#
# 前置：已安装 uv（https://docs.astral.sh/uv/）。脚本依赖 uv 管理 .venv 与依赖。
# 用法：
#   ./bootstrap.sh            # 常规初始化（.venv 已存在则跳过创建）
#   ./bootstrap.sh --force-venv   # 强制删除并重建 .venv
#
# 注意：本脚本只动 .venv / 组件目录，不会触碰 .git 或 workbench 内产物。
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
echo "[1/3] 创建虚拟环境 (uv venv --python $PY_BIN)..."
if [ -d .venv ] && [ "$FORCE_VENV" -eq 0 ]; then
  echo "      .venv 已存在，跳过创建（--force-venv 可重建）"
else
  if [ "$FORCE_VENV" -eq 1 ]; then
    echo "      --force-venv：移除旧 .venv 并重建"
    rm -rf .venv
  fi
  uv venv --python "$PY_BIN" .venv
fi

# ---------- 2. 安装依赖 ----------
echo "[2/3] 合并并安装组件依赖 (uv pip install)..."
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

# ---------- 3. 校验 / 修复组件 ----------
echo "[3/3] 校验/修复组件..."
SRC_ROOT="$HOME/.workbuddy/skills"
COMPONENTS="info-extract desensitization-sop summarize doc-layout-aesthetics"
for comp in $COMPONENTS; do
  if [ -d "components/$comp" ]; then
    echo "      ✓ $comp 存在"
  else
    if [ -d "$SRC_ROOT/$comp" ]; then
      echo "      + 缺失 $comp，从 $SRC_ROOT/$comp 重新复制"
      cp -R "$SRC_ROOT/$comp" "components/$comp"
      find "components/$comp" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    else
      echo "      ⚠ 缺失 $comp，且源 $SRC_ROOT/$comp 不存在，请手动放入该组件" >&2
    fi
  fi
done

echo ">>> 初始化完成。"
echo "    运行 ./office-kit.sh --help 试用各组件；仓库状态用 git / ./ogit 查看。"
