# -*- coding: utf-8 -*-
"""虚拟环境解析与运行引导（入口脚本共用，便于跨平台移植）。

设计目标
--------
把「用哪个虚拟环境」的决定权交给**显式配置**，脚本只读取、绝不覆盖：

1. 最高优先级：环境变量 ``UV_PROJECT_ENVIRONMENT``（用户/宿主显式指定）；
2. 其次：已激活的 ``VIRTUAL_ENV``（``source .venv/bin/activate`` 或 ``uv run`` 自动注入）；
3. office-kit 部署自带的 ``<OFFICE_KIT_ROOT>/.venv``（或已部署的生产副本
   ``~/office-kit/.venv``，若存在，见 ``_kit_venv``）；
   覆盖「开发者/用户裸跑脚本、未设上述变量」时落到宿主全局默认环境与 kit
   隔离环境不一致的困惑（kit 经 ``UV_PROJECT_ENVIRONMENT`` 调用时本就命中优先级 1）；
4. 兜底平台默认（见 ``resolve_venv``）：WorkBuddy 宿主 → 全局共享默认环境
   ``~/.workbuddy/binaries/python/envs/default``（依赖经 ``uv pip install --python``
   追加式并入，不另建 venv、禁 ``uv sync``，以免按本技能 pyproject 裁剪他技能依赖）；
   其他平台 → 项目内 ``.venv``（走 ``uv sync``）。

运行引导（见 ``ensure_project_env`` / ``find_python``）：宿主下 ``build_all.py`` 等
**直接调共享默认环境 python 直跑**，不走 ``uv run --project``；非宿主仍走
``uv run --project <技能根目录>``（自有 ``.venv``，无裁剪风险）。

仅依赖标准库，可被 selfcheck.py 等安全 import。
"""
import os
import shutil
import subprocess
import sys


def _is_workbuddy_host():
    """是否运行在 WorkBuddy 宿主（存在 ~/.workbuddy 目录）。"""
    return os.path.isdir(os.path.expanduser("~/.workbuddy"))


DEFAULT_KIT_ROOT = "~/office-kit"


def _kit_venv():
    """office-kit 部署自带的隔离 .venv（若存在），作为裸跑兜底。

    office-kit 以组件方式部署本技能时，会在 ``<OFFICE_KIT_ROOT>/.venv`` 维护
    独立环境（kit.py 已通过 ``UV_PROJECT_ENVIRONMENT`` 注入，此处仅覆盖
    「开发者/用户直接裸跑脚本、未设该变量」的情形，避免落到宿主全局默认环境
    与 kit 隔离环境不一致）。

    探测顺序：``OFFICE_KIT_ROOT``（宿主显式声明）→ ``~/office-kit``（已部署的
    生产副本默认位置）。即「复用已部署生产副本的虚拟环境」（用户 2026-09-11 明确）。
    非 office-kit 部署（两处 .venv 均不存在）返回 ``None``，不影响既有解析顺序。
    仅依赖标准库。
    """
    candidates = []
    root = os.environ.get("OFFICE_KIT_ROOT")
    if root:
        candidates.append(os.path.expanduser(root))
    candidates.append(os.path.expanduser(DEFAULT_KIT_ROOT))
    for r in candidates:
        venv = os.path.join(r, ".venv")
        if os.path.isdir(venv):
            return venv
    return None


def resolve_venv(root):
    """解析虚拟环境目录（按优先级），返回绝对路径。

    优先级：
    1. UV_PROJECT_ENVIRONMENT（显式指定，最高优先级，绝不覆盖）；
    2. VIRTUAL_ENV（已激活的 venv）；
    3. office-kit 部署自带的 ``.venv``（``<OFFICE_KIT_ROOT>/.venv`` 或已部署的生产
       副本 ``~/office-kit/.venv``，见 ``_kit_venv``）；
    4. 平台默认：WorkBuddy 宿主 → 全局共享默认环境；其他平台 → 项目内 .venv。
    """
    explicit = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    active = os.environ.get("VIRTUAL_ENV")
    if active:
        return os.path.abspath(active)
    kit = _kit_venv()
    if kit:
        return os.path.abspath(kit)
    if _is_workbuddy_host():
        # 治理对齐：宿主平台默认 = 全局共享默认环境（依赖并入、不另建 venv）
        return default_env_dir()
    return os.path.join(root, ".venv")


def venv_python(venv):
    """venv 内 python 可执行文件路径（Windows 为 Scripts\\python.exe）。"""
    if sys.platform == "win32":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def default_env_dir():
    """WorkBuddy 全局共享默认环境（见 config/python-env.md 治理）：扁平目录，
    所有技能依赖并入此处（doc-layout 的 python-docx/pptx/reportlab 已并入），
    不另建专属 venv、禁用 uv sync（会按项目 pyproject 裁剪他技能依赖）。"""
    return os.path.expanduser("~/.workbuddy/binaries/python/envs/default")


def default_env_python():
    """共享默认环境内的 python 可执行文件（Windows 为 Scripts\\python.exe）。"""
    if sys.platform == "win32":
        return os.path.join(default_env_dir(), "Scripts", "python.exe")
    return os.path.join(default_env_dir(), "bin", "python")


def ensure_project_env(root):
    """若可用 uv 项目方式运行，确保 UV_PROJECT_ENVIRONMENT 已设置（不覆盖用户值）。

    返回 True 表示应走 `uv run --project <root>`；False 表示回退直接调解释器。
    仅在用户尚未设置 UV_PROJECT_ENVIRONMENT 时才注入平台默认值，
    避免覆盖用户/宿主的显式配置导致 venv 建错位置或重建。

    注意（治理对齐，2026-08-25）：WorkBuddy 宿主下**返回 False**，改由调用方
    经 `find_python` 直接调共享默认环境 python —— 避免 `uv run --project` 按本技能
    pyproject 裁剪默认环境中 desensitization-sop 等他技能依赖
    （config/python-env.md 明令禁止）。非宿主仍走 uv run（自有 .venv，无裁剪风险）。
    """
    has_uv = shutil.which("uv") is not None
    has_project = os.path.exists(os.path.join(root, "pyproject.toml"))
    if not (has_uv and has_project):
        return False
    if _is_workbuddy_host():
        # 宿主：共享默认环境直跑（desen 同模型），不走 uv run --project 以免裁剪
        return False
    if not os.environ.get("UV_PROJECT_ENVIRONMENT"):
        os.environ["UV_PROJECT_ENVIRONMENT"] = resolve_venv(root)
    return True


def find_python(root):
    """uv 不可用时的解释器回退：优先解析出的 venv，再当前解释器，最后 python3。

    候选路径按宿主平台感知：WorkBuddy 宿主才包含 ~/.workbuddy 托管解释器，
    Claude/Codex/OpenClaw 等平台无此目录，直接跳过。仅选用能 import 关键依赖
    （docx/pptx/reportlab）的解释器。
    """
    candidates = [venv_python(resolve_venv(root)), sys.executable, "python3"]
    if _is_workbuddy_host():
        candidates.insert(1, default_env_python())
    for c in candidates:
        try:
            r = subprocess.run(
                [c, "-c", "import docx, pptx, reportlab"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return sys.executable
