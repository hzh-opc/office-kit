# -*- coding: utf-8 -*-
"""统一构建《版面美学观》全部本地交付物：docx + pptx + html (+pdf)。

依赖由 uv 管理（见 pyproject.toml）。本脚本本身只用到标准库，
子脚本经 `scripts/_venv.py` 解析出的 python 执行。

WorkBuddy 宿主下（对齐 config/python-env.md 治理）：默认直接调全局共享默认环境
`~/.workbuddy/binaries/python/envs/default` 的 python（doc-layout 依赖已并入），
**不走 `uv run --project`**，以免按本技能 pyproject 裁剪默认环境中他技能依赖。
非宿主（Claude/Codex/OpenClaw 等）仍走 `uv run --project`（自有 .venv，无裁剪风险）。

环境解析统一走 `scripts/_venv.py`（可移植）：优先尊重 `UV_PROJECT_ENVIRONMENT`
（用户显式指定）与 `VIRTUAL_ENV`（已激活 venv），两者都缺省时宿主用共享默认环境、
其他平台用项目内 .venv。

用法：
  python scripts/build_all.py                  # 默认输出到当前目录
  python scripts/build_all.py --out /path/dir  # 指定输出目录
  python scripts/build_all.py --pdf            # 额外生成 PDF（自动探测引擎：LibreOffice > docx2pdf > WPS > 纯 Python）
"""
import argparse
import os
import subprocess

import _venv  # 虚拟环境解析：UV_PROJECT_ENVIRONMENT > VIRTUAL_ENV > 平台默认，绝不覆盖用户显式配置

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 技能根目录（pyproject.toml / uv.lock 所在）
# 默认输出当前目录（平台无关，跨 macOS/Linux/Windows 一致），可用 --out 覆盖。
DEFAULT_OUT = os.getcwd()


def _run(script, out, extra=None):
    path = os.path.join(HERE, script)
    cmd = []
    if _venv.ensure_project_env(ROOT):
        cmd = ["uv", "run", "--project", ROOT, "python", path, "--out", out]
    else:
        cmd = [_venv.find_python(ROOT), path, "--out", out]
    if extra:
        cmd += extra
    print(">>>", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败，退出码 {r.returncode}")


def main():
    ap = argparse.ArgumentParser(description="构建 docx / pptx / html (+可选 pdf) 交付物")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--pdf", action="store_true",
                    help="额外把 docx 转 PDF（自动探测引擎：LibreOffice > docx2pdf > WPS > 纯 Python 兜底）")
    args = ap.parse_args()
    out = args.out
    if not args.out and os.path.abspath(out) == os.path.abspath(ROOT):
        print("⚠️ 未指定 --out，且当前目录是技能根目录：产物会写入技能目录，"
              "建议加 --out 指定输出位置，避免被打包进技能 zip。")
    os.makedirs(out, exist_ok=True)

    docx_path = os.path.join(out, "版面美学观_侯捷Word排版艺术提炼.docx")
    for script in ("build_docx.py", "build_pptx.py", "build_html.py"):
        _run(script, out)

    if args.pdf:
        extra = ["--docx", docx_path] if os.path.exists(docx_path) else None
        _run("build_pdf.py", out, extra=extra)

    print("全部构建完成 ->", out)


if __name__ == "__main__":
    main()
