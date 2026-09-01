#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 账号/合集枚举 Provider（方案 B：抖音/小红书/B站等账号视频批量处理，阶段五增强）。

- available()：探测 yt-dlp 二进制或 pip 模块是否就绪。
- enumerate(url, options)：用 yt-dlp `--flat-playlist -j` 列出账号/合集/频道下的全部视频，
  返回可下载的视频 URL 列表（不去重下载整份播放列表，逐条 video 再走 YtDlpProvider 下载）。
- cookie 适配：options 中的 cookies / cookies_from-browser 经 yt_common.build_cookie_args
  透传进枚举命令，解决抖音/小红书/B站 账号视频需登录态的问题。
- 法律/ToS 提示：账号视频批量处理仅建议用于你有权访问的内容，尊重平台条款与版权（§4 边界 #2/#3），
  不规避任何访问/版权保护机制。

设计要点（呼应方案 §0.6 可插拔 / D15 / 流程规范 §1）：
- 实现新的 IAccountEnumProvider 接口（与 IVideoOnlineProvider 并列，同属在线视频 Provider 族）。
- 枚举失败（需登录/cookie、平台限制）抛 InfoExtractError（recoverable + 可执行 hint），不静默失败。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Dict, Optional

from modules.base import InfoExtractError
from modules.video_online.providers.base import IAccountEnumProvider
from modules.video_online.providers.yt_common import (
    build_cookie_args, detect_account_url, is_login_error,
)


class YtDlpEnumProvider(IAccountEnumProvider):
    name = "yt-dlp-enum"
    source_layer = "local_builtin"
    cost = "local"

    def available(self) -> bool:
        # 与 YtDlpProvider 同依赖：yt-dlp 二进制或 pip 模块
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

    def enumerate(self, url: str, options: Dict) -> Dict:
        bin_ = self._yt_dlp_bin()
        if bin_ is None:
            raise InfoExtractError(
                "未找到 yt-dlp（在线视频枚举/下载工具）。",
                recoverable=True,
                hint="请先安装 yt-dlp：pip install yt-dlp 或 brew install yt-dlp；"
                     "账号/合集枚举与单视频下载均依赖它。",
            )

        # --flat-playlist：仅列出条目（不下载整个播放列表）；-j：每行一个 JSON 对象
        cmd = [bin_, "--flat-playlist", "-j", "--skip-download", "--no-warnings", url] \
            + build_cookie_args(options)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise InfoExtractError(
                "yt-dlp 枚举账号视频超时（网络或平台策略）。",
                recoverable=True,
                hint="检查网络或稍后重试；若平台需登录，请用 --cookies-from-browser 注入登录态。",
            )

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").lower()
            if is_login_error(err):
                raise InfoExtractError(
                    "枚举账号视频需登录态/cookie（抖音/小红书/B站 账号视频常需）。",
                    recoverable=True,
                    hint="用 --cookies-from-browser chrome 注入浏览器登录态，或 --cookies cookies.txt；"
                         "仅处理你有权访问的内容，且注意平台服务条款与版权（§4 边界 #2/#3）。",
                )
            raise InfoExtractError(
                f"yt-dlp 枚举失败：{(proc.stderr or '')[:300]}",
                recoverable=True,
                hint="链接可能失效/需登录/平台限制；公开单视频可直接传视频 URL（无需枚举）。",
            )

        entries = self._parse_entries(proc.stdout)
        if not entries:
            raise InfoExtractError(
                "账号/合集内未枚举到任何视频。",
                recoverable=True,
                hint="链接可能需登录(cookie)、账号为空或平台已变更结构；"
                     "用 --cookies-from-browser 重试，或确认链接指向账号/合集/频道页。",
            )

        platform = detect_account_url(url) or "unknown"
        return {
            "entries": entries,
            "platform": platform,
            "account": url,
            "count": len(entries),
            "note": "经 yt-dlp --flat-playlist 枚举账号/合集视频（cookie 已按需注入）；"
                    "逐条 video 将由下载管线处理，不留存副本（D3）。",
            "external": False,
        }

    @staticmethod
    def _parse_entries(stdout: str) -> list:
        """从 yt-dlp `--flat-playlist -j` 的多行 JSON 输出解析视频条目。"""
        entries = []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            # flat-playlist 模式：每个条目已是独立视频对象
            vurl = obj.get("webpage_url") or obj.get("url") or obj.get("original_url")
            if not vurl and obj.get("id"):
                # 兜底：用 id 拼一个可枚举的引用（多数平台 yt-dlp 仍能解析）
                ie = obj.get("ie_key") or obj.get("extractor") or ""
                vurl = f"{ie}::{obj['id']}" if ie else f"#id={obj['id']}"
            if not vurl:
                continue
            entries.append({
                "url": vurl,
                "title": obj.get("title") or "",
                "id": obj.get("id") or "",
            })
        return entries

    def meta(self) -> dict:
        return {
            "provider": self.name,
            "source_layer": self.source_layer,
            "cost": self.cost,
        }


__all__ = ["YtDlpEnumProvider"]
