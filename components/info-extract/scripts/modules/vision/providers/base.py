#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视觉理解 Provider 统一接口（D15 可插拔架构）。

每个能力域的底层引擎是可替换 Provider。视觉理解默认 Provider = 本地多模态 VLM
（ollama 系 Qwen2.5-VL / Llama3.2-Vision，权重本地存放、数据不出本机）。可经
provider_registry 切换为：
- 本地增强（D14：公式 OCR / 版面分析 / VLM 拓扑重建）
- 云端可选（D2 交互范式、上云前脱敏闸门）
- 外部技能（skill_bridge 发现的未来抽取技能）
- 连接器（已连接的视觉类 connector，运行时检测、未连接则跳过）

所有 Provider 实现 IVisionProvider，统一签名，主入口不感知具体实现。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


class IVisionProvider:
    """视觉理解 Provider 接口。

    - name / source_layer：供 provider_meta 透明回显（D15 / 流程规范 §4.7）。
    - cost：local / cloud（是否上云，§4.7 透明展示）。
    - available()：运行前探测依赖（如 ollama 二进制 / 服务）是否就绪，缺失即降级、不静默失败。
    - caption()：输入图像（路径 / ndarray / 列表）+ 任务提示 → 返回 (描述文本, info)。
    """

    name: str = ""
    source_layer: str = "local_builtin"  # local_builtin / local_enhanced / cloud / skill / connector
    cost: str = "local"  # local / cloud（是否上云，D4.7 透明展示）

    def available(self) -> bool:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def caption(
        self,
        image,  # str/Path（图片路径）或 np.ndarray(H×W×3) 或 列表（多图）
        prompt: str,
        **opts,
    ) -> Tuple[str, Dict]:  # pragma: no cover - 由子类实现
        """返回 (caption_text, info_dict)。

        image：单张图片路径 / RGB ndarray，或上述组成的列表（多图对话）。
        prompt：任务提示（含用户任务 + OCR 协同文字等，由上层 build_vision_prompt 构造）。
        info：{model, engine, ...}
        """
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


__all__ = ["IVisionProvider"]
