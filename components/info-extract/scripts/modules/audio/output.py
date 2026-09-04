#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 音频转录输出契约（D11 双通道 + 时间戳 + 交付物分区）。

- 纯文本通道 .txt：可直接喂 summarize 做摘要（= 纠正版稿件）。
- 结构化通道 .json：ExtractResult.to_contract()，供归档/知识库/翻译消费。
- 字幕通道 .srt：带时间戳，便于字幕/跳转（原始识别，归存档区）。
- 可读通道 .md：带来源/置信度/字段/provider 标注，供用户核验（流程规范 §4.1）。
- 校正过程文件 .correction.md：逐条改动清单（组件反馈 P1-③，归存档区）。

组件反馈「交互与展示优化」落地：
- P0-① 交付/存档物理分区：默认拆「交付/存档」两子目录，--flat-out 降级平铺。
- P0-② 校正版逐字稿带时间码：.md 的「纠正版稿件」区块改为带时间码的校正逐字稿。
- P1-② 无纠正模型降级显式标记：.txt 文件名用 .raw.txt 后缀区分。
- P1-③ 校正过程文件落盘：新增 .correction.md 通道（逐条改动，降级不生成）。
- P1-④ 识别稿敏感预检：落盘后只读扫描，命中结果挂 media_ref 供交付卡片提示。
- P2-① correction.status 五态透出：按 status 细分提示语。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.base import ExtractResult, Segment
from modules.output_common import resolve_output_dirs, detect_pii
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


def _correction_meta_line(result: ExtractResult) -> List[str]:
    """纠正来源标注行（含 status 五态细分）。"""
    corr = result.corrected
    lines: List[str] = []
    if corr:
        lines.append(f"> 纠正来源：{corr.get('correction_source')}｜模型：{corr.get('model')}｜时间：{corr.get('corrected_at')}")
        notes = corr.get("correction_notes")
        if notes:
            lines.append(f"> 纠正说明：{notes}")
    else:
        hint = _correction_status_hint(result)
        lines.append("> 未经本地纠正（未配置本地文本模型或已 --no-correct），以上即原始识别文本。")
        if hint:
            lines.append(f"> ℹ️ {hint}")
    return lines


def _corrected_verbatim(result: ExtractResult) -> str:
    """校正版逐字稿（带时间码）：优先 corrected_segments，回退 segments（组件反馈 P0-②）。"""
    segs = result.corrected_segments or result.segments
    out: List[str] = []
    for seg in segs:
        out.append(f"{format_seconds(seg.start)} {seg.text.strip()}")
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
    # D16 纠正版稿件（交付物，置顶）——组件反馈 P0-②：带时间码的校正逐字稿
    lines.append("")
    lines.append("## 纠正版逐字稿（交付物，带时间码，请以此为准；机器识别可能不准，请核对）\n")
    corr = result.corrected
    if corr:
        lines.append(_corrected_verbatim(result))
        lines.append("")
        lines.extend(_correction_meta_line(result))
    else:
        lines.append(_corrected_verbatim(result))
        lines.append("")
        lines.append("> 未经本地纠正（未配置本地文本模型或已 --no-correct），以上即原始识别文本。")
        hint = _correction_status_hint(result)
        if hint:
            lines.append(f"> ℹ️ {hint}")
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


def _to_correction_md(result: ExtractResult) -> str:
    """校正过程文件（P1-③）：逐条改动清单。"""
    entries = result.correction_entries or []
    corr = result.corrected or {}
    lines: List[str] = []
    lines.append("# 校正过程（备查）\n")
    lines.append(f"- 纠正来源：`{corr.get('correction_source', '?')}`")
    lines.append(f"- 模型：`{corr.get('model', '?')}`")
    lines.append(f"- 时间：`{corr.get('corrected_at', '?')}`")
    lines.append("")
    if not entries:
        lines.append("（本次校正无逐条改动记录）")
    else:
        lines.append("| 时间码 | 原始识别 | 校正后 | 纠正类型 |")
        lines.append("|---|---|---|---|")
        for e in entries:
            raw = (e.get("raw") or "").replace("|", "\\|").replace("\n", " ")
            corrected = (e.get("corrected") or "").replace("|", "\\|").replace("\n", " ")
            kind = e.get("kind") or "修订"
            lines.append(f"| {format_seconds(e.get('start', 0.0))} | {raw} | {corrected} | {kind} |")
    return "\n".join(lines) + "\n"


def write_outputs(
    result: ExtractResult,
    out_dir: str | Path,
    stem: str,
    formats: Tuple[str, ...] = ("txt", "srt", "json", "md"),
    flat_out: Optional[bool] = None,
) -> Dict[str, str]:
    """把结果落到双通道（含字幕与可读 MD + 交付物分区）。返回 {格式: 路径}。

    组件反馈 P0-①：默认拆「交付/存档」两子目录；flat_out=True（或环境变量
    INFO_EXTRACT_FLAT_OUT=1）平铺（旧行为）。交付区：.txt（纠正版）/.md（可读版）；
    存档区：.srt/.json/.correction.md。
    组件反馈 P1-②：无纠正模型时 .txt 用 .raw.txt 后缀显式标记降级。
    """
    out_dir = Path(out_dir)
    deliver, archive = resolve_output_dirs(out_dir, flat_out=flat_out)
    deliver.mkdir(parents=True, exist_ok=True)
    if archive != deliver:
        archive.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    # 降级显式标记（P1-②）：corrected=None 时 .txt 用 .raw.txt 后缀
    degraded = result.corrected is None
    txt_name = f"{stem}.raw.txt" if degraded else f"{stem}.txt"

    if "txt" in formats:
        p = deliver / txt_name
        # D16：.txt = 纠正版稿件（交付物，clean text）；原始带时间戳备查见 .srt
        p.write_text(result.text or "", encoding="utf-8")
        written["txt"] = str(p)
    if "srt" in formats:
        p = archive / f"{stem}.srt"
        p.write_text(segments_to_srt(result.segments), encoding="utf-8")
        written["srt"] = str(p)
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
    # 校正过程文件（P1-③）：仅当有纠正且有逐条改动时生成，降级不生成
    if result.corrected is not None and result.correction_entries is not None:
        p = archive / f"{stem}.correction.md"
        p.write_text(_to_correction_md(result), encoding="utf-8")
        written["correction"] = str(p)

    # 敏感信息轻量预检（P1-④）：只读扫描，结果挂 media_ref 供交付卡片提示
    pii = detect_pii(result.text)
    if pii is not None:
        result.media_ref["pii_scan"] = pii

    return written


__all__ = [
    "segments_to_srt", "segments_to_txt", "_to_md", "_to_correction_md", "write_outputs",
]
