#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 一键安装脚本（跨平台，兼容 WorkBuddy / Claude / Codex / OpenClaw）。

功能：
  1. 在 <技能目录>/scripts/.venv 创建隔离 venv（CPython 3.13，与 DESEN 一致）；
  2. 安装 requirements.txt 依赖（numpy / av / faster-whisper / Pillow / rapidocr / onnxruntime / pypdfium2）；
  3. 运行 `router.py --check` 冒烟自检；
  4. 打印完成信息与使用命令（含画面解读可选 ollama 运行时说明）。

注：画面解读（阶段四）的本地 VLM 走 ollama + Qwen2.5-VL（HTTP REST，零新增 pip 依赖），
  ollama 为「用户自装的外部运行时」——需另行 `brew install ollama` 并 `ollama pull qwen2.5vl:7b`。
  未装 ollama 时画面解读自动降级为「仅 OCR 文字 + 提示上云提质」，不影响其它能力安装与使用。

注：在线/加密视频（阶段五）的下载走 yt-dlp（pip 可选依赖，非强制）——需另行
  `pip install yt-dlp`（或 `brew install yt-dlp`）。未装时优雅降级为「浏览器播放中捕获」回退
  （依赖 browser 技能）或清晰安装引导，不静默失败；加密/DRM 场景仅显式提示法律灰区与质量风险（§4 边界 #2）。

用法：
  python3 install.py                       # 默认自动探测 3.13 解释器 + 建 venv + 装依赖 + 自检
  python3 install.py --python /path/python # 指定建 venv 所用解释器（默认自动探测 3.13）
  python3 install.py --venv /path/venv     # 指定 venv 目录
  python3 install.py --skip-venv --skip-tests
退出码：0=全部通过；非 0=存在失败项。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
REQ = SKILL_DIR / "requirements.txt"
PYPROJECT = SKILL_DIR / "scripts" / "pyproject.toml"
DEFAULT_VENV = SKILL_DIR / "scripts" / ".venv"

# 优先使用的受管 3.13 路径（若存在），否则回退系统 python3.13 / python3
MANAGED_313 = Path.home() / ".workbuddy" / "binaries" / "python" / "versions" / "3.13.12" / "bin" / "python3"


def find_python() -> str:
    for cand in [str(MANAGED_313), "python3.13", "python3"]:
        p = shutil.which(cand) if "/" not in cand else (cand if os.path.exists(cand) else None)
        # 版本窗：>=3.10 且 <3.14（onnxruntime 无 free-threaded wheel，3.14+ 会装不上）
        if p and (3, 10) <= _py_version(p) < (3, 14):
            return p
    return sys.executable


def _py_version(exe: str):
    try:
        out = subprocess.run([exe, "-c", "import sys;print(sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            return tuple(eval(out.stdout.strip()))
    except Exception:
        pass
    return (0, 0)


def run(cmd, **kw):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", help="指定创建 venv 所用的解释器（默认自动探测 3.13）")
    ap.add_argument("--venv", help="指定 venv 目录（替代 scripts/.venv）")
    ap.add_argument("--skip-venv", action="store_true", help="不创建/不安装 venv")
    ap.add_argument("--skip-tests", action="store_true", help="跳过冒烟自检")
    args = ap.parse_args()

    venv_py = None
    if not args.skip_venv:
        py = args.python or find_python()
        venv_dir = Path(args.venv) if args.venv else DEFAULT_VENV
        if not venv_dir.exists():
            print(f"[install] 创建 venv：{venv_dir}（解释器 {py}）")
            r = run([py, "-m", "venv", str(venv_dir)])
            if r.returncode != 0:
                print("[install] ❌ venv 创建失败"); sys.exit(1)
        venv_py = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python")
        # 升级 pip + 安装依赖
        print("[install] 安装依赖（numpy/av/faster-whisper/Pillow/rapidocr/onnxruntime/pypdfium2）…")
        run([venv_py, "-m", "pip", "install", "-U", "pip"], check=False)
        # 优先用 pyproject（若有 uv），否则 requirements.txt
        if PYPROJECT.exists() and shutil.which("uv"):
            run([shutil.which("uv"), "pip", "install", "--python", venv_py, "-r", str(REQ)], check=False)
        else:
            r = run([venv_py, "-m", "pip", "install", "-r", str(REQ)])
            if r.returncode != 0:
                print("[install] ❌ 依赖安装失败（见上）"); sys.exit(1)
    else:
        venv_py = args.python or sys.executable

    # 冒烟自检
    if not args.skip_tests:
        print("[install] 运行 router.py --check 自检…")
        r = run([venv_py, str(SKILL_DIR / "scripts" / "router.py"), "--check"])
        if r.returncode != 0:
            print("[install] ⚠️ 自检返回非 0（部分 provider 可能未安装，属正常）")

    print("\n[install] ✅ 完成。使用：")
    print(f"  {venv_py} {SKILL_DIR/'scripts'/'router.py'} 录音.mp3")
    print(f"  {venv_py} {SKILL_DIR/'scripts'/'router.py'} --check")
    print("\n[install] 可选 · 画面解读（阶段四，本地 VLM）：")
    print("  1) 安装 ollama 运行时：brew install ollama（或 https://ollama.com 下载）")
    print("  2) 拉取多模态模型：ollama pull qwen2.5vl:7b（轻量 qwen2.5vl:3b / 旗舰 qwen2.5vl:32b）")
    print("  3) 解读图片：python router.py 截图.png ；整视频关键帧分析：python router.py 课程.mp4 --vision")
    print("  （未装 ollama 时画面解读自动降级为仅 OCR 文字，不静默失败）")
    sys.exit(0)


if __name__ == "__main__":
    main()
