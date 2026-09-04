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


def desensitization_skill_name() -> Optional[str]:
    """返回已检出的脱敏技能名（无则 None）。"""
    return self_check(["desensitization"])["desensitization"]


# ---------------------------------------------------------------------------
# 隐性外发确认闸口（2026-09-04 政策细化：扫描→提示→确认→否则阻断）
# ---------------------------------------------------------------------------
EXTERNAL_CONFIRM_ENV = "OFFICE_KIT_EXTERNAL_CONFIRM"

_PII_LABEL = {
    "id_card": "身份证号", "phone": "手机号", "bank_card": "银行卡号",
    "email": "邮箱", "ip": "IP 地址", "plate": "车牌号", "passport": "护照号",
}


def _external_pii_hits(texts):
    """用本组件自带 pii_scan 做本地只读预检，返回 {类别: 数量}（无则空）。"""
    stats = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from modules.pii_scan import scan_text
        for t in texts or []:
            if not t:
                continue
            r = scan_text(t)
            for k, v in (r or {}).items():
                stats[k] = stats.get(k, 0) + v
    except Exception:
        pass
    return stats


def request_external_confirmation(purpose, texts=None, paths=None, pii_hits=None):
    """隐性外发确认闸口（组件内部，confirm-or-block，安全默认=阻断）。

    在组件把内容送出本机（如识别稿外发、上云）前调用。返回 True=放行 / False=阻断。

    确认逻辑：
    - OFFICE_KIT_EXTERNAL_CONFIRM=allow → 放行（agent 已在对话中代用户确认）。
    - =deny → 阻断（显式拒绝）。
    - 未设 且 sys.stdin 是 TTY → 交互 input() 提示 y/N。
    - 未设 且 非 TTY（agent / 管道调用）→ 安全默认阻断，打印提示，等 agent 代确认。

    注：PII 检测仅用于提示增强，不影响阻断决策——任何隐性外发都需用户确认。
    """
    import sys as _sys
    hits = dict(pii_hits or {})
    if not hits:
        hits = _external_pii_hits(texts)
        if not hits and paths:
            try:
                for p in paths:
                    if p and os.path.isfile(p):
                        with open(p, "r", encoding="utf-8", errors="replace") as f:
                            t = _external_pii_hits([f.read()])
                            for k, v in t.items():
                                hits[k] = hits.get(k, 0) + v
            except Exception:
                pass
    _sys.stderr.write("\n⚠ 隐性外发确认：%s\n" % purpose)
    if hits:
        kinds = "、".join("%s×%d" % (_PII_LABEL.get(k, k), v) for k, v in sorted(hits.items()))
        _sys.stderr.write("  本地预检检出疑似敏感信息：%s（建议先 `desen run` 脱敏）\n" % kinds)
    else:
        _sys.stderr.write("  本地预检未发现已知 PII（仍请确认内容不含敏感信息）。\n")
    decision = os.environ.get(EXTERNAL_CONFIRM_ENV, "").strip().lower()
    if decision == "allow":
        _sys.stderr.write("  → 已确认（OFFICE_KIT_EXTERNAL_CONFIRM=allow），放行。\n")
        return True
    if decision == "deny":
        _sys.stderr.write("  → 已显式拒绝，外发阻断。\n")
        return False
    if _sys.stdin.isatty():
        try:
            ans = input("  是否确认执行此外发？[y/N] ").strip().lower()
        except Exception:
            return False
        if ans in ("y", "yes", "是"):
            return True
        _sys.stderr.write("  → 用户未确认，外发阻断。\n")
        return False
    _sys.stderr.write("  → 非交互环境未获确认，按安全默认阻断（已与用户确认请置 "
                      "OFFICE_KIT_EXTERNAL_CONFIRM=allow 后重试）。\n")
    return False


def enforce_desen_scan_before_external(paths):
    """外发前确认闸口（2026-09-04 政策细化：提示+确认，否则阻断）。

    委托 request_external_confirmation 实现「扫描→提示→确认→否则阻断」。
    返回 True=放行 / False=阻断（与套件层对隐性外发的口径一致：不静默放行）。
    """
    return request_external_confirmation(
        purpose="识别稿外发 / 上云（paths=%s）" % (paths or []),
        paths=paths)


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))


__all__ = ["COOP_CAPS", "self_check", "has_desensitization",
           "desensitization_skill_name", "enforce_desen_scan_before_external",
           "request_external_confirmation"]
