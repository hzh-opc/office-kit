#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频采集设备摄取模块（上游需求 P1，阶段六）。

流程：按设备描述符（摄像头/HDMI 采集卡/OBS 虚拟相机/DeckLink）→ ffmpeg 设备后端
（avfoundation/dshow/v4l2/DeckLink）录制为本地文件 → 调用 video_transcript 转写。

机制二（录制-转写优先级）：默认 --live-transcribe 边采边录边转（近实时出稿）；
不可行降级 --record-and-transcribe（先录后转）；转写失败不影响录制（解耦）。
增强 A–E（共享 Recorder 实现）：健康探针（B）/ 自动分段（C）/ 断流重连（D）/ 统一摄取 manifest（E）。
产物契约：默认 D3 不留存录制副本（--keep-live 才保留）；结束写 ingestion_manifest.json。

默认本地优先、默认不上云。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.base import ExtractResult, IModule, InfoExtractError, SourceType
from modules.recorder import Recorder, find_ffmpeg

# 设备录制默认硬超时（秒）：无 --duration 时到点自动停止，避免永录到磁盘满（缺陷 #7）
DEFAULT_CAPTURE_TIMEOUT = 3600


class CaptureModule(IModule):
    name = "capture"
    source_type = SourceType.CAPTURE
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        device = options.get("device") or (inputs[0] if inputs else None)
        if not device:
            return [self._error("(device)", InfoExtractError(
                "设备摄取需提供 --device 设备描述符，如 --device \"avfoundation:1:0\"（macOS）/ "
                "--device \"USB Video\"（Windows dshow）/ --device /dev/video0（Linux v4l2）。",
                recoverable=False,
            ))]

        out_dir = options.get("out_dir") or os.getcwd()
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            return [self._error(device, InfoExtractError(
                "设备录制需要 ffmpeg（系统或隔离环境均可）。",
                recoverable=True,
                hint="安装 ffmpeg：brew install ffmpeg（macOS）/ apt install ffmpeg（Linux）/ "
                     "或设置环境变量 FFMPEG_BIN。",
            ))]

        # 设备录制：--duration 作为硬超时（到点停止）；无 --duration 时给默认硬超时（缺陷 #7 修复）
        opts = dict(options)
        duration = options.get("duration")
        if duration:
            opts["live_timeout"] = int(duration)
        else:
            opts["live_timeout"] = DEFAULT_CAPTURE_TIMEOUT
        live_transcribe = bool(options.get("live_transcribe", False))
        keep = bool(options.get("keep_live", False))
        opts["live_transcribe"] = live_transcribe
        opts["keep_live"] = keep
        opts["stem"] = self._stem(device)

        recorder = Recorder(ffmpeg, out_dir, opts, capability="capture")

        # 设备可达性预检（C8）：无设备/权限不足显式提示，不静默失败
        backend = recorder.device_backend(device)
        try:
            res = recorder.record(device=device, backend=backend)
        except InfoExtractError as e:
            return [self._error(device, e)]
        except Exception as e:  # noqa: BLE001
            return [self._error(device, InfoExtractError(f"设备录制失败：{e}", recoverable=True,
                                                         hint="确认设备已连接、有权限，且 ffmpeg 支持该后端（"
                                                              f"{backend}）。macOS 需在『系统设置→隐私与安全性→摄像头/麦克风』授权。"))]

        manifest = res["manifest"]
        manifest_path = recorder._write_manifest(manifest)
        segments = res["segments"]
        transcribed = res.get("transcribed") or {}
        used_live_transcribe = bool(res.get("live_transcribe")) and bool(transcribed)

        # 转写：边录边转已增量转写的段直接复用，仅补转缺失段（缺陷 #1 修复）
        result = recorder.transcribe_segments(segments, already_transcribed=transcribed)

        # 合并稿落盘（缺陷 #2 修复）：恢复 D11 双通道契约
        if result is not None:
            outputs = recorder.write_merged_outputs(result)
            result.media_ref["outputs"] = outputs

        recorder.cleanup(segments, manifest)

        if result is None:
            return [self._error(device, InfoExtractError(
                "设备录制未产出可转写片段（可能无音轨或录制长度不足）。",
                recoverable=True,
                hint="确认设备有音轨输出；尝试加长录制时长（--duration）。",
            ))]

        result.media_ref.update({
            "status": "ok",
            "method": "info-extract:capture",
            "device": device,
            "capture": True,
            "manifest": manifest_path,
            "no_copy_saved": not keep,
            "backend": backend,
            "live_transcribe": used_live_transcribe,
        })
        result.provider_meta = result.provider_meta or {}
        result.provider_meta.update({
            "provider": "ffmpeg-recorder",
            "capability": "capture",
            "backend": backend,
        })
        result.fields["capture"] = True
        result.fields["backend"] = backend
        result.fields["live_transcribe"] = used_live_transcribe
        return [result]

    @staticmethod
    def _stem(device: str) -> str:
        import hashlib
        import re
        s = re.sub(r"[^\w一-鿿-]+", "_", device).strip("_")
        if s:
            return "capture_" + s[:40]
        h = hashlib.md5(device.encode("utf-8")).hexdigest()[:12]
        return f"capture_{h}"

    def _error(self, device: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.TRANSCRIPT,
            text="",
            media_ref={
                "device": device, "capture": True,
                "status": "error", "error": err.message,
                "recoverable": err.recoverable, "hint": err.hint,
            },
            provider_meta={"provider": "ffmpeg-recorder", "capability": "capture"},
        )


__all__ = ["CaptureModule"]
