#!/usr/bin/env bash
# =============================================================================
# doc-layout-aesthetics 字体安装脚本（macOS / Linux 通用）
#
# 安装 doc-layout-aesthetics 技能渲染 PDF/DOCX/PPTX 所需的开源可商用字体：
#   思源宋体 SC（衬线正文）· 思源黑体 SC（无衬线标题）· 霞鹜文楷（楷体）
#   DejaVu Sans Mono（等宽）· 文泉驿正黑（兜底）
#
# 两种模式：
#   离线模式（默认）——从脚本同目录 common/ 下已下载好的字体文件安装
#   在线模式  --online —— 优先用系统包管理器（Homebrew / apt / dnf），
#                        没有包管理器或失败时自动改为 curl 下载安装
#
# 镜像选择：--mirror official（默认，GitHub/SourceForge 官方源）
#                    china    （国内源：npmmirror 阿里 CDN / ghproxy 加速代理）
#
# 兼容性：仅依赖 bash 3.2+（macOS 自带）+ curl + 系统原生命令，无第三方包。
# 用法：
#   ./install_fonts.sh              # 离线安装（默认，需本目录存在 common/）
#   ./install_fonts.sh --dir /path  # 从指定目录安装字体文件
#   ./install_fonts.sh --online     # 在线安装（包管理器优先）
#   ./install_fonts.sh --online --mirror china   # 在线安装（国内源）
#   ./install_fonts.sh --dry-run    # 只列出将安装的文件，不实际安装
# =============================================================================
set -e
# 注：原 set -u 在 bash 3.2 (macOS 默认) + 多字节路径下偶发误报 unbound；脚本已用
# 显式 if [ ! -d ... ] 等做存在性检查，移除 -u 以提升 macOS 兼容性。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="offline"
FONT_DIR=""
MIRROR="official"
DRY_RUN=0
COUNT=0

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --online)  MODE="online" ;;
        --offline) MODE="offline" ;;
        --dir)     shift; FONT_DIR="$1" ;;
        --mirror)  shift; MIRROR="$1" ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "未知参数: $1（--help 查看用法）"; exit 1 ;;
    esac
    shift
done

if [ "$MIRROR" != "official" ] && [ "$MIRROR" != "china" ]; then
    echo "错误: --mirror 仅支持 official|china"; exit 1
fi

# ---------- 确定字体来源目录 ----------
if [ -z "$FONT_DIR" ]; then
    FONT_DIR="$SCRIPT_DIR/common"
fi
if [ ! -d "$FONT_DIR" ]; then
    echo "错误: 字体目录不存在: $FONT_DIR"
    echo "离线模式请先下载字体到 fonts/common/（参考 fonts/../FONTS.md），或使用 --online 在线安装。"
    exit 1
fi

# ---------- 收集字体文件 ----------
FILES=$(find "$FONT_DIR" -type f \( -iname "*.otf" -o -iname "*.ttf" -o -iname "*.ttc" \) 2>/dev/null | sort)
COUNT=$(echo "$FILES" | grep -c . || true)
if [ "$COUNT" -eq 0 ]; then
    echo "错误: $FONT_DIR 下未找到 .otf/.ttf/.ttc 字体文件"; exit 1
fi

# ---------- 平台目标目录 ----------
install_dir() {
    if [ "$(uname)" = "Darwin" ]; then
        echo "$HOME/Library/Fonts"
    else
        echo "$HOME/.local/share/fonts"
    fi
}
TARGET="$(install_dir)"

info()  { printf '\033[32m[安装]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
fail()  { printf '\033[31m[错误]\033[0m %s\n' "$*"; exit 1; }

# ---------- 在线模式：包管理器优先 ----------
install_via_pkg() {
    local os="$(uname)"
    if [ "$os" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        echo "检测到 Homebrew，使用 brew cask 安装（官方源字体 cask）..."
        local casks=(
            font-source-han-serif-sc font-source-han-sans-sc
            font-lxgw-wenkai font-dejavu-sans-mono font-wqy-zenhei
        )
        # 部分 cask 名称可能随版本变化，逐个尝试，失败仅告警
        for c in "${casks[@]}"; do
            if brew list --cask "$c" >/dev/null 2>&1; then
                info "已安装: $c"
            else
                brew install --cask "$c" >/dev/null 2>&1 \
                    && info "brew 安装成功: $c" \
                    || warn "brew cask 安装失败(可能已改名): $c"
            fi
        done
        return 0
    fi
    if [ "$os" = "Linux" ]; then
        local pkgs="fonts-noto-cjk fonts-wqy-zenhei fonts-dejavu-core"
        if command -v apt-get >/dev/null 2>&1; then
            echo "检测到 apt，安装: ${pkgs}（sudo 需要密码）..."
            sudo apt-get update -qq && sudo apt-get install -y -qq $pkgs \
                && info "apt 安装成功" || warn "apt 安装失败"
            return 0
        fi
        if command -v dnf >/dev/null 2>&1; then
            echo "检测到 dnf，安装: $pkgs ..."
            sudo dnf install -y $pkgs && info "dnf 安装成功" || warn "dnf 安装失败"
            return 0
        fi
        if command -v pacman >/dev/null 2>&1; then
            echo "检测到 pacman，安装: noto-fonts-cjk wqy-zenhei ttf-dejavu ..."
            sudo pacman -S --noconfirm noto-fonts-cjk wqy-zenhei ttf-dejavu \
                && info "pacman 安装成功" || warn "pacman 安装失败"
            return 0
        fi
    fi
    return 1
}

# ---------- 在线模式：curl 直接下载（无包管理器时回退） ----------
# 每个字体: "显示名|文件 URL 列表用空格分隔"（URL 按官方/国内镜像二选一）
dl_url() {
    # $1 = 字体 key; $2 = official URL; $3 = china URL
    if [ "$MIRROR" = "china" ]; then echo "$3"; else echo "$2"; fi
}

download_and_install() {
    local tmp="$(mktemp -d /tmp/fonts.XXXXXX)"
    local got=0
    echo "在线下载字体（镜像: ${MIRROR}）到 $tmp ..."

    # 思源黑体 SC（zip 内含 Regular/Bold 等全字重 OTF）
    local sans_url
    sans_url="$(dl_url sans \
        "https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip" \
        "https://ghproxy.net/https://github.com/adobe-fonts/source-han-sans/releases/download/2.005R/09_SourceHanSansSC.zip")"
    echo "  [1/5] 思源黑体 SC ..."
    if curl -fsSL --retry 2 -o "$tmp/shans.zip" "$sans_url" && [ -s "$tmp/shans.zip" ]; then
        (cd "$tmp" && unzip -qo shans.zip '*/SourceHanSansSC-Regular.otf' '*/SourceHanSansSC-Bold.otf' 2>/dev/null \
            || unzip -qo shans.zip 'SourceHanSansSC-*' 2>/dev/null) && got=1
    else warn "思源黑体下载失败"; fi

    # 思源宋体 SC
    local serif_url
    serif_url="$(dl_url serif \
        "https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip" \
        "https://ghproxy.net/https://github.com/adobe-fonts/source-han-serif/releases/download/2.003R/09_SourceHanSerifSC.zip")"
    echo "  [2/5] 思源宋体 SC ..."
    if curl -fsSL --retry 2 -o "$tmp/sherif.zip" "$serif_url" && [ -s "$tmp/sherif.zip" ]; then
        (cd "$tmp" && unzip -qo sherif.zip '*/SourceHanSerifSC-Regular.otf' '*/SourceHanSerifSC-Bold.otf' 2>/dev/null \
            || unzip -qo sherif.zip 'SourceHanSerifSC-*' 2>/dev/null) && got=1
    else warn "思源宋体下载失败"; fi

    # 霞鹜文楷
    local kai_url
    kai_url="$(dl_url kai \
        "https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf" \
        "https://ghproxy.net/https://github.com/lxgw/LxgwWenKai/releases/download/v1.522/LXGWWenKai-Regular.ttf")"
    echo "  [3/5] 霞鹜文楷 ..."
    if curl -fsSL --retry 2 -o "$tmp/LXGWWenKai-Regular.ttf" "$kai_url" && [ -s "$tmp/LXGWWenKai-Regular.ttf" ]; then got=1; else warn "霞鹜文楷下载失败"; fi

    # DejaVu（zip 内含 SansMono/Serif/Sans）
    local dejavu_url
    dejavu_url="$(dl_url dejavu \
        "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip" \
        "https://ghproxy.net/https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip")"
    echo "  [4/5] DejaVu ..."
    if curl -fsSL --retry 2 -o "$tmp/dejavu.zip" "$dejavu_url" && [ -s "$tmp/dejavu.zip" ]; then
        (cd "$tmp" && unzip -qo dejavu.zip '*/DejaVuSansMono.ttf' '*/DejaVuSansMono-Bold.ttf' '*/DejaVuSerif.ttf' '*/DejaVuSans.ttf' 2>/dev/null) && got=1
    else warn "DejaVu 下载失败"; fi

    # 文泉驿正黑
    local wqy_url
    wqy_url="$(dl_url wqy \
        "https://sourceforge.net/projects/wqy/files/wqy-zenhei/0.9.45%20%28Fighting-state%20RC1%29/wqy-zenhei-0.9.45.tar.gz/download" \
        "https://sourceforge.net/projects/wqy/files/wqy-zenhei/0.9.45%20%28Fighting-state%20RC1%29/wqy-zenhei-0.9.45.tar.gz/download")"
    echo "  [5/5] 文泉驿正黑 ..."
    if curl -fsSL --retry 2 -o "$tmp/wqy.tar.gz" "$wqy_url" && [ -s "$tmp/wqy.tar.gz" ]; then
        tar -xzf "$tmp/wqy.tar.gz" -C "$tmp" && got=1
    else warn "文泉驿下载失败"; fi

    if [ "$got" -eq 0 ]; then warn "在线下载全部失败，请检查网络或改用离线模式"; fi

    FILES=$(find "$tmp" -type f \( -iname "*.otf" -o -iname "*.ttf" -o -iname "*.ttc" \) 2>/dev/null | sort)
    COUNT=$(echo "$FILES" | grep -c . || true)
    echo "下载到 $COUNT 个字体文件，开始安装..."
    install_files "$tmp"
    rm -rf "$tmp"
}

# ---------- 安装（复制 + 刷新缓存） ----------
install_files() {
    local src_root="$1"
    mkdir -p "$TARGET"
    local i=0
    for f in $FILES; do
        i=$((i+1))
        local name
        name="$(basename "$f")"
        if [ "$DRY_RUN" -eq 1 ]; then
            printf '  [%d/%d] 将安装 %s -> %s\n' "$i" "$COUNT" "$name" "$TARGET/$name"
        else
            cp -f "$f" "$TARGET/$name" 2>/dev/null && info "[$i/$COUNT] $name" || warn "复制失败: $name"
        fi
    done
    if [ "$DRY_RUN" -eq 0 ]; then
        # 刷新 Linux 字体缓存；macOS 无需手动刷新
        if [ "$(uname)" = "Linux" ] && command -v fc-cache >/dev/null 2>&1; then
            fc-cache -f >/dev/null 2>&1 && info "字体缓存已刷新 (fc-cache)"
        fi
        info "安装完成，共 $COUNT 个字体 -> $TARGET"
        echo "提示: Linux 可用 'fc-list | grep -i sourcehan' 验证；macOS 重启相关应用后生效。"
    fi
}

# ---------- 主流程 ----------
if [ "$MODE" = "online" ]; then
    if install_via_pkg; then
        echo "包管理器路径完成。若仍有缺字，可再运行: $0 --online（将回退到 curl 下载）。"
        exit 0
    fi
    download_and_install
else
    printf '离线安装：来源 %s（共 %d 个字体），目标 %s\n' "$FONT_DIR" "$COUNT" "$TARGET"
    install_files "$FONT_DIR"
fi
