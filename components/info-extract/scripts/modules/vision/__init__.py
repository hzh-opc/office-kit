#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面解读模块（阶段四，已实现）。

流程（呼应方案 §3 阶段四 + 流程规范 §2.1 / §1.1 B）：
1. 接收图片 / 视频帧 → 敏感预检（上云前由 DESEN 闸门接管，§4.4）。
2. **OCR 协同（§1.1 B.3）**：先取图中文字，再结合画面语义整体理解（默认开启，可 --no-ocr-vision 关闭）。
3. **本地 VLM 视觉理解**（默认 provider：local-vlm / ollama + Qwen2.5-VL，档位自适应 D7）：
   识别画面要素（物体/场景/人物/图表/截图语义），按任务提示解读。
4. **云端升级（D2 交互范式）**：本地 VLM 不可用（未装 ollama / 算力不足）→ 标记建议上云提质
   （不自动上云、上云前须经脱敏闸门）；拒绝则仅交付 OCR 文字、保证不上云。
5. 双通道输出（D11）+ 哈希缓存（D12·L）+ provider_meta 透明回显（D15/§4.7）。
6. 批量输入 + 聚合报告（D12·H），含异常清单。
7. 不支持格式 / 文件缺失（审阅 I）：清晰引导，不静默失败。

与视频帧共用同一视觉栈（方案 §3 阶段四）：视频帧经 frame_sampling / D13 抽帧后，
由 vision_caption 的同一套 caption 逻辑解读（见 modules.video 衔接）。

默认本地优先、默认不上云（§4）；涉及上云/外部调用由交互确认门（⑧⑨）控制，本 CLI 不自动上云。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.base import ExtractResult, IModule, InfoExtractError, SourceType, contract_to_result
from modules.corrector import maybe_correct
from modules.vision.output import write_outputs
from modules.vision.vision_caption import build_vision_prompt, caption_image, ocr_text_for_image
from provider_registry import get_provider
from utils.hash_cache import ResultCache


class VisionModule(IModule):
    name = "vision"
    source_type = SourceType.VISION
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        use_cache = options.get("use_cache", True)
        cache = ResultCache() if use_cache else None
        provider_name = options.get("provider")
        ocr_coop = options.get("ocr_coop", True)
        vision_tier = options.get("vision_tier")
        task = options.get("task") or options.get("lang")

        results: List[ExtractResult] = []
        for path in inputs:
            try:
                res = self._process_one(
                    path, options, out_dir, cache, provider_name, ocr_coop, vision_tier, task
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

    def _process_one(self, path, options, out_dir, cache, provider_name, ocr_coop, vision_tier, task):
        path = str(Path(path).expanduser().resolve())
        if not os.path.isfile(path):
            raise InfoExtractError(f"文件不存在：{path}", recoverable=False)

        cache_key_opts = {
            "vision": True,
            "provider": provider_name,
            "ocr_coop": ocr_coop,
            "vision_tier": vision_tier,
            "task": task,
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
                r.media_ref["outputs"] = write_outputs(r, out_dir, Path(path).stem)
                return r

        # 读取图片为 RGB（Pillow，缺失优雅降级）
        from utils.image import load_image_rgb

        rgb = load_image_rgb(path)

        # OCR 协同（§1.1 B.3）
        ocr_text: Optional[str] = None
        ocr_meta: Optional[Dict] = None
        if ocr_coop:
            ocr_provider = get_provider(SourceType.OCR)
            if ocr_provider is not None and ocr_provider.available():
                ocr_text = ocr_text_for_image(rgb, ocr_provider)
                ocr_meta = ocr_provider.meta()

        # 本地 VLM 视觉理解（D15 默认本地优先；显式指定优先；不可用则降级提示）
        provider = get_provider(SourceType.VISION, name=provider_name)
        provider_ok = provider is not None and provider.available()
        caption: Optional[str] = None
        vision_meta: Optional[Dict] = None
        tier_name: Optional[str] = None
        if provider_ok:
            prompt = build_vision_prompt(task=task, ocr_text=ocr_text)
            caption, _ = caption_image(rgb, prompt, provider)
            vision_meta = provider.meta()
            tier_name = getattr(provider, "tier", {}).get("name") if hasattr(provider, "tier") else None

        # 组合文本：视觉描述优先，无则退回 OCR 文字
        text = caption if caption else (ocr_text or "")

        fields: Dict[str, Any] = {
            "task": task,
            "ocr_text": ocr_text,
            "caption": caption,
            "ocr_coop": ocr_coop,
            "vision_tier": tier_name,
            "vision_available": provider_ok,
        }
        if not provider_ok:
            fields["note"] = "本地未配置 VLM（ollama），仅提供 OCR 文字；可启用云端提质（D2/§4.4）。"

        media_ref: Dict[str, Any] = {"path": path, "status": "ok"}
        if not provider_ok:
            # 置信度门控上云（D2 / 审阅 D 同构）：标记建议、不自动上云（§4 红线）
            media_ref["suggest_cloud_upgrade"] = True
            media_ref["upgrade_hint"] = (
                "本地未配置视觉模型（ollama + Qwen2.5-VL），画面解读不可用；"
                "如需高质量解读可上云提质；上云前需经脱敏闸门、原始图留本机（D2/§4.4）。"
            )

        provider_meta = dict(vision_meta or {})
        if ocr_meta:
            provider_meta["ocr_provider"] = ocr_meta.get("provider")

        result = ExtractResult(
            source=SourceType.VISION,
            text=text,
            confidence=None,  # VLM 无干净置信度，记未知（§4.1 透明）
            fields=fields,
            media_ref=media_ref,
            provider_meta=provider_meta,
        )

        # D16 交付物范式：固定原始识别为单一备查副本，再尝试生成纠正版稿件
        result.raw_text = result.text
        maybe_correct(result, options)
        # 双通道输出（D11）
        outputs = write_outputs(result, out_dir, Path(path).stem)
        result.media_ref["outputs"] = outputs

        # 写缓存（D12·L）：仅落本地私有目录，不外传
        if cache is not None:
            cache.put(path, cache_key_opts, result.to_contract())

        return result

    def _error_result(self, path: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.VISION,
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
        lines = ["# info-extract 画面解读 · 批量聚合报告", ""]
        lines.append(f"- 总计：{len(results)} 个文件")
        lines.append(f"- 成功：{len(ok)} ｜ 缓存命中：{len(cached)} ｜ 异常：{len(errs)}")
        lines.append("")
        lines.append("## 逐文件")
        for r in results:
            mr = r.media_ref
            line = f"- `{mr.get('path')}` → **{mr.get('status')}**"
            if mr.get("status") == "ok":
                cap = r.fields.get("caption")
                line += (
                    f"（VLM={'✅' if r.fields.get('vision_available') else '⚠️未配置'}"
                    f"，OCR协同={'✅' if r.fields.get('ocr_text') else '—'}"
                    + (f"，tier={r.fields.get('vision_tier')}" if r.fields.get('vision_tier') else "")
                    + "）"
                )
                if cap:
                    line += f" 解读：{cap[:40]}{'…' if len(cap) > 40 else ''}"
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
        md_path = out_dir_p / "info-extract-vision-report.md"
        json_path = out_dir_p / "info-extract-vision-report.json"
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


__all__ = ["VisionModule"]
