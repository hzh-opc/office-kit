#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
consistency_check.py — 摘要与原文一致性自检（源文忠实守护，纯标准库、零依赖）

设计意图：自动化守护「源文忠实」铁律（D8）。一条摘要必须是原文的可追溯投影，
不得引入原文之外的外部信息 / 幻觉。本脚本对摘要逐句判定：能否在原文中找到
支撑句（基于 CJK 二元组 + 拉丁词 Jaccard 句级相似度）。

- 可追溯：该摘要句与原文某句相似度 >= 阈值（默认 0.12，可调），视为来自原文。
- 不可追溯：所有原文句相似度均 < 阈值，标为「疑似外部引入 / 幻觉」，需人工复核。

输出：可追溯 / 不可追溯计数与清单，并给整体 verdict。
exit code：0=全部可追溯（一致）；非 0=存在不可追溯句（可接入 CI / 自动门禁）。

用法：
  python3 consistency_check.py --original 原文.txt --summary 摘要.txt \
      [--format md|json|txt] [--out PATH] [--threshold F]

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
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_text_maybe_json(path):
    """读取摘要文本；若文件是 JSON（如 summarize --format json 的输出）则提取 summary 字段。"""
    raw = read_text(path)
    s = raw.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and "summary" in obj and obj["summary"]:
                return obj["summary"]
        except Exception:
            pass
    return raw


# 摘要文本中可能混入的「技能附加物」，非原文内容，自检前须剥离，避免误判为不可追溯
_CITE_RE = re.compile(r"（见原文第\d+段·句\d+）|（见第\d+篇·第\d+段·句\d+）")
_KEYWORD_FOOTER_RE = re.compile(r"^\s*关键词[：:].*$")
_HEADER_RE = re.compile(r"^#+\s*(摘要|关键词)\s*$")


def clean_summary(text):
    """剥离 --cite 溯源标注与「关键词」脚注 / 摘要 markdown 标题，仅保留摘要正文句。"""
    out_lines = []
    for ln in text.splitlines():
        if _KEYWORD_FOOTER_RE.match(ln) or _HEADER_RE.match(ln.strip()):
            continue
        out_lines.append(_CITE_RE.sub("", ln))
    return "\n".join(out_lines)


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
    """取 CJK 二元组 + 拉丁词作为相似度特征（与 diff_summary.py 同约定）。"""
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


def consistency_check(original_text, summary_text, threshold=0.12):
    """返回 {traceable, untraceable, counts, verdict, threshold}。"""
    orig_sents = split_sentences(original_text)
    summ_sents = split_sentences(summary_text)
    orig_tok = [tokens(s) for s in orig_sents]

    traceable, untraceable = [], []

    for i, s in enumerate(summ_sents):
        ts = tokens(s)
        best, best_j = 0.0, -1
        if ts:  # 空句直接视为可追溯（无信息可引入）
            for j, ot in enumerate(orig_tok):
                sc = sim(s, orig_sents[j])
                if sc > best:
                    best, best_j = sc, j
        if best >= threshold:
            traceable.append({
                "text": s, "idx": i,
                "best_match_idx": best_j,
                "best_match_score": round(best, 3),
            })
        else:
            untraceable.append({
                "text": s, "idx": i,
                "best_match_idx": best_j,
                "best_match_score": round(best, 3),
            })

    n_total = len(summ_sents)
    n_unt = len(untraceable)
    if n_total == 0:
        verdict = "empty"
    elif n_unt == 0:
        verdict = "consistent"
    else:
        verdict = "inconsistent"

    return {
        "traceable": traceable,
        "untraceable": untraceable,
        "counts": {
            "summary_sentences": n_total,
            "traceable": len(traceable),
            "untraceable": n_unt,
            "traceable_ratio": round(len(traceable) / n_total, 3) if n_total else 0.0,
        },
        "verdict": verdict,
        "threshold": threshold,
    }


def main():
    ap = argparse.ArgumentParser(description="摘要与原文一致性自检（源文忠实守护 / 零依赖）")
    ap.add_argument("--original", required=True, help="原文文件路径（或 - 读 stdin）")
    ap.add_argument("--summary", required=True, help="摘要文件路径（或 - 读 stdin）")
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--threshold", type=float, default=0.12,
                    help="可追溯判定阈值（默认 0.12；越高越严格，越易判为不可追溯）")
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    orig = read_text(args.original)
    summ = clean_summary(read_text_maybe_json(args.summary))
    r = consistency_check(orig, summ, threshold=args.threshold)

    if args.format == "json":
        out = json.dumps(r, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        lines = []
        c = r["counts"]
        lines.append("一致性自检：verdict=%s（阈值 %.2f）" % (r["verdict"], r["threshold"]))
        lines.append("摘要句数=%d，可追溯=%d，不可追溯=%d，可追溯率=%.2f" % (
            c["summary_sentences"], c["traceable"], c["untraceable"], c["traceable_ratio"]))
        if r["untraceable"]:
            lines.append("")
            lines.append("⚠ 不可追溯（疑似外部引入 / 幻觉）：")
            for x in r["untraceable"]:
                lines.append("  ? [%d] (best=%.2f) %s" % (x["idx"], x["best_match_score"], x["text"]))
        if r["traceable"]:
            lines.append("")
            lines.append("✔ 可追溯：")
            for x in r["traceable"]:
                lines.append("  . [%d] (best=%.2f) %s" % (x["idx"], x["best_match_score"], x["text"]))
        out = "\n".join(lines)
    else:  # md
        c = r["counts"]
        icon = "✅" if r["verdict"] == "consistent" else ("⚠️" if r["verdict"] == "inconsistent" else "ℹ️")
        lines = ["# 摘要一致性自检（源文忠实守护）", ""]
        lines.append("%s **verdict: %s**（阈值 %.2f）" % (icon, r["verdict"], r["threshold"]))
        lines.append("")
        lines.append("> 摘要句数 **%d**，可追溯 **%d**，不可追溯 **%d**，可追溯率 **%.2f**。" % (
            c["summary_sentences"], c["traceable"], c["untraceable"], c["traceable_ratio"]))
        lines.append("")
        if r["untraceable"]:
            lines.append("## ⚠️ 不可追溯句（疑似外部引入 / 幻觉，需人工复核）")
            for x in r["untraceable"]:
                lines.append("- 句 %d（与原文最高相似度 %.2f）：%s" % (
                    x["idx"], x["best_match_score"], x["text"]))
            lines.append("")
        if r["traceable"]:
            lines.append("## ✔️ 可追溯句")
            for x in r["traceable"]:
                lines.append("- 句 %d（溯源原文句 %s，相似度 %.2f）：%s" % (
                    x["idx"],
                    "无" if x["best_match_idx"] < 0 else str(x["best_match_idx"]),
                    x["best_match_score"], x["text"]))
            lines.append("")
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")

    # 门禁：存在不可追溯句 → 非 0 退出（供 CI / 自动守护）
    if r["verdict"] == "inconsistent":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
