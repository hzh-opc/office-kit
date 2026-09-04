#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播链接录制模块（上游需求 P0，阶段六）。

流程：检测直播状态（未开始/进行中/已结束）→ 解析直连流地址（机制一：cookie/登录态）→
录制（stream-copy 优先）→ 检测结束（EOF/平台信号/超时/断流重连）→ 调用 video_transcript 转写。

机制二（录制-转写优先级）：默认 --live-transcribe 边播边录边转（近实时出稿）；
不可行降级 --live（先录制为本地文件再转写）；转写失败不影响录制（解耦）。
增强 A–E：浏览器内直录兜底（A）/ 录制健康探针（B）/ 自动分段（C）/ 断流重连（D）/ 统一摄取 manifest（E）。
产物契约：默认 D3 不留存录制副本（--keep-live 才保留）；结束写 ingestion_manifest.json。

默认本地优先、默认不上云。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.base import ExtractResult, IModule, InfoExtractError, SourceType
from modules.recorder import Recorder, find_ffmpeg


class LiveModule(IModule):
    name = "live"
    source_type = SourceType.LIVE
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            return [self._error(u, InfoExtractError(
                "直播录制需要 ffmpeg（系统或隔离环境均可，无需额外安装）。",
                recoverable=True,
                hint="安装 ffmpeg：brew install ffmpeg（macOS）/ apt install ffmpeg（Linux）/ "
                     "或设置环境变量 FFMPEG_BIN 指向 ffmpeg 可执行文件。",
            )) for u in inputs]

        live_transcribe = bool(options.get("live_transcribe", False))
        keep = bool(options.get("keep_live", False))

        results: List[ExtractResult] = []
        for url in inputs:
            try:
                results.append(self._process_one(url, options, out_dir, ffmpeg, live_transcribe, keep))
            except InfoExtractError as e:
                results.append(self._error(url, e))
            except Exception as e:  # noqa: BLE001 兜底，绝不静默失败
                results.append(self._error(url, InfoExtractError(f"未预期错误：{e}", recoverable=False)))
        return results

    def _process_one(self, url, options, out_dir, ffmpeg, live_transcribe, keep) -> ExtractResult:
        url = (url or "").strip()
        if not url:
            raise InfoExtractError("空直播 URL。", recoverable=False)

        recorder = Recorder(ffmpeg, out_dir, {**options, "live_transcribe": live_transcribe,
                                              "keep_live": keep, "stem": self._stem(url)},
                            capability="live")

        # 直播状态检测（L2，best-effort）：解析直连流地址；解析失败不阻断，回退 ffmpeg 直连原 URL
        resolved_url, meta = recorder.resolve_live_url(url)

        # 录制（含分段/重连/健康探针/边录边转）；结束写 manifest（recorder 内部已写，此处不重复写）
        try:
            rec = recorder.record(url=resolved_url)
        except InfoExtractError as e:
            # 录制失败（可能需登录态）→ 尝试 browser 取流回退（机制一，缺陷 #3 补齐）
            return self._browser_fallback(url, options, out_dir, ffmpeg, live_transcribe, keep, e)

        manifest = rec["manifest"]
        manifest_path = recorder._write_manifest(manifest)
        segments = rec["segments"]
        transcribed = rec.get("transcribed") or {}
        used_live_transcribe = bool(rec.get("live_transcribe")) and bool(transcribed)

        # 转写（复用 video_transcript；先录后转 或 边录边转 的最终合并）
        # 边录边转期间已增量转写的段直接复用，仅补转缺失段（缺陷 #1 修复）
        result = recorder.transcribe_segments(segments, already_transcribed=transcribed)

        # 合并稿落盘（缺陷 #2 修复）：恢复 D11 双通道契约
        if result is not None:
            outputs = recorder.write_merged_outputs(result)
            result.media_ref["outputs"] = outputs

        # D3 不留存：转写完成后再删录制副本
        recorder.cleanup(segments, manifest)

        if result is None:
            raise InfoExtractError(
                "直播录制未产出可转写片段（可能直播立即结束/无音轨/源不可用）。",
                recoverable=True,
                hint="确认直播有音轨且已开始；检查网络与登录态（--cookies-from-browser）。",
            )

        # 直播专属元数据 + provider_meta 透明回显（L14）
        result.media_ref.update({
            "status": "ok",
            "method": "info-extract:live",
            "source_url": url,
            "live": True,
            "manifest": manifest_path,
            "no_copy_saved": not keep,
            "acquire_method": meta.get("method"),
            "live_transcribe": used_live_transcribe,
        })
        result.provider_meta = result.provider_meta or {}
        result.provider_meta.update({
            "provider": "ffmpeg-recorder",
            "capability": "live",
            "acquire_method": meta.get("method"),
        })
        result.fields["live"] = True
        result.fields["acquire_method"] = meta.get("method")
        result.fields["live_transcribe"] = used_live_transcribe
        return result

    def _browser_fallback(self, url, options, out_dir, ffmpeg, live_transcribe, keep,
                          orig_err: InfoExtractError) -> ExtractResult:
        """机制一（鉴权直播）：录制失败时回退 browser 技能持登录态取流（缺陷 #3 补齐）。

        参照 video_online 的 BrowserCaptureProvider 约定：
        1) 检测 browser 技能是否可用（skill_bridge.self_check(["browser"])）；
        2) 若用户已提供浏览器/播放器产出的本地录制文件（--capture-path），直接转写该文件；
        3) 否则给出明确操作指引（持登录态取流），绝不静默失败。
        """
        capture_path = options.get("capture_path")
        # 1) 用户已产出本地录制文件 → 直接转写
        if capture_path and Path(capture_path).expanduser().is_file():
            cp = str(Path(capture_path).expanduser().resolve())
            recorder = Recorder(ffmpeg, out_dir, {**options, "keep_live": keep,
                                                  "stem": self._stem(url)},
                                capability="live")
            result = recorder.transcribe_segments([cp])
            if result is not None:
                outputs = recorder.write_merged_outputs(result)
                result.media_ref.update({
                    "status": "ok",
                    "method": "info-extract:live",
                    "source_url": url,
                    "live": True,
                    "acquire_method": "browser-capture",
                    "no_copy_saved": True,
                    "manifest": None,
                    "outputs": outputs,
                })
                result.provider_meta = result.provider_meta or {}
                result.provider_meta.update({
                    "provider": "browser-capture",
                    "capability": "live",
                    "acquire_method": "browser-capture",
                })
                result.fields["live"] = True
                result.fields["acquire_method"] = "browser-capture"
                return result
            # 本地文件转写失败 → 落入下方统一错误指引

        # 2) 检测 browser 技能，给出持登录态取流指引（不静默失败）
        try:
            from skill_bridge import self_check
            skill = self_check(["browser"]).get("browser")
        except Exception:  # noqa: BLE001
            skill = None
        hint = (
            f"直播录制失败（{orig_err.message}）。该直播可能需登录态或强鉴权。"
        )
        if skill:
            hint += (
                f"已检测到 browser 技能「{skill}」：可经其驱动浏览器持登录态打开直播页"
                "并录制（页内播放 + 系统录屏/音频捕获），录制为本地文件后用 --capture-path 指定重跑，"
                "或用 --cookies-from-browser 导出登录态后重试直连录制。"
            )
        else:
            hint += (
                "未检测到 browser 技能；建议安装 browser 技能以持登录态取流，"
                "或先导出登录态（--cookies-from-browser），或手动录屏后用 --capture-path 指定。"
            )
        hint += " 仅处理你有权访问的内容（§4 边界 #2/#3）。"
        return self._error(url, InfoExtractError(
            f"直播录制失败：{orig_err.message}",
            recoverable=True,
            hint=hint,
        ))

    @staticmethod
    def _stem(url: str) -> str:
        from modules.video_online import VideoOnlineModule
        return "live_" + VideoOnlineModule._stem(url, None)

    def _error(self, url: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.TRANSCRIPT,
            text="",
            media_ref={
                "url": url, "live": True,
                "status": "error", "error": err.message,
                "recoverable": err.recoverable, "hint": err.hint,
            },
            provider_meta={"provider": "ffmpeg-recorder", "capability": "live"},
        )


__all__ = ["LiveModule"]
