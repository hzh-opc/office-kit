#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 图像读写共享工具（零新依赖，标准库 PNG 写出）。

设计：
- 视觉栈（阶段四）与视频帧（D13）都需要把 RGB ndarray 写成 PNG；为避免重复实现、
  并规避本机 ffmpeg 图像编码器（mjpeg/png）受限问题，统一用标准库 `zlib` 手写 PNG。
- 图像读取用 Pillow（阶段三已列为依赖，轻量广泛可用）；缺失即优雅降级。
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Union

import numpy as np  # 核心数值依赖（已在隔离 venv）

PathLike = Union[str, Path]


def _rgb_to_png_bytes(rgb: np.ndarray) -> bytes:
    """RGB(H×W×3 uint8) → 标准库-only PNG 字节流（color type 2, 8-bit）。

    与 modules.video.frames._write_png 同算法，集中在此处复用，避免重复实现。
    """
    if rgb.ndim == 2:  # 灰度图转伪彩（极少见，稳妥处理）
        rgb = np.stack([rgb, rgb, rgb], axis=-1)
    h, w, _ = rgb.shape
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0 (None)
        raw.extend(rgb[y].tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")


def write_png_rgb(path: PathLike, rgb: np.ndarray) -> None:
    """把 RGB ndarray 写成 PNG 文件。"""
    Path(path).write_bytes(_rgb_to_png_bytes(np.asarray(rgb)))


def rgb_to_png_bytes(rgb: np.ndarray) -> bytes:
    """返回 RGB ndarray 的 PNG 字节（供 VLM provider 直接 base64 编码）。"""
    return _rgb_to_png_bytes(np.asarray(rgb))


def load_image_rgb(path: PathLike) -> np.ndarray:
    """读取图片为 RGB uint8 ndarray（依赖 Pillow，缺失则优雅降级提示）。"""
    try:
        from PIL import Image
    except Exception:
        from modules.base import InfoExtractError

        raise InfoExtractError(
            "未找到 Pillow 依赖，无法读取图片。请运行技能目录下 install.py / install.sh 安装 Pillow。",
            recoverable=True,
        )
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


__all__ = ["write_png_rgb", "rgb_to_png_bytes", "load_image_rgb"]
