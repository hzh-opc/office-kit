#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 音频加载与 VAD/静音分块（D12·J 长文件分块）。

- load_audio：用 PyAV（自带 ffmpeg，零系统依赖）解码为单声道 16kHz float32，
  免去对系统 ffmpeg 二进制 / libsndfile 的依赖（本机实测 ffmpeg 未安装，故走 PyAV）。
- vad_split：基于能量（RMS）的静音检测分块，无需额外 VAD 模型，依赖轻、跨平台。
  长音频先按静音切分为若干段，逐段送 Whisper，避免超大音频内存溢出/超时（审阅 J）。
- faster-whisper 直接接受 float32 16k ndarray，故分块在内存切片即可，无需落盘临时文件。
"""

from __future__ import annotations

import os
from typing import List, Tuple

import numpy as np

from modules.base import InfoExtractError

TARGET_SR = 16000


def load_audio(path: str, target_sr: int = TARGET_SR) -> Tuple[np.ndarray, int]:
    """解码音频为单声道、target_sr Hz、float32[-1,1] 的 1D 数组。

    优先 PyAV（自带解码器，离线、数据不出本机）；失败给出清晰错误（不静默）。
    """
    try:
        import av
    except Exception as e:  # pragma: no cover - 依赖未装
        raise InfoExtractError(
            "缺少音频解码依赖 PyAV（av），无法读取音频。请运行技能安装脚本安装依赖。",
            recoverable=True,
            hint="执行 skill 目录下的 install.py / install.sh 完成依赖安装。",
        ) from e

    try:
        container = av.open(path)
        if not container.streams.audio:
            raise InfoExtractError(f"文件无音轨，可能不是音频：{path}", recoverable=False)
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(
            format="s16", layout="mono", rate=target_sr
        )
        chunks: List[np.ndarray] = []
        for frame in container.decode(stream):
            for res in resampler.resample(frame):
                a = res.to_ndarray().astype(np.float32) / 32768.0
                chunks.append(a.reshape(-1))
        # flush 残帧
        for res in resampler.resample(None):
            a = res.to_ndarray().astype(np.float32) / 32768.0
            chunks.append(a.reshape(-1))
        if not chunks:
            raise InfoExtractError(f"音频解码为空：{path}", recoverable=False)
        samples = np.concatenate(chunks).astype(np.float32)
        return samples, target_sr
    except InfoExtractError:
        raise
    except Exception as e:
        raise InfoExtractError(
            f"音频解码失败：{path}（{e}）", recoverable=False
        ) from e


def vad_split(
    samples: np.ndarray,
    sr: int = TARGET_SR,
    min_silence_ms: int = 700,
    silence_thresh_ratio: float = 0.03,
    frame_ms: int = 20,
    min_chunk_ms: int = 2000,
) -> List[Tuple[float, float]]:
    """能量（RMS）静音检测分块，返回 [(start_sec, end_sec), ...]（含首尾）。

    策略：按 frame 求 RMS → 相对最大值归一化 → 低于阈值的帧判为静音；
    连续静音时长 ≥ min_silence_ms 才作为切分点（取静音段中点），避免短停顿误切；
    切分后单段低于 min_chunk_ms 则与前段合并，保证每段有足够上下文。
    """
    n = len(samples)
    if n == 0:
        return []
    frame_len = max(1, int(sr * frame_ms / 1000))
    n_frames = n // frame_len
    if n_frames <= 1:
        return [(0.0, n / sr)]

    frames = samples[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt((frames.astype(np.float32) ** 2).mean(axis=1) + 1e-10)
    peak = float(rms.max()) or 1.0
    rms_norm = rms / peak
    is_silence = rms_norm < silence_thresh_ratio

    min_sil_frames = max(1, int(min_silence_ms / frame_ms))
    min_chunk_frames = max(1, int(min_chunk_ms / frame_ms))

    # 找连续静音 run，仅保留足够长的作为候选切分点（取中点）
    cuts: List[int] = []
    i = 0
    while i < n_frames:
        if is_silence[i]:
            j = i
            while j < n_frames and is_silence[j]:
                j += 1
            run = j - i
            if run >= min_sil_frames:
                mid = i + run // 2
                cuts.append(mid)
            i = j
        else:
            i += 1

    if not cuts:
        return [(0.0, n / sr)]

    # 由切分点生成段（帧索引），并合并过短段
    bounds = [0] + cuts + [n_frames]
    segs: List[Tuple[int, int]] = []
    for k in range(len(bounds) - 1):
        s, e = bounds[k], bounds[k + 1]
        if e - s < min_chunk_frames and segs:
            segs[-1] = (segs[-1][0], e)  # 与前段合并
        else:
            segs.append((s, e))

    return [(s * frame_len / sr, e * frame_len / sr) for s, e in segs]


__all__ = ["load_audio", "vad_split", "TARGET_SR"]
