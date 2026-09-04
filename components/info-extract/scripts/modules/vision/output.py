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
from typing import Dict, List, Optional, Tuple

from modules.base import ExtractResult
from modules.output_common import resolve_output_dirs, detect_pii


def _correction_status_hint(result: ExtractResult) -> str:
    """按 provider_meta.correction.status 细分提示语（组件反馈 P2-①）。"""
    meta = result.provider_meta or {}
    corr = meta.get("correction") if isinstance(meta, dict) else None
    status = (corr or {}).get("status") if corr else None
    if status == "applied":
        return ""
    model = (corr or {}).get("model") if corr else None
    hints = {
        "skipped:disabled": "已通过 --no-correct 主动关闭纠正。",
        "skipped:no-model": f"本机未配置纠正模型（{model or 'qwen2.5:7b'}），可运行 `ollama pull qwen2.5:7b` 启用。",
        "skipped:error": "纠正失败（模型不可达或超时），已保留原始识别。",
        "skipped:empty": "纠正模型未返回有效文本，已保留原始识别。",
    }
    return hints.get(status, "")


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
        hint = _correction_status_hint(result)
        if hint:
            lines.append(f"> ℹ️ {hint}")
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
    flat_out: Optional[bool] = None,
) -> Dict[str, str]:
    """把结果落到双通道（txt/json/md + 交付物分区）。返回 {格式: 路径}。

    组件反馈 P0-①：默认拆「交付/存档」两子目录；flat_out=True 平铺（旧行为）。
    交付区：.txt（纠正版）/.md（可读版）；存档区：.json（含 raw_text）。
    组件反馈 P1-②：无纠正模型时 .txt 用 .raw.txt 后缀显式标记降级。
    """
    out_dir = Path(out_dir)
    deliver, archive = resolve_output_dirs(out_dir, flat_out=flat_out)
    deliver.mkdir(parents=True, exist_ok=True)
    if archive != deliver:
        archive.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    degraded = result.corrected is None
    txt_name = f"{stem}.raw.txt" if degraded else f"{stem}.txt"

    if "txt" in formats:
        p = deliver / txt_name
        # 纯文本通道：视觉描述优先，无则退回 OCR 文字
        p.write_text(result.text or "", encoding="utf-8")
        written["txt"] = str(p)
    if "json" in formats:
        p = archive / f"{stem}.json"
        p.write_text(
            json.dumps(result.to_contract(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written["json"] = str(p)
    if "md" in formats:
        p = deliver / f"{stem}.md"
        p.write_text(_to_md(result), encoding="utf-8")
        written["md"] = str(p)

    # 敏感信息轻量预检（P1-④）：只读扫描，结果挂 media_ref 供交付卡片提示
    pii = detect_pii(result.text)
    if pii is not None:
        result.media_ref["pii_scan"] = pii

    return written


__all__ = ["_to_md", "write_outputs"]
