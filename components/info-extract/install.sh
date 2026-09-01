#!/usr/bin/env bash
# info-extract 安装脚本（Linux / macOS）
# 等价于 install.py：建隔离 venv + 装依赖 + 自检
set -e
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SKILL_DIR"

PYTHON_BIN="python3"
if [ -x "$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3" ]; then
  PYTHON_BIN="$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
fi

VENV_DIR="$SKILL_DIR/scripts/.venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "[install] 创建 venv: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"
"$VENV_PY" -m pip install -U pip >/dev/null
echo "[install] 安装依赖…"
"$VENV_PY" -m pip install -r requirements.txt
echo "[install] 自检："
"$VENV_PY" "$SKILL_DIR/scripts/router.py" --check || true
echo ""
echo "[install] ✅ 完成。使用："
echo "  $VENV_PY $SKILL_DIR/scripts/router.py 录音.mp3"
