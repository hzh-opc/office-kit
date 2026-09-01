#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 协同能力自检（D9 / 流程规范 §6）。

复用 summarize 的 skill_bridge 思路：按 capabilities 关键词泛匹配已安装技能的
SKILL.md（name/description/tags），判定各协同能力是否可用；命中即调、缺失即降级。
当前关注三类协同：
- desensitization（DESEN，上云脱敏闸门，§4.4）
- document_text（原生文本层抽取，分工 D10）
- browser（在线视频捕获，阶段五）

纯标准库、离线、缺失不报错。
"""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

# 协同能力清单（按技能目录名匹配，关键词精炼，避免全文扫描误判）
COOP_CAPS = {
    "desensitization": ["desensitiz", "脱敏"],
    "document_text": ["document", "文档"],
    "browser": ["browser", "浏览器"],
}

SKILL_ROOTS = [
    os.path.expanduser("~/.workbuddy/skills"),
    os.path.expanduser("~/.claude/skills"),
    os.path.expanduser("~/.codex/skills"),
    os.path.expanduser("~/.openclaw/skills"),
]


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
    import json

    print(json.dumps(self_check(), ensure_ascii=False, indent=2))


__all__ = ["COOP_CAPS", "self_check", "has_desensitization"]
