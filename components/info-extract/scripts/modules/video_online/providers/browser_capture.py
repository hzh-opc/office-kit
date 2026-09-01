#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 加密视频回退 Provider：BrowserCaptureProvider（外部技能，D9）。

- 定位：阶段五加密/DRM 视频的回退路径。yt-dlp 无法下载的加密内容，仅能「播放中捕获」
  （浏览器播放 + 系统录屏/音频捕获）。自动化 DRM 规避属法律灰区（§4 边界 #2），本技能
  **不实现**自动破解，而是提供「捕获入口」：复用 skill_bridge（D9）检测已安装的 browser 技能，
  并优先消费用户已产出的本地录制文件（--capture-path）。
- available()：检测到 browser 技能即视为可用（入口就绪；真实捕获仍依赖用户播放+录制动作）。
- acquire()：
  - 若 options["capture_path"] 指向一个存在的本地文件 → 直接以其为可转录媒体（external=True，
    模块不删，因该文件在沙箱外、属用户提供物）。
  - 否则 → 抛 InfoExtractError，hint 明确「播放中捕获」的法律与质量风险，并给出可操作步骤，
    绝不静默失败（流程规范 §7 / §4 边界 #2）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from modules.base import InfoExtractError
from modules.video_online.providers.base import IVideoOnlineProvider


class BrowserCaptureProvider(IVideoOnlineProvider):
    name = "browser-capture"
    source_layer = "skill"
    cost = "local"

    def _browser_skill(self) -> Optional[str]:
        # 复用 D9 协同自检：扫描已安装技能是否声明 browser 能力
        from skill_bridge import self_check

        return self_check(["browser"]).get("browser")

    def available(self) -> bool:
        # 入口就绪（需 browser 技能）；真实捕获仍依赖用户播放+录制动作
        return self._browser_skill() is not None

    def acquire(self, url: str, tmp_root: str, options: Dict) -> Dict:
        capture_path = options.get("capture_path")
        # 1) 优先消费用户已产出的本地录制文件（播放中捕获的产物）
        if capture_path and Path(capture_path).expanduser().is_file():
            cp = str(Path(capture_path).expanduser().resolve())
            return {
                "video_path": cp,
                "title": Path(cp).stem,
                "encrypted": True,
                "method": "browser-capture",
                "note": "由用户提供本地录制文件（播放中捕获）走回退；请注意法律与质量风险（§4 边界 #2），"
                        "该文件不在本技能临时沙箱内，不会被自动删除。",
                "external": True,
            }
        # 2) 否则：加密/DRM 无法自动下载，给出明确法律/质量风险与操作指引，不静默失败
        skill = self._browser_skill()
        hint = (
            "加密/DRM 视频需「播放中捕获」：请在浏览器播放该视频并用系统录屏/音频捕获工具"
            "录制为本地文件，再用 --capture-path 指定该文件重跑本技能。"
            + (f"（已检测到 browser 技能「{skill}」，亦可经其驱动浏览器自动化捕获入口。）"
               if skill else "（未检测到 browser 技能；如需浏览器自动化捕获入口，请安装 browser 技能。）")
            + " 注意：此举属法律灰区，且录制质量损失大（§4 边界 #2）。"
        )
        raise InfoExtractError(
            "加密/DRM 视频无法直接下载；仅能经「播放中捕获」处理。",
            recoverable=True,
            hint=hint,
        )


__all__ = ["BrowserCaptureProvider"]
