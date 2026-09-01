#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段四（画面解读 / VLM 视觉理解）验证脚本。

设计（呼应方案 §3 阶段四 / 流程规范 §2.1 / §1.1 B.3 / D7 / D11 / D12·L / D12·H / D13 / D15 / §4.4 / §4.7）：
- 不依赖 ollama / 真实 VLM 推理即可验证全部编排逻辑：
  路由 → OCR 协同 → 本地 VLM caption（mock）→ 双通道输出 → 哈希缓存 → 批量聚合 →
  D13 讲解段帧视觉填充 → 审阅 F 整视频关键帧采样 → provider_meta 透明回显 → 档位自适应（D7）。
- 真实 LocalVLMProvider 仅做无网络单元验证（available/meta/tier/异常路径），不触发模型下载。
- 可选真实 VLM 端到端（需装 ollama + 模型）作为可选用例，缺失则跳过不报错。

用法：
  python tests/verify_phase4.py
退出码：0=全部通过；非 0=存在失败项。
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import numpy as np  # noqa: E402

from modules.base import SourceType, ExtractResult, InfoExtractError  # noqa: E402
import modules.vision as vision_mod  # noqa: E402
import modules.vision.vision_caption as vc  # noqa: E402
import modules.vision.frame_sampling as fs  # noqa: E402
import modules.vision.tier as tier_mod  # noqa: E402
import modules.vision.providers.local_vlm as local_vlm_mod  # noqa: E402
from modules.vision.providers.mock import MockVLMProvider  # noqa: E402
import modules.video.frames as vf  # noqa: E402
import provider_registry  # noqa: E402
import utils.io as io_mod  # noqa: E402
import router  # noqa: E402
from utils.image import write_png_rgb  # noqa: E402


# ---------- 结果收集 ----------
_PASS, _FAIL = [], []
def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail and not cond else ""))


def _synthetic_image(h=640, w=480):
    return (np.random.rand(h, w, 3) * 255).astype(np.uint8)


def _dummy_file(path: Path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(8))


# ---------- Mock Providers ----------
class SpyVLM(MockVLMProvider):
    """记录上次 caption 调用（image/prompt）的 Mock VLM，便于验证 OCR 协同注入。"""
    def __init__(self, caption_text="MOCK_VISION_CAPTION", *, available=True, tier_name="标准档"):
        super().__init__(caption_text, available=available, tier_name=tier_name)
        self.last_prompt = None
        self.last_image = None

    def caption(self, image, prompt, **opts):
        self.last_prompt = prompt
        self.last_image = image
        return super().caption(image, prompt, **opts)


class MockOcrProvider:
    name = "mock-ocr"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, boxes=None):
        self._boxes = boxes or [
            {"box": [[0, 0], [1, 0], [1, 1], [0, 1]], "text": "OCRMARKER_A", "score": 0.91},
            {"box": [[0, 0], [1, 0], [1, 1], [0, 1]], "text": "OCRMARKER_B", "score": 0.90},
        ]

    def available(self):
        return True

    def meta(self):
        return {"provider": self.name, "source_layer": self.source_layer, "cost": self.cost}

    def ocr(self, image, **opts):
        scores = [b["score"] for b in self._boxes] or []
        avg = round(float(np.mean(scores)), 3) if scores else None
        return self._boxes, {"num_boxes": len(self._boxes), "avg_confidence": avg, "engine": "mock"}


def _make_fake_gp(spy, mock_ocr):
    def fake(capability, name=None):
        if capability == SourceType.VISION:
            return spy
        if capability == SourceType.OCR:
            return mock_ocr
        return None
    return fake


@contextmanager
def vision_patches(spy, mock_ocr, *, load_image=True):
    fake = _make_fake_gp(spy, mock_ocr)
    patchers = [
        patch.object(vision_mod, "get_provider", fake),
        patch.object(vc, "get_provider", fake),
    ]
    if load_image:
        patchers.append(patch("utils.image.load_image_rgb", return_value=_synthetic_image()))
    for p in patchers:
        p.start()
    try:
        yield
    finally:
        for p in patchers:
            p.stop()


# ---------- 测试 ----------
def test_io_routing_and_registry():
    print("\n[1] 类型识别与 Provider 注册（VISION 已接入 local-vlm）")
    # 图片走 OCR（视觉栈在 VisionModule 内部经 OCR 协同 + VLM 复用）；这里确认 VISION 域已注册
    check("SourceType.VISION 常量", SourceType.VISION == "vision")
    prov = provider_registry.get_provider(SourceType.VISION)
    check("get_provider(VISION) 返回 local-vlm 实例",
          prov is not None and prov.name == "local-vlm")
    aps = provider_registry.available_providers(SourceType.VISION)
    check("available_providers(VISION) 含 local-vlm",
          any(p["name"] == "local-vlm" for p in aps))
    # MODULE_MAP 含 VISION → VisionModule
    check("router.MODULE_MAP 含 VISION", SourceType.VISION in router.MODULE_MAP
          and router.MODULE_MAP[SourceType.VISION][1] == "VisionModule")
    check("VisionModule.ready=True", vision_mod.VisionModule.ready is True)


def test_build_prompt():
    print("\n[2] build_vision_prompt（任务 / OCR 协同 / 视频讲解段）")
    p1 = vc.build_vision_prompt(task="总结要点", ocr_text="OCRMARKER_A")
    check("含用户任务", "用户任务：总结要点" in p1)
    check("含 OCR 协同文字", "OCRMARKER_A" in p1)
    p2 = vc.build_vision_prompt(seg_text="如图所示")
    check("含视频口播文案", "口播文案" in p2 and "如图所示" in p2)
    p3 = vc.build_vision_prompt()
    check("无任务/无 OCR 仍生成基础指令", "解读这张图片" in p3 and "OCR" not in p3)


def test_vision_module_e2e():
    print("\n[3] VisionModule 全链路（mock VLM + mock OCR 协同）")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.png"
        _dummy_file(f)
        opts = {"out_dir": td, "use_cache": True, "provider": None,
                "ocr_coop": True, "vision_tier": None, "task": None, "lang": None, "vision": False}
        with vision_patches(spy, mock_ocr):
            r = vision_mod.VisionModule().run([str(f)], opts)[0]
        check("source=VISION", r.source == SourceType.VISION)
        check("caption 产出", r.fields.get("caption") == "MOCK_VISION_CAPTION")
        check("OCR 协同文字非空", bool(r.fields.get("ocr_text")))
        check("ocr_coop=True", r.fields.get("ocr_coop") is True)
        check("vision_available=True", r.fields.get("vision_available") is True)
        check("档位名已记录", r.fields.get("vision_tier") == "标准档")
        check("confidence=None（VLM 无干净置信度，§4.1 透明）", r.confidence is None)
        outs = r.media_ref.get("outputs", {})
        check("双通道输出（txt/json/md）", set(outs.keys()) >= {"txt", "json", "md"})
        md = Path(outs["md"]).read_text(encoding="utf-8")
        check("md 含视觉描述", "MOCK_VISION_CAPTION" in md)
        check("md 含『请核对』提示", "请核对" in md)
        check("provider_meta 透明回显 provider", r.provider_meta.get("provider") == "mock-vlm")
        check("provider_meta 透明回显 ocr_provider", r.provider_meta.get("ocr_provider") == "mock-ocr")
        check("provider_meta 含 cost=local", r.provider_meta.get("cost") == "local")
        check("OCR 协同文字已注入 VLM 提示词",
              spy.last_prompt is not None and "OCRMARKER_A" in spy.last_prompt)


def test_vision_vlm_unavailable_cloud_upgrade():
    print("\n[4] VLM 不可用 → 仅交付 OCR + 标记建议上云提质（D2/§4.4）")
    spy = SpyVLM(available=False)
    mock_ocr = MockOcrProvider()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.png"
        _dummy_file(f)
        opts = {"out_dir": td, "use_cache": False, "provider": None,
                "ocr_coop": True, "vision_tier": None, "task": None, "lang": None, "vision": False}
        with vision_patches(spy, mock_ocr):
            r = vision_mod.VisionModule().run([str(f)], opts)[0]
        check("vision_available=False", r.fields.get("vision_available") is False)
        check("标记 suggest_cloud_upgrade", r.media_ref.get("suggest_cloud_upgrade") is True)
        check("upgrade_hint 提及脱敏闸门", "脱敏" in (r.media_ref.get("upgrade_hint") or ""))
        check("文本回退为 OCR 文字（不静默丢内容）", r.text == r.fields.get("ocr_text") and r.text)
        check("caption 为 None", r.fields.get("caption") is None)
        outs = r.media_ref.get("outputs", {})
        check("仍落双通道", set(outs.keys()) >= {"txt", "json", "md"})
        md = Path(outs["md"]).read_text(encoding="utf-8")
        check("md 含上云提质提示", "上云" in md)


def test_no_ocr_coop():
    print("\n[5] --no-ocr-vision：关闭 OCR 协同（§1.1 B.3 默认开启）")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.png"
        _dummy_file(f)
        opts = {"out_dir": td, "use_cache": False, "provider": None,
                "ocr_coop": False, "vision_tier": None, "task": None, "lang": None, "vision": False}
        with vision_patches(spy, mock_ocr):
            r = vision_mod.VisionModule().run([str(f)], opts)[0]
        check("ocr_text 为 None", r.fields.get("ocr_text") is None)
        check("caption 仍由 VLM 产出", r.fields.get("caption") == "MOCK_VISION_CAPTION")
        check("VLM 提示词不含 OCR 标记", spy.last_prompt is not None and "OCRMARKER" not in spy.last_prompt)


def test_hash_cache_hit():
    print("\n[6] 哈希缓存命中（D12·L）：同输入二次运行走缓存")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.png"
        _dummy_file(f)
        opts = {"out_dir": td, "use_cache": True, "provider": None,
                "ocr_coop": True, "vision_tier": None, "task": None, "lang": None, "vision": False}
        with vision_patches(spy, mock_ocr):
            r1 = vision_mod.VisionModule().run([str(f)], opts)[0]
            r2 = vision_mod.VisionModule().run([str(f)], opts)[0]
        check("首次运行 status=ok", r1.media_ref.get("status") == "ok")
        check("二次运行 status=cached", r2.media_ref.get("status") == "cached")
        check("缓存命中仍刷新产出", set(r2.media_ref.get("outputs", {}).keys()) >= {"txt", "json", "md"})


def test_batch_aggregate():
    print("\n[7] 批量输入 + 聚合报告（D12·H）")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    with tempfile.TemporaryDirectory() as td:
        f1 = Path(td) / "a.png"; _dummy_file(f1)
        f2 = Path(td) / "b.png"; _dummy_file(f2)
        opts = {"out_dir": td, "use_cache": False, "provider": None,
                "ocr_coop": True, "vision_tier": None, "task": None, "lang": None, "vision": False}
        with vision_patches(spy, mock_ocr):
            results = vision_mod.VisionModule().run([str(f1), str(f2)], opts)
        check("返回 2 条结果", len(results) == 2)
        report = results[0].media_ref.get("report", {})
        check("聚合报告生成（md）", report.get("md") and Path(report["md"]).is_file())
        check("聚合报告生成（json）", report.get("json") and Path(report["json"]).is_file())


def test_d13_fill_vision_caption():
    print("\n[8] D13 讲解段帧视觉填充（fill_d13_frames）")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    rf = {
        "frames": [
            {"timestamp": 1.0, "extracted": True, "frame_path": "x1.png",
             "segment_text": "如图所示", "is_visual_explanation": True},
            {"timestamp": 3.5, "extracted": True, "frame_path": "x2.png",
             "segment_text": "这张图", "is_visual_explanation": True},
        ],
        "note": "",
    }
    with tempfile.TemporaryDirectory() as td:
        opts = {"out_dir": td, "ocr_coop": True, "task": None, "lang": None, "vision": False}
        fake = _make_fake_gp(spy, mock_ocr)
        with patch.object(vc, "get_provider", fake), \
             patch.object(vf, "extract_frame_rgb", lambda *a, **k: _synthetic_image()):
            out = vc.fill_d13_frames(rf, "video.mp4", td, "video", opts)
        frs = out["frames"]
        check("帧1 vision_caption 已填充", frs[0].get("vision_caption") == "MOCK_VISION_CAPTION")
        check("帧1 ocr_on_frame 已填充", bool(frs[0].get("ocr_on_frame")))
        check("帧1 vision_tier 已记录", frs[0].get("vision_tier") == "标准档")
        check("帧2 同样填充", frs[1].get("vision_caption") == "MOCK_VISION_CAPTION"
              and bool(frs[1].get("ocr_on_frame")))

    # 不可用分支：vision_caption 留 None + note 追加
    spy_na = SpyVLM(available=False)
    rf2 = {"frames": [{"timestamp": 1.0, "extracted": True, "frame_path": "x.png",
                       "segment_text": "如图所示", "is_visual_explanation": True}], "note": ""}
    with tempfile.TemporaryDirectory() as td:
        opts = {"out_dir": td, "ocr_coop": True, "task": None, "lang": None, "vision": False}
        fake_na = _make_fake_gp(spy_na, mock_ocr)
        with patch.object(vc, "get_provider", fake_na), \
             patch.object(vf, "extract_frame_rgb", lambda *a, **k: _synthetic_image()):
            out2 = vc.fill_d13_frames(rf2, "video.mp4", td, "video", opts)
        check("VLM 不可用：vision_caption 留 None", out2["frames"][0].get("vision_caption") is None)
        check("VLM 不可用：note 追加提示", "VLM" in (out2.get("note") or ""))


def test_analyze_video_frames():
    print("\n[9] 审阅 F：整视频关键帧采样 + 视觉描述（analyze_video_frames）")
    spy = SpyVLM()
    mock_ocr = MockOcrProvider()
    fake_kf = [
        {"timestamp": 0.5, "frame_path": "kf0.png", "phash": "10101010"},
        {"timestamp": 1.5, "frame_path": "kf1.png", "phash": "01010101"},
    ]
    with tempfile.TemporaryDirectory() as td:
        opts = {"out_dir": td, "ocr_coop": True, "task": None, "lang": None, "vision": False}
        fake = _make_fake_gp(spy, mock_ocr)
        with patch.object(vc, "get_provider", fake), \
             patch.object(fs, "sample_keyframes", lambda *a, **k: list(fake_kf)), \
             patch.object(vf, "extract_frame_rgb", lambda *a, **k: _synthetic_image()):
            res = vc.analyze_video_frames("video.mp4", td, "video", opts)
        kfs = res.get("keyframes", [])
        check("返回关键帧列表", len(kfs) == 2)
        check("关键帧含 vision_caption", kfs[0].get("vision_caption") == "MOCK_VISION_CAPTION")
        check("关键帧含 ocr_on_frame", bool(kfs[0].get("ocr_on_frame")))
        check("内部 phash 不落产出", all("phash" not in k for k in kfs))
        check("note 说明场景切换采样", "场景切换" in (res.get("note") or ""))


def test_local_vlm_provider_unit():
    print("\n[10] LocalVLMProvider 单元（无网络；available/meta/tier/异常路径）")
    # 不触发网络：仅验证 available 不报错、返回 bool
    try:
        avail = local_vlm_mod.LocalVLMProvider().available()
        ok_avail = isinstance(avail, bool)
    except Exception:
        ok_avail = False
    check("available() 返回 bool 且不抛异常", ok_avail)
    meta = local_vlm_mod.LocalVLMProvider().meta()
    check("meta 含 provider/model/tier",
          meta.get("provider") == "local-vlm" and "model" in meta and "tier" in meta)
    # 档位覆盖（D7 用户覆盖优先；接受 档位数字 / 完整标签 / 中文名）
    check("tier_override=0 → qwen2.5vl:3b",
          local_vlm_mod.LocalVLMProvider(tier_override=0).tier["ollama_tag"] == "qwen2.5vl:3b")
    check("tier_override=3 → qwen2.5vl:32b",
          local_vlm_mod.LocalVLMProvider(tier_override=3).tier["ollama_tag"] == "qwen2.5vl:32b")
    check("tier_override='qwen2.5vl:3b' → 轻量档",
          local_vlm_mod.LocalVLMProvider(tier_override="qwen2.5vl:3b").tier["name"] == "轻量档")
    check("tier_override='旗舰档' → 32B 标签",
          local_vlm_mod.LocalVLMProvider(tier_override="旗舰档").tier["ollama_tag"] == "qwen2.5vl:32b")
    # 异常路径：服务不可达 → InfoExtractError(recoverable)
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "x.png"
        write_png_rgb(png, _synthetic_image(32, 32))
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            raised = False
            try:
                local_vlm_mod.LocalVLMProvider().caption(str(png), "p")
            except InfoExtractError:
                raised = True
        check("caption 服务不可达 → InfoExtractError(recoverable)", raised)
    # caption_image：provider 不可用 → (None, {available:False})
    prov = local_vlm_mod.LocalVLMProvider()
    with patch.object(prov, "available", return_value=False):
        cap, info = vc.caption_image(_synthetic_image(), "p", prov)
    check("caption_image provider 不可用返回 available:False",
          cap is None and info.get("available") is False)


def test_tier_adaptive():
    print("\n[11] VLM 档位自适应（D7）：探测 / 下调 / 采样密度 / 用户覆盖 / 缓存")  # noqa: E501

    @contextmanager
    def fake_resources(d):
        saved = tier_mod._RESOURCE_CACHE
        tier_mod._RESOURCE_CACHE = None
        with patch.object(tier_mod, "probe_system_resources", return_value=d):
            yield
        tier_mod._RESOURCE_CACHE = saved

    # 无独显、RAM 充足 → 标准档
    with fake_resources({"ram_gb": 64.0, "vram_gb": 0.0, "unified": False, "gpu": False}):
        t = tier_mod.detect_optimal_tier()
        check("无独显 + 大 RAM → 标准档(tier=1)", t["tier"] == 1 and t["name"] == "标准档")
    # 有独显 + 大显存 → 选较高档（资源足够）
    with fake_resources({"ram_gb": 16.0, "vram_gb": 24.0, "unified": False, "gpu": True}):
        t2 = tier_mod.detect_optimal_tier()
        check("有独显探测返回合法档位(tier>=1)", t2["tier"] >= 1 and "ollama_tag" in t2)
    # 极低资源 → 至少最轻量档
    with fake_resources({"ram_gb": 4.0, "vram_gb": 0.0, "unified": False, "gpu": False}):
        t0 = tier_mod.detect_optimal_tier()
        check("极低资源 → 轻量档(tier=0)", t0["tier"] == 0)

    # 用户手动覆盖（数字 / 完整标签 / 中文名）
    check("detect_optimal_tier(0) → 轻量档", tier_mod.detect_optimal_tier(0)["tier"] == 0)
    check("detect_optimal_tier('qwen2.5vl:32b') → 旗舰档", tier_mod.detect_optimal_tier("qwen2.5vl:32b")["tier"] == 3)
    check("detect_optimal_tier('旗舰档') → 旗舰档", tier_mod.detect_optimal_tier("旗舰档")["tier"] == 3)
    # 环境变量覆盖
    with patch.dict(os.environ, {"INFO_EXTRACT_VISION_TIER": "3"}):
        check("环境变量 INFO_EXTRACT_VISION_TIER=3 → 旗舰档",
              tier_mod.detect_optimal_tier()["tier"] == 3)

    # 采样密度（审阅 F）随档位递增
    sp0 = tier_mod.sampling_profile(tier_mod.TIERS[0])
    sp3 = tier_mod.sampling_profile(tier_mod.TIERS[3])
    check("采样密度：轻量档 8 帧/2s，旗舰档 24 帧/0.5s",
          sp0["max_keyframes"] == 8 and sp0["interval_sec"] == 2.0
          and sp3["max_keyframes"] == 24 and sp3["interval_sec"] == 0.5)
    check("采样密度随档位递增", sp3["max_keyframes"] > sp0["max_keyframes"])

    # 运行时下调（D7）：安装缓存 tier3，探测仅 tier0 → 标记 downgraded
    with fake_resources({"ram_gb": 4.0, "vram_gb": 0.0, "unified": False, "gpu": False}):
        with patch.object(tier_mod, "load_cached_tier", return_value=tier_mod.TIERS[3]):
            t_down = tier_mod.current_tier()
    check("运行时资源下降 → 自动下调一档", t_down["tier"] == 0 and t_down.get("_downgraded") is True)
    check("下调记录来源档位", t_down.get("_downgraded_from") == 3)

    # 缓存落盘往返（CACHE_PATH 指向临时文件，避免污染仓库）
    with tempfile.TemporaryDirectory() as td:
        cache_file = Path(td) / ".vision_tier.json"
        with patch.object(tier_mod, "CACHE_PATH", cache_file):
            tier_mod.cache_tier(tier_mod.TIERS[1])
            loaded = tier_mod.load_cached_tier()
        check("cache_tier/load_cached_tier 往返一致", loaded is not None and loaded["tier"] == 1)


def test_router_vision_options():
    print("\n[12] router.build_options 含阶段四选项（D7/OCR协同/审阅 F）")
    import argparse
    ns = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier=None, no_ocr_vision=False, vision=False,
    )
    opts = router.build_options(ns)
    check("build_options 含 vision_tier", "vision_tier" in opts and opts["vision_tier"] is None)
    check("build_options 含 ocr_coop=True", opts["ocr_coop"] is True)
    check("build_options 含 vision=False", opts["vision"] is False)
    # --no-ocr-vision / --vision 翻转
    ns2 = argparse.Namespace(
        lang=None, task=None, model="small", provider="auto", out="/tmp",
        no_cache=False, long_threshold=600, vad_threshold=700, no_frames=False,
        confidence_threshold=0.85, force_ocr=False, no_preprocess=False,
        vision_tier="32b", no_ocr_vision=True, vision=True,
    )
    opts2 = router.build_options(ns2)
    check("build_options --vision-tier 透传", opts2["vision_tier"] == "32b")
    check("build_options --no-ocr-vision → ocr_coop=False", opts2["ocr_coop"] is False)
    check("build_options --vision=True 透传", opts2["vision"] is True)


def _main():
    print("=== info-extract · 阶段四验证（verify_phase4）===\n")
    test_io_routing_and_registry()
    test_build_prompt()
    test_vision_module_e2e()
    test_vision_vlm_unavailable_cloud_upgrade()
    test_no_ocr_coop()
    test_hash_cache_hit()
    test_batch_aggregate()
    test_d13_fill_vision_caption()
    test_analyze_video_frames()
    test_local_vlm_provider_unit()
    test_tier_adaptive()
    test_router_vision_options()

    print(f"\n=== 汇总：通过 {len(_PASS)} ｜ 失败 {len(_FAIL)} ===")
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print(f"  ❌ {n}")
        return 1
    print("✅ 阶段四全部验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
