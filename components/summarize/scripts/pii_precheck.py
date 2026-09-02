#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pii_precheck.py — 上云前本地 PII（个人可识别信息）预检（纯标准库、零依赖）

设计意图：在把任何文本送云端模型前，先在本地用正则 + 词典模式扫描其中可能
的 PII，输出命中类别统计、上下文片段与脱敏预览（mask），帮助用户/智能体在
脱敏协同缺失或仅送 brief 时也能快速发现风险点。脚本**不修改、不覆盖**原文件。

检测类别（默认全开，可用 --categories 指定子集）：
  - phone      手机号（中国大陆 1[3-9] 开头 11 位）
  - email      邮箱
  - idcard     身份证号（18 位 / 15 位）
  - bankcard   银行卡号（16~19 位连续数字）
  - url        网址（http/https）
  - money      金额（¥ / 人民币 + 数字）
  - address    疑似地址（路/街/巷/道+门牌号、或省/市+区/县行政链，已收紧防误报）
  - name       疑似姓名（X 先生/女士/同志 前的 2~3 字中文，启发式、可能误报）

输出：命中统计 + 每条样本（类别、原文片段、行号、脱敏预览）。exit code：
  0=未发现 PII；非 0=发现 PII（可接入 CI / 上云前自动门禁，建议配合脱敏协同）。

用法：
  python3 pii_precheck.py <输入.txt> [-] [--format md|json|txt] [--out PATH] \
      [--categories phone,email,idcard] [--mask] [--no-context]

本脚本**不依赖任何外部技能**；纯标准库实现。
"""

import sys
import os
import re
import json
import argparse

# ---- 各类别正则（保守、零依赖）----
PATTERNS = {
    "phone": re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    "idcard": re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)"),
    "bankcard": re.compile(r"(?<!\d)(\d{16,19})(?!\d)"),
    "url": re.compile(r"https?://[^\s，。；、）)]+"),
    "money": re.compile(r"([¥￥]\s?\d+(?:\.\d+)?\s?(?:元|万|亿)?|人民币\s?\d+(?:\.\d+)?\s?(?:元|万|亿)?)"),
    "address": re.compile(
        r"(?:"
        r"[\u4e00-\u9fff]{2,10}(?:路|街|巷|道|大道)\s?\d{1,6}(?:号|栋|单元|室|楼)?"  # 路/街/巷/道 + 门牌号（强信号）
        r"|"
        r"[\u4e00-\u9fff]{2,6}(?:省|自治区)[\u4e00-\u9fff]{2,8}(?:市|区|县|镇|街道)"  # XX省/自治区 + XX市/区/县/镇/街道
        r"|"
        r"[\u4e00-\u9fff]{2,6}市[\u4e00-\u9fff]{2,6}(?:区|县)"  # XX市 + XX区/县（区县名≥2字，防"市场区域"误报）
        r")"
    ),
    "name": re.compile(r"([\u4e00-\u9fff]{2,3})(?=先生|女士|同志|老师)"),
}
CATEGORY_LABEL = {
    "phone": "手机号",
    "email": "邮箱",
    "idcard": "身份证号",
    "bankcard": "银行卡号",
    "url": "网址",
    "money": "金额",
    "address": "疑似地址",
    "name": "疑似姓名",
}
RISK_LEVEL = {
    "phone": "high",
    "email": "high",
    "idcard": "high",
    "bankcard": "high",
    "url": "medium",
    "money": "medium",
    "address": "medium",
    "name": "low",
}


def read_text(path):
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def mask_value(cat, value):
    """按类别生成脱敏预览（保留首尾少量字符，中间打码）。"""
    if cat in ("phone", "bankcard", "idcard"):
        if len(value) >= 6:
            return value[:3] + "*" * (len(value) - 6) + value[-3:]
        return "*" * len(value)
    if cat == "email":
        if "@" in value:
            u, d = value.split("@", 1)
            show = u[:1] + "*" * (len(u) - 1) if len(u) > 1 else u
            return show + "@" + d
        return "*" * len(value)
    if cat == "url":
        return value[:12] + "…(已省略)"
    # money / address / name：仅显示首字 + 打码
    if len(value) <= 1:
        return "*"
    return value[0] + "*" * (len(value) - 1)


def precheck(text, categories=None, with_context=True):
    cats = categories or list(PATTERNS.keys())
    findings = []
    lines = text.splitlines()
    for li, line in enumerate(lines, start=1):
        for cat in cats:
            pat = PATTERNS.get(cat)
            if not pat:
                continue
            for m in pat.finditer(line):
                val = m.group(0)
                span = (m.start(), m.end())
                findings.append({
                    "category": cat,
                    "label": CATEGORY_LABEL.get(cat, cat),
                    "risk": RISK_LEVEL.get(cat, "low"),
                    "value": val,
                    "masked": mask_value(cat, val),
                    "line": li,
                    "span": list(span),
                    "context": line.strip() if with_context else "",
                })
    # 统计
    stat = {}
    for f in findings:
        stat[f["category"]] = stat.get(f["category"], 0) + 1
    return {"findings": findings, "stats": stat, "total": len(findings)}


def main():
    ap = argparse.ArgumentParser(description="上云前本地 PII 预检（零依赖 / 不修改原文件）")
    ap.add_argument("input", help="待检查文本文件（或 - 读 stdin）")
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--categories", default=None,
                    help="仅检查指定类别，逗号分隔（phone,email,idcard,bankcard,url,money,address,name）")
    ap.add_argument("--no-context", action="store_true", help="不输出上下文行")
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    cats = None
    if args.categories:
        cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    text = read_text(args.input)
    r = precheck(text, categories=cats, with_context=not args.no_context)

    if args.format == "json":
        out = json.dumps(r, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        lines = ["PII 预检：共发现 %d 处" % r["total"]]
        if r["stats"]:
            lines.append("统计：" + ", ".join("%s=%d" % (CATEGORY_LABEL.get(k, k), v)
                                              for k, v in sorted(r["stats"].items())))
        for f in r["findings"]:
            lines.append("[%s/%s] 行%d: %s -> %s" % (
                f["label"], f["risk"], f["line"], f["value"], f["masked"]))
            if f["context"]:
                lines.append("    上下文: " + f["context"])
        out = "\n".join(lines)
    else:  # md
        lines = ["# PII 预检报告（本地 / 零依赖）", ""]
        lines.append("> 共发现 **%d** 处疑似 PII。" % r["total"])
        if r["stats"]:
            lines.append("")
            lines.append("## 分类统计")
            for k, v in sorted(r["stats"].items()):
                lines.append("- %s（%s）：**%d** 处" % (CATEGORY_LABEL.get(k, k), k, v))
        if r["findings"]:
            lines.append("")
            lines.append("## 命中明细")
            lines.append("")
            lines.append("| 类别 | 风险 | 行号 | 原文 | 脱敏预览 | 上下文 |")
            lines.append("|---|---|---|---|---|---|")
            for f in r["findings"]:
                ctx = f["context"].replace("|", "\\|") if f["context"] else ""
                lines.append("| %s | %s | %d | `%s` | `%s` | %s |" % (
                    f["label"], f["risk"], f["line"], f["value"], f["masked"], ctx))
        lines.append("")
        lines.append("> 本预检为启发式正则扫描，仅供风险发现参考；正式上云前仍须按脱敏协同做人工复核。")
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")

    # 门禁：发现 PII → 非 0 退出（供上云前自动门禁）
    if r["total"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
