#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 默认本地 OCR Provider（rapidocr + onnxruntime，PP-OCRv6）。

完全离线：模型随 wheel 捆绑（rapidocr_onnxruntime 包内 models 目录），数据不出本机、
零部署零协议风险（DESEN 已在 v2.4 起实装并跨平台验证，方案 §3 阶段三 / 附录选型依据）。

OCR 文本属「未脱敏副本」，上云前须经 DESEN 脱敏闸门（§4.4），原始图绝不整份留云。
已知弱项（DESEN 实测）：手写体 / 模糊图质量受限；单行极端宽高比图识别率低——这些由
置信度门控（审阅 D）触发上云提质提示（D2），不对手写/模糊一刀切。
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple

from modules.base import InfoExtractError
from .base import IOCRProvider

# rapidocr 有两代包名：rapidocr（3.x 统一包，含 onnxruntime 后端）/ rapidocr_onnxruntime（旧 wheel），做兼容探测。
try:
    from rapidocr import RapidOCR
except Exception:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        RapidOCR = None

_ENGINE = None  # 引擎单例（模型加载较重，惰性实例化 + 跨调用缓存）


class RapidOcrProvider(IOCRProvider):
    name = "rapidocr"
    source_layer = "local_builtin"
    cost = "local"

    def available(self) -> bool:
        return RapidOCR is not None

    def _get_engine(self):
        global _ENGINE
        if _ENGINE is None:
            if not self.available():
                raise InfoExtractError(
                    "未找到 rapidocr 依赖。请运行技能目录下 install.py / install.sh 安装 rapidocr、onnxruntime、pypdfium2、pillow。",
                    recoverable=True,
                )
            _ENGINE = RapidOCR()
        return _ENGINE

    def ocr(self, image: np.ndarray, **opts) -> Tuple[List[Dict], Dict]:
        engine = self._get_engine()
        # rapidocr 内部以 cv2 读取，期望 BGR；本技能统一用 RGB 输入，故翻转通道后传入。
        if image.ndim == 3 and image.shape[2] == 3:
            img_bgr = image[..., ::-1].copy()
        else:
            img_bgr = image
        try:
            result = engine(img_bgr)
        except Exception as e:  # 模型缺失 / 推理异常 → 降级提示，不静默失败
            raise InfoExtractError(f"rapidocr 推理失败：{e}", recoverable=True)

        boxes: List[Dict] = []
        if result is None:
            pass
        elif hasattr(result, "boxes"):
            # rapidocr 3.x：返回 RapidOCROutput（boxes 为 ndarray(N,4,2)，txts/scores 为 tuple）
            _boxes_arr = result.boxes
            _txts = result.txts or ()
            _scores = result.scores or ()
            for i, text in enumerate(_txts):
                box = _boxes_arr[i].tolist() if hasattr(_boxes_arr, "tolist") else _boxes_arr[i]
                boxes.append({"box": box, "text": text, "score": float(_scores[i])})
        else:
            # rapidocr_onnxruntime（旧）：返回 (boxes, txts, scores) 三元组
            boxes_list, txts, scores = result
            for box, text, score in zip(boxes_list or (), txts or (), scores or ()):
                boxes.append({"box": box, "text": text, "score": float(score)})

        scores = [b["score"] for b in boxes] or []
        avg_conf = round(float(np.mean(scores)), 3) if scores else None
        info = {"num_boxes": len(boxes), "avg_confidence": avg_conf, "engine": "rapidocr"}
        return boxes, info

    def meta(self) -> dict:
        m = super().meta()
        m["model"] = "PP-OCRv6 (rapidocr)"  # 实际模型版本以所装 wheel 为准
        return m


__all__ = ["RapidOcrProvider"]
