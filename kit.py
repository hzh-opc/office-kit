#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
office-kit 动态注册与分发器（纯标准库，零额外依赖）

设计目标（对照 规划文档/insp-office-kit.md）：
  * 可拆卸模块化：扫描 components/<component>/manifest.json，自动生成"功能记录"
    （command -> component -> entry 的映射），不再手写静态 case 分发。
  * 重叠比对：汇总各组件 capabilities 标记，检测跨组件功能重叠（kit overlaps）。
  * 环境自检：doctor 检测虚拟环境与组件/入口完整性（webui 启动自检的基础）。
  * 反馈文档：feedback 子命令向 workbench/feedback/ 生成含组件名的反馈文件。

用法：
  python kit.py                      # 列出全部已注册命令
  python kit.py list                 # 同上
  python kit.py overlaps             # 列出跨组件功能重叠
  python kit.py doctor               # 环境与组件自检
  python kit.py check [组件...]       # 检测组件完整性 + 远程新版本（只读）
  python kit.py upgrade [组件...]     # 在线升级到远程最新版
  python kit.py repair [组件...]      # 在线修复损坏/缺失组件
  python kit.py feedback --component <name> --title <t> --detail <d> [--severity ...] [--repro ...]
  python kit.py <command> [组件参数...]            # 动态分发
  python kit.py run <command> [组件参数...]         # 同上（显式）
  python kit.py run <command> --dry-run [组件参数...]  # 仅打印将执行的命令，不执行
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path


KIT_DIR = Path(__file__).resolve().parent

# workbench 按业务流程阶段组织的子目录（inbox/extract/desen/summary/render/archive/logs）
WORKBENCH_SUBDIRS = ("inbox", "extract", "desen", "summary", "render", "archive", "logs")

# 远程组件源（组件升级/修复的下载源）。可用环境变量覆盖以适配私有仓库/镜像：
#   OFFICE_KIT_REPO   -> "owner/repo"（默认 hzh-opc/office-kit）
#   OFFICE_KIT_BRANCH -> 分支名（默认 main）
DEFAULT_REPO = "hzh-opc/office-kit"
DEFAULT_BRANCH = "main"

# 组件完整性检测必需的标志文件（缺失即判为损坏，可在线修复）
REQUIRED_MARKERS = ("manifest.json", "SKILL.md")


def _venv_python() -> Path:
    """返回 kit 虚拟环境解释器路径（跨平台）。"""
    if os.name == "nt":
        return KIT_DIR / ".venv" / "Scripts" / "python.exe"
    return KIT_DIR / ".venv" / "bin" / "python"


def _ensure_workbench():
    """补齐 workbench 阶段子目录（幂等），保证新机 clone 后流水线目录开箱可用。"""
    for sub in WORKBENCH_SUBDIRS:
        (KIT_DIR / "workbench" / sub).mkdir(parents=True, exist_ok=True)


# ---------- 远程组件源与升级/修复（check / upgrade / repair） ----------

def _remote_config():
    """返回 (repo, branch)；优先环境变量，回退内置默认。"""
    repo = os.environ.get("OFFICE_KIT_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    branch = os.environ.get("OFFICE_KIT_BRANCH", DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    return repo, branch


def _raw_url(path):
    repo, branch = _remote_config()
    return "https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, path)


def _tarball_url():
    repo, branch = _remote_config()
    return "https://codeload.github.com/%s/tar.gz/refs/heads/%s" % (repo, branch)


def _http_fetch(url, timeout=30):
    """匿名下载 URL 内容，返回 bytes；失败抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": "office-kit"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_version(v):
    """版本字符串 → 可比较的 tuple；空/非法 → ()（视为最旧）。"""
    if not v:
        return ()
    parts = []
    for seg in str(v).split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _scan_component_dirs():
    """列出 components/ 下所有目录名（含 manifest 损坏的），供 check/repair 使用。"""
    root = KIT_DIR / "components"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def _load_manifest(name):
    """读取本地组件 manifest；缺失/损坏返回 None。"""
    p = KIT_DIR / "components" / name / "manifest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _remote_manifest(name):
    """拉取远程某组件 manifest.json；失败返回 None。"""
    try:
        raw = _http_fetch(_raw_url("components/%s/manifest.json" % name))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _remote_components():
    """通过 GitHub API 列出远程 components/ 下的组件目录名；失败返回 None。"""
    repo, branch = _remote_config()
    url = "https://api.github.com/repos/%s/contents/components?ref=%s" % (repo, branch)
    try:
        data = json.loads(_http_fetch(url).decode("utf-8"))
        return sorted(d["name"] for d in data if d.get("type") == "dir")
    except Exception:
        return None


def _component_integrity(name, manifest):
    """本地组件完整性检测，返回 (ok, problems)。manifest=None 表示 manifest.json 缺失/无法解析。"""
    comp_dir = KIT_DIR / "components" / name
    if not comp_dir.is_dir():
        return False, ["组件目录缺失"]
    if manifest is None:
        return False, ["manifest.json 缺失或无法解析"]
    problems = []
    for marker in REQUIRED_MARKERS:
        if not (comp_dir / marker).is_file():
            problems.append("缺失标志文件: %s" % marker)
    for cmd in manifest.get("commands", []) or []:
        entry = cmd.get("entry", "")
        if entry and not (comp_dir / entry).is_file():
            problems.append("入口缺失: %s" % entry)
    return (not problems), problems


def _component_report(name):
    """聚合单个组件的本地状态，返回 dict（check 的基础）。"""
    manifest = _load_manifest(name)
    ok, problems = _component_integrity(name, manifest)
    return {
        "name": name,
        "exists": (KIT_DIR / "components" / name).is_dir(),
        "ok": ok,
        "problems": problems,
        "local_ver": (manifest or {}).get("version"),
        "manifest": manifest,
    }


def _discover_components():
    """扫描 components/*/manifest.json，返回 (components, commands, capabilities)。"""
    components = {}          # name -> manifest dict
    commands = {}            # cmd/alias -> {component, entry, description, category, name}
    capabilities = {}        # capability -> set(component names)
    comp_dir = KIT_DIR / "components"
    if not comp_dir.is_dir():
        return components, commands, capabilities
    for manifest_path in sorted(comp_dir.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 单个清单损坏不应阻断整体扫描
            sys.stderr.write("⚠ 读取清单失败，已跳过：%s (%s)\n" % (manifest_path, exc))
            continue
        name = data.get("component") or manifest_path.parent.name
        components[name] = data
        for cap in data.get("capabilities", []) or []:
            capabilities.setdefault(cap, set()).add(name)
        for cmd in data.get("commands", []) or []:
            cmd_name = cmd.get("name")
            if not cmd_name:
                continue
            rec = {
                "component": name,
                "entry": cmd.get("entry", ""),
                "fallback": cmd.get("fallback", "none"),
                "description": cmd.get("description", ""),
                "category": cmd.get("category", "未分类"),
                "name": cmd_name,
            }
            commands[cmd_name] = rec
            for alias in cmd.get("aliases", []) or []:
                commands[alias] = rec
    return components, commands, capabilities


def _detect_overlaps(commands, capabilities):
    """返回 (cmd_overlaps, cap_overlaps)。"""
    cmd_overlaps = {}
    seen = {}
    for key, rec in commands.items():
        seen.setdefault(rec["name"], []).append(rec["component"])
    for cname, comps in seen.items():
        if len(set(comps)) > 1:
            cmd_overlaps[cname] = sorted(set(comps))
    cap_overlaps = {cap: sorted(comps) for cap, comps in capabilities.items() if len(comps) > 1}
    return cmd_overlaps, cap_overlaps


def cmd_list(components, commands):
    print("office-kit 已注册命令（扫描 components/*/manifest.json 动态生成）：\n")
    by_cat = {}
    seen_names = set()
    for rec in commands.values():
        if rec["name"] in seen_names:
            continue
        seen_names.add(rec["name"])
        by_cat.setdefault(rec["category"], []).append(rec)
    for cat in sorted(by_cat):
        print("【%s】" % cat)
        for rec in sorted(by_cat[cat], key=lambda r: r["name"]):
            print("  %-12s %s" % (rec["name"], rec["description"]))
            print("               ↳ %s → %s" % (rec["component"], rec["entry"]))
        print()
    print("组件数：%d　命令数：%d" % (len(components), len(set(r['name'] for r in commands.values()))))


def cmd_overlaps(components, commands, capabilities):
    cmd_ov, cap_ov = _detect_overlaps(commands, capabilities)
    print("office-kit 跨组件功能重叠检测：\n")
    if cap_ov:
        print("▶ 能力标签重叠（capabilities）：")
        for cap, comps in sorted(cap_ov.items()):
            print("  - %s：%s" % (cap, " / ".join(comps)))
        print("  → 详见 规划文档/功能重叠比对.md 的逐项比对与调用决策。\n")
    else:
        print("▶ 能力标签重叠：无\n")
    if cmd_ov:
        print("▶ 命令名重叠：")
        for cname, comps in sorted(cmd_ov.items()):
            print("  - %s：%s" % (cname, " / ".join(comps)))
        print("  → 需立即裁决，避免分发歧义。\n")
    else:
        print("▶ 命令名重叠：无（分发无歧义）\n")


def cmd_doctor(components):
    print("office-kit 环境与组件自检：\n")
    venv_py = _venv_python()
    ok = True
    if venv_py.is_file():
        print("  ✓ 虚拟环境解释器：%s" % venv_py)
    else:
        ok = False
        print("  ✗ 虚拟环境缺失：%s" % venv_py)
        print("    → 请运行 ./bootstrap.sh（或 bootstrap.ps1）初始化。")
    for name, data in sorted(components.items()):
        comp_path = KIT_DIR / "components" / name
        ver = data.get("version", "未声明")
        if comp_path.is_dir():
            print("  ✓ 组件目录：%s（v%s）" % (name, ver))
        else:
            ok = False
            print("  ✗ 组件目录缺失：%s" % name)
        for cmd in data.get("commands", []) or []:
            entry = cmd.get("entry", "")
            ep = KIT_DIR / "components" / name / entry
            mark = "✓" if ep.is_file() else "✗"
            if mark == "✗":
                ok = False
            print("      %s 入口 %s (%s)" % (mark, cmd.get("name"), entry))
    print()
    print("自检结果：%s" % ("通过 ✅" if ok else "存在问题 ❌（可 kit.py check 诊断 / kit.py repair 在线修复）"))


def _slugify(text):
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    s = "-".join([p for p in "".join(out).split("-") if p])
    return s[:40] or "issue"


def cmd_feedback(components, args):
    parser = argparse.ArgumentParser(
        prog="kit.py feedback",
        description="生成组件问题反馈文档到 workbench/feedback/（规划文档 L13）。")
    parser.add_argument("--component", default="", help="组件名（留空表示工具包本身）")
    parser.add_argument("--title", required=True, help="一句话描述问题（必填）")
    parser.add_argument("--detail", default="", help="问题详细描述")
    parser.add_argument("--severity", default="medium",
                        choices=["low", "medium", "high", "critical"],
                        help="严重度（默认 medium）")
    parser.add_argument("--repro", default="", help="复现步骤")
    parser.add_argument("--contact", default="", help="联系方式")
    try:
        opts = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    comp = opts.component
    if comp and comp not in components:
        sys.stderr.write("⚠ 未知组件：%s（已知：%s）\n" % (comp, ", ".join(sorted(components)) or "（无）"))
        return 2
    fb_dir = KIT_DIR / "workbench" / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(opts.title)
    fname = "%s-%s-%s.md" % (stamp, comp or "kit", slug)
    env_lines = []
    for k, v in (("kit_dir", str(KIT_DIR)), ("venv_python", str(_venv_python())),
                 ("python", sys.version.split()[0]), ("os", os.name)):
        env_lines.append("- %s: %s" % (k, v))
    body = [
        "# 组件反馈 · %s" % opts.title,
        "",
        "> 由 office-kit 自动生成，用于反馈给组件开发者（规划文档 L13）。",
        "",
        "## 元信息",
        "- component: %s" % (comp or "（工具包本身）"),
        "- severity: %s" % opts.severity,
        "- created: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "- contact: %s" % (opts.contact or "（未提供）"),
        "",
        "## 问题描述",
        opts.detail or "（待补充）",
        "",
        "## 复现步骤",
        opts.repro or "（待补充）",
        "",
        "## 环境",
        "\n".join(env_lines),
        "",
    ]
    (fb_dir / fname).write_text("\n".join(body), encoding="utf-8")
    print("✓ 反馈文档已生成：%s" % (fb_dir / fname))
    print("  组件：%s　标题：%s" % (comp or "（工具包本身）", opts.title))
    return 0


def _download_and_install(name, old_ver, new_ver):
    """下载远程 tarball 并安装单个组件。返回 (ok, msg)。"""
    try:
        raw = _http_fetch(_tarball_url(), timeout=180)
    except Exception as exc:  # noqa: BLE001
        return False, "下载失败: %s" % exc
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tgz = tmp_path / "office-kit.tar.gz"
            tgz.write_bytes(raw)
            try:
                with tarfile.open(tgz, "r:gz") as tf:
                    try:
                        tf.extractall(tmp_path, filter="data")  # Py3.12+ 安全过滤
                    except TypeError:
                        tf.extractall(tmp_path)  # Py3.10/3.11 无 filter 参数
            except Exception as exc:  # noqa: BLE001
                return False, "解压失败: %s" % exc
            # 定位 tarball 内的 components/<name>（对顶层目录名不敏感）
            src = None
            for root in tmp_path.iterdir():
                cand = root / "components" / name
                if cand.is_dir():
                    src = cand
                    break
            if src is None:
                return False, "远程仓库中未找到组件目录: %s" % name
            # 备份旧组件（移动到 workbench/archive/components/，非硬删）
            dest = KIT_DIR / "components" / name
            if dest.exists():
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = (KIT_DIR / "workbench" / "archive" / "components"
                          / ("%s-%s-%s" % (name, old_ver or "unknown", stamp)))
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(backup))
            # 安装新组件
            shutil.copytree(str(src), str(dest))
            # 清理 __pycache__（避免携带宿主机字节码）
            for pyc in dest.rglob("__pycache__"):
                if pyc.is_dir():
                    shutil.rmtree(str(pyc))
    except Exception as exc:  # noqa: BLE001
        return False, "安装失败: %s" % exc
    return True, "已更新 %s：%s → %s" % (name, old_ver or "缺失", new_ver or "未知")


def _log_component_event(name, action, old_ver, new_ver, detail=""):
    """追加一条组件升级/修复事件到 workbench/logs/component-events.log。"""
    log_file = KIT_DIR / "workbench" / "logs" / "component-events.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %-7s %-22s %s -> %-8s %s\n" % (
        now, action, name, old_ver or "-", new_ver or "-", detail)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)


def _write_registry():
    """生成/更新组件上下游对接记录（component-registry.json）。

    上游：来源仓库/分支/版本；下游：注册命令、能力标签、组件间共享能力与显式依赖。
    """
    comps, cmds, caps = _discover_components()
    repo, branch = _remote_config()
    _, cap_ov = _detect_overlaps(cmds, caps)
    registry = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": {"repo": repo, "branch": branch},
        "components": {},
    }
    for name, manifest in sorted(comps.items()):
        comp_cmds = sorted({r["name"] for r in cmds.values() if r["component"] == name})
        caps_of_comp = sorted(manifest.get("capabilities", []) or [])
        shares = sorted({other for cap in caps_of_comp for other in cap_ov.get(cap, []) if other != name})
        registry["components"][name] = {
            "version": manifest.get("version", "未声明"),
            "display_name": manifest.get("display_name", name),
            "commands": comp_cmds,
            "capabilities": caps_of_comp,
            "dependencies": manifest.get("dependencies", []) or [],
            "shares_capabilities_with": shares,
        }
    out = KIT_DIR / "workbench" / "logs" / "component-registry.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _describe_component(name, manifest):
    """打印组件能力识别结果（升级/修复后调用）。"""
    if not manifest:
        print("  ⚠ 无法识别 %s 的能力（manifest 缺失/损坏）" % name)
        return
    cmds = sorted({c.get("name") for c in manifest.get("commands", []) if c.get("name")})
    caps = sorted(manifest.get("capabilities", []) or [])
    print("  · 能力识别 v%s　命令 %s　能力 %s" % (
        manifest.get("version", "未声明"),
        ", ".join(cmds) or "（无）",
        ", ".join(caps) or "（无）",
    ))


def _confirm(prompt):
    """交互确认；EOF 视为否。"""
    try:
        ans = input(prompt + " [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    return ans in ("y", "yes")


def cmd_check(components, args):
    parser = argparse.ArgumentParser(
        prog="kit.py check",
        description="检测组件完整性（本地）与版本（远程），只读、不下载。")
    parser.add_argument("components", nargs="*", help="组件名（默认全部）")
    parser.add_argument("--offline", action="store_true", help="仅本地完整性检测，不联网查版本")
    try:
        opts = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    repo, branch = _remote_config()
    names = opts.components or _scan_component_dirs()
    if not names:
        print("components/ 下未发现任何组件目录。")
        return 1

    print("office-kit 组件检测（远程源 %s@%s）：\n" % (repo, branch))
    all_ok = True
    for name in names:
        rep = _component_report(name)
        local_ver = rep["local_ver"]
        if not rep["exists"]:
            all_ok = False
            print("✗ %-22s 组件目录缺失（kit.py repair %s 在线恢复）" % (name, name))
            continue
        if not rep["ok"]:
            all_ok = False
            print("✗ %-22s 损坏：%s" % (name, "；".join(rep["problems"])))
        else:
            print("✓ %-22s 完整（本地 v%s）" % (name, local_ver or "未声明"))
        if not opts.offline:
            remote = _remote_manifest(name)
            rver = (remote or {}).get("version")
            if remote is None:
                print("      ? 远程版本未知（网络失败或组件不在远程）")
                all_ok = False
            elif rver is None:
                print("      ? 远程未声明 version（可能为旧版，建议 upgrade 同步）")
                all_ok = False
            elif _parse_version(rver) > _parse_version(local_ver):
                print("      ↑ 有新版本 %s → %s（kit.py upgrade %s）" % (local_ver or "?", rver, name))
                all_ok = False
            else:
                print("      ✓ 已是最新（远程 v%s）" % rver)
    print()
    print("检测结果：%s" % ("全部正常 ✅" if all_ok else "存在可修复/可升级项 ❌"))
    return 0 if all_ok else 1


def cmd_upgrade(components, args):
    parser = argparse.ArgumentParser(
        prog="kit.py upgrade",
        description="在线升级组件到远程最新版（有新版才下载，--force 强制同步）。")
    parser.add_argument("components", nargs="*", help="组件名（默认全部）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认（脚本/CI 用）")
    parser.add_argument("--force", action="store_true", help="即使本地已最新也强制重下载")
    try:
        opts = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    repo, branch = _remote_config()
    names = opts.components or _scan_component_dirs()
    if not names:
        print("components/ 下未发现任何组件目录。")
        return 2

    print("office-kit 组件升级（远程源 %s@%s）：\n" % (repo, branch))
    plan = []
    for name in names:
        rep = _component_report(name)
        local_ver = rep["local_ver"]
        remote = _remote_manifest(name)
        rver = (remote or {}).get("version")
        if opts.force:
            plan.append((name, local_ver, rver, "force"))
        elif remote is None:
            print("✗ %-22s 远程不可达，跳过" % name)
        elif rver is None:
            print("? %-22s 远程未声明版本，跳过（可用 --force 强制同步）" % name)
        elif _parse_version(rver) > _parse_version(local_ver):
            plan.append((name, local_ver, rver, "upgrade"))
        else:
            print("✓ %-22s 已是最新（v%s）" % (name, local_ver or "?"))
    if not plan:
        print("\n无待升级组件。")
        return 0

    print("\n待升级组件：")
    for name, old, new, why in plan:
        print("  - %-22s %s → %s（%s）" % (name, old or "缺失", new or "未知", why))
    if not opts.yes and not _confirm("\n确认在线下载并升级以上组件？"):
        print("已取消。")
        return 0

    failures = 0
    for name, old, new, why in plan:
        print("\n▶ 升级 %s ..." % name)
        ok, msg = _download_and_install(name, old, new)
        if ok:
            print("  ✓ %s" % msg)
            _log_component_event(name, "upgrade", old, new, why)
            _describe_component(name, _load_manifest(name))
        else:
            failures += 1
            print("  ✗ %s" % msg)
    reg = _write_registry()
    print("\n上下游对接记录已更新：%s" % reg)
    print("  提示：若组件依赖（requirements.txt）有变化，请运行 ./bootstrap.sh 重装依赖。")
    if failures:
        print("升级完成，%d 个组件失败。" % failures)
        return 2
    print("升级完成 ✅")
    return 0


def cmd_repair(components, args):
    parser = argparse.ArgumentParser(
        prog="kit.py repair",
        description="在线修复损坏/缺失的组件（重下载覆盖）。")
    parser.add_argument("components", nargs="*", help="组件名（默认：本地目录 ∪ 远程清单）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认（脚本/CI 用）")
    try:
        opts = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    repo, branch = _remote_config()
    if opts.components:
        names = opts.components
    else:
        remote_list = _remote_components() or []
        names = list(dict.fromkeys(_scan_component_dirs() + remote_list))
    if not names:
        print("未发现可检测的组件（本地无目录且远程清单不可达）。")
        return 2

    print("office-kit 组件修复（远程源 %s@%s）：\n" % (repo, branch))
    plan = []
    for name in names:
        rep = _component_report(name)
        if rep["ok"]:
            print("✓ %-22s 完整（无需修复）" % name)
        else:
            problems = rep["problems"] or ["组件目录缺失"]
            plan.append((name, rep["local_ver"], problems))
            print("✗ %-22s 需修复：%s" % (name, "；".join(problems)))
    if not plan:
        print("\n无损坏组件，无需修复。")
        return 0

    if not opts.yes and not _confirm("\n确认在线下载并修复以上组件？"):
        print("已取消。")
        return 0

    failures = 0
    for name, old, problems in plan:
        remote = _remote_manifest(name)
        rver = (remote or {}).get("version")
        print("\n▶ 修复 %s ..." % name)
        ok, msg = _download_and_install(name, old, rver)
        if ok:
            print("  ✓ %s" % msg)
            _log_component_event(name, "repair", old, rver, "；".join(problems))
            _describe_component(name, _load_manifest(name))
        else:
            failures += 1
            print("  ✗ %s" % msg)
    reg = _write_registry()
    print("\n上下游对接记录已更新：%s" % reg)
    print("  提示：若组件依赖（requirements.txt）有变化，请运行 ./bootstrap.sh 重装依赖。")
    if failures:
        print("修复完成，%d 个组件失败（请检查网络或远程源）。" % failures)
        return 2
    print("修复完成 ✅")
    return 0


# ---------------------------------------------------------------------------
# 外发必扫 DESEN 铁律（套件反馈 P0-②）：分发层唯一外发门禁。
# 「凡外发必先 desen scan，未扫即阻断」——DESEN 已装时强制前置扫描；未装时
# 显式提醒 + 组件最小脱敏兜底，不随意阻断任务。详见套件 SKILL.md「外发必扫
# DESEN 铁律」节与 归档/feedback/office-kit（套件）反馈·外发铁律审计.md。
# ---------------------------------------------------------------------------

# 外发命令：把信息送出本机的命令（含隐性外发）。键=命令名，值=说明。
# 新增外发能力时须在此登记（套件 SKILL.md 外发边界清单同步维护）。
EXTERNAL_COMMANDS = {
    "tencent-doc": "Markdown→腾讯文档云端（docs.qq.com）",
    # summarize 的上云/翻译/TTS/联网补全由组件脚本自身在 --mode cloud/hybrid、
    # translation、podcast --tts、search 等子动作触发外发，套件层在此按命令级
    # 统一拦 summarize（其外发子动作由组件 skill_bridge 已装即必扫兜底）。
    "summarize": "摘要上云/翻译/TTS/联网补全/知识库沉淀等隐性外发",
}

# 触发 summarize 外发的参数片段（用于精确提示，实际拦截以命令级为准）。
_SUMMARIZE_EXTERNAL_HINTS = ("--mode cloud", "--mode hybrid", "cloud", "hybrid", "translation", "--tts", "search")


def _desen_component() -> "dict | None":
    """检测 desensitization-sop 组件是否已装（本地 components/ 下且 manifest 可解析）。"""
    m = _load_manifest("desensitization-sop")
    if not m:
        return None
    entry = KIT_DIR / "components" / "desensitization-sop" / (m.get("commands", [{}])[0].get("entry") or "")
    if not entry.is_file():
        return None
    return {"manifest": m, "entry": entry}


def _run_desen_scan(paths):
    """调用 desen scan 子命令做外发前强制扫描。返回 (passed: bool, output: str)。"""
    desen = _desen_component()
    venv_py = _venv_python()
    if not desen or not venv_py.is_file():
        return False, "DESEN 组件或虚拟环境缺失，无法执行 scan"
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_py.parent)
    env["OFFICE_KIT_ROOT"] = str(KIT_DIR)
    cmd = [str(venv_py), str(desen["entry"]), "scan"] + list(paths)
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    except Exception as exc:  # noqa: BLE001
        return False, "desen scan 调用失败：%s" % exc
    out = (proc.stdout or "").strip() + ("\n" + proc.stderr.strip() if proc.stderr and proc.stderr.strip() else "")
    # 注意：desen 的 cmd_scan 即使命中敏感信息也不返回非零退出码（只打印命中汇总），
    # 故不能仅凭 returncode==0 判「通过」。改为解析输出：命中敏感 → 出现「汇总：」；
    # 干净 → 出现「未发现已知敏感标识符」。两者皆无则视为异常，保守阻断（fail-safe）。
    if "未发现已知敏感标识符" in out:
        return True, out
    if "汇总：" in out:
        return False, out
    return False, out or "（desen scan 无有效输出）"


def _external_scan_targets(rest):
    """从外发命令参数中提取应扫描的输入文件/目录。

    仅把「真实存在的输入」纳入扫描；排除选项及其值（如 `--chars 50` 的 `50`、
    `--title X` 的 `X`、`--format json`、`--out <路径>` 等），避免把它们误当扫描
    目标传给 `desen scan` 导致参数非法并触发 fail-safe 误阻断。

    处理规则：
    - 以 `-` 开头的 token：选项本身；附着形式 `--out=...` 整体排除；空格形式
      `--out <val>` 标记「跳过下一 token」（输出路径即使存在也不扫）。
    - 其余 token：仅当 `os.path.exists` 为真（输入文件或目录）才纳入扫描。
    """
    out_flags = {"--out", "-o"}
    targets, skip_next = [], False
    for tok in rest:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            head = tok.split("=", 1)[0]
            if head in out_flags:
                if "=" in tok:
                    continue            # 附着形式 --out=... 已含值，整体排除
                skip_next = True        # 空格形式 --out <val> 跳过下一 token
            continue
        if os.path.exists(tok):
            targets.append(tok)
    return targets


def _external_gate(target, rest):
    """外发命令门禁。返回 (allow: bool, note: str)。allow=False 表示阻断。

    分两路：
    - DESEN 已装：强制前置 desen scan，未通过即阻断；
    - DESEN 未装：显式提醒（风险告知前置）+ 组件最小脱敏兜底，不随意阻断。
    同时支持环境变量 OFFICE_KIT_SKIP_EXTERNAL_GATE=1 显式跳过（用户自主放行，
    与 security-scan 的 Skip 档一致）。
    """
    if os.environ.get("OFFICE_KIT_SKIP_EXTERNAL_GATE") == "1":
        return True, "（已显式跳过外发门禁 OFFICE_KIT_SKIP_EXTERNAL_GATE=1）"
    desen = _desen_component()
    if desen is None:
        # 未装 DESEN：不阻断，但显式提醒风险。
        return True, (
            "⚠ 未检测到脱敏技能（desensitization-sop 未安装）。本次「%s」属外发动作，"
            "未经完整脱敏，请自行确认待发内容不含敏感信息。" % target
        )
    # 已装 DESEN：强制前置 scan。仅扫描真实存在的输入（排除选项值，见 _external_scan_targets）。
    paths = _external_scan_targets(rest)
    passed, out = _run_desen_scan(paths)
    if passed:
        return True, "✓ 外发前 desen scan 通过"
    return False, (
        "✗ 外发必扫 DESEN 未通过，已阻断「%s」执行。\n"
        "  请先运行 `desen run <文档> --out workbench/desen/` 完成脱敏后再外发。\n"
        "  扫描详情：\n%s" % (target, out or "（无输出）")
    )


def cmd_run(commands, argv):
    target = argv[0]
    rest = argv[1:]
    dry = False
    if "--dry-run" in rest:
        dry = True
        rest = [a for a in rest if a != "--dry-run"]
    rec = commands.get(target)
    if not rec:
        # 命令未注册：多为「命令所属组件未安装」。给清晰提醒 + 修复指引，不假装成功。
        known = sorted(set(r['name'] for r in commands.values()))
        sys.stderr.write(
            "✗ 未知命令：%s\n"
            "  可能原因：对应组件未安装 / 未同步。\n"
            "  已注册命令：%s\n"
            "  → 请用 `kit.py list` 查看已注册命令，`kit.py repair <组件名>` 在线修复/安装缺失组件。\n"
            % (target, ", ".join(known) or "（无）")
        )
        return 2
    venv_py = _venv_python()
    entry = KIT_DIR / "components" / rec["component"] / rec["entry"]
    if not entry.is_file():
        sys.stderr.write(
            "✗ 入口不存在：%s\n"
            "  → 组件「%s」已损坏或未完整同步，请运行 `kit.py repair %s` 在线修复。\n"
            % (entry, rec["component"], rec["component"])
        )
        return 2
    if dry:
        print("[dry-run] %s %s %s" % (venv_py, entry, " ".join(rest)))
        return 0
    # venv 缺失时的降级：fallback=minimal-stdlib 的命令（纯标准库、无第三方依赖）
    # 可用系统 Python 直接运行，不阻断任务；其余（none）依赖 venv，保持硬提示。
    if not venv_py.is_file():
        if rec.get("fallback") == "minimal-stdlib":
            sys.stderr.write(
                "⚠ 虚拟环境缺失（%s），命令「%s」为纯标准库实现，已降级到系统 Python 执行。\n"
                "  如需完整能力请运行 ./bootstrap.sh 初始化。\n" % (venv_py, target)
            )
            py = sys.executable
        else:
            sys.stderr.write("✗ 虚拟环境缺失：%s\n→ 请先运行 ./bootstrap.sh 初始化。\n" % venv_py)
            return 3
    else:
        py = venv_py
    # 外发命令门禁（套件反馈 P0-②）：外发命令执行前强制前置 desen scan。
    if target in EXTERNAL_COMMANDS:
        allow, note = _external_gate(target, rest)
        print(note)
        if not allow:
            return 3
    # 集成层统一 venv 约定（2026-09-01，office-kit 设计评审反馈）：
    # 显式向组件进程注入 venv 真相源，避免组件自行 re-exec 到错误路径。
    #   UV_PROJECT_ENVIRONMENT → kit 根 .venv（doc-layout / info-extract 优先读取）
    #   OFFICE_KIT_ROOT         → kit 根目录（doc-layout 兜底优先复用 kit/.venv）
    # 降级到系统 Python（fallback=minimal-stdlib）时不注入 venv 真相源（不存在）。
    env = dict(os.environ)
    env["OFFICE_KIT_ROOT"] = str(KIT_DIR)
    if py == venv_py:
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_py.parent)
    try:
        proc = subprocess.run([str(py), str(entry)] + rest, env=env)
        return proc.returncode
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("✗ 调用失败：%s\n" % exc)
        return 3


# ---------------------------------------------------------------------------
# 工作流（插件/预设）机制：扫描 workflows/*/workflow.json，按步骤分发既有的
# 套件内建命令 / 组件命令 / 外部 shell（media 环境），落工作记录链
# （pipeline_state.json），支持人工确认门与断点续跑。
# 设计原则（见 规划文档/插件预设机制可行性分析.md 方案 A）：
#   * 工作流 = 对既有能力的可声明式编排，不重造逻辑；
#   * 每步 uses 指向 kit 内建命令 / 组件命令 / shell（media 环境）；
#   * state 链复用视频交付工作流既有的 pipeline_state 思路。
# ---------------------------------------------------------------------------

WORKFLOW_DIR = KIT_DIR / "workflows"


def _scan_workflow_dirs():
    """返回 workflows/ 下含 workflow.json 的目录名列表。"""
    if not WORKFLOW_DIR.is_dir():
        return []
    out = []
    for d in sorted(WORKFLOW_DIR.glob("*")):
        if d.is_dir() and (d / "workflow.json").is_file():
            out.append(d.name)
    return out


def _load_workflow(name):
    """读取工作流契约；缺失/损坏返回 (None, 错误)。"""
    p = WORKFLOW_DIR / name / "workflow.json"
    if not p.is_file():
        return None, "未找到工作流：%s（%s 不存在）" % (name, p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "workflow.json 解析失败：%s" % exc
    if not data.get("workflow"):
        return None, "workflow.json 缺 workflow 字段"
    return data, None


def _workflow_state_path(data, params):
    """解析工作记录链根目录与 pipeline_state.json 路径。"""
    ws = params.get("workspace") or str(WORKFLOW_DIR / data["workflow"] / "_state")
    root = Path(ws).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "pipeline_state.json", root


def _load_state(state_path):
    if state_path.is_file():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"workflow": None, "steps": {}}


def _resolve_uses(uses, cmds):
    """把 uses 解析为 (kind, tokens)。
    kind: 'component'（注册命令）/ 'kit'（内建）/ 'shell'（media 等外部）。
    """
    if isinstance(uses, dict):
        if "component" in uses:
            return "component", [uses["component"]] + list(uses.get("args", []))
        if "kit" in uses:
            return "kit", [uses["kit"]] + list(uses.get("args", []))
        if "shell" in uses:
            return "shell", uses["shell"]
        return "shell", json.dumps(uses, ensure_ascii=False)
    toks = uses.split()
    cmd = toks[0]
    if cmd in cmds:
        return "component", toks
    if cmd in ("list", "overlaps", "doctor", "check", "upgrade", "repair", "workflow"):
        return "kit", toks
    return "shell", uses


def _run_step_uses(kind, tokens, cmds, dry):
    """执行单步 uses；返回 (rc, note)。dry 仅打印。"""
    if kind == "component":
        rec = cmds[tokens[0]]
        venv_py = _venv_python()
        entry = KIT_DIR / "components" / rec["component"] / rec["entry"]
        if dry:
            print("  [dry-run] component %s → %s %s %s" % (tokens[0], venv_py, entry, " ".join(tokens[1:])))
            return 0, "dry-run"
        if not venv_py.is_file():
            return 3, "venv 缺失"
        env = dict(os.environ)
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_py.parent)
        env["OFFICE_KIT_ROOT"] = str(KIT_DIR)
        try:
            proc = subprocess.run([str(venv_py), str(entry)] + tokens[1:], env=env)
            return proc.returncode, "ok"
        except Exception as exc:  # noqa: BLE001
            return 3, "调用失败：%s" % exc
    if kind == "kit":
        if dry:
            print("  [dry-run] kit %s" % " ".join(tokens))
            return 0, "dry-run"
        rc = main(tokens)  # 复用主分发（doctor/list 等）
        return (rc or 0), "ok"
    # shell（media 环境等）
    if dry:
        print("  [dry-run] shell: %s" % tokens)
        return 0, "dry-run"
    try:
        proc = subprocess.run(tokens, shell=True)
        return proc.returncode, "ok"
    except Exception as exc:  # noqa: BLE001
        return 3, "shell 失败：%s" % exc


def _eval_when(when, params):
    """极简条件：支持 'k==v' / 'k!=v' / 'k in a,b,c' / 'k not in a,b,c' / 单 token 真值。
    值缺失（None/空）时按空串参与比较，避免 str(None) 造成的误判。"""
    when = when.strip()
    # in / not in：值列表匹配（逗号分隔，去空白）
    m = re.match(r"^(\w+)\s+(not\s+in|in)\s+(.+)$", when)
    if m:
        k, op, raw = m.group(1), m.group(2), m.group(3)
        vals = [x.strip().strip('"\'') for x in raw.split(",") if x.strip()]
        cur = str(params.get(k) or "")
        hit = cur in vals
        return (not hit) if op.startswith("not") else hit
    # == / !=
    m = re.match(r"^(\w+)\s*(==|!=)\s*(.+)$", when)
    if m:
        k, op, v = m.group(1), m.group(2), m.group(3).strip().strip('"\'')
        cur = str(params.get(k) or "")
        return cur == v if op == "==" else cur != v
    return bool(params.get(when))


def _subst_params(s, params):
    """把 {k} 替换为 params[k]（缺失保留原样）。"""

    def _rep(mm):
        key = mm.group(1)
        return str(params[key]) if key in params else mm.group(0)

    return re.sub(r"\{(\w+)\}", _rep, s)


def cmd_workflow(cmds, argv):
    if not argv or argv[0] in ("-h", "--help", "list"):
        names = _scan_workflow_dirs()
        if not names:
            print("未发现有工作流（workflows/ 下无含 workflow.json 的目录）。")
            return 0
        print("office-kit 工作流（扫描 workflows/*/workflow.json）：\n")
        for n in names:
            data, err = _load_workflow(n)
            if err:
                print("  ✗ %-22s %s" % (n, err))
                continue
            trig = data.get("trigger", {})
            kw = trig.get("intent_keywords", []) if isinstance(trig, dict) else []
            print("  · %-22s v%s" % (data.get("workflow"), data.get("version", "?")))
            print("      触发：%s" % ("/".join(kw) if kw else "（无）"))
            print("      步骤：%d" % len(data.get("steps", [])))
        return 0
    if argv[0] == "run":
        return _workflow_run(cmds, argv[1:])
    if argv[0] == "step-done":
        return _workflow_step_done(cmds, argv[1:])
    if argv[0] == "show":
        return _workflow_show(cmds, argv[1:])
    sys.stderr.write("✗ 未知 workflow 子命令：%s\n" % argv[0])
    return 2


def _workflow_show(cmds, argv):
    """查看单个工作流详情：kit workflow show <name>"""
    if not argv:
        sys.stderr.write("✗ 用法：kit workflow show <name>\n")
        return 2
    name = argv[0]
    data, err = _load_workflow(name)
    if err:
        sys.stderr.write("✗ %s\n" % err)
        return 2
    print("工作流：%s v%s" % (data.get("workflow"), data.get("version", "?")))
    print("标题：%s" % data.get("title", ""))
    print("描述：%s" % data.get("description", ""))
    trig = data.get("trigger", {})
    if isinstance(trig, dict) and trig.get("intent_keywords"):
        print("触发词：%s" % "/".join(trig["intent_keywords"]))
    params = data.get("params", {}) or {}
    if params:
        print("参数：")
        for k, v in params.items():
            if isinstance(v, dict):
                d = v.get("default")
                # default 为 None 或缺失 → 视为无默认（需显式传入）；空串 → 可选留空
                label = "（无默认）" if (d is None or "default" not in v) else repr(d)
            else:
                label = repr(v)
            print("  %-18s 默认=%s" % (k, label))
    steps = data.get("steps", []) or []
    print("步骤（%d）：" % len(steps))
    for i, s in enumerate(steps, 1):
        tag = "agent" if s.get("executor") == "agent" else ("runner" if s.get("uses") else "-")
        when = (" [when: %s]" % s["when"]) if s.get("when") else ""
        print("  #%-2d %-22s %s%s" % (i, s.get("id"), tag, when))
    return 0


def _workflow_step_done(cmds, argv):
    """Agent 完成 executor=agent 步骤后回填状态：kit workflow step-done <name> <step_id> [--workspace <dir>]"""
    parser = argparse.ArgumentParser(prog="kit.py workflow step-done", add_help=True)
    parser.add_argument("name", help="工作流名")
    parser.add_argument("step_id", help="待回填的步骤 id")
    parser.add_argument("--workspace", default=None, help="工作记录链根目录（同 run）")
    try:
        opts = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    data, err = _load_workflow(opts.name)
    if err:
        sys.stderr.write("✗ %s\n" % err)
        return 2

    # 复用 run 的参数合并逻辑（仅取默认值 + workspace 覆盖）
    params = {}
    for k, v in (data.get("params", {}) or {}).items():
        params[k] = v.get("default") if isinstance(v, dict) else v
    if opts.workspace:
        params["workspace"] = opts.workspace

    state_path, _ = _workflow_state_path(data, params)
    state = _load_state(state_path)
    step_rec = state.setdefault("steps", {}).get(opts.step_id)
    if not step_rec:
        sys.stderr.write("✗ 未找到步骤 %s 的状态记录（可能尚未运行到该步）。\n" % opts.step_id)
        return 2

    step_rec["status"] = "done"
    step_rec["finished_at"] = datetime.now().isoformat(timespec="seconds")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✓ 步骤 %s 已回填为 done。加 --resume 续跑：kit workflow run %s --resume --workspace %s" % (
        opts.step_id, data["workflow"], params.get("workspace") or "<workspace>"))
    return 0


def _workflow_run(cmds, argv):
    parser = argparse.ArgumentParser(prog="kit.py workflow run", add_help=True)
    parser.add_argument("name", help="工作流名（workflows/<name>）")
    parser.add_argument("--resume", action="store_true", help="跳过已完成步骤，从断点续跑")
    parser.add_argument("--step", type=int, default=None, help="仅运行第 N 步（1-based）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印计划不执行")
    parser.add_argument("--yes", "-y", action="store_true", help="确认门自动通过（非交互）")
    parser.add_argument("--param", action="append", default=[], help="覆盖参数 k=v（可多次）")
    parser.add_argument("--workspace", default=None, help="工作记录链根目录（覆盖 params.workspace）")
    try:
        opts = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    data, err = _load_workflow(opts.name)
    if err:
        sys.stderr.write("✗ %s\n" % err)
        return 2

    # 合并参数：声明默认值 + CLI 覆盖
    params = {}
    for k, v in (data.get("params", {}) or {}).items():
        params[k] = v.get("default") if isinstance(v, dict) else v
    for kv in opts.param:
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    if opts.workspace:
        params["workspace"] = opts.workspace

    state_path, state_root = _workflow_state_path(data, params)
    state = _load_state(state_path)
    state.pop("completed_at", None)  # 清掉可能来自 dry-run / 上次失败运行的过期标记
    state["workflow"] = data["workflow"]
    state.setdefault("steps", {})
    state["params"] = params

    steps = data.get("steps", []) or []
    print("▶ 工作流 %s v%s（%d 步）" % (data["workflow"], data.get("version", "?"), len(steps)))
    print("  工作记录链：%s\n" % state_root)

    overall_rc = 0
    for i, step in enumerate(steps, start=1):
        sid = step.get("id") or ("step%d" % i)
        if opts.step and i != opts.step:
            continue
        # 续跑：跳过已完成
        prev = state["steps"].get(sid)
        if opts.resume and prev and prev.get("status") == "done":
            print("✓ 跳过已完成步骤 #%d %s（--resume）" % (i, sid))
            continue
        # 条件 when
        when = step.get("when")
        if when and not _eval_when(when, params):
            print("· 跳过步骤 #%d %s（条件不满足：%s）" % (i, sid, when))
            state["steps"][sid] = {"status": "skipped", "when": when}
            continue

        print("▶ 步骤 #%d %s" % (i, sid))
        uses = step.get("uses")
        executor = step.get("executor")

        # agent 步：无 uses、标 executor=agent——runner 不执行，标记 await_agent 并暂停，
        # 由驱动 Agent 按蓝本对应章节完成后再 `workflow step-done` 回填 + `--resume` 续跑。
        if not uses and executor == "agent":
            if opts.dry_run:
                print("  [dry-run] agent 步（executor=agent，交 Agent 执行）：%s" % step.get("desc", ""))
                continue
            started = datetime.now().isoformat(timespec="seconds")
            state["steps"][sid] = {
                "status": "await_agent",
                "started_at": started,
                "executor": "agent",
                "desc": step.get("desc"),
                "writes": step.get("writes"),
                "checkpoint": step.get("checkpoint"),
            }
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            print("  ⏸ 待 Agent 执行（executor=agent，无 uses）：%s" % step.get("desc", ""))
            print("     → Agent 完成后执行：kit workflow step-done %s %s（再 --resume 续跑）" % (data["workflow"], sid))
            print("  已暂停于 agent 步。")
            return 0

        kind, tokens = _resolve_uses(uses, cmds) if uses else ("shell", "")
        if isinstance(tokens, str):
            tokens = _subst_params(tokens, params)
        else:
            tokens = [_subst_params(t, params) for t in tokens]

        started = datetime.now().isoformat(timespec="seconds")
        rc, note = (0, "no-op") if not uses else _run_step_uses(kind, tokens, cmds, opts.dry_run)
        if rc != 0:
            overall_rc = rc
            state["steps"][sid] = {"status": "failed", "started_at": started, "rc": rc, "note": note}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            print("  ✗ 步骤 #%d %s 失败（rc=%s）：%s" % (i, sid, rc, note))
            break

        # 确认门
        chk = step.get("checkpoint")
        if chk == "confirm" and not opts.yes and not opts.dry_run:
            if not _confirm("  确认继续？（步骤 #%d %s）" % (i, sid)):
                state["steps"][sid] = {"status": "await_confirm", "started_at": started}
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                print("  已暂停于确认门。重跑加 --resume 可从此步继续。")
                return 0

        finished = datetime.now().isoformat(timespec="seconds")
        state["steps"][sid] = {
            "status": "done",
            "started_at": started,
            "finished_at": finished,
            "uses": uses,
            "writes": step.get("writes"),
            "confirm": (chk if chk else None),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  ✓ 完成（%s）" % note)

    if overall_rc == 0 and not opts.dry_run:
        state["completed_at"] = datetime.now().isoformat(timespec="seconds")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n工作流执行完成 ✅  工作记录链：%s" % state_path)
    return overall_rc


HELP_TEXT = """office-kit 动态注册与分发器

用法：
  python kit.py [command] [参数...]

治理命令：
  list | -h | --help   列出全部已注册命令（含入口路径）
  overlaps             列出跨组件功能重叠（capabilities 标签比对）
  doctor               环境与组件自检（venv 解释器 + 组件/入口完整性）
  check [组件...]       检测组件完整性（本地）+ 版本（远程），只读不下载（--offline 仅本地）
  upgrade [组件...]     在线升级到远程最新版（--force 强制同步 / --yes 跳过确认）
  repair [组件...]      在线修复损坏/缺失组件（--yes 跳过确认）
  feedback             生成组件问题反馈文档到 workbench/feedback/
                       （--component <name> --title <t> --detail <d>
                        [--severity low|medium|high|critical] [--repro ...] [--contact ...]）
  run <command> [...]  显式分发（等价于直接 <command> [...]）
  workflow list        列出全部工作流（扫描 workflows/*/workflow.json）
  workflow show <name> 查看单个工作流详情（参数/步骤/触发词）
  workflow run <name> [--resume] [--step N] [--dry-run] [--yes] [--param k=v] [--workspace <dir>]
                      加载工作流契约并按步骤分发（套件命令/组件命令/shell），落工作记录链
                      executor=agent 步会暂停，由 Agent 完成后 step-done 回填再 --resume
  workflow step-done <name> <step_id> [--workspace <dir>]
                      Agent 完成 executor=agent 步骤后回填该步状态为 done（供 --resume 续跑）

分发命令：
  <command> [参数...]   动态分发到对应组件（扫描 components/*/manifest.json 生成映射）

任意分发命令可加 --dry-run 仅打印将执行的命令、不真正运行。
升级/修复会更新 workbench/logs/component-registry.json（上下游对接）与 component-events.log（操作流水）。
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    comps, cmds, caps = _discover_components()
    _ensure_workbench()
    if not argv:
        cmd_list(comps, cmds)
        return 0
    sub = argv[0]
    if sub in ("-h", "--help"):
        print(HELP_TEXT)
        cmd_list(comps, cmds)
        return 0
    if sub == "list":
        cmd_list(comps, cmds)
        return 0
    if sub == "overlaps":
        cmd_overlaps(comps, cmds, caps)
        return 0
    if sub == "doctor":
        cmd_doctor(comps)
        return 0
    if sub == "check":
        return cmd_check(comps, argv[1:])
    if sub == "upgrade":
        return cmd_upgrade(comps, argv[1:])
    if sub == "repair":
        return cmd_repair(comps, argv[1:])
    if sub == "feedback":
        return cmd_feedback(comps, argv[1:])
    if sub == "workflow":
        return cmd_workflow(cmds, argv[1:])
    if sub == "run":
        return cmd_run(cmds, argv[1:])
    # 默认：首个参数为命令名，直接分发
    return cmd_run(cmds, argv)


if __name__ == "__main__":
    sys.exit(main())
