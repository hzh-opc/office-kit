#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 音频转录输出契约（D11 双通道 + 时间戳）。

- 纯文本通道 .txt：可直接喂 summarize 做摘要。
- 结构化通道 .json：ExtractResult.to_contract()，供归档/知识库/翻译消费。
- 字幕通道 .srt：带时间戳，便于字幕/跳转。
- 可读通道 .md：带来源/置信度/字段/provider 标注，供用户核验（流程规范 §4.1）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from modules.base import ExtractResult, Segment
from utils.io import format_seconds


def _srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms % 1000:03d}"


def segments_to_srt(segments: List[Segment]) -> str:
    lines: List[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def segments_to_txt(segments: List[Segment], with_ts: bool = True) -> str:
    out: List[str] = []
    for seg in segments:
        text = seg.text.strip()
        out.append(f"{format_seconds(seg.start)} {text}" if with_ts else text)
    return "\n".join(out)


def _to_md(result: ExtractResult) -> str:
    lines: List[str] = []
    title = "在线/加密视频文案提取结果" if result.fields.get("online") else "音频转录结果"
    lines.append(f"# {title}\n")
    if result.fields.get("online"):
        enc = "（加密/DRM）" if result.fields.get("encrypted") else ""
        lines.append(f"- **获取方式 (acquire_method)**：`{result.fields.get('acquire_method')}`{enc}")
        lines.append(f"- **副本保存**：未保存（D3：录制副本默认不本地/云端保存，仅处理不留存）")
        if result.fields.get("title"):
            lines.append(f"- **标题 (title)**：{result.fields.get('title')}")
        if result.fields.get("legal_risk_warning"):
            lines.append(f"- **⚠️ 法律风险提示**：{result.fields.get('legal_risk_warning')}")
        lines.append("")
    lines.append(f"- **来源 (source)**：`{result.source}`")
    pm = result.provider_meta or {}
    lines.append(f"- **引擎 (provider)**：`{pm.get('provider', '?')}`（上云：{pm.get('cost', 'local')}）")
    if result.confidence is not None:
        lines.append(f"- **平均置信度 (confidence)**：{result.confidence:.3f}")
    if result.fields:
        lines.append("- **关键字段 (fields)**：")
        for k, v in result.fields.items():
            lines.append(f"  - {k}: {v}")
    if result.media_ref:
        lines.append("- **溯源 (media_ref)**：")
        for k, v in result.media_ref.items():
            lines.append(f"  - {k}: {v}")
    # D16 纠正版稿件（交付物，置顶）
    lines.append("")
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
    # 识别结果备查（原始，带时间戳）
    lines.append("")
    lines.append("## 识别结果备查（原始，带时间戳，供核对）\n")
    lines.append(segments_to_txt(result.segments, with_ts=True))
    # D13：讲解画面关联帧（视频专属）
    rf = result.referenced_frame
    if rf and rf.get("frames"):
        lines.append("")
        lines.append("## 讲解画面关联帧（D13，供查阅 / 审核）\n")
        for i, f in enumerate(rf["frames"], 1):
            lines.append(f"### 帧 {i} · @ {f.get('timestamp')}s（段落 {f.get('segment_start')}–{f.get('segment_end')}s）")
            lines.append(f"- 是否讲解画面：`{f.get('is_visual_explanation')}`")
            if f.get("frame_path"):
                lines.append(f"- 帧图：`{f.get('frame_path')}`")
            else:
                lines.append(f"- 帧图：⚠️ 抽取失败（{f.get('segment_text','')[:20]}…）")
            if f.get("segment_text"):
                lines.append(f"- 对应文案：{f.get('segment_text')}")
            oc = f.get("ocr_on_frame")
            vc = f.get("vision_caption")
            if oc:
                lines.append(f"- 帧上 OCR 文字：{oc}")
            if vc:
                lines.append(f"- 视觉描述：{vc}")
            if not oc and not vc:
                lines.append(f"- 视觉描述 / 帧上 OCR：（本地未配置 VLM，未填充；可上云提质 D2/§4.4）")
            lines.append("")
    # 审阅 F：整视频关键帧视觉分析（--vision 开启，需本地 VLM）
    kfa = result.fields.get("keyframe_analysis")
    if kfa and kfa.get("keyframes"):
        lines.append("")
        lines.append("## 关键帧视觉分析（审阅 F，供查阅 / 审核）\n")
        for i, kf in enumerate(kfa["keyframes"], 1):
            lines.append(f"### 关键帧 {i} · @ {kf.get('timestamp')}s")
            if kf.get("frame_path"):
                lines.append(f"- 帧图：`{kf.get('frame_path')}`")
            oc = kf.get("ocr_on_frame")
            vc = kf.get("vision_caption")
            if oc:
                lines.append(f"- 帧上 OCR 文字：{oc}")
            if vc:
                lines.append(f"- 视觉描述：{vc}")
            if not oc and not vc:
                lines.append("- 视觉描述 / 帧上 OCR：（VLM 不可用，未填充）")
            lines.append("")
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ExtractResult,
    out_dir: str | Path,
    stem: str,
    formats: Tuple[str, ...] = ("txt", "srt", "json", "md"),
) -> Dict[str, str]:
    """把结果落到双通道（含字幕与可读 MD）。返回 {格式: 路径}。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    if "txt" in formats:
        p = out_dir / f"{stem}.txt"
        # D16：.txt = 纠正版稿件（交付物，clean text）；原始带时间戳备查见 .srt
        p.write_text(result.text or "", encoding="utf-8")
        written["txt"] = str(p)
    if "srt" in formats:
        p = out_dir / f"{stem}.srt"
        p.write_text(segments_to_srt(result.segments), encoding="utf-8")
        written["srt"] = str(p)
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


__all__ = [
    "segments_to_srt", "segments_to_txt", "_to_md", "write_outputs",
]
