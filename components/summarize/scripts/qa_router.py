#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_router.py — 问答路由 · 多轮状态机（本地、零依赖）

`qa_router` 协同能力的**本地兜底实现**：在原文（及可选摘要）上做基于「源文忠实」的
多轮问答路由。每条问题按关键词在原文中精准取片段作答，并标回具体句 / 段落；多轮之间
用 JSON session 文件持久化上下文，支持追问的**指代消解**（结合上一轮的 topic / 上下文），
并识别「疑似需要联网补全」的问题给出 `needs_external` 标记与下一步建议。

设计要点（与 SKILL.md 一致）：
  - 本地优先、零依赖：复用 `summarize.py` 的 `split_paragraphs` / `split_sentences` 做句级索引；
    检索用 CJK 二元组 + 拉丁词重叠（与 consistency_check / diff_summary 同款 token 口径）。
  - 源文忠实：答案即「从原文检索到的证据句 + 溯源标注」，绝不在本地编造未核实结论。
  - 多轮状态机：session 文件记录每轮 {问题 / 解析后问题 / 答案 / 引用 / topic / 是否需外部}，
    下一轮追问自动结合上一轮上下文消解代词（那这个 / 它 / 为什么 / 举个例子 …）。
  - 受控联网：仅当问题疑似需要外部信息时标记 `needs_external`，建议走 `search`（须三段标记）
    或 `rag`（若已有本地索引），默认不联网。

用法（每轮一次调用，复用同一 --session 文件即形成多轮）：
  python3 qa_router.py --session state.json --original 原文.txt \
      [--summary 摘要.txt] --question "..." [--k 3] \
      [--format md|json|txt] [--out PATH] [--reset]

退出码：0=正常；2=参数/IO 错误。
"""

import sys
import os
import re
import json
import argparse
from datetime import datetime, timezone

# 复用本技能引擎的切分函数（同目录、零耦合）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from summarize import split_paragraphs, split_sentences
except Exception:  # 兜底：自带最小实现
    def split_paragraphs(text):
        out = []
        for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
            p = p.strip()
            if p:
                out.append(p)
        return out
    def split_sentences(text):
        raw = re.split(r"(?<=[。！？!?；;…])|(?<=[\n\r])", text)
        return [s.strip() for s in raw if s.strip()]

# ---------------------------------------------------------------------------
# token（与 consistency_check / diff_summary 同口径）
# ---------------------------------------------------------------------------
CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")
LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+\-./]*")


def tokens(text):
    toks = set()
    for run in CJK_RUN.findall(text):
        if len(run) >= 2:
            for i in range(len(run) - 1):
                toks.add(run[i:i + 2])
        elif run:
            toks.add(run)
    for w in LATIN_WORD.findall(text.lower()):
        if len(w) > 1:
            toks.add(w)
    return toks


# ---------------------------------------------------------------------------
# 索引原文句（段落归属）
# ---------------------------------------------------------------------------
def index_sentences(text):
    """返回 [(para_idx(0基), sent_text), ...]。"""
    out = []
    for p, para in enumerate(split_paragraphs(text)):
        for s in split_sentences(para):
            out.append((p, s))
    return out


# ---------------------------------------------------------------------------
# 指代消解与意图识别
# ---------------------------------------------------------------------------
FOLLOWUP_CUE = re.compile(
    r"(那这个|这个呢|它|它们|这|那|为什么|怎么|如何|举个例子|比如|也就是说|"
    r"然后呢|接着|上面说的|前面说的|前者|后者|这点是|那点是|这种情况|此| thereof)",
    re.I)
EXTERNAL_CUE = re.compile(
    r"(最新|最新进展|趋势|对比外部|外部|网上|查一下|查一查|搜索|业界|"
    r"竞争对手|市场|202[4-9]|203\d|今年|目前市场|其他人|相关研究|公开资料|百度|谷歌|联网)",
    re.I)
INTERROGATIVE = re.compile(r"(是什么|为什么|怎么|如何|哪些|哪几个|谁|哪年|是否|吗|呢|？|\?)$", re.I)


def subject_of(question):
    """从问题中抽取干净的主体（去掉末尾疑问词/标点），用于上下文 topic。"""
    s = re.sub(r"[？?]+$", "", question.strip())
    s = INTERROGATIVE.sub("", s).strip()
    # 去掉指代代词残留
    s = FOLLOWUP_CUE.sub("", s).strip()
    return s or question.strip()


def resolve_question(raw, prev_topic, prev_context_text):
    """结合上一轮上下文消解追问代词；返回 (resolved, is_followup)。"""
    has_cue = bool(FOLLOWUP_CUE.search(raw))
    # 关键词过少（基本只有代词/短追问）→ 视为追问，用上一轮 topic 丰富
    own_kw = [t for t in tokens(raw) if len(t) >= 2]
    short = len(raw.strip()) <= 12 or (len(own_kw) <= 2 and has_cue)
    if prev_topic and (short or has_cue) and not EXTERNAL_CUE.search(raw):
        # 去掉问题中的指代代词，再用上一轮 topic（干净主体）补全
        core = FOLLOWUP_CUE.sub("", raw).strip()
        if prev_topic in core:
            resolved = core
        else:
            resolved = "%s %s" % (prev_topic, core) if core else prev_topic
        return resolved.strip(), True
    return raw, False


def detect_external(raw):
    return bool(EXTERNAL_CUE.search(raw))


# ---------------------------------------------------------------------------
# 检索（取 top-k 相关句）
# ---------------------------------------------------------------------------
def retrieve(question, indexed, k=3, exclude=None):
    qt = tokens(question)
    if not qt:
        return []
    exclude = exclude or set()
    scored = []
    for (p, s) in indexed:
        st = tokens(s)
        overlap = len(qt & st)
        if overlap == 0:
            continue
        # 重叠数 / 问句 token 数（召回侧命中比例）
        score = overlap / max(1, len(qt))
        # 新颖性惩罚：上一轮已引用的句子打分大幅下调，迫使追问带出新证据
        if s in exclude:
            score *= 0.15
        scored.append((score, p, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"para": p + 1, "text": s, "score": round(sc, 3)}
            for sc, p, s in scored[:k]]


# ---------------------------------------------------------------------------
# session 状态读写
# ---------------------------------------------------------------------------
def load_session(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"session_id": "qa-%s" % datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "original_path": "", "summary_path": "",
            "turns": [], "last_context": {}}


def save_session(path, state):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def answer_turn(state, original_text, summary_text, question, k):
    indexed = index_sentences(original_text)
    if summary_text:
        indexed = index_sentences(summary_text) + indexed  # 摘要优先，原文兜底召回

    prev = state.get("last_context", {}) or {}
    prev_topic = prev.get("topic", "")
    prev_ctx = prev.get("context_text", "")
    # 全局新颖性：本会话所有已引用句子都参与惩罚，避免追问在轮次间反复带回同一证据
    all_cited = set()
    for t in state.get("turns", []):
        for c in t.get("citations", []):
            all_cited.add(c["text"])

    resolved, is_followup = resolve_question(question, prev_topic, prev_ctx)
    needs_external = detect_external(resolved)

    hits = retrieve(resolved, indexed, k=k, exclude=all_cited)
    if not hits and prev_ctx:
        # 本轮回检索为空但有上下文：退而在上一轮上下文里取片段
        hits = retrieve(resolved, index_sentences(prev_ctx), k=k)

    # 答案 = 检索到的证据句（本地不编造）；逐句附溯源标注
    evidence = []
    for h in hits:
        seg = h["text"]
        if not seg.endswith(("。", "！", "？", "!", "?", "；", ";")):
            seg += "。"
        seg += "（见原文第%d段）" % h["para"]
        evidence.append(seg)
    answer = "".join(evidence) if evidence else "（未在原文检索到相关片段；建议补充上下文或改述问题）"

    # topic：追问轮沿用上一轮的稳定主体（避免 aspect 累积 snowball），
    #        新话题轮取本问干净主体；仅用于下一轮指代消解
    if is_followup and prev_topic:
        topic = prev_topic
    else:
        topic = subject_of(question) or (hits[0]["text"][:12] if hits else "")
    context_text = "\n".join(h["text"] for h in hits) if hits else prev_ctx

    suggested = []
    if needs_external:
        suggested += ["search（受控联网补全，须按【原文】/【联网补全】/【处理结果】三段标记）",
                      "rag（若已在原文建本地索引，做溯源式追问）"]
    else:
        suggested += ["mindmap（把该要点可视化为脑图）",
                      "hierarchical_summary（展开层级要点）",
                      "继续追问（可指代上一轮 topic，自动消解）"]

    turn = {
        "turn": len(state.get("turns", [])) + 1,
        "raw_question": question,
        "resolved_question": resolved if resolved != question else None,
        "is_followup": is_followup,
        "needs_external": needs_external,
        "answer": answer,
        "citations": [{"para": h["para"], "text": h["text"]} for h in hits],
        "topic": topic,
        "suggested": suggested,
    }
    state.setdefault("turns", []).append(turn)
    state["last_context"] = {"topic": topic, "context_text": context_text,
                             "citations": [{"para": c["para"], "text": c["text"]}
                                           for c in turn["citations"]]}
    if original_text:
        state["original_path"] = state.get("original_path") or ""
    return turn


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------
def render_md(turn):
    lines = ["## 第 %d 轮问答" % turn["turn"], ""]
    lines.append("**问题**：%s" % turn["raw_question"])
    if turn.get("resolved_question"):
        lines.append("**解析后（指代消解）**：%s" % turn["resolved_question"])
    lines.append("")
    lines.append("**依据原文**：")
    if turn["citations"]:
        for c in turn["citations"]:
            lines.append("- %s（见原文第%d段）" % (c["text"], c["para"]))
    else:
        lines.append("- （未检索到相关片段）")
    lines.append("")
    lines.append("**建议下一步**：")
    for s in turn["suggested"]:
        lines.append("- %s" % s)
    return "\n".join(lines)


def render_txt(turn):
    out = ["[第%d轮] Q: %s" % (turn["turn"], turn["raw_question"])]
    if turn.get("resolved_question"):
        out.append("  解析: %s" % turn["resolved_question"])
    for c in turn["citations"]:
        out.append("  - %s（见原文第%d段）" % (c["text"], c["para"]))
    out.append("  建议: " + " / ".join(turn["suggested"]))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="问答路由·多轮状态机（本地、源文忠实、零依赖）")
    ap.add_argument("--session", required=True, help="session 状态文件（JSON，多轮复用同一文件）")
    ap.add_argument("--original", required=True, help="原文文本文件（或 - 读 stdin）")
    ap.add_argument("--summary", default=None, help="可选摘要文件（检索时优先召回）")
    ap.add_argument("--question", required=True, help="本轮问题")
    ap.add_argument("--k", type=int, default=3, help="每轮检索返回的相关句数")
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--out", default=None, help="输出文件路径（仅当前轮；session 始终写回 --session）")
    ap.add_argument("--reset", action="store_true", help="清空已有 session 再开始新一轮")
    args = ap.parse_args()

    if args.original == "-":
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        original_text = sys.stdin.read()
    else:
        if not os.path.exists(args.original):
            sys.stderr.write("错误：原文文件不存在：%s\n" % args.original)
            sys.exit(2)
        with open(args.original, "r", encoding="utf-8", errors="replace") as f:
            original_text = f.read()

    summary_text = ""
    if args.summary:
        if os.path.exists(args.summary):
            with open(args.summary, "r", encoding="utf-8", errors="replace") as f:
                summary_text = f.read()

    state = load_session(args.session)
    if args.reset:
        state = {"session_id": state.get("session_id", "qa"),
                 "created_at": datetime.now(timezone.utc).isoformat(),
                 "turns": [], "last_context": {}}
    state["original_path"] = args.original
    if args.summary:
        state["summary_path"] = args.summary

    turn = answer_turn(state, original_text, summary_text, args.question, k=args.k)
    save_session(args.session, state)

    if args.format == "json":
        out = json.dumps(turn, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        out = render_txt(turn)
    else:
        out = render_md(turn)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入本轮：%s\n" % args.out)
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
