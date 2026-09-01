#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 纠正版稿件生成（D16 交付物范式）。

职责（呼应方案 §3.6 / 流程规范 §1 ⑦.5 / D16）：
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
from typing import Any, Dict, Optional

from modules.base import ExtractResult

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


def maybe_correct(result: ExtractResult, options: Dict[str, Any]) -> ExtractResult:
    """就地完善 result：set raw_text（单一备查副本）+ 尝试生成纠正版稿件。

    不返回新对象（就地修改），便于各模块在 write_outputs 前调用。
    - result.text 变为纠正版稿件（无纠正时保持原始）；
    - result.raw_text 固定为原始识别文本（备查副本）；
    - result.corrected 为纠正元数据 dict，或 None（跳过时）。
    """
    raw = result.raw_text if result.raw_text else result.text
    result.raw_text = raw

    # 透明标注（D15/§4.7 同构）
    meta = dict(result.provider_meta or {})
    corr_meta: Dict[str, Any] = {"status": "skipped", "source": None, "model": None}

    if options.get("no_correct"):
        corr_meta["status"] = "skipped:disabled"
        meta["correction"] = corr_meta
        result.provider_meta = meta
        return result

    model = options.get("correct_model") or os.environ.get("INFO_EXTRACT_CORRECT_MODEL") or DEFAULT_CORRECT_MODEL
    host = _ollama_host()
    if not _model_available(host, model):
        corr_meta["status"] = "skipped:no-model"
        corr_meta["model"] = model
        meta["correction"] = corr_meta
        result.provider_meta = meta
        return result

    context = options.get("context")
    try:
        resp = _generate(host, model, _build_prompt(raw, context))
    except urllib.error.URLError:
        corr_meta["status"] = "skipped:error"
        corr_meta["model"] = model
        meta["correction"] = corr_meta
        result.provider_meta = meta
        return result
    except Exception:
        corr_meta["status"] = "skipped:error"
        corr_meta["model"] = model
        meta["correction"] = corr_meta
        result.provider_meta = meta
        return result

    parsed = _parse_response(resp)
    corrected_text = parsed.get("corrected_text")
    if not corrected_text:
        corr_meta["status"] = "skipped:empty"
        corr_meta["model"] = model
        meta["correction"] = corr_meta
        result.provider_meta = meta
        return result

    # 应用纠正
    result.text = corrected_text
    source = "context" if (context and context.strip()) else "local-model"
    result.corrected = {
        "text": corrected_text,
        "correction_notes": parsed.get("correction_notes"),
        "correction_source": source,
        "model": model,
        "corrected_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    corr_meta["status"] = "applied"
    corr_meta["source"] = source
    corr_meta["model"] = model
    meta["correction"] = corr_meta
    result.provider_meta = meta
    return result


__all__ = ["maybe_correct"]
