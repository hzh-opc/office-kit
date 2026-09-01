#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段五（在线/加密视频受限场景）验证脚本。

不依赖 yt-dlp / 浏览器 / 真实 Whisper 模型即可验证阶段五核心逻辑：
  - URL 路由到 video_online（D8）
  - Provider 注册（VIDEO_ONLINE → yt-dlp + browser-capture，D15）
  - yt-dlp Provider 单元（available/meta，无网络）
  - 浏览器捕获 Provider 单元（D9 协同自检 / capture_path 消费 / 加密法律风险提示）
  - 全链路（MockVideoOnlineProvider + FakeProvider 推理，绕过网络与模型下载）：
    下载至 tmp 沙箱 → 抽音轨转录 → 双通道输出 → D13 讲解段帧 → 加密回退 → 无 provider 引导
  - 强约束：no_copy_saved（D3）/ 不落盘（审阅 G）/ 法律风险提示（§4 边界 #2）随产出透明回显
  - router 路由 + --capture-path + --check

运行：python tests/verify_phase5.py
退出码：0=全部通过；非 0=存在失败项。
"""

from __future__ import annotations

import json
import os
import shutil
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
from modules.video_online.providers.base import IVideoOnlineProvider  # noqa: E402
from modules.video_online.providers.browser_capture import BrowserCaptureProvider  # noqa: E402
from modules.video_online.providers.ytdlp import YtDlpProvider  # noqa: E402
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


class MockVideoOnlineProvider(IVideoOnlineProvider):
    """Mock 在线视频 Provider：返回本地 fixture 视频（external=True，模块不删）。"""
    name = "mock-online"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, *, available=True, raise_encrypted=False, encrypted=False,
                 video_path=None, external=True, method="yt-dlp"):
        self._available = available
        self._raise_encrypted = raise_encrypted
        self._encrypted = encrypted
        self._video_path = video_path
        self._external = external
        self._method = method

    def available(self):
        return self._available

    def meta(self):
        m = super().meta()
        m["encrypted"] = self._encrypted
        return m

    def acquire(self, url, tmp_root, options):
        if self._raise_encrypted:
            raise InfoExtractError(
                "该视频疑似加密/DRM 保护，yt-dlp 无法直接下载。",
                recoverable=True,
                hint="加密/DRM 视频仅能「播放中捕获」（法律灰区，§4 边界 #2）。",
            )
        return {
            "video_path": self._video_path,
            "title": "MockOnlineTitle",
            "encrypted": self._encrypted,
            "method": self._method,
            "note": "MOCK",
            "external": self._external,
        }


def _fake_get_provider(fake_transcript, fake_online):
    def gp(cap, name=None):
        if cap == SourceType.TRANSCRIPT:
            return fake_transcript
        if cap == SourceType.VIDEO_ONLINE:
            return fake_online
        return None
    return gp


# ---------- 测试 ----------
def test_io_routing():
    print("\n[1] URL 路由到 video_online（D8）")
    check("http URL→video_online", is_url("https://example.com/a.mp4"))
    check("https URL→video_online", is_url("https://youtu.be/abc"))
    check("ftp URL→video_online", is_url("ftp://host/v.mkv"))
    check("本地路径非 URL", not is_url("/tmp/a.mp4"))
    check("SourceType.VIDEO_ONLINE 常量", SourceType.VIDEO_ONLINE == "video_online")
    check("router.MODULE_MAP 含 VIDEO_ONLINE",
          SourceType.VIDEO_ONLINE in router.MODULE_MAP
          and router.MODULE_MAP[SourceType.VIDEO_ONLINE][1] == "VideoOnlineModule")
    check("VideoOnlineModule.ready=True", vo_mod.VideoOnlineModule.ready is True)


def test_provider_registry():
    print("\n[2] Provider 注册（VIDEO_ONLINE → yt-dlp + browser-capture，D15）")
    aps = provider_registry.available_providers(SourceType.VIDEO_ONLINE)
    names = [p["name"] for p in aps]
    check("注册含 yt-dlp", "yt-dlp" in names)
    check("注册含 browser-capture", "browser-capture" in names)
    yt = provider_registry.get_provider(SourceType.VIDEO_ONLINE, name="yt-dlp")
    bc = provider_registry.get_provider(SourceType.VIDEO_ONLINE, name="browser-capture")
    check("get_provider(VIDEO_ONLINE,yt-dlp) 命中", yt is not None and yt.name == "yt-dlp")
    check("get_provider(VIDEO_ONLINE,browser-capture) 命中", bc is not None and bc.name == "browser-capture")


def test_ytdlp_unit():
    print("\n[3] YtDlpProvider 单元（available/meta，无网络）")
    p = YtDlpProvider()
    try:
        avail = p.available()
        ok_avail = isinstance(avail, bool)
    except Exception:
        ok_avail = False
    check("available() 返回 bool 且不抛异常", ok_avail)
    meta = p.meta()
    check("meta 含 provider=yt-dlp / cost=local",
          meta.get("provider") == "yt-dlp" and meta.get("cost") == "local")


def test_browser_provider_unit(td: Path):
    print("\n[4] BrowserCaptureProvider 单元（D9 / capture_path / 法律风险提示）")
    p = BrowserCaptureProvider()
    try:
        avail = p.available()
        ok_avail = isinstance(avail, bool)
    except Exception:
        ok_avail = False
    check("available() 返回 bool 且不抛异常", ok_avail)
    meta = p.meta()
    check("meta 含 provider=browser-capture / source_layer=skill",
          meta.get("provider") == "browser-capture" and meta.get("source_layer") == "skill")
    # 消费用户 capture_path（external 文件）
    cap = td / "user_recording.mp4"
    cap.write_bytes(b"fake")
    m = p.acquire("https://enc.example/v", str(td), {"capture_path": str(cap)})
    check("acquire(capture_path) 返回外部文件", m["video_path"] == str(cap.resolve()) and m["external"] is True)
    check("acquire(capture_path) 标记 encrypted=True", m["encrypted"] is True)
    # 无 capture_path → 抛 InfoExtractError 且 hint 含法律提示
    raised = None
    try:
        p.acquire("https://enc.example/v", str(td), {})
    except InfoExtractError as e:
        raised = e
    check("无 capture_path → InfoExtractError（不静默失败）", raised is not None)
    check("hint 含法律灰区/§4 边界 #2", raised is not None and "法律灰区" in (raised.hint or ""))


def test_online_full_pipeline_mock(fixture: Path, td: Path):
    print("\n[5] 在线视频全链路（mock 下载 + fake 推理，绕过网络/模型）")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    fake_gp = _fake_get_provider(FakeProvider(), mock_online)
    with patch.object(provider_registry, "get_provider", fake_gp):
        r = vo_mod.VideoOnlineModule().run(
            ["https://example.com/a.mp4"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None},
        )[0]
    check("返回 1 条结果", r is not None)
    check("状态 ok", r.media_ref.get("status") == "ok", str(r.media_ref))
    check("fields.online=True", r.fields.get("online") is True)
    check("fields.no_copy_saved=True（D3 不留存副本）", r.fields.get("no_copy_saved") is True)
    check("fields.acquire_method=yt-dlp", r.fields.get("acquire_method") == "yt-dlp")
    check("fields.encrypted=False", r.fields.get("encrypted") is False)
    check("无法律风险提示（非加密）", "legal_risk_warning" not in r.fields)
    check("产出 provider_meta（provider=fake，转录侧）", r.provider_meta.get("provider") == "fake")
    outs = r.media_ref.get("outputs", {})
    check("双通道输出（txt/json/md）", set(outs.keys()) >= {"txt", "json", "md"})
    check("D13 抽出 1 张讲解帧", r.fields.get("visual_frames") == 1, str(r.fields))
    check("referenced_frame 含帧图", bool(r.referenced_frame and r.referenced_frame["frames"][0]["frame_path"]))
    md = Path(outs["md"]).read_text(encoding="utf-8")
    check("md 含在线标题", "在线/加密视频文案提取结果" in md)
    check("md 含『副本未保存』说明", "未保存" in md)


def test_online_encrypted_fallback(fixture: Path, td: Path):
    print("\n[6] 加密/DRM 回退：yt-dlp 报加密 → 浏览器捕获提供录制文件")
    cap = td / "user_recording.mp4"
    make_video_fixture(cap)  # 真实可解码的 mp4，模拟用户「播放中捕获」产物
    yt = MockVideoOnlineProvider(raise_encrypted=True)
    bc = MockVideoOnlineProvider(video_path=str(cap), external=True, encrypted=True, method="browser-capture")
    fake_gp = _fake_get_provider(FakeProvider(), yt)  # yt 默认；bc 经模块级 _browser_provider
    with patch.object(provider_registry, "get_provider", fake_gp), \
         patch.object(vo_mod, "_yt_provider", return_value=yt), \
         patch.object(vo_mod, "_browser_provider", return_value=bc):
        r = vo_mod.VideoOnlineModule().run(
            ["https://enc.example/v"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": str(cap)},
        )[0]
    check("加密回退后状态 ok", r.media_ref.get("status") == "ok", str(r.media_ref))
    check("fields.encrypted=True", r.fields.get("encrypted") is True)
    check("fields.acquire_method=browser-capture", r.fields.get("acquire_method") == "browser-capture")
    check("法律风险提示已写入产出（§4 边界 #2）", "legal_risk_warning" in r.fields
          and "法律灰区" in r.fields["legal_risk_warning"])


def test_online_encrypted_no_capture(td: Path):
    print("\n[7] 加密且无捕获文件 → 显式法律风险提示，不静默失败")
    yt = MockVideoOnlineProvider(raise_encrypted=True)
    bc = MockVideoOnlineProvider(available=True, raise_encrypted=True)  # 浏览器回退也报加密
    fake_gp = _fake_get_provider(FakeProvider(), yt)
    with patch.object(provider_registry, "get_provider", fake_gp), \
         patch.object(vo_mod, "_yt_provider", return_value=yt), \
         patch.object(vo_mod, "_browser_provider", return_value=bc):
        r = vo_mod.VideoOnlineModule().run(
            ["https://enc.example/v"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None},
        )[0]
    check("状态 error（不静默失败）", r.media_ref.get("status") == "error")
    check("error hint 含法律灰区/§4 边界 #2", "法律灰区" in (r.media_ref.get("hint") or ""))


def test_online_no_provider(td: Path):
    print("\n[8] 无可用工具（yt-dlp + browser 均不可用）→ 明确安装引导")
    fake_gp = _fake_get_provider(FakeProvider(), None)  # VIDEO_ONLINE 返回 None
    with patch.object(provider_registry, "get_provider", fake_gp):
        r = vo_mod.VideoOnlineModule().run(
            ["https://example.com/a.mp4"],
            {"out_dir": str(td), "use_cache": False, "provider": None,
             "lang": None, "task": None, "model": "small", "vad_threshold": 700,
             "long_threshold": 600, "extract_frames": True, "vision": False,
             "capture_path": None},
        )[0]
    check("状态 error", r.media_ref.get("status") == "error")
    check("hint 引导安装 yt-dlp", "yt-dlp" in (r.media_ref.get("hint") or ""))


def test_online_cache_hit(fixture: Path, td: Path):
    print("\n[9] 哈希缓存命中（D12·L，按 URL）")
    # 清空持久缓存，保证首次运行走真实处理（缓存目录跨进程保留，否则会误命中 cached）
    shutil.rmtree(SCRIPT_DIR / ".cache", ignore_errors=True)
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    fake_gp = _fake_get_provider(FakeProvider(), mock_online)
    opts = {"out_dir": str(td), "use_cache": True, "provider": None,
            "lang": None, "task": None, "model": "small", "vad_threshold": 700,
            "long_threshold": 600, "extract_frames": True, "vision": False,
            "capture_path": None}
    with patch.object(provider_registry, "get_provider", fake_gp):
        r1 = vo_mod.VideoOnlineModule().run(["https://example.com/a.mp4"], opts)[0]
        r2 = vo_mod.VideoOnlineModule().run(["https://example.com/a.mp4"], opts)[0]
    check("首次 status=ok", r1.media_ref.get("status") == "ok")
    check("二次 status=cached", r2.media_ref.get("status") == "cached")
    check("缓存命中仍刷新产出", set(r2.media_ref.get("outputs", {}).keys()) >= {"txt", "json", "md"})


def test_router_options():
    print("\n[10] router.build_options 含 --capture-path（阶段五）")
    import argparse
    ns = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier=None, no_ocr_vision=False, vision=False, capture_path="/tmp/rec.mp4",
    )
    opts = router.build_options(ns)
    check("build_options 含 capture_path", "capture_path" in opts and opts["capture_path"] == "/tmp/rec.mp4")
    # 默认 None
    ns2 = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier=None, no_ocr_vision=False, vision=False, capture_path=None,
    )
    check("build_options 默认 capture_path=None", router.build_options(ns2).get("capture_path") is None)


def test_router_online_routing(fixture: Path, td: Path):
    print("\n[11] router 在线视频路由（mock，进程内）")
    mock_online = MockVideoOnlineProvider(video_path=str(fixture), external=True)
    fake_gp = _fake_get_provider(FakeProvider(), mock_online)
    rc = 0
    with patch.object(provider_registry, "get_provider", fake_gp):
        try:
            router.main(["https://example.com/a.mp4", "--out", str(td), "--no-cache"])
        except SystemExit as e:
            rc = e.code or 0
    check("router 在线路由退出码 0", rc == 0)
    js = list(td.glob("*.json"))
    check("router 写出结构化结果", bool(js))
    if js:
        data = json.loads(js[0].read_text(encoding="utf-8"))
        results = data.get("results", [data])
        first = results[0] if results else {}
        check("产出 fields.online=True", first.get("fields", {}).get("online") is True, str(first))
        check("产出 media_ref.no_copy_saved=True", first.get("media_ref", {}).get("no_copy_saved") is True)


def test_router_check():
    print("\n[12] router.py --check（含 video_online 能力）")
    r = __import__("subprocess").run(
        [sys.executable, str(SCRIPT_DIR / "router.py"), "--check"],
        capture_output=True, text=True, cwd=str(SCRIPT_DIR.parent),
    )
    check("router --check 退出码 0", r.returncode == 0, r.stderr[-300:])
    check("--check 输出含 video_online 能力", "video_online" in r.stdout.lower())


def _main():
    print("=== info-extract · 阶段五验证（verify_phase5）===\n")
    fixture = Path(__file__).resolve().parent / "fixtures" / "sample_online.mp4"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    td = Path(__file__).resolve().parent.parent / "_verify_out5"
    td.mkdir(parents=True, exist_ok=True)
    make_video_fixture(fixture)

    test_io_routing()
    test_provider_registry()
    test_ytdlp_unit()
    test_browser_provider_unit(td)
    test_online_full_pipeline_mock(fixture, td)
    test_online_encrypted_fallback(fixture, td)
    test_online_encrypted_no_capture(td)
    test_online_no_provider(td)
    test_online_cache_hit(fixture, td)
    test_router_options()
    test_router_online_routing(fixture, td)
    test_router_check()

    print(f"\n=== 汇总：通过 {len(_PASS)} ｜ 失败 {len(_FAIL)} ===")
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print(f"  ❌ {n}")
        return 1
    print("✅ 阶段五全部验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
