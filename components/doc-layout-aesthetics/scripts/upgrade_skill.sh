#!/usr/bin/env bash
# =============================================================================
# doc-layout-aesthetics 升级脚本（macOS / Linux 通用）
#
# 从 GitHub 远程仓库拉取最新版，同步到技能副本。
# 副本保持干净：不含 .git / __pycache__ / .pytest_cache / .DS_Store /
# 字体二进制（fonts/common/、fonts/SHA256SUMS 由用户按需另装）。
#
# 【主从关系】独立仓库 hzh-opc/doc-layout-aesthetics 是**唯一上游**；
#   office-kit 套件内的 components/doc-layout-aesthetics 副本由套件统一入口
#   `kit.py upgrade doc-layout-aesthetics` 定期同步，**勿用本脚本直接覆盖**。
#
# 【适用场景】本脚本仅用于 S4「仅组件独立部署」：把组件装到独立技能副本
#   （~/.workbuddy/skills/doc-layout-aesthetics，或 --target 指定目录）。
#   若本机已装 office-kit 套件（技能副本已是转向器，SKILL.md 含 redirect_to），
#   请改用套件统一入口升级：`python kit.py upgrade doc-layout-aesthetics`。
#   本脚本检测到目标为转向器时会告警并中止，避免覆盖转向机制。
#
# 用法：
#   ./upgrade_skill.sh                 # 默认升级到 WorkBuddy 技能副本
#   ./upgrade_skill.sh --target DIR    # 指定技能副本目录
#   ./upgrade_skill.sh --repo URL      # 指定仓库地址（默认 GitHub 官方）
#   ./upgrade_skill.sh --branch main   # 指定分支（默认 main）
#   ./upgrade_skill.sh --dry-run       # 只拉取并展示差异，不实际同步
#   ./upgrade_skill.sh --check         # 只检查远程是否有新版本
#
# 兼容性：依赖 bash 3.2+ + git + rsync（macOS/Linux 均自带或易装）。
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET="${HOME}/.workbuddy/skills/doc-layout-aesthetics"
REPO_URL="https://github.com/hzh-opc/doc-layout-aesthetics"
BRANCH="main"
TARGET="$DEFAULT_TARGET"
MODE="upgrade"          # upgrade | dry-run | check
SKIP_CLEAN=0

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --target) shift; TARGET="$1" ;;
        --repo)   shift; REPO_URL="$1" ;;
        --branch) shift; BRANCH="$1" ;;
        --dry-run) MODE="dry-run" ;;
        --check)  MODE="check" ;;
        --no-clean) SKIP_CLEAN=1 ;;
        -h|--help) sed -n '1,22p' "$0"; exit 0 ;;
        *) echo "未知参数: $1（--help 查看用法）"; exit 1 ;;
    esac
    shift
done

info() { printf '\033[32m[升级]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[错误]\033[0m %s\n' "$*"; exit 1; }

command -v git >/dev/null 2>&1 || fail "未找到 git，请先安装 git（macOS: brew install git）"

# ---------- 守卫：检测目标是否为 office-kit 转向器 ----------
# 本机已装 office-kit 套件时，~/.workbuddy/skills/doc-layout-aesthetics/SKILL.md
# 是转向器（含 redirect_to ~/office-kit/），组件权威副本在套件 components/。
# 直接跑本脚本会覆盖转向器、且与套件副本双源漂移，故告警并中止。
if [ -f "$TARGET/SKILL.md" ] && grep -q "redirect_to" "$TARGET/SKILL.md" 2>/dev/null; then
    warn "目标 $TARGET 当前是 office-kit 转向器（SKILL.md 含 redirect_to）。"
    warn "本机已装 office-kit 套件时，组件权威副本在 components/，请改用：python kit.py upgrade doc-layout-aesthetics"
    warn "本脚本仅适用于 S4「仅组件独立部署」；如确需独立部署，请 --target 指向独立副本目录。"
    exit 1
fi

# ---------- 检查模式：只比较远程与本地版本 ----------
if [ "$MODE" = "check" ]; then
    if [ ! -d "$TARGET/.git" ] && [ ! -f "$TARGET/SKILL.md" ]; then
        echo "技能副本不存在: $TARGET（可运行 --dry-run 或直接升级完成首次安装）"
        exit 0
    fi
    if [ -d "$TARGET/.git" ]; then
        (cd "$TARGET" && git fetch origin "$BRANCH" >/dev/null 2>&1) || true
        local_ver=$(cd "$TARGET" && git rev-parse --short HEAD 2>/dev/null || echo "未知")
        remote_ver=$(git ls-remote "$REPO_URL" "refs/heads/$BRANCH" 2>/dev/null | cut -c1-7)
        echo "本地版本: $local_ver"
        echo "远程版本: ${remote_ver:-无法获取}"
        [ -n "$remote_ver" ] && [ "$local_ver" != "$remote_ver" ] \
            && echo "有可用更新 ✅" || echo "已是最新 ✅"
    else
        echo "副本非 git 克隆（无 .git），无法比较版本；建议直接升级。"
    fi
    exit 0
fi

# ---------- 拉取最新源码到临时目录 ----------
TMP="$(mktemp -d /tmp/dla_upgrade.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

info "拉取仓库: $REPO_URL (branch=$BRANCH)"
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP/repo" >/dev/null 2>&1 \
    || fail "git clone 失败：请检查网络或仓库地址"
VERSION="$(cd "$TMP/repo" && git rev-parse --short HEAD)"
info "远程最新提交: $VERSION"

# ---------- 校验拉取的技能结构 ----------
[ -f "$TMP/repo/SKILL.md" ] || fail "拉取结果缺少 SKILL.md，仓库结构异常，中止"

# ---------- 清理：移除不入副本的文件 ----------
if [ "$SKIP_CLEAN" -eq 0 ]; then
    rm -rf "$TMP/repo/.git"
    find "$TMP/repo" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$TMP/repo" -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$TMP/repo" -name ".DS_Store" -delete 2>/dev/null || true
    rm -rf "$TMP/repo/fonts/common" "$TMP/repo/fonts/SHA256SUMS" 2>/dev/null || true
fi

# ---------- dry-run：只展示将同步的内容 ----------
if [ "$MODE" = "dry-run" ]; then
    if [ -d "$TARGET" ]; then
        echo "以下文件将同步到 $TARGET："
        rsync -avn --delete \
            --exclude='.git/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
            --exclude='.DS_Store' --exclude='fonts/common/' --exclude='fonts/SHA256SUMS' \
            "$TMP/repo/" "$TARGET/" 2>/dev/null | grep -v "^\./$" | head -30
    else
        echo "目标不存在，将创建: $TARGET"
        (cd "$TMP/repo" && find . -type f | head -30)
    fi
    echo "---"
    echo "dry-run 完成（未实际同步）。实际升级请去掉 --dry-run。"
    exit 0
fi

# ---------- 实际同步（rsync 镜像，保持副本干净） ----------
mkdir -p "$TARGET"
command -v rsync >/dev/null 2>&1 || fail "未找到 rsync（macOS/Linux 通常自带）"
info "同步到: $TARGET"
rsync -a --delete \
    --exclude='.git/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='.DS_Store' --exclude='fonts/common/' --exclude='fonts/SHA256SUMS' \
    "$TMP/repo/" "$TARGET/"

# ---------- 收尾验证 ----------
if [ -f "$TARGET/SKILL.md" ]; then
    info "升级完成 ✅ 版本: $VERSION"
    echo "副本内容（不含 .git/缓存/字体）："
    (cd "$TARGET" && find . -type f -not -path './fonts/*' | sort | head -25)
    echo ""
    echo "下一步：技能副本已是最新。字体如需安装：bash $SCRIPT_DIR/../fonts/install_fonts.sh --online"
else
    fail "同步后缺少 SKILL.md，升级失败"
fi
