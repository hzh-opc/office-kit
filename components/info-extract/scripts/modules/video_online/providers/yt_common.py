#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 在线视频 Provider 共享工具（阶段五 / 阶段五增强：账号枚举 + cookie 适配）。

集中放置 yt-dlp 下载与枚举共用的逻辑，避免在各 Provider 间重复：
- DRM / 登录态 / 受限 关键词（命中即判定无法经 yt-dlp 直接下载 / 需 cookie）。
- build_cookie_args()：把 options 中的 cookie 配置翻译为 yt-dlp 命令行参数
  （--cookies <path> / --cookies-from-browser <browser>），贯穿枚举与下载（方案 B：抖音/小红书/B站 登录态适配）。
- detect_account_url()：识别「账号 / 合集 / 频道 / 播放列表」URL，决定是否走枚举分支
  （抖音 / 小红书 / B站 / YouTube 频道 / 通用 playlist 参数）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

# yt-dlp 探测/下载失败时命中的关键词 → 判定加密/DRM 或需登录态
DRM_KEYWORDS = (
    "drm", "encrypted", "加密", "premium", "sign in", "登录", "付费",
    "版权", "protected", "仅限", "订阅",
)

# 枚举/下载失败时命中的关键词 → 判定需登录态/cookie（抖音/小红书/B站 常需）
LOGIN_KEYWORDS = (
    "login", "登录", "sign in", "cookies", "cookie", "认证", "unavailable",
    "private", "members only", "仅粉丝", "仅限", "permission",
)


def is_drm_error(err_text: str) -> bool:
    """err_text 是否指向加密/DRM。"""
    t = (err_text or "").lower()
    return any(k in t for k in DRM_KEYWORDS)


def is_login_error(err_text: str) -> bool:
    """err_text 是否指向需登录态/cookie（账号视频常见）。"""
    t = (err_text or "").lower()
    return any(k in t for k in LOGIN_KEYWORDS)


def build_cookie_args(options: Dict) -> list:
    """把 options 中的 cookie 配置翻译为 yt-dlp 命令行参数片段。

    options 支持：
    - cookies: Netscape cookies.txt 路径
    - cookies_from_browser: 浏览器名（chrome / firefox / edge / safari / brave ...）
    两者均未设置则返回空列表（不影响无登录态的公开视频）。
    """
    args: list = []
    cookies = options.get("cookies")
    if cookies:
        args += ["--cookies", str(Path(cookies).expanduser())]
    cfb = options.get("cookies_from_browser")
    if cfb:
        args += ["--cookies-from-browser", str(cfb)]
    return args


# 账号 / 合集 / 频道 / 播放列表 URL 识别模式 → 平台名
_ACCOUNT_PATTERNS = {
    "douyin": ["douyin.com/user/", "v.douyin.com/", "iesdouyin.com/"],
    "xiaohongshu": ["xiaohongshu.com/user/profile/", "xhslink.com/"],
    "bilibili": [
        "space.bilibili.com/", "bilibili.com/channel/", "bilibili.com/list/",
        "bilibili.com/medialist/", "b23.tv/",
    ],
    "youtube_channel": ["youtube.com/c/", "youtube.com/channel/", "youtube.com/@"],
    "playlist": ["/playlist", "list=", "&list="],  # 通用播放列表参数
}


def detect_account_url(url: str) -> Optional[str]:
    """识别给定 URL 是否为「账号 / 合集 / 频道 / 播放列表」页。

    返回平台名（如 "douyin" / "xiaohongshu" / "bilibili" / "youtube_channel" / "playlist"），
    非账号类（单条视频）返回 None。单条视频 URL（如 bilibili.com/video/BVxxx、youtube.com/watch）不匹配。
    """
    u = (url or "").lower()
    for platform, subs in _ACCOUNT_PATTERNS.items():
        if any(s in u for s in subs):
            return platform
    return None


__all__ = [
    "DRM_KEYWORDS", "LOGIN_KEYWORDS", "is_drm_error", "is_login_error",
    "build_cookie_args", "detect_account_url",
]
