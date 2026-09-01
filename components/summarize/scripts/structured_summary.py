#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
structured_summary.py — 结构化信息抽取（本地、零依赖、启发式）

从纯文本中抽取结构化条目，便于把「散落的叙述」转为可机读的结构，与 chart /
entity_extract 等协同能力呼应。支持四类抽取（--mode 可限定的子集）：

  - qa        问答对：含「？/ ?」的问句 + 其下一句作答；或「问：/答：」「Q:/A:」成对
  - list      列表项：以 -/*/+ 或 1. 1、1) （1） 等开头的行
  - definition 定义/要点说明：短主语 + 冒号/破折号/「是指/即」构成的「X：Y」「X——Y」「X 是指 Y」
  - table     表格行：markdown 表格（| 分隔）及其表头/分隔行

用法：
  python3 structured_summary.py <输入.txt> [-] [--mode auto|qa|list|definition|table] \
      [--format md|json] [--out PATH]

本脚本**不依赖任何外部技能**；纯标准库正则 + 启发式实现（非 NER，质量受限于
文本形态；缺失外部抽取技能时作为轻量本地替代，详见 SKILL.md entity_extract 兜底）。
"""

import sys
import os
import re
import json
import argparse

QA_MARK = re.compile(r"^\s*(问|问题|Q|Question)\s*[:：.、)]", re.I)
QA_ANS = re.compile(r"^\s*(答|答案|A|Answer)\s*[:：.、)]", re.I)
LIST_MARK = re.compile(r"^\s*([-*+]\s+|\d+[.、)]\s+|（\d+）\s+|\(?\d+\)\s+)")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
DEF_MARK = re.compile(r"^(.{1,24}?)\s*(?:[:：]|——|--|—)\s*(.+)$")
DEF_VERB = re.compile(r"^(.{1,24}?)\s*(?:是指|即是|即|称为|称作)\s*(.+)$")
QA_SENT = re.compile(r"[？?]\s*$")


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


def extract_items(text, mode="auto"):
    """返回 items 列表，每项 {type, content, ...}。"""
    lines = text.splitlines()
    items = []
    i = 0
    n = len(lines)

    def want(t):
        return mode == "auto" or mode == t

    # 先处理显式「问：/答：」成对（优先级最高，避免被 definition 误吞）
    paired = [False] * n
    if want("qa"):
        j = 0
        while j < n:
            if QA_MARK.match(lines[j]) and j + 1 < n and QA_ANS.match(lines[j + 1]):
                q = re.sub(QA_MARK, "", lines[j]).strip()
                a = re.sub(QA_ANS, "", lines[j + 1]).strip()
                items.append({"type": "qa", "question": q, "answer": a,
                              "content": "问：%s　答：%s" % (q, a)})
                paired[j] = paired[j + 1] = True
                j += 2
                continue
            j += 1

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # 表格行
        if want("table") and TABLE_ROW.match(line):
            cells = [c.strip() for c in TABLE_ROW.match(line).group(1).split("|")]
            is_sep = bool(TABLE_SEP.match(line))
            if is_sep:
                i += 1
                continue  # 分隔行是结构噪声，不计入结构化条目
            items.append({"type": "table", "cells": cells, "is_separator": False,
                          "content": stripped})
            i += 1
            continue

        # 已配对的问答行
        if paired[i]:
            i += 1
            continue

        # 列表项
        if want("list") and LIST_MARK.match(line):
            content = re.sub(LIST_MARK, "", line).strip()
            if content:
                items.append({"type": "list", "content": content})
            i += 1
            continue

        # 定义 / 要点说明（短主语 + 标记）
        if want("definition"):
            m = DEF_VERB.match(stripped)
            if m and len(m.group(2)) >= 2:
                items.append({"type": "definition", "term": m.group(1).strip(),
                              "desc": m.group(2).strip(),
                              "content": "%s：%s" % (m.group(1).strip(), m.group(2).strip())})
                i += 1
                continue
            m = DEF_MARK.match(stripped)
            if m and 1 <= len(m.group(1).strip()) <= 24 and len(m.group(2).strip()) >= 2:
                items.append({"type": "definition", "term": m.group(1).strip(),
                              "desc": m.group(2).strip(),
                              "content": "%s：%s" % (m.group(1).strip(), m.group(2).strip())})
                i += 1
                continue

        # 问句（以 ？/? 结尾）→ 其下一句作答
        if want("qa") and QA_SENT.search(stripped):
            q = stripped
            a = ""
            if i + 1 < n:
                nxt = lines[i + 1].strip()
                if nxt and not (LIST_MARK.match(lines[i + 1]) or TABLE_ROW.match(lines[i + 1])):
                    a = nxt
                    i += 1
            items.append({"type": "qa", "question": q, "answer": a,
                          "content": "问：%s　答：%s" % (q, a)})
            i += 1
            continue

        i += 1

    # 统计
    stat = {}
    for it in items:
        stat[it["type"]] = stat.get(it["type"], 0) + 1
    return {"items": items, "stats": stat, "total": len(items)}


def main():
    ap = argparse.ArgumentParser(description="结构化信息抽取（问答/列表/定义/表格，零依赖）")
    ap.add_argument("input", help="文本文件（或 - 读 stdin）")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "qa", "list", "definition", "table"],
                    help="抽取类型子集（默认 auto=全部）")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    text = read_text(args.input)
    r = extract_items(text, mode=args.mode)

    if args.format == "json":
        out = json.dumps(r, ensure_ascii=False, indent=2)
    else:  # md
        lines = ["# 结构化抽取", ""]
        lines.append("> 共抽取 **%d** 条结构化条目。" % r["total"])
        if r["stats"]:
            lines.append("")
            lines.append("分类：" + ", ".join("%s=%d" % (k, v)
                                              for k, v in sorted(r["stats"].items())))
        order = ["qa", "list", "definition", "table"]
        title = {"qa": "问答对", "list": "列表项", "definition": "定义 / 要点说明", "table": "表格行"}
        for t in order:
            group = [it for it in r["items"] if it["type"] == t]
            if not group:
                continue
            lines.append("")
            lines.append("## %s（%d）" % (title[t], len(group)))
            if t == "table":
                for it in group:
                    if it.get("is_separator"):
                        continue
                    lines.append("- " + " | ".join(it["cells"]))
            elif t == "qa":
                for it in group:
                    lines.append("- **问**：%s" % it["question"])
                    if it["answer"]:
                        lines.append("  **答**：%s" % it["answer"])
            else:
                for it in group:
                    lines.append("- %s" % it["content"])
        out = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
