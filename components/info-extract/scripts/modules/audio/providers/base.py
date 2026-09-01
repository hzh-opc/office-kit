#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 转录 Provider 统一接口（D15 可插拔架构）。

每个能力域的底层引擎是可替换 Provider。音频转录默认 Provider = 本地 Whisper
（faster-whisper，离线、数据不出本机）。可经 provider_registry 切换为：
- 本地内置其他 ASR（whisper.cpp）
- 本地增强 / 云端可选 / 外部技能 / 连接器（后续阶段按 §0.6 接入）
所有 Provider 实现 ITranscriptProvider，统一签名，主入口不感知具体实现。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from modules.base import Segment


class ITranscriptProvider:
    """转录 Provider 接口。

    - name / source_layer：供 provider_meta 透明回显（D15 / 流程规范 §4.7）。
    - available()：运行前探测依赖/二进制是否就绪，缺失即降级、不静默失败。
    - transcribe()：返回 (segments, info_dict)；info 含 detected_language / duration 等。
    """

    name: str = ""
    source_layer: str = "local_builtin"  # local_builtin / local_enhanced / cloud / skill / connector
    cost: str = "local"  # local / cloud（是否上云，D4.7 透明展示）

    def available(self) -> bool:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def transcribe(
        self,
        audio,  # 路径或 float32 16k ndarray
        language: Optional[str] = None,
        task: Optional[str] = None,
        model_size: str = "small",
        **opts,
    ) -> Tuple[List[Segment], dict]:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


__all__ = ["ITranscriptProvider"]
