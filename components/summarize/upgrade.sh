#!/usr/bin/env bash
# summarize 技能 · 升级脚本
#
# 作用：从上游仓库 hzh-opc/summarize 拉取最新本体，rsync 增量同步到本技能目录（本体升级）。
#       不负责安装依赖（jieba 等可选依赖见 install.sh）。
#
# 用法：
#   ./upgrade.sh                            # 升级到本脚本所在目录（默认：独立部署的 summarize 本体目录）
#   ./upgrade.sh /path/to/summarize         # 升级到指定技能目录
#   REMOTE=<git-url> ./upgrade.sh           # 自定义上游仓库
#
# 说明：
#   - 默认上游：git@github.com:hzh-opc/summarize.git（SSH）；无 SSH 权限可改用
#     REMOTE=https://github.com/hzh-opc/summarize.git
#   - 升级前对目标目录做一次性快照备份（.upgrade_backup_<时间戳>/），确认无误后可手动删除。
#   - 仅增量覆盖本体文件，不删除目标目录中上游已不存在的文件（安全优先）；排除 .git/.gitignore/
#     __pycache__/capabilities.detected.json 等工作区个性化或运行产物。

set -euo pipefail

REMOTE="${REMOTE:-git@github.com:hzh-opc/summarize.git}"
TARGET_DIR="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")}" 2>/dev/null && pwd || echo "${1:-$(dirname "${BASH_SOURCE[0]}")}")"

for c in git rsync; do
  command -v "$c" >/dev/null 2>&1 || { echo "[error] 缺少依赖命令: $c" >&2; exit 1; }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[info] 上游仓库 : $REMOTE"
echo "[info] 升级目标 : $TARGET_DIR"

echo "[info] 拉取上游最新本体..."
if ! git clone --depth 1 "$REMOTE" "$TMP/repo"; then
  echo "[error] 拉取上游失败：请检查网络 / SSH 权限，或改用 REMOTE=https://github.com/hzh-opc/summarize.git" >&2
  exit 1
fi

# 升级前快照备份（仅目标目录非空时）
if [ -n "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  BACKUP="$TARGET_DIR/.upgrade_backup_$STAMP"
  mkdir -p "$BACKUP"
  echo "[info] 备份当前版本 -> $BACKUP"
  rsync -a --exclude '.upgrade_backup_*' "$TARGET_DIR"/ "$BACKUP"/ || true
fi

# 增量同步本体（不加 --delete，安全优先）
echo "[info] 增量同步本体文件..."
rsync -a \
  --exclude '.git' --exclude '.gitignore' \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'capabilities.detected.json' \
  --exclude '.upgrade_backup_*' --exclude '.DS_Store' \
  "$TMP/repo/" "$TARGET_DIR/"

echo "[done] 本体升级完成。备份（如有）位于 $TARGET_DIR/.upgrade_backup_*，确认无误后可手动删除。"
echo "       如需安装 jieba 中文分词增强，请运行 ./install.sh。"
