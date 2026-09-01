#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 视觉描述核心（阶段四，D13 / 审阅 F 衔接）。

职责（呼应方案 §3 阶段四 / 流程规范 §2.1 / §2.3）：
- **build_vision_prompt**：构造任务提示词（用户任务 + OCR 协同文字 + 视频讲解段文案）。
- **ocr_text_for_image**：OCR 协同（§1.1 B.3）——先取图中文字，再结合画面语义整体理解。
- **caption_image**：经可插拔 Provider（D15）调用本地 VLM 得视觉描述；provider 不可用时返回 None。
- **fill_d13_frames**：为 D13 讲解段帧填充 `vision_caption` / `ocr_on_frame`（语义重合度判定的
  视觉栈部分，规则信号已在阶段二落地）；provider 不可用则留 None + 提示。
- **analyze_video_frames**：审阅 F 整视频关键帧采样 + 视觉描述 + OCR 协同，供视频「画面识别分类」。

全部经 provider_registry 取 provider（默认本地优先、可手动/自动切换，D15）；
VLM 不可用 → 优雅降级（caption=None），由上层标记建议上云提质（D2），不静默失败。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from modules.base import InfoExtractError, SourceType
from provider_registry import get_provider


def build_vision_prompt(task: Optional[str] = None, ocr_text: Optional[str] = None,
                          seg_text: Optional[str] = None) -> str:
    """构造 VLM 提示词：基础解读指令 + 用户任务 + OCR 协同文字 + （视频）讲解段文案。"""
    parts: List[str] = []
    if seg_text:
        parts.append(f"这是视频中某段讲解画面，对应的口播文案是：{seg_text}")
    parts.append(
        "请解读这张图片：识别画面要素（物体/场景/人物/图表/截图语义），"
        "并按用户任务抽取关键信息；若画面是图表/流程图/思维导图，请说明其结构与要点。"
    )
    if task:
        parts.append(f"用户任务：{task}")
    if ocr_text and ocr_text.strip():
        parts.append(f"图中 OCR 提取到的文字（供参考，若不相关可忽略）：{ocr_text}")
    return "\n".join(parts)


def ocr_text_for_image(rgb, ocr_provider=None) -> Optional[str]:
    """OCR 协同：取图中文字（§1.1 B.3）。返回文字或 None。"""
    if ocr_provider is None:
        ocr_provider = get_provider(SourceType.OCR)
    if ocr_provider is None or not ocr_provider.available():
        return None
    try:
        boxes, _ = ocr_provider.ocr(rgb)
    except Exception:
        return None
    if not boxes:
        return None
    from modules.ocr.output import boxes_to_text

    return boxes_to_text(boxes)


def caption_image(rgb, prompt: str, provider=None, *, ocr_text: Optional[str] = None) -> (str, Dict):
    """经 provider 得视觉描述。返回 (caption_text, info)；provider 不可用返回 (None, {available:False})。"""
    if provider is None:
        provider = get_provider(SourceType.VISION)
    if provider is None or not provider.available():
        return None, {"available": False}
    try:
        text, info = provider.caption(rgb, prompt)
        return text, info
    except InfoExtractError:
        raise
    except Exception as e:  # 其他意外 → 降级为不可用，不静默失败
        return None, {"available": True, "error": str(e)}


def fill_d13_frames(referenced_frame: Optional[Dict], video_path: str, out_dir, stem: str,
                     options: Dict) -> Optional[Dict]:
    """D13：为讲解段帧填充视觉描述（阶段二规则信号已抽帧，此处填 vision_caption/ocr_on_frame）。"""
    if not referenced_frame or not referenced_frame.get("frames"):
        return referenced_frame

    vision_provider = get_provider(SourceType.VISION)
    vision_ok = vision_provider is not None and vision_provider.available()
    ocr_coop = options.get("ocr_coop", True)
    ocr_provider = get_provider(SourceType.OCR) if ocr_coop else None
    ocr_ok = ocr_provider is not None and ocr_provider.available()

    from modules.video.frames import extract_frame_rgb

    for f in referenced_frame["frames"]:
        if not (f.get("extracted") and f.get("frame_path")):
            f["vision_caption"] = f.get("vision_caption")
            f["ocr_on_frame"] = f.get("ocr_on_frame")
            continue
        rgb = None
        try:
            rgb = extract_frame_rgb(video_path, f["timestamp"])
        except Exception:
            rgb = None
        if rgb is None:
            f["vision_caption"] = None
            f["ocr_on_frame"] = None
            continue
        ocr_text = ocr_text_for_image(rgb, ocr_provider) if ocr_ok else None
        f["ocr_on_frame"] = ocr_text
        vision_caption = None
        if vision_ok:
            prompt = build_vision_prompt(
                task=options.get("task") or options.get("lang"),
                ocr_text=ocr_text,
                seg_text=f.get("segment_text"),
            )
            vision_caption, _ = caption_image(rgb, prompt, vision_provider)
        f["vision_caption"] = vision_caption
        f["vision_tier"] = (
            getattr(vision_provider, "tier", {}).get("name") if vision_ok else None
        )

    if not vision_ok:
        note = referenced_frame.get("note", "")
        referenced_frame["note"] = (note + " " if note else "") + (
            "本地未配置 VLM（ollama），vision_caption 未填充；可启用云端提质（D2/§4.4）。"
        )
    return referenced_frame


def analyze_video_frames(video_path: str, out_dir, stem: str, options: Dict) -> Dict:
    """审阅 F：场景切换关键帧采样 + 视觉描述 + OCR 协同，供视频「画面识别分类」。"""
    from modules.vision.frame_sampling import sample_keyframes

    sampling = sample_keyframes(video_path, out_dir=out_dir, stem=stem)
    vision_provider = get_provider(SourceType.VISION)
    vision_ok = vision_provider is not None and vision_provider.available()
    ocr_coop = options.get("ocr_coop", True)
    ocr_provider = get_provider(SourceType.OCR) if ocr_coop else None
    ocr_ok = ocr_provider is not None and ocr_provider.available()

    from modules.video.frames import extract_frame_rgb

    for kf in sampling:
        rgb = None
        try:
            rgb = extract_frame_rgb(video_path, kf["timestamp"])
        except Exception:
            rgb = None
        if rgb is None:
            kf["vision_caption"] = None
            kf["ocr_on_frame"] = None
            continue
        ocr_text = ocr_text_for_image(rgb, ocr_provider) if ocr_ok else None
        kf["ocr_on_frame"] = ocr_text
        cap = None
        if vision_ok:
            prompt = build_vision_prompt(task=options.get("task") or options.get("lang"), ocr_text=ocr_text)
            cap, _ = caption_image(rgb, prompt, vision_provider)
        kf["vision_caption"] = cap
        kf.pop("phash", None)  # 内部哈希不落产出

    return {
        "keyframes": sampling,
        "note": "场景切换关键帧采样 + 视觉描述（审阅 F）；VLM 不可用则仅保留帧图与 OCR 文字。",
    }


__all__ = [
    "build_vision_prompt", "ocr_text_for_image", "caption_image",
    "fill_d13_frames", "analyze_video_frames",
]
