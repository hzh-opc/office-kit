#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频文案提取模块（阶段二，已实现）。

流程（呼应方案 §3 阶段二 + 流程规范 §2.3）：
1. 接收视频 → 敏感预检（上云前由 DESEN 闸门接管）。
2. PyAV（自带 ffmpeg）从视频容器抽取音轨 → 复用阶段一 Whisper 转录（transcribe_core）。
3. D13 讲解段关联帧：规则信号命中（转录含「如图/如图所示…」指代词）→ 抽取对应帧（标准库 PNG）→ 附 referenced_frame。
4. 输出：纯文本 / 带时间戳（SRT/TXT）+ 结构化 JSON/MD（D11）。
5. 哈希缓存（D12·L）、provider_meta 透明回显（D15/§4.7）。

默认本地优先、默认不上云（§4）；涉及上云/外部调用由交互确认门控制，本 CLI 不自动上云。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from modules.audio.language import parse_language_hint, parse_task_hint
from modules.audio.output import write_outputs
from modules.audio.transcribe import transcribe_core
from modules.audio.vad import TARGET_SR, load_audio
from modules.base import ExtractResult, IModule, InfoExtractError, Segment, SourceType, contract_to_result
from modules.corrector import maybe_correct
from modules.video.frames import extract_referenced_frames
from utils.hash_cache import ResultCache
from utils.io import format_seconds

LONG_THRESHOLD_SEC = 600  # 超过 10 分钟启用 VAD 分块（与音频一致，D12·J）


class VideoModule(IModule):
    name = "video"
    source_type = SourceType.VIDEO
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        use_cache = options.get("use_cache", True)
        cache = ResultCache() if use_cache else None
        model_size = options.get("model") or options.get("model_size") or "small"
        vad_threshold = options.get("vad_threshold", 700)  # min_silence_ms
        long_threshold = options.get("long_threshold", LONG_THRESHOLD_SEC)
        extract_frames = options.get("extract_frames", True)

        results: List[ExtractResult] = []
        for path in inputs:
            try:
                res = self._process_one(
                    path, options, out_dir, cache, model_size,
                    vad_threshold, long_threshold, extract_frames,
                )
                results.append(res)
            except InfoExtractError as e:
                results.append(self._error_result(path, e))
            except Exception as e:  # 兜底，绝不静默失败
                results.append(
                    self._error_result(path, InfoExtractError(f"未预期错误：{e}", recoverable=False))
                )

        # 批量聚合报告（D12·H）
        if len(inputs) > 1:
            self._write_aggregate(results, out_dir)

        return results

    def _process_one(self, path, options, out_dir, cache, model_size, vad_threshold, long_threshold, extract_frames):
        path = str(Path(path).expanduser().resolve())
        if not os.path.isfile(path):
            raise InfoExtractError(f"文件不存在：{path}", recoverable=False)

        # 语言 / 任务轻提示（D12·K）：复用音频解析
        hint = options.get("lang") or Path(path).stem
        language = parse_language_hint(hint) or options.get("language")
        task = parse_task_hint(options.get("task") or hint) or options.get("task") or "transcribe"

        cache_key_opts = {
            "lang": language, "task": task, "model": model_size,
            "provider": options.get("provider"), "vad_threshold": vad_threshold,
            "container": "video",  # 区分视频缓存键
            "vision_frames": options.get("vision", False),  # 整视频关键帧视觉分析影响结果
            "extract_frames": extract_frames,  # D13 讲解段抽帧开关影响 referenced_frame
            # D16 纠正版稿件选项（影响 text/corrected，须纳入缓存键）
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
                r.media_ref["outputs"] = write_outputs(r, out_dir, Path(path).stem)
                return r

        # 抽音轨（PyAV 对视频容器同样有效；无音轨则清晰报错，不静默失败）
        try:
            samples, sr = load_audio(path, TARGET_SR)
        except InfoExtractError as e:
            if "无音轨" in str(e):
                raise InfoExtractError(
                    "该视频无音轨，无法转录语音文案。如需识别画面内容，请用画面解读能力（阶段四）。",
                    recoverable=False,
                ) from e
            raise

        # 核心转录（复用阶段一 Whisper 管线，source 仍记为 transcript）
        result = transcribe_core(
            samples, sr, path, options, out_dir, cache,
            model_size, vad_threshold, long_threshold,
            source_type=SourceType.TRANSCRIPT,
        )
        # 标记为来自视频容器
        result.media_ref["container"] = "video"
        result.fields["container"] = "video"

        # D13：讲解段关联帧抽取（默认启用，--no-frames 可关）
        if extract_frames:
            rf = extract_referenced_frames(path, result.segments, out_dir, Path(path).stem, enabled=True)
            if rf is not None:
                # 阶段四：用视觉栈填充讲解段帧的视觉描述 / 帧上 OCR（VLM 不可用则留 None，不静默失败）
                try:
                    from modules.vision.vision_caption import fill_d13_frames

                    rf = fill_d13_frames(rf, path, out_dir, Path(path).stem, options)
                except Exception:
                    pass
                result.referenced_frame = rf
                result.fields["visual_frames"] = len(rf["frames"])
                n_cap = sum(1 for f in rf["frames"] if f.get("vision_caption"))
                if n_cap:
                    result.fields["visual_frames_captioned"] = n_cap

        # 审阅 F：整视频关键帧采样 + 视觉描述（--vision 开启；VLM 不可用则仅留帧图与 OCR 文字）
        if options.get("vision"):
            try:
                from modules.vision.vision_caption import analyze_video_frames

                kfa = analyze_video_frames(path, out_dir, Path(path).stem, options)
                if kfa.get("keyframes"):
                    result.fields["keyframe_analysis"] = kfa
            except Exception:
                pass

        # D16 交付物范式：固定原始识别为单一备查副本，再尝试生成纠正版稿件
        result.raw_text = result.text
        maybe_correct(result, options)
        # 双通道输出（D11）
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
        ok = [r for r in results if r.media_ref.get("status") == "ok"]
        errs = [r for r in results if r.media_ref.get("status") == "error"]
        cached = [r for r in results if r.media_ref.get("status") == "cached"]
        lines = ["# info-extract 视频文案 · 批量聚合报告", ""]
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
                    f"置信度={r.confidence}"
                    + (f", 讲解帧={r.fields.get('visual_frames')}" if r.fields.get('visual_frames') else "")
                    + "）"
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
        md_path = out_dir_p / "info-extract-video-report.md"
        json_path = out_dir_p / "info-extract-video-report.json"
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
                            "referenced_frame": r.referenced_frame,
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
        if results:
            results[0].media_ref["report"] = {"md": str(md_path), "json": str(json_path)}
        return {"md": str(md_path), "json": str(json_path)}


__all__ = ["VideoModule"]
