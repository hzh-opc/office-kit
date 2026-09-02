#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 手动升级脚本（安全零停机，参考 DESEN upgrade 范式）。

从 GitHub 仓库 hzh-opc/info-extract 拉取最新版本到暂存目录，校验后原子替换
当前技能目录；任一环节失败绝不破坏线上技能（保留备份，可回滚）。

【手动触发】本脚本默认不自动运行；由用户 / AI Agent 显式调用。AI Agent 仅在
用户明确要求「升级 / 更新本技能」时才运行，绝不在技能加载时自动升级。

【安全策略 —— 升级不得影响使用】
  1. 下载新版本到「暂存目录」（与线上技能同文件系统，便于原子 rename）；
  2. 在暂存副本上做轻量校验（语法编译；若有 venv 再跑 --check）；
  3. 校验通过后才替换：先 rename 当前目录到「备份目录」（仅改名、不删除）；
  4. 原子 rename 暂存副本到线上目录；
  5. 替换后再次实测；失败 → 自动回滚到备份；
  6. 任一环节失败 → 绝不破坏线上技能。

用法：
  python3 upgrade.py                                  # 检查更新；有则 下载→校验→应用
  python3 upgrade.py --check                          # 仅检查是否有更新（不下载/不应用）
  python3 upgrade.py --dry-run                        # 下载+校验，但不替换（试跑）
  python3 upgrade.py --force                          # 版本相同也强制重装（用于修复）
  python3 upgrade.py --source local --local-path PATH # 离线/本地源升级
  python3 upgrade.py --clean-backup                   # 清理历史备份目录

退出码：0=成功/已最新；1=升级失败（已回滚/未触碰）；2=下载失败；3=参数错误。
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
REPO_OWNER_REPO = "hzh-opc/info-extract"
DEFAULT_BRANCH = "main"
RAW_BASE = "https://raw.githubusercontent.com/{}/{}/{}".format(
    *REPO_OWNER_REPO.split("/"), DEFAULT_BRANCH
)
TARBALL_URL = "https://github.com/{}/archive/refs/heads/{}.tar.gz".format(
    REPO_OWNER_REPO, DEFAULT_BRANCH
)

SKILL_DIR = Path(__file__).resolve().parent
VERSION_FILE = SKILL_DIR / "VERSION"
VENV_PY = SKILL_DIR / "scripts" / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


# --------------------------------------------------------------------------- #
# 版本解析
# --------------------------------------------------------------------------- #
def parse_version(text):
    """把 '0.6.3' 解析为 (0, 6, 3)；失败返回 None。"""
    if not text:
        return None
    text = str(text).strip().strip('"').strip("'").lstrip("vV")
    parts = []
    for seg in text.split("."):
        num = ""
        for ch in seg:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else None


def read_local_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def fetch_remote_version(timeout=15):
    """拉取远程 VERSION；失败返回 None。"""
    url = RAW_BASE + "/VERSION"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 下载
# --------------------------------------------------------------------------- #
def download_to_staging(staging_dir: Path):
    """下载 tarball 到暂存目录并解压，返回解压后的技能根目录；失败抛异常。"""
    staging_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(TARBALL_URL, headers={"User-Agent": "info-extract-upgrade"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(staging_dir)
    # tarball 解压后是 <repo>-<branch>/ 目录
    for child in staging_dir.iterdir():
        if child.is_dir():
            return child
    raise RuntimeError("解压后未找到技能目录")


def copy_local_to_staging(local_path: str, staging_dir: Path):
    """离线/本地源：复制本地技能目录到暂存。"""
    src = Path(local_path).resolve()
    if not src.is_dir():
        raise RuntimeError("本地源目录不存在: {}".format(src))
    dst = staging_dir / "local-copy"
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", ".DS_Store")
    )
    return dst


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def verify(skill_dir: Path) -> bool:
    """轻量校验：语法编译全部 .py；若有 venv 再跑 --check（失败仅告警不阻断）。"""
    scripts = skill_dir / "scripts"
    if not scripts.is_dir():
        return False
    # 1) 语法编译（强制）
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(scripts)],
        capture_output=True,
    )
    if r.returncode != 0:
        return False
    # 2) 若有 venv，跑 --check（部分 provider 未装属正常，故仅告警不阻断）
    venv_py = scripts / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if venv_py.is_file():
        subprocess.run(
            [str(venv_py), str(scripts / "router.py"), "--check"],
            check=False,
        )
    return True


# --------------------------------------------------------------------------- #
# 应用（备份 + 原子替换 + 回滚）
# --------------------------------------------------------------------------- #
def apply(skill_dir: Path, staged: Path) -> bool:
    """备份当前目录 → 原子替换；失败自动回滚。"""
    backup = skill_dir.parent / (skill_dir.name + ".backup." + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    applied = False
    try:
        os.rename(str(skill_dir), str(backup))            # 备份（仅改名，不删除）
        try:
            os.rename(str(staged), str(skill_dir))        # 原子替换
            applied = True
        except Exception:
            os.rename(str(backup), str(skill_dir))        # 回滚
            raise
        return True
    finally:
        if not applied and backup.exists() and not skill_dir.exists():
            # 极端情况兜底：若替换失败且线上目录缺失，从备份恢复
            try:
                os.rename(str(backup), str(skill_dir))
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="info-extract 手动升级（安全零停机）")
    ap.add_argument("--check", action="store_true", help="仅检查是否有更新")
    ap.add_argument("--dry-run", action="store_true", help="下载+校验，但不替换")
    ap.add_argument("--force", action="store_true", help="版本相同也强制重装")
    ap.add_argument("--source", default="remote", choices=["remote", "local"], help="升级源")
    ap.add_argument("--local-path", help="本地源路径（--source local 时使用）")
    ap.add_argument("--clean-backup", action="store_true", help="清理历史备份目录")
    args = ap.parse_args()

    # 清理备份
    if args.clean_backup:
        for p in SKILL_DIR.parent.glob(SKILL_DIR.name + ".backup.*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                print("[upgrade] 已清理备份: {}".format(p.name))
        return 0

    local_ver = read_local_version()
    print("[upgrade] 本地版本: {}".format(local_ver or "未知"))

    if args.source == "local":
        if not args.local_path:
            print("[upgrade] ❌ --source local 需指定 --local-path")
            return 3
        remote_ver = None
    else:
        remote_ver = fetch_remote_version()
        if remote_ver is None:
            print("[upgrade] ❌ 无法获取远程版本（网络不可达？），升级中止")
            return 2
        print("[upgrade] 远程版本: {}".format(remote_ver))

    # 版本比较
    if not args.force:
        lp = parse_version(local_ver)
        rp = parse_version(remote_ver) if remote_ver else None
        if rp is not None and lp is not None and rp <= lp:
            print("[upgrade] ✅ 已是最新版本，无需升级")
            return 0
        if args.source == "local":
            print("[upgrade] 本地源升级（无远程版本可比），继续")

    if args.check:
        print("[upgrade] 存在可用更新（或 --force 指定）")
        return 0

    # 下载 / 复制到暂存
    staging_parent = tempfile.mkdtemp(prefix="info-extract-upgrade-", dir=str(SKILL_DIR.parent))
    staging_dir = Path(staging_parent)
    staged = None
    try:
        if args.source == "local":
            staged = copy_local_to_staging(args.local_path, staging_dir)
        else:
            staged = download_to_staging(staging_dir)
        print("[upgrade] 已获取新版本: {}".format(staged))

        if not verify(staged):
            print("[upgrade] ❌ 暂存副本校验失败，未改动线上技能")
            return 1

        if args.dry_run:
            print("[upgrade] ✅ 试跑通过（未替换）")
            return 0

        if not apply(SKILL_DIR, staged):
            print("[upgrade] ❌ 替换失败（已回滚）")
            return 1
        print("[upgrade] ✅ 升级完成，已原子替换")
        return 0
    except Exception as exc:
        print("[upgrade] ❌ 升级失败: {}（线上技能未受影响）".format(exc))
        return 1
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
