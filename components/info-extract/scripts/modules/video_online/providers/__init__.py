#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 在线/加密视频 Provider 注册表（D15）。

优先级（列表顺序 → 默认优先）：
1. yt-dlp（本地内置，非加密在线视频首选下载）
2. browser-capture（加密/DRM 回退，依赖 browser 技能，D9）

账号/合集枚举 Provider（方案 B：抖音/小红书/B站 账号视频批量处理）单列 ENUM_PROVIDERS，
由 VideoOnlineModule 在识别到账号 URL（或显式 --playlist）时调用，枚举出视频 URL 列表后
逐条走上述下载管线。
"""

from __future__ import annotations

from modules.video_online.providers.browser_capture import BrowserCaptureProvider
from modules.video_online.providers.ytdlp import YtDlpProvider
from modules.video_online.providers.ytdlp_enum import YtDlpEnumProvider, detect_account_url

PROVIDERS = [YtDlpProvider, BrowserCaptureProvider]
ENUM_PROVIDERS = [YtDlpEnumProvider]

__all__ = ["PROVIDERS", "ENUM_PROVIDERS", "YtDlpEnumProvider", "detect_account_url"]
