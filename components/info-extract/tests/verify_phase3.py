#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 阶段三（OCR）验证脚本。

设计（呼应方案 §3 阶段三 + 流程规范 §2.1/§2.5/D2/审阅 D/E/G/H/I）：
- 不依赖重型 OCR 依赖（rapidocr/onnxruntime/pypdfium2/PIL）即可验证全部编排逻辑：
  路由 → 预处理链 → PDF 类型探测分流 → rapidocr OCR（mock）→ 置信度门控上云 →
  双通道输出 → 哈希缓存 → 批量聚合报告 → provider_meta 透明回显。
- 真实 rapidocr 端到端（需安装依赖）作为可选用例，缺失则 SKIP 不报错。

用法：
  python tests/verify_phase3.py
退出码：0=全部通过；非 0=存在失败项。
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import numpy as np  # noqa: E402
from unittest.mock import patch  # noqa: E402

from modules.base import SourceType, ExtractResult, InfoExtractError  # noqa: E402
import modules.ocr as ocr_mod  # noqa: E402
from modules.ocr.providers.base import IOCRProvider  # noqa: E402
import provider_registry  # noqa: E402
import utils.io as io_mod  # noqa: E402
import router  # noqa: E402


# ---------- 结果收集 ----------
_PASS, _FAIL = [], []
def check(name, cond, detail=""):
    ( _PASS if cond else _FAIL ).append(name)
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail and not cond else ""))


# ---------- Mock Provider ----------
def _boxes(scores):
    return [
        {"box": [[0, 0], [10, 0], [10, 10], [0, 10]], "text": f"t{i}", "score": s}
        for i, s in enumerate(scores)
    ]


class MockOcrProvider(IOCRProvider):
    name = "mock-ocr"
    source_layer = "local_builtin"
    cost = "local"

    def __init__(self, boxes=None):
        self._boxes = boxes or _boxes([0.95, 0.90, 0.88])

    def available(self):
        return True

    def ocr(self, image, **opts):
        boxes = self._boxes
        scores = [b["score"] for b in boxes] or []
        avg = round(float(np.mean(scores)), 3) if scores else None
        return boxes, {"num_boxes": len(boxes), "avg_confidence": avg, "engine": "mock"}


def _synthetic_image(h=1500, w=1000):
    # 纯合成 RGB ndarray（无需 PIL/cv2），最长边 < 2000 以走「不缩放」分支
    return (np.random.rand(h, w, 3) * 255).astype(np.uint8)


def _dummy_png(path: Path):
    # 仅用于缓存哈希（内容无关）；写唯一字节避免跨用例缓存键碰撞（共享 scripts/.cache）
    import os as _os
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _os.urandom(16) + str(path).encode())


# ---------- 测试 ----------
def test_io_routing():
    print("\n[1] IO 类型识别（图片/pdf→OCR；音频→TRANSCRIPT；视频→VIDEO；docx→DOC_EXTRACT）")
    cases = {
        "a.png": SourceType.OCR, "a.jpg": SourceType.OCR, "a.jpeg": SourceType.OCR,
        "a.webp": SourceType.OCR, "a.pdf": SourceType.OCR,
        "a.mp3": SourceType.TRANSCRIPT, "a.m4a": SourceType.TRANSCRIPT,
        "a.mp4": SourceType.VIDEO, "a.mov": SourceType.VIDEO,
        "a.docx": SourceType.DOC_EXTRACT, "a.pptx": SourceType.DOC_EXTRACT,
        "a.xyz": "",
    }
    ok = True
    for f, exp in cases.items():
        got = io_mod.classify(f)
        if got != exp:
            ok = False
            print(f"     mismatch {f}: got={got!r} exp={exp!r}")
    check("classify 路由正确", ok)
    check("PDF_EXT 已导出且 pdf 归入 OCR",
          hasattr(io_mod, "PDF_EXT") and ".pdf" in io_mod.PDF_EXT and io_mod.classify("x.pdf") == SourceType.OCR)
    check("pdf 已从 DOC_EXT 移除", ".pdf" not in io_mod.DOC_EXT)


def test_preprocess_degrade():
    print("\n[2] 预处理链降级（无 PIL/cv2 时优雅不崩）")
    from modules.ocr import preprocess as P
    img = _synthetic_image(3000, 1000)
    out, did = P.normalize_max_side(img, 2000)
    check("normalize_max_side 不抛异常（无 PIL 时返回原图+False）", isinstance(out, np.ndarray) and did in (True, False))
    out2, did2 = P.deskew(img)
    check("deskew 无 cv2 降级返回原图+False", isinstance(out2, np.ndarray) and did2 is False)
    out3, steps = P.preprocess_image(img)
    check("preprocess_image 返回 (ndarray, list)", isinstance(out3, np.ndarray) and isinstance(steps, list))


def test_output_dual_channel():
    print("\n[3] OCR 双通道输出（txt/json/md；md 含逐框置信度★标记）")
    boxes = _boxes([0.95, 0.70])  # 0.70 < 0.85 → 标★
    res = ExtractResult(
        source=SourceType.OCR, text="t0\nt1", confidence=0.825,
        fields={"num_boxes": 2, "confidence_threshold": 0.85, "local_quality_limited": True},
        media_ref={"path": "x.png", "status": "ok"}, provider_meta={"provider": "mock", "cost": "local"},
    )
    with tempfile.TemporaryDirectory() as td:
        outs = ocr_mod.write_outputs(res, td, "x", boxes)
        check("三通道均写出", all(k in outs for k in ("txt", "json", "md")))
        txt = Path(outs["txt"]).read_text(encoding="utf-8")
        check("txt 含识别文本", "t0" in txt and "t1" in txt)
        md = Path(outs["md"]).read_text(encoding="utf-8")
        check("md 含低置信度★标记", "★" in md)
        j = json.loads(Path(outs["json"]).read_text(encoding="utf-8"))
        check("json 为合法 contract（含 source/provider_meta）",
              j.get("source") == SourceType.OCR and "provider_meta" in j)
        check("json 置信度门控字段落盘", j.get("fields", {}).get("local_quality_limited") is True)


def test_full_image_pipeline():
    print("\n[4] OCRModule 全链路（图片：mock provider + patch load_image）")
    # 注：OCRModule 先校验 os.path.isfile，故需一个真实（内容无关）文件占位
    boxes_mixed = _boxes([0.95, 0.90, 0.87])  # avg≈0.907 > 0.85 → 不触发门控
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.png"; _dummy_png(f)
        opts = {"out_dir": td, "use_cache": True, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "load_image", lambda p: _synthetic_image()):
            mod = ocr_mod.OCRModule()
            results = mod.run([str(f)], opts)
        r = results[0]
        check("status=ok", r.media_ref.get("status") == "ok")
        check("输出三通道", set(r.media_ref.get("outputs", {}).keys()) >= {"txt", "json", "md"})
        check("provider_meta 透明回显", r.provider_meta.get("provider") == "mock-ocr"
              and r.provider_meta.get("cost") == "local")
        check("平均置信度计算", r.confidence is not None and r.confidence > 0.85)
        f_ = r.fields
        check("local_quality_limited 边界判定（avg>0.85 不触发）", f_.get("local_quality_limited") is False)


def test_confidence_gating():
    print("\n[5] 置信度门控上云（D2/审阅 D）：低置信度标记建议上云提质，不自动上云")
    boxes_low = _boxes([0.80, 0.72, 0.60])  # avg=0.707 < 0.85
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "low.png"; _dummy_png(f)
        opts = {"out_dir": td, "use_cache": True, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_low)), \
             patch.object(ocr_mod, "load_image", lambda p: _synthetic_image()):
            r = ocr_mod.OCRModule().run([str(f)], opts)[0]
        check("local_quality_limited=True", r.fields.get("local_quality_limited") is True)
        check("标记 suggest_cloud_upgrade（不自动上云）", r.media_ref.get("suggest_cloud_upgrade") is True)
        check("upgrade_hint 提及脱敏闸门", "脱敏" in (r.media_ref.get("upgrade_hint") or ""))


def test_pdf_routing():
    print("\n[6] PDF 类型探测分流（审阅 E / D10 分工）")
    boxes_mixed = _boxes([0.96, 0.91])
    # 6.1 图片型 PDF：纯图页 → 渲染 + OCR
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "img.pdf"; _dummy_png(f)
        opts = {"out_dir": td, "use_cache": False, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        calls = {"render": 0}
        def fake_detect(p): return [{"page_index": 0, "has_text_layer": False}]
        def fake_render(p, idx): calls["render"] += 1; return _synthetic_image(1200, 900)
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "detect_pdf_pages", fake_detect), \
             patch.object(ocr_mod, "render_page", fake_render):
            r = ocr_mod.OCRModule().run([str(f)], opts)[0]
        check("纯图 PDF：页面被渲染", calls["render"] == 1)
        check("纯图 PDF：OCR 产出框数", r.fields.get("num_boxes") == 2)
        check("纯图 PDF：无文本层页跳过", r.fields.get("text_layer_pages_skip") == [])
        check("纯图 PDF：pdf_pages 字段存在", bool(r.fields.get("pdf_pages")))

    # 6.2 含文本层 PDF（默认不强制）：跳过 OCR、建议 document_text（D10）
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "text.pdf"; _dummy_png(f)
        opts = {"out_dir": td, "use_cache": False, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        def fake_detect_txt(p): return [{"page_index": 0, "has_text_layer": True}]
        def fake_render_txt(p, idx): raise AssertionError("不应渲染文本层页")
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "detect_pdf_pages", fake_detect_txt), \
             patch.object(ocr_mod, "render_page", fake_render_txt):
            r = ocr_mod.OCRModule().run([str(f)], opts)[0]
        check("文本层 PDF：跳过 OCR（D10）", r.fields.get("text_layer_pages_skip") == [1])
        check("文本层 PDF：num_boxes=0（未 OCR）", r.fields.get("num_boxes") == 0)
        check("文本层 PDF：提示走 document_text", "document_text" in (r.fields.get("note_document_text") or ""))

    # 6.3 含文本层 PDF + --force-ocr：强制渲染 + OCR
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "text_force.pdf"; _dummy_png(f)
        opts = {"out_dir": td, "use_cache": False, "confidence_threshold": 0.85,
                "force_ocr": True, "preprocess": True, "provider": None}
        def fake_detect_txt2(p): return [{"page_index": 0, "has_text_layer": True}]
        calls = {"render": 0}
        def fake_render_txt2(p, idx): calls["render"] += 1; return _synthetic_image(1200, 900)
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "detect_pdf_pages", fake_detect_txt2), \
             patch.object(ocr_mod, "render_page", fake_render_txt2):
            r = ocr_mod.OCRModule().run([str(f)], opts)[0]
        check("force-ocr：文本层页仍渲染并 OCR", calls["render"] == 1 and r.fields.get("num_boxes") == 2)
        check("force-ocr：无文本层页跳过提示", r.fields.get("text_layer_pages_skip") == [])


def test_cache():
    print("\n[7] 哈希缓存（D12·L）：同文件重跑命中 cached，刷新产出")
    boxes_mixed = _boxes([0.95, 0.90])
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "cache.png"
        _dummy_png(f)
        opts = {"out_dir": td, "use_cache": True, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "load_image", lambda p: _synthetic_image()):
            mod = ocr_mod.OCRModule()
            r1 = mod.run([str(f)], opts)[0]
            r2 = mod.run([str(f)], opts)[0]
        check("首次 status=ok", r1.media_ref.get("status") == "ok")
        check("二次 status=cached", r2.media_ref.get("status") == "cached")
        check("二次仍刷新产出路径", set(r2.media_ref.get("outputs", {}).keys()) >= {"txt", "json", "md"})


def test_batch_aggregate():
    print("\n[8] 批量聚合报告（D12·H）")
    boxes_mixed = _boxes([0.95, 0.90])
    with tempfile.TemporaryDirectory() as td:
        opts = {"out_dir": td, "use_cache": False, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        with patch.object(provider_registry, "get_provider", lambda *a, **k: MockOcrProvider(boxes_mixed)), \
             patch.object(ocr_mod, "load_image", lambda p: _synthetic_image()):
            mod = ocr_mod.OCRModule()
            mod.run(["/fake/a.png", "/fake/b.png"], opts)
        report = Path(td) / "info-extract-ocr-report.md"
        check("聚合报告 md 生成", report.exists())
        check("聚合报告含逐文件与异常清单段", "逐文件" in report.read_text(encoding="utf-8"))


def test_registry_and_router():
    print("\n[9] Provider 注册 + 路由映射（D15 / 路由）")
    provs = provider_registry.available_providers(SourceType.OCR)
    names = [p["name"] for p in provs]
    check("OCR 已注册 rapidocr provider", "rapidocr" in names)
    check("MODULE_MAP 将 OCR 路由到 modules.ocr.OCRModule",
          router.MODULE_MAP.get(SourceType.OCR) == ("modules.ocr", "OCRModule"))
    check("OCRModule.ready=True", ocr_mod.OCRModule.ready is True)


def test_real_provider_optional():
    print("\n[10] 真实 rapidocr 端到端（依赖就绪则实跑，否则 SKIP）")
    try:
        from modules.ocr.providers.rapid_ocr import RapidOcrProvider
    except Exception:
        RapidOcrProvider = None
    if RapidOcrProvider is None or not RapidOcrProvider().available():
        check("真实 rapidocr 用例（SKIP：未安装 rapidocr，仅验证编排）", True, "SKIP")
        return
    try:
        from PIL import Image, ImageDraw
    except Exception:
        check("真实 rapidocr 用例（SKIP：未安装 Pillow 写测试图）", True, "SKIP")
        return

    with tempfile.TemporaryDirectory() as td:
        # 合成一张含英文+数字的真实 PNG（默认位图字体即可渲染 ASCII）
        f = Path(td) / "real_ocr.png"
        img = Image.new("RGB", (600, 200), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((20, 80), "INFO EXTRACT TEST 123", fill=(0, 0, 0))
        img.save(f)

        # 10.1 provider 层直测
        arr = np.asarray(img)
        prov = RapidOcrProvider()
        boxes, info = prov.ocr(arr)
        check("真实 rapidocr 返回非空框", len(boxes) > 0, f"num_boxes={len(boxes)}")
        check("真实 rapidocr 返回置信度", info.get("avg_confidence") is not None,
              f"avg={info.get('avg_confidence')}")

        # 10.2 完整 OCRModule 端到端（真实引擎 + 预处理 + 双通道输出，不 mock）
        opts = {"out_dir": td, "use_cache": False, "confidence_threshold": 0.85,
                "force_ocr": False, "preprocess": True, "provider": None}
        r = ocr_mod.OCRModule().run([str(f)], opts)[0]
        check("真实端到端 status=ok", r.media_ref.get("status") == "ok")
        outs = r.media_ref.get("outputs", {})
        check("真实端到端 三通道产出", set(outs.keys()) >= {"txt", "json", "md"})
        check("真实端到端 provider_meta=rapidocr", r.provider_meta.get("provider") == "rapidocr")
        txt = Path(outs["txt"]).read_text(encoding="utf-8")
        check("真实端到端 txt 含识别文字", len(txt.strip()) > 0 and any(c.isalnum() for c in txt))


def main():
    print("=== info-extract · 阶段三（OCR）验证 ===")
    test_io_routing()
    test_preprocess_degrade()
    test_output_dual_channel()
    test_full_image_pipeline()
    test_confidence_gating()
    test_pdf_routing()
    test_cache()
    test_batch_aggregate()
    test_registry_and_router()
    test_real_provider_optional()

    print(f"\n=== 结果：通过 {len(_PASS)} ｜ 失败 {len(_FAIL)} ===")
    if _FAIL:
        for n in _FAIL:
            print(f"  ❌ {n}")
        return 1
    print("✅ 阶段三 OCR 编排逻辑验证通过（真实推理需安装 rapidocr 依赖）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
