#!/usr/bin/env bash
# =============================================================================
# install.sh —— doc-layout-aesthetics 一键安装 / 依赖自检
#
# 职责：检测运行平台 → 解析/准备 Python 环境 → 装依赖 → 冒烟自检。
# 环境解析与 scripts/_venv.py 保持一致（复用其 resolve_venv / venv_python），
# 避免重复实现、避免与 build_all.py 的运行时行为不一致。
#
# 平台行为（对齐 AGENT_INSTALL.md）：
#   - WorkBuddy 宿主（存在 ~/.workbuddy）：复用全局共享默认环境
#     ~/.workbuddy/binaries/python/envs/default，依赖经
#     `uv pip install --python <默认环境>/bin/python` 追加式并入（禁 uv sync，
#     以免按本技能 pyproject 裁剪默认环境中其他技能的依赖）。
#   - 非宿主（Claude/Codex/OpenClaw）：建项目内 .venv + `uv sync`（或 venv+pip）。
#
# 用法：
#   bash install.sh             # 装依赖 + selfcheck --build 自检
#   bash install.sh --no-check  # 只装依赖，跳过自检
#   bash install.sh --help
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"  # install.sh 位于仓库根目录，ROOT 即本目录（scripts/ 在 ROOT/scripts）

DEPS="python-docx python-pptx reportlab pytest"
CHECK=1

info() { printf '\033[32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[error]\033[0m %s\n' "$*"; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --no-check) CHECK=0 ;;
        -h|--help) sed -n '1,30p' "$0"; exit 0 ;;
        *) fail "未知参数: $1（--help 查看用法）" ;;
    esac
    shift
done

# ---------- 1. 定位基础 python3（仅用于调用 _venv.py 解析环境，标准库即可） ----------
PYTHON="$(command -v python3 || command -v python || true)"
[ -z "$PYTHON" ] && fail "未找到 python3，请先安装 Python ≥ 3.11"

# ---------- 2. 复用 _venv.py 解析目标环境的 python ----------
# 优先级：UV_PROJECT_ENVIRONMENT > VIRTUAL_ENV > OFFICE_KIT_ROOT/.venv > 平台默认
VENV_PY="$("$PYTHON" - "$ROOT" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/scripts")
import _venv
print(_venv.venv_python(_venv.resolve_venv(sys.argv[1])))
PY
)"
[ -n "$VENV_PY" ] || fail "环境解析失败：无法确定目标 Python 解释器"

# ---------- 3. 判断宿主 / 非宿主 ----------
if [ -d "$HOME/.workbuddy" ]; then
    HOST=1
    info "检测到 WorkBuddy 宿主：复用全局共享默认环境（不另建 venv、禁 uv sync）"
else
    HOST=0
    info "非宿主平台：使用项目内 .venv"
fi

# ---------- 4. 非宿主：若目标 .venv 未就绪则创建 ----------
if [ "$HOST" -eq 0 ] && [ ! -x "$VENV_PY" ]; then
    if command -v uv >/dev/null 2>&1; then
        info "创建项目内 .venv（uv sync）..."
        (cd "$ROOT" && uv sync)
    else
        info "创建项目内 .venv（python3 -m venv）..."
        "$PYTHON" -m venv "$ROOT/.venv"
    fi
    VENV_PY="$ROOT/.venv/bin/python"
    [ -x "$VENV_PY" ] || fail "创建 .venv 失败：$VENV_PY 不可执行"
fi

# ---------- 5. 目标 Python 可执行性检查 ----------
[ -x "$VENV_PY" ] || fail "目标 Python 不可用: ${VENV_PY}（宿主下请确认 WorkBuddy 默认环境已初始化）"
info "目标环境: $VENV_PY"

# ---------- 6. 检查依赖，缺失则安装 ----------
if "$VENV_PY" -c "import docx, pptx, reportlab" >/dev/null 2>&1; then
    info "依赖已就位（docx/pptx/reportlab）✅"
else
    info "依赖缺失，开始安装: $DEPS"
    if [ "$HOST" -eq 1 ]; then
        # 宿主：追加式并入共享默认环境（绝不 uv sync，以免裁剪他技能依赖）
        command -v uv >/dev/null 2>&1 \
            || fail "宿主下需 uv 来并入依赖：请先安装 uv（curl -LsSf https://astral.sh/uv/install.sh | sh）"
        uv pip install --python "$VENV_PY" $DEPS
    else
        if command -v uv >/dev/null 2>&1 && [ -f "$ROOT/uv.lock" ]; then
            (cd "$ROOT" && uv sync)
        else
            "$VENV_PY" -m pip install $DEPS
        fi
    fi
fi

# ---------- 7. 冒烟自检（可选） ----------
if [ "$CHECK" -eq 1 ]; then
    info "运行冒烟自检 selfcheck.py --build ..."
    "$VENV_PY" "$SCRIPT_DIR/scripts/selfcheck.py" --build
fi

info "安装完成 ✅ 环境 python: $VENV_PY"
info "字体（可选，PDF 最佳渲染）: bash $SCRIPT_DIR/fonts/install_fonts.sh --online"
