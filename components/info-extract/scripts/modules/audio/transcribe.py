#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 音频转录模块（阶段一，高优先级，已实现）。

流程（呼应方案 §3 阶段一 + 流程规范 §2.2）：
1. 接收音频 → 敏感预检（上云前由 DESEN 闸门接管，详见 skill_bridge）。
2. 长文件分块（D12·J）：duration > 阈值（默认 10min）时按 VAD/静音切分，逐段转录，
   段内时间戳归一到全局；超大音频不整体驻留、不落盘临时分块（PyAV 内存切片 + ndarray 直传）。
3. Whisper 本地转录（默认 faster-whisper / small，D15 默认本地 provider）。
4. 输出：纯文本 / 带时间戳（SRT/TXT）+ 结构化 JSON/MD（D11 双通道）。
5. 语言/任务轻提示（D12·K）：文件名或对话 hint 解析；自动识别兜底。
6. 批量输入 + 聚合报告（D12·H）：目录/多文件/glob，统一进度 + 聚合报告（含异常清单）。
7. 哈希缓存（D12·L）：同文件同参数跳过。
8. 临时文件清理（D12·G）：本模块不写中间临时文件；若将来引入落盘分块，统一走 TempSandbox。

provider_meta 透明回显（D15 / 流程规范 §4.7）：用了哪个 provider、是否上云，随产出回显。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from modules.audio.language import parse_language_hint, parse_task_hint
from modules.audio.output import write_outputs
from modules.audio.providers import FasterWhisperProvider
from modules.audio.vad import TARGET_SR, load_audio, vad_split
from modules.base import ExtractResult, IModule, InfoExtractError, Segment, SourceType, contract_to_result
from modules.corrector import maybe_correct
from utils.hash_cache import ResultCache
from utils.io import format_seconds

LONG_THRESHOLD_SEC = 600  # 超过 10 分钟启用 VAD 分块（D12·J）


def _offset_segments(segs: List[Segment], offset: float) -> List[Segment]:
    out: List[Segment] = []
    for s in segs:
        out.append(
            Segment(
                start=s.start + offset,
                end=s.end + offset,
                text=s.text,
                words=[
                    {**w, "start": w["start"] + offset, "end": w["end"] + offset}
                    for w in s.words
                ],
            )
        )
    return out


def _mean_confidence(segs: List[Segment]) -> Optional[float]:
    probs: List[float] = []
    for s in segs:
        for w in s.words:
            if "prob" in w:
                probs.append(w["prob"])
    if not probs:
        return None
    return round(float(np.mean(probs)), 3)


def transcribe_core(
    samples: np.ndarray,
    sr: int,
    path: str,
    options: Dict[str, Any],
    out_dir,  # 仅占位，写盘由调用方负责
    cache,
    model_size: str,
    vad_threshold: int,
    long_threshold: int,
    source_type: str = SourceType.TRANSCRIPT,
) -> "ExtractResult":
    """阶段一 / 阶段二共用的核心转录：选 provider（D15）+ VAD 分块（D12·J）+ Whisper 转录。

    返回已填好的 ExtractResult（含 text/segments/confidence/fields/provider_meta/media_ref），
    **不负责写盘与缓存**——由调用方（AudioModule / VideoModule）统一落双通道 + 写缓存，
    保证音频与视频产物的输出/缓存行为一致。
    """
    hint = options.get("lang") or Path(path).stem
    language = parse_language_hint(hint) or options.get("language")
    task = parse_task_hint(options.get("task") or hint) or options.get("task") or "transcribe"

    # 选 provider（D15 默认本地优先；显式指定优先；不可用则降级提示）
    from provider_registry import get_provider  # 惰性 import 打破循环依赖

    provider_name = options.get("provider")
    if provider_name in (None, "auto"):  # "auto" 视为未显式指定
        provider_name = None
    provider = get_provider(SourceType.TRANSCRIPT, name=provider_name)
    if provider is None or not provider.available():
        raise InfoExtractError(
            "未找到可用的本地转录引擎（faster-whisper）。请先安装技能依赖。",
            recoverable=True,
            hint="运行技能目录下 install.py / install.sh 安装 faster-whisper 等依赖。",
        )

    # 加载 + 分块（D12·J）
    duration = len(samples) / sr
    chunks = vad_split(samples, sr, min_silence_ms=vad_threshold)
    use_chunking = len(chunks) > 1 and duration > long_threshold

    all_segs: List[Segment] = []
    detected_lang = language or "auto"
    if use_chunking:
        for (s, e) in chunks:
            chunk = samples[int(s * sr): int(e * sr)]
            segs, info = provider.transcribe(
                chunk, language=language, task=task, model_size=model_size
            )
            all_segs.extend(_offset_segments(segs, s))
            detected_lang = info.get("detected_language") or detected_lang
    else:
        segs, info = provider.transcribe(
            samples, language=language, task=task, model_size=model_size
        )
        all_segs.extend(segs)
        detected_lang = info.get("detected_language") or detected_lang

    confidence = _mean_confidence(all_segs)
    text = "\n".join(seg.text.strip() for seg in all_segs if seg.text.strip())

    return ExtractResult(
        source=source_type,
        text=text,
        confidence=confidence,
        fields={
            "detected_language": detected_lang,
            "task": task,
            "model_size": model_size,
            "duration_sec": round(duration, 2),
            "num_segments": len(all_segs),
            "chunked": use_chunking,
        },
        media_ref={
            "path": path,
            "duration": round(duration, 2),
            "status": "ok",
        },
        provider_meta=provider.meta(),
        segments=all_segs,
    )


class AudioModule(IModule):
    name = "audio"
    source_type = SourceType.TRANSCRIPT
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        use_cache = options.get("use_cache", True)
        cache = ResultCache() if use_cache else None
        model_size = options.get("model") or options.get("model_size") or "small"
        vad_threshold = options.get("vad_threshold", 700)  # min_silence_ms
        long_threshold = options.get("long_threshold", LONG_THRESHOLD_SEC)

        results: List[ExtractResult] = []
        for path in inputs:
            try:
                res = self._process_one(
                    path, options, out_dir, cache, model_size, vad_threshold, long_threshold
                )
                results.append(res)
            except InfoExtractError as e:
                results.append(self._error_result(path, e))
            except Exception as e:  # 兜底，绝不静默失败
                results.append(
                    self._error_result(
                        path,
                        InfoExtractError(f"未预期错误：{e}", recoverable=False),
                    )
                )

        # 批量聚合报告（D12·H）
        if len(inputs) > 1:
            self._write_aggregate(results, out_dir)

        # 控制台简报（router 也会再汇总，这里提供模块级回显）
        return results

    def _process_one(self, path, options, out_dir, cache, model_size, vad_threshold, long_threshold):
        path = str(Path(path).expanduser().resolve())
        if not os.path.isfile(path):
            raise InfoExtractError(f"文件不存在：{path}", recoverable=False)

        # 语言 / 任务轻提示（D12·K）：优先显式参数，其次文件名
        hint = options.get("lang") or Path(path).stem
        language = parse_language_hint(hint) or options.get("language")
        task = parse_task_hint(options.get("task") or hint) or options.get("task") or "transcribe"

        cache_key_opts = {
            "lang": language, "task": task, "model": model_size,
            "provider": options.get("provider"), "vad_threshold": vad_threshold,
            "min_silence_ms": vad_threshold,
            # D16 纠正版稿件选项（影响 text/corrected，须纳入缓存键，避免换语境命中旧稿）
            "context": options.get("context"),
            "correct_model": options.get("correct_model"),
            "no_correct": options.get("no_correct", False),
        }

        # 哈希缓存（D12·L）
        if cache is not None:
            hit = cache.get(path, cache_key_opts)
            if hit:
                r = contract_to_result(hit)
                r.media_ref = r.media_ref or {}
                r.media_ref.update({"path": path, "status": "cached", "outputs": {}})
                # 缓存命中仍落盘输出（确保 out_dir 有文件）
                r.media_ref["outputs"] = write_outputs(r, out_dir, Path(path).stem)
                return r

        # 加载音轨（D12·J 加载；分块 / 转录在 transcribe_core 内完成）
        samples, sr = load_audio(path, TARGET_SR)

        # 核心转录（阶段一/二共用）：provider 选择 + VAD 分块 + Whisper 转录
        result = transcribe_core(
            samples, sr, path, options, out_dir, cache,
            model_size, vad_threshold, long_threshold,
            source_type=SourceType.TRANSCRIPT,
        )
        # D16 交付物范式：固定原始识别为单一备查副本，再尝试生成纠正版稿件
        result.raw_text = result.text
        maybe_correct(result, options)
        # 双通道输出（D11）：.txt=纠正版稿件，.srt=原始带时间戳备查，.json/.md 含 raw_text+corrected
        outputs = write_outputs(result, out_dir, Path(path).stem)
        result.media_ref["outputs"] = outputs

        # 写缓存（D12·L）：仅落本地私有目录，不外传
        if cache is not None:
            cache.put(path, cache_key_opts, result.to_contract())

        return result

    def _error_result(self, path: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.TRANSCRIPT,
            text="",
            media_ref={
                "path": path,
                "status": "error",
                "error": err.message,
                "recoverable": err.recoverable,
                "hint": err.hint,
            },
        )

    def _write_aggregate(self, results: List[ExtractResult], out_dir: str) -> Dict[str, str]:
        from utils.io import format_seconds  # local import to avoid cycle at module load

        ok = [r for r in results if r.media_ref.get("status") == "ok"]
        errs = [r for r in results if r.media_ref.get("status") == "error"]
        cached = [r for r in results if r.media_ref.get("status") == "cached"]
        lines = ["# info-extract 音频转录 · 批量聚合报告", ""]
        lines.append(f"- 总计：{len(results)} 个文件")
        lines.append(f"- 成功：{len(ok)} ｜ 缓存命中：{len(cached)} ｜ 异常：{len(errs)}")
        lines.append("")
        lines.append("## 逐文件")
        for r in results:
            mr = r.media_ref
            line = f"- `{mr.get('path')}` → **{mr.get('status')}**"
            if mr.get("status") == "ok":
                line += (
                    f"（语言={r.fields.get('detected_language')}, "
                    f"时长={format_seconds(r.fields.get('duration_sec', 0))}, "
                    f"置信度={r.confidence}）"
                )
            elif mr.get("status") == "error":
                line += f" ⚠️ {mr.get('error')}"
                if mr.get("hint"):
                    line += f" 建议：{mr.get('hint')}"
            lines.append(line)
        if errs:
            lines.append("")
            lines.append("## 异常清单（请核对，未静默放过）")
            for r in errs:
                lines.append(f"- `{r.media_ref.get('path')}`：{r.media_ref.get('error')}")
        content = "\n".join(lines) + "\n"

        out_dir_p = Path(out_dir)
        out_dir_p.mkdir(parents=True, exist_ok=True)
        md_path = out_dir_p / "info-extract-transcript-report.md"
        json_path = out_dir_p / "info-extract-transcript-report.json"
        md_path.write_text(content, encoding="utf-8")
        json_path.write_text(
            __import__("json").dumps(
                {
                    "total": len(results),
                    "ok": len(ok),
                    "cached": len(cached),
                    "error": len(errs),
                    "items": [
                        {
                            "path": r.media_ref.get("path"),
                            "status": r.media_ref.get("status"),
                            "fields": r.fields,
                            "outputs": r.media_ref.get("outputs", {}),
                            "error": r.media_ref.get("error"),
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        # 把报告路径挂到首个结果，便于 router 展示
        if results:
            results[0].media_ref["report"] = {
                "md": str(md_path),
                "json": str(json_path),
            }
        return {"md": str(md_path), "json": str(json_path)}


__all__ = ["AudioModule"]
