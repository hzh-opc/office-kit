#!/usr/bin/env bash
# office-kit 统一入口（macOS / Linux）
#
# 动态分发：委托 kit.py 扫描 components/*/manifest.json 生成"功能记录"后调用对应组件。
# 不再使用静态 case 分发（规划文档要求"可拆卸"模块化 + 扫描组件形成功能记录）。
#
# 用法:
#   ./office-kit.sh <command> [组件参数...]
#   抽取处理链: extract / desen / summarize
#   美化交付:   md-pdf / docx / pptx / html / render
#   治理:       list | overlaps | doctor | feedback | run <command> | <command> --dry-run
set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$KIT_DIR/.venv/bin/python"
# 显式指向 kit 的 .venv，避免回退到全局环境用错解释器。
export UV_PROJECT_ENVIRONMENT="$KIT_DIR/.venv"

# 管理类命令（list/overlaps/doctor/feedback）在无 .venv 时也能运行；
# 分发类命令（run）由 kit.py 内部校验并提示初始化。
if [ -x "$VENV_PY" ]; then
  PY="$VENV_PY"
else
  PY="python3"
fi
exec "$PY" "$KIT_DIR/kit.py" "$@"
