#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
podcast.py — 播客 / 口播稿生成（本地兜底，零依赖）

把「原文 / 摘要」转为可直接喂给 TTS / 播客工具的口播稿：

  - 复用本技能 `summarize.py` 引擎抽取核心句作为章节要点（不编造，全部来自原文）；
  - 组织为「开场白 → 主体（每章：标题 + 口播稿 + [停顿] 标记）→ 结尾（总结 + 行动号召）」；
  - 估算总字数与口播时长（中文 ~220 字/分钟，英文 ~150 wpm）；
  - 输出分级讲稿（md）/ 纯文本口播稿（txt，便于直接粘贴进 TTS）/ 结构化（json）。

这是 `podcast` 协同能力（摘要→播客音频）**缺失时的本地兜底**：
用户把输出粘贴进任意 TTS / 播客工具即可生成音频，无需外部技能。

**可选 TTS 合成（扩展）**：用 `--tts` 可把口播稿直接合成音频，无需手动粘贴：
  - edge  —— edge-tts，免费、无需 API Key（中文推荐 `zh-CN-XiaoxiaoNeural`）；
  - openai —— OpenAI TTS，需 `OPENAI_API_KEY`（或 --api-key）；
  - azure —— Azure 语音服务，需 `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION`（纯标准库联网，无第三方包）。
三类 provider 均以 import guard 优雅降级：**未装对应包 / 缺密钥时不报错崩溃，而是给出安装提示并退出**，
零依赖默认（--tts none）与 md/txt/json 输出路径完全不受影响。
"""

import sys
import os
import re
import json
import argparse

# ---------------------------------------------------------------------------
# 读入
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


# ---------------------------------------------------------------------------
# 句子切分（与 summarize 约定一致：中英文句末切分）
# ---------------------------------------------------------------------------
SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")


def split_sentences(text):
    parts = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    return parts


# ---------------------------------------------------------------------------
# 取核心句（章节要点）：复用 summarize 引擎，再拆回句子
# ---------------------------------------------------------------------------
def key_sentences(text, chapters=5, keywords_k=8):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from summarize import summarize
        res = summarize([text], length=chapters, keywords_k=keywords_k,
                        do_eval=False, brief=False, multi=False, cite=False)
        summary = res.get("summary", "")
    except Exception:
        # 引擎不可用则退化为首尾句抽样
        sents = split_sentences(text)
        if not sents:
            return []
        step = max(1, len(sents) // max(1, chapters))
        summary = "。".join(sents[::step][:chapters])
    return split_sentences(summary)


# ---------------------------------------------------------------------------
# 时长估算
# ---------------------------------------------------------------------------
def estimate_duration(text):
    """返回 (cjk_chars, latin_words, seconds)。"""
    cjk = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]+", text))
    sec_cjk = cjk / 220.0 * 60.0      # 220 字/分钟
    sec_latin = latin / 150.0 * 60.0  # 150 wpm
    total = sec_cjk + sec_latin
    return cjk, latin, total


def fmt_duration(sec):
    if sec <= 0:
        return "0 秒"
    m = int(sec // 60)
    s = int(sec % 60)
    if m:
        return "%d 分 %d 秒" % (m, s)
    return "%d 秒" % s


# ---------------------------------------------------------------------------
# 口播稿组装
# ---------------------------------------------------------------------------
def build_script(text, title, host, chapters, keywords_k):
    sents = key_sentences(text, chapters=chapters, keywords_k=keywords_k)
    if not sents:
        sents = split_sentences(text)[:chapters] or ["（未从输入抽取到可用内容）"]

    # 开场白：用主题 + 首句要点引导，不编造额外事实
    lead = sents[0] if sents else ""
    intro = (
        "欢迎收听本期节目。今天我们聊聊《%s》。%s 接下来，我会用 %d 个要点，"
        "带大家快速把握核心内容。[停顿]"
        % (title, ("我们从一个关键结论说起：" + lead) if lead else "", len(sents))
    )

    body = []
    for i, s in enumerate(sents, 1):
        chapter = (
            "第 %d 个要点。%s[停顿]"
            % (i, s)
        )
        body.append({"no": i, "text": chapter})

    outro = (
        "以上就是本期关于《%s》的 %d 个核心要点。如果觉得有用，欢迎收藏或分享。[停顿]"
        "感谢收听，我们下期再见。"
        % (title, len(sents))
    )

    full = intro + "\n" + "\n".join(c["text"] for c in body) + "\n" + outro
    cjk, latin, sec = estimate_duration(full)
    return {
        "title": title,
        "host": host,
        "chapters": len(sents),
        "intro": intro,
        "body": body,
        "outro": outro,
        "full_text": full,
        "stats": {
            "cjk_chars": cjk,
            "latin_words": latin,
            "est_seconds": round(sec, 1),
            "est_duration": fmt_duration(sec),
        },
    }


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------
def render_md(sc):
    lines = ["# 口播稿：《%s》" % sc["title"], ""]
    if sc["host"]:
        lines.append("> 主播 / 节目：%s" % sc["host"])
    lines.append("")
    lines.append("**预计时长**：%s（中文 %d 字 · 英文 %d 词）" % (
        sc["stats"]["est_duration"], sc["stats"]["cjk_chars"], sc["stats"]["latin_words"]))
    lines.append("")
    lines.append("## 开场白")
    lines.append(sc["intro"])
    lines.append("")
    lines.append("## 主体")
    for c in sc["body"]:
        lines.append("- %s" % c["text"])
    lines.append("")
    lines.append("## 结尾")
    lines.append(sc["outro"])
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 纯文本口播稿（可直接粘贴进 TTS / 播客工具）")
    lines.append("")
    lines.append("```text")
    lines.append(sc["full_text"])
    lines.append("```")
    return "\n".join(lines)


def render_txt(sc):
    return sc["full_text"]


# ---------------------------------------------------------------------------
# 可选 TTS 合成（第三方依赖按需安装；缺失时优雅降级，不破坏零依赖默认）
# ---------------------------------------------------------------------------
class TTSProvider:
    """TTS provider 抽象基类。子类须实现 available() / synthesize()。"""
    name = ""
    pkg = ""            # pip 包名（用于缺失提示）；留空表示纯标准库
    needs_key = False

    def available(self):
        return False

    def synthesize(self, text, voice, out_path, **opts):
        raise NotImplementedError


def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


class EdgeTTSProvider(TTSProvider):
    name = "edge"
    pkg = "edge-tts"

    def available(self):
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False

    def synthesize(self, text, voice, out_path, **opts):
        import asyncio
        import edge_tts
        v = voice or "zh-CN-XiaoxiaoNeural"

        async def _run():
            comm = edge_tts.Communicate(text, v)
            await comm.save(out_path)

        asyncio.run(_run())


class OpenAITTSProvider(TTSProvider):
    name = "openai"
    pkg = "openai"
    needs_key = True

    def available(self):
        try:
            import openai  # noqa: F401
            return True
        except Exception:
            return False

    def synthesize(self, text, voice, out_path, **opts):
        from openai import OpenAI
        client = OpenAI(api_key=opts.get("api_key") or os.environ.get("OPENAI_API_KEY"))
        model = opts.get("model", "tts-1")
        v = voice or "alloy"
        with client.audio.speech.with_streaming_response.create(
                model=model, voice=v, input=text) as resp:
            resp.stream_to_file(out_path)


class AzureTTSProvider(TTSProvider):
    name = "azure"
    pkg = ""  # 纯标准库 urllib，无需第三方包
    needs_key = True

    def available(self):
        return True  # 仅依赖网络与密钥，无第三方依赖

    def synthesize(self, text, voice, out_path, **opts):
        import ssl
        import urllib.error
        import urllib.request
        key = opts.get("api_key") or os.environ.get("AZURE_SPEECH_KEY")
        region = opts.get("region") or os.environ.get("AZURE_SPEECH_REGION")
        if not key or not region:
            raise RuntimeError(
                "Azure TTS 需要 AZURE_SPEECH_KEY 与 AZURE_SPEECH_REGION"
                "（环境变量，或 --api-key / --region）")
        v = voice or "zh-CN-XiaoxiaoNeural"
        ctx = ssl.create_default_context()
        # 1) 换取访问令牌
        token_url = "https://%s.api.cognitive.microsoft.com/sts/v1.0/issueToken" % region
        req = urllib.request.Request(token_url, data=b"", method="POST")
        req.add_header("Ocp-Apim-Subscription-Key", key)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
                token = r.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise RuntimeError("Azure 取令牌失败：%s" % e)
        # 2) 合成音频（SSML）
        ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                'xml:lang="zh-CN"><voice name="%s">%s</voice></speak>'
                % (v, _xml_escape(text)))
        tts_url = "https://%s.tts.speech.microsoft.com/cognitiveservices/v1" % region
        req2 = urllib.request.Request(tts_url, data=ssml.encode("utf-8"), method="POST")
        req2.add_header("Authorization", "Bearer " + token)
        req2.add_header("Content-Type", "application/ssml+xml")
        req2.add_header("X-Microsoft-OutputFormat",
                        "audio-16khz-128kbitrate-mono-mp3")
        try:
            with urllib.request.urlopen(req2, context=ctx, timeout=60) as r:
                audio = r.read()
        except urllib.error.URLError as e:
            raise RuntimeError("Azure 合成失败：%s" % e)
        with open(out_path, "wb") as f:
            f.write(audio)


TTS_PROVIDERS = {
    "edge": EdgeTTSProvider,
    "openai": OpenAITTSProvider,
    "azure": AzureTTSProvider,
}

DEFAULT_VOICE = {
    "edge": "zh-CN-XiaoxiaoNeural",
    "openai": "alloy",
    "azure": "zh-CN-XiaoxiaoNeural",
}


def run_tts(provider_name, text, out_path, voice, api_key=None, region=None, model=None):
    """返回 (ok, message)。ok=False 时 message 为错误/提示，exit code 应为 2。"""
    prov = TTS_PROVIDERS[provider_name]()
    if not prov.available():
        if prov.pkg:
            return False, ("未安装 TTS 依赖 `%s`。请先安装：\n"
                           "  pip install %s\n然后重试 --tts %s。"
                           % (prov.pkg, prov.pkg, provider_name))
        return False, "TTS provider 不可用。"
    try:
        prov.synthesize(text, voice, out_path,
                        api_key=api_key, region=region, model=model)
    except RuntimeError as e:
        return False, "TTS 合成失败：%s" % e
    except Exception as e:  # 网络/鉴权/IO 等
        return False, "TTS 合成异常：%s" % e
    return True, "已合成音频：%s" % out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="播客/口播稿生成（本地兜底，零依赖；可选 TTS）")
    ap.add_argument("input", help="原文/摘要文本文件（或 - 读 stdin）")
    ap.add_argument("--title", default="", help="节目/主题标题（默认取首句或文件名）")
    ap.add_argument("--host", default="", help="主播/节目名（可选，写入抬头）")
    ap.add_argument("--chapters", type=int, default=5, help="主体要点（章节）数")
    ap.add_argument("--keywords", type=int, default=8, help="抽取要点时的关键词数")
    ap.add_argument("--format", default="md", choices=["md", "txt", "json"])
    ap.add_argument("--out", default=None, help="口播稿输出文件路径（md/txt/json）")
    # 可选 TTS 合成
    ap.add_argument("--tts", default="none",
                    choices=["none", "edge", "openai", "azure"],
                    help="TTS 合成引擎：none=仅输出讲稿；edge=免费无密钥；"
                         "openai/azure=需 API Key（默认 none）")
    ap.add_argument("--voice", default="", help="TTS 语音名（留空用各引擎默认值）")
    ap.add_argument("--audio", default=None, help="合成音频输出路径（默认 <标题>.mp3）")
    ap.add_argument("--api-key", default=None, help="openai/azure 的 API Key（或走环境变量）")
    ap.add_argument("--region", default=None, help="azure 区域（或走 AZURE_SPEECH_REGION）")
    ap.add_argument("--model", default="tts-1", help="openai 模型（默认 tts-1）")
    args = ap.parse_args()

    text = read_text(args.input)
    title = args.title or (os.path.splitext(os.path.basename(args.input))[0]
                           if args.input != "-" else "未命名主题")
    sc = build_script(text, title, args.host, args.chapters, args.keywords)

    if args.format == "json":
        out = json.dumps(sc, ensure_ascii=False, indent=2)
    elif args.format == "txt":
        out = render_txt(sc)
    else:
        out = render_md(sc)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s（章节=%d，预计%s）\n"
                         % (args.out, sc["chapters"], sc["stats"]["est_duration"]))
    else:
        sys.stdout.write(out + "\n")

    # 可选 TTS 合成（在输出讲稿之后，不影响讲稿产出）
    if args.tts and args.tts != "none":
        audio_path = args.audio or (
            os.path.splitext(args.out)[0] + ".mp3"
            if args.out else (title + ".mp3"))
        ok, msg = run_tts(
            args.tts, sc["full_text"], audio_path,
            voice=args.voice or DEFAULT_VOICE.get(args.tts, ""),
            api_key=args.api_key, region=args.region, model=args.model)
        sys.stderr.write(msg + "\n")
        if not ok:
            sys.exit(2)


if __name__ == "__main__":
    main()
