#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 图像预处理链（审阅 D）。

OCR 前本地预处理，提升本地可用率、减少上云频次（呼应 D2 但更智能、更省云）：
1. 方向校正（EXIF orientation，PIL 读取时完成）；
2. 归一化（最长边 ≤2000px，DESEN 实测稳定识别区 1000–2100px，Det.limit_side_len 736–2000）；
3. 可选去噪（中值滤波，去除扫描噪点）；
4. 可选轻量超分（upscale，提升小字识别率）；
5. 可选透视校正（deskew，opencv 可用时霍夫直线检测；否则跳过并记录为可选增强）。

返回 (处理后的 RGB ndarray, 执行的步骤列表) 供透明展示（流程规范 §4.1）。
依赖：numpy + Pillow（轻量、普遍可用）；deskew 优先 cv2（rapidocr 自带 opencv-python-headless），缺失则降级跳过。

设计原则：所有预处理在内存中完成，不落临时文件（隐私闭环审阅 G）；如需落盘临时分块，由调用方走 TempSandbox。
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageFilter, ImageOps
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

MAX_SIDE = 2000  # 归一化最长边上限（DESEN 实测稳定区 1000–2100px）


def load_image(path) -> np.ndarray:
    """读取图像为 RGB ndarray，并做 EXIF 方向校正。"""
    if not _HAS_PIL:
        raise RuntimeError("缺少 Pillow，无法读取图像。请安装 Pillow。")
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.asarray(img)


def normalize_max_side(img: np.ndarray, max_side: int = MAX_SIDE) -> Tuple[np.ndarray, bool]:
    """最长边归一化到 max_side。返回 (图像, 是否做过缩放)。"""
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return img, False
    scale = max_side / float(longest)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    if _HAS_PIL:
        out = np.asarray(Image.fromarray(img).resize((nw, nh), Image.LANCZOS))
    else:
        # 无 PIL 无法可靠缩放：交给 OCR（调用方可能提示降级），不强行最近邻（易碎字）
        return img, False
    return out, True


def deskew(img: np.ndarray) -> Tuple[np.ndarray, bool]:
    """轻量倾斜校正：优先 cv2 霍夫直线检测；否则跳过。返回 (图像, 是否校正)。"""
    if not _HAS_CV2:
        return img, False
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(50, int(min(gray.shape) * 0.3)))
    if lines is None:
        return img, False
    angles = []
    for rho_theta in lines:
        rho, theta = rho_theta[0]
        angle = (theta * 180 / np.pi) - 90
        if -45 < angle < 45:
            angles.append(angle)
    if not angles:
        return img, False
    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:
        return img, False
    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return rotated, True


def denoise(img: np.ndarray) -> np.ndarray:
    """中值滤波去噪（扫描噪点）。"""
    if not _HAS_PIL:
        return img
    return np.asarray(Image.fromarray(img).filter(ImageFilter.MedianFilter(3)))


def upscale(img: np.ndarray, factor: float = 1.5) -> np.ndarray:
    """轻量超分放大（提升小字识别率）。"""
    if not _HAS_PIL:
        return img
    h, w = img.shape[:2]
    nw, nh = max(1, int(w * factor)), max(1, int(h * factor))
    return np.asarray(Image.fromarray(img).resize((nw, nh), Image.LANCZOS))


def preprocess_image(img: np.ndarray, options: Optional[Dict] = None) -> Tuple[np.ndarray, List[str]]:
    """对 RGB ndarray 执行预处理链，返回 (处理后图像, 步骤日志)。

    options 支持：max_side(int)、denoise(bool,默认True)、upscale(bool,默认False)、
    upscale_factor(float)、deskew(bool,默认True)。
    """
    options = options or {}
    steps: List[str] = []
    cur = img

    # 1. 归一化（最长边 ≤ max_side）
    cur, resized = normalize_max_side(cur, options.get("max_side", MAX_SIDE))
    if resized:
        steps.append("归一化(最长边≤2000px)")

    # 2. 去噪（默认开）
    if options.get("denoise", True):
        cur = denoise(cur)
        steps.append("去噪(中值滤波)")

    # 3. 轻量超分（默认关，仅小字/低清图按需开）
    if options.get("upscale", False):
        cur = upscale(cur, options.get("upscale_factor", 1.5))
        steps.append("超分(轻量放大)")

    # 4. 透视校正（deskew，优先 cv2）
    if options.get("deskew", True):
        cur, did = deskew(cur)
        if did:
            steps.append("透视校正(deskew)")

    return cur, steps


__all__ = [
    "load_image", "normalize_max_side", "deskew", "denoise", "upscale", "preprocess_image", "MAX_SIDE",
]
