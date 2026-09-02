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


def cmd_run(commands, argv):
    target = argv[0]
    rest = argv[1:]
    dry = False
    if "--dry-run" in rest:
        dry = True
        rest = [a for a in rest if a != "--dry-run"]
    rec = commands.get(target)
    if not rec:
        sys.stderr.write("✗ 未知命令：%s\n已知命令：%s\n" % (target, ", ".join(sorted(set(r['name'] for r in commands.values()))) or "（无）"))
        return 2
    venv_py = _venv_python()
    entry = KIT_DIR / "components" / rec["component"] / rec["entry"]
    if not entry.is_file():
        sys.stderr.write("✗ 入口不存在：%s\n" % entry)
        return 2
    if dry:
        print("[dry-run] %s %s %s" % (venv_py, entry, " ".join(rest)))
        return 0
    if not venv_py.is_file():
        sys.stderr.write("✗ 虚拟环境缺失：%s\n→ 请先运行 ./bootstrap.sh 初始化。\n" % venv_py)
        return 3
    # 集成层统一 venv 约定（2026-09-01，office-kit 设计评审反馈）：
    # 显式向组件进程注入 venv 真相源，避免组件自行 re-exec 到错误路径。
    #   UV_PROJECT_ENVIRONMENT → kit 根 .venv（doc-layout / info-extract 优先读取）
    #   OFFICE_KIT_ROOT         → kit 根目录（doc-layout 兜底优先复用 kit/.venv）
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_py.parent)
    env["OFFICE_KIT_ROOT"] = str(KIT_DIR)
    try:
        proc = subprocess.run([str(venv_py), str(entry)] + rest, env=env)
        return proc.returncode
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("✗ 调用失败：%s\n" % exc)
        return 3


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
    if sub == "run":
        return cmd_run(cmds, argv[1:])
    # 默认：首个参数为命令名，直接分发
    return cmd_run(cmds, argv)


if __name__ == "__main__":
    sys.exit(main())
