#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 协同能力自检（D9 / 流程规范 §6）。

复用 summarize 的 skill_bridge 思路：按协同能力关键词泛匹配已安装技能目录名，
判定各协同能力是否可用；命中即调、缺失即降级。
当前关注两类协同：
- desensitization（DESEN，上云脱敏闸门，§4.4）
- browser（在线视频捕获，阶段五）

（document_text 原生文本层抽取分工已由 DESEN 承接——office-kit 内 desensitization-sop
 声明 pdf-text-extract/office-text-extract 能力，且 OCR 模块对文本层页已有硬编码建议，
 不再单独检测。见开发参考 D10 / 组件反馈 P2-①。）

协同能力清单数据驱动：优先读 assets/capabilities.json 的 coop_caps 字段，
缺失/异常时回退内置默认（与文件保持一致）。纯标准库、离线、缺失不报错。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

# 内置默认协同能力清单（按技能目录名匹配，关键词精炼，避免全文扫描误判；
# 与 assets/capabilities.json 的 coop_caps 保持一致，文件缺失时回退）。
DEFAULT_COOP_CAPS = {
    "desensitization": ["desensitiz", "脱敏"],
    "browser": ["browser", "浏览器"],
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CAPS_JSON = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "assets", "capabilities.json"))


def _load_coop_caps() -> Dict[str, List[str]]:
    """数据驱动：读 assets/capabilities.json 的 coop_caps；失败回退内置默认。"""
    try:
        with open(_CAPS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        coop = data.get("coop_caps")
        if isinstance(coop, dict) and coop:
            out: Dict[str, List[str]] = {}
            for cap, kws in coop.items():
                if isinstance(kws, list) and kws:
                    out[str(cap)] = [str(k) for k in kws]
            if out:
                return out
    except Exception:
        pass
    return dict(DEFAULT_COOP_CAPS)


COOP_CAPS = _load_coop_caps()


def _skill_roots() -> List[str]:
    """技能根目录：4 个 Agent skills 目录 + $OFFICE_KIT_ROOT/components（若存在）。

    纳入套件组件目录，使套件内（S1/S2）部署的 desensitization-sop 等组件
    也能被检出（此前 S1/S2 下 desen 完全检不到，组件反馈 P1-①）。
    """
    roots = [
        os.path.expanduser("~/.workbuddy/skills"),
        os.path.expanduser("~/.claude/skills"),
        os.path.expanduser("~/.codex/skills"),
        os.path.expanduser("~/.openclaw/skills"),
    ]
    kit_root = os.environ.get("OFFICE_KIT_ROOT")
    if kit_root:
        roots.append(os.path.join(os.path.expanduser(kit_root), "components"))
    return roots


SKILL_ROOTS = _skill_roots()


def _match_capability(keywords) -> Optional[str]:
    """按技能目录名（技能名）匹配能力关键词，返回首个匹配技能名（无则 None）。

    只匹配目录名、不扫描 SKILL.md 全文——避免全文关键词过宽导致的误判
    （如 a-stock-data 的 SKILL.md 含「文档/网页」被误判为 document_text/browser，
    browser-skill 含「敏感」被误判为 desensitization）。
    """
    for root in SKILL_ROOTS:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            skill_dir = os.path.join(root, name)
            if not os.path.isdir(skill_dir):
                continue
            nl = name.lower()
            for kw in keywords:
                if kw.lower() in nl:
                    return name
    return None


def self_check(caps: Optional[list] = None) -> Dict[str, Optional[str]]:
    """返回 {能力: 已安装技能名或 None}。"""
    caps = caps or list(COOP_CAPS.keys())
    return {cap: _match_capability(COOP_CAPS[cap]) for cap in caps}


def has_desensitization() -> bool:
    return self_check(["desensitization"])["desensitization"] is not None


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))


__all__ = ["COOP_CAPS", "self_check", "has_desensitization"]
