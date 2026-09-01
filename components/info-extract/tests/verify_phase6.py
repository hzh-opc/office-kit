#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段五增强（方案 B：账号/合集枚举 + cookie 适配）验证脚本。

不依赖 yt-dlp / 浏览器 / 真实 Whisper 模型即可验证方案 B 核心逻辑：
  - 账号/合集 URL 识别（抖音/小红书/B站 账号页、频道、播放列表；单条视频不误判）
  - Provider 注册（VIDEO_ONLINE_ENUM → yt-dlp-enum，D15）
  - YtDlpEnumProvider 单元（available/meta；enumerate 解析 --flat-playlist 多行 JSON；
    需登录态→提示 --cookies；空账号→明确错误，不静默失败）
  - cookie 透传（yt_common.build_cookie_args：--cookies / --cookies-from-browser）
  - 集成：账号 URL → 枚举出视频 URL 列表 → 逐条走下载+转录管线（mock）
    → 每条结果 media_ref.from_account 标注、provider_meta.enum_provider 透明回显
    → 聚合报告含「账号/合集枚举明细」与 ToS 提示
  - 强制 --playlist 覆盖单视频 URL 也走枚举
  - 枚举 Provider 不可用（缺 yt-dlp）→ 账号级错误，引导安装
  - router 选项（--cookies/--cookies-from-browser/--playlist）+ router --check 显示枚举能力
  - 账号批量防风控限速：相邻视频随机间隔（time.sleep 被调用）/ --no-throttle 关闭 / --enum-limit 数量上限

运行：python tests/verify_phase6.py
退出码：0=全部通过；非 0=存在失败项。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import fractions  # noqa: E402

import av  # noqa: E402
import numpy as np  # noqa: E402

import provider_registry  # noqa: E402
import router  # noqa: E402
import modules.video_online as vo_mod  # noqa: E402
from modules.audio.language import parse_language_hint  # noqa: E402
from modules.audio.providers.base import ITranscriptProvider  # noqa: E402
from modules.audio.vad import TARGET_SR  # noqa: E402
from modules.base import ExtractResult, InfoExtractError, Segment, SourceType  # noqa: E402
from modules.video_online.providers.base import IAccountEnumProvider  # noqa: E402
from modules.video_online.providers.ytdlp_enum import YtDlpEnumProvider, detect_account_url  # noqa: E402
from modules.video_online.providers.yt_common import build_cookie_args  # noqa: E402
from utils.io import is_url  # noqa: E402

_PASS, _FAIL = [], []
def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail and not cond else ""))


def make_video_fixture(path: Path, with_audio: bool = True) -> None:
    """生成含音轨的合成 mp4（mpeg4 视频 + mp3 音频，约 3s），供在线/加密全链路复用。"""
    if path.exists():
        path.unlink()
    c = av.open(str(path), "w")
    vs = c.add_stream("mpeg4", rate=25)
    vs.width, vs.height, vs.pix_fmt = 64, 64, "yuv420p"
    if with_audio:
        au = c.add_stream("mp3", rate=16000)
        au.layout, au.sample_rate = "mono", 16000
    tb = fractions.Fraction(1, 25)
    for i in range(75):
        f = av.VideoFrame(64, 64, "yuv420p")
        f.pts, f.time_base = i, tb
        arr = f.to_ndarray()
        arr[:] = (i * 3) % 255
        for pkt in vs.encode(f):
            c.mux(pkt)
    if with_audio:
        total = 16000 * 3
        done = 0
        while done < total:
            n = min(1600, total - done)
            af = av.AudioFrame(format="fltp", layout="mono", samples=n)
            af.sample_rate, af.pts, af.time_base = 16000, done, fractions.Fraction(1, 16000)
            a = af.to_ndarray()
            t = np.arange(a.shape[1]) / 16000.0
            a[:] = (np.sin(2 * np.pi * 220 * t) * 0.3).astype(np.float32)
            done += n
            for pkt in au.encode(af):
                c.mux(pkt)
    for pkt in vs.encode(None):
        c.mux(pkt)
    if with_audio:
        for pkt in au.encode(None):
            c.mux(pkt)
    c.close()


class FakeProvider(ITranscriptProvider):
    """绕过 Whisper 模型下载的 fake 转录，输出含指代词段（触发 D13）。"""
    name = "fake"
    source_layer = "local_builtin"
    cost = "local"

    def available(self):
        return True

    def transcribe(self, audio, language=None, task=None, model_size="small", **opts):
        dur = len(audio) / TARGET_SR if isinstance(audio, np.ndarray) else 3.0
        segs = [
            Segment(0.0, 1.5, "今天我们开始讲解项目背景。"),
            Segment(1.5, 3.0, "如图所示，这张流程图说明了整体架构。"),
        ]
        info = {"detected_language": language or "zh", "duration": round(dur, 2), "model_size": model_size}
        return segs, info


class MockVideoOnlineProvider:
    """Mock 在线视频 Provider：返回本地 fixture 视频（external=True，模块不删）。"""
    name = "mock-online"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, *, available=True, video_path=None, external=True, method="yt-dlp"):
        self._available = available
        self._video_path = video_path
        self._external = external
        self._method = method

    def available(self):
        return self._available

    def meta(self):
        return {"provider": self.name, "source_layer": self.source_layer, "cost": self.cost}

    def acquire(self, url, tmp_root, options):
        return {
            "video_path": self._video_path,
            "title": "MockOnlineTitle",
            "encrypted": False,
            "method": self._method,
            "note": "MOCK",
            "external": self._external,
        }


class MockEnumProvider(IAccountEnumProvider):
    """Mock 账号/合集枚举 Provider：返回固定视频条目列表。"""
    name = "mock-enum"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, *, available=True, entries=None, raise_err=None):
        self._available = available
        self._entries = entries if entries is not None else [
            {"url": "https://v.douyin.com/v1", "title": "视频A", "id": "v1"},
            {"url": "https://v.douyin.com/v2", "title": "视频B", "id": "v2"},
        ]
        self._raise_err = raise_err

    def available(self):
        return self._available

    def meta(self):
        return {"provider": self.name, "source_layer": self.source_layer, "cost": self.cost}

    def enumerate(self, url, options):
        if self._raise_err is not None:
            raise self._raise_err
        return {
            "entries": self._entries,
            "platform": detect_account_url(url) or "unknown",
            "account": url,
            "count": len(self._entries),
            "note": "MOCK",
            "external": False,
        }


def _fake_get_provider(fake_transcript, fake_online, fake_enum):
    def gp(cap, name=None):
        if cap == SourceType.TRANSCRIPT:
            return fake_transcript
        if cap == SourceType.VIDEO_ONLINE:
            return fake_online
        if cap == SourceType.VIDEO_ONLINE_ENUM:
            return fake_enum
        return None
    return gp


# ---------- 测试 ----------
def test_account_url_detection():
    print("\n[1] 账号/合集 URL 识别（detect_account_url）")
    check("抖音账号页→douyin", detect_account_url("https://www.douyin.com/user/MXoabc") == "douyin")
    check("抖音短链→douyin", detect_account_url("https://v.douyin.com/iRabc") == "douyin")
    check("小红书账号页→xiaohongshu", detect_account_url("https://www.xiaohongshu.com/user/profile/abc") == "xiaohongshu")
    check("B站空间→bilibili", detect_account_url("https://space.bilibili.com/123/video") == "bilibili")
    check("B站合集→bilibili", detect_account_url("https://www.bilibili.com/list/ml123") == "bilibili")
    check("YouTube 频道→youtube_channel", detect_account_url("https://www.youtube.com/@someone") == "youtube_channel")
    check("通用 playlist 参数→playlist", "playlist" in (detect_account_url("https://x.com/playlist?list=1") or ""))
    check("B站单视频→None（不误判）", detect_account_url("https://www.bilibili.com/video/BV1xx") is None)
    check("YouTube 单视频→None（不误判）", detect_account_url("https://www.youtube.com/watch?v=1") is None)
    check("普通文件 URL→None", detect_account_url("https://example.com/a.mp4") is None)


def test_provider_registry_enum():
    print("\n[2] Provider 注册（VIDEO_ONLINE_ENUM → yt-dlp-enum，D15）")
    aps = provider_registry.available_providers(SourceType.VIDEO_ONLINE_ENUM)
    names = [p["name"] for p in aps]
    check("注册含 yt-dlp-enum", "yt-dlp-enum" in names)
    ep = provider_registry.get_provider(SourceType.VIDEO_ONLINE_ENUM, name="yt-dlp-enum")
    check("get_provider(VIDEO_ONLINE_ENUM,yt-dlp-enum) 命中", ep is not None and ep.name == "yt-dlp-enum")


def test_enum_provider_unit():
    print("\n[3] YtDlpEnumProvider 单元（available/meta/enumerate，mock subprocess）")
    p = YtDlpEnumProvider()
    try:
        avail = p.available()
        ok_avail = isinstance(avail, bool)
    except Exception:
        ok_avail = False
    check("available() 返回 bool 且不抛异常", ok_avail)
    meta = p.meta()
    check("meta 含 provider=yt-dlp-enum / cost=local",
          meta.get("provider") == "yt-dlp-enum" and meta.get("cost") == "local")

    # 单测环境无真实 yt-dlp：桩出二进制探测，使 enumerate 进入真实解析分支
    p._yt_dlp_bin = lambda: "yt-dlp"  # type: ignore[assignment]

    # enumerate 解析 --flat-playlist 多行 JSON
    json_lines = "\n".join([
        json.dumps({"id": "v1", "title": "视频A", "webpage_url": "https://v.douyin.com/v1"}),
        json.dumps({"id": "v2", "title": "视频B", "webpage_url": "https://v.douyin.com/v2"}),
    ])
    fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=json_lines, stderr="")
    with patch.object(subprocess, "run", return_value=fake_proc):
        res = p.enumerate("https://www.douyin.com/user/ABC", {})
    check("enumerate 返回 2 条视频", len(res.get("entries") or []) == 2, str(res))
    check("enumerate 记录 platform=douyin", res.get("platform") == "douyin")
    check("enumerate 条目含 webpage_url", res["entries"][0]["url"] == "https://v.douyin.com/v1")

    # 需登录态 → InfoExtractError 且 hint 含 cookie 引导
    login_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="ERROR: Please login to view this video (cookies required)")
    raised = None
    with patch.object(subprocess, "run", return_value=login_proc):
        try:
            p.enumerate("https://www.douyin.com/user/ABC", {})
        except InfoExtractError as e:
            raised = e
    check("需登录态→InfoExtractError（不静默失败）", raised is not None)
    check("hint 含 cookies-from-browser 引导", raised is not None and "cookies-from-browser" in (raised.hint or ""))

    # 空账号（无条目）→ 明确错误
    empty_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    raised2 = None
    with patch.object(subprocess, "run", return_value=empty_proc):
        try:
            p.enumerate("https://www.douyin.com/user/EMPTY", {})
        except InfoExtractError as e:
            raised2 = e
    check("空账号→InfoExtractError（未静默放过）", raised2 is not None)


def test_cookie_args():
    print("\n[4] cookie 透传（build_cookie_args）")
    check("cookies 文件 → --cookies", build_cookie_args({"cookies": "/tmp/c.txt"}) == ["--cookies", "/tmp/c.txt"])
    check("cookies_from_browser → --cookies-from-browser",
          build_cookie_args({"cookies_from_browser": "chrome"}) == ["--cookies-from-browser", "chrome"])
    check("两者皆有", build_cookie_args({"cookies": "/tmp/c.txt", "cookies_from_browser": "firefox"})
          == ["--cookies", "/tmp/c.txt", "--cookies-from-browser", "firefox"])
    check("均未设置→空列表（不影响公开视频）", build_cookie_args({}) == [])


def test_account_enum_pipeline(fixture: Path, td: Path):
    print("\n[5] 账号 URL → 枚举 → 逐条下载+转录（mock 全链路）")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    mock_enum = MockEnumProvider(available=True)
    fake_gp = _fake_get_provider(FakeProvider(), mock_online, mock_enum)
    with patch.object(provider_registry, "get_provider", fake_gp):
        results = vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None, "cookies": None, "cookies_from_browser": None, "enumerate": False},
        )
    ok = [r for r in results if r.media_ref.get("status") == "ok"]
    check("枚举出 2 条 → 2 个 ok 结果", len(ok) == 2, str([r.media_ref.get("status") for r in results]))
    check("每条 media_ref.from_account 标注来源账号",
          all(r.media_ref.get("from_account") == "https://www.douyin.com/user/ABC" for r in ok))
    check("每条 provider_meta.enum_provider=yt-dlp-enum",
          all(r.provider_meta.get("enum_provider") == "yt-dlp-enum" for r in ok))
    check("每条 fields.online=True", all(r.fields.get("online") is True for r in ok))
    # 聚合报告
    report_md = td / "info-extract-video-online-report.md"
    check("聚合报告已生成（账号枚举场景）", report_md.exists())
    if report_md.exists():
        md = report_md.read_text(encoding="utf-8")
        check("报告含『账号/合集枚举明细』", "账号/合集枚举明细" in md)
        check("报告含 ToS 提示（§4 边界 #2/#3）", "服务条款" in md or "版权" in md)
        check("报告含展开的视频 URL", "https://v.douyin.com/v1" in md)
    report_json = td / "info-extract-video-online-report.json"
    if report_json.exists():
        data = json.loads(report_json.read_text(encoding="utf-8"))
        check("JSON 报告含 account_enum", "account_enum" in data and len(data["account_enum"]) == 1)
        check("JSON 报告条目含 from_account", data["items"][0].get("from_account") == "https://www.douyin.com/user/ABC")


def test_force_playlist_on_single(fixture: Path, td: Path):
    print("\n[6] 强制 --playlist 覆盖单视频 URL 也走枚举")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    mock_enum = MockEnumProvider(available=True, entries=[
        {"url": "https://example.com/coll/a", "title": "A", "id": "a"},
    ])
    fake_gp = _fake_get_provider(FakeProvider(), mock_online, mock_enum)
    with patch.object(provider_registry, "get_provider", fake_gp):
        results = vo_mod.VideoOnlineModule().run(
            ["https://example.com/collection"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None, "cookies": None, "cookies_from_browser": None, "enumerate": True},
        )
    ok = [r for r in results if r.media_ref.get("status") == "ok"]
    check("强制 --playlist 仍展开为 1 条并 ok", len(ok) == 1, str([r.media_ref.get("status") for r in results]))
    check("展开来源标注 from_account", ok and ok[0].media_ref.get("from_account") == "https://example.com/collection")


def test_enum_provider_unavailable(fixture: Path, td: Path):
    print("\n[7] 枚举 Provider 不可用（缺 yt-dlp）→ 账号级错误，引导安装")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    # VIDEO_ONLINE_ENUM 返回 None（枚举 provider 不可用）
    fake_gp = _fake_get_provider(FakeProvider(), mock_online, None)
    with patch.object(provider_registry, "get_provider", fake_gp):
        results = vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None, "cookies": None, "cookies_from_browser": None, "enumerate": False},
        )
    check("账号 URL 产生 1 条 error 结果（不静默失败）", len(results) == 1)
    check("error 状态", results[0].media_ref.get("status") == "error")
    check("hint 引导安装 yt-dlp", "yt-dlp" in (results[0].media_ref.get("hint") or ""))


def test_enum_login_failure(fixture: Path, td: Path):
    print("\n[8] 枚举需登录态但无 cookie → 账号级错误提示 cookie 引导")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    login_err = InfoExtractError("枚举账号视频需登录态/cookie", recoverable=True,
                                 hint="用 --cookies-from-browser chrome 注入登录态（§4 边界 #2/#3）。")
    mock_enum = MockEnumProvider(available=True, raise_err=login_err)
    fake_gp = _fake_get_provider(FakeProvider(), mock_online, mock_enum)
    with patch.object(provider_registry, "get_provider", fake_gp):
        results = vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None, "cookies": None, "cookies_from_browser": None, "enumerate": False},
        )
    check("产生 1 条 error 结果", len(results) == 1 and results[0].media_ref.get("status") == "error")
    check("hint 含 cookies-from-browser 引导", "cookies-from-browser" in (results[0].media_ref.get("hint") or ""))


def test_router_options():
    print("\n[9] router.build_options 含 cookie/枚举选项（方案 B）")
    import argparse
    ns = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier=None, no_ocr_vision=False, vision=False, capture_path=None,
        cookies="/tmp/c.txt", cookies_from_browser="chrome", playlist=True,
        enum_interval=5.0, enum_limit=10, no_throttle=True,
    )
    opts = router.build_options(ns)
    check("build_options 含 cookies", opts.get("cookies") == "/tmp/c.txt")
    check("build_options 含 cookies_from_browser", opts.get("cookies_from_browser") == "chrome")
    check("build_options 含 enumerate(=playlist)", opts.get("enumerate") is True)
    check("build_options 含 enum_interval(=5.0)", opts.get("enum_interval") == 5.0)
    check("build_options 含 enum_limit(=10)", opts.get("enum_limit") == 10)
    check("build_options 含 no_throttle(=True)", opts.get("no_throttle") is True)
    # 默认：均为 None/False
    ns2 = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier=None, no_ocr_vision=False, vision=False, capture_path=None,
        cookies=None, cookies_from_browser=None, playlist=False,
        enum_interval=3.0, enum_limit=None, no_throttle=False,
    )
    opts2 = router.build_options(ns2)
    check("build_options 默认 cookies/cookies_from_browser=None、enumerate=False",
          opts2.get("cookies") is None and opts2.get("cookies_from_browser") is None
          and opts2.get("enumerate") is False)
    check("build_options 默认 enum_interval=3.0 / enum_limit=None / no_throttle=False",
          opts2.get("enum_interval") == 3.0 and opts2.get("enum_limit") is None
          and opts2.get("no_throttle") is False)


def test_router_check():
    print("\n[10] router.py --check（含 video_online_enum 能力）")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "router.py"), "--check"],
        capture_output=True, text=True, cwd=str(SCRIPT_DIR.parent),
    )
    check("router --check 退出码 0", r.returncode == 0, r.stderr[-300:])
    check("--check 输出含 video_online_enum 能力", "video_online_enum" in r.stdout.lower())


def test_account_enum_throttle(fixture: Path, td: Path):
    print("\n[11] 账号批量防风控限速（随机间隔 / --no-throttle / --enum-limit）")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    mock_enum = MockEnumProvider(available=True, entries=[
        {"url": "https://v.douyin.com/v1", "title": "A", "id": "1"},
        {"url": "https://v.douyin.com/v2", "title": "B", "id": "2"},
        {"url": "https://v.douyin.com/v3", "title": "C", "id": "3"},
    ])
    fake_gp = _fake_get_provider(FakeProvider(), mock_online, mock_enum)
    base_opts = {"out_dir": str(td), "use_cache": False, "provider": None,
                 "lang": None, "task": None, "model": "small", "vad_threshold": 700,
                 "long_threshold": 600, "extract_frames": True, "vision": False,
                 "capture_path": None, "cookies": None, "cookies_from_browser": None,
                 "enumerate": False}

    # ① 限速开启：相邻视频间应调用 time.sleep（首条不 sleep，故 3 条→2 次）
    with patch("time.sleep") as mocksleep, patch.object(provider_registry, "get_provider", fake_gp):
        results = vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {**base_opts, "enum_interval": 2.0, "no_throttle": False},
        )
    ok = [r for r in results if r.media_ref.get("status") == "ok"]
    check("3 条视频全部 ok", len(ok) == 3, str([r.media_ref.get("status") for r in results]))
    check("限速开启→time.sleep 被调用 2 次（相邻视频间隔）", mocksleep.call_count == 2,
          f"call_count={mocksleep.call_count}")
    report_md = td / "info-extract-video-online-report.md"
    if report_md.exists():
        md = report_md.read_text(encoding="utf-8")
        check("聚合报告含防风控限速提示", "防风控" in md)

    # ② 关闭限速：不应调用 time.sleep
    with patch("time.sleep") as mocksleep2, patch.object(provider_registry, "get_provider", fake_gp):
        vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {**base_opts, "enum_interval": 2.0, "no_throttle": True},
        )
    check("--no-throttle→time.sleep 不被调用", mocksleep2.call_count == 0,
          f"call_count={mocksleep2.call_count}")

    # ③ enum-limit 上限：仅处理前 2 条
    with patch("time.sleep"), patch.object(provider_registry, "get_provider", fake_gp):
        results3 = vo_mod.VideoOnlineModule().run(
            ["https://www.douyin.com/user/ABC"],
            {**base_opts, "enum_limit": 2},
        )
    ok3 = [r for r in results3 if r.media_ref.get("status") == "ok"]
    check("--enum-limit 2→仅处理 2 条", len(ok3) == 2, str(len(ok3)))


def _main():
    print("=== info-extract · 阶段五增强验证（verify_phase6 · 方案 B）===\n")
    fixture = Path(__file__).resolve().parent / "fixtures" / "sample_online.mp4"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    td = Path(__file__).resolve().parent.parent / "_verify_out6"
    td.mkdir(parents=True, exist_ok=True)
    make_video_fixture(fixture)

    test_account_url_detection()
    test_provider_registry_enum()
    test_enum_provider_unit()
    test_cookie_args()
    test_account_enum_pipeline(fixture, td)
    test_force_playlist_on_single(fixture, td)
    test_enum_provider_unavailable(fixture, td)
    test_enum_login_failure(fixture, td)
    test_router_options()
    test_router_check()
    test_account_enum_throttle(fixture, td)

    print(f"\n=== 汇总：通过 {len(_PASS)} ｜ 失败 {len(_FAIL)} ===")
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print(f"  ❌ {n}")
        return 1
    print("✅ 阶段五增强（方案 B）全部验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
