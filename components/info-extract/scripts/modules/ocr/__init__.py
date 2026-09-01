#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 模块（阶段三，已实现）。

流程（呼应方案 §3 阶段三 + 流程规范 §2.1 / §2.5）：
1. 接收图片 / 图片型 PDF → 敏感预检（上云前由 DESEN 闸门接管，§4.4）。
2. 图像预处理链（审阅 D）：归一化（最长边≤2000px）→ 方向校正 → 可选去噪/超分 → 可选 deskew；
   给出逐框置信度与平均置信度。
3. 图片型 PDF（pypdfium2 渲染）：PDF 类型探测（审阅 E）分流——
   纯图页渲染 + OCR；有原生文本层页（D10 分工）默认跳过 OCR、建议走 document_text，除非 --force-ocr 强制。
4. rapidocr 本地 OCR（默认 provider，PP-OCRv6）→ 文本 + 逐框置信度。
5. 置信度门控上云（审阅 D，替代旧「手写/模糊一刀切」）：平均置信度 < 阈值 → 标记「本地质量受限」、
   建议上云提质（D2 交互范式），不自动上云、上云前须经脱敏闸门。
6. 双通道输出（D11）+ 哈希缓存（D12·L）+ provider_meta 透明回显（D15/§4.7）。
7. 批量输入 + 聚合报告（D12·H），含异常清单。
8. 不支持格式 / 加密 PDF（审阅 I）：清晰引导，不静默失败。

默认本地优先、默认不上云（§4）；涉及上云/外部调用由交互确认门（⑧⑨）控制，本 CLI 不自动上云。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from modules.base import ExtractResult, IModule, InfoExtractError, SourceType, contract_to_result
from modules.corrector import maybe_correct
from modules.ocr.output import boxes_to_text, write_outputs
from modules.ocr.pdf import detect_pdf_pages, render_page
from modules.ocr.preprocess import load_image, preprocess_image
from utils.hash_cache import ResultCache

# 置信度门控阈值（审阅 D）：低于此值标记本地质量受限、提示上云提质（D2）
CONF_THRESHOLD = 0.85


class OCRModule(IModule):
    name = "ocr"
    source_type = SourceType.OCR
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        use_cache = options.get("use_cache", True)
        cache = ResultCache() if use_cache else None
        conf_threshold = options.get("confidence_threshold", CONF_THRESHOLD)
        force_ocr = options.get("force_ocr", False)
        do_preprocess = options.get("preprocess", True)
        provider_name = options.get("provider")

        results: List[ExtractResult] = []
        for path in inputs:
            try:
                res = self._process_one(
                    path, options, out_dir, cache, conf_threshold, force_ocr, do_preprocess, provider_name
                )
                results.append(res)
            except InfoExtractError as e:
                results.append(self._error_result(path, e))
            except Exception as e:  # 兜底，绝不静默失败
                results.append(
                    self._error_result(path, InfoExtractError(f"未预期错误：{e}", recoverable=False))
                )

        # 批量聚合报告（D12·H）
        if len(inputs) > 1:
            self._write_aggregate(results, out_dir)

        return results

    def _process_one(self, path, options, out_dir, cache, conf_threshold, force_ocr, do_preprocess, provider_name):
        path = str(Path(path).expanduser().resolve())
        if not os.path.isfile(path):
            raise InfoExtractError(f"文件不存在：{path}", recoverable=False)

        ext = Path(path).suffix.lower()
        is_pdf = ext == ".pdf"

        cache_key_opts = {
            "ocr": True,
            "provider": provider_name,
            "force_ocr": force_ocr,
            "preprocess": do_preprocess,
            "conf_threshold": conf_threshold,
            # D16 纠正版稿件选项（影响 text/corrected，须纳入缓存键）
            "context": options.get("context"),
            "correct_model": options.get("correct_model"),
            "no_correct": options.get("no_correct", False),
        }

        # 哈希缓存（D12·L）
        if cache is not None:
            hit = cache.get(path, cache_key_opts)
            if hit:
                r = contract_to_result(hit)
                r.media_ref = r.media_ref or {}
                r.media_ref.update({"path": path, "status": "cached", "outputs": {}})
                r.media_ref["outputs"] = write_outputs(r, out_dir, Path(path).stem, hit.get("_boxes", []))
                return r

        # 选 provider（D15 默认本地优先；显式指定优先；不可用则降级提示）
        from provider_registry import get_provider

        provider = get_provider(SourceType.OCR, name=provider_name)
        if provider is None or not provider.available():
            raise InfoExtractError(
                "未找到可用的本地 OCR 引擎（rapidocr）。请先安装技能依赖。",
                recoverable=True,
                hint="运行技能目录下 install.py / install.sh 安装 rapidocr onnxruntime pypdfium2 pillow。",
            )

        all_boxes: List[Dict] = []
        pages_meta: List[Dict] = []
        text_layer_pages: List[int] = []
        preprocess_log: List[str] = []

        if is_pdf:
            # PDF 类型探测 + 渲染（审阅 E）；加密 PDF 捕获提示密码（审阅 I）
            try:
                page_infos = detect_pdf_pages(path)
            except Exception as e:
                msg = str(e).lower()
                if "password" in msg or "encrypt" in msg:
                    raise InfoExtractError(
                        "该 PDF 已加密，请输入密码或先解密后再处理（审阅 I）。",
                        recoverable=True,
                    ) from e
                raise InfoExtractError(f"PDF 解析失败：{e}", recoverable=True) from e

            for pi in page_infos:
                idx = pi["page_index"]
                if pi["has_text_layer"] and not force_ocr:
                    # D10 分工：文本层页不归 info-extract，建议 document_text
                    text_layer_pages.append(idx + 1)
                    continue
                img = render_page(path, idx)
                if img is None:
                    continue
                boxes, info = self._ocr_image(provider, img, do_preprocess)
                all_boxes.extend(boxes)
                pages_meta.append({
                    "page": idx + 1,
                    "num_boxes": len(boxes),
                    "avg_confidence": info.get("avg_confidence"),
                })
        else:
            # 单张图片：加载 → 预处理 → OCR
            img = load_image(path)
            boxes, info = self._ocr_image(provider, img, do_preprocess)
            all_boxes.extend(boxes)
            pages_meta.append({"page": 1, "num_boxes": len(boxes), "avg_confidence": info.get("avg_confidence")})
            preprocess_log = info.get("preprocess", [])

        avg_conf = round(float(np.mean([b["score"] for b in all_boxes])), 3) if all_boxes else None
        text = boxes_to_text(all_boxes)
        low_conf = avg_conf is not None and avg_conf < conf_threshold

        fields: Dict[str, Any] = {
            "num_boxes": len(all_boxes),
            "confidence_threshold": conf_threshold,
            "local_quality_limited": low_conf,
            "pages": len(pages_meta) + len(text_layer_pages),  # 图片=1；PDF=总页数
        }
        if is_pdf:
            fields["pdf_pages"] = pages_meta
            fields["text_layer_pages_skip"] = text_layer_pages  # D10：原生文本层页已跳过
            if text_layer_pages:
                fields["note_document_text"] = (
                    f"第 {text_layer_pages} 页含原生文本层，按分工(D10)已跳过 OCR，"
                    f"建议用 document_text 技能抽取文本层（信息抽取只做媒体抽取）"
                )
        else:
            fields["preprocess_steps"] = preprocess_log

        result = ExtractResult(
            source=SourceType.OCR,
            text=text,
            confidence=avg_conf,
            fields=fields,
            media_ref={
                "path": path,
                "status": "ok",
                "is_pdf": is_pdf,
                "pages": len(pages_meta) + len(text_layer_pages),
            },
            provider_meta=provider.meta(),
        )

        # 置信度门控上云（审阅 D → D2）：标记建议、不自动上云（§4 红线）
        if low_conf:
            result.media_ref["suggest_cloud_upgrade"] = True
            result.media_ref["upgrade_hint"] = (
                f"本地平均置信度偏低（<{conf_threshold:.2f}），可上云提质；"
                f"上云前需经脱敏闸门、原始图留本机（D2/§4.4）。"
            )

        # D16 交付物范式：固定原始识别为单一备查副本，再尝试生成纠正版稿件
        result.raw_text = result.text
        maybe_correct(result, options)
        # 双通道输出（D11）
        outputs = write_outputs(result, out_dir, Path(path).stem, all_boxes)
        result.media_ref["outputs"] = outputs

        # 写缓存（D12·L）：仅落本地私有目录，不外传
        if cache is not None:
            contract = result.to_contract()
            contract["_boxes"] = all_boxes  # 缓存附带逐框，便于命中后直接落盘
            cache.put(path, cache_key_opts, contract)

        return result

    def _ocr_image(self, provider, img: np.ndarray, do_preprocess: bool):
        """单图预处理 + OCR；返回 (boxes, info)。"""
        if do_preprocess:
            img, steps = preprocess_image(img)
        else:
            steps = []
        boxes, info = provider.ocr(img)
        info = dict(info)
        info["preprocess"] = steps
        return boxes, info

    def _error_result(self, path: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.OCR,
            text="",
            media_ref={
                "path": path,
                "status": "error",
                "error": err.message,
                "recoverable": err.recoverable,
                "hint": err.hint,
            },
        )

    def _write_aggregate(self, results: List[ExtractResult], out_dir: str) -> Dict[str, str]:
        ok = [r for r in results if r.media_ref.get("status") == "ok"]
        errs = [r for r in results if r.media_ref.get("status") == "error"]
        cached = [r for r in results if r.media_ref.get("status") == "cached"]
        lines = ["# info-extract OCR · 批量聚合报告", ""]
        lines.append(f"- 总计：{len(results)} 个文件")
        lines.append(f"- 成功：{len(ok)} ｜ 缓存命中：{len(cached)} ｜ 异常：{len(errs)}")
        lines.append("")
        lines.append("## 逐文件")
        for r in results:
            mr = r.media_ref
            line = f"- `{mr.get('path')}` → **{mr.get('status')}**"
            if mr.get("status") == "ok":
                line += (
                    f"（页数={r.fields.get('pages')}, 框数={r.fields.get('num_boxes')}, "
                    f"置信度={r.confidence}"
                    + (", 本地质量受限" if r.fields.get("local_quality_limited") else "")
                    + "）"
                )
                if r.fields.get("text_layer_pages_skip"):
                    line += f"  ［文本层页 {r.fields['text_layer_pages_skip']} 已跳过→建议 document_text］"
            elif mr.get("status") == "error":
                line += f" ⚠️ {mr.get('error')}"
                if mr.get("hint"):
                    line += f" 建议：{mr.get('hint')}"
            lines.append(line)
        if errs:
            lines.append("")
            lines.append("## 异常清单（请核对，未静默放过）")
            for r in errs:
                lines.append(f"- `{r.media_ref.get('path')}`：{r.media_ref.get('error')}")
        content = "\n".join(lines) + "\n"

        out_dir_p = Path(out_dir)
        out_dir_p.mkdir(parents=True, exist_ok=True)
        md_path = out_dir_p / "info-extract-ocr-report.md"
        json_path = out_dir_p / "info-extract-ocr-report.json"
        md_path.write_text(content, encoding="utf-8")
        json_path.write_text(
            __import__("json").dumps(
                {
                    "total": len(results),
                    "ok": len(ok),
                    "cached": len(cached),
                    "error": len(errs),
                    "items": [
                        {
                            "path": r.media_ref.get("path"),
                            "status": r.media_ref.get("status"),
                            "fields": r.fields,
                            "outputs": r.media_ref.get("outputs", {}),
                            "error": r.media_ref.get("error"),
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if results:
            results[0].media_ref["report"] = {"md": str(md_path), "json": str(json_path)}
        return {"md": str(md_path), "json": str(json_path)}


__all__ = ["OCRModule"]
