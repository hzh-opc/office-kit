#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 默认本地视觉理解 Provider（ollama + Qwen2.5-VL，权重本地、零新依赖）。

设计（呼应方案 §3 阶段四 / 资源评估 §4 / D7 自适应）：
- **本地优先**：通过 ollama 在本地运行多模态 VLM（Qwen2.5-VL 系列），权重本地存放、
  数据不出本机，与「本地优先 · 默认不上云」红线一致。
- **零新依赖**：经 ollama 的 HTTP REST API（stdlib `urllib`，`http://localhost:11434`）
  发送图片 base64 + 提示词，不引入 `ollama` Python 包或额外网络库。
- **档位自适应（D7）**：模型标签由 `tier.current_tier()` 决定——安装时按硬件选最优档、
  运行时复探可下调、用户可用 `--vision-tier` / 环境变量覆盖。
- **可用判定（available）**：探测 `ollama` 二进制或本地服务可达；缺失即降级、不静默失败。
- **调用失败**：服务未启动 / 模型未拉取 / 推理异常 → 抛出 `InfoExtractError(recoverable)`，
  由 VisionModule 捕获并给出「上云提质（D2）」提示。

注：图像以 base64 经 API 发送；VLM 是「最重组件」，低端设备可能超时/显存不足——
此时由 D7 下调档位或 D2 交互式云端降级（§3 / 资源评估 §8）。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

from modules.base import InfoExtractError
from modules.vision.providers.base import IVisionProvider
from modules.vision.tier import current_tier


class LocalVLMProvider(IVisionProvider):
    name = "local-vlm"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, tier_override=None):
        # tier_override：手动指定档位（int/str/tag），优先于自动判定（D7 用户覆盖）
        self._tier_override = tier_override

    # ---- 档位（D7）----
    @property
    def tier(self) -> Dict:
        return current_tier(self._tier_override)

    def _model(self) -> str:
        return self.tier.get("ollama_tag", "qwen2.5vl:7b")

    # ---- 可用判定（D15 优雅降级）----
    def available(self) -> bool:
        if shutil.which("ollama") is not None:
            return True
        return self._ollama_reachable()

    @staticmethod
    def _ollama_reachable(host: str | None = None) -> bool:
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            req = urllib.request.Request(host + "/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ---- 图像编码 ----
    @staticmethod
    def _encode_images(image) -> List[str]:
        if isinstance(image, (list, tuple)):
            return [LocalVLMProvider._enc_one(x) for x in image]
        return [LocalVLMProvider._enc_one(image)]

    @staticmethod
    def _enc_one(x) -> str:
        if isinstance(x, (str, Path)):
            with open(x, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        # numpy ndarray（RGB H×W×3 uint8）：经 stdlib PNG 字节编码
        try:
            import numpy as np
            from utils.image import rgb_to_png_bytes

            arr = np.asarray(x)
            return base64.b64encode(rgb_to_png_bytes(arr)).decode("utf-8")
        except Exception as e:
            raise InfoExtractError(f"不支持的图像输入类型：{e}", recoverable=False)

    # ---- 核心：视觉描述 ----
    def caption(self, image, prompt: str, **opts) -> Tuple[str, Dict]:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        model = self._model()
        try:
            imgs = self._encode_images(image)
        except InfoExtractError:
            raise
        except Exception as e:
            raise InfoExtractError(f"图像编码失败：{e}", recoverable=True)

        payload = {
            "model": model,
            "prompt": prompt,
            "images": imgs,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        try:
            req = urllib.request.Request(
                host + "/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise InfoExtractError(
                f"本地 VLM(ollama) 服务不可达：{e}。请先启动 ollama 并拉取模型 "
                f"`{model}`（如 `ollama pull {model}`），或改用云端提质（D2/§4.4）。",
                recoverable=True,
            )
        except Exception as e:
            raise InfoExtractError(
                f"本地 VLM(ollama) 调用失败：{e}（请确认 ollama 已启动且已拉取模型 `{model}`）",
                recoverable=True,
            )

        text = (data.get("response") or "").strip()
        info = {"model": model, "engine": "ollama", "done": data.get("done", True)}
        return text, info

    def meta(self) -> dict:
        m = super().meta()
        m["model"] = self._model()
        m["tier"] = self.tier.get("name")
        if self.tier.get("_downgraded"):
            m["downgraded_from_tier"] = self.tier.get("_downgraded_from")
        return m


__all__ = ["LocalVLMProvider"]
