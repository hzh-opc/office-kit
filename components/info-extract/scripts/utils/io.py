#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 输入发现与类型识别（D8 触发范围）。

支持四类输入（方案 §0.5）：
① 图片（含图片型文档）            → OCR + 画面解读
② 文档中含图片/媒体需单独识别      → 抽取后逐张/逐段路由（阶段三/四）
③ 音频（需转录）                  → 音频转录（阶段一，已实现）
④ 视频（需提取文案或识别画面）    → 视频文案/画面（阶段二/四/五）

本模块只做「发现 + 分类」，不触发任何重型依赖；重型模块由 router 按类型惰性载入。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Tuple

from modules.base import SourceType

# ---- 扩展名分类表 ----
AUDIO_EXT = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wma", ".aiff", ".aif", ".caf",
}
# 注：.webm 归 VIDEO_EXT（多为 VP8/VP9 视频容器）；纯音频 webm 极少见，若被当视频处理
# 会因「无音轨」清晰报错（不静默失败），比双归类（先后覆盖）的隐式行为更可预期。
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp", ".heic", ".heif",
}
# 复合文档（②）：需先抽取内嵌媒体再路由（阶段三/四落地）
# 注：.pdf 已从复合文档抽出，单独归 OCR（阶段三）——OCR 模块内做类型探测分流
# （纯图/扫描件页 → OCR；含原生文本层页 → D10 分工交 document_text 技能）。
DOC_EXT = {
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".epub", ".odt", ".rtf",
}

# 图片型 / 扫描件 PDF：路由到 OCR（阶段三）；OCR 模块内做类型探测分流（审阅 E）。
PDF_EXT = {".pdf"}

# 已知可处理扩展名 → 来源类型
_EXT_TO_TYPE: Dict[str, str] = {}
for _e in AUDIO_EXT:
    _EXT_TO_TYPE[_e] = SourceType.TRANSCRIPT
for _e in VIDEO_EXT:
    _EXT_TO_TYPE[_e] = SourceType.VIDEO  # 本地视频文件 → 阶段二视频文案（复用音频转录）
for _e in IMAGE_EXT:
    _EXT_TO_TYPE[_e] = SourceType.OCR  # 图片先路由 OCR（阶段三）；画面解读由 OCR 模块协同
for _e in PDF_EXT:
    _EXT_TO_TYPE[_e] = SourceType.OCR  # 扫描件/图片型 PDF → OCR（阶段三，模块内探测分流）
for _e in DOC_EXT:
    _EXT_TO_TYPE[_e] = SourceType.DOC_EXTRACT  # 其余复合文档抽取（阶段四/五落地）


def classify(path: str) -> str:
    """按扩展名判定来源类型；未知返回空串。"""
    ext = Path(path).suffix.lower()
    return _EXT_TO_TYPE.get(ext, "")


def is_supported(path: str) -> bool:
    return bool(classify(path))


# URL 正则（在线/加密视频场景，阶段五）：http(s)/ftp(s)
import re as _re  # noqa: E402

_URL_RE = _re.compile(r"^(?:https?|ftps?)://", _re.IGNORECASE)


def is_url(s: str) -> bool:
    """判定输入是否为在线视频 URL（非本地文件）。命中即路由到 video_online（阶段五）。"""
    return bool(_URL_RE.match((s or "").strip()))


def discover(inputs: List[str], recursive: bool = False) -> List[Tuple[str, str]]:
    """展开目录 / glob / 多文件，返回 [(绝对路径, 来源类型), ...]，仅保留已知可处理类型。

    不支持格式（审阅 I）：明确排除并交由 router 报告，绝不静默放过。
    """
    found: List[Tuple[str, str]] = []
    unsupported: List[str] = []
    seen = set()
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            entries = sorted(p.glob(pattern))
        else:
            # 支持 glob（如 "*.mp3"）
            entries = sorted(p.parent.glob(p.name)) if any(ch in raw for ch in "*?[]") else ([p] if p.exists() else [])
        for e in entries:
            if not e.is_file():
                continue
            t = classify(str(e))
            if not t:
                unsupported.append(str(e))
                continue
            ap = str(e.resolve())
            if ap in seen:
                continue
            seen.add(ap)
            found.append((ap, t))
    return found, unsupported


def format_seconds(sec: float) -> str:
    """把秒格式化为 [HH:MM:SS] 或 [MM:SS]，用于文本通道时间戳。"""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"[{h:02d}:{m:02d}:{s:02d}]"
    return f"[{m:02d}:{s:02d}]"


__all__ = [
    "AUDIO_EXT", "VIDEO_EXT", "IMAGE_EXT", "DOC_EXT", "PDF_EXT",
    "classify", "is_supported", "discover", "is_url", "format_seconds",
]
