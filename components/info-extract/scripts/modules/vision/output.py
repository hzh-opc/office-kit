#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视觉理解输出契约（D11 双通道）。

- 纯文本通道 .txt：视觉描述（vision caption），可直接喂 summarize 做摘要。
- 结构化通道 .json：ExtractResult.to_contract()，含 ocr 协同文字 / 档位 / provider_meta。
- 可读通道 .md：带来源/档位/置信度说明/字段，供用户核验（流程规范 §4.1）。

视觉理解无「逐框置信度」，VLM 也不产出干净置信度，故 confidence 记为 None（未知），
由 quality_scorer 给出「请人工核对」建议；不假装 100% 准确（§4.1 透明展示）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from modules.base import ExtractResult


def _to_md(result: ExtractResult) -> str:
    lines: List[str] = []
    lines.append("# 画面解读结果\n")
    pm = result.provider_meta or {}
    lines.append(f"- **来源 (source)**：`{result.source}`")
    lines.append(f"- **引擎 (provider)**：`{pm.get('provider', '?')}`（上云：{pm.get('cost', 'local')}）")
    if pm.get("ocr_provider"):
        lines.append(f"- **OCR 协同**：`{pm.get('ocr_provider')}`（画面文字经 OCR 取回，供视觉理解参考）")
    if result.fields:
        lines.append("- **关键字段 (fields)**：")
        for k, v in result.fields.items():
            if k in ("caption", "ocr_text", "note"):
                continue
            lines.append(f"  - {k}: {v}")
    lines.append("")
    # D16 纠正版稿件（交付物，置顶）
    lines.append("## 纠正版稿件（交付物，请以此为准；机器理解可能不准确，请核对）\n")
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
    # 识别结果备查（原始，未经纠正）
    lines.append("")
    lines.append("## 识别结果备查（原始，未经纠正）\n")
    lines.append(result.raw_text or result.text or "（无）")
    ocr_text = result.fields.get("ocr_text")
    if ocr_text:
        lines.append("")
        lines.append("## 图中 OCR 文字（协同参考）\n")
        lines.append(ocr_text)
    # 上云提质提示（D2 / §4.4）
    if result.media_ref.get("suggest_cloud_upgrade"):
        lines.append("")
        lines.append(f"> ⚠️ {result.media_ref.get('upgrade_hint', '')}")
    note = result.fields.get("note")
    if note:
        lines.append("")
        lines.append(f"> ℹ️ {note}")
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ExtractResult,
    out_dir: str | Path,
    stem: str,
    formats: Tuple[str, ...] = ("txt", "json", "md"),
) -> Dict[str, str]:
    """把结果落到双通道（txt/json/md）。返回 {格式: 路径}。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    if "txt" in formats:
        p = out_dir / f"{stem}.txt"
        # 纯文本通道：视觉描述优先，无则退回 OCR 文字
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
        p.write_text(_to_md(result), encoding="utf-8")
        written["md"] = str(p)
    return written


__all__ = ["_to_md", "write_outputs"]
