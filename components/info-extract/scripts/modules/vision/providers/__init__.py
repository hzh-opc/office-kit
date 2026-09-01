#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉理解 Provider 包（D15 可插拔架构）。

默认本地 provider = LocalVLMProvider（ollama + Qwen2.5-VL，本地优先、零新依赖）。
后续阶段按 §0.6 接入：本地增强（公式 OCR / 版面分析 / VLM 拓扑重建，D14）、云端、
外部技能、连接器。
"""

from __future__ import annotations

from .base import IVisionProvider
from .local_vlm import LocalVLMProvider

# 注册表：默认优先 local-vlm（本地内置，离线）；其余来源层后续按 §0.6 接入。
PROVIDERS = [LocalVLMProvider]

__all__ = [
    "IVisionProvider",
    "LocalVLMProvider",
    "PROVIDERS",
]
