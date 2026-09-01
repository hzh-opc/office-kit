#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · whisper.cpp Provider（可选本地内置①，D15 可插拔）。

- 经子进程调用 whisper.cpp 命令行（GGML，可纯 CPU / Metal / CUDA，无 torch 依赖）。
- 仅当检测到 whisper 二进制 + 模型文件时才 available()=True（默认不可用，不干扰默认链路）。
- 环境变量：WHISPER_CPP_BIN（二进制路径）、WHISPER_CPP_MODEL（ggml 模型路径）。
- 这是「可插拔 Provider」的示范实现：证明底层引擎可替换，而不改写主入口。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from modules.audio.providers.base import ITranscriptProvider
from modules.base import InfoExtractError, Segment


class WhisperCppProvider(ITranscriptProvider):
    name = "whisper.cpp"
    source_layer = "local_builtin"
    cost = "local"

    def _bin(self) -> Optional[str]:
        if env := os.environ.get("WHISPER_CPP_BIN"):
            return env if Path(env).exists() else None
        return shutil.which("whisper-cli") or shutil.which("whisper") or shutil.which("main")

    def _model(self) -> Optional[str]:
        m = os.environ.get("WHISPER_CPP_MODEL")
        return m if (m and Path(m).exists()) else None

    def available(self) -> bool:
        return bool(self._bin() and self._model())

    def transcribe(
        self,
        audio,
        language: Optional[str] = None,
        task: Optional[str] = None,
        model_size: str = "small",
        **opts,
    ) -> Tuple[List[Segment], dict]:
        bin_path = self._bin()
        model_path = self._model()
        if not bin_path or not model_path:
            raise InfoExtractError(
                "whisper.cpp 未配置（需 WHISPER_CPP_BIN 与 WHISPER_CPP_MODEL）",
                recoverable=True,
                hint="改用默认 faster-whisper provider，或配置 whisper.cpp 环境变量。",
            )
        # 仅接受文件路径（whisper.cpp 不吃 ndarray）；若是 ndarray 需先写临时 wav
        audio_path = audio
        if not isinstance(audio, (str, Path)):
            raise InfoExtractError(
                "whisper.cpp provider 仅接受文件路径（分块场景请用 faster-whisper）",
                recoverable=True,
            )
        out_dir = Path(audio_path).parent
        cmd = [
            bin_path, "-m", model_path, "-f", str(audio_path),
            "--output-txt", "--output-srt", "-of", str(out_dir / "_whispercpp_out"),
        ]
        if language:
            cmd += ["-l", language]
        if task == "translate":
            cmd += ["-tr"]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise InfoExtractError(f"whisper.cpp 执行失败：{e.stderr}", recoverable=True) from e

        srt_path = out_dir / "_whispercpp_out.srt"
        segments = self._parse_srt(srt_path) if srt_path.exists() else []
        return segments, {"detected_language": language or "unknown", "model_size": model_path}

    @staticmethod
    def _parse_srt(path: Path) -> List[Segment]:
        """极简 SRT 解析（whisper.cpp 输出规范）。"""
        text = path.read_text(encoding="utf-8", errors="ignore")
        segs: List[Segment] = []
        blocks = re.split(r"\n\s*\n", text.strip())
        ts_re = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")
        for block in blocks:
            m = ts_re.search(block)
            if not m:
                continue
            def sec(gi):
                h, mi, s, ms = (int(block.group(gi + 0 + x)) for x in range(4))  # placeholder
            # 简单计算
            def to_sec(a, b, c, d):
                return a * 3600 + b * 60 + c + d / 1000.0
            start = to_sec(*(int(block.group(i)) for i in (1, 2, 3, 4)))
            end = to_sec(*(int(block.group(i)) for i in (5, 6, 7, 8)))
            body = block[ts_re.search(block).end():].strip()
            segs.append(Segment(start=start, end=end, text=body))
        return segs


__all__ = ["WhisperCppProvider"]
