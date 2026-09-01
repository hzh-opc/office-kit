#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视觉理解 Mock Provider（仅供测试，不进入 PROVIDERS 注册）。

让阶段四的全部编排逻辑（路由 → OCR 协同 → VLM caption → 双通道输出 → 缓存 → 批量
聚合 → D13 帧填充 → provider_meta 透明回显）在不依赖 ollama / 真实 VLM 推理的前提下
可完整验证（与阶段一/二/三的 mock 范式一致）。
"""

from __future__ import annotations

from typing import Dict, Tuple

from modules.vision.providers.base import IVisionProvider


class MockVLMProvider(IVisionProvider):
    name = "mock-vlm"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, caption_text: str = "MOCK_VISION_CAPTION", *, available: bool = True, tier_name: str = "标准档"):
        self._caption = caption_text
        self._available = available
        self._tier_name = tier_name

    def available(self) -> bool:
        return self._available

    @property
    def tier(self) -> Dict:
        return {"tier": 1, "name": self._tier_name, "ollama_tag": "mock"}

    def caption(self, image, prompt: str, **opts) -> Tuple[str, Dict]:
        # 把 prompt 长度编码进返回，便于测试断言「提示词已带上 OCR 协同文字」
        return self._caption, {"model": "mock", "engine": "mock", "prompt_len": len(prompt)}

    def meta(self) -> dict:
        m = super().meta()
        m["model"] = "mock"
        m["tier"] = self._tier_name
        return m


__all__ = ["MockVLMProvider"]
