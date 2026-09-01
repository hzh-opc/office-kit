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
  python kit.py feedback --component <name> --title <t> --detail <d> [--severity ...] [--repro ...]
  python kit.py <command> [组件参数...]            # 动态分发
  python kit.py run <command> [组件参数...]         # 同上（显式）
  python kit.py run <command> --dry-run [组件参数...]  # 仅打印将执行的命令，不执行
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


KIT_DIR = Path(__file__).resolve().parent


def _venv_python() -> Path:
    """返回 kit 虚拟环境解释器路径（跨平台）。"""
    if os.name == "nt":
        return KIT_DIR / ".venv" / "Scripts" / "python.exe"
    return KIT_DIR / ".venv" / "bin" / "python"


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


def cmd_doctor(components, commands):
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
        if comp_path.is_dir():
            print("  ✓ 组件目录：%s" % name)
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
    print("自检结果：%s" % ("通过 ✅" if ok else "存在问题 ❌"))


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
    # 解析 feedback 参数
    opts = {"component": "", "title": "", "detail": "", "severity": "medium",
            "repro": "", "contact": ""}
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--component", "--title", "--detail", "--severity", "--repro", "--contact"):
            key = a.lstrip("-")
            if i + 1 < len(args):
                opts[key] = args[i + 1]
                i += 2
                continue
        i += 1
    comp = opts["component"]
    if comp and comp not in components:
        sys.stderr.write("⚠ 未知组件：%s（已知：%s）\n" % (comp, ", ".join(sorted(components)) or "（无）"))
        return 2
    if not opts["title"]:
        sys.stderr.write("⚠ --title 必填（一句话描述问题）\n")
        return 2
    fb_dir = KIT_DIR / "workbench" / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(opts["title"])
    fname = "%s-%s-%s.md" % (stamp, comp or "kit", slug)
    env_lines = []
    for k, v in (("kit_dir", str(KIT_DIR)), ("venv_python", str(_venv_python())),
                 ("python", sys.version.split()[0]), ("os", os.name)):
        env_lines.append("- %s: %s" % (k, v))
    body = [
        "# 组件反馈 · %s" % opts["title"],
        "",
        "> 由 office-kit 自动生成，用于反馈给组件开发者（规划文档 L13）。",
        "",
        "## 元信息",
        "- component: %s" % (comp or "（工具包本身）"),
        "- severity: %s" % opts["severity"],
        "- created: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "- contact: %s" % (opts["contact"] or "（未提供）"),
        "",
        "## 问题描述",
        opts["detail"] or "（待补充）",
        "",
        "## 复现步骤",
        opts["repro"] or "（待补充）",
        "",
        "## 环境",
        "\n".join(env_lines),
        "",
    ]
    (fb_dir / fname).write_text("\n".join(body), encoding="utf-8")
    print("✓ 反馈文档已生成：%s" % (fb_dir / fname))
    print("  组件：%s　标题：%s" % (comp or "（工具包本身）", opts["title"]))
    return 0


def cmd_run(commands, argv):
    if not argv:
        cmd_list(_discover_components()[0], commands)
        return 0
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
    try:
        proc = subprocess.run([str(venv_py), str(entry)] + rest)
        return proc.returncode
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("✗ 调用失败：%s\n" % exc)
        return 3


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "list"):
        comps, cmds, caps = _discover_components()
        if argv and argv[0] == "list":
            cmd_list(comps, cmds)
        else:
            cmd_list(comps, cmds)
        return 0
    sub = argv[0]
    comps, cmds, caps = _discover_components()
    if sub == "overlaps":
        cmd_overlaps(comps, cmds, caps)
        return 0
    if sub == "doctor":
        cmd_doctor(comps, cmds)
        return 0
    if sub == "feedback":
        return cmd_feedback(comps, argv[1:])
    if sub == "run":
        return cmd_run(cmds, argv[1:])
    # 默认：首个参数为命令名，直接分发
    return cmd_run(cmds, argv)


if __name__ == "__main__":
    sys.exit(main())
