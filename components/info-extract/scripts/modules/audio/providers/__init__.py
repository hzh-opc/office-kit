#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频转录 Provider 包。"""

from .base import ITranscriptProvider
from .faster_whisper import FasterWhisperProvider
from .whisper_cpp import WhisperCppProvider

# D15 注册：默认优先 faster-whisper（本地内置）；whisper.cpp 作为可选本地内置
PROVIDERS = [FasterWhisperProvider, WhisperCppProvider]

__all__ = [
    "ITranscriptProvider",
    "FasterWhisperProvider",
    "WhisperCppProvider",
    "PROVIDERS",
]
