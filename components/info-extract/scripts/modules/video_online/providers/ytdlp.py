#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 在线视频 Provider：yt-dlp（本地内置，阶段五默认）。

- available()：探测 yt-dlp 二进制或 pip 模块是否就绪。
- acquire()：用 yt-dlp 将视频下载至调用方提供的 tmp 沙箱目录（keep=False → 处理后即删，
  不留存副本，符合 D3 「录制副本默认不保存」与审阅 G「不落盘」）；随后模块从临时文件抽音轨转录。
- 加密/DRM 检测：探针或下载失败且 stderr 命中 DRM 关键词 → 抛 InfoExtractError（recoverable），
  hint 明确「加密视频仅能播放中捕获（法律灰区，§4 边界 #2）」，由模块转浏览器捕获回退。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from modules.base import InfoExtractError
from modules.video_online.providers.base import IVideoOnlineProvider
from modules.video_online.providers.yt_common import (
    DRM_KEYWORDS, build_cookie_args, is_drm_error, is_login_error,
)


class YtDlpProvider(IVideoOnlineProvider):
    name = "yt-dlp"
    source_layer = "local_builtin"
    cost = "local"

    def available(self) -> bool:
        # yt-dlp 多为独立二进制；也兼容 pip 安装的 yt_dlp 模块
        if shutil.which("yt-dlp"):
            return True
        try:
            import yt_dlp  # noqa: F401
            return True
        except Exception:
            return False

    def _yt_dlp_bin(self) -> Optional[str]:
        if shutil.which("yt-dlp"):
            return "yt-dlp"
        try:
            import yt_dlp  # noqa: F401
            return "yt-dlp"
        except Exception:
            return None

    def acquire(self, url: str, tmp_root: str, options: Dict) -> Dict:
        bin_ = self._yt_dlp_bin()
        if bin_ is None:
            raise InfoExtractError(
                "未找到 yt-dlp（在线视频下载工具）。",
                recoverable=True,
                hint="请先安装 yt-dlp：pip install yt-dlp 或 brew install yt-dlp；"
                     "加密/DRM 视频 yt-dlp 也无法处理，需走浏览器捕获回退。",
            )

        tmp = Path(tmp_root)
        tmp.mkdir(parents=True, exist_ok=True)
        # 固定命名模板：tmp 为独立沙箱目录，下载后即唯一文件（处理后由模块整体删除）
        out_tmpl = str(tmp / "%(id)s.%(ext)s")

        # 1) 先探测（不下载）：早期识别 DRM/加密/需登录，并取标题
        try:
            probe = subprocess.run(
                [bin_, "-j", "--no-playlist", "--skip-download", url] + build_cookie_args(options),
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise InfoExtractError(
                "yt-dlp 探测超时（网络或平台策略）。",
                recoverable=True,
                hint="检查网络或稍后重试；加密平台请走浏览器捕获回退（§4 边界 #2）。",
            )
        if probe.returncode != 0:
            err = (probe.stderr or probe.stdout or "").lower()
            if is_drm_error(err):
                raise InfoExtractError(
                    "该视频疑似加密/DRM 保护，yt-dlp 无法直接下载。",
                    recoverable=True,
                    hint="加密/DRM 视频仅能「播放中捕获」处理（法律灰区，§4 边界 #2）："
                         "用浏览器播放+系统录屏/音频捕获得到本地文件，再用 --capture-path 指定重跑；"
                         "或安装 browser 技能获取浏览器自动化捕获入口。",
                )
            if is_login_error(err):
                raise InfoExtractError(
                    "该视频需登录态/cookie（抖音/小红书/B站 账号视频常需）。",
                    recoverable=True,
                    hint="用 --cookies-from-browser chrome 注入浏览器登录态，或 --cookies cookies.txt；"
                         "仅处理你有权访问的内容，且注意平台服务条款与版权（§4 边界 #2/#3）。",
                )
            raise InfoExtractError(
                f"yt-dlp 探测失败：{(probe.stderr or '')[:300]}",
                recoverable=True,
                hint="链接可能失效/需登录/平台限制；加密视频请走浏览器捕获回退。",
            )

        title = url
        try:
            info = json.loads(probe.stdout)
            title = info.get("title") or url
        except Exception:
            pass

        # 2) 正式下载（bestvideo+bestaudio/best，合并为单一容器文件）
        dl = subprocess.run(
            [bin_, "--no-playlist", "-f", "bestvideo+bestaudio/best",
             "-o", out_tmpl, "--no-warnings", url] + build_cookie_args(options),
            capture_output=True, text=True, timeout=600,
        )
        if dl.returncode != 0:
            err = (dl.stderr or dl.stdout or "").lower()
            if is_drm_error(err):
                raise InfoExtractError(
                    "该视频疑似加密/DRM 保护，yt-dlp 下载被拒。",
                    recoverable=True,
                    hint="加密/DRM 视频仅能「播放中捕获」（法律灰区，§4 边界 #2）；"
                         "用 --capture-path 指定本地录制文件或安装 browser 技能。",
                )
            if is_login_error(err):
                raise InfoExtractError(
                    "该视频需登录态/cookie（抖音/小红书/B站 账号视频常需）。",
                    recoverable=True,
                    hint="用 --cookies-from-browser chrome 注入浏览器登录态，或 --cookies cookies.txt；"
                         "仅处理你有权访问的内容，且注意平台服务条款与版权（§4 边界 #2/#3）。",
                )
            raise InfoExtractError(
                f"yt-dlp 下载失败：{(dl.stderr or '')[:300]}",
                recoverable=True,
                hint="网络/登录态/平台限制；重试或走浏览器捕获回退。",
            )

        files = [str(p) for p in tmp.iterdir() if p.is_file()]
        if not files:
            raise InfoExtractError("yt-dlp 下载未产生文件。", recoverable=True)
        video_path = sorted(files, key=lambda f: Path(f).stat().st_mtime, reverse=True)[0]
        return {
            "video_path": video_path,
            "title": title,
            "encrypted": False,
            "method": "yt-dlp",
            "note": "经 yt-dlp 下载至临时沙箱（处理后即删，不留存副本，D3/审阅 G）。",
            "external": False,
        }


__all__ = ["YtDlpProvider"]
