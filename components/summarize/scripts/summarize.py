#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
summarize.py — 本地抽取式摘要与关键词提取引擎（纯标准库，离线，跨平台）

设计原则（对应技能定位）：
  - 完整的本地处理能力（离线）：默认零第三方依赖，Windows / macOS / Linux 均可运行。
    若环境已安装 jieba，则自动启用其分词提升中文关键词质量；未安装则回退内置二元/三元组，不报错。
  - 云端取方法、本地处理信息：通过 `--brief` 模式仅把「关键词 + 候选句 + 结构」
    这一紧凑中间产物交给云端大模型，原始长文不出本机、省 TOKEN。
  - 可定制摘要长度：--length（句数）/ --ratio（比例）/ --chars（字数）。
  - 超长文本：超过 --max-input-chars 时自动滑动窗口分块抽取后合并。
  - 多文档：传入多个输入，跨文档统一提取关键词与候选句，产出联合摘要。
  - 质量评估：压缩比、关键词覆盖、句数缩减、可读性启发式，输出 0~100 评分。
  - 语气：--tone 调节喂给云端模型的摘要语气（neutral/concise/professional/casual）。

用法：
  python3 summarize.py INPUT [INPUT2 ...] [--length N | --ratio R | --chars C]
                           [--keywords K] [--lang auto|zh|en] [--tone neutral|concise|professional|casual]
                           [--max-input-chars N] [--format json|md|txt] [--eval] [--brief]
                           [--cite] [--tldr] [--out PATH]

  INPUT 可为：文本文件路径；或 `-` 表示从 stdin 读取（多文档时每个位置独立）。
  --brief   输出「喂给云端模型的紧凑中间产物」（关键词 + 候选句 + 结构骨架）。
  --eval    在输出中附带质量评估。
  --cite    摘要句末附原文溯源标注（见原文第P段·句S），落实「源文忠实」铁律。
  --tldr    仅输出一句话核心结论（取打分最高句截断为单行）。

本脚本**不依赖任何外部技能**（如 desensitization-sop）；脱敏协同由 SKILL.md 在智能体层
面按「是否安装」条件执行，脚本本身零耦合、缺失不致错。
"""

import sys
import os
import re
import json
import argparse
import math

# ---------------------------------------------------------------------------
# 可选依赖：jieba（中文分词，提升关键词质量）。缺失则优雅回退，绝不报错。
# ---------------------------------------------------------------------------
try:
    import jieba
    try:
        jieba.setLogLevel(20)  # 静默
    except Exception:
        pass
    _JIEBA = True
except Exception:
    _JIEBA = False

# ---------------------------------------------------------------------------
# 停用词（内置，覆盖中英常用功能词；可按需扩展）
# ---------------------------------------------------------------------------
ZH_STOP = set("""
的 了 和 是 在 我 有 也 就 不 人 都 一 一个 上 也 你 他 她 它 这 那 这个 那个 这些 那些
我们 你们 他们 自己 之 与 及 或 而 但 却 因为 所以 但是 由于 对于 关于 通过 以及 能够
进行 方面 问题 情况 目前 已经 可能 应该 需要 认为 表示 一种 一些 这样 那样 如果 虽然
为了 从而 并且 或者 然后 此外 例如 比如 按照 根据 由于 加以 予以 使得 成为 作为 位于
可以 不可 没有 不是 只是 这里 那里 怎么 什么 为什么 如何 多少 一种 一项 一名 一位
其 其其 其中 其他 其余 本身 各自 同样 相反 如此 这么 那么 多少 几 许多 一切 任何
""".split())

EN_STOP = set("""
the a an and or but if then else when while for to of in on at by with from as is are was were
be been being it its this that these those we you they he she i my your our their his her them
can could should would may might must do does did have has had will shall not no yes so because
however therefore thus also more most other another such than into about over under again
further what which who whom whose how why where there here all any each every both either neither
one two three first second last new old get got use used using using see seen make made like
just only very can't don't won't isn't aren't doesn't didn't won't
""".split())

# 中文字符范围
CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")
# 句子切分符
SENT_SPLIT = re.compile(r"(?<=[。！？!?；;…])|(?<=[\n\r])")
# 拉丁词
LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+\-./]*")

# 语气 -> 喂给云端模型的措辞
TONE_INSTR = {
    "neutral": "生成一段连贯、客观、立场中性的抽象式摘要，指出核心结论与要点。",
    "concise": "用尽可能简洁的语言生成摘要，只保留最关键结论，去除一切冗余。",
    "professional": "用专业、正式、书面化的语气生成摘要，适合报告与存档场景。",
    "casual": "用通俗、口语化、易懂的语气生成摘要，面向非专业读者。",
}


def is_cjk(ch):
    return bool(CJK.match(ch))


# ---------------------------------------------------------------------------
# 文本预处理
# ---------------------------------------------------------------------------
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


def split_sentences(text):
    """按中英文标点切分句子，保留非空、去首尾空白。"""
    raw = SENT_SPLIT.split(text)
    out = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        s = re.sub(r"\s+", " ", s)
        out.append(s)
    return out


def split_paragraphs(text):
    """按空行切分段落，返回非空段落列表（用于摘要溯源标注）。"""
    paras = re.split(r"\n\s*\n|\r\n\s*\r\n", text)
    out = []
    for p in paras:
        p = p.strip()
        if p:
            out.append(p)
    return out


def detect_lang(text, sentences):
    cjk = sum(len(CJK_RUN.findall(s)) for s in sentences)
    latin = sum(len(LATIN_WORD.findall(s)) for s in sentences)
    if cjk > latin:
        return "zh"
    if latin > cjk and latin > 0:
        return "en"
    return "zh" if cjk >= latin else "en"


# ---------------------------------------------------------------------------
# 关键词提取
# ---------------------------------------------------------------------------
def cjk_bigrams(text):
    tf, df = {}, {}
    for run in CJK_RUN.findall(text):
        if len(run) < 2:
            continue
        grams = set()
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            tf[g] = tf.get(g, 0) + 1
            grams.add(g)
        for g in grams:
            df[g] = df.get(g, 0) + 1
    return tf, df


def cjk_trigrams(text):
    tf, df = {}, {}
    for run in CJK_RUN.findall(text):
        if len(run) < 3:
            continue
        grams = set()
        for i in range(len(run) - 2):
            g = run[i:i + 3]
            tf[g] = tf.get(g, 0) + 1
            grams.add(g)
        for g in grams:
            df[g] = df.get(g, 0) + 1
    return tf, df


def extract_keywords(text, sentences, lang, top_k=8):
    """返回 [(keyword, weight), ...] 已排序。

    中文：
      - 若 jieba 可用：用 jieba 分词得到真实词，词频*文档频打分（质量最佳）。
      - 否则回退「二元组 + 三元组」候选，并要求跨句复现(df>=2)抑制跨词边界噪声。
    """
    kw = {}

    if lang == "zh":
        if _JIEBA:
            sent_tokens = []
            for s in sentences:
                toks = [t for t in jieba.cut(s)
                        if len(t) >= 2 and CJK_RUN.match(t) and t not in ZH_STOP]
                sent_tokens.append(set(toks))
            tf, df = {}, {}
            for toks in sent_tokens:
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
            for toks in sent_tokens:
                for t in toks:
                    df[t] = df.get(t, 0) + 1
            min_df = 2 if len(sentences) >= 3 else 1
            for t, freq in tf.items():
                if df[t] < min_df:
                    continue
                kw[t] = kw.get(t, 0) + freq * (1.0 + math.log(1 + df[t])) * 1.2
        else:
            bi_tf, bi_df = cjk_bigrams(text)
            tri_tf, tri_df = cjk_trigrams(text)
            n_sent = max(1, len(sentences))
            min_df = 2 if n_sent >= 3 else 1
            for g, freq in bi_tf.items():
                if g in ZH_STOP or bi_df[g] < min_df:
                    continue
                kw[g] = kw.get(g, 0) + freq * (1.0 + math.log(1 + bi_df[g]))
            for g, freq in tri_tf.items():
                if g in ZH_STOP or tri_df[g] < min_df:
                    continue
                kw[g] = kw.get(g, 0) + freq * (1.0 + math.log(1 + tri_df[g])) * 1.3
    else:
        tokens = [w.lower() for w in LATIN_WORD.findall(text)]
        for w in tokens:
            if w in EN_STOP or len(w) <= 1:
                continue
            kw[w] = kw.get(w, 0) + 1.0
        for i in range(len(tokens) - 1):
            a, b = tokens[i].lower(), tokens[i + 1].lower()
            if a in EN_STOP or b in EN_STOP:
                continue
            if len(a) > 2 and len(b) > 2:
                kw["%s %s" % (a, b)] = kw.get("%s %s" % (a, b), 0) + 0.8

    ranked = sorted(kw.items(), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


# ---------------------------------------------------------------------------
# 句子打分（抽取式）
# ---------------------------------------------------------------------------
def score_sentences(sentences, keywords, lang):
    kw_map = {k.lower(): w for k, w in keywords}
    total_kw_weight = sum(kw_map.values()) or 1.0
    n = len(sentences)
    scored = []
    for i, s in enumerate(sentences):
        low = s.lower()
        kcov = 0.0
        for k, w in kw_map.items():
            if k in low:
                kcov += w
        kcov_norm = kcov / total_kw_weight

        pos = 0.0
        if i == 0:
            pos = 1.0
        elif i == n - 1:
            pos = 0.7
        elif i <= max(1, n // 5):
            pos = 0.6
        else:
            pos = 0.3

        L = len(s)
        if lang == "zh":
            if 15 <= L <= 80:
                len_score = 1.0
            elif L < 15:
                len_score = 0.4
            else:
                len_score = max(0.4, 1.0 - (L - 80) / 200.0)
        else:
            words = len(s.split())
            if 8 <= words <= 35:
                len_score = 1.0
            elif words < 8:
                len_score = 0.4
            else:
                len_score = max(0.4, 1.0 - (words - 35) / 80.0)

        signal = 0.0
        signals = ["总之", "因此", "结论", "综上", "本文", "研究", "发现", "建议",
                   "in conclusion", "therefore", "however", "we propose", "our findings",
                   "this paper", "the result", "importantly"]
        if any(sig in low for sig in signals):
            signal = 0.4

        score = 0.55 * kcov_norm + 0.22 * pos + 0.15 * len_score + 0.08 * signal
        scored.append((i, s, score))  # (全局句索引, 句文本, 分值)
    return scored


# ---------------------------------------------------------------------------
# 摘要长度解析
# ---------------------------------------------------------------------------
def select_sentences(scored, n_total, length=None, ratio=None, chars=None):
    """scored: [(全局句索引, 句文本, 分值), ...]。返回按全局顺序排序的 (idx, s, sc)。"""
    if chars:
        chosen, total = [], 0
        for i, s, sc in sorted(scored, key=lambda x: x[2], reverse=True):
            if total + len(s) > chars and chosen:
                break
            chosen.append((i, s, sc))
            total += len(s)
        return sorted(chosen, key=lambda x: x[0])
    if ratio is not None:
        k = max(1, int(round(n_total * ratio)))
    elif length is not None:
        k = length
    else:
        k = max(1, min(5, int(round(n_total * 0.3))))
    k = min(k, n_total)
    top = sorted(scored, key=lambda x: x[2], reverse=True)[:k]
    return sorted(top, key=lambda x: x[0])


# ---------------------------------------------------------------------------
# 超长文本：滑动窗口分块抽取后合并
# ---------------------------------------------------------------------------
def chunk_sentences(sentences, max_chars, overlap=1):
    chunks, cur, cur_chars = [], [], 0
    for i, s in enumerate(sentences):
        if cur and cur_chars + len(s) > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:] if overlap else []
            cur_chars = sum(len(x[1]) for x in cur)
        cur.append((i, s))
        cur_chars += len(s)
    if cur:
        chunks.append(cur)
    return chunks


def sliding_window(sentences, keywords, lang, max_input_chars,
                   length=None, ratio=None, chars=None):
    chunks = chunk_sentences(sentences, max_input_chars)
    # 各块按最终比例抽取候选句（全局索引），重叠句去重
    final_ratio = ratio if ratio is not None else 0.3
    candidates = []
    for ch in chunks:
        idxs = [i for i, _ in ch]
        ch_sent = [s for _, s in ch]
        scored = score_sentences(ch_sent, keywords, lang)
        keep = max(1, int(round(len(ch) * final_ratio)))
        top = sorted(scored, key=lambda x: x[2], reverse=True)[:keep]
        for local_i, s, sc in top:
            candidates.append((idxs[local_i], s, sc))
    seen = {}
    for g, s, sc in candidates:
        if g not in seen:
            seen[g] = (g, s, sc)
    candidates = list(seen.values())

    # 用户显式 --length / --chars 时，在候选集上做二次裁剪
    if length is not None:
        chosen = sorted(candidates, key=lambda x: x[2], reverse=True)[:length]
        return sorted(chosen, key=lambda x: x[0])
    if chars is not None:
        chosen, total = [], 0
        for g, s, sc in sorted(candidates, key=lambda x: x[2], reverse=True):
            if total + len(s) > chars and chosen:
                break
            chosen.append((g, s, sc))
            total += len(s)
        return sorted(chosen, key=lambda x: x[0])
    return sorted(candidates, key=lambda x: x[0])


# ---------------------------------------------------------------------------
# 质量评估
# ---------------------------------------------------------------------------
def quality_eval(original, summary, keywords, chosen_idx, n_total):
    orig_chars = len(original)
    sum_chars = len(summary)
    compression = 1.0 - (sum_chars / orig_chars) if orig_chars else 0.0
    sent_red = 1.0 - (len(chosen_idx) / n_total) if n_total else 0.0

    low_sum = summary.lower()
    covered = sum(1 for k, _ in keywords if k.lower() in low_sum)
    kw_cov = covered / len(keywords) if keywords else 0.0

    sents = [s for _, s, _ in chosen_idx]
    avg_len = (sum(len(s) for s in sents) / len(sents)) if sents else 0
    if 25 <= avg_len <= 70:
        read = 1.0
    elif avg_len < 25:
        read = 0.6
    else:
        read = max(0.5, 1.0 - (avg_len - 70) / 150.0)

    score = int(round(100 * (0.35 * compression + 0.30 * kw_cov +
                             0.20 * sent_red + 0.15 * read)))
    return {
        "compression_ratio": round(compression, 3),
        "sentence_reduction": round(sent_red, 3),
        "keyword_coverage": round(kw_cov, 3),
        "keywords_covered": covered,
        "keywords_total": len(keywords),
        "avg_sentence_len": round(avg_len, 1),
        "score": max(0, min(100, score)),
    }


# ---------------------------------------------------------------------------
# 主流程（单文档 / 多文档统一）
# ---------------------------------------------------------------------------
def summarize(texts, length=None, ratio=None, chars=None, keywords_k=8,
              lang="auto", do_eval=True, brief=False,
              max_input_chars=200000, tone="neutral", multi=False, cite=False):
    if isinstance(texts, str):
        texts = [texts]
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return {"summary": "", "keywords": [], "eval": None, "brief": None,
                "lang": lang, "sentence_count": 0, "doc_count": 0}

    # 构建全局句序列（含文档归属、段落归属）与合并全文（供关键词提取）
    all_sent = []               # [(doc_id, para_idx, 句文本)]
    doc_of = {}                 # 全局句索引 -> doc_id
    para_of = {}                # 全局句索引 -> para_idx（0 基）
    para_sent_local = {}        # (doc_id, para_idx) -> [全局句索引, ...]（句内顺序）
    full_parts = []
    gidx = 0
    for d, t in enumerate(texts):
        for p, para in enumerate(split_paragraphs(t)):
            for s in split_sentences(para):
                all_sent.append((d, p, s))
                doc_of[gidx] = d
                para_of[gidx] = p
                para_sent_local.setdefault((d, p), []).append(gidx)
                gidx += 1
        full_parts.append(t)
    full_text = "\n".join(full_parts)
    sentences_only = [s for _, _, s in all_sent]

    if not sentences_only:
        return {"summary": "", "keywords": [], "eval": None, "brief": None,
                "lang": lang, "sentence_count": 0, "doc_count": len(texts)}

    if lang == "auto":
        lang = detect_lang(full_text, sentences_only)

    keywords = extract_keywords(full_text, sentences_only, lang, keywords_k)

    # 超长文本滑动窗口（按合并全文长度判断）
    if len(full_text) > max_input_chars and len(sentences_only) > 1:
        chosen = sliding_window(sentences_only, keywords, lang, max_input_chars,
                                length, ratio, chars)
    else:
        scored = score_sentences(sentences_only, keywords, lang)
        chosen = select_sentences(scored, len(sentences_only), length, ratio, chars)

    # 组装摘要（多文档时标注来源；--cite 时附原文溯源标注）
    parts = []
    for g, s, _ in chosen:
        if lang == "zh":
            seg = s
            if not seg.endswith(("。", "！", "？", "!", "?", "；", ";")):
                seg += "。"
            if cite:
                d = doc_of[g]
                p0 = para_of[g]           # 0 基，用于字典查
                p = p0 + 1                # 1 基，用于展示
                sp = para_sent_local[(d, p0)].index(g) + 1
                if multi:
                    seg += "（见第%d篇·第%d段·句%d）" % (d + 1, p, sp)
                else:
                    seg += "（见原文第%d段·句%d）" % (p, sp)
            elif multi:
                seg = "[文档%d] %s" % (doc_of[g] + 1, seg)
            parts.append(seg)
        else:
            parts.append(s)
    if lang == "zh":
        summary = "".join(parts)
    else:
        summary = " ".join(parts)

    chosen_out = [{"index": g, "doc": doc_of[g] + 1,
                   "para": para_of[g] + 1, "text": s} for g, s, _ in chosen]

    # TL;DR：取打分最高的候选句截断为单行核心结论（本地、零依赖）
    if chosen:
        top_g, top_s, _ = max(chosen, key=lambda x: x[2])
        tldr_text = top_s
        cap = 80 if lang == "zh" else 140
        if len(tldr_text) > cap:
            tldr_text = tldr_text[:cap].rstrip("，。、；,.; ") + "…"
    else:
        tldr_text = ""

    result = {
        "lang": lang,
        "doc_count": len(texts),
        "sentence_count": len(sentences_only),
        "summary": summary,
        "keywords": [k for k, _ in keywords],
        "keyword_weights": {k: round(w, 2) for k, w in keywords},
        "chosen_sentences": chosen_out,
        "jieba_used": _JIEBA,
        "tldr": tldr_text,
    }

    if do_eval:
        result["eval"] = quality_eval(full_text, summary, keywords, chosen, len(sentences_only))

    if brief:
        cand = sorted(score_sentences(sentences_only, keywords, lang),
                      key=lambda x: x[2], reverse=True)[:min(10, len(sentences_only))]
        result["brief"] = {
            "keywords": [k for k, _ in keywords],
            "candidate_sentences": [
                {"index": g, "doc": doc_of.get(g, 1), "score": round(sc, 3), "text": s}
                for g, s, sc in cand
            ],
            "total_sentences": len(sentences_only),
            "char_count": len(full_text),
            "instruction": (
                "基于上方关键词与候选句（已脱敏/仅本地信息），%s"
                "不要复述原始长文，不要引入候选句之外的未核实信息。"
                % TONE_INSTR.get(tone, TONE_INSTR["neutral"])
            ),
        }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="本地抽取式摘要与关键词提取（离线/零依赖）")
    ap.add_argument("input", nargs="+", help="文本文件（可多个）或 - (stdin)")
    ap.add_argument("--length", type=int, default=None, help="摘要句数")
    ap.add_argument("--ratio", type=float, default=None, help="摘要占原文比例 0~1")
    ap.add_argument("--chars", type=int, default=None, help="摘要字数上限")
    ap.add_argument("--keywords", type=int, default=8, help="关键词数量")
    ap.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    ap.add_argument("--tone", default="neutral",
                    choices=["neutral", "concise", "professional", "casual"],
                    help="喂给云端模型的摘要语气")
    ap.add_argument("--max-input-chars", type=int, default=200000,
                    help="超长文本滑动窗口阈值（字符数），默认 200000")
    ap.add_argument("--format", default="json", choices=["json", "md", "txt"])
    ap.add_argument("--eval", action="store_true", help="附带质量评估")
    ap.add_argument("--brief", action="store_true", help="输出喂给云端模型的紧凑中间产物")
    ap.add_argument("--cite", action="store_true",
                    help="摘要句末附原文溯源标注（见原文第P段·句S）")
    ap.add_argument("--tldr", action="store_true",
                    help="仅输出一句话 TL;DR 核心结论")
    ap.add_argument("--out", default=None, help="输出文件路径")
    args = ap.parse_args()

    texts = [read_text(p) for p in args.input]
    if not any(t.strip() for t in texts):
        sys.stderr.write("错误：输入为空。\n")
        sys.exit(2)

    multi = len(args.input) > 1
    res = summarize(texts, length=args.length, ratio=args.ratio, chars=args.chars,
                    keywords_k=args.keywords, lang=args.lang, tone=args.tone,
                    max_input_chars=args.max_input_chars,
                    do_eval=args.eval or True, brief=args.brief,
                    multi=multi, cite=args.cite)

    if args.tldr:
        tldr = res.get("tldr", "")
        if args.format == "json":
            out = json.dumps({"tldr": tldr}, ensure_ascii=False, indent=2)
        else:
            out = tldr
    elif args.format == "json":
        out = json.dumps(res, ensure_ascii=False, indent=2)
    elif args.format == "md":
        lines = ["## 摘要", res["summary"], "",
                 "## 关键词", "、".join(res["keywords"])]
        if res.get("eval"):
            e = res["eval"]
            lines += ["", "## 质量评估",
                      f"- 综合评分：{e['score']}/100",
                      f"- 压缩比：{e['compression_ratio']}",
                      f"- 句数缩减：{e['sentence_reduction']}",
                      f"- 关键词覆盖：{e['keyword_coverage']}（{e['keywords_covered']}/{e['keywords_total']}）"]
        out = "\n".join(lines)
    else:
        out = res["summary"] + "\n\n关键词：" + "、".join(res["keywords"])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write(f"已写入：{args.out}\n")
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
