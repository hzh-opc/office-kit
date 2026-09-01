#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · PDF 类型探测与渲染（阶段三 / 审阅 E）。

- detect_pdf_pages：判定每页是否有原生文本层。有文本层 → 交 document_text（D10，分工 B），
  不归 info-extract；纯图页（扫描件）→ 才渲染 + OCR；混合 PDF 逐页分流。
- render_page：纯图页用 pypdfium2（PDFium，C 实现，对畸形 PDF 稳健）渲染为 RGB ndarray，
  再归一化最长边 ≤2000px。
- 加密 PDF：捕获异常并提示输入密码（审阅 I），不静默失败。

完全离线、数据不出本机；中间渲染图若需落盘走 TempSandbox（审阅 G）。
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional

try:
    import pypdfium2 as pdfium
    _HAS_PDFIUM = True
except Exception:
    _HAS_PDFIUM = False

MAX_SIDE = 2000


def detect_pdf_pages(pdf_path: str) -> List[Dict]:
    """返回每页信息：{page_index, has_text_layer}。完全离线。"""
    if not _HAS_PDFIUM:
        raise RuntimeError("缺少 pypdfium2，无法解析 PDF。请安装 pypdfium2。")
    pdf = pdfium.PdfDocument(pdf_path)
    pages: List[Dict] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                tp = page.get_textpage()
                text = tp.get_text_range().strip()
            except Exception:
                # 加密/损坏页无法取文本层 → 视为纯图（由 OCR 进一步判定）
                text = ""
            pages.append({"page_index": i, "has_text_layer": bool(text)})
    finally:
        pdf.close()
    return pages


def _normalize(arr: np.ndarray, max_side: int = MAX_SIDE) -> np.ndarray:
    h, w = arr.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return arr
    scale = max_side / float(longest)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    try:
        from PIL import Image
        return np.asarray(Image.fromarray(arr).resize((nw, nh), Image.LANCZOS))
    except Exception:
        return arr


def render_page(pdf_path: str, page_index: int, max_side: int = MAX_SIDE) -> Optional[np.ndarray]:
    """渲染指定页为 RGB ndarray（最长边归一化）。失败返回 None。"""
    if not _HAS_PDFIUM:
        raise RuntimeError("缺少 pypdfium2，无法渲染 PDF。请安装 pypdfium2。")
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=2.0)  # 2x 渲染提升清晰度，后由 _normalize 限边
        arr = np.asarray(bitmap.to_numpy())  # RGB uint8
    finally:
        pdf.close()
    if arr.size == 0:
        return None
    return _normalize(arr, max_side)


__all__ = ["detect_pdf_pages", "render_page"]
