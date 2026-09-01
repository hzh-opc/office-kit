#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · OCR Provider 统一接口（D15 可插拔架构）。

每个能力域的底层引擎是可替换 Provider。OCR 默认 Provider = 本地 rapidocr + onnxruntime
（PP-OCRv6，模型随 wheel 捆绑、完全离线、数据不出本机）。可经 provider_registry 切换为：
- 本地增强（公式 OCR / 版面分析，D14）
- 云端可选（D2 交互范式、上云前脱敏闸门）
- 外部技能（skill_bridge 发现的 document_text / 未来抽取技能）
- 连接器（已连接的 OCR 类 connector，运行时检测、未连接则跳过）

所有 Provider 实现 IOCRProvider，统一签名，主入口不感知具体实现。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


class IOCRProvider:
    """OCR Provider 接口。

    - name / source_layer：供 provider_meta 透明回显（D15 / 流程规范 §4.7）。
    - cost：local / cloud（是否上云，§4.7 透明展示）。
    - available()：运行前探测依赖是否就绪，缺失即降级、不静默失败。
    - ocr()：输入 RGB ndarray → 返回 (boxes, info)；boxes 含逐框 text/score/box。
    """

    name: str = ""
    source_layer: str = "local_builtin"  # local_builtin / local_enhanced / cloud / skill / connector
    cost: str = "local"  # local / cloud（是否上云，D4.7 透明展示）

    def available(self) -> bool:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def ocr(
        self,
        image,  # H×W×3 uint8 (RGB)
        **opts,
    ) -> Tuple[List[Dict], Dict]:  # pragma: no cover - 由子类实现
        """返回 (boxes, info)。

        boxes: [{box: [[x,y], ...], text: str, score: float}, ...]（按阅读顺序）
        info:  {num_boxes, avg_confidence, engine, ...}
        """
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


__all__ = ["IOCRProvider"]
