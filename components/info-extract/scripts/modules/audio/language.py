#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 语言 / 任务轻提示解析（D12·K）。

支持文件名或对话 hint（如「这是日文采访」「翻译成英文」），自动识别兜底；
多语识别顺序按 hint 优化（先按 hint 语言探查，失败再自动检测）。
"""

from __future__ import annotations

from typing import Optional

# 常见语言提示 → Whisper language code（覆盖方案 §1.2 外语/方言诉求）
LANG_HINTS = {
    "中文": "zh", "汉语": "zh", "普通话": "zh", "国语": "zh", "chinese": "zh", "zh": "zh", "zh-cn": "zh",
    "英文": "en", "英语": "en", "english": "en", "en": "en",
    "日文": "ja", "日语": "ja", "日本语": "ja", "japanese": "ja", "ja": "ja",
    "韩文": "ko", "韩语": "ko", "朝鲜语": "ko", "korean": "ko", "ko": "ko",
    "法文": "fr", "法语": "fr", "french": "fr", "fr": "fr",
    "德文": "de", "德语": "de", "german": "de", "de": "de",
    "西班牙文": "es", "西班牙语": "es", "spanish": "es", "es": "es",
    "俄文": "ru", "俄语": "ru", "russian": "ru", "ru": "ru",
    "葡文": "pt", "葡语": "pt", "葡萄牙语": "pt", "portuguese": "pt", "pt": "pt",
    "意大利文": "it", "意大利语": "it", "italian": "it", "it": "it",
    "阿拉伯文": "ar", "阿拉伯语": "ar", "arabic": "ar", "ar": "ar",
    "印地文": "hi", "印地语": "hi", "hindi": "hi", "hi": "hi",
    "越南文": "vi", "越南语": "vi", "vietnamese": "vi", "vi": "vi",
    "泰文": "th", "泰语": "th", "thai": "th", "th": "th",
    "粤语": "yue", "cantonese": "yue", "yue": "yue",
}


def parse_language_hint(text: Optional[str]) -> Optional[str]:
    """从任意文本（文件名/对话）解析语言 code；无匹配返回 None（自动检测）。"""
    if not text:
        return None
    low = text.lower()
    for key, code in LANG_HINTS.items():
        if key.lower() in low:
            return code
    return None


def parse_task_hint(text: Optional[str]) -> Optional[str]:
    """解析任务类型：translate（翻译为目标语）/ transcribe（原语转录）；无匹配返回 None。"""
    if not text:
        return None
    t = text.lower()
    if any(k in t for k in ["翻译", "译", "translate", "translation"]):
        return "translate"
    if any(k in t for k in ["转录", "转写", "听写", "transcribe", "transcription", "asr"]):
        return "transcribe"
    return None


__all__ = ["LANG_HINTS", "parse_language_hint", "parse_task_hint"]
