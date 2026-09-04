#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 纠正版稿件生成（D16 交付物范式 + 组件反馈 P0-②/P1-③）。

职责（呼应方案 §3.6 / 流程规范 §1 ⑦.5 / D16 / 组件反馈「交互与展示优化」）：
- 把各能力域的「识别结果」（OCR/ASR/视觉原始文本）完善为「纠正版稿件」——
  这是面向用户的交付物；原始识别结果保留为 **单一备查副本**（raw_text），不另存多份。
- 默认本地离线纠正：复用本机 ollama 的纯文本模型（零新依赖，经 stdlib urllib 调 REST API，
  与本地 VLM 同栈；默认模型 qwen2.5:7b，可用 --correct-model / 环境变量覆盖）。
- 用户提供 --context（语境/上下文）时，作为纠正依据（correction_source="context"）；
  否则 correction_source="local-model"（纯本地模型，离线、不出本机）。
- **联网检索纠正不在本 CLI 实现**：D16 明确「联网仅 agent 层按需触发（D2/D15 确认门）」，
  本模块绝不自动上云、不发起网络检索，符合「本地优先 · 默认不上云」红线。
- 优雅降级：未安装 ollama / 未拉取文本模型 / --no-correct → 跳过纠正，
  raw_text 照常保留、text 不变、corrected=None，并透明标注（D15/§4.7）。

组件反馈 P0-②「校正版逐字稿带时间码」实现要点：
- 当 result.segments 非空（音频/视频转录）时，采用 **逐段校正**（时间码天然对齐）：
  把各段标号后一次性送入模型，要求按段返回校正文本，段数/顺序不变；
  解析后回写 result.segments[i].text，并把原始段文本写入 seg.raw_text；
  result.text 同步为各段校正文本拼接（干净拼接，不含时间码）。
- 当无 segments（OCR/vision）时，维持整篇校正（原逻辑）。

组件反馈 P1-③「校正过程文件」实现要点：
- 逐段校正后，用 difflib 对比每段「原始 vs 校正」提取逐条改动，
  产出 result.correction_entries（[{start, raw, corrected, kind}]），
  供 output 层落盘「校正过程文件」；降级/无改动时不产出。

纠正版稿件契约（挂 ExtractResult.corrected，dict）：
  {
    "text": <纠正后文本，=ExtractResult.text>,
    "correction_notes": <改了哪些处的简要说明，无则 None>,
    "correction_source": "context" | "local-model",
    "model": <模型标签或 None>,
    "corrected_at": <ISO 时间戳>,
  }
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from modules.base import ExtractResult, Segment

DEFAULT_CORRECT_MODEL = "qwen2.5:7b"


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _model_available(host: str, model: str) -> bool:
    """ollama 可达且已拉取目标文本模型 → True；否则（含不可达）False。"""
    try:
        req = urllib.request.Request(host + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = {m.get("name", "") for m in data.get("models", [])}
        # 精确或前缀匹配（ollama 标签可能带 :latest 等）
        return any(m == model or m.startswith(model + ":") for m in models)
    except Exception:
        return False


def _generate(host: str, model: str, prompt: str, timeout: float = 300.0) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0},
    }
    req = urllib.request.Request(
        host + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("response") or "").strip()


def _build_prompt(raw_text: str, context: Optional[str]) -> str:
    lines = [
        "你是一个严谨的中文校对助手，负责把机器 OCR / 语音识别得到的原始文本完善为可读稿件。",
        "规则：",
        "1. 仅修正明显的识别错误：错别字、同音/近音词误识、数字与单位错乱、公式符号误识、标点错乱；",
        "2. 保留原意、专有名词、人名、地名、术语；不要改写文风，不要增删内容（除非明显是识别噪声）；",
        "3. 若文本无明显错误，原样返回，不要强行改动；",
        "4. 只输出一个 JSON 对象，不要任何额外说明：",
        '   {"corrected_text": "纠正后的完整文本", "correction_notes": "简要说明改了哪些处，无改动则空字符串"}',
    ]
    if context and context.strip():
        lines.append(f"\n【上下文/语境，供你判断】（来自用户提供的背景，可据此纠正歧义）：\n{context.strip()}")
    lines.append(f"\n【待纠正的原始识别文本】：\n{raw_text}")
    return "\n".join(lines)


def _build_segments_prompt(segments: List[Segment], context: Optional[str]) -> str:
    """逐段校正提示：把各段标号送入，要求按段返回校正文本（段数/顺序不变）。"""
    numbered = "\n".join(f"[{i}] {seg.text.strip()}" for i, seg in enumerate(segments))
    lines = [
        "你是一个严谨的中文校对助手，负责把机器语音识别得到的逐段文本逐段完善为可读稿件。",
        "下面按序号给出若干段识别文本，请逐段纠正（每段独立处理，段数不变、顺序不变）。",
        "规则：",
        "1. 仅修正明显的识别错误：错别字、同音/近音词误识、数字与单位错乱、标点错乱；",
        "2. 保留原意、专有名词、人名、地名、术语；不要改写文风，不要增删/合并/拆分段落；",
        "3. 某段无明显错误时，原样返回该段，不要强行改动；",
        "4. 只输出一个 JSON 对象，不要任何额外说明，格式：",
        f'   {{"segments": ["第0段校正后文本", "第1段校正后文本", ... 共 {len(segments)} 项]}}',
        "   注意 segments 数组长度必须与输入段数完全一致，顺序一一对应。",
    ]
    if context and context.strip():
        lines.append(f"\n【上下文/语境，供你判断】（来自用户提供的背景，可据此纠正歧义）：\n{context.strip()}")
    lines.append(f"\n【待逐段纠正的识别文本】：\n{numbered}")
    return "\n".join(lines)


def _parse_response(resp: str) -> Dict[str, Optional[str]]:
    """从模型回复中解析 corrected_text / correction_notes。失败则整体回退。"""
    try:
        start = resp.index("{")
        end = resp.rindex("}") + 1
        obj = json.loads(resp[start:end])
        text = (obj.get("corrected_text") or "").strip()
        notes = (obj.get("correction_notes") or "").strip() or None
        if text:
            return {"corrected_text": text, "correction_notes": notes}
    except Exception:
        pass
    # 回退：整段回复当作纠正文本
    if resp:
        return {"corrected_text": resp, "correction_notes": None}
    return {"corrected_text": None, "correction_notes": None}


def _parse_segments_response(resp: str, n: int) -> Optional[List[str]]:
    """从逐段校正回复中解析 segments 数组；长度不符则返回 None（回退整篇校正）。"""
    try:
        start = resp.index("{")
        end = resp.rindex("}") + 1
        obj = json.loads(resp[start:end])
        segs = obj.get("segments")
        if isinstance(segs, list) and len(segs) == n:
            return [str(s).strip() for s in segs]
    except Exception:
        pass
    return None


def _diff_kind(raw: str, corrected: str) -> str:
    """粗略归类改动类型（供校正过程文件展示）。"""
    if raw == corrected:
        return ""
    # 数字/单位差异 → 数字规范化（含中文数字：一二三…十百千万）
    digits = "".join(ch for ch in raw if ch.isdigit())
    digits_c = "".join(ch for ch in corrected if ch.isdigit())
    cn_num = set("零一二三四五六七八九十百千万两")
    has_cn = any(ch in cn_num for ch in raw + corrected)
    if (digits and digits != digits_c) or (has_cn and abs(len(raw) - len(corrected)) <= 3):
        return "数字/单位规范"
    # 同音/近音：长度接近、仅个别字不同 → 同音误识
    if abs(len(raw) - len(corrected)) <= 2:
        return "同音/形近误识"
    return "修订"


def _build_correction_entries(segments: List[Segment], corrected: List[str]) -> List[Dict[str, Any]]:
    """逐段对比原始 vs 校正，产出逐条改动清单（P1-③ 校正过程文件用）。

    注意：调用时 segments 的 text 可能已被回写为校正文本，原始文本在 seg.raw_text。
    故对比 seg.raw_text（原始）与 corrected[i]（校正后）。
    """
    entries: List[Dict[str, Any]] = []
    for seg, c in zip(segments, corrected):
        raw = (seg.raw_text if seg.raw_text is not None else seg.text).strip()
        c = c.strip()
        if raw == c:
            continue
        entries.append({
            "start": seg.start,
            "raw": raw,
            "corrected": c,
            "kind": _diff_kind(raw, c),
        })
    return entries


def _set_skipped(result: ExtractResult, status: str, model: Optional[str]) -> None:
    meta = dict(result.provider_meta or {})
    corr_meta: Dict[str, Any] = {"status": status, "source": None, "model": model}
    meta["correction"] = corr_meta
    result.provider_meta = meta


def maybe_correct(result: ExtractResult, options: Dict[str, Any]) -> ExtractResult:
    """就地完善 result：set raw_text（单一备查副本）+ 尝试生成纠正版稿件。

    不返回新对象（就地修改），便于各模块在 write_outputs 前调用。
    - result.text 变为纠正版稿件（无纠正时保持原始）；
    - result.raw_text 固定为原始识别文本（备查副本）；
    - result.corrected 为纠正元数据 dict，或 None（跳过时）；
    - 有 segments 时（音频/视频）：逐段校正 → 回写 result.segments[i].text、
      置 seg.raw_text，并产出 result.corrected_segments / result.correction_entries（P0-②/P1-③）。
    """
    raw = result.raw_text if result.raw_text else result.text
    result.raw_text = raw

    if options.get("no_correct"):
        _set_skipped(result, "skipped:disabled", None)
        return result

    model = options.get("correct_model") or os.environ.get("INFO_EXTRACT_CORRECT_MODEL") or DEFAULT_CORRECT_MODEL
    host = _ollama_host()
    if not _model_available(host, model):
        _set_skipped(result, "skipped:no-model", model)
        return result

    context = options.get("context")
    has_segments = bool(result.segments)
    try:
        if has_segments:
            resp = _generate(host, model, _build_segments_prompt(result.segments, context))
        else:
            resp = _generate(host, model, _build_prompt(raw, context))
    except urllib.error.URLError:
        _set_skipped(result, "skipped:error", model)
        return result
    except Exception:
        _set_skipped(result, "skipped:error", model)
        return result

    # 有 segments：解析逐段校正结果；失败回退整篇校正（不阻断）
    if has_segments:
        seg_texts = _parse_segments_response(resp, len(result.segments))
        if seg_texts is not None:
            # 回写各段校正文本，保留原始段文本（P0-②）
            for seg, c in zip(result.segments, seg_texts):
                if seg.raw_text is None:
                    seg.raw_text = seg.text
                seg.text = c
            result.corrected_segments = [
                Segment(start=s.start, end=s.end, text=s.text, words=s.words, raw_text=s.raw_text)
                for s in result.segments
            ]
            result.correction_entries = _build_correction_entries(result.segments, seg_texts)
            corrected_text = "\n".join(s.text.strip() for s in result.segments)
            notes = _summarize_notes(result.correction_entries)
        else:
            # 逐段解析失败 → 回退整篇校正（result.text 为整篇，segments 不动）
            parsed = _parse_response(resp)
            corrected_text = parsed.get("corrected_text")
            notes = parsed.get("correction_notes")
            if not corrected_text:
                _set_skipped(result, "skipped:empty", model)
                return result
            result.correction_entries = None
    else:
        parsed = _parse_response(resp)
        corrected_text = parsed.get("corrected_text")
        notes = parsed.get("correction_notes")
        if not corrected_text:
            _set_skipped(result, "skipped:empty", model)
            return result

    # 应用纠正
    result.text = corrected_text
    source = "context" if (context and context.strip()) else "local-model"
    result.corrected = {
        "text": corrected_text,
        "correction_notes": notes,
        "correction_source": source,
        "model": model,
        "corrected_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    meta = dict(result.provider_meta or {})
    meta["correction"] = {"status": "applied", "source": source, "model": model}
    result.provider_meta = meta
    return result


def _summarize_notes(entries: List[Dict[str, Any]]) -> Optional[str]:
    """把逐条改动清单压缩为一句简要说明（correction_notes）。"""
    if not entries:
        return None
    kinds = {}
    for e in entries:
        k = e.get("kind") or "修订"
        kinds[k] = kinds.get(k, 0) + 1
    parts = [f"{k} {n} 处" for k, n in kinds.items()]
    return "共纠正 " + str(len(entries)) + " 处：" + "、".join(parts)


__all__ = ["maybe_correct"]
