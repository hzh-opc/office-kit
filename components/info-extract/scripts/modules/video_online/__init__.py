#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在线/加密视频模块（阶段五，已实现）。

流程（呼应方案 §3 阶段五 + 流程规范 §2.4）：
1. 在线视频：yt-dlp 优先下载至私有 tmp 沙箱（keep=False → 处理后即删，不留存副本，D3）；
   加密/DRM 或 yt-dlp 失败时回退「浏览器播放+捕获」（BrowserCaptureProvider，依赖 browser 技能，D9）。
2. 加密视频：仅「播放中捕获」；显式提示法律与质量风险（§4 边界 #2）。
3. 强约束：录制副本默认不本地/云端保存（D3）——仅下载至 tmp 沙箱、处理后即清；
   产出仅转文字/字幕/结构化（不含视频副本），⑩ 不产出视频副本。
4. 复用阶段二转录管线（PyAV 抽音轨 → transcribe_core → 双通道输出 + D13 帧 + 审阅 F 关键帧）。
5. provider_meta 透明回显（D15/§4.7）；批量聚合报告（D12·H）；哈希缓存按 URL（D12·L）。

默认本地优先、默认不上云（§4）；涉及上云/外部调用由交互确认门控制，本 CLI 不自动上云。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.audio.language import parse_language_hint, parse_task_hint
from modules.audio.output import write_outputs
from modules.audio.vad import TARGET_SR, load_audio
from modules.base import ExtractResult, IModule, InfoExtractError, SourceType, contract_to_result
from modules.video.frames import extract_referenced_frames
from modules.video_online.providers import PROVIDERS
from utils.hash_cache import ResultCache
from utils.io import format_seconds
from utils.tmp import TempSandbox

# 法律/质量风险提示语（加密/DRM 场景，§4 边界 #2）
LEGAL_RISK_NOTE = (
    "⚠️ 加密/DRM 视频属法律灰区，且录制质量损失大；仅建议处理你有权访问的内容，"
    "不要规避版权保护机制（§4 边界 #2）。"
)

# 账号/合集批量处理提示（方案 B，§4 边界 #2/#3）：尊重平台条款与版权，不规避访问/保护机制
ACCOUNT_ENUM_NOTE = (
    "ℹ️ 账号/合集视频批量处理：仅建议用于你有权访问的内容，并遵守对应平台的服务条款与版权规定"
    "（§4 边界 #2/#3）；本技能不规避任何登录/版权保护机制，副本默认不保存（D3）。"
)

# 防风控限速提示（方案 B 后续强化）：账号/合集批量按序处理 + 随机间隔，降低封号/限流风险
ANTI_BAN_NOTE = (
    "🛡️ 防风控限速：账号/合集视频按顺序逐条处理，相邻视频之间随机间隔（默认约 3 秒，"
    "可用 --enum-interval 调整；--no-throttle 可关闭，仅当你明确拥有这些内容且接受平台风控风险时）。"
    "超大账号建议用 --enum-limit 分批处理，进一步降低封号/限流风险。"
)

LONG_THRESHOLD_SEC = 600  # 与音频/视频一致（D12·J）

# 账号/合集批量处理防风控限速（默认约 3 秒，随机抖动；§4 边界 #2/#3）
DEFAULT_ENUM_INTERVAL = 3.0


def _yt_provider():
    from provider_registry import get_provider

    return get_provider(SourceType.VIDEO_ONLINE, name="yt-dlp")


def _browser_provider():
    from provider_registry import get_provider

    return get_provider(SourceType.VIDEO_ONLINE, name="browser-capture")


def _enum_provider():
    from provider_registry import get_provider

    return get_provider(SourceType.VIDEO_ONLINE_ENUM, name="yt-dlp-enum")


def _should_enumerate(url: str, options: Dict[str, Any]) -> bool:
    """是否对给定 URL 走账号/合集枚举分支。

    - 显式 --playlist/--account（options["enumerate"]）强制枚举；
    - 否则按 URL 模式识别（抖音/小红书/B站 账号页、频道、播放列表）。
    """
    if options.get("enumerate"):
        return True
    from modules.video_online.providers.ytdlp_enum import detect_account_url
    return detect_account_url(url) is not None


class VideoOnlineModule(IModule):
    name = "video_online"
    source_type = SourceType.VIDEO_ONLINE
    ready = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        out_dir = options.get("out_dir") or os.getcwd()
        use_cache = options.get("use_cache", True)
        cache = ResultCache() if use_cache else None
        model_size = options.get("model") or options.get("model_size") or "small"
        vad_threshold = options.get("vad_threshold", 700)  # min_silence_ms
        long_threshold = options.get("long_threshold", LONG_THRESHOLD_SEC)
        extract_frames = options.get("extract_frames", True)

        # —— 账号/合集枚举展开（方案 B）——
        # 把「账号/合集 URL」展开为「逐条视频 URL」；单条视频 URL 原样进入下载管线。
        # leaf: list of (video_url, account_url_or_None)；account_errors: 枚举失败/空账号的账号级错误
        enum = _enum_provider()
        leaf: List[tuple] = []
        account_errors: List[tuple] = []
        enum_report: Dict[str, Dict] = {}

        for url in inputs:
            if _should_enumerate(url, options) and enum is not None and enum.available():
                try:
                    res = enum.enumerate(url, options)
                    entries = res.get("entries") or []
                    # 防风控：单账号视频数上限（默认不限制；超大账号建议分批，降低风控/成本）
                    enum_limit = options.get("enum_limit")
                    if enum_limit and int(enum_limit) > 0 and len(entries) > int(enum_limit):
                        capped = entries[: int(enum_limit)]
                        res = dict(res)
                        res["entries"] = capped
                        res["note"] = (res.get("note") or "") + (
                            f" 〔防风控：仅处理前 {int(enum_limit)}/{len(entries)} 条，"
                            f"其余请分批或调大 --enum-limit〕"
                        )
                        entries = capped
                    enum_report[url] = res
                    if not entries:
                        account_errors.append((url, InfoExtractError(
                            "账号/合集内未枚举到任何视频。",
                            recoverable=True,
                            hint="链接可能需登录(cookie)、账号为空或平台结构变更；"
                                 "用 --cookies-from-browser 重试（§4 边界 #2/#3）。",
                        )))
                        continue
                    for e in entries:
                        leaf.append((e["url"], url))
                except InfoExtractError as e:
                    account_errors.append((url, e))
            elif _should_enumerate(url, options):
                # 应枚举但枚举 Provider 不可用（缺 yt-dlp）→ 账号级错误，引导安装
                account_errors.append((url, InfoExtractError(
                    "枚举账号/合集视频需 yt-dlp（下载/枚举工具）。",
                    recoverable=True,
                    hint="请先安装 yt-dlp：pip install yt-dlp 或 brew install yt-dlp；"
                         "抖音/小红书/B站 账号视频还需 --cookies-from-browser 登录态。",
                )))
            else:
                leaf.append((url, None))

        results: List[ExtractResult] = []
        # 账号/合集展开 → 启用防风控限速（顺序处理 + 随机间隔），降低平台封号/限流风险
        is_account_batch = bool(enum_report)
        enum_interval = options.get("enum_interval", DEFAULT_ENUM_INTERVAL)
        no_throttle = options.get("no_throttle", False)
        safety_note = ""
        if is_account_batch:
            if no_throttle:
                safety_note = ("⚠️ 已关闭防风控限速（--no-throttle）：你明确接受平台风控/封号风险。"
                               "（§4 边界 #2/#3）")
            else:
                safety_note = (f"🛡️ 防风控限速已启用：账号/合集视频按序逐条处理，相邻视频随机间隔约 "
                               f"{float(enum_interval):g} 秒（0.5x~1.5x 抖动）。")
        for idx, (url, account_url) in enumerate(leaf):
            # 防风控：账号批量模式下，首条之后按随机抖动间隔休眠（避免固定节奏被识别为爬虫）
            if is_account_batch and not no_throttle and idx > 0 and enum_interval and float(enum_interval) > 0:
                jitter = float(enum_interval) * (0.5 + random.random())
                time.sleep(jitter)
            try:
                res = self._process_one(
                    url, options, out_dir, cache, model_size,
                    vad_threshold, long_threshold, extract_frames, account_url,
                )
                results.append(res)
            except InfoExtractError as e:
                results.append(self._error_result(url, e))
            except Exception as e:  # 兜底，绝不静默失败
                results.append(
                    self._error_result(url, InfoExtractError(f"未预期错误：{e}", recoverable=False))
                )

        # 账号级错误同样进入结果（不静默失败）
        for (url, err) in account_errors:
            results.append(self._error_result(url, err))

        # 批量聚合报告（D12·H）：多输入或含账号枚举时均生成（账号展开后视频数 >1）
        if len(inputs) > 1 or enum_report:
            self._write_aggregate(results, out_dir, enum_report, safety_note=safety_note)

        return results

    def _acquire(self, url: str, options: Dict[str, Any]) -> Tuple[str, Optional[TempSandbox], Dict[str, Any]]:
        """获取可转录媒体（在线：yt-dlp；加密回退：浏览器捕获）。

        返回 (video_path, sandbox, meta)：
        - sandbox 为下载临时沙箱（keep=False），处理完由调用方 cleanup() 即删；external 文件 sandbox=None。
        - 全程不静默失败：无可用工具 / DRM 无捕获 → 抛 InfoExtractError（recoverable + 法律/质量 hint）。
        """
        yt = _yt_provider()
        bc = _browser_provider()

        # 1) 优先 yt-dlp（本地内置）
        if yt is not None and yt.available():
            sandbox = TempSandbox(keep=False)
            try:
                meta = yt.acquire(url, str(sandbox.dir), options)
                return meta["video_path"], sandbox, meta
            except InfoExtractError as e:
                sandbox.cleanup()
                # 加密/DRM 或失败 → 尝试浏览器捕获回退
                if bc is not None and bc.available():
                    try:
                        # 浏览器捕获为 external 文件（不写 tmp），无需沙箱目录；
                        # 传 "" 避免 cleanup 后再访问 sandbox.dir 触发重建空目录泄漏
                        meta = bc.acquire(url, "", options)
                        return meta["video_path"], None, meta
                    except InfoExtractError:
                        raise  # 回退也无捕获 → 透传（hint 已含法律/质量风险）
                raise  # 无回退 → 透传 yt 原始错误

        # 2) yt-dlp 不可用 → 直接尝试浏览器捕获
        if bc is not None and bc.available():
            meta = bc.acquire(url, "", options)
            return meta["video_path"], None, meta

        # 3) 均不可用 → 明确引导，不静默失败
        raise InfoExtractError(
            "在线/加密视频处理需要 yt-dlp（下载）或 browser 技能（播放中捕获），当前均不可用。",
            recoverable=True,
            hint="安装 yt-dlp：pip install yt-dlp（或 brew install yt-dlp）；"
                 "加密视频另需 browser 技能做播放中捕获（§4 边界 #2）。",
        )

    def _process_one(self, url, options, out_dir, cache, model_size, vad_threshold, long_threshold, extract_frames, account_url=None):
        url = (url or "").strip()
        if not url:
            raise InfoExtractError("空 URL。", recoverable=False)

        # 语言 / 任务轻提示（D12·K）：优先显式参数
        hint = options.get("lang") or ""
        language = parse_language_hint(hint) or options.get("language")
        task = parse_task_hint(options.get("task") or hint) or options.get("task") or "transcribe"

        # 哈希缓存（D12·L）：按 URL 缓存转写结果（内容可能更新；仅本地、不外传）
        cache_key_opts = {
            "lang": language, "task": task, "model": model_size,
            "provider": options.get("provider"), "vad_threshold": vad_threshold,
            "online": True, "vision_frames": options.get("vision", False),
            "extract_frames": extract_frames,  # D13 讲解段抽帧开关影响 referenced_frame
            # D16 纠正版稿件选项（影响 text/corrected，须纳入缓存键）
            "context": options.get("context"),
            "correct_model": options.get("correct_model"),
            "no_correct": options.get("no_correct", False),
        }
        if cache is not None:
            hit = cache.get(url, cache_key_opts)
            if hit:
                r = contract_to_result(hit)
                r.media_ref = r.media_ref or {}
                r.media_ref.update({
                    "url": url, "status": "cached", "online": True,
                    "no_copy_saved": True, "encrypted": r.media_ref.get("encrypted", False),
                    "acquire_method": r.media_ref.get("acquire_method"), "outputs": {},
                })
                r.media_ref["outputs"] = write_outputs(r, out_dir, self._stem(url, r.fields.get("title")))
                return r

        # 获取媒体（在线：yt-dlp；加密回退：浏览器捕获）
        video_path, sandbox, meta = self._acquire(url, options)
        stem = self._stem(url, meta.get("title"))
        # 标记 external（沙箱外文件，如用户 capture_path → 模块不删）
        external = bool(meta.get("external"))
        if not external and sandbox is not None:
            external = not str(video_path).startswith(str(sandbox.dir))

        try:
            # 抽音轨（PyAV 对视频容器同样有效；无音轨则清晰报错，不静默失败）
            samples, sr = load_audio(video_path, TARGET_SR)

            # 核心转录（复用阶段一/二 Whisper 管线；path 用 URL 便于缓存溯源）
            opts = dict(options)
            opts["lang"] = opts.get("lang") or meta.get("title") or ""
            result = self._transcribe_core(
                samples, sr, url, opts, cache, model_size, vad_threshold, long_threshold,
            )

            # 在线/加密专属字段标注（D3 / §4 边界 #2 / D15 透明）
            result.fields["online"] = True
            result.fields["no_copy_saved"] = True
            result.fields["acquire_method"] = meta.get("method")
            result.fields["encrypted"] = bool(meta.get("encrypted"))
            result.fields["title"] = meta.get("title")
            result.media_ref.update({
                "url": url, "online": True, "no_copy_saved": True,
                "encrypted": bool(meta.get("encrypted")),
                "acquire_method": meta.get("method"), "status": "ok",
            })
            # 账号/合集来源透明标注（方案 B）：该视频由哪个账号/合集 URL 展开而来
            if account_url:
                result.media_ref["from_account"] = account_url
                result.provider_meta = result.provider_meta or {}
                result.provider_meta["enum_provider"] = "yt-dlp-enum"
            if meta.get("encrypted"):
                result.fields["legal_risk_warning"] = LEGAL_RISK_NOTE
                result.media_ref["legal_risk_warning"] = LEGAL_RISK_NOTE

            # D13：讲解段关联帧抽取（默认启用；从 tmp 视频抽帧，帧图落输出目录供查阅，不自动上云）
            if extract_frames:
                rf = extract_referenced_frames(video_path, result.segments, out_dir, stem, enabled=True)
                if rf is not None:
                    try:
                        from modules.vision.vision_caption import fill_d13_frames
                        rf = fill_d13_frames(rf, video_path, out_dir, stem, options)
                    except Exception:
                        pass
                    result.referenced_frame = rf
                    result.fields["visual_frames"] = len(rf["frames"])
                    n_cap = sum(1 for f in rf["frames"] if f.get("vision_caption"))
                    if n_cap:
                        result.fields["visual_frames_captioned"] = n_cap

            # 审阅 F：整视频关键帧采样 + 视觉描述（--vision 开启；VLM 不可用则仅留帧图与 OCR 文字）
            if options.get("vision"):
                try:
                    from modules.vision.vision_caption import analyze_video_frames
                    kfa = analyze_video_frames(video_path, out_dir, stem, options)
                    if kfa.get("keyframes"):
                        result.fields["keyframe_analysis"] = kfa
                except Exception:
                    pass

            # 双通道输出（D11）：仅文案/字幕/结构化，**不含视频副本**（D3/⑩）
            outputs = write_outputs(result, out_dir, stem)
            result.media_ref["outputs"] = outputs

            # 写缓存（D12·L）：仅落本地私有目录，不外传
            if cache is not None:
                cache.put(url, cache_key_opts, result.to_contract())

            return result
        finally:
            # 临时沙箱清理（keep=False → 无论成败均删除下载副本，不留存，审阅 G/D3）
            if sandbox is not None:
                sandbox.cleanup()

    def _transcribe_core(self, samples, sr, url, opts, cache, model_size, vad_threshold, long_threshold):
        """复用阶段一/二转录核心（避免循环 import 时机的尴尬）。"""
        from modules.audio.transcribe import transcribe_core

        return transcribe_core(
            samples, sr, url, opts, opts.get("out_dir") or os.getcwd(), cache,
            model_size, vad_threshold, long_threshold,
            source_type=SourceType.TRANSCRIPT,
        )

    @staticmethod
    def _stem(url: str, title: Optional[str]) -> str:
        """为 URL 产出安全的输出文件名（优先用标题，退化为 URL 哈希）。

        注：此处 md5 仅用于把 URL 映射为短文件名（非安全用途），不涉及任何安全保证。
        """
        if title:
            s = re.sub(r"[^\w一-鿿-]+", "_", title).strip("_")
            if s:
                return s[:60]
        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        return f"online_{h}"

    def _error_result(self, url: str, err: InfoExtractError) -> ExtractResult:
        return ExtractResult(
            source=SourceType.VIDEO_ONLINE,
            text="",
            media_ref={
                "url": url,
                "online": True,
                "status": "error",
                "error": err.message,
                "recoverable": err.recoverable,
                "hint": err.hint,
            },
        )

    def _write_aggregate(self, results: List[ExtractResult], out_dir: str,
                         enum_report: Dict[str, Dict] = None, safety_note: str = None) -> Dict[str, str]:
        enum_report = enum_report or {}
        ok = [r for r in results if r.media_ref.get("status") == "ok"]
        errs = [r for r in results if r.media_ref.get("status") == "error"]
        cached = [r for r in results if r.media_ref.get("status") == "cached"]
        lines = ["# info-extract 在线/加密视频 · 批量聚合报告", ""]
        lines.append(f"- 总计：{len(results)} 个 URL（含账号/合集展开的视频）")
        lines.append(f"- 成功：{len(ok)} ｜ 缓存命中：{len(cached)} ｜ 异常：{len(errs)}")
        if enum_report:
            lines.append(f"- 账号/合集枚举：{len(enum_report)} 个（展开视频共 "
                         f"{sum(r.get('count', 0) for r in enum_report.values())} 条）")
            lines.append("")
            lines.append(ACCOUNT_ENUM_NOTE)
            if safety_note:
                lines.append("")
                lines.append(safety_note)
        lines.append("")

        # 账号/合集枚举明细（方案 B）
        if enum_report:
            lines.append("## 账号/合集枚举明细")
            for acct, res in enum_report.items():
                entries = res.get("entries") or []
                lines.append(f"- 账号/合集：`{acct}`（平台={res.get('platform', 'unknown')}，"
                             f"枚举到 {res.get('count', len(entries))} 条视频）")
                for e in entries[:20]:
                    lines.append(f"  - {e.get('title') or e.get('id') or ''} → `{e.get('url')}`")
                if len(entries) > 20:
                    lines.append(f"  - …（其余 {len(entries) - 20} 条见各自产出）")
            lines.append("")

        lines.append("## 逐 URL")
        for r in results:
            mr = r.media_ref
            line = f"- `{mr.get('url')}` → **{mr.get('status')}**"
            if mr.get("from_account"):
                line += f" 〔来自账号 `{mr.get('from_account')}`〕"
            if mr.get("status") == "ok":
                line += (
                    f"（获取={mr.get('acquire_method')}, 语言={r.fields.get('detected_language')}, "
                    f"时长={format_seconds(r.fields.get('duration_sec', 0))}, 置信度={r.confidence}"
                    + (f", 加密" if r.fields.get('encrypted') else "")
                    + (f", 讲解帧={r.fields.get('visual_frames')}" if r.fields.get('visual_frames') else "")
                    + "；副本未保存(D3)）"
                )
            elif mr.get("status") == "error":
                line += f" ⚠️ {mr.get('error')}"
                if mr.get("hint"):
                    line += f" 建议：{mr.get('hint')}"
            lines.append(line)
        if errs:
            lines.append("")
            lines.append("## 异常清单（请核对，未静默放过）")
            for r in errs:
                lines.append(f"- `{r.media_ref.get('url')}`：{r.media_ref.get('error')}")
        content = "\n".join(lines) + "\n"

        out_dir_p = Path(out_dir)
        out_dir_p.mkdir(parents=True, exist_ok=True)
        md_path = out_dir_p / "info-extract-video-online-report.md"
        json_path = out_dir_p / "info-extract-video-online-report.json"
        md_path.write_text(content, encoding="utf-8")
        json_path.write_text(
            __import__("json").dumps(
                {
                    "total": len(results),
                    "ok": len(ok),
                    "cached": len(cached),
                    "error": len(errs),
                    "account_enum": enum_report,
                    "items": [
                        {
                            "url": r.media_ref.get("url"),
                            "status": r.media_ref.get("status"),
                            "from_account": r.media_ref.get("from_account"),
                            "fields": r.fields,
                            "outputs": r.media_ref.get("outputs", {}),
                            "referenced_frame": r.referenced_frame,
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


__all__ = ["VideoOnlineModule"]
