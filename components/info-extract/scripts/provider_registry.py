#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · Provider 注册表（D15 可插拔架构核心）。

按能力域登记可替换 Provider，主入口只按类型取 provider，不感知具体实现：
- 默认：返回第一个「可用」的 Provider（列表顺序即优先级 → 本地内置①优先）。
- 显式指定：用户指定 provider 名称优先于自动判定。
- 全不可用：返回列表中第一个（available()=False），由调用方给出降级提示，不静默失败。
后续阶段（OCR / 视觉 / 文档抽取 / 在线视频）按 §0.6 来源分层接入本地增强/云端/技能/连接器。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from modules.base import InfoExtractError, SourceType

# 注意：为避免与 modules.audio.transcribe（其又 import 本模块）形成循环依赖，
# 这里不在此模块加载时 import modules.audio，而是在首次调用时惰性构建注册表。
_REGISTRY: Optional[Dict] = None


def _build_registry() -> Dict:
    from modules.audio.providers import PROVIDERS as AUDIO_PROVIDERS
    from modules.ocr.providers import PROVIDERS as OCR_PROVIDERS
    from modules.vision.providers import PROVIDERS as VISION_PROVIDERS
    from modules.video_online.providers import PROVIDERS as VIDEO_ONLINE_PROVIDERS
    from modules.video_online.providers import ENUM_PROVIDERS as VIDEO_ONLINE_ENUM_PROVIDERS
    from modules.recorder import FfmpegRecorderProvider  # 阶段六 直播/设备录制（ffmpeg 后端）

    RECORDER_PROVIDERS = [FfmpegRecorderProvider]

    return {
        SourceType.TRANSCRIPT: AUDIO_PROVIDERS,
        # 阶段二视频文案复用同一套本地 Whisper provider（抽音轨后转录）
        SourceType.VIDEO: AUDIO_PROVIDERS,
        # 阶段三 OCR（rapidocr + onnxruntime，PP-OCRv6，本地内置、离线）
        SourceType.OCR: OCR_PROVIDERS,
        # 阶段四 画面解读（本地 VLM，ollama + Qwen2.5-VL，档位自适应 D7，零新依赖）
        SourceType.VISION: VISION_PROVIDERS,
        # 阶段五 在线/加密视频（yt-dlp 本地下载 + 浏览器捕获回退，D3 不留存副本）
        SourceType.VIDEO_ONLINE: VIDEO_ONLINE_PROVIDERS,
        # 阶段五增强（方案 B）：账号/合集枚举（抖音/小红书/B站 等），枚举出视频 URL 后逐条走下载管线
        SourceType.VIDEO_ONLINE_ENUM: VIDEO_ONLINE_ENUM_PROVIDERS,
        # 阶段六 直播录制（P0）/ 设备摄取（P1）：ffmpeg 录制后端（D3 不留存 / 边录边转 / 增强 A–E）
        SourceType.LIVE: RECORDER_PROVIDERS,
        SourceType.CAPTURE: RECORDER_PROVIDERS,
    }


def _registry() -> Dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def register(capability: str, provider_cls, priority: int = 99) -> None:
    """扩展接入新 Provider（阶段落地时调用）。priority 越小越优先。

    与 `_build_registry` 的静态列表一致：列表顺序即优先级。priority 默认 99 追加末尾；
    显式 < 99 时按升序插入到对应位置（现有内置 provider 未声明 priority，视为 99）。
    """
    reg = _registry()
    lst: List = reg.setdefault(capability, [])
    # 同名去重（幂等注册）
    name = getattr(provider_cls, "name", None)
    if any(getattr(c, "name", None) == name for c in lst):
        return
    idx = 0
    while idx < len(lst) and getattr(lst[idx], "priority", 99) <= priority:
        idx += 1
    lst.insert(idx, provider_cls)


def get_provider(capability: str, name: Optional[str] = None):
    """取 provider 实例。

    name=None → 默认第一个可用的（本地优先）；
    name 指定 → 精确匹配；无匹配返回 None（调用方降级）。
    """
    providers = _registry().get(capability, [])
    if not providers:
        return None
    # "auto" / 空 / None 均视为「未指定」→ 返回第一个可用的（本地优先）
    if name and name != "auto":
        for p in providers:
            if p.name == name:
                return p()
        return None
    for p in providers:
        inst = p()
        if inst.available():
            return inst
    # 全不可用：返回首个，供调用方给降级提示
    return providers[0]()


def available_providers(capability: str) -> List[dict]:
    """列出某能力域所有已注册 provider 及其可用性（供 --check / 透明回显）。"""
    out = []
    for p in _registry().get(capability, []):
        inst = p()
        out.append({"name": inst.name, "available": inst.available(), "meta": inst.meta()})
    return out


__all__ = ["register", "get_provider", "available_providers"]
