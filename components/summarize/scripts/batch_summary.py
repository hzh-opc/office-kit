#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_summary.py — 对目录下多文档批量摘要并生成索引页（本地、零依赖）

对目录下每个文本文件逐一抽取摘要，汇总为带要点的索引 markdown。
与「多文档联合摘要」（合并为一份）互补：本脚本是「分别摘要 + 索引」。

用法：
  python3 batch_summary.py DIR [DIR2 ...] [--out index.md] [--length N] [--format md|json]

本脚本复用同目录 summarize.py 的引擎；纯标准库、不联网。
"""

import sys
import os
import json
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from summarize import summarize, split_sentences  # 复用本地引擎

TEXT_EXT = {".txt", ".md", ".markdown", ".text"}


def collect_files(dirs):
    files = []
    for d in dirs:
        if os.path.isfile(d):
            files.append(d)
            continue
        for root, _, names in os.walk(d):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in TEXT_EXT:
                    files.append(os.path.join(root, n))
    return files


def first_sentence(summary, n=1):
    sents = split_sentences(summary)
    return " ".join(sents[:n])


def main():
    ap = argparse.ArgumentParser(description="批量目录摘要 + 索引页（本地 / 零依赖）")
    ap.add_argument("dirs", nargs="+", help="目录（或文件）路径，可多个")
    ap.add_argument("--out", default=None, help="索引输出路径（默认打印到 stdout）")
    ap.add_argument("--length", type=int, default=3, help="每篇摘要句数（默认 3）")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    args = ap.parse_args()

    files = collect_files(args.dirs)
    if not files:
        sys.stderr.write("错误：未找到文本文件。\n")
        sys.exit(2)

    entries = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            sys.stderr.write("跳过 %s：%s\n" % (path, e))
            continue
        if not text.strip():
            continue
        try:
            res = summarize([text], length=args.length,
                            do_eval=False, brief=False, multi=False)
        except Exception as e:
            sys.stderr.write("摘要失败 %s：%s\n" % (path, e))
            continue
        entries.append({
            "path": path,
            "name": os.path.basename(path),
            "summary": res.get("summary", ""),
            "headline": first_sentence(res.get("summary", ""), 1),
            "keywords": res.get("keywords", []),
            "lang": res.get("lang", ""),
        })

    if args.format == "json":
        out = json.dumps(entries, ensure_ascii=False, indent=2)
    else:
        lines = ["# 批量摘要索引", ""]
        lines.append("> 共处理 **%d** 篇文档。" % len(entries))
        lines.append("")
        for e in entries:
            lines.append("## %s" % e["name"])
            lines.append("")
            lines.append(e["summary"])
            if e["keywords"]:
                lines.append("")
                lines.append("**关键词**：%s" % "、".join(e["keywords"]))
            lines.append("")
            lines.append("---")
            lines.append("")
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s（%d 篇）\n" % (args.out, len(entries)))
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
