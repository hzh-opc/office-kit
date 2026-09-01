#!/usr/bin/env bash
# office-kit 统一入口（macOS / Linux）
# 用法: ./office-kit.sh <component> [组件参数...]
#
# 抽取/处理链:
#   extract   → info-extract（转录 / OCR / 视频 / 画面解读）
#   desen     → desensitization-sop（脱敏）
#   summarize → summarize（摘要 / 提炼）
#
# 排版美化交付（doc-layout-aesthetics）:
#   md-pdf    → Markdown 直转排版 PDF（build_md_pdf.py，支持 -i/-o/-t）
#   docx      → 生成《版面美学观》精排 Word 样例（build_docx.py，--out）
#   pptx      → 生成精排 PPT 样例（build_pptx.py，--out）
#   html      → 生成响应式 HTML 样例（build_html.py，--out）
#   render    → 一键构建 docx/pptx/html（可选 --pdf）（build_all.py）
set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$KIT_DIR/.venv/bin/python"
DL="$KIT_DIR/components/doc-layout-aesthetics/scripts"
# doc-layout 的 build_all.py 经 _venv.py 重新解析 python；显式指向 kit 的 .venv，
# 避免回退到 WorkBuddy 全局默认环境而用错解释器（对 build_md_pdf 等无 _venv 依赖的脚本无害）。
export UV_PROJECT_ENVIRONMENT="$KIT_DIR/.venv"
case "${1:-}" in
  extract|info-extract)
    shift
    exec "$VENV_PY" "$KIT_DIR/components/info-extract/scripts/router.py" "$@"
    ;;
  desen|desensitization-sop)
    shift
    exec "$VENV_PY" "$KIT_DIR/components/desensitization-sop/scripts/desensitize.py" "$@"
    ;;
  summarize|summary)
    shift
    exec "$VENV_PY" "$KIT_DIR/components/summarize/scripts/summarize.py" "$@"
    ;;
  md-pdf)
    shift
    exec "$VENV_PY" "$DL/build_md_pdf.py" "$@"
    ;;
  docx)
    shift
    exec "$VENV_PY" "$DL/build_docx.py" "$@"
    ;;
  pptx)
    shift
    exec "$VENV_PY" "$DL/build_pptx.py" "$@"
    ;;
  html)
    shift
    exec "$VENV_PY" "$DL/build_html.py" "$@"
    ;;
  render)
    shift
    exec "$VENV_PY" "$DL/build_all.py" "$@"
    ;;
  *)
    cat <<USAGE
用法: $0 <component> [组件参数...]

抽取/处理链:
  extract   info-extract         转录 / OCR / 视频 / 画面解读
  desen     desensitization-sop  脱敏
  summarize summarize            摘要 / 提炼

排版美化交付 (doc-layout-aesthetics):
  md-pdf    Markdown 直转排版 PDF        (-i 输入.md -o 输出.pdf [-t 标题])
  docx      《版面美学观》精排 Word 样例  (--out 目录)
  pptx      精排 PPT 样例                (--out 目录)
  html      响应式 HTML 样例             (--out 目录)
  render    一键构建 docx/pptx/html [--pdf]  (--out 目录)
USAGE
    exit 1
    ;;
esac
