#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 在线/加密视频 Provider 统一接口（D15 可插拔架构，阶段五）。

在线/加密视频的底层引擎是可替换 Provider。默认 Provider = 本地 yt-dlp（下载）；
加密/DRM 或 yt-dlp 失败时回退 BrowserCaptureProvider（播放中捕获，依赖 browser 技能，D9）。
所有 Provider 实现 IVideoOnlineProvider，统一签名，主入口不感知具体实现。

设计要点（呼应方案 §3 阶段五 / 流程规范 §2.4 / §4 边界 #2·#3 / 审阅 G）：
- acquire() 获取「可转录媒体」：返回临时沙箱内的视频路径（模块处理后即删，不留存副本，D3）
  或用户提供的本地录制文件路径（external=True，模块不删）。
- 加密/DRM 视频 yt-dlp 无法处理 → 抛 InfoExtractError（recoverable + 法律/质量风险 hint），
  由模块转浏览器捕获回退，绝不静默失败（D9 / 流程规范 §7）。
- provider_meta 透明回显（D15 / §4.7）：用了哪个 provider、是否上云（此处均 local）。
"""

from __future__ import annotations

from typing import Dict

from modules.base import InfoExtractError


class IVideoOnlineProvider:
    """在线/加密视频 Provider 接口。

    - name / source_layer：供 provider_meta 透明回显（D15 / §4.7）。
    - available()：运行前探测依赖/二进制是否就绪，缺失即降级、不静默失败。
    - acquire()：获取可转录媒体；返回结构见类 docstring；失败抛 InfoExtractError。
    """

    name: str = ""
    source_layer: str = "local_builtin"  # local_builtin / skill / connector
    cost: str = "local"  # local / cloud（均本地，cost=local）

    def available(self) -> bool:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def acquire(self, url: str, tmp_root: str, options: Dict) -> Dict:
        """获取在线/加密视频的可转录媒体。

        返回：
        {
          "video_path": str,          # tmp 内临时文件（模块负责清理）或外部录制文件（external=True）
          "title": str,              # 视频标题（用于命名/语言轻提示）
          "encrypted": bool,         # 是否为加密/DRM 内容
          "method": str,             # "yt-dlp" / "browser-capture"
          "note": str,               # 透明说明（如「下载至临时沙箱，处理后即删」）
          "external": bool,          # True=video_path 在沙箱外（如用户 capture_path，模块不删）
        }
        获取失败（如 DRM 加密且无捕获回退）抛 InfoExtractError（recoverable + hint）。
        """
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


class IAccountEnumProvider:
    """账号/合集枚举 Provider 接口（方案 B：抖音/小红书/B站 等账号视频批量处理，阶段五增强）。

    - name / source_layer：供 provider_meta 透明回显（D15 / §4.7）。
    - available()：运行前探测依赖/二进制是否就绪，缺失即降级、不静默失败。
    - enumerate()：给定账号/合集/频道 URL，列出其下全部视频条目（不去重下载整份播放列表）。
      返回结构：
      {
        "entries": [{"url":..., "title":..., "id":...}, ...],  # 可下载视频 URL 列表
        "platform": str,    # 平台名（douyin/xiaohongshu/bilibili/...）
        "account": str,     # 原始账号/合集 URL
        "count": int,       # 枚举到的视频数
        "note": str,        # 透明说明
        "external": bool,   # 始终 False（枚举不产出本地文件）
      }
      枚举失败（需登录态/cookie、平台限制、空账号）抛 InfoExtractError（recoverable + hint）。
    """

    name: str = ""
    source_layer: str = "local_builtin"
    cost: str = "local"

    def available(self) -> bool:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def enumerate(self, url: str, options: Dict) -> Dict:
        """枚举账号/合集/频道下的全部视频，返回可下载视频 URL 列表。"""
        raise NotImplementedError

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


__all__ = ["IVideoOnlineProvider", "IAccountEnumProvider"]
