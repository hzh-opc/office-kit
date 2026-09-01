#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py — 云端处理结果 × 本地抽取副本 对比与改进建议生成（纯标准库，离线）

用途（对应技能定位「云端结果可与本地副本比较，记录差异与改进建议」）：
  1. 将云端大模型产出的「抽象摘要」与本地抽取式摘要副本逐维对比；
  2. 记录差异点 + 可执行的改进建议，用于反哺本地引擎；
  3. 可导出一段「开发者反馈」JSON（默认收件 hzh.opc@foxmail.com）。

用法：
  python3 compare.py --local LOCAL_SUMMARY --cloud CLOUD_SUMMARY
                     [--original ORIGINAL_TEXT] [--format json|md|txt]
                     [--feedback PATH] [--email hzh.opc@foxmail.com]
  LOCAL_SUMMARY / CLOUD_SUMMARY 可为文本文件，或 `-` 表示 stdin（cloud 用 - 时建议配合 --original）。
"""

import sys
import os
import re
import json
import argparse
import datetime

CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+\-./]*")
ZH_STOP = set("的 了 和 是 在 我 有 也 就 不 人 都 一 上 你 他 她 它 这 那 我们 你们 他们 之 与 及 或 而 但 因为 所以 但是 由于 对于 关于 通过 以及 能够 进行 方面 目前 已经 可能 应该 需要 认为 表示 一种 一些 这样 那样 如果 虽然 为了 从而 并且 然后 此外 例如 比如 按照 根据 使得 成为 作为 可以 没有 不是".split())
# 跨词边界伪词常含的功能字（如 的抽/先的/以本），取词时直接跳过含这些字的二元组
ZH_BOUNDARY = set("的 了 是 在 与 及 或 而 但 因 所 对 通 能 进 目 已 可 需 认 表 如 按 根 使 成 作 没 这 那 就 也 都 又 还 很 更 最 以 把 被 给 让 让 从 向 往 当 若 若 则 且".split())
EN_STOP = set("the a an and or but if then else when while for to of in on at by with from as is are was were be been being it its this that these those we you they he she i my your our their his her them can could should would may might must do does did have has had will shall not no yes so because however therefore thus also more most other another such than into about over under again what which who whom whose how why where there here all any each every".split())


def tokens(text):
    t = []
    for run in re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]+", text):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g in ZH_STOP or (g[0] in ZH_BOUNDARY) or (g[1] in ZH_BOUNDARY):
                continue
            t.append(g)
    for w in LATIN_WORD.findall(text.lower()):
        if w not in EN_STOP:
            t.append(w)
    return t


def kw_set(text, top=12):
    toks = tokens(text)
    freq = {}
    for t in toks:
        if t in ZH_STOP:
            continue
        freq[t] = freq.get(t, 0) + 1
    # 过滤一次性跨词边界噪声：优先保留 freq>=2 的词；不足则放宽到 >=1
    strong = {k: v for k, v in freq.items() if v >= 2}
    pool = strong if len(strong) >= 4 else freq
    ranked = sorted(pool.items(), key=lambda x: x[1], reverse=True)
    return set(k for k, _ in ranked[:top])


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare(local_text, cloud_text, original_text=None):
    lk = kw_set(local_text)
    ck = kw_set(cloud_text)
    overlap = lk & ck
    only_local = lk - ck
    only_cloud = ck - lk

    llen = len(local_text)
    clen = len(cloud_text)
    olen = len(original_text) if original_text else None

    suggestions = []
    if only_local:
        suggestions.append(
            "本地副本含『%s』等关键词而云端摘要未涵盖，建议本地引擎在候选句打分中上调这些词权重，"
            "或在 brief 中显式提示云端模型勿遗漏。" % "、".join(list(only_local)[:5]))
    if only_cloud:
        suggestions.append(
            "云端摘要引入了『%s』等本地未提取的关键信息，提示本地引擎的候选词表/二元组规则可补充该类表达。"
            % "、".join(list(only_cloud)[:5]))
    if olen:
        lcomp = 1 - llen / olen if olen else 0
        ccomp = 1 - clen / olen if olen else 0
        if abs(lcomp - ccomp) > 0.25:
            suggestions.append(
                "压缩比差异较大（本地 %.2f / 云端 %.2f），可校准摘要长度参数（--ratio/--chars）以贴近用户期望。"
                % (lcomp, ccomp))
    if llen and clen:
        if clen > llen * 1.6:
            suggestions.append("云端摘要明显更长，若目标为「省时」，可约束云端摘要输出长度。")
        elif clen < llen * 0.5:
            suggestions.append("云端摘要明显更短，可能丢失要点，建议要求云端保留核心结论句。")

    return {
        "keyword_overlap": sorted(overlap),
        "only_in_local": sorted(only_local),
        "only_in_cloud": sorted(only_cloud),
        "keyword_jaccard": round(jaccard(lk, ck), 3),
        "local_len": llen,
        "cloud_len": clen,
        "original_len": olen,
        "suggestions": suggestions,
    }


def build_feedback(rep, email, local_text, cloud_text):
    return {
        "to": email,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "skill": "summarize",
        "type": "local_engine_improvement",
        "metric": {
            "keyword_jaccard": rep["keyword_jaccard"],
            "only_in_local": rep["only_in_local"],
            "only_in_cloud": rep["only_in_cloud"],
        },
        "suggestions": rep["suggestions"],
        "local_summary_excerpt": local_text[:500],
        "cloud_summary_excerpt": cloud_text[:500],
    }


def main():
    ap = argparse.ArgumentParser(description="云端×本地摘要对比与改进建议")
    ap.add_argument("--local", required=True, help="本地摘要文件或 -")
    ap.add_argument("--cloud", required=True, help="云端摘要文件或 -")
    ap.add_argument("--original", default=None, help="原文（可选，用于压缩比）")
    ap.add_argument("--format", default="json", choices=["json", "md", "txt"])
    ap.add_argument("--feedback", default=None, help="导出开发者反馈 JSON 路径")
    ap.add_argument("--email", default="hzh.opc@foxmail.com")
    args = ap.parse_args()

    def rd(p):
        if p == "-":
            return sys.stdin.read()
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    local_text = rd(args.local)
    cloud_text = rd(args.cloud)
    original_text = rd(args.original) if args.original else None

    rep = compare(local_text, cloud_text, original_text)

    if args.format == "json":
        out = json.dumps(rep, ensure_ascii=False, indent=2)
    elif args.format == "md":
        lines = ["## 云端 × 本地 摘要对比", "",
                 f"- 关键词 Jaccard：{rep['keyword_jaccard']}",
                 f"- 本地长度：{rep['local_len']} 字 / 云端长度：{rep['cloud_len']} 字"]
        if rep["original_len"]:
            lines.append(f"- 原文长度：{rep['original_len']} 字")
        lines += ["", "### 共同关键词", "、".join(rep["keyword_overlap"]) or "（无）",
                  "", "### 仅本地含", "、".join(rep["only_in_local"]) or "（无）",
                  "", "### 仅云端含", "、".join(rep["only_in_cloud"]) or "（无）",
                  "", "### 改进建议"]
        lines += ["- " + s for s in rep["suggestions"]] or ["- 无显著差异"]
        out = "\n".join(lines)
    else:
        out = (f"Jaccard={rep['keyword_jaccard']} 本地{rep['local_len']}字 云端{rep['cloud_len']}字\n"
               + "\n".join("- " + s for s in rep["suggestions"]) or "无显著差异")

    sys.stdout.write(out + "\n")

    if args.feedback:
        fb = build_feedback(rep, args.email, local_text, cloud_text)
        with open(args.feedback, "w", encoding="utf-8") as f:
            json.dump(fb, f, ensure_ascii=False, indent=2)
        sys.stderr.write(f"已导出开发者反馈：{args.feedback}\n")


if __name__ == "__main__":
    main()
