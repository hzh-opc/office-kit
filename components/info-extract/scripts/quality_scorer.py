#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 质量评分器（D15 自动升级依据）。

基于结果置信度/不确定项给出质量档与升级建议，驱动「本地质量不足 → 自动升级 provider」策略。
阶段一：音频以 Whisper 词级概率均值作 confidence；OCR/视觉阶段接入各自置信度口径（§3.6）。
"""

from __future__ import annotations

from typing import Dict

from modules.base import ExtractResult


def score(result: ExtractResult) -> Dict[str, str]:
    """返回 {quality, suggestion}。quality ∈ high|medium|low|unknown。"""
    if result.source == "transcript":
        return _score_transcript(result)
    # OCR / 视觉阶段：以 confidence 阈值通用判断
    conf = result.confidence
    if conf is None:
        return {"quality": "unknown", "suggestion": "无置信度信息，请人工核对关键字段"}
    if conf < 0.5:
        return {"quality": "low", "suggestion": "置信度偏低，建议升级模型/上云提质并核对关键字段"}
    if conf < 0.85:
        return {"quality": "medium", "suggestion": "置信度中等，建议核对专有名词/数字"}
    return {"quality": "high", "suggestion": ""}


def _score_transcript(result: ExtractResult) -> Dict[str, str]:
    conf = result.confidence
    if conf is None:
        return {"quality": "unknown", "suggestion": "无词级置信度，请人工核对"}
    if conf < 0.5:
        return {
            "quality": "low",
            "suggestion": "置信度偏低，建议升级 Whisper 模型（medium+）或核对关键字段",
        }
    if conf < 0.75:
        return {"quality": "medium", "suggestion": "置信度中等，建议核对专有名词/数字/人名"}
    return {"quality": "high", "suggestion": ""}


__all__ = ["score"]
