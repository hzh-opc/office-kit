#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复合文档内嵌媒体抽取模块（阶段三/四，规划中）。

先按 PDF 类型探测（审阅 E）分流：文本层 → document_text（D10），纯图页 → OCR，
内嵌音视频 → 各自流程。本占位模块确保 router 对文档输入给出清晰「规划中」提示（D9/D15）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from modules.base import ExtractResult, IModule, SourceType

PHASE = "阶段三/四（规划中）"


class DocExtractModule(IModule):
    name = "doc_extract"
    source_type = SourceType.DOC_EXTRACT
    ready = False

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        return [
            ExtractResult(
                source=SourceType.DOC_EXTRACT,
                text="",
                media_ref={"path": p, "status": "planned", "phase": PHASE},
            )
            for p in inputs
        ]


__all__ = ["DocExtractModule"]
