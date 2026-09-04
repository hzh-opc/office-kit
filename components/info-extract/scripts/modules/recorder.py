#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 录制核心（上游需求阶段六：直播录制 P0 + 设备摄取 P1）。

复用既有 video_transcript 转录管线 + router.py 路由 + provider_meta 透明回显；
仅新增 live / capture 来源类型，路由层按需载入（D8）。

能力（呼应上游需求文档 + 处理纪要）：
- 直播链接录制：检测直播状态→录制（stream-copy 优先）→检测结束（EOF/平台信号/超时/断流重连）→调用 video_transcript 转写。
- 视频采集设备摄取：ffmpeg 设备后端（avfoundation/dshow/v4l2/DeckLink）录制为文件再转写。
- 机制一（鉴权）：需登录态的直播，--cookies-from-browser 导出 cookie；更稳妥由 browser 技能持登录态取流
  （复制/导出 m3u8/flv 或直接页内录制，登录态由浏览器技能维护）。
- 机制二（录制-转写优先级）：默认 --live-transcribe 边录边转；不可行降级先录后转；解耦（转写失败不影响录制）。
- 增强 A–E：浏览器内直录兜底（A，机制一的增强）、录制健康探针（B）、自动分段（C）、断流重连（D）、统一摄取 manifest（E）。
- 产物契约：默认 D3 不留存录制副本（--keep-live 才保留）；结束写 ingestion_manifest.json。
- 风控：复用方案 B 限速（账号批量）/ 脱敏闸门（上云前）；仅处理用户有权访问内容。

默认本地优先、默认不上云。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.base import ExtractResult, InfoExtractError, Segment, SourceType


# ---------- 工具：定位外部二进制 ----------

def find_ffmpeg() -> Optional[str]:
    """定位 ffmpeg：优先环境变量 FFMPEG_BIN，其次 PATH。"""
    env = os.environ.get("FFMPEG_BIN")
    if env and shutil.which(env):
        return env
    return shutil.which("ffmpeg")


def find_ytdlp() -> Optional[str]:
    return shutil.which("yt-dlp")


class FfmpegRecorderProvider:
    """供 --check 展示 live/capture 录制能力可用性（依赖 ffmpeg）。"""

    name = "ffmpeg-recorder"
    priority = 0

    def available(self) -> bool:
        return find_ffmpeg() is not None

    def meta(self) -> Dict[str, Any]:
        return {"cost": "本地", "ffmpeg": find_ffmpeg() or "缺失"}


# ---------- 录制默认参数 ----------

DEFAULT_SEGMENT_TIME = 300        # 自动分段时长（秒）
DEFAULT_HEALTH_INTERVAL = 15      # 健康探针轮询间隔（秒）
DEFAULT_HEALTH_STALL_LIMIT = 90   # 静默（无新数据）超过该秒数告警
DEFAULT_RECONNECT_LIMIT = 5       # 断流重连次数上限
DEFAULT_RECONNECT_DELAY = 3.0     # 重连退避（秒）


class Recorder:
    """统一录制编排（直播 / 设备共用）。"""

    def __init__(self, ffmpeg_bin: str, out_dir: str, options: Dict[str, Any], capability: str):
        self.ffmpeg = ffmpeg_bin
        self.out_dir = out_dir
        self.options = options or {}
        self.capability = capability  # "live" / "capture"
        self.keep = bool(self.options.get("keep_live", False))
        self.stem = self.options.get("stem") or (f"{capability}_{int(time.time())}")

    # ---- 直播：用 yt-dlp 解析直连流地址（带 cookie/登录态，机制一基础）----
    def resolve_live_url(self, url: str) -> Tuple[str, Dict[str, Any]]:
        """解析直播直连流地址（机制一基础：cookie/登录态）。

        - yt-dlp 可用且解析成功 → 返回直连流地址，method="yt-dlp-resolved"。
        - 解析失败 / yt-dlp 不可用 → 仍返回原 URL，method="direct-fallback"，
          交由 ffmpeg 直连原 URL 录制（机制二解耦：取流失败不阻断录制，录制失败再报需登录态）。
        """
        ytdlp = find_ytdlp()
        cookies = self.options.get("cookies")
        cookies_from_browser = self.options.get("cookies_from_browser")
        if ytdlp is None:
            return url, {"method": "direct-fallback",
                         "note": "yt-dlp 不可用，直接以原 URL 交给 ffmpeg 录制（部分平台可能失败，建议安装 yt-dlp）"}
        cmd = [ytdlp, "-f", "best", "-g", url]
        if cookies:
            cmd += ["--cookies", cookies]
        if cookies_from_browser:
            cmd += ["--cookies-from-browser", cookies_from_browser]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out:
                # -g 可能输出多行（音/视分离流）：优先取首条 http(s) 直连流（直播取视频流最稳）
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                stream = next((l for l in lines if l.startswith(("http://", "https://"))), lines[0])
                return stream, {"method": "yt-dlp-resolved", "url": stream}
        except Exception as e:  # noqa: BLE001
            return url, {"method": "direct-fallback", "note": f"yt-dlp 解析失败：{e}"}
        return url, {"method": "direct-fallback", "note": "yt-dlp 未解析到直连流，回退直连原 URL"}

    # ---- 设备后端映射 ----
    @staticmethod
    def device_backend(device: str) -> str:
        """按设备描述符 / 平台猜测 ffmpeg 设备后端。"""
        d = (device or "").lower()
        if d.startswith("avfoundation:") or d.startswith("qtkit:"):
            return "avfoundation"
        if d.startswith("dshow:") or d.startswith("video=") or d.startswith("audio=") or "directshow" in d:
            return "dshow"
        if d.startswith("v4l2:") or d.startswith("/dev/video"):
            return "v4l2"
        if "decklink" in d:
            return "decklink"
        if sys.platform.startswith("darwin"):
            return "avfoundation"
        if sys.platform.startswith("win"):
            return "dshow"
        if sys.platform.startswith("linux"):
            return "v4l2"
        return "avfoundation"

    def _ffmpeg_input_args(self, *, url: Optional[str] = None, device: Optional[str] = None,
                           backend: Optional[str] = None) -> List[str]:
        if url:
            # 直播/在线流：加重连参数（增强 D 的基础，ffmpeg 原生）
            return ["-reconnect", "1", "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "5", "-i", url]
        backend = backend or self.device_backend(device or "")
        if backend == "dshow":
            dev = device
            if not (dev.lower().startswith("video=") or dev.lower().startswith("audio=")):
                dev = f'video="{device}"'
            return ["-f", "dshow", "-i", dev]
        if backend == "avfoundation":
            return ["-f", "avfoundation", "-i", device]
        if backend == "v4l2":
            return ["-f", "v4l2", "-i", device]
        if backend == "decklink":
            return ["-f", "decklink", "-i", device]
        return ["-f", backend or "avfoundation", "-i", device]

    # ---- 录制主体 ----
    def record(self, *, url: Optional[str] = None, device: Optional[str] = None,
               backend: Optional[str] = None) -> Dict[str, Any]:
        """执行录制（含分段/重连/健康探针），返回 {segments, manifest, method, ...}。

        直播 url 与 设备 device 二选一。
        """
        if not url and not device:
            raise InfoExtractError("录制需提供直播 URL 或设备描述符。", recoverable=False)

        live_transcribe = bool(self.options.get("live_transcribe", False))
        segment = bool(self.options.get("segment", False)) or live_transcribe
        seg_time = int(self.options.get("segment_time", DEFAULT_SEGMENT_TIME))
        timeout = int(self.options.get("live_timeout", 0))  # 0=不超时
        stop_on_end = bool(self.options.get("live_stop_on_end", False))
        reconnect_limit = int(self.options.get("reconnect_limit", DEFAULT_RECONNECT_LIMIT))

        out_dir_p = Path(self.out_dir)
        out_dir_p.mkdir(parents=True, exist_ok=True)

        segments: List[str] = []
        manifest: Dict[str, Any] = {
            "method": f"info-extract:{self.capability}",
            "source": "live" if self.capability == "live" else "device",
            "live_transcribe": live_transcribe,
            "segments": [],
            "keep": self.keep,
        }
        if url:
            manifest["source_url"] = url
        if device:
            manifest["device"] = device

        # 分段：用 segment muxer 输出多段；否则单文件
        if segment:
            seg_pattern = str(out_dir_p / f"{self.stem}_seg_%03d.mp4")
            output_args = ["-f", "segment", "-segment_time", str(seg_time),
                           "-reset_timestamps", "1", "-c", "copy", seg_pattern]
        else:
            single = str(out_dir_p / f"{self.stem}.mp4")
            output_args = ["-c", "copy", single]

        input_args = self._ffmpeg_input_args(url=url, device=device, backend=backend)

        # 边录边转（机制二）的增量结果容器：由 _run_once 内的监控线程填充，随 record() 传出，
        # 避免增量转写结果被丢弃、随后又全量重转（缺陷 #1）。
        transcribed: Dict[str, ExtractResult] = {}

        # 重连循环（增强 D）
        attempt = 0
        last_err: Optional[str] = None
        while attempt <= reconnect_limit:
            attempt += 1
            try:
                self._run_once(input_args, output_args, timeout=timeout, stop_on_end=stop_on_end,
                               segment=segment, seg_pattern=seg_pattern if segment else None,
                               live_transcribe=live_transcribe, manifest=manifest,
                               transcribed=transcribed)
                last_err = None
                break
            except InfoExtractError as e:
                last_err = e.message
                if e.recoverable is False:
                    break
                if attempt > reconnect_limit:
                    break
                time.sleep(DEFAULT_RECONNECT_DELAY * attempt)
                # 重连后续录到新段（segment 模式天然按序号续写；单文件模式则覆盖，需改后缀）
                if not segment:
                    output_args = ["-c", "copy",
                                   str(out_dir_p / f"{self.stem}_re{attempt}.mp4")]

        # 收集实际产生的段文件
        if segment:
            segments = sorted(str(p) for p in out_dir_p.glob(f"{self.stem}_seg_*.mp4"))
            # 也包含重连产生的单文件（非分段模式兜底）
            segments += sorted(str(p) for p in out_dir_p.glob(f"{self.stem}_re*.mp4"))
        else:
            segments = sorted(str(p) for p in out_dir_p.glob(f"{self.stem}*.mp4"))
        segments = [s for s in segments if os.path.getsize(s) > 0]
        manifest["segments"] = segments
        manifest["segment_count"] = len(segments)

        # 注意：D3 不留存（--keep-live 才保留）在「转写完成后」由调用方调用 cleanup() 执行，
        # 避免删除早于转写（录制文件是转写的唯一输入）。

        self._write_manifest(manifest)
        return {"segments": segments, "manifest": manifest, "method": manifest["method"],
                "error": last_err, "transcribed": transcribed,
                "live_transcribe": live_transcribe}

    def cleanup(self, segments: List[str], manifest: Dict[str, Any]) -> None:
        """D3 不留存：转写完成后默认删除录制副本，仅保留转写产物（--keep-live 才保留）。"""
        if self.keep:
            return
        for s in segments:
            try:
                os.remove(s)
            except OSError:
                pass
        manifest["note"] = "录制副本已按 D3 默认删除（--keep-live 可保留）"
        self._write_manifest(manifest)

    def _run_once(self, input_args, output_args, *, timeout, stop_on_end, segment,
                  seg_pattern, live_transcribe, manifest, transcribed):
        """单次 ffmpeg 录制进程；含健康探针（增强 B）与超时看护。"""
        cmd = [self.ffmpeg, "-y", *input_args, *output_args]
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)

        # 健康探针（增强 B）：周期性检查输出文件是否增长，区分卡顿/已结束
        health_interval = DEFAULT_HEALTH_INTERVAL
        stall_limit = DEFAULT_HEALTH_STALL_LIMIT
        last_size = -1
        stall_start = None
        start = time.time()
        health_msg = ""

        # 边录边转（机制二）：监控已完成的段并增量转写
        monitor_thread = None
        stop_flag = {"stop": False}
        if live_transcribe:
            from threading import Thread
            monitor_thread = Thread(target=self._live_transcribe_monitor,
                                    args=(seg_pattern, stop_flag, transcribed, manifest),
                                    daemon=True)
            monitor_thread.start()

        # 静默超阈是否终止（缺陷 #8）：默认终止并交重连循环接管，避免录空文件仍判 success；
        # 用户可经 options["stall_abort"]=False 关闭（仅告警）。
        stall_abort = bool(self.options.get("stall_abort", True))

        try:
            while True:
                # 超时看护（直播默认不超时；设备按 --duration 由调用方控制）
                if timeout and timeout > 0 and (time.time() - start) >= timeout:
                    proc.terminate()
                    break
                if proc.poll() is not None:
                    break  # ffmpeg 自行退出（EOF/结束/错误）
                # 健康探针
                cur = self._current_output_size(segment, seg_pattern)
                if cur is not None:
                    if last_size >= 0 and cur == last_size:
                        if stall_start is None:
                            stall_start = time.time()
                        elif (time.time() - stall_start) >= stall_limit:
                            health_msg = (f"录制静默超 {stall_limit}s（直播可能卡顿/已结束/断流）")
                            if stall_abort:
                                # 终止录制并抛可恢复错误，交由重连循环/上层处理
                                proc.terminate()
                                break
                            # 仅告警不终止（--no-stall-abort）：可能瞬时卡顿
                            manifest.setdefault("warnings", []).append(
                                health_msg + "；未自动终止（已关闭静默终止）")
                            stall_start = None
                    else:
                        stall_start = None
                    last_size = cur
                time.sleep(health_interval)
        finally:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
            if monitor_thread is not None:
                stop_flag["stop"] = True  # 通知监控线程停止增量转写
                try:
                    monitor_thread.join(timeout=5)
                except Exception:  # noqa: BLE001
                    pass

        if health_msg and stall_abort:
            # 静默超阈主动终止：抛可恢复错误（recoverable=True），由重连循环尝试重连
            raise InfoExtractError(
                f"{health_msg}；已主动终止录制（避免录空文件）。",
                recoverable=True,
                hint="直播可能已结束或卡顿；将尝试断流重连（增强 D），若仍无数据则判定源不可用。",
            )

        if proc.returncode not in (0, None) and proc.returncode != -15:  # -15=SIGTERM 主动终止
            stderr_tail = ""
            if proc.stderr:
                try:
                    stderr_tail = "".join(list(proc.stderr)[-20:])
                except Exception:  # noqa: BLE001
                    pass
            raise InfoExtractError(
                f"ffmpeg 录制异常退出（code={proc.returncode}）。{health_msg}".strip(),
                recoverable=True,
                hint="检查直播是否已开始/已结束、设备是否连接/有权限；"
                     "需登录态的直播请用 --cookies-from-browser 或 browser 技能持登录态。\n"
                     f"ffmpeg 输出尾部：{stderr_tail[-500:]}",
            )
        if health_msg and not stall_abort:
            # 录制结束但曾静默（仅告警模式）：记录到 manifest（不静默失败）
            manifest.setdefault("warnings", []).append(health_msg)

    def _current_output_size(self, segment, seg_pattern) -> Optional[int]:
        try:
            if segment:
                files = sorted(Path(seg_pattern).parent.glob(Path(seg_pattern).name.replace("%03d", "*")))
                if not files:
                    return 0
                # 取最新一段的大小（正在写入的那段）
                return os.path.getsize(files[-1])
            # 单文件
            cand = sorted(Path(seg_pattern).parent.glob(self.stem + "*.mp4")) if seg_pattern else []
            if not cand:
                return 0
            return os.path.getsize(cand[-1])
        except Exception:  # noqa: BLE001
            return None

    def _live_transcribe_monitor(self, seg_pattern, stop_flag, transcribed, manifest):
        """边录边转（机制二）：周期性转写已关闭的段，近实时出稿。"""
        from modules.video import VideoModule
        vm = VideoModule()
        seen = set()
        while not stop_flag.get("stop"):
            files = sorted(Path(seg_pattern).parent.glob(Path(seg_pattern).name.replace("%03d", "*")))
            # 跳过正在写入的最后一段（其大小可能仍在增长）
            for f in files[:-1]:
                fp = str(f)
                if fp in seen or not os.path.getsize(fp) > 0:
                    continue
                try:
                    res = vm.run([fp], self.options)
                    if res and res[0].media_ref.get("status") == "ok":
                        transcribed[fp] = res[0]
                        seen.add(fp)
                        manifest.setdefault("live_transcribe_segments", []).append(fp)
                except Exception:  # noqa: BLE001
                    # 转写失败不影响录制（机制二解耦）
                    pass
            time.sleep(DEFAULT_HEALTH_INTERVAL)

    def _write_manifest(self, manifest: Dict[str, Any]) -> str:
        out_dir_p = Path(self.out_dir)
        out_dir_p.mkdir(parents=True, exist_ok=True)
        # 按 stem 命名，避免多源并发/多次录制互相覆盖同一固定名（缺陷 #6）
        path = out_dir_p / f"{self.stem}_manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    # ---- 转录：复用 video_transcript 管线 ----
    def transcribe_segments(self, segments: List[str],
                            already_transcribed: Optional[Dict[str, ExtractResult]] = None) -> Optional[ExtractResult]:
        """录制完成后统一转写（先录后转，或边录边转的最终合并）。

        already_transcribed：边录边转（机制二）期间已增量转写的段（{段路径: ExtractResult}）；
        传入时跳过这些段的重复全量转写，仅补转缺失段（缺陷 #1 修复）。
        返回合并后的完整交付物；无论返回 None 与否，都不在这里写段级中间产物，
        由调用方决定是否对合并稿落盘（缺陷 #2）。
        """
        if not segments:
            return None
        already_transcribed = already_transcribed or {}
        # 惰性加载 video 依赖：仅当存在需要补转的段时才 import（边录边转全命中时零依赖开销）
        vm = None
        results: List[ExtractResult] = []
        for seg in segments:
            if seg in already_transcribed:
                # 复用边录边转已产出的增量结果，避免重复全量转写
                results.append(already_transcribed[seg])
                continue
            if vm is None:
                from modules.video import VideoModule
                vm = VideoModule()
            try:
                res = vm.run([seg], self.options)
                if res and res[0].media_ref.get("status") == "ok":
                    results.append(res[0])
                else:
                    # 单段转写失败（status 非 ok）→ 记 error 段，不阻断整体
                    results.append(self._error_segment_result(seg, "转录未返回有效结果"))
            except Exception as e:  # noqa: BLE001
                # 单段失败不影响整体（增强 C：单段失败不影响整体）
                results.append(self._error_segment_result(seg, str(e)))
        if not results:
            return None
        return self._merge_results(results)

    @staticmethod
    def _error_segment_result(seg: str, err: str) -> ExtractResult:
        return ExtractResult(
            source=SourceType.TRANSCRIPT, text="",
            media_ref={"path": seg, "status": "error", "error": err, "recoverable": True},
        )

    @staticmethod
    def _merge_results(results: List[ExtractResult]) -> ExtractResult:
        """把多段转录合并为单一交付物（按时间顺序拼接）。

        base 优先取第一个成功的段（避免首个 error 段的 media_ref/status 污染合并稿）；
        若全部为 error 段则退回首个，交由调用方按 error 处理。
        """
        base = next((r for r in results if r.media_ref.get("status") == "ok"), results[0])
        full_text_parts = []
        full_segs: List[Segment] = []
        offset = 0.0
        confidences = []
        for r in results:
            full_text_parts.append(r.text or "")
            for s in r.segments:
                full_segs.append(Segment(start=s.start + offset, end=s.end + offset,
                                          text=s.text, words=s.words))
            offset += (r.fields.get("duration_sec") or 0)
            if isinstance(r.confidence, (int, float)):
                confidences.append(r.confidence)
        merged = ExtractResult(
            source=SourceType.TRANSCRIPT,
            text="\n".join(p for p in full_text_parts if p),
            confidence=(sum(confidences) / len(confidences)) if confidences else None,
            fields=dict(base.fields),
            media_ref=dict(base.media_ref),
            referenced_frame=None,
            provider_meta=dict(base.provider_meta or {}),
            segments=full_segs,
        )
        merged.raw_text = merged.text
        return merged

    def write_merged_outputs(self, result: ExtractResult) -> Dict[str, str]:
        """把合并后的完整转录稿落盘（缺陷 #2 修复）。

        按稳定 stem（self.stem，不含段后缀）写双通道 .txt/.srt/.json/.md，
        恢复 D11 双通道契约；返回 {格式: 路径}。
        """
        from modules.audio.output import write_outputs
        # 合并稿以 self.stem 命名（稳定、与段产物区分），避免段级 stem 导致的孤儿命名
        return write_outputs(result, self.out_dir, self.stem)


__all__ = ["find_ffmpeg", "find_ytdlp", "FfmpegRecorderProvider", "Recorder"]
