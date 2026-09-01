#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · OCR 输出契约（D11 双通道）。

- 纯文本通道 .txt：识别文本拼接（可直接喂 summarize 做摘要）。
- 结构化通道 .json：ExtractResult.to_contract()，含逐框信息供归档/知识库/翻译消费。
- 可读通道 .md：带来源/置信度/字段/逐框明细（含每框置信度，不确定项标★）供用户核验（§4.1）。

与音频转录 output 的区别：OCR 无「带时间戳片段」，逐框 text+score 即核对单元。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from modules.base import ExtractResult

# 不确定项标记阈值（与置信度门控阈值一致，审阅 D）
LOW_CONF_MARK = 0.85


def boxes_to_text(boxes: List[Dict]) -> str:
    """把逐框文本按阅读顺序拼接为纯文本通道（喂 summarize）。"""
    return "\n".join(b["text"] for b in boxes if b.get("text") is not None)


def _to_md(result: ExtractResult, boxes: List[Dict]) -> str:
    lines: List[str] = []
    lines.append("# OCR 识别结果\n")
    pm = result.provider_meta or {}
    lines.append(f"- **来源 (source)**：`{result.source}`")
    lines.append(f"- **引擎 (provider)**：`{pm.get('provider', '?')}`（上云：{pm.get('cost', 'local')}）")
    if result.confidence is not None:
        lines.append(f"- **平均置信度 (confidence)**：{result.confidence:.3f}")
    if result.fields:
        lines.append("- **关键字段 (fields)**：")
        for k, v in result.fields.items():
            # 长列表折叠显示
            if isinstance(v, list) and len(v) > 8:
                v = f"[{len(v)} 项] {v[:8]} …"
            lines.append(f"  - {k}: {v}")
    lines.append("")
    # D16 纠正版稿件（交付物，置顶）
    lines.append("## 纠正版稿件（交付物，请以此为准；机器识别可能不准，请核对）\n")
    corr = result.corrected
    if corr:
        lines.append(result.text)
        lines.append("")
        lines.append(f"> 纠正来源：{corr.get('correction_source')}｜模型：{corr.get('model')}｜时间：{corr.get('corrected_at')}")
        notes = corr.get("correction_notes")
        if notes:
            lines.append(f"> 纠正说明：{notes}")
    else:
        lines.append(result.text)
        lines.append("")
        lines.append("> 未经本地纠正（未配置本地文本模型或已 --no-correct），以上即原始识别文本。")
    # 识别结果备查（原始识别文本）
    lines.append("")
    lines.append("## 识别结果备查（原始识别文本）\n")
    lines.append(boxes_to_text(boxes) or "（无文本）")
    # 逐框明细 + 不确定标记
    lines.append("")
    lines.append("## 逐框明细（含置信度，便于核对）\n")
    if boxes:
        for i, b in enumerate(boxes, 1):
            mark = " ★" if b["score"] < LOW_CONF_MARK else ""
            lines.append(f"{i}. {b['text']}  (conf={b['score']:.2f}{mark})")
    else:
        lines.append("（无文本）")
    # 文本层页提示（D10 分工）
    if result.fields.get("note_document_text"):
        lines.append("")
        lines.append(f"> ℹ️ {result.fields['note_document_text']}")
    # 上云提质提示（审阅 D → D2）
    if result.media_ref.get("suggest_cloud_upgrade"):
        lines.append("")
        lines.append(f"> ⚠️ {result.media_ref.get('upgrade_hint', '')}")
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ExtractResult,
    out_dir: str | Path,
    stem: str,
    boxes: List[Dict],
    formats: Tuple[str, ...] = ("txt", "json", "md"),
) -> Dict[str, str]:
    """把结果落到双通道（txt/json/md）。返回 {格式: 路径}。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    if "txt" in formats:
        p = out_dir / f"{stem}.txt"
        # D16：.txt = 纠正版稿件（交付物）；原始识别见 .md 备查 / .json raw_text
        p.write_text(result.text or "", encoding="utf-8")
        written["txt"] = str(p)
    if "json" in formats:
        p = out_dir / f"{stem}.json"
        p.write_text(
            json.dumps(result.to_contract(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written["json"] = str(p)
    if "md" in formats:
        p = out_dir / f"{stem}.md"
        p.write_text(_to_md(result, boxes), encoding="utf-8")
        written["md"] = str(p)
    return written


__all__ = ["boxes_to_text", "_to_md", "write_outputs"]
