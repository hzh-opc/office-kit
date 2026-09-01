#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · D16 交付物范式验证脚本（识别结果单一备查副本 + 纠正版稿件）。

覆盖：
  - ExtractResult 契约含 raw_text / corrected（base）
  - maybe_correct 各分支：skipped:disabled（--no-correct）/ skipped:no-model（无本地模型）/ applied（mock 本地模型）
  - 输出落地：.txt = 纠正版稿件；.json/.md 含 raw_text + corrected
  - 缓存还原（D12·L）：_contract_to_result_kwargs 还原 raw_text / corrected

不依赖真实 ollama：applied 路径用 monkeypatch 注入本地模型调用，skipped 路径依赖本机未拉取模型（自动优雅跳过）。

运行：scripts/.venv/bin/python tests/verify_phase7.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from modules.base import ExtractResult, Segment, SourceType, contract_to_result  # noqa: E402
from modules.corrector import maybe_correct  # noqa: E402
from modules.audio.output import write_outputs as audio_write  # noqa: E402
from modules.ocr.output import write_outputs as ocr_write  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def _raw_result(text: str) -> ExtractResult:
    return ExtractResult(
        source=SourceType.OCR,
        text=text,
        confidence=0.9,
        fields={"num_boxes": 1},
        media_ref={"path": "x.png", "status": "ok"},
        provider_meta={"provider": "mock", "cost": "local"},
        segments=[Segment(0.0, 1.0, text)],
        raw_text=text,
    )


def test_contract_fields():
    print("\n[1] ExtractResult 契约含 D16 字段（raw_text / corrected）")
    r = _raw_result("原始识别文本")
    c = r.to_contract()
    check("to_contract 含 raw_text", "raw_text" in c)
    check("to_contract 含 corrected", "corrected" in c)
    check("默认 corrected 为 None", c["corrected"] is None)
    check("raw_text = 原始识别", c["raw_text"] == "原始识别文本")


def test_skip_no_correct():
    print("\n[2] maybe_correct：--no-correct → skipped:disabled")
    r = _raw_result("原始识别文本")
    maybe_correct(r, {"no_correct": True})
    cm = (r.provider_meta or {}).get("correction")
    check("状态 skipped:disabled", cm and cm["status"] == "skipped:disabled")
    check("corrected 仍为 None", r.corrected is None)
    check("text 不变（=原始）", r.text == "原始识别文本")
    check("raw_text 保留备查", r.raw_text == "原始识别文本")


def test_skip_no_model():
    print("\n[3] maybe_correct：无本地模型 → skipped:no-model（优雅降级，不联网）")
    r = _raw_result("原始识别文本")
    # 本机未拉取文本模型时，_model_available 返回 False → skipped:no-model
    maybe_correct(r, {})
    cm = (r.provider_meta or {}).get("correction")
    check("状态 skipped:no-model", cm and cm["status"] == "skipped:no-model")
    check("corrected 仍为 None", r.corrected is None)
    check("text 不变", r.text == "原始识别文本")
    check("raw_text 保留备查", r.raw_text == "原始识别文本")


def test_applied():
    print("\n[4] maybe_correct：applied（mock 本地文本模型，离线纠正）")
    import modules.corrector as corrector

    saved_avail = corrector._model_available
    saved_gen = corrector._generate
    corrector._model_available = lambda host, model: True
    corrector._generate = lambda host, model, prompt, timeout=300.0: json.dumps(
        {"corrected_text": "纠正后的文本", "correction_notes": "将'识'改为'识'（示例）"}
    )
    try:
        r = _raw_result("原始识別文本")
        maybe_correct(r, {"context": "化学实验报告"})
        cm = (r.provider_meta or {}).get("correction")
        check("状态 applied", cm and cm["status"] == "applied")
        check("text 被纠正", r.text == "纠正后的文本")
        check("corrected 含 text", r.corrected and r.corrected["text"] == "纠正后的文本")
        check("corrected 含 notes", bool(r.corrected and r.corrected.get("correction_notes")))
        check("correction_source=context", r.corrected and r.corrected["correction_source"] == "context")
        check("raw_text 仍为原始", r.raw_text == "原始识別文本")
    finally:
        corrector._model_available = saved_avail
        corrector._generate = saved_gen


def test_output_dual_channel():
    print("\n[5] D16 输出落地：.txt=纠正版稿件，.json/.md 含 raw_text+corrected")
    import tempfile

    # 音频通道：构造已纠正结果
    r = ExtractResult(
        source=SourceType.TRANSCRIPT,
        text="纠正后的转录",
        confidence=0.9,
        fields={"detected_language": "zh", "duration_sec": 8.0},
        media_ref={"path": "x.mp3", "status": "ok"},
        provider_meta={"provider": "mock", "cost": "local"},
        segments=[Segment(0.0, 2.0, "纠正后的"), Segment(2.0, 4.0, "转录")],
        raw_text="原始转录",
        corrected={"text": "纠正后的转录", "correction_source": "local-model", "model": "qwen2.5:7b",
                   "correction_notes": None, "corrected_at": "2026-08-28T00:00:00"},
    )
    with tempfile.TemporaryDirectory() as td:
        outs = audio_write(r, td, "x")
        check("写出 txt/json/md/srt", all(k in outs for k in ("txt", "json", "md", "srt")))
        txt = Path(outs["txt"]).read_text(encoding="utf-8")
        check("txt 为纠正版稿件", "纠正后的转录" in txt)
        j = json.loads(Path(outs["json"]).read_text(encoding="utf-8"))
        check("json 含 raw_text", j.get("raw_text") == "原始转录")
        check("json 含 corrected", j.get("corrected", {}).get("text") == "纠正后的转录")
        md = Path(outs["md"]).read_text(encoding="utf-8")
        check("md 置顶『纠正版稿件（交付物）』", "## 纠正版稿件（交付物" in md)
        check("md 含『识别结果备查』", "识别结果备查" in md)

    # OCR 通道：.txt 应为纠正版稿件（=result.text）
    r2 = _raw_result("原始OCR")
    r2.text = "纠正后OCR"
    r2.corrected = {"text": "纠正后OCR", "correction_source": "local-model", "model": "qwen2.5:7b",
                    "correction_notes": None, "corrected_at": "2026-08-28T00:00:00"}
    with tempfile.TemporaryDirectory() as td:
        outs = ocr_write(r2, td, "y", [{"text": "原始OCR", "score": 0.9}])
        txt = Path(outs["txt"]).read_text(encoding="utf-8")
        check("OCR txt 为纠正版稿件", "纠正后OCR" in txt and "原始OCR" not in txt.split("\n")[0] or "纠正后OCR" in txt)
        j = json.loads(Path(outs["json"]).read_text(encoding="utf-8"))
        check("OCR json 含 raw_text", j.get("raw_text") == "原始OCR")


def test_cache_restore():
    print("\n[6] 缓存还原（D12·L）：raw_text / corrected 还原")
    r = _raw_result("原始识别文本")
    r.text = "纠正后的文本"  # 交付物（真实流程由 maybe_correct 将 text 置为纠正版稿件）
    r.corrected = {"text": "纠正后的文本", "correction_source": "local-model", "model": "qwen2.5:7b",
                   "correction_notes": "示例", "corrected_at": "2026-08-28T00:00:00"}
    contract = r.to_contract()
    # 模拟缓存命中还原（统一 contract_to_result 直接返回 ExtractResult）
    r2 = contract_to_result(contract)
    check("还原 raw_text", r2.raw_text == "原始识别文本")
    check("还原 corrected.text", r2.corrected and r2.corrected["text"] == "纠正后的文本")
    check("还原 text（交付物）", r2.text == "纠正后的文本")
    # 旧缓存缺 D16 字段 → 优雅回退 None
    old = {k: v for k, v in contract.items() if k not in ("raw_text", "corrected")}
    r3 = contract_to_result(old)
    check("旧缓存缺字段→raw_text=None", r3.raw_text is None)
    check("旧缓存缺字段→corrected=None", r3.corrected is None)


def main() -> int:
    print("=== info-extract · D16 交付物范式验证 ===")
    test_contract_fields()
    test_skip_no_correct()
    test_skip_no_model()
    test_applied()
    test_output_dual_channel()
    test_cache_restore()
    print(f"\n=== D16 结果：通过 {PASS} ｜ 失败 {FAIL} ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
