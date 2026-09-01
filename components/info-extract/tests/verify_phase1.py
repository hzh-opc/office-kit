#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段一（音频转录）验证脚本。

不依赖 Whisper 模型下载即可验证阶段一核心逻辑：
  - 音频加载(PyAV) + VAD 分块（D12·J）
  - 类型识别（D8）
  - 哈希缓存（D12·L）
  - 双通道输出契约（D11）
  - Provider 注册/可用性检测（D15）
  - 全链路（mock 推理，绕过模型下载）
  - router --check 自检

运行：python tests/verify_phase1.py
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from modules.audio.language import parse_language_hint, parse_task_hint  # noqa: E402
from modules.audio.output import write_outputs  # noqa: E402
from modules.audio.providers.base import ITranscriptProvider  # noqa: E402
from modules.audio.vad import TARGET_SR, load_audio, vad_split  # noqa: E402
from modules.base import ExtractResult, Segment, SourceType, contract_to_result  # noqa: E402
from provider_registry import get_provider  # noqa: E402
from utils.hash_cache import ResultCache  # noqa: E402
from utils.io import classify  # noqa: E402

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


def make_fixture(path: Path) -> None:
    """生成 8s 合成音频：语音 0-3s、静音 3-4s、语音 4-7s、静音 7-8s。"""
    sr = TARGET_SR
    t = np.arange(0, 8.0, 1 / sr)
    sig = np.zeros_like(t)
    for a, b in [(0.0, 3.0), (4.0, 7.0)]:
        mask = (t >= a) & (t < b)
        sig[mask] = 0.5 * np.sin(2 * np.pi * 220 * t[mask])
    pcm = (sig * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class FakeProvider(ITranscriptProvider):
    name = "fake"
    source_layer = "local_builtin"
    cost = "local"

    def available(self):
        return True

    def transcribe(self, audio, language=None, task=None, model_size="small", **opts):
        dur = len(audio) / TARGET_SR if isinstance(audio, np.ndarray) else 1.0
        seg = [Segment(start=0.0, end=min(3.0, dur), text="这是一段模拟转录文本。")]
        info = {"detected_language": language or "zh", "duration": round(dur, 2),
                "model_size": model_size}
        return seg, info


def test_vad_and_load(fixture: Path):
    print("[测试] 音频加载 + VAD 分块（D12·J）")
    samples, sr = load_audio(str(fixture), TARGET_SR)
    check("load_audio 返回 16k 单声道", sr == TARGET_SR and samples.ndim == 1)
    check("音频时长≈8s", abs(len(samples) / sr - 8.0) < 0.2, f"got {len(samples)/sr:.2f}s")
    chunks = vad_split(samples, sr)
    check("VAD 在静音处切出≥2段", len(chunks) >= 2, f"segments={chunks}")
    # 验证切分点落在静音区（3-4s 之间应有切点）
    mid = (chunks[0][1] + chunks[1][0]) / 2
    check("切点落在静音区(2.5~4.5s)", 2.5 < mid < 4.5, f"cut_mid={mid:.2f}s")


def test_io_classify():
    print("[测试] 类型识别（D8）")
    check("mp3→transcript", classify("x.mp3") == SourceType.TRANSCRIPT)
    check("wav→transcript", classify("x.wav") == SourceType.TRANSCRIPT)
    check("png→ocr", classify("x.png") == SourceType.OCR)
    # 阶段三：图片型/扫描件 PDF 从复合文档抽出、单独归 OCR（D10 分工，原生文本层页交 document_text）
    check("pdf→ocr（阶段三：图片型/扫描件 PDF 归 OCR）", classify("x.pdf") == SourceType.OCR)
    check("mp4→video（本地，阶段二）", classify("x.mp4") == SourceType.VIDEO)
    check("xyz→空(不支持)", classify("x.xyz") == "")


def test_lang_hint():
    print("[测试] 语言/任务轻提示（D12·K）")
    check("『日文采访』→ja", parse_language_hint("这是日文采访") == "ja")
    check("『english』→en", parse_language_hint("english meeting") == "en")
    check("『翻译成英文』→translate", parse_task_hint("请翻译成英文") == "translate")
    check("无 hint→None", parse_language_hint("") is None)


def test_hash_cache():
    print("[测试] 哈希缓存（D12·L）")
    cache_dir = REPO / "scripts" / ".cache_verify"
    cache = ResultCache(cache_dir)
    tmp = REPO / "_verify_cache_test.bin"
    tmp.write_bytes(b"\x00info-extract-cache-test\x01" * 100)
    try:
        key_opts = {"lang": "zh", "task": "transcribe", "model": "small"}
        cache.put(str(tmp), key_opts, {"source": "transcript", "text": "hi"})
        got = cache.get(str(tmp), key_opts)
        check("缓存写入/读取命中", got is not None and got["text"] == "hi")
        miss = cache.get(str(tmp), {**key_opts, "model": "medium"})
        check("选项变更→缓存未命中", miss is None)
        # 修复 P0-1：阶段三/四/五/D16 新增选项须参与缓存键（白名单漏配曾导致错误命中）
        miss_ocr = cache.get(str(tmp), {**key_opts, "force_ocr": True})
        check("force_ocr 变更→缓存未命中", miss_ocr is None)
        miss_pre = cache.get(str(tmp), {**key_opts, "preprocess": False})
        check("preprocess 变更→缓存未命中", miss_pre is None)
        miss_ctx = cache.get(str(tmp), {**key_opts, "context": "化学实验报告"})
        check("D16 context 变更→缓存未命中", miss_ctx is None)
    finally:
        tmp.unlink(missing_ok=True)


def test_output_contract():
    print("[测试] 双通道输出契约（D11）")
    res = ExtractResult(
        source=SourceType.TRANSCRIPT, text="你好世界", confidence=0.91,
        fields={"detected_language": "zh", "duration_sec": 8.0},
        media_ref={"path": "x.mp3", "status": "ok"},
        provider_meta={"provider": "fake", "cost": "local"},
        segments=[Segment(0.0, 2.0, "你好"), Segment(2.0, 4.0, "世界")],
    )
    out = Path("_verify_out")
    written = write_outputs(res, out, "x")
    check("写出 4 个通道文件", set(written) == {"txt", "srt", "json", "md"})
    j = json.loads((out / "x.json").read_text(encoding="utf-8"))
    check("JSON 含 source/confidence", j["source"] == "transcript" and j["confidence"] == 0.91)
    txt = (out / "x.txt").read_text(encoding="utf-8")
    check("TXT 为纠正版稿件文本（含正文）", "你好" in txt and "世界" in txt)
    check("JSON 含 D16 raw_text/corrected 字段", "raw_text" in j and "corrected" in j)
    srt = (out / "x.srt").read_text(encoding="utf-8")
    check("SRT 含时间轴", "-->" in srt)
    # 修复 P0-2：segments 须入契约，缓存命中后才能还原带时间戳片段（否则 .srt 变空）
    check("JSON 含 segments（带时间戳片段）", "segments" in j and len(j["segments"]) == 2)
    rr = contract_to_result(j)
    check("缓存还原 segments 数量一致", len(rr.segments) == 2)
    check("缓存还原 segments 时间戳一致", rr.segments[0].start == 0.0 and rr.segments[1].end == 4.0)
    # 清理
    for f in out.glob("*"):
        f.unlink()
    out.rmdir()


def test_provider_registry():
    print("[测试] Provider 注册/可用性（D15）")
    p = get_provider(SourceType.TRANSCRIPT)
    check("取得默认 transcript provider", p is not None)
    if p is not None:
        check("provider 有 meta", "provider" in p.meta())
    # faster-whisper 可能未安装 → 仅验证接口存在
    from modules.audio.providers import FasterWhisperProvider
    fw = FasterWhisperProvider()
    check("FasterWhisperProvider.available() 可调用", isinstance(fw.available(), bool))


def test_full_pipeline_mock(fixture: Path):
    print("[测试] 全链路（mock 推理，绕过模型下载）")
    import provider_registry as pr

    # 打桩 provider（transcribe 在方法内惰性 import，故打模块属性即可生效）
    pr.get_provider = lambda cap, name=None: FakeProvider()

    from modules.audio.transcribe import AudioModule

    mod = AudioModule()
    # 非分块路径
    res = mod.run([str(fixture)], {"out_dir": str(REPO / "_verify_out"), "use_cache": False})
    check("返回 1 条结果", len(res) == 1)
    r = res[0]
    check("状态 ok", r.media_ref.get("status") == "ok", str(r.media_ref))
    check("产出 provider_meta", r.provider_meta.get("provider") == "fake")
    check("双通道文件已写出", bool(r.media_ref.get("outputs", {})))
    # 分块路径（long_threshold=1 → 强制 VAD 分块）
    res2 = mod.run([str(fixture)], {
        "out_dir": str(REPO / "_verify_out"), "use_cache": False, "long_threshold": 1,
    })
    r2 = res2[0]
    segs = r2.segments
    check("分块后多段且时间戳有序", len(segs) >= 2 and segs[0].start <= segs[-1].start)
    check("分块偏移在文件时长内", all(0 <= s.start < 8.1 and 0 <= s.end <= 8.1 for s in segs),
          f"segs={[(s.start,s.end) for s in segs]}")
    # 清理
    import shutil
    shutil.rmtree(str(REPO / "_verify_out"), ignore_errors=True)
    shutil.rmtree(str(REPO / "scripts" / ".cache_verify"), ignore_errors=True)


def test_router_check():
    print("[测试] router.py --check（CLI 入口）")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "router.py"), "--check"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    check("router --check 退出码 0", r.returncode == 0, r.stderr[-300:])
    check("--check 输出含能力自检", "能力自检" in r.stdout or "info-extract" in r.stdout)


def test_router_audio_routing(fixture: Path):
    print("[测试] router 音频路由（mock，进程内）")
    import json
    import shutil

    import provider_registry as pr
    import router

    pr.get_provider = lambda cap, name=None: FakeProvider()
    out_dir = REPO / "_verify_out"
    rc = 0
    try:
        router.main([str(fixture), "--out", str(out_dir), "--no-cache"])
    except SystemExit as e:
        rc = e.code or 0
    check("router 音频路由退出码 0", rc == 0)
    js = list(out_dir.glob("*.json"))
    check("router 写出结构化结果", bool(js))
    if js:
        data = json.loads(js[0].read_text(encoding="utf-8"))
        check("router 产出 provider=fake",
              data.get("provider_meta", {}).get("provider") == "fake",
              str(data.get("provider_meta")))
    # 修复 P1：--json 输出须为纯 JSON（横幅不污染 stdout，下游 json.loads 可直接解析）
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            router.main([str(fixture), "--out", str(out_dir), "--no-cache", "--json"])
    except SystemExit:
        pass
    raw = buf.getvalue().strip()
    try:
        payload = json.loads(raw)
        check("--json 输出为纯 JSON（无横幅污染）", payload.get("total") == 1)
    except Exception:
        check("--json 输出为纯 JSON（无横幅污染）", False, raw[:200])
    shutil.rmtree(str(out_dir), ignore_errors=True)


def main():
    fixture = REPO / "tests" / "fixtures" / "sample.wav"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    make_fixture(fixture)

    test_io_classify()
    test_lang_hint()
    test_hash_cache()
    test_output_contract()
    test_provider_registry()
    test_vad_and_load(fixture)
    test_full_pipeline_mock(fixture)
    test_router_check()
    test_router_audio_routing(fixture)

    print(f"\n=== 结果：通过 {PASS} / 失败 {FAIL} ===")
    if fixture.exists():
        fixture.unlink()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
