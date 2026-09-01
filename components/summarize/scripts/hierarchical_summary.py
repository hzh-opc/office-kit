#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hierarchical_summary.py — 层级摘要（本地、零依赖，复用 summarize.py 引擎）

把一份文本生成多层嵌套摘要，从「总览」到「细节」逐级展开，便于结构化阅读与
一键导入脑图 / 大纲工具：

  - L1 概览：一句话核心结论（来自 summarize 的 --tldr）
  - L2 要点：默认长度的核心摘要（关键要点）
  - L3 细节：更多候选支撑句（带 --cite 溯源标注），逐条支撑 L2 要点

用法：
  python3 hierarchical_summary.py <输入.txt> [-] [--l1] [--l2 N] [--l3 N] \
      [--cite] [--keywords K] [--format md|json|txt] [--out PATH]

参数：
  --l1            若给定，L1 单独成行输出（默认 L1 始终输出，此开关仅历史兼容）
  --l2 N          要点句数（默认 3）
  --l3 N          细节支撑句数（默认 8；0 表示不输出 L3）
  --cite          细节句附原文溯源标注（见原文第P段·句S）
  --keywords K    关键词数量（默认 8）

本脚本通过 `from summarize import summarize` 复用同目录引擎，**不依赖任何外部技能**。
"""

import sys
import os
import json
import argparse

# 同目录复用核心引擎（零耦合：仍只 import 自家 summarize 模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from summarize import summarize, read_text  # noqa: E402


def hierarchical(text, l2=3, l3=8, keywords_k=8, cite=False, lang="auto"):
    """返回 {l1, l2, l3, keywords}。"""
    base = dict(keywords_k=keywords_k, lang=lang, do_eval=False, brief=False, multi=False)

    # L1：一句话核心
    r1 = summarize([text], **base)
    l1 = r1.get("tldr", "") or r1.get("summary", "")

    # L2：核心要点
    r2 = summarize([text], length=l2, cite=False, **base)
    l2_sents = [c["text"] for c in r2.get("chosen_sentences", [])]

    # L3：细节支撑（更多候选句 + cite）
    l3_sents = []
    if l3 > 0:
        r3 = summarize([text], length=l3, cite=cite, **base)
        l3_sents = [c["text"] for c in r3.get("chosen_sentences", [])]
        # 去重：避免与 L2 完全重合（L3 作为 L2 的细节补充）
        seen = set(l2_sents)
        l3_sents = [s for s in l3_sents if s not in seen][:l3]

    return {
        "l1": l1,
        "l2": l2_sents,
        "l3": l3_sents,
        "keywords": r2.get("keywords", []),
    }


def main():
    ap = argparse.ArgumentParser(description="层级摘要（L1 概览 / L2 要点 / L3 细节，零依赖）")
    ap.add_argument("input", help="文本文件（或 - 读 stdin）")
    ap.add_argument("--l1", action="store_true", help="（兼容开关）L1 始终输出，此开关无额外副作用")
    ap.add_argument("--l2", type=int, default=3, help="L2 要点句数（默认 3）")
    ap.add_argument("--l3", type=int, default=8, help="L3 细节支撑句数（默认 8；0=不输出 L3）")
    ap.add_argument("--cite", action="store_true", help="L3 细节句附原文溯源标注")
    ap.add_argument("--keywords", type=int, default=8, help="关键词数量（默认 8）")
    ap.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    text = read_text(args.input)
    if not text.strip():
        sys.stderr.write("错误：输入为空。\n")
        sys.exit(2)

    r = hierarchical(text, l2=args.l2, l3=args.l3, keywords_k=args.keywords,
                     cite=args.cite, lang=args.lang)

    if args.format == "json":
        out = json.dumps(r, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        lines = ["【L1 概览】", r["l1"], "",
                 "【L2 要点】"]
        for i, s in enumerate(r["l2"], 1):
            lines.append("%d. %s" % (i, s))
        if r["l3"]:
            lines.append("", "【L3 细节】")
            for i, s in enumerate(r["l3"], 1):
                lines.append("%d. %s" % (i, s))
        lines.append("", "【关键词】" + "、".join(r["keywords"]))
        out = "\n".join(lines)
    else:  # md
        lines = ["# 层级摘要", ""]
        lines.append("## L1 · 概览（一句话核心）")
        lines.append("> " + r["l1"])
        lines.append("")
        lines.append("## L2 · 要点")
        for s in r["l2"]:
            lines.append("- " + s)
        if r["l3"]:
            lines.append("")
            lines.append("## L3 · 细节支撑")
            for s in r["l3"]:
                lines.append("- " + s)
        lines.append("")
        lines.append("## 关键词")
        lines.append("、".join(r["keywords"]))
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
