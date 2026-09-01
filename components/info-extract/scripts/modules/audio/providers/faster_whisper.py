#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · Faster-Whisper Provider（默认本地转录引擎，D15 本地内置①）。

- 纯 Python/Cross（CTranslate2），跨平台；默认 small 模型（CPU 近实时、WER~7%，见资源评估 §1）。
- 完全离线、数据不出本机（D2/D4 本地优先红线）。
- 依赖惰性 import：仅 transcribe() 内 import faster_whisper，未安装时 available()=False，
  router 据此降级提示，不静默失败。
- 默认开启 vad_filter + word_timestamps，输出带字级时间戳与置信度（供 §3.6 契约 confidence）。
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from modules.audio.providers.base import ITranscriptProvider
from modules.base import InfoExtractError, Segment


class FasterWhisperProvider(ITranscriptProvider):
    name = "faster-whisper"
    source_layer = "local_builtin"
    cost = "local"
    # 模型规模策略（资源评估 §1）：默认 small；噪声明/方言可升 medium+；large-v3 需独显
    DEFAULT_MODEL = "small"

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        task: Optional[str] = None,
        model_size: str = DEFAULT_MODEL,
        **opts,
    ) -> Tuple[List[Segment], dict]:
        from faster_whisper import WhisperModel

        device = opts.get("device", "auto")
        compute_type = opts.get("compute_type", "int8")
        cpu_threads = opts.get("cpu_threads", min(8, (os.cpu_count() or 4)))
        try:
            model = WhisperModel(
                model_size, device=device, compute_type=compute_type, cpu_threads=cpu_threads
            )
            segments_gen, info = model.transcribe(
                audio,
                language=language,
                task=task or "transcribe",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                word_timestamps=True,
                condition_on_previous_text=True,
            )
            segments: List[Segment] = []
            for seg in segments_gen:
                words = [
                    {
                        "word": w.word,
                        "start": float(w.start),
                        "end": float(w.end),
                        "prob": float(w.probability),
                    }
                    for w in (seg.words or [])
                ]
                segments.append(
                    Segment(start=float(seg.start), end=float(seg.end), text=seg.text, words=words)
                )
        except Exception as e:  # 模型下载失败 / 加载失败 / 推理异常
            raise InfoExtractError(
                f"Whisper 转录失败：{e}",
                recoverable=True,
                hint=(
                    "首次运行需从 HuggingFace 下载模型（默认 small ~466MB），请确认网络/代理可访问 hf.co；"
                    "或改用 whisper.cpp 离线模型（设置 WHISPER_CPP_BIN 与 WHISPER_CPP_MODEL 环境变量）。"
                ),
            ) from e
        info_dict = {
            "detected_language": getattr(info, "language", language or "unknown"),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 3),
            "duration": round(float(getattr(info, "duration", 0.0)), 3),
            "model_size": model_size,
        }
        return segments, info_dict


# 模型规模提示（供 router 在用户未指定时给出默认建议文案）
MODEL_HINTS = {
    "tiny": "极低资源/边缘，WER~12%",
    "base": "平衡首选，WER~10%",
    "small": "推荐默认（CPU 近实时，WER~7%）",
    "medium": "高精度/噪声明，WER~5%",
    "large-v3": "最强，需 ≥10GB 显存，WER~3.5%",
    "turbo": "速度/质量平衡，WER~3.7%",
}

__all__ = ["FasterWhisperProvider", "MODEL_HINTS"]
