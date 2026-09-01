#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_summary.py — 两份同主题文档的差异 / 变更摘要（本地、零依赖）

对「旧版 A」与「新版 B」做句级相似度比对，识别：
  - 新增：B 中相对 A 无近义句者
  - 删除：A 中相对 B 无近义句者
  - 修改：A↔B 间存在中等相似句（旧 → 新）
输出变更摘要 / changelog。全程本地、不联网、零第三方依赖。

用法：
  python3 diff_summary.py A.txt B.txt [--format md|json|txt] [--out PATH] [--threshold F]

本脚本**不依赖任何外部技能**；纯标准库实现。
"""

import sys
import os
import re
import json
import argparse

CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")
LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+\-./]*")


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def split_sentences(text):
    """按中英文标点切分句子，保留非空、去首尾空白。"""
    raw = re.split(r"(?<=[。！？!?；;…])|(?<=[\n\r])", text)
    out = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        s = re.sub(r"\s+", " ", s)
        out.append(s)
    return out


def tokens(s):
    """取 CJK 二元组 + 拉丁词作为相似度特征（零依赖）。"""
    toks = set()
    for run in CJK_RUN.findall(s):
        for i in range(len(run) - 1):
            toks.add(run[i:i + 2])
    for w in LATIN_WORD.findall(s):
        toks.add(w.lower())
    return toks


def sim(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def diff_summary(a_text, b_text, threshold=0.3, modify_hi=0.85):
    """返回 {added, removed, modified, counts}。"""
    sa = split_sentences(a_text)
    sb = split_sentences(b_text)
    added, removed, modified = [], [], []
    used_b = set()

    for i, x in enumerate(sa):
        best, best_j = 0.0, -1
        for j, y in enumerate(sb):
            s = sim(x, y)
            if s > best:
                best, best_j = s, j
        if best >= modify_hi:
            used_b.add(best_j)
        elif best >= threshold:
            used_b.add(best_j)
            modified.append({"old": x, "new": sb[best_j],
                             "score": round(best, 3), "old_idx": i, "new_idx": best_j})
        else:
            removed.append({"text": x, "idx": i})

    for j, y in enumerate(sb):
        if j in used_b:
            continue
        best = max((sim(y, x) for x in sa), default=0.0)
        if best < threshold:
            added.append({"text": y, "idx": j})

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
        },
    }


def main():
    ap = argparse.ArgumentParser(description="两份文档的差异 / 变更摘要（本地 / 零依赖）")
    ap.add_argument("a", help="旧版文档路径")
    ap.add_argument("b", help="新版文档路径")
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--threshold", type=float, default=0.3,
                    help="新增 / 删除判定阈值（默认 0.3；修改区间 [threshold, 0.85)）")
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    ta = read_text(args.a)
    tb = read_text(args.b)
    r = diff_summary(ta, tb, threshold=args.threshold)

    if args.format == "json":
        out = json.dumps(r, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        lines = []
        lines.append("新增 %d 句：" % r["counts"]["added"])
        for x in r["added"]:
            lines.append("  + " + x["text"])
        lines.append("删除 %d 句：" % r["counts"]["removed"])
        for x in r["removed"]:
            lines.append("  - " + x["text"])
        lines.append("修改 %d 处：" % r["counts"]["modified"])
        for x in r["modified"]:
            lines.append("  ~ 旧：%s" % x["old"])
            lines.append("    新：%s" % x["new"])
        out = "\n".join(lines)
    else:  # md
        lines = ["# 差异摘要（变更日志）", ""]
        lines.append("> 相对旧版：新增 **%d** 句、删除 **%d** 句、修改 **%d** 处。" % (
            r["counts"]["added"], r["counts"]["removed"], r["counts"]["modified"]))
        lines.append("")
        if r["added"]:
            lines.append("## ➕ 新增")
            for x in r["added"]:
                lines.append("- %s" % x["text"])
            lines.append("")
        if r["removed"]:
            lines.append("## ➖ 删除")
            for x in r["removed"]:
                lines.append("- %s" % x["text"])
            lines.append("")
        if r["modified"]:
            lines.append("## ✏️ 修改")
            for x in r["modified"]:
                lines.append("- 旧：%s" % x["old"])
                lines.append("  新：%s" % x["new"])
            lines.append("")
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
