#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video-to-content-pack · 机械步 CLI（跨平台，纯标准库 + 套件 venv 已有依赖）

定位
----
本工作流的**机械环节**（建目录、来源归一化、记录链索引、帧 OCR、去边、切片、
清单导出、交付物渲染、外发扫描、机械校验）由此 CLI 承担，由工作流契约
`workflow.json` 以 `uses: {"script": "tools/vcp.py", "args": [...]}` 声明、runner
用套件 venv 解释器执行。

为什么不做成 shell 步
--------------------
历史契约用 POSIX shell 实现这些步骤（`mkdir -p` / `cp -n` / `[ -n ]`），而 runner
以 `subprocess(shell=True)` 执行——在 Windows 上是 `cmd.exe`，这些方言全部失败，
与蓝本「跨平台」的宣称冲突。改为 Python 脚本后：跨平台一致、可断点续跑、
退出码语义明确、产物可校验。

解释器与依赖
------------
由 runner 用**套件虚拟环境**（`OFFICE_KIT_ROOT/.venv`，套件唯一真相源）执行，
故可直接使用 `PIL`（去边 / 帧去重）、`imageio_ffmpeg`（内置静态 ffmpeg，
裁切与录制）、`av`。三者均已在套件 venv 内，**不需要** media 隔离环境。
缺失时明确报错并给安装指引，不静默降级。

输出与状态
----------
所有机器可读记录落 `<WORKSPACE>/_work/<节名>/`（工作记录链，蓝本 §0.4）；
人类可读产物落 `<WORKSPACE>/课程交付/` 与 `<WORKSPACE>/按章节/<节名>/`（蓝本 §7）。

退出码：0 成功 / 2 用法错误 / 3 业务失败（含需用户确认的外发阻断）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

VIDEO_EXTS = [".mp4", ".mkv", ".mov", ".m4v", ".webm", ".flv", ".ts", ".avi", ".wmv", ".mpg", ".mpeg"]
TEXT_DELIVER_EXTS = {".md", ".txt", ".csv"}
# 交付文档形态（与蓝本 §0.5 一致）
DELIVERABLE_TYPES = {"讲义", "文档", "参考文档", "教程", "知识点汇总", "文案"}
SOURCE_ENUM = {"file", "online", "live", "live_fallback", "device", "device_fallback"}
GRANULARITY_ENUM = {"none", "transcript", "catalog", "product"}
GRANULARITY_DIR = {"transcript": "小节_按转录", "catalog": "小节_按目录", "product": "小节_按产品"}
ON_OFF = {"on", "off"}

KIT_ROOT = Path(os.environ.get("OFFICE_KIT_ROOT") or Path(__file__).resolve().parents[3])
KIT_PY = Path(os.environ.get("OFFICE_KIT_PY") or sys.executable)

# 帧文件名解析（info-extract 命名约定）
RE_D13_FRAME = re.compile(r"^frame_(\d+)_(\d+)\.png$")            # frame_0006_00.png → 6.00s
RE_KEYFRAME = re.compile(r"^.+_kf_\d+_(\d+)\.png$")               # <stem>_kf_001_600.png → 6.00s
RE_MD_IMG = re.compile(r"!\[[^\]]*\]\(<?([^)>]+)>?\)")


class VcpError(Exception):
    """业务失败（退出码 3）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise VcpError("记录文件损坏，无法解析：%s（%s）" % (path, exc)) from exc


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Ctx:
    """工作区路径集合（蓝本 §7 目录结构的唯一实现处）。"""

    def __init__(self, workspace: str, section: str):
        if not workspace:
            raise VcpError("缺少 --workspace（内容工作区根目录必填）")
        self.ws = Path(workspace).expanduser().resolve()
        self.section = section or "第1节"
        self.work = self.ws / "_work" / self.section
        self.chapter = self.ws / "按章节" / self.section
        self.deliver = self.ws / "课程交付"
        self.sub_transcript = self.deliver / "逐字稿_修正版"
        self.sub_doc = self.deliver / "讲义"
        self.shots = self.deliver / "讲义截图"
        self.shots_bak = self.deliver / "讲义截图_原始备份"
        self.pdf = self.deliver / "PDF"

    def all_dirs(self):
        return [
            self.work,
            self.chapter,
            self.deliver,
            self.sub_transcript,
            self.sub_doc,
            self.shots,
            self.shots_bak,
            self.pdf,
        ] + [self.chapter / d for d in GRANULARITY_DIR.values()]

    # 记录链路径
    def rec(self, name: str) -> Path:
        return self.work / name


def kit_call(args, *, capture=True, check=False):
    """通过 kit.py 调用套件命令（保留外发必扫 DESEN 闸门等统一策略）。

    脚本内**不**直接 subprocess 组件入口——那样会绕过 kit.py 的外发门禁与
    入口校验（历史缺陷：工作流内 extract 未经 DESEN 扫描）。
    """
    cmd = [str(KIT_PY), str(KIT_ROOT / "kit.py")] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace", check=check)


def resolve_ffmpeg(explicit: str = "") -> tuple[str, str]:
    """解析 ffmpeg 可执行文件。返回 (路径, 来源说明)。

    探测顺序：① --ffmpeg-bin/param 显式指定 → ② 套件 venv 的 imageio_ffmpeg
    （内置静态二进制，本机实测可用）→ ③ media 隔离环境（历史兼容，可选）
    → ④ 系统 PATH。全部落空则明确报错 + 三选一指引，不静默失败。
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return str(p), "参数 ffmpeg_bin"
        w = shutil.which(explicit)
        if w:
            return w, "参数 ffmpeg_bin（PATH 命中）"
        raise VcpError("指定的 ffmpeg 不存在：%s" % explicit)

    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe, "套件 venv 的 imageio_ffmpeg"
    except Exception:  # noqa: BLE001
        pass

    for cand in (
        Path.home() / ".workbuddy/binaries/python/envs/media/bin/python",
        Path.home() / ".workbuddy/binaries/python/envs/media/Scripts/python.exe",
    ):
        if not cand.is_file():
            continue
        try:
            out = subprocess.run(
                [str(cand), "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=30,
            )
            exe = (out.stdout or "").strip()
            if exe and Path(exe).is_file():
                return exe, "media 环境的 imageio_ffmpeg"
        except Exception:  # noqa: BLE001
            continue

    w = shutil.which("ffmpeg")
    if w:
        return w, "系统 PATH 的 ffmpeg"

    raise VcpError(
        "未找到 ffmpeg。三选一：\n"
        "  ① 指定二进制：--param ffmpeg_bin=/path/to/ffmpeg\n"
        "  ② 依赖套件 venv 内置 ffmpeg（重装依赖：cd %s && ./bootstrap.sh）\n"
        "  ③ 安装到系统 PATH（macOS: brew install ffmpeg）" % KIT_ROOT
    )


# ---------------------------------------------------------------------------
# 子命令：precheck
# ---------------------------------------------------------------------------

def cmd_precheck(a) -> int:
    errors, warns = [], []

    if not a.workspace:
        errors.append("--workspace 必填（内容工作区根目录）")
    if a.source not in SOURCE_ENUM:
        errors.append("source=%s 非法；可选：%s" % (a.source, " | ".join(sorted(SOURCE_ENUM))))
    if a.granularity not in GRANULARITY_ENUM:
        errors.append("granularity=%s 非法；可选：%s" % (a.granularity, " | ".join(sorted(GRANULARITY_ENUM))))
    for key, val in (("copywriting", a.copywriting), ("digest", a.digest),
                     ("desen_gate", a.desen_gate)):
        if val not in ON_OFF:
            errors.append("%s=%s 非法；可选 on | off" % (key, val))
    if a.deliverable_render not in ("off", "pdf"):
        errors.append("deliverable_render=%s 非法；可选 off | pdf" % a.deliverable_render)
    if a.cloud_upload not in ("off", "tencent"):
        errors.append("cloud_upload=%s 非法；可选 off | tencent" % a.cloud_upload)

    types = [t.strip() for t in (a.deliverable_types or "").split(",") if t.strip()]
    if not types:
        errors.append("deliverable_types 不能为空（可选：%s）" % " / ".join(sorted(DELIVERABLE_TYPES)))
    for t in types:
        if t not in DELIVERABLE_TYPES:
            errors.append("deliverable_types 含未知形态 `%s`；可选：%s"
                          % (t, " / ".join(sorted(DELIVERABLE_TYPES))))

    if a.source in SOURCE_ENUM and not (a.source_uri or "").strip():
        hint = {
            "file": "本地视频文件路径",
            "online": "自媒体/在线视频 URL",
            "live": "直播 URL",
            "live_fallback": "直播 URL",
            "device": "设备描述符，如 avfoundation:1:0（macOS）/ USB Video（Windows）/ /dev/video0（Linux）",
            "device_fallback": "设备描述符，同 device",
        }.get(a.source, "来源地址")
        errors.append("source=%s 时必须提供 source_uri（%s）" % (a.source, hint))
    if a.source == "file" and a.source_uri:
        p = Path(a.source_uri).expanduser()
        if not p.is_file():
            errors.append("source=file 但文件不存在：%s" % p)

    if a.whisper_model and a.whisper_model not in (
            "tiny", "base", "small", "medium", "large-v3", "turbo"):
        errors.append("whisper_model=%s 非法；可选 tiny/base/small/medium/large-v3/turbo（留空=组件默认 small）"
                      % a.whisper_model)

    # ffmpeg：仅在确需时才硬要求（录制降级 / 切片）
    need_ffmpeg = a.source in ("live_fallback", "device_fallback") or a.granularity != "none"
    ffmpeg, ff_src = "", ""
    if need_ffmpeg or a.ffmpeg_bin:
        try:
            ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)
        except VcpError as exc:
            if need_ffmpeg:
                errors.append(str(exc))
            else:
                warns.append(str(exc))
    else:
        try:
            ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)
        except VcpError:
            warns.append("未解析到 ffmpeg（当前参数组合用不到；如需录制降级/切片请先解决）")

    # 运行解释器自检：脚本步由 runner 用套件 venv 解释器执行，这里校验「当前解释器」
    # 是否真的具备本工作流依赖（比检查固定 .venv 目录更准确——套件允许 venv 位于
    # 部署副本 ~/office-kit/.venv，而开发副本通常不自建 .venv）。
    if not (KIT_ROOT / "kit.py").is_file():
        errors.append("kit.py 未找到（OFFICE_KIT_ROOT=%s 是否正确？）" % KIT_ROOT)
    missing_mods = []
    for mod, why in (("PIL", "截图去边 / 帧去重"), ("imageio_ffmpeg", "内置静态 ffmpeg（录制降级与切片）")):
        try:
            __import__(mod)
        except ImportError:
            missing_mods.append("%s（%s）" % (mod, why))
    if missing_mods:
        errors.append(
            "当前解释器缺少依赖：%s\n     解释器=%s\n     → 脚本步须由套件 venv 解释器执行"
            "（如 %s/.venv/bin/python）；如确为套件 venv 仍缺，请运行 ./bootstrap.sh 补齐"
            % ("；".join(missing_mods), sys.executable, KIT_ROOT))
    warns.append("运行解释器：%s" % sys.executable)

    ctx = Ctx(a.workspace or ".", a.section)
    ctx.work.mkdir(parents=True, exist_ok=True)
    ctx.rec("run_context.json")  # 触发父目录创建

    ctx_obj = {
        "workflow": "video-to-content-pack",
        "generated_at": now_iso(),
        "workspace": str(ctx.ws),
        "section": ctx.section,
        "params": {
            "source": a.source, "source_uri": a.source_uri, "granularity": a.granularity,
            "copywriting": a.copywriting, "digest": a.digest,
            "deliverable_types": types, "deliverable_render": a.deliverable_render,
            "cloud_upload": a.cloud_upload, "desen_gate": a.desen_gate,
            "whisper_model": a.whisper_model or "small(组件默认)", "device_duration": a.device_duration,
        },
        "env": {
            "office_kit_root": str(KIT_ROOT),
            "kit_python": str(KIT_PY),
            "ffmpeg": ffmpeg,
            "ffmpeg_source": ff_src,
        },
    }
    write_json(ctx.rec("run_context.json"), ctx_obj)

    for w in warns:
        log("  ⚠ %s" % w)
    if errors:
        log("✗ 入参/环境校验未通过：")
        for e in errors:
            log("  · %s" % e)
        return 3
    log("  ✓ 入参与环境校验通过（ffmpeg=%s；%s）" % (ffmpeg or "未解析（当前用不到）", ff_src or "—"))
    log("  ✓ 运行上下文已落盘：%s" % ctx.rec("run_context.json"))
    return 0


# ---------------------------------------------------------------------------
# 子命令：mkdirs
# ---------------------------------------------------------------------------

def cmd_mkdirs(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    for d in ctx.all_dirs():
        d.mkdir(parents=True, exist_ok=True)
    log("  ✓ 目录骨架就绪（%d 个）：%s" % (len(ctx.all_dirs()), ctx.ws))
    for d in ctx.all_dirs():
        log("      %s" % d.relative_to(ctx.ws))
    return 0


# ---------------------------------------------------------------------------
# 子命令：ingest（本地文件归一化）
# ---------------------------------------------------------------------------

def cmd_ingest(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    src = Path(a.source_uri).expanduser().resolve()
    if not src.is_file():
        raise VcpError("来源文件不存在：%s" % src)
    ext = src.suffix.lower() or ".mp4"
    dst = ctx.chapter / ("%s%s" % (ctx.section, ext))
    ctx.chapter.mkdir(parents=True, exist_ok=True)
    if src == dst:
        log("  ✓ 来源已在归一化目录，无需复制：%s" % dst)
        return 0

    def _same(p: Path) -> bool:
        try:
            return p.stat().st_size == src.stat().st_size
        except OSError:
            return False

    if dst.exists() and not _same(dst):
        # 幂等重跑：内容不同才覆盖（避免重复消耗大文件 IO）
        shutil.copy2(src, dst)
        log("  ✓ 已覆盖归一化：%s" % dst)
    elif not dst.exists():
        shutil.copy2(src, dst)
        log("  ✓ 已归一化：%s → %s" % (src, dst))
    else:
        log("  ✓ 归一化文件已存在且大小一致，跳过复制：%s" % dst)
    return 0


# ---------------------------------------------------------------------------
# 子命令：record-live / record-device（降级路径：先录制为本地文件）
# ---------------------------------------------------------------------------

def _record(ctx: Ctx, ffmpeg: str, extra_in: list, out_name: str, duration: int, *, copy: bool) -> int:
    out = ctx.chapter / out_name
    ctx.chapter.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-nostdin"] + extra_in
    # 直播流是无损转封装（-c copy）；采集设备是原始信号，必须编码
    cmd += ["-c", "copy"] if copy else [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
    ]
    if duration and duration > 0:
        cmd += ["-t", str(int(duration))]
    cmd += [str(out)]
    log("  ▶ %s" % " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc != 0 or not out.is_file():
        raise VcpError(
            "录制失败（ffmpeg rc=%s）。常见原因：URL/设备不可达、需登录态（请改走原生路径 "
            "`kit extract <URL> --live --cookies-from-browser chrome`）、或设备被占用。"
            "产物未生成：%s" % (rc, out))
    log("  ✓ 已录制：%s（%.1f MB）" % (out, out.stat().st_size / 1024 / 1024))
    return 0


def cmd_record_live(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    ffmpeg, src = resolve_ffmpeg(a.ffmpeg_bin)
    log("  · ffmpeg=%s（%s）" % (ffmpeg, src))
    return _record(ctx, ffmpeg, ["-i", a.source_uri], "%s.mkv" % ctx.section, a.device_duration, copy=True)


def cmd_record_device(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    ffmpeg, src = resolve_ffmpeg(a.ffmpeg_bin)
    dev = a.source_uri
    # 设备描述符可带后端前缀（与 info-extract 约定一致）：avfoundation:1:0 / dshow:USB Video / v4l2:/dev/video0
    backend, sep, target = dev.partition(":")
    if not sep or backend not in ("avfoundation", "dshow", "v4l2", "decklink"):
        if sys.platform == "darwin":
            backend, target = "avfoundation", dev
        elif sys.platform.startswith("win"):
            backend, target = "dshow", dev
        else:
            backend, target = "v4l2", dev
    if backend == "dshow":
        extra = ["-f", "dshow", "-i", "video=%s" % target]
    elif backend == "decklink":
        extra = ["-f", "decklink", "-i", target]
    else:
        extra = ["-f", backend, "-i", target]
    log("  · 设备后端=%s，目标=%s" % (backend, target))
    return _record(ctx, ffmpeg, extra, "%s.mkv" % ctx.section, a.device_duration, copy=False)


# ---------------------------------------------------------------------------
# 子命令：transcribe（经 kit.py 调用组件，保留统一外发闸门）
# ---------------------------------------------------------------------------

def _find_normalized(ctx: Ctx) -> Path:
    """定位本节的归一化源视频（§1.1 各来源归一后的落点）。"""
    cands = [p for p in sorted(ctx.chapter.glob("%s.*" % ctx.section)) if p.suffix.lower() in VIDEO_EXTS]
    if not cands:
        cands = [p for p in sorted(ctx.chapter.glob("*")) if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not cands:
        raise VcpError(
            "未找到归一化源视频：%s/%s.<视频扩展名>。请先确认摄取步成功"
            "（source=live/device 原生路径由组件边录边转，无需本步）。" % (ctx.chapter, ctx.section))
    prio = {e: i for i, e in enumerate(VIDEO_EXTS)}
    cands.sort(key=lambda p: prio.get(p.suffix.lower(), 99))
    return cands[0]


def cmd_transcribe(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    src_video = _find_normalized(ctx)
    args = ["extract", str(src_video), "--out", str(ctx.work)]
    if a.whisper_model:
        args += ["--model", a.whisper_model]
    log("  ▶ kit %s" % " ".join(args))
    proc = kit_call(args, capture=False)
    if proc.returncode != 0:
        raise VcpError(
            "转录失败（kit extract rc=%s）。若为模型下载失败：受限网络可用本地缓存并设 "
            "HF_HUB_OFFLINE=1；或改用 whisper.cpp（WHISPER_CPP_BIN/WHISPER_CPP_MODEL）。" % proc.returncode)
    # 产物即时报验：不静默成功
    n_arch = len(list((ctx.work / "存档").glob("*.json"))) if (ctx.work / "存档").is_dir() else 0
    if not n_arch:
        raise VcpError("转录结束但未发现结构化产物（%s/存档/*.json），请检查上方日志。" % ctx.work)
    log("  ✓ 转录产物已落盘（存档/ 下 %d 个 json）" % n_arch)
    return 0


# ---------------------------------------------------------------------------
# 子命令：index-records（记录链索引：ingestion_manifest / transcript_meta / frame_index）
# ---------------------------------------------------------------------------

def _img_signature(path: Path, size: int = 16):
    """帧指纹：16×16 灰度缩略（用于近似重复判定）。

    为何不用 aHash/dHash：课程/直播画面多为「大面积纯底 + 少量元素」的幻灯片，
    均值哈希会因纯底占绝对多数而把不同帧哈希成同一个值（实测：两张内容不同的
    幻灯片 aHash 距离 = 0）。改为**逐像素平均绝对差（MAD）**，在同类画面上区分度
    明显更好（实测：完全相同帧 MAD=0.0，内容不同帧 MAD≥3.8）。
    """
    from PIL import Image  # type: ignore
    return list(Image.open(path).convert("L").resize((size, size)).getdata())


def _mad(a, b) -> float:
    """两个指纹的平均绝对差（0=完全相同）。"""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _dedup(frames: list, threshold: float) -> int:
    """原地标记重复帧（dup_of + dup_mad）。返回去重后保留数。

    判据保守：仅把「视觉几乎完全相同」的帧判重，保证选帧时仍有足够候选
    （相似度只是筛子不是裁判——配图规范 §六 通用铁律）。
    """
    kept, kept_sig = [], []
    for f in frames:
        sig = f.get("_sig")
        best, best_mad = None, None
        for k, ksig in zip(kept, kept_sig):
            d = _mad(ksig, sig)
            if best_mad is None or d < best_mad:
                best, best_mad = k, d
        if best is not None and best_mad is not None and best_mad <= threshold:
            f["selected"] = False
            f["dup_of"] = best["frame_id"]
            f["dup_mad"] = round(best_mad, 2)
        else:
            f["selected"] = True
            kept.append(f)
            kept_sig.append(sig)
    return len(kept)


def cmd_index_records(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    rc = read_json(ctx.rec("run_context.json"), {}) or {}
    params = rc.get("params", {})

    arch_dir = ctx.work / "存档"
    contracts = []
    for p in sorted(arch_dir.glob("*.json")) if arch_dir.is_dir() else []:
        if p.name.endswith(".correction.json"):
            continue
        try:
            contracts.append((p.stem, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            continue
    if not contracts:
        raise VcpError("未发现转录契约（%s/*.json）。请先完成 transcribe 或原生摄取。" % arch_dir)

    items, all_frames = [], []
    for stem, c in contracts:
        fields = c.get("fields") or {}
        dur = fields.get("duration_sec") or 0
        segs = c.get("segments") or []
        deliver = ctx.work / "交付"
        item = {
            "stem": stem,
            "duration_sec": round(float(dur), 2) if dur else 0.0,
            "language": fields.get("detected_language") or fields.get("language") or "",
            "segments_count": len(segs),
            "confidence": c.get("confidence"),
            "provider": (c.get("provider_meta") or {}).get("provider", ""),
            "srt": str(arch_dir / ("%s.srt" % stem)) if (arch_dir / ("%s.srt" % stem)).is_file() else "",
            "json": str(arch_dir / ("%s.json" % stem)),
            "txt": str(deliver / ("%s.txt" % stem)) if (deliver / ("%s.txt" % stem)).is_file()
                   else (str(deliver / ("%s.raw.txt" % stem)) if (deliver / ("%s.raw.txt" % stem)).is_file() else ""),
            "md": str(deliver / ("%s.md" % stem)) if (deliver / ("%s.md" % stem)).is_file() else "",
            "correction_md": str(arch_dir / ("%s.correction.md" % stem))
                             if (arch_dir / ("%s.correction.md" % stem)).is_file() else "",
            "degraded_no_correction": (deliver / ("%s.raw.txt" % stem)).is_file(),
        }
        # 帧目录（D13 讲解段帧免费产出；--vision 时另有 keyframes）
        fr_dirs = [d for d in (ctx.work / ("%s_frames" % stem), ctx.work / ("%s_keyframes" % stem)) if d.is_dir()]
        item["frame_dirs"] = [str(d) for d in fr_dirs]
        items.append(item)

        # 段文本（供帧定位说明）：segment_start/end → text
        seg_text = {}
        for s in segs:
            try:
                seg_text[(round(float(s["start"]), 2), round(float(s["end"]), 2))] = (s.get("text") or "").strip()
            except Exception:  # noqa: BLE001
                continue

        for d in fr_dirs:
            is_kf = d.name.endswith("_keyframes")
            for png in sorted(d.glob("*.png")):
                m = RE_KEYFRAME.match(png.name) if is_kf else RE_D13_FRAME.match(png.name)
                ts = None
                if m:
                    # D13：frame_<整秒:04d>_<百分秒:02d>.png → 6 + 0.00；关键帧：..._kf_<序号>_<ts*100>.png
                    ts = (int(m.group(1)) / 100.0) if is_kf else (int(m.group(1)) + int(m.group(2)) / 100.0)
                all_frames.append({
                    "frame_id": "%s/%s" % (d.name, png.name),
                    "path": str(png),
                    "kind": "keyframe" if is_kf else "d13",
                    "stem": stem,
                    "timestamp_sec": ts,
                    "size_bytes": png.stat().st_size,
                    "segment_text": "",
                    "ocr_text": "",
                    "ocr_head": "",
                    "selected": True,
                    "dup_of": None,
                    "_hash": None,
                })
        # 回填 D13 帧所在段文本
        for fr in all_frames:
            if fr["kind"] != "d13" or fr["stem"] != stem:
                continue
            rf = (c.get("referenced_frame") or {}).get("frames") or []
            for r in rf:
                try:
                    if abs(float(r.get("timestamp", -1)) - (fr["timestamp_sec"] or -1)) < 0.01:
                        fr["segment_text"] = (r.get("segment_text") or "").strip()
                        fr["ocr_text"] = r.get("ocr_on_frame") or ""
                        break
                except Exception:  # noqa: BLE001
                    continue

    # 帧去重（16×16 灰度 MAD；与组件关键帧的 phash 去重互补，覆盖 D13 段帧）
    warn_img = ""
    try:
        from PIL import Image  # noqa: F401  # type: ignore
        for f in all_frames:
            try:
                f["_sig"] = _img_signature(Path(f["path"]))
            except Exception:  # noqa: BLE001
                f["_sig"] = None
        kept = _dedup(all_frames, a.dup_mad)
    except ImportError:
        kept = len(all_frames)
        warn_img = "（未安装 Pillow，跳过帧去重；请确认套件 venv 完整）"

    for f in all_frames:
        f.pop("_sig", None)
        if f["ocr_text"]:
            f["ocr_head"] = f["ocr_text"][:60]

    # 归一化源文件
    src_file = ""
    try:
        src_file = str(_find_normalized(ctx))
    except VcpError:
        for p in sorted(ctx.work.glob("*")):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                src_file = str(p)
                break

    primary = items[0] if items else {}
    write_json(ctx.rec("transcript_meta.json"), {
        "section": ctx.section,
        "generated_at": now_iso(),
        "primary_stem": primary.get("stem"),
        "duration_sec": primary.get("duration_sec"),
        "items": items,
        "note": "本文件是转录产物的轻量索引（原 transcript_meta.json 曾指向不存在的产物，2026-09-22 起改为"
                "由 存档/<stem>.json 抽取；时间戳与段落的唯一真源仍是 存档/<stem>.srt 与 存档/<stem>.json）。",
    })
    write_json(ctx.rec("ingestion_manifest.json"), {
        "section": ctx.section,
        "source_type": params.get("source", ""),
        "source_uri": params.get("source_uri", ""),
        "method": {
            "file": "本地文件归一化（--param source=file）",
            "online": "info-extract 在线下载+转录（yt-dlp）",
            "live": "info-extract 直播原生摄取（边录边转）",
            "live_fallback": "media/套件 ffmpeg 先录制为本地回放，再转录",
            "device": "info-extract 采集设备原生摄取（边采边转）",
            "device_fallback": "套件 ffmpeg 设备后端先采集为本地文件，再转录",
        }.get(params.get("source", ""), "未知（请人工补记）"),
        "normalized_file": src_file,
        "duration_sec": primary.get("duration_sec"),
        "fetched_at": now_iso(),
        "compliance": "仅处理用户有权访问的内容；批量抓取遵守平台 ToS 并默认限速；"
                      "直播/设备录制产物留存于本工作区，留存与销毁由用户负责。",
    })
    write_json(ctx.rec("frame_index.json"), {
        "section": ctx.section,
        "generated_at": now_iso(),
        "source": "info-extract D13 讲解段帧（转录时免费产出）+ --vision 关键帧（如已启用）",
        "dedup": "16×16 灰度平均绝对差（MAD ≤ %.1f 判重；组件关键帧另有 phash 去重，两者互补）" % a.dup_mad
                 + "——判据保守，保证选帧时仍有足够候选",
        "total": len(all_frames),
        "selected": sum(1 for f in all_frames if f["selected"]),
        "frames": all_frames,
    })

    log("  ✓ 转录契约 %d 份；帧 %d 张（去重后保留 %d 张）%s"
        % (len(contracts), len(all_frames), kept, warn_img))
    log("  ✓ 已落盘：transcript_meta.json / ingestion_manifest.json / frame_index.json")
    if not all_frames:
        log("  ⚠ 未发现任何帧：该视频可能无「讲解画面」指代（D13 未命中）。"
            "如需更多画面素材，可对源视频显式启用画面解读：kit extract <视频> --vision --out %s" % ctx.work)
    return 0


# ---------------------------------------------------------------------------
# 子命令：digest（summarize 接入：速览/关键词，供 authoring 写「本节速览」）
# ---------------------------------------------------------------------------

def cmd_digest(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json")) or {}
    items = meta.get("items") or []
    if not items:
        raise VcpError("缺少 transcript_meta.json（请先执行 index-records）")

    out = {"section": ctx.section, "generated_at": now_iso(), "provider": "summarize（本地抽取式，零上云）",
           "items": []}
    for it in items:
        txt = it.get("txt") or ""
        if not txt or not Path(txt).is_file():
            out["items"].append({"stem": it.get("stem"), "skipped": "无可用文本（交付区 .txt 缺失）"})
            continue
        tmp = ctx.work / ("_digest_%s.json" % it["stem"])
        proc = kit_call(["summarize", txt, "--keywords", str(a.keywords),
                         "--format", "json", "--out", str(tmp)])
        data = read_json(tmp, None) if tmp.is_file() else None
        if proc.returncode != 0 or not data:
            out["items"].append({"stem": it.get("stem"), "skipped": "summarize 失败（rc=%s）" % proc.returncode})
            continue
        out["items"].append({
            "stem": it["stem"],
            "tldr": data.get("tldr") or "",
            "summary": data.get("summary") or "",
            "keywords": data.get("keywords") or [],
            "keyword_weights": data.get("keyword_weights") or {},
            "sentences": [s.get("text") for s in (data.get("chosen_sentences") or [])],
        })
        try:
            tmp.unlink()
        except OSError:
            pass

    write_json(ctx.rec("digest.json"), out)
    ok = sum(1 for i in out["items"] if not i.get("skipped"))
    log("  ✓ 摘要/关键词已落盘：digest.json（成功 %d/%d 节）" % (ok, len(out["items"])))
    return 0


# ---------------------------------------------------------------------------
# 子命令：frames-ocr（逐帧独立子进程 + 断点续跑，防内存累积 OOM）
# ---------------------------------------------------------------------------

def cmd_frames_ocr(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    idx = read_json(ctx.rec("frame_index.json"))
    if idx is None:
        raise VcpError("缺少 frame_index.json（请先执行 index-records）")
    frames = idx.get("frames") or []
    selected = [f for f in frames if f.get("selected")]
    if not selected:
        log("  · 无可 OCR 的帧（frame_index 为空或无选中帧），跳过")
        write_json(ctx.rec("ocr_review.json"), {"section": ctx.section, "generated_at": now_iso(),
                                                "items": [], "note": "无选中帧"})
        return 0

    ocr_root = ctx.work / "frames_ocr"
    ocr_root.mkdir(parents=True, exist_ok=True)
    review, done, cached, failed = [], 0, 0, 0
    for f in selected:
        fid = f["frame_id"].split("/")[-1].rsplit(".", 1)[0]
        out_dir = ocr_root / fid
        arch = out_dir / "存档" / ("%s.json" % fid)
        if arch.is_file():
            cached += 1
        else:
            # subprocess-per-image：每图独立进程，避免单进程反复初始化推理引擎导致 OOM（配图规范 §六-8）
            proc = kit_call(["extract", f["path"], "--type", "ocr", "--out", str(out_dir)])
            if proc.returncode != 0 or not arch.is_file():
                failed += 1
                review.append({"frame_id": f["frame_id"], "hit": False, "ocr_text": "",
                               "score": None, "error": "OCR 失败（rc=%s）" % proc.returncode})
                continue
            done += 1
        data = read_json(arch, {}) or {}
        text = (data.get("text") or data.get("raw_text") or "").strip()
        fields = data.get("fields") or {}
        score = data.get("confidence", fields.get("avg_confidence"))
        review.append({"frame_id": f["frame_id"], "hit": bool(text), "ocr_text": text,
                       "ocr_head": text[:60], "score": score, "error": ""})
        f["ocr_text"] = text
        f["ocr_head"] = text[:60]

    write_json(ctx.rec("ocr_review.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "note": "hit 仅代表「该帧 OCR 有文本输出」；是否命中预期锚点属语义判断，"
                "在 frame_pick（选帧归位）步由 Agent/用户复核。",
        "items": review, "stats": {"total": len(selected), "new": done, "cached": cached, "failed": failed},
    })
    write_json(ctx.rec("frame_index.json"), idx)  # 回写 ocr_text / ocr_head
    log("  ✓ OCR 复核完成：共 %d 帧（新算 %d / 命中缓存 %d / 失败 %d）→ ocr_review.json"
        % (len(selected), done, cached, failed))
    if failed:
        log("  ⚠ %d 帧 OCR 失败，已在 ocr_review.json 标记 error，未静默放过" % failed)
    return 0


# ---------------------------------------------------------------------------
# 子命令：crop（截图去边，保守算法）
# ---------------------------------------------------------------------------

def _crop_one(path: Path, pad: int, keep_min: float, max_side: int):
    """估算内容边界并保守裁剪；返回 (裁剪框, 保留面积比) 或 None（无需/不宜裁剪）。"""
    from PIL import Image, ImageChops  # type: ignore
    im = Image.open(path).convert("RGB")
    w, h = im.size
    gray = im.convert("L")

    # 以四边内侧 3% 采样估背景灰度；仅当边缘为「近纯色暗底」才裁
    px = gray.load()
    samples = []
    for x in range(0, w, max(1, w // 200)):
        samples += [px[x, 0], px[x, 1], px[x, h - 2]]
    for y in range(0, h, max(1, h // 200)):
        samples += [px[0, y], px[1, y], px[w - 2, y]]
    if not samples:
        return None
    bg = sum(samples) / len(samples)
    if bg > 60:  # 边缘不是暗底 → 没有可裁的黑边
        return None
    # 标准差护栏：纯色带才裁，避免误裁暗调画面
    var = sum((s - bg) ** 2 for s in samples) / len(samples)
    if var > 400:  # std > 20
        return None

    mask = gray.point(lambda v: 255 if v > max(40, bg + 18) else 0)
    bbox = mask.getbbox()
    if not bbox:
        return None
    l, t, r, b = bbox
    l, t = max(0, l - pad), max(0, t - pad)
    r, b = min(w, r + pad), min(h, b + pad)
    box_w, box_h = r - l, b - t
    if box_w <= 0 or box_h <= 0:
        return None
    # 保守护栏：保留面积 ≥ keep_min；单边裁掉不超过 max_side px
    if (box_w * box_h) / float(w * h) < keep_min:
        return None
    if l > max_side or t > max_side or (w - r) > max_side or (h - b) > max_side:
        return None
    if (l, t, r, b) == (0, 0, w, h):
        return None
    im.crop((l, t, r, b)).save(path)
    return (l, t, r, b), round((box_w * box_h) / float(w * h), 3)


def cmd_crop(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if not ctx.shots.is_dir():
        raise VcpError("截图目录不存在：%s（请先完成 frame_pick 的命名归位）" % ctx.shots)
    try:
        import PIL  # noqa: F401  # type: ignore
    except ImportError as exc:
        raise VcpError("缺少 Pillow，无法去边。请补依赖：cd %s && ./bootstrap.sh（%s）" % (KIT_ROOT, exc)) from exc

    ctx.shots_bak.mkdir(parents=True, exist_ok=True)
    manifest, cropped, skipped = [], 0, 0
    for src in sorted(ctx.shots.iterdir()):
        if not src.is_file() or src.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        bak = ctx.shots_bak / src.name
        if not bak.exists():          # 先备份原图（幂等：已备份不覆盖）
            shutil.copy2(src, bak)
        try:
            res = _crop_one(src, a.pad, a.keep_min, a.max_side)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"file": src.name, "cropped": False, "error": str(exc), "keep_ratio": None})
            skipped += 1
            continue
        if res is None:
            manifest.append({"file": src.name, "cropped": False, "box": None, "keep_ratio": 1.0})
            skipped += 1
        else:
            box, ratio = res
            manifest.append({"file": src.name, "cropped": True, "box": list(box), "keep_ratio": ratio})
            cropped += 1

    write_json(ctx.rec("crop_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "algorithm": "边缘背景灰度估计 → 前景掩码 → 内容边界+pad；护栏：保留面积 ≥%.2f、单边裁掉 ≤%dpx、"
                     "边缘须为近纯色暗底（std ≤20）" % (a.keep_min, a.max_side),
        "backup_dir": str(ctx.shots_bak),
        "items": manifest,
        "stats": {"total": len(manifest), "cropped": cropped, "unchanged": skipped},
    })
    log("  ✓ 去边完成：共 %d 张（实际裁剪 %d / 保持原样 %d）→ crop_manifest.json" % (len(manifest), cropped, skipped))
    log("      原图备份：%s" % ctx.shots_bak)
    return 0


# ---------------------------------------------------------------------------
# 子命令：cut（按 cut_plan.json 执行切片；增量重切）
# ---------------------------------------------------------------------------

def cmd_cut(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    plan = read_json(ctx.rec("cut_plan.json"))
    if not plan:
        raise VcpError("缺少 cut_plan.json（裁切计划是唯一真源，请先完成 cut_plan 步）")
    granularity = plan.get("granularity") or a.granularity
    out_dir = ctx.chapter / GRANULARITY_DIR.get(granularity, "小节_按转录")
    out_dir.mkdir(parents=True, exist_ok=True)

    src = Path(plan.get("source_video") or "").expanduser()
    if not src.is_file():
        try:
            src = _find_normalized(ctx)
        except VcpError as exc:
            raise VcpError("源视频不可用：%s（cut_plan.source_video=%s）"
                           % (exc, plan.get("source_video"))) from exc
    src_sha = sha256_file(src)
    ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)

    prev = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    prev_map = {i.get("filename"): i for i in (prev.get("items") or [])}

    items, cut, reused = [], 0, 0
    for seg in plan.get("segments") or []:
        fn = seg.get("filename")
        if not fn:
            raise VcpError("cut_plan 段缺少 filename 字段（第 %s 段）" % seg.get("idx"))
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        if end <= start:
            raise VcpError("cut_plan 段时间区间非法：%s（%.2f→%.2f）" % (fn, start, end))
        dst = out_dir / fn
        old = prev_map.get(fn)
        same = (old and old.get("src_sha256") == src_sha
                and abs(float(old.get("start", -1)) - start) < 0.01
                and abs(float(old.get("end", -1)) - end) < 0.01
                and dst.is_file())
        if same:
            reused += 1
        else:
            # 临时文件名保留真实扩展名（ffmpeg 靠扩展名推断容器格式，`.mp4.part` 会直接失败）
            tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
            cmd = [ffmpeg, "-y", "-nostdin", "-ss", "%.3f" % start, "-to", "%.3f" % end,
                   "-i", str(src), "-c", "copy", "-avoid_negative_ts", "make_zero", str(tmp)]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            rc = proc.returncode
            if rc != 0 or not tmp.is_file():
                # stream-copy 失败（关键帧/容器不兼容等）→ 回退重编码，保证段可用（不静默）
                cmd2 = [ffmpeg, "-y", "-nostdin", "-ss", "%.3f" % start, "-to", "%.3f" % end,
                        "-i", str(src), "-c:v", "libx264", "-crf", "20", "-c:a", "aac", str(tmp)]
                proc2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8", errors="replace")
                rc2 = proc2.returncode
                if rc2 != 0 or not tmp.is_file():
                    tail = "\n".join((proc.stderr or "").strip().splitlines()[-4:]
                                     + (proc2.stderr or "").strip().splitlines()[-4:])
                    raise VcpError("切片失败：%s（stream-copy rc=%s / 重编码 rc=%s）\n%s"
                                   % (fn, rc, rc2, tail))
            tmp.replace(dst)
            cut += 1
        items.append({
            "filename": fn, "dest_dir": str(out_dir), "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3),
            "transcript_title": seg.get("transcript_title") or "",
            "product_name": seg.get("product_name") or "",
            "basis": seg.get("basis") or granularity,
            "src_video": str(src), "src_sha256": src_sha,
            "size_bytes": dst.stat().st_size if dst.is_file() else 0,
        })

    write_json(ctx.rec("cut_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(), "granularity": granularity,
        "output_dir": str(out_dir), "src_video_sha256": src_sha,
        "ffmpeg": ffmpeg, "ffmpeg_source": ff_src,
        "stats": {"total": len(items), "cut": cut, "reused": reused},
        "items": items,
    })
    log("  ✓ 切片完成：共 %d 段（新切 %d / 复用 %d）→ %s" % (len(items), cut, reused, out_dir))
    return 0


# ---------------------------------------------------------------------------
# 子命令：export（由记录派生清单/索引/文案汇总/交付总索引）
# ---------------------------------------------------------------------------

def cmd_export(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json"), {}) or {}
    cm = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    catalog = read_json(ctx.rec("catalog.json"), {}) or {}
    pcatalog = read_json(ctx.rec("product_catalog.json"), {}) or {}
    cw = read_json(ctx.rec("copywriting.json"), {}) or {}
    written = []

    # 交付清单（始终产出）：逐字稿 + 交付文档 + 截图
    transcript_docs = sorted(p for p in ctx.sub_transcript.glob("*.md")) if ctx.sub_transcript.is_dir() else []
    deliver_docs = sorted(p for p in ctx.sub_doc.glob("*.md")) if ctx.sub_doc.is_dir() else []
    shots = sorted(p for p in ctx.shots.iterdir()
                   if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")) if ctx.shots.is_dir() else []

    lines = ["# %s 交付总索引" % ctx.section, "",
             "> 由工作流 `video-to-content-pack` 于 %s 自动生成（源头记录见 `_work/%s/`）。" % (now_iso(), ctx.section), "",
             "## 交付物", "", "| 类别 | 文件 | 大小 |", "|---|---|---|"]
    for p in transcript_docs:
        lines.append("| 修正版逐字稿 | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))
    for p in deliver_docs:
        lines.append("| 交付文档 | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))
    if shots:
        lines.append("| 去边截图 | 共 %d 张（`讲义截图/`） | — |" % len(shots))
    pdfs = sorted(ctx.pdf.glob("*.pdf")) if ctx.pdf.is_dir() else []
    for p in pdfs:
        lines.append("| 精排 PDF | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))

    if meta.get("items"):
        lines += ["", "## 转录概览", "", "| 文件 | 时长(秒) | 语言 | 段落数 | 置信度 |", "|---|---|---|---|---|"]
        for it in meta["items"]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                it.get("stem"), it.get("duration_sec"), it.get("language") or "—",
                it.get("segments_count"), it.get("confidence") if it.get("confidence") is not None else "—"))
    if cm.get("items"):
        lines += ["", "## 视频切片", "",
                  "粒度：`%s`　输出目录：`%s`　段数：%d" % (
                      cm.get("granularity"), Path(cm.get("output_dir", "")).name, len(cm["items"])), "",
                  "| # | 文件名 | 起 | 止 | 时长(秒) |", "|---|---|---|---|---|"]
        for i, it in enumerate(cm["items"], 1):
            lines.append("| %d | `%s` | %.1f | %.1f | %.1f |"
                         % (i, it["filename"], it["start"], it["end"], it["duration"]))
    idx_md = ctx.deliver / "README.md"
    idx_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(str(idx_md))

    # 小节视频清单 CSV / 索引 MD（按粒度）
    if cm.get("items"):
        csv_path = ctx.deliver / "小节视频清单.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["节次", "节标题", "段号", "段标题", "逐字稿对应标题", "文件名", "相对路径",
                        "起始", "结束", "时长_秒", "粒度来源"])
            for i, it in enumerate(cm["items"], 1):
                title = Path(it["filename"]).stem
                rel = str((Path(it["dest_dir"]) / it["filename"]).relative_to(ctx.ws))
                w.writerow([ctx.section, ctx.section, i, title, it.get("transcript_title", ""),
                            it["filename"], rel, "%.2f" % it["start"], "%.2f" % it["end"],
                            "%.2f" % it["duration"], it.get("basis", "")])
        written.append(str(csv_path))

        idx_lines = ["# %s 小节视频索引" % ctx.section, "",
                     "粒度：`%s`　共 %d 段" % (cm.get("granularity"), len(cm["items"])), ""]
        for i, it in enumerate(cm["items"], 1):
            t = it.get("transcript_title") or Path(it["filename"]).stem
            idx_lines.append("%d. **%s**（%.1f–%.1f 秒，%.1f 秒）" % (i, t, it["start"], it["end"], it["duration"]))
            if it.get("product_name"):
                idx_lines.append("   - 产品：%s" % it["product_name"])
        (ctx.deliver / "小节视频索引.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")
        written.append(str(ctx.deliver / "小节视频索引.md"))

        if any(it.get("product_name") for it in cm["items"]):
            pcsv = ctx.deliver / "产品切片清单.csv"
            with pcsv.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["产品名", "对应节次", "段号", "视频文件", "起始", "结束", "时长_秒", "文案文件"])
                for i, it in enumerate(cm["items"], 1):
                    if not it.get("product_name"):
                        continue
                    cw_file = "%s_%s_文案.md" % (ctx.section, it["product_name"])
                    w.writerow([it["product_name"], ctx.section, i, it["filename"],
                                "%.2f" % it["start"], "%.2f" % it["end"], "%.2f" % it["duration"],
                                cw_file if (ctx.chapter / cw_file).is_file() else ""])
            written.append(str(pcsv))

    # 文案汇总（copywriting==on 时，任何粒度都要出）
    entries = cw.get("items") if isinstance(cw, dict) else cw
    if entries:
        cl = ["# %s 文案汇总" % ctx.section, "", "> 由 `copywriting.json` 派生；合规提示须人工核对后方可外发。", ""]
        for e in entries:
            cl.append("## %s" % (e.get("ref") or e.get("scope") or "文案"))
            if e.get("selling_points"):
                cl.append("**卖点**：" + "；".join(map(str, e["selling_points"])))
            if e.get("script"):
                cl += ["", "**口播**：", "", str(e["script"])]
            if e.get("title"):
                cl += ["", "**标题**：%s" % e["title"]]
            if e.get("body"):
                cl += ["", "**正文**：", "", str(e["body"])]
            if e.get("compliance_notes"):
                cl += ["", "**合规提示**：" + "；".join(map(str, e["compliance_notes"]))]
            cl.append("")
        (ctx.deliver / "文案汇总.md").write_text("\n".join(cl) + "\n", encoding="utf-8")
        written.append(str(ctx.deliver / "文案汇总.md"))

    # 目录/产品差异报告（有则归档到交付区，便于交付时一并查阅）
    for src_name, dst_name in (("catalog_diff.json", "目录差异报告.md"),
                               ("product_catalog_diff.json", "产品切片差异报告.md")):
        rec = read_json(ctx.rec(src_name), None)
        if rec:
            body = rec.get("report_md") if isinstance(rec, dict) else None
            if body:
                (ctx.deliver / dst_name).write_text(str(body), encoding="utf-8")
                written.append(str(ctx.deliver / dst_name))

    write_json(ctx.rec("export_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "granularity": cm.get("granularity") or a.granularity,
        "copywriting": bool(entries), "catalog": bool(catalog), "product_catalog": bool(pcatalog),
        "files": written,
    })
    log("  ✓ 导出完成，共 %d 个文件：" % len(written))
    for p in written:
        log("      %s" % Path(p).relative_to(ctx.ws))
    return 0


# ---------------------------------------------------------------------------
# 子命令：render（doc-layout md-pdf：交付文档 → 精排 PDF）
# ---------------------------------------------------------------------------

def cmd_render(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if a.deliverable_render == "off":
        log("  · deliverable_render=off，跳过渲染")
        return 0
    ctx.pdf.mkdir(parents=True, exist_ok=True)

    candidates = []
    for d in (ctx.sub_doc, ctx.sub_transcript):
        if d.is_dir():
            candidates += sorted(d.glob("*.md"))
    if not candidates:
        log("  ⚠ 未找到可渲染的 Markdown 交付物（%s / %s），跳过" % (ctx.sub_doc, ctx.sub_transcript))
        write_json(ctx.rec("render_manifest.json"),
                   {"section": ctx.section, "items": [], "note": "无 Markdown 交付物"})
        return 0

    items, ok, fail = [], 0, 0
    for md in candidates:
        out = ctx.pdf / (md.stem + ".pdf")
        title = md.stem.replace("_", " ")
        proc = kit_call(["md-pdf", "-i", str(md), "-o", str(out), "-t", title])
        good = proc.returncode == 0 and out.is_file() and out.stat().st_size > 1024
        items.append({"src": str(md), "pdf": str(out) if out.is_file() else "",
                      "ok": good, "bytes": out.stat().st_size if out.is_file() else 0,
                      "rc": proc.returncode})
        ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
        log("  %s %s" % ("✓" if good else "✗", md.name))

    write_json(ctx.rec("render_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "renderer": "doc-layout-aesthetics · md-pdf（Markdown→中文精排 PDF；图片按相对路径内联）",
        "output_dir": str(ctx.pdf), "stats": {"ok": ok, "failed": fail}, "items": items,
    })
    if fail:
        log("  ⚠ %d 份渲染失败（见 render_manifest.json），未静默放过" % fail)
        return 3
    log("  ✓ 渲染完成：%d 份 → %s" % (ok, ctx.pdf))
    return 0


# ---------------------------------------------------------------------------
# 子命令：cloud-upload（doc-layout tencent-doc：显式外发，经 kit 外发闸门）
# ---------------------------------------------------------------------------

def cmd_cloud_upload(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if a.cloud_upload != "tencent":
        log("  · cloud_upload=off，跳过云端上传")
        return 0
    docs = sorted(ctx.sub_doc.glob("*.md")) if ctx.sub_doc.is_dir() else []
    if not docs:
        log("  ⚠ 无可上传的交付文档，跳过")
        write_json(ctx.rec("cloud_manifest.json"), {"section": ctx.section, "items": [], "note": "无交付文档"})
        return 0
    items = []
    for md in docs:
        proc = kit_call(["tencent-doc", str(md), "--title", md.stem.replace("_", " ")])
        items.append({"src": str(md), "rc": proc.returncode,
                      "ok": proc.returncode == 0,
                      "note": "（显式外发：命中敏感信息时由 kit 外发闸门阻断，须 --confirm-raw 确认）"})
        log("  %s %s" % ("✓" if proc.returncode == 0 else "✗", md.name))
    write_json(ctx.rec("cloud_manifest.json"), {"section": ctx.section, "generated_at": now_iso(),
                                                "target": "腾讯文档（docs.qq.com）", "items": items})
    bad = [i for i in items if not i["ok"]]
    if bad:
        log("  ⚠ %d 份上传未成功（常见的非缺陷原因：宿主未连接腾讯文档 / 命中敏感被闸门阻断）。"
            "详见 cloud_manifest.json" % len(bad))
        return 3
    log("  ✓ 云端上传完成：%d 份" % len(items))
    return 0


# ---------------------------------------------------------------------------
# 子命令：desen-gate（交付物外发前强制 DESEN 扫描）
# ---------------------------------------------------------------------------

_SCAN_CLEAN = "未发现已知敏感标识符"
_SCAN_HIT = "汇总："


def cmd_desen_gate(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if a.desen_gate == "off":
        log("  ⚠ desen_gate=off：交付物**未经**本地敏感信息扫描（用户显式关闭，风险自负）")
        write_json(ctx.rec("desen_report.json"), {"section": ctx.section, "skipped": True,
                                                  "reason": "desen_gate=off（用户显式关闭）"})
        return 0

    targets = []
    if ctx.deliver.is_dir():
        targets.append(ctx.deliver)
    text_files = []
    for d in (ctx.deliver, ctx.work / "交付"):
        if d.is_dir():
            text_files += [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_DELIVER_EXTS]
    if not targets and not text_files:
        log("  ⚠ 未发现待扫描的交付物（课程交付/ 为空），跳过并将跳过写入报告")
        write_json(ctx.rec("desen_report.json"), {"section": ctx.section, "targets": [], "clean": None,
                                                  "note": "无交付物"})
        return 0

    results, hit_detail, clean_all = [], [], True
    # ① 目录级扫描（快）：命中则确定性阻断；出现「未发现」标记则通过
    for d in targets:
        proc = kit_call(["desen", "scan", str(d), "--recursive"])
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        results.append({"target": str(d), "mode": "dir", "rc": proc.returncode, "output": out[-4000:]})
        if _SCAN_HIT in out:
            clean_all = False
            hit_detail.append({"target": str(d), "output": out[-4000:]})
        elif _SCAN_CLEAN not in out:
            clean_all = None  # 无法判定 → 降级逐文件扫描
    # ② 目录扫描无法判定 → 逐文件扫描（单文件扫描必定产出明确标记）
    if clean_all is None:
        clean_all = True
        for f in sorted(set(text_files)):
            proc = kit_call(["desen", "scan", str(f)])
            out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            results.append({"target": str(f), "mode": "file", "rc": proc.returncode, "output": out[-2000:]})
            if _SCAN_HIT in out:
                clean_all = False
                hit_detail.append({"target": str(f), "output": out[-2000:]})
            elif _SCAN_CLEAN not in out:
                clean_all = False
                hit_detail.append({"target": str(f), "output": out[-2000:] or "（扫描无有效输出，按 fail-safe 判定）"})

    report = {
        "section": ctx.section, "generated_at": now_iso(),
        "policy": "外发必扫 DESEN 铁律（SOUL.md 常驻规则 / SKILL.md 硬约束）——交付物外发前强制扫描",
        "targets": [str(t) for t in targets], "text_files": [str(p) for p in sorted(set(text_files))],
        "clean": bool(clean_all), "hits": hit_detail, "runs": results,
    }
    write_json(ctx.rec("desen_report.json"), report)

    if clean_all:
        log("  ✓ 交付物本地敏感信息扫描通过（未发现已知敏感标识符）→ desen_report.json")
        return 0
    log("  ✗ 交付物命中敏感信息，已按铁律**阻断交付**：")
    for h in hit_detail:
        log("      · %s" % h["target"])
    log("  处置三选一（详见 desen_report.json）：")
    log("    ① 脱敏副本外发：kit desen run <文件> --out workbench/desen/ → 用脱敏副本交付")
    log("    ② 确认原样外发（风险自负）：kit desen audit-log --target 交付物 --decision raw，再经用户确认为相关文件放行")
    log("    ③ 定位并修改源内容后重跑本步")
    return 3


# ---------------------------------------------------------------------------
# 子命令：verify（机械校验；语义判据由 verify 步的确认门交用户/Agent）
# ---------------------------------------------------------------------------

def _duration_of(path: Path, ffmpeg: str) -> float:
    """用 ffprobe 同源能力取时长：ffmpeg -i 输出解析（无 ffprobe 依赖）。"""
    proc = subprocess.run([ffmpeg, "-nostdin", "-i", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
    if not m:
        return -1.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def cmd_verify(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json"), {}) or {}
    cm = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    checks, failed = [], 0

    def add(name, ok, detail=""):
        nonlocal failed
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failed += 1
        log("  %s %s%s" % ("✓" if ok else "✗", name, ("　— %s" % detail) if detail else ""))

    # ① 交付物存在
    docs = list(ctx.sub_doc.glob("*.md")) if ctx.sub_doc.is_dir() else []
    trans = list(ctx.sub_transcript.glob("*.md")) if ctx.sub_transcript.is_dir() else []
    add("交付文档存在（课程交付/讲义/*.md）", bool(docs), "%d 份" % len(docs))
    add("修正版逐字稿存在（课程交付/逐字稿_修正版/*.md）", bool(trans), "%d 份" % len(trans))

    # ② 截图引用零缺失 / 零冗余
    refs, missing = set(), []
    for md in docs + trans:
        for m in RE_MD_IMG.finditer(md.read_text(encoding="utf-8")):
            raw = m.group(1).strip()
            if raw.startswith(("http://", "https://")):
                continue
            p = (md.parent / raw).resolve()
            refs.add(str(p))
            if not p.is_file():
                missing.append("%s → %s" % (md.name, raw))
    add("截图引用零缺失", not missing, ("缺失 %d 处：%s" % (len(missing), "; ".join(missing[:5]))) if missing else "引用 %d 个" % len(refs))
    shots = {str(p.resolve()) for p in ctx.shots.iterdir()
             if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")} if ctx.shots.is_dir() else set()
    orphan = sorted(shots - refs)
    add("截图零冗余（无未被引用的孤儿图）", not orphan,
        ("孤儿 %d 张：%s" % (len(orphan), ", ".join(Path(o).name for o in orphan[:5]))) if orphan else "共 %d 张" % len(shots))

    # ③ 备份链
    if shots:
        baks = {p.name for p in ctx.shots_bak.iterdir() if p.is_file()} if ctx.shots_bak.is_dir() else set()
        add("去边前原图备份齐全（讲义截图_原始备份/）",
            len(baks) >= len(shots), "备份 %d / 现图 %d" % (len(baks), len(shots)))

    # ④ 切片一致性 + 时长核验
    if cm.get("items"):
        items = cm["items"]
        add("切片文件全部存在", all(Path(i["dest_dir"], i["filename"]).is_file() for i in items),
            "%d 段" % len(items))
        csv_path = ctx.deliver / "小节视频清单.csv"
        csv_rows = 0
        if csv_path.is_file():
            with csv_path.open(encoding="utf-8-sig", newline="") as fh:
                csv_rows = max(0, sum(1 for _ in csv.reader(fh)) - 1)
        idx_path = ctx.deliver / "小节视频索引.md"
        idx_rows = 0
        if idx_path.is_file():
            idx_rows = len(re.findall(r"^\d+\.\s\*\*", idx_path.read_text(encoding="utf-8"), re.M))
        add("段数一致（磁盘 = CSV = 索引）", len(items) == csv_rows == idx_rows,
            "磁盘 %d / CSV %d / 索引 %d" % (len(items), csv_rows, idx_rows))
        try:
            ffmpeg, _ = resolve_ffmpeg(a.ffmpeg_bin)
            bad, small = [], []
            for i in items:
                p = Path(i["dest_dir"], i["filename"])
                if not p.is_file():
                    continue
                if p.stat().st_size <= 200 * 1024:
                    small.append(i["filename"])
                d = _duration_of(p, ffmpeg)
                if d > 0 and abs(d - float(i["duration"])) >= 5.0:
                    bad.append("%s 实测 %.1fs ≠ 计划 %.1fs" % (i["filename"], d, i["duration"]))
            add("每段时长误差 <5s", not bad, "; ".join(bad[:5]) if bad else "%d 段核验通过" % len(items))
            if small:
                log("  ⚠ %d 个片段 ≤200KB，可能过短或损坏：%s" % (len(small), ", ".join(small[:5])))
        except VcpError as exc:
            add("时长核验（需 ffmpeg）", False, str(exc))

    # ⑤ 记录链完整性
    required = ["run_context.json", "ingestion_manifest.json", "transcript_meta.json", "frame_index.json"]
    if a.granularity != "none":
        required += ["cut_plan.json", "cut_manifest.json"]
    miss = [r for r in required if not ctx.rec(r).is_file()]
    add("工作记录链完整", not miss, ("缺失：%s" % ", ".join(miss)) if miss else "%d 项齐全" % len(required))

    # ⑥ 外发扫描结论（外发前必扫铁律的留痕）
    drep = read_json(ctx.rec("desen_report.json"), None)
    if a.desen_gate == "on":
        add("交付物已经本地敏感信息扫描且通过", bool(drep and drep.get("clean")),
            "见 desen_report.json" if drep else "缺少 desen_report.json（desen_gate 步未执行）")

    # ⑦ 渲染一致性（开启时）
    if a.deliverable_render == "pdf":
        rman = read_json(ctx.rec("render_manifest.json"), {}) or {}
        expect = {p.stem for p in docs + trans}
        got = {Path(i["src"]).stem for i in (rman.get("items") or []) if i.get("ok")}
        add("Markdown 交付物均已产出精排 PDF", expect <= got,
            "缺 %s" % ", ".join(sorted(expect - got)) if expect - got else "%d 份" % len(got))

    write_json(ctx.rec("verify_report.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "granularity": cm.get("granularity") or a.granularity,
        "mechanical_checks": checks, "failed": failed,
        "semantic_pending": [
            "图文位置判据 A 真错位 / B 多图堆叠 / C 图先于文 / D 裸图堆叠 必须为 0（E 类合法例外放行）"
            "——见 illustration-spec.md，属语义判断，由确认门交用户/Agent 复核",
            "配图三条标准（内容匹配 / 数量按需 / 密集合成）复核",
            "交付文档结构符合 delivery_spec.json 指定形态",
            "文案合规提示齐全（极限词/价格/功效需人工核对）",
            "目录/产品差异报告已确认",
        ],
    })
    log("  ── 机械校验：%d 项，失败 %d 项 ──" % (len(checks), failed))
    if failed:
        log("  ✗ 机械校验未通过，请修复后重跑本步（详见 verify_report.json）")
        return 3
    log("  ✓ 机械校验全部通过；语义判据（图文位置/配图标准/合规）见 verify_report.json 的 semantic_pending，"
        "须在确认门由用户确认")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vcp.py",
        description="video-to-content-pack 机械步 CLI（由 kit workflow 以 uses.script 调用）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, workspace=True):
        if workspace:
            sp.add_argument("--workspace", required=True, help="内容工作区根目录")
        sp.add_argument("--section", default="第1节", help="节名（默认 第1节）")
        return sp

    sp = common(sub.add_parser("precheck", help="入参与环境前置校验"))
    sp.add_argument("--source", default="file")
    sp.add_argument("--source-uri", dest="source_uri", default="")
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--copywriting", default="off")
    sp.add_argument("--digest", default="on")
    sp.add_argument("--deliverable-types", dest="deliverable_types", default="讲义")
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.add_argument("--cloud-upload", dest="cloud_upload", default="off")
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.add_argument("--whisper-model", dest="whisper_model", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_precheck)

    common(sub.add_parser("mkdirs", help="建工作区目录骨架")).set_defaults(func=cmd_mkdirs)

    sp = common(sub.add_parser("ingest", help="本地文件归一化到 按章节/<节>/"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.set_defaults(func=cmd_ingest)

    sp = common(sub.add_parser("record-live", help="直播降级：ffmpeg 先录制为本地文件"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.set_defaults(func=cmd_record_live)

    sp = common(sub.add_parser("record-device", help="设备降级：ffmpeg 设备后端采集为本地文件"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.set_defaults(func=cmd_record_device)

    sp = common(sub.add_parser("transcribe", help="转录（经 kit.py 调用 info-extract，保留外发闸门）"))
    sp.add_argument("--whisper-model", dest="whisper_model", default="")
    sp.set_defaults(func=cmd_transcribe)

    sp = common(sub.add_parser("index-records",
                               help="记录链索引：ingestion_manifest / transcript_meta / frame_index"))
    sp.add_argument("--dup-mad", dest="dup_mad", type=float, default=2.0,
                    help="帧判重的 MAD 阈值（0~255，越小越严；默认 2.0）")
    sp.set_defaults(func=cmd_index_records)

    sp = common(sub.add_parser("digest", help="summarize 接入：速览/关键词"))
    sp.add_argument("--keywords", type=int, default=12)
    sp.set_defaults(func=cmd_digest)

    common(sub.add_parser("frames-ocr", help="逐帧 OCR（subprocess-per-image + 断点续跑）")
           ).set_defaults(func=cmd_frames_ocr)

    sp = common(sub.add_parser("crop", help="截图去边（保守算法 + 原图备份）"))
    sp.add_argument("--pad", type=int, default=8)
    sp.add_argument("--keep-min", dest="keep_min", type=float, default=0.55)
    sp.add_argument("--max-side", dest="max_side", type=int, default=200)
    sp.set_defaults(func=cmd_crop)

    sp = common(sub.add_parser("cut", help="按 cut_plan.json 切片（增量重切）"))
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_cut)

    sp = common(sub.add_parser("export", help="派生清单/索引/文案汇总/交付总索引"))
    sp.add_argument("--granularity", default="none")
    sp.set_defaults(func=cmd_export)

    sp = common(sub.add_parser("render", help="交付文档 → 精排 PDF（doc-layout md-pdf）"))
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.set_defaults(func=cmd_render)

    sp = common(sub.add_parser("cloud-upload", help="交付文档 → 腾讯文档（显式外发，经 kit 闸门）"))
    sp.add_argument("--cloud-upload", dest="cloud_upload", default="off")
    sp.set_defaults(func=cmd_cloud_upload)

    sp = common(sub.add_parser("desen-gate", help="交付物外发前 DESEN 扫描（命中即阻断）"))
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.set_defaults(func=cmd_desen_gate)

    sp = common(sub.add_parser("verify", help="机械校验（引用/段数/时长/记录链/备份链）"))
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_verify)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except VcpError as exc:
        log("✗ %s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
