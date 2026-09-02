#!/usr/bin/env bash
# summarize 技能 · 依赖安装脚本
#
# 作用：安装 jieba 中文分词增强（可选依赖）。安装后 summarize.py 自动启用 jieba 分词，
#       中文分词质量优于内置二元/三元组；未安装则自动回退内置分词（零依赖，不报错）。
#
# 用法：
#   ./install.sh                                  # 装到默认解释器 python3
#   PYTHON=/path/to/python ./install.sh           # 指定解释器（须与运行 summarize.py 的 python 一致）
#
# WorkBuddy 受管默认环境可用：
#   PYTHON=/Users/hzh/.workbuddy/binaries/python/envs/default/bin/python ./install.sh
#
# 说明：本技能保持「零依赖回退为底线」——jieba 是「默认开、缺失自动降级」，
#       装不装都不影响脚本运行。安装仅为提升中文分词质量。
#       若目标 python 无 pip（如 WorkBuddy 受管默认环境 envs/default），脚本自动改用 uv 安装。
#
# 本体获取方式（本脚本只装依赖、不下载本体）：
#   本技能本体（SKILL.md + scripts/ + assets/ + references/）请先通过以下任一方式获取：
#     1) git clone git@github.com:hzh-opc/summarize.git            # SSH
#        （或 HTTPS：git clone https://github.com/hzh-opc/summarize.git）
#     2) 下载发行包（GitHub Releases 的 source tarball）后解压
#   获取本体后，在本目录运行 ./install.sh 安装 jieba 可选依赖即可；升级本体见 ./upgrade.sh。

set -euo pipefail

# 默认解释器：优先用调用方指定的 PYTHON，否则回退 python3（跨平台通用）
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[error] 找不到 python 解释器: $PY" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ="$SCRIPT_DIR/requirements.txt"

echo "[info] 使用 python: $PY ($("$PY" --version 2>&1))"
echo "[info] 安装依赖清单: $REQ"

if "$PY" -m pip --version >/dev/null 2>&1; then
  # 标准 venv / 系统 python（自带 pip）
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$PY" -m pip install -r "$REQ"
else
  # 受管 / uv 管理的 venv 默认不含 pip，改用 uv（WorkBuddy 默认环境即如此）
  UV_BIN="$(command -v uv 2>/dev/null || true)"
  if [ -n "$UV_BIN" ]; then
    echo "[info] 该 python 无 pip，改用 uv 安装"
    "$UV_BIN" pip install -r "$REQ" --python "$PY"
  else
    echo "[error] 既无 pip 也无 uv，无法安装依赖。请手动安装 $REQ 中的包。" >&2
    exit 1
  fi
fi

echo "[done] jieba 已安装。运行 summarize.py 时会自动启用 jieba 分词。"
echo "       验证：python3 scripts/summarize.py 输入.txt --eval  # 看 jieba_used 字段"
echo "       回退：若未安装 jieba，脚本自动用内置二元/三元组分词，不报错。"
