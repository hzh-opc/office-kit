#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 识别稿敏感信息轻量预检（组件反馈 P1-④）。

职责边界（组件反馈 P1-④，避免职责越界）：
- info-extract 只做「检测 + 提示 + 提供脱敏入口」，**不重复实现脱敏**。
- 脱敏动作归 DESEN（desensitization-sop）负责；本模块仅对识别稿文本做**只读扫描**，
  报告命中类型与数量，供交付卡片「敏感信息提示」行使用。

设计：
- 纯标准库、离线、零新依赖（不 import cryptography/rapidocr 等重型依赖）。
- 正则口径与 desensitization-sop 的 desen_rules.py PATTERNS 保持一致，
  覆盖核心结构化 PII：身份证 / 手机号 / 银行卡 / 邮箱 / IP / 车牌 / 护照。
- 全角数字归一后再识别（对齐 desen 的全角→半角归一，避免漏检）。
"""

from __future__ import annotations

import re
from typing import Dict, List

# 词边界（对齐 desen_rules.py：前后非字母数字）
_BOUND_L = r"(?<![0-9A-Za-z])"
_BOUND_R = r"(?![0-9A-Za-z])"

# 核心 PII 正则（与 desensitization-sop/scripts/desen_rules.py 的 PATTERNS 口径一致）
_PATTERNS: Dict[str, re.Pattern] = {
    "id_card": re.compile(_BOUND_L + r"[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]" + _BOUND_R),
    "phone": re.compile(_BOUND_L + r"1[3-9]\d{9}" + _BOUND_R),
    "bank_card": re.compile(_BOUND_L + r"\d{16,19}" + _BOUND_R),
    "email": re.compile(_BOUND_L + r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" + _BOUND_R),
    "ip": re.compile(_BOUND_L + r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)" + _BOUND_R),
    "plate": re.compile(_BOUND_L + r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9]{5,6}" + _BOUND_R),
    "passport": re.compile(_BOUND_L + r"[EGDSH]\d{8}" + _BOUND_R + r"|" + _BOUND_L + r"[a-zA-Z]\d{9}" + _BOUND_R),
}

# 全角数字/字母 → 半角（对齐 desen 的归一，避免全角漏检）
_FULLWIDTH_TABLE = {chr(c): chr(c - 0xFF10 + ord("0")) for c in range(0xFF10, 0xFF1A)}
_FULLWIDTH_TABLE.update({chr(c): chr(c - 0xFF21 + ord("A")) for c in range(0xFF21, 0xFF3B)})
_FULLWIDTH_TABLE.update({chr(c): chr(c - 0xFF41 + ord("a")) for c in range(0xFF41, 0xFF5B)})
_FULLWIDTH_RE = re.compile("|".join(re.escape(k) for k in _FULLWIDTH_TABLE))

# 敏感类型 → 中文标签（供提示展示）
_LABELS = {
    "id_card": "身份证号",
    "phone": "手机号",
    "bank_card": "银行卡号",
    "email": "邮箱",
    "ip": "IP 地址",
    "plate": "车牌号",
    "passport": "护照号",
}


def _normalize_fullwidth(text: str) -> str:
    return _FULLWIDTH_RE.sub(lambda m: _FULLWIDTH_TABLE[m.group(0)], text)


def scan_text(text: str) -> Dict[str, int]:
    """扫描文本，返回 {类型: 命中数量}（未命中类型不出现）。"""
    if not text:
        return {}
    norm = _normalize_fullwidth(text)
    counts: Dict[str, int] = {}
    for kind, pat in _PATTERNS.items():
        # findall 以非零宽正则为单位计数；这里用 finditer 计数更稳（避免重叠影响）
        n = sum(1 for _ in pat.finditer(norm))
        if n:
            counts[kind] = n
    return counts


def scan_summary(text: str) -> Dict[str, object]:
    """扫描并产出摘要：{total, kinds: [{kind, label, count}]}，供卡片展示。"""
    counts = scan_text(text)
    kinds = [
        {"kind": k, "label": _LABELS.get(k, k), "count": v}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return {
        "total": sum(counts.values()),
        "kinds": kinds,
    }


__all__ = ["scan_text", "scan_summary"]
