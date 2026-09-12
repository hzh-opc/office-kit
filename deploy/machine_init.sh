#!/usr/bin/env bash
# machine_init.sh —— 机器级环境初始化（macOS / Linux）
#
# 承接部署提示词「可并入上游」审计 B5/U9：uv + 国内源（uv.toml 5 源）+ 默认环境
# envs/default + 「Python 默认环境」常驻铁律注入。这是“环境 bootstrap”，
# 与技能安装（bootstrap.sh）解耦——单独部署 office-kit 技能时无须运行本脚本；
# 新机器复刻治理体系时先跑本脚本、再跑 bootstrap.sh。
#
# 步骤（全部幂等，可重复执行）：
#   1) 安装 uv（已装则跳过；受限网络可预设 UV_INSTALLER_MIRROR / UV_PYTHON_INSTALL_MIRROR）
#   2) 写 uv.toml 5 源（aliyun/tencent/tsinghua/ustc/huawei，huawei default=true）
#      macOS/Linux: ~/.config/uv/uv.toml
#   3) 建 <BASE>/binaries/python/envs/default（优先受管解释器 3.13.12，否则 uv 拉取 3.13）
#   4) 向 <BASE>/SOUL.md 注入「Python 默认环境」常驻铁律（已存在则跳过）
#
# 用法：
#   ./deploy/machine_init.sh            # 全部四步
#   ./deploy/machine_init.sh --no-soul  # 只做 1-3 步，不动 SOUL.md
#
# 跨平台约定：LF、UTF-8 无 BOM、变量紧邻多字节一律 ${VAR}（macOS bash 3.2 实证）。

set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${HOME}/.workbuddy"
MANAGED_PY="${BASE}/binaries/python/versions/3.13.12/bin/python3"
DEFAULT_ENV="${BASE}/binaries/python/envs/default"
SOUL_FILE="${BASE}/SOUL.md"
INJECT_SOUL=1
for arg in "$@"; do
  case "$arg" in
    --no-soul) INJECT_SOUL=0 ;;
    -h|--help) echo "用法: ./deploy/machine_init.sh [--no-soul]"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

echo "== machine_init：机器级环境初始化（共 4 步）=="

# ---------- 1. 安装 uv ----------
echo "[1/4] 安装 uv..."
if command -v uv >/dev/null 2>&1; then
  echo "      ✓ 已安装：$(uv --version 2>/dev/null || echo 'uv')"
else
  # 国内网络受限时请先 export UV_INSTALLER_MIRROR / UV_PYTHON_INSTALL_MIRROR（清华镜像路径）
  # ⚠ `if !` 守护：pipefail 下安装器管道失败不得无声中止
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    echo "      ✗ uv 安装失败。受限网络请先 export UV_INSTALLER_MIRROR 与 UV_PYTHON_INSTALL_MIRROR 后重试。" >&2
    exit 1
  fi
  # 安装器默认写入 ~/.local/bin，当前 shell 可能未收录
  export PATH="${HOME}/.local/bin:${PATH}"
  echo "      ✓ 安装完成：$(uv --version 2>/dev/null || echo '（需新开 shell 生效）')"
fi

# ---------- 2. 写 uv.toml 5 源 ----------
echo "[2/4] 写 uv.toml（5 源，huawei default=true）..."
UV_CONFIG_DIR="${HOME}/.config/uv"
UV_CONFIG_FILE="${UV_CONFIG_DIR}/uv.toml"
mkdir -p "${UV_CONFIG_DIR}"
if [ -f "${UV_CONFIG_FILE}" ] && grep -q "huaweicloud" "${UV_CONFIG_FILE}" 2>/dev/null; then
  echo "      ✓ 已存在且含 huawei 源，跳过：${UV_CONFIG_FILE}"
else
  cat > "${UV_CONFIG_FILE}" <<'TOML'
# 由 office-kit deploy/machine_init 生成（幂等覆盖；手工调整请改文件并避免重跑本脚本覆盖）
[[index]]
url = "https://mirrors.aliyun.com/pypi/simple/"
name = "aliyun"

[[index]]
url = "https://mirrors.cloud.tencent.com/pypi/simple/"
name = "tencent"

[[index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple/"
name = "tsinghua"

[[index]]
url = "https://pypi.mirrors.ustc.edu.cn/simple/"
name = "ustc"

[[index]]
url = "https://repo.huaweicloud.com/repository/pypi/simple/"
name = "huawei"
default = true
TOML
  echo "      ✓ 已写入：${UV_CONFIG_FILE}"
fi

# ---------- 3. 建 envs/default（扁平目录，直接含 bin/python） ----------
echo "[3/4] 创建默认环境 envs/default..."
if [ -x "${DEFAULT_ENV}/bin/python" ]; then
  echo "      ✓ 已存在，跳过：${DEFAULT_ENV}"
else
  mkdir -p "$(dirname "${DEFAULT_ENV}")"
  if [ -x "${MANAGED_PY}" ]; then
    # 版本钉版靠显式 --python <受管解释器绝对路径>；uv 不会自管另下版本
    uv venv --python "${MANAGED_PY}" "${DEFAULT_ENV}"
  else
    echo "      · 受管解释器未找到（${MANAGED_PY}），改用 uv 拉取 3.13 独立构建版"
    uv venv --python 3.13 "${DEFAULT_ENV}"
  fi
  echo "      ✓ 已创建：${DEFAULT_ENV}"
fi
echo "      提示：装包永远显式 uv pip install --python ${DEFAULT_ENV}/bin/python <pkg>，绝不裸 pip install。"

# ---------- 4. 注入「Python 默认环境」常驻铁律（幂等） ----------
if [ "$INJECT_SOUL" -eq 1 ]; then
  echo "[4/4] 注入「Python 默认环境」常驻铁律到 SOUL.md..."
  mkdir -p "${BASE}"
  if [ -f "${SOUL_FILE}" ] && grep -q "常驻执行规则：Python 默认环境" "${SOUL_FILE}" 2>/dev/null; then
    echo "      ✓ 已存在，跳过（幂等）：${SOUL_FILE}"
  else
    cat >> "${SOUL_FILE}" <<'SOUL'

<!-- machine-init:python-env -->
### 常驻执行规则：Python 默认环境

- 日常执行 Python 默认用 `<BASE>/binaries/python/envs/default`（受管解释器创建的扁平目录环境，直接含 `bin/python`）。
- 装包一律 `uv pip install --python <该环境>/bin/python <pkg>`，绝不裸 `pip install`、不手动激活后裸跑。
- office-kit 例外：其依赖收敛于 `~/office-kit/.venv`（kit 自带 bootstrap 管理），不并入默认环境。
- 完整治理正文见 `<BASE>/config/python-env.md`（按需加载，勿在此展开）。
<!-- /machine-init:python-env -->
SOUL
    # <BASE> 占位替换为真实路径（保留可读性）
    if ! sed -i.bak "s|<BASE>|${BASE}|g" "${SOUL_FILE}"; then
      echo "      ⚠ <BASE> 占位替换失败（铁律段已追加，可手工把 <BASE> 改为 ${BASE}）" >&2
    fi
    rm -f "${SOUL_FILE}.bak"
    echo "      ✓ 已追加：${SOUL_FILE}"
  fi
else
  echo "[4/4] 按 --no-soul 跳过 SOUL.md 注入。"
fi

echo
echo "== machine_init 完成 ✅ =="
echo "   下一步：运行 ./bootstrap.sh 完成 office-kit 技能安装与平台启用（两者解耦，顺序不强制）。"
echo "   验收：uv --version 可用；${DEFAULT_ENV}/bin/python 存在；uv pip install --dry-run pip 解析走 mirrors.*。"
