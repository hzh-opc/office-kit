#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR Provider 包。"""

from .base import IOCRProvider
from .rapid_ocr import RapidOcrProvider

# D15 注册：默认优先 rapidocr（本地内置，离线）；
# 后续阶段按 §0.6 接本地增强（公式 OCR / 版面分析）/ 云端 / 外部技能 / 连接器。
PROVIDERS = [RapidOcrProvider]

__all__ = [
    "IOCRProvider",
    "RapidOcrProvider",
    "PROVIDERS",
]
