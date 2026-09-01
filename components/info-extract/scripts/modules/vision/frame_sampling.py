#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视频关键帧采样（审阅 F）。

设计（呼应方案 §3 阶段四 / 流程规范 §2.3）：
- **不朴素均匀采样**：改用**场景切换检测（scene detection）+ 关键帧去重**——
  以固定间隔解码视频帧，计算感知哈希（average hash），当相邻帧哈希距离超过
  阈值即判定场景切换，记录该帧为关键帧；近邻哈希过近的关键帧视为重复、跳过。
- **采样密度按 D7 资源自适应**：档位越高 → 关键帧上限越多、采样间隔越密
  （见 `tier.sampling_profile`）。减少 VLM 调用、提升关键帧覆盖。
- **含文字帧优先 OCR（可选）**：采样出的关键帧由调用方决定是否逐帧 OCR（协同），
  本模块只负责「抽帧」，OCR 协同在 vision_caption 的 analyze_video_frames 里完成。
- **零新依赖**：帧解码用 PyAV（自带 ffmpeg），写出用标准库 PNG（utils.image）。
- 容错：解码失败/无视频流 → 返回空列表，不静默报错。关键帧图默认落本地私有目录。
"""

from __future__ import annotations

import av
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional

from modules.vision.tier import sampling_profile
from utils.image import write_png_rgb


def _ahash(rgb: np.ndarray, size: int = 8) -> str:
    """average hash：灰度 → 8×8 下采样 → 二值化。返回二进制位串。"""
    gray = rgb.mean(axis=2).astype(np.float32)
    h, w = gray.shape
    sh, sw = max(1, h // size), max(1, w // size)
    small = gray[: sh * size, : sw * size].reshape(size, sh, size, sw).mean(axis=(1, 3))
    mean = small.mean()
    bits = (small > mean).flatten()
    return "".join("1" if b else "0" for b in bits)


def _hamming(a: str, b: str) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def sample_keyframes(
    video_path: str,
    *,
    out_dir,
    stem: str = "key",
    max_keyframes: Optional[int] = None,
    scene_threshold: int = 8,
    interval_sec: Optional[float] = None,
    dedup_threshold: int = 4,
) -> List[Dict]:
    """场景切换检测 + 关键帧去重采样，返回 [{timestamp, frame_path, phash}, ...]。

    - max_keyframes / interval_sec：不传则按 D7 档位自适应（sampling_profile）。
    - 关键帧 PNG 落 <out_dir>/<stem>_keyframes/。
    """
    prof = sampling_profile()
    if max_keyframes is None:
        max_keyframes = prof["max_keyframes"]
    if interval_sec is None:
        interval_sec = prof["interval_sec"]

    out_dir = Path(out_dir) / f"{stem}_keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)

    keyframes: List[Dict] = []
    try:
        container = av.open(video_path)
        if not container.streams.video:
            return []
        v = container.streams.video[0]
        acc = 0.0
        last_hash: Optional[str] = None
        last_key_hash: Optional[str] = None
        count = 0
        for frame in container.decode(v):
            if frame.pts is None:
                continue
            t = float(frame.pts * frame.time_base)
            if t < acc:
                continue
            acc += interval_sec
            try:
                rgb = frame.reformat(frame.width, frame.height, "rgb24").to_ndarray()
            except Exception:
                continue
            h = _ahash(rgb)
            # 场景切换：与上一帧哈希距离超阈值
            if last_hash is None or _hamming(h, last_hash) > scene_threshold:
                # 关键帧去重：与上一个关键帧过近则跳过
                if last_key_hash is None or _hamming(h, last_key_hash) > dedup_threshold:
                    ts = round(t, 2)
                    p = out_dir / f"{stem}_kf_{count:03d}_{int(ts * 100)}.png"
                    try:
                        write_png_rgb(p, rgb)
                        keyframes.append({"timestamp": ts, "frame_path": str(p), "phash": h})
                        last_key_hash = h
                        count += 1
                    except Exception:
                        pass
            last_hash = h
            if count >= max_keyframes:
                break
    except Exception:
        # 解码失败/格式不支持：返回已采部分（空也可），不静默抛错中断主流程
        return keyframes
    return keyframes


__all__ = ["sample_keyframes"]
