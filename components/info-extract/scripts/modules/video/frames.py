#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视频讲解段关联帧抽取（D13）。

设计（呼应方案 §3 阶段二 D13 / 流程规范 §2.3）：
- 规则信号：转录含「如图 / 见下图 / 这张图 / 这个流程图 / 如图所示 …」等指代词（中英），
  即判为「在讲解画面」的段落。
  （注：方案 D13 另含「文案与同帧视觉描述语义重合度高」判定，该路径需视觉栈，留待阶段四；
   本阶段先落地规则信号检测，并在 referenced_frame 中预留 vision_caption / ocr_on_frame 字段。）
- 对讲解段抽取对应帧：取该段中点时间戳 → PyAV seek 解码 → 转 rgb24 → 标准库 zlib 写出 PNG。
  **零新依赖**：复用 PyAV 解码 + 标准库 zlib 写 PNG，规避本机 ffmpeg 图像编码器（mjpeg/png）受限问题。
- 帧图默认落本地 `<out_dir>/<stem>_frames/`，不自动上云（D13 / §4.4 隐私闭环）；敏感内容走脱敏闸门。
- 视觉描述 / 帧上 OCR：阶段四视觉栈填充，当前置 None 并标注待补。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import av
import numpy as np

from utils.image import write_png_rgb

# 指代词（中英）：命中即视为「在讲解画面」
DEICTIC_PATTERNS_ZH = [
    "如图", "见图", "见下图", "见上图", "如图所示", "如下图", "上图", "下图",
    "这张图", "这个图", "此图", "该图", "这张表", "这个表", "此表", "该表",
    "图中", "图里", "图内", "表里", "流程图", "结构图", "架构图", "示意如下",
    "看这张", "看图中", "参照图", "参考图", "图中所示", "框图", "配图", "附图",
]
DEICTIC_PATTERNS_EN = [
    "as shown", "this figure", "this chart", "this picture", "see the figure",
    "see the chart", "see the picture", "pictured above", "as illustrated",
    "the diagram", "the figure above", "in the figure", "in this image",
    "as depicted", "shown below", "shown above",
]
_DEICTIC_RE = re.compile(
    "|".join(re.escape(p) for p in DEICTIC_PATTERNS_ZH + DEICTIC_PATTERNS_EN),
    re.IGNORECASE,
)


def is_visual_explanation(text: str) -> bool:
    """规则信号：转录文本是否命中讲解画面的指代词。"""
    if not text:
        return False
    return bool(_DEICTIC_RE.search(text))


def _write_png(path: str, rgb: np.ndarray) -> None:
    """标准库-only PNG 写出（不依赖 ffmpeg 图像编码器 / Pillow）。rgb: H×W×3 uint8。

    复用 utils.image.write_png_rgb（集中实现，避免重复）。
    """
    write_png_rgb(path, rgb)


def extract_frame_rgb(video_path: str, timestamp: float) -> Optional[np.ndarray]:
    """在 timestamp（秒）处抽取一帧并返回 RGB ndarray（H×W×3 uint8）；失败返回 None。

    供视觉栈（阶段四）对 D13 讲解段帧 / 关键帧做 VLM 解读时复用，避免重复解码逻辑。
    """
    try:
        container = av.open(video_path)
        if not container.streams.video:
            return None
        v = container.streams.video[0]
        frame = None
        try:
            container.seek(int(timestamp / float(v.time_base)), stream=v)
            frame = next(container.decode(v), None)
        except Exception:
            frame = None
        if frame is None:
            # 兜底：从头顺序解码到首个 >= timestamp 的帧
            container = av.open(video_path)
            v = container.streams.video[0]
            for fr in container.decode(v):
                ft = float(fr.pts * v.time_base) if fr.pts is not None else None
                if ft is not None and ft >= timestamp:
                    frame = fr
                    break
        if frame is None:
            return None
        return frame.reformat(frame.width, frame.height, "rgb24").to_ndarray()
    except Exception:
        return None


def extract_frame(video_path: str, timestamp: float, out_path: str) -> bool:
    """在 timestamp（秒）处抽取一帧并写为 PNG。成功返回 True。

    策略：先 seek 到最近关键帧后解码取首帧；失败则从头顺序解码到首个 ≥ timestamp 的帧兜底。
    """
    try:
        container = av.open(video_path)
        if not container.streams.video:
            return False
        v = container.streams.video[0]
        frame = None
        try:
            container.seek(int(timestamp / float(v.time_base)), stream=v)
            frame = next(container.decode(v), None)
        except Exception:
            frame = None
        if frame is None:
            # 兜底：从头顺序解码到首个 >= timestamp 的帧
            container = av.open(video_path)
            v = container.streams.video[0]
            for fr in container.decode(v):
                ft = float(fr.pts * v.time_base) if fr.pts is not None else None
                if ft is not None and ft >= timestamp:
                    frame = fr
                    break
        if frame is None:
            return False
        rgb = frame.reformat(frame.width, frame.height, "rgb24").to_ndarray()
        _write_png(out_path, rgb)
        return True
    except Exception:
        return False


def _ts_label(ts: float) -> str:
    return f"{ts:07.2f}".replace(".", "_")


def extract_referenced_frames(
    video_path: str,
    segments,
    out_dir: str,
    stem: str,
    *,
    enabled: bool = True,
) -> Optional[Dict]:
    """D13：对讲解画面的段落抽取对应帧，返回 referenced_frame 结构（含 frames 列表）。

    返回 None 表示未命中任何讲解段 / 未启用。
    """
    if not enabled:
        return None
    if not segments:
        return None

    frames_dir = Path(out_dir) / f"{stem}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frames: List[Dict] = []
    for seg in segments:
        if not is_visual_explanation(seg.text):
            continue
        mid = (seg.start + seg.end) / 2.0
        out_path = frames_dir / f"frame_{_ts_label(mid)}.png"
        ok = extract_frame(video_path, mid, str(out_path))
        frames.append({
            "segment_start": round(seg.start, 2),
            "segment_end": round(seg.end, 2),
            "timestamp": round(mid, 2),
            "frame_path": str(out_path) if ok else None,
            "segment_text": seg.text.strip(),
            # 以下两项待阶段四视觉栈（VLM）填充：帧画面描述 + 帧上 OCR 文字
            "vision_caption": None,
            "ocr_on_frame": None,
            "is_visual_explanation": True,
            "extracted": ok,
        })

    if not frames:
        return None
    return {
        "frames": frames,
        "note": "视觉描述/帧上OCR 待阶段四视觉栈填充；帧图默认落本地、不自动上云（D13/§4.4）。",
    }


__all__ = ["is_visual_explanation", "extract_frame", "extract_referenced_frames"]
