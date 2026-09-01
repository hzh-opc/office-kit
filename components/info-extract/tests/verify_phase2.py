#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段二（视频文案提取 + D13 讲解段关联帧）验证脚本。

不依赖 Whisper 模型下载即可验证阶段二核心逻辑：
  - 类型识别（视频文件 → video；URL → video_online，D8）
  - PyAV 从视频容器抽音轨（复用 load_audio）
  - 转录核心复用（transcribe_core，fake 推理绕过模型下载）
  - D13 指代词检测 + 帧抽取（标准库 PNG 写出，零新依赖）
  - 全链路（fake 推理，进程内 + router 路由）
  - router --check 含 VIDEO 能力

运行：python tests/verify_phase2.py
"""

from __future__ import annotations

import fractions
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import av
import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from modules.audio.language import parse_language_hint  # noqa: E402
from modules.audio.providers.base import ITranscriptProvider  # noqa: E402
from modules.audio.vad import TARGET_SR, load_audio  # noqa: E402
from modules.base import ExtractResult, Segment, SourceType  # noqa: E402
from modules.video.frames import (  # noqa: E402
    extract_frame,
    extract_referenced_frames,
    is_visual_explanation,
)
from utils.io import classify, is_url  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def make_video_fixture(path: Path, with_audio: bool = True) -> None:
    """生成含音轨的合成 mp4（mpeg4 视频 + mp3 音频，约 3s）。"""
    if path.exists():
        path.unlink()
    c = av.open(str(path), "w")
    vs = c.add_stream("mpeg4", rate=25)
    vs.width, vs.height, vs.pix_fmt = 64, 64, "yuv420p"
    if with_audio:
        au = c.add_stream("mp3", rate=16000)
        au.layout, au.sample_rate = "mono", 16000
    tb = fractions.Fraction(1, 25)
    for i in range(75):  # 3s @25fps
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
    name = "fake"
    source_layer = "local_builtin"
    cost = "local"

    def available(self):
        return True

    def transcribe(self, audio, language=None, task=None, model_size="small", **opts):
        dur = len(audio) / TARGET_SR if isinstance(audio, np.ndarray) else 3.0
        # 含指代词的段落，用于触发 D13
        segs = [
            Segment(start=0.0, end=1.5, text="今天我们开始讲解项目背景。"),
            Segment(start=1.5, end=3.0, text="如图所示，这张流程图说明了整体架构。"),
        ]
        info = {"detected_language": language or "zh", "duration": round(dur, 2), "model_size": model_size}
        return segs, info


def test_io_classify_video():
    print("[测试] 视频类型识别 + URL 路由（D8）")
    check("mp4→video", classify("x.mp4") == SourceType.VIDEO)
    check("mov→video", classify("x.mov") == SourceType.VIDEO)
    check("音频仍为 transcript", classify("x.wav") == SourceType.TRANSCRIPT)
    check("URL→video_online", is_url("https://example.com/a.mp4") == True)
    check("本地路径非 URL", is_url("/tmp/a.mp4") == False)
    check("ftp URL→video_online", is_url("ftp://host/v.mkv") == True)


def test_load_audio_from_video(fixture: Path):
    print("[测试] PyAV 从视频容器抽音轨（复用 load_audio）")
    samples, sr = load_audio(str(fixture), TARGET_SR)
    check("返回 16k 单声道", sr == TARGET_SR and samples.ndim == 1)
    check("音频时长≈3s", abs(len(samples) / sr - 3.0) < 0.3, f"got {len(samples)/sr:.2f}s")


def test_deictic():
    print("[测试] D13 指代词检测")
    check("『如图所示』命中", is_visual_explanation("如图所示，这张流程图很重要"))
    check("『这张图』命中", is_visual_explanation("请看这张图，它展示了结构"))
    check("as shown 命中", is_visual_explanation("As shown in this figure, the chart explains."))
    check("普通文案不命中", not is_visual_explanation("今天我们讨论一下项目进度安排"))


def test_frame_extract(fixture: Path, out_dir: Path):
    print("[测试] 帧抽取（PyAV 解码 + 标准库 PNG，零新依赖）")
    frame_path = out_dir / "probe_frame.png"
    ok = extract_frame(str(fixture), 1.0, str(frame_path))
    check("extract_frame 成功", ok)
    check("写出有效 PNG", frame_path.exists() and frame_path.stat().st_size > 0)
    data = frame_path.read_bytes()
    check("PNG 签名正确", data[:8] == b"\x89PNG\r\n\x1a\n")


def test_d13_extract(fixture: Path, out_dir: Path):
    print("[测试] D13 referenced_frame 结构")
    segs = [
        Segment(0.0, 1.5, "背景介绍"),
        Segment(1.5, 3.0, "如图所示，这张流程图说明了整体架构。"),
    ]
    rf = extract_referenced_frames(str(fixture), segs, str(out_dir), "probe", enabled=True)
    check("返回 frames 列表", rf is not None and len(rf["frames"]) == 1)
    if rf:
        f0 = rf["frames"][0]
        check("is_visual_explanation=True", f0["is_visual_explanation"] is True)
        check("frame_path 有效 PNG", f0["frame_path"] and os.path.exists(f0["frame_path"]))
        check("vision_caption 预留 None", f0["vision_caption"] is None)
    # 关闭帧抽取
    rf_off = extract_referenced_frames(str(fixture), segs, str(out_dir), "probe", enabled=False)
    check("--no-frames 时返回 None", rf_off is None)


def test_video_full_pipeline_mock(fixture: Path, out_dir: Path):
    print("[测试] 视频全链路（fake 推理，绕过模型下载）")
    import provider_registry as pr

    pr.get_provider = lambda cap, name=None: FakeProvider()

    from modules.video import VideoModule

    mod = VideoModule()
    res = mod.run([str(fixture)], {"out_dir": str(out_dir), "use_cache": False})
    check("返回 1 条结果", len(res) == 1)
    r = res[0]
    check("状态 ok", r.media_ref.get("status") == "ok", str(r.media_ref))
    check("container=video", r.fields.get("container") == "video")
    check("产出 provider_meta", r.provider_meta.get("provider") == "fake")
    check("双通道文件已写出", bool(r.media_ref.get("outputs", {})))
    check("D13 抽出 1 张讲解帧", r.fields.get("visual_frames") == 1, str(r.fields))
    check("referenced_frame 含帧图", bool(r.referenced_frame and r.referenced_frame["frames"][0]["frame_path"]))
    # 无音轨视频清晰报错
    silent = out_dir / "silent.mp4"
    make_video_fixture(silent, with_audio=False)
    res2 = mod.run([str(silent)], {"out_dir": str(out_dir), "use_cache": False})
    check("无音轨视频→error 不静默失败",
          res2[0].media_ref.get("status") == "error" and "无音轨" in (res2[0].media_ref.get("error") or ""),
          str(res2[0].media_ref))


def test_router_check():
    print("[测试] router.py --check（含 VIDEO 能力）")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "router.py"), "--check"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    check("router --check 退出码 0", r.returncode == 0, r.stderr[-300:])
    check("--check 输出含 video 能力", "video" in r.stdout.lower() or "VIDEO" in r.stdout)


def test_router_video_routing(fixture: Path, out_dir: Path):
    print("[测试] router 视频路由（mock，进程内）")
    import json as _json

    import provider_registry as pr
    import router

    pr.get_provider = lambda cap, name=None: FakeProvider()
    rc = 0
    try:
        router.main([str(fixture), "--out", str(out_dir), "--no-cache"])
    except SystemExit as e:
        rc = e.code or 0
    check("router 视频路由退出码 0", rc == 0)
    js = list(out_dir.glob("*.json"))
    check("router 写出结构化结果", bool(js))
    if js:
        data = _json.loads(js[0].read_text(encoding="utf-8"))
        # 顶层是 {total, ok, ...} 或单条？router --json 输出 payload
        results = data.get("results", [data])
        first = results[0] if results else {}
        check("产出 container=video", first.get("fields", {}).get("container") == "video", str(first))
        check("产出 referenced_frame 含帧",
              bool(first.get("referenced_frame") and first["referenced_frame"].get("frames")), str(first))


def main():
    fixture = REPO / "tests" / "fixtures" / "sample.mp4"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    out_dir = REPO / "_verify_out2"
    out_dir.mkdir(parents=True, exist_ok=True)
    make_video_fixture(fixture)

    test_io_classify_video()
    test_load_audio_from_video(fixture)
    test_deictic()
    test_frame_extract(fixture, out_dir)
    test_d13_extract(fixture, out_dir)
    test_video_full_pipeline_mock(fixture, out_dir)
    test_router_check()
    test_router_video_routing(fixture, out_dir)

    print(f"\n=== 阶段二结果：通过 {PASS} / 失败 {FAIL} ===")
    # 清理
    if fixture.exists():
        fixture.unlink()
    shutil.rmtree(str(out_dir), ignore_errors=True)
    shutil.rmtree(str(REPO / "scripts" / ".cache_verify"), ignore_errors=True)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
