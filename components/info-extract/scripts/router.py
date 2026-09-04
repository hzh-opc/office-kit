#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 主入口（类型识别 + 按需路由，D8）。

设计（呼应方案 §0.5 / 流程规范 §1）：
- 仅做「接收 → 类型识别 → 路由」，命中类型才 import 对应模块（未命中不预载 Whisper/VLM 等重型依赖）。
- 默认本地优先、默认不上云（§4 红线）；涉及上云/外部调用由交互确认门（⑧⑨）控制，本 CLI 不自动上云。
- 输出经各模块落双通道（txt/srt/json/md，D11）；本入口负责汇总展示与批量聚合提示（D12·H）。

用法：
  python router.py 录音.mp3                       # 自动识别为音频 → 转录
  python router.py *.wav --lang 日文 --task transcribe
  python router.py 会议.m4a --model medium        # 升级模型（噪声明/方言）
  python router.py ./音频目录 --recursive --out ./结果
  python router.py --check                         # 查看能力/provider 可用性
  python router.py 课程.mp4                         # 抽音轨→转录（阶段二，复用 Whisper）
  python router.py 课程.mp4 --no-frames            # 仅文案，不抽讲解画面帧
  python router.py "https://www.example.com/watch?v=abc"   # 在线视频（阶段五）：yt-dlp 下载(tmp,处理后即删,不留存)
  python router.py "https://encrypted.example.com/v" --capture-path ./录制.mp4  # 加密/DRM：本地录制文件走浏览器捕获回退
  python router.py 图片.png                         # 本地 OCR（阶段三，rapidocr，离线）
  python router.py 扫描件.pdf                       # 图片型 PDF → 探测分流 + 本地 OCR
  python router.py 扫描件.pdf --force-ocr          # 强制全部页 OCR（含文本层页）
  python router.py 图片.png --confidence-threshold 0.9   # 调高置信度门控阈值
  python router.py 图片.png --context "这是一份化学实验报告"   # D16 纠正版稿件：提供语境消歧
  python router.py 录音.mp3 --no-correct                # D16 跳过纠正，直接以原始识别为交付物
  # 直播录制（阶段六 P0）：录制直播为本地回放后转写
  python router.py --live "https://live.douyin.com/xxx" --live-transcribe   # 边录边转，近实时出稿
  python router.py --live "https://live.douyin.com/xxx" --cookies-from-browser chrome  # 需登录态直播
  python router.py --live "https://live.douyin.com/xxx" --capture-path ./直播录屏.mp4  # browser 持登录态取流回退
  # 设备摄取（阶段六 P1）：摄像头/采集卡/OBS 虚拟相机
  python router.py --device "avfoundation:1:0" --duration 300   # macOS 摄像头录制 300 秒后转写
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from modules.base import SourceType  # noqa: E402
from quality_scorer import score  # noqa: E402
from utils.io import classify, discover, is_url  # noqa: E402

MODULE_MAP = {
    SourceType.TRANSCRIPT: ("modules.audio", "AudioModule"),
    SourceType.OCR: ("modules.ocr", "OCRModule"),
    SourceType.VISION: ("modules.vision", "VisionModule"),
    SourceType.DOC_EXTRACT: ("modules.doc_extract", "DocExtractModule"),
    SourceType.VIDEO: ("modules.video", "VideoModule"),
    SourceType.VIDEO_ONLINE: ("modules.video_online", "VideoOnlineModule"),
    # 阶段六 上游需求：直播链接录制（P0）/ 视频采集设备摄取（P1）
    SourceType.LIVE: ("modules.live", "LiveModule"),
    SourceType.CAPTURE: ("modules.capture", "CaptureModule"),
}


def _detect_runtime_problem() -> str | None:
    """返回缺失的硬依赖名；都可用则返回 None。

    numpy/av 是阶段一音频管线的强制本地依赖（av 自带 ffmpeg 免系统依赖）。
    faster-whisper 为可选 provider，缺失时由 available() 优雅降级（显示 ⬜），不在此门禁。
    """
    for mod in ("numpy", "av"):
        try:
            __import__(mod)
        except ImportError:
            return mod
    return None


def _venv_python() -> Path | None:
    """解析隔离 venv 解释器（跨平台），按优先级：

    1. UV_PROJECT_ENVIRONMENT（宿主/kit 显式注入，office-kit 经 kit.py 已设置）；
    2. VIRTUAL_ENV（已激活的 venv，source .venv/bin/activate 或 uv run 注入）；
    3. 脚本同目录 .venv（独立技能时期布局，回退保持兼容）。

    与 doc-layout-aesthetics/scripts/_venv.py:resolve_venv 约定一致，
    使组件被「拔插」进任意 kit 时只要调用方设置了 UV_PROJECT_ENVIRONMENT，
    组件自身无需感知 kit 目录布局、零改造即可运行。
    """
    candidates: List[Path] = []
    env_uv = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if env_uv:
        candidates.append(Path(os.path.expanduser(env_uv)))
    env_virtual = os.environ.get("VIRTUAL_ENV")
    if env_virtual:
        candidates.append(Path(os.path.expanduser(env_virtual)))
    candidates.append(SCRIPT_DIR / ".venv")  # 回退：独立技能用法
    for base in candidates:
        cand = base / "Scripts" / "python.exe" if sys.platform.startswith("win") else base / "bin" / "python"
        if cand.is_file():
            return cand
    return None


def ensure_runtime() -> None:
    """在导入任何重型依赖前，保证运行环境就绪。

    - 裸 python 缺 numpy/av 时：优先自动复用到同目录 .venv（仅一次，带 env 防递归标记）；
    - 否则给出明确 install 指引并干净退出（exit 2），避免抛出裸 ModuleNotFoundError traceback。
    """
    missing = _detect_runtime_problem()
    if missing is None:
        return

    # 尝试一次自动复用同目录 venv（防递归：已复刻进程不再二次复刻）
    if os.environ.get("INFO_EXTRACT_REEXEC") != "1":
        vp = _venv_python()
        if vp is not None:
            os.environ["INFO_EXTRACT_REEXEC"] = "1"
            try:
                os.execv(str(vp), [str(vp), str(Path(__file__).resolve()), *sys.argv[1:]])
            except OSError:
                pass  # 落到下面的友好提示

    print(
        "❌ 未检测到运行环境依赖（缺少 '" + (missing or "numpy/av") + "'）。\n"
        "info-extract 依赖隔离在虚拟环境中，venv 解析顺序：UV_PROJECT_ENVIRONMENT → VIRTUAL_ENV → scripts/.venv。\n"
        "请先安装运行环境：\n"
        "  bash install.sh            # 或：python install.py\n"
        "随后可用对应 venv 解释器运行：\n"
        "  <venv>/bin/python scripts/router.py --check\n"
        "（也可直接裸 python 运行：若已设 UV_PROJECT_ENVIRONMENT/VIRTUAL_ENV 或 scripts/.venv 存在，"
        "脚本会自动复用对应环境；否则需先 install。）",
        file=sys.stderr,
    )
    sys.exit(2)


def load_module(source_type: str):
    mod_path, cls_name = MODULE_MAP[source_type]
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)()


def build_options(args) -> Dict:
    return {
        "lang": args.lang,
        "task": args.task,
        "model": args.model,
        "provider": args.provider,
        "out_dir": args.out,
        "use_cache": not args.no_cache,
        "long_threshold": args.long_threshold,
        "vad_threshold": args.vad_threshold,
        "extract_frames": not args.no_frames,
        # 阶段三 OCR 选项（D2 置信度门控 / 审阅 D 预处理链 / D15 provider）
        "confidence_threshold": args.confidence_threshold,
        "force_ocr": args.force_ocr,
        "preprocess": not args.no_preprocess,
        # 阶段四 画面解读选项（D7 档位自适应 / OCR 协同 / 整视频关键帧视觉分析）
        "vision_tier": args.vision_tier,
        "ocr_coop": not args.no_ocr_vision,
        "vision": args.vision,
        # D16 交付物范式：纠正版稿件（本地离线 / 语境消歧；联网检索仅 agent 层触发）
        # 用 getattr 兜底，保证 build_options 对未含新选项的调用方（如单测手搓 args）健壮
        "no_correct": getattr(args, "no_correct", False),
        "context": getattr(args, "context", None),
        "correct_model": getattr(args, "correct_model", None),
        # 组件反馈「交互与展示优化」：交付物分区 + 敏感预检
        "flat_out": getattr(args, "flat_out", False),
        "desensitize": getattr(args, "desensitize", False),
        # 阶段五 在线/加密视频：用户提供本地录制文件走浏览器捕获回退（--capture-path）
        "capture_path": getattr(args, "capture_path", None),
        # 阶段五增强（方案 B）：账号/合集枚举 + cookie 适配（抖音/小红书/B站 等）
        "cookies": getattr(args, "cookies", None),
        "cookies_from_browser": getattr(args, "cookies_from_browser", None),
        "enumerate": getattr(args, "playlist", False),
        # 方案 B 后续强化：账号批量防风控限速（顺序处理 + 随机间隔 + 数量上限）
        "enum_interval": getattr(args, "enum_interval", 3.0),
        "no_throttle": getattr(args, "no_throttle", False),
        "enum_limit": getattr(args, "enum_limit", None),
        # 阶段六 直播录制（P0）/ 设备摄取（P1）：新增参数（上游需求）
        "live": getattr(args, "live", False),
        "live_timeout": getattr(args, "live_timeout", 0),
        "live_stop_on_end": getattr(args, "live_stop_on_end", False),
        "live_transcribe": getattr(args, "live_transcribe", False),
        "record_and_transcribe": getattr(args, "record_and_transcribe", False),
        "device": getattr(args, "device", None),
        "duration": getattr(args, "duration", None),
        "keep_live": getattr(args, "keep_live", False),
        # 录制静默超阈终止开关（默认启用；--no-stall-abort 关闭，仅告警）
        "stall_abort": not getattr(args, "no_stall_abort", False),
    }


def run_check() -> int:
    from provider_registry import available_providers  # noqa
    from skill_bridge import self_check  # noqa

    print("=== info-extract · 能力自检 ===")
    print("\n[本地 Provider 可用性]")
    for cap in [SourceType.TRANSCRIPT, SourceType.OCR, SourceType.VISION,
                SourceType.DOC_EXTRACT, SourceType.VIDEO, SourceType.VIDEO_ONLINE,
                SourceType.VIDEO_ONLINE_ENUM, SourceType.LIVE, SourceType.CAPTURE]:
        provs = available_providers(cap)
        if not provs:
            print(f"  - {cap}: (尚未接入)")
            continue
        for p in provs:
            mark = "✅" if p["available"] else "⬜"
            print(f"  - {cap} / {p['name']}: {mark} {p['meta'].get('cost','')}")
    print("\n[协同能力自检 D9]")
    for cap, skill in self_check().items():
        mark = "✅" if skill else "⬜"
        print(f"  - {cap}: {mark} {skill or '缺失（将降级）'}")
    print("\n原则：本地优先 · 默认不上云 · 机器结果须经你确认（§4）。")
    return 0


def main(argv: List[str] | None = None) -> int:
    ensure_runtime()  # 门禁：缺依赖自动复用 venv 或友好退出（见 ensure_runtime）
    parser = argparse.ArgumentParser(
        prog="info-extract",
        description="信息抽取技能主入口：音频转录、视频文案、OCR、画面解读、在线/加密视频均已实现；"
                    "复合文档抽取（doc_extract）规划中。",
    )
    parser.add_argument("inputs", nargs="*", help="待处理文件/目录/glob")
    parser.add_argument("--type", choices=["auto", *MODULE_MAP.keys()], default="auto",
                        help="强制指定类型；默认 auto 按扩展名识别")
    parser.add_argument("--lang", help="语言/任务轻提示，如「日文采访」「翻译成英文」（D12·K）")
    parser.add_argument("--task", choices=["transcribe", "translate"], help="transcribe 原语转录 / translate 翻译")
    parser.add_argument("--model", default="small",
                        choices=["tiny", "base", "small", "medium", "large-v3", "turbo"],
                        help="Whisper 模型规模（默认 small；仅音频/视频文案生效）")
    parser.add_argument("--provider", default="auto",
                        help="provider：auto / faster-whisper（转录）/ rapidocr（OCR）（D15）")
    parser.add_argument("--out", default=os.getcwd(), help="输出目录（默认当前目录）")
    parser.add_argument("-r", "--recursive", action="store_true", help="递归目录")
    parser.add_argument("--no-cache", action="store_true", help="禁用哈希缓存（D12·L）")
    parser.add_argument("--no-frames", action="store_true",
                        help="禁用视频讲解段关联帧抽取（D13）；仅产出文案")
    parser.add_argument("--long-threshold", type=int, default=600,
                        help="超过该秒数启用 VAD 分块（默认 600，D12·J）")
    parser.add_argument("--vad-threshold", type=int, default=700,
                        help="VAD 最小静音毫秒（默认 700，D12·J）")
    # 阶段三 OCR 选项
    parser.add_argument("--confidence-threshold", type=float, default=0.85,
                        help="OCR 置信度门控阈值（默认 0.85，低于则标记本地质量受限、建议上云提质，D2/审阅 D）")
    parser.add_argument("--force-ocr", action="store_true",
                        help="PDF 强制全部页 OCR（默认含原生文本层页交 document_text，D10 分工）")
    parser.add_argument("--no-preprocess", action="store_true",
                        help="禁用 OCR 前图像预处理链（归一化/去噪/deskew，审阅 D）")
    # 阶段四 画面解读选项
    parser.add_argument("--vision", action="store_true",
                        help="视频：额外做场景切换关键帧采样 + 视觉描述（审阅 F，需本地 VLM）")
    parser.add_argument("--vision-tier", default=None,
                        help="手动指定 VLM 档位（D7 覆盖自动判定）：0=轻量(3B)/1=标准(7B)/2=高性能/3=旗舰(32B)，"
                             "或 ollama 模型标签；默认按硬件自适应")
    parser.add_argument("--no-ocr-vision", action="store_true",
                        help="画面解读时关闭 OCR 协同（§1.1 B.3，默认开启：先取图中文字再结合画面理解）")
    # D16 交付物范式：纠正版稿件（默认本地离线纠正，不联网）
    parser.add_argument("--no-correct", action="store_true",
                        help="跳过纠正版稿件生成（D16）：直接以原始识别作为交付物，raw_text 仍保留备查")
    parser.add_argument("--context", default=None,
                        help="纠正版稿件的语境/上下文（D16）：提供给本地模型用于消歧，如领域/术语/专有名词")
    parser.add_argument("--correct-model", default=None,
                        help="纠正用本地文本模型（ollama 标签，默认 qwen2.5:7b；需本机已拉取，零新依赖）")
    # 组件反馈「交互与展示优化」：交付物分区 + 敏感预检
    parser.add_argument("--flat-out", action="store_true",
                        help="输出目录不拆「交付/存档」分区，平铺到输出目录（组件反馈 P0-① 降级，旧行为）")
    parser.add_argument("--desensitize", "--redact-pii", action="store_true",
                        help="交付前对识别稿做敏感信息检测并在交付卡片提示（组件反馈 P1-④；脱敏动作仍归 DESEN，"
                             "本开关仅强化检测提示，如需真正脱敏请用 desensitization-sop）")
    # 阶段五 在线/加密视频选项
    parser.add_argument("--capture-path", default=None,
                        help="在线/加密视频：指定本地录制文件路径（播放中捕获产物），走 BrowserCapture 回退（§4 边界 #2）")
    # 阶段五增强（方案 B）：账号/合集枚举 + cookie 适配
    parser.add_argument("--cookies", default=None,
                        help="在线/加密视频：Netscape cookies.txt 路径，用于需登录态的账号视频（抖音/小红书/B站）")
    parser.add_argument("--cookies-from-browser", default=None,
                        help="在线/加密视频：从本机浏览器注入登录态（chrome/firefox/edge/safari/brave），"
                             "用于需登录的账号视频；仅处理你有权访问的内容（§4 边界 #2/#3）")
    parser.add_argument("--playlist", "--account", action="store_true",
                        help="强制将输入 URL 视为账号/合集/频道页，先枚举其下全部视频再逐条转写"
                             "（抖音/小红书/B站 账号页默认自动识别枚举，此开关可覆盖其它平台）")
    # 方案 B 后续强化：账号批量防风控限速
    parser.add_argument("--enum-interval", type=float, default=3.0,
                        help="账号/合集批量处理：相邻两条视频之间的间隔秒数（默认 3.0，带 0.5x~1.5x 随机抖动；"
                             "防风控限流，降低封号/限流风险）")
    parser.add_argument("--enum-limit", type=int, default=None,
                        help="账号/合集批量处理：单账号最多处理的视频数（默认全部；超大账号建议分批，防风控/控成本）")
    parser.add_argument("--no-throttle", action="store_true",
                        help="关闭账号批量处理的限速间隔（仅当你明确拥有这些内容且接受平台风控风险时）")
    # 阶段六 直播录制（P0）/ 设备摄取（P1）：上游需求新增参数
    parser.add_argument("--live", action="store_true",
                        help="进入直播录制模式（区别于点播下载）：录制直播为本地回放后转写（上游需求 P0）")
    parser.add_argument("--live-timeout", type=int, default=0,
                        help="直播录制最长时长（秒，0=不超时，直到直播结束或中断）；到点自动停止")
    parser.add_argument("--live-stop-on-end", action="store_true",
                        help="直播结束时（EOF/平台信号）自动停止录制（默认也监听，此开关显式强调）")
    parser.add_argument("--live-transcribe", action="store_true",
                        help="边录边转：录制同时持续送 video_transcript，近实时出稿（上游需求·机制二优先策略）")
    parser.add_argument("--record-and-transcribe", action="store_true",
                        help="先录制为本地文件、结束后再统一转写（机制二降级策略，稳定性更高）")
    parser.add_argument("--device", default=None,
                        help="视频采集设备摄取（P1）：设备描述符，如 \"avfoundation:1:0\"(macOS)/"
                             "\"USB Video\"(Windows dshow)/ /dev/video0(Linux v4l2)/ DeckLink 设备")
    parser.add_argument("--duration", type=int, default=None,
                        help="设备录制时长（秒），到点自动停止；亦可作为直播硬超时（无 --duration 时设备默认 "
                             "3600 秒硬超时，避免永录）")
    parser.add_argument("--keep-live", action="store_true",
                        help="保留录制副本（默认 D3 不留存，处理后即删，仅保留转写产物）")
    parser.add_argument("--no-stall-abort", action="store_true",
                        help="录制静默超阈时仅告警、不自动终止（默认静默超 90s 即主动终止并断流重连）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果（供下游消费）")
    parser.add_argument("--check", action="store_true", help="仅自检能力/provider 可用性")
    parser.add_argument("--quiet", action="store_true", help="仅输出结果，不打印横幅")
    parser.add_argument("--external", action="store_true",
                        help="声明本结果将外发/上云：检出敏感信息时触发确认闸口，"
                             "未获确认则阻断（exit 3），避免含 PII 的识别稿被送出本机")
    args = parser.parse_args(argv)

    if args.check:
        return run_check()

    if not args.inputs and not (args.live or args.device):
        parser.error("未提供输入；用 router.py --check 查看能力，或传入音频文件（直播用 --live <url>，设备用 --device <设备描述符>）。")

    # 类型识别：拆分 URL 与本地文件（URL 默认归在线/加密视频，阶段五）
    url_inputs = [raw for raw in args.inputs if is_url(raw)]
    file_inputs = [raw for raw in args.inputs if not is_url(raw)]

    # 阶段六 上游需求：直播/设备 优先于通用 URL 路由（--live / --device / --type live|capture）
    forced = None
    if args.type not in ("auto", None):
        forced = args.type
    elif args.live:
        forced = SourceType.LIVE
    elif args.device:
        forced = SourceType.CAPTURE

    if forced and forced != SourceType.VIDEO_ONLINE:
        # 直播/设备：URL 与本地文件都按该类型路由（直播源为 URL；设备源来自 --device）
        found = []
        unsupported = []
        if forced == SourceType.CAPTURE:
            # 设备摄取：输入来自 --device（非位置参数），构造占位输入供模块消费
            found.append((args.device, SourceType.CAPTURE))
        else:
            for raw in args.inputs:
                if forced == SourceType.LIVE:
                    found.append((raw, SourceType.LIVE))
                else:
                    p = Path(raw).expanduser()
                    if p.exists() and p.is_file():
                        found.append((str(p.resolve()), forced))
                    else:
                        unsupported.append(str(p))
    else:
        # 自动类型：本地文件走 discover；URL → 在线/加密视频
        if args.type == "auto":
            found, unsupported = discover(file_inputs, recursive=args.recursive)
        else:
            # 强制类型为其它（如 video_online）：把所有存在的本地文件当作该类型
            found = []
            unsupported = []
            for raw in file_inputs:
                p = Path(raw).expanduser()
                if p.exists() and p.is_file():
                    found.append((str(p.resolve()), args.type))
                else:
                    unsupported.append(str(p))
        # URL 输入 → 在线/加密视频（阶段五，已实现：yt-dlp 下载 / 浏览器捕获回退 / 账号枚举）
        for u in url_inputs:
            found.append((u, SourceType.VIDEO_ONLINE))

    if not found and unsupported:
        print("⚠️ 无受支持的文件。以下格式当前未支持或对应能力规划中：")
        for u in unsupported:
            print(f"  - {u}")
        return 2

    # 按类型分组
    groups: Dict[str, List[str]] = {}
    for path, stype in found:
        groups.setdefault(stype, []).append(path)

    options = build_options(args)
    # 组件反馈 P0-①：--flat-out 通过环境变量兜底到所有 output 调用点（含无 options 的 recorder）
    if options.get("flat_out"):
        os.environ["INFO_EXTRACT_FLAT_OUT"] = "1"
    all_results = []

    if not args.quiet and not args.json:
        print("info-extract · 本地优先 · 默认不上云（§4）")
        print(f"命中类型：{', '.join(groups.keys()) or '无'}")

    for stype, paths in groups.items():
        module = load_module(stype)
        if not module.ready:
            planned = module.run(paths, options)
            phase = planned[0].media_ref.get("phase", "规划中") if planned else "规划中"
            print(f"\n[{stype}] {phase}：当前阶段未实现，输入已识别但暂不处理：")
            for p in paths:
                print(f"  - {p}")
            continue
        results = module.run(paths, options)
        all_results.extend(results)

    # 汇总
    ok = [r for r in all_results if r.media_ref.get("status") == "ok"]
    cached = [r for r in all_results if r.media_ref.get("status") == "cached"]
    err = [r for r in all_results if r.media_ref.get("status") == "error"]

    if args.json:
        payload = {
            "total": len(all_results),
            "ok": len(ok), "cached": len(cached), "error": len(err),
            "results": [r.to_contract() for r in all_results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        if not args.quiet:
            print(f"\n=== 处理汇总 ===\n成功 {len(ok)} ｜ 缓存命中 {len(cached)} ｜ 异常 {len(err)}")
            for r in all_results:
                mr = r.media_ref
                if mr.get("status") == "ok":
                    print(f"\n📄 {mr.get('path')}")
                    if r.source == SourceType.OCR:
                        # OCR 友好汇总（页数/框数/置信度/质量受限/文本层页提示）
                        f = r.fields
                        print(f"   页数={f.get('pages')} 框数={f.get('num_boxes')} "
                              f"平均置信度={r.confidence} 引擎={r.provider_meta.get('provider')}")
                        if mr.get("is_pdf"):
                            tl = f.get("text_layer_pages_skip")
                            if tl:
                                print(f"   文本层页(D10)：{tl} 已跳过→建议 document_text 抽取文本层")
                        if f.get("local_quality_limited"):
                            print(f"   ⚠️ 本地质量受限：平均置信度 <{f.get('confidence_threshold')}，"
                                  f"可上云提质（需经脱敏闸门，§4.4）")
                    elif r.source == SourceType.VISION:
                        # 画面解读友好汇总（VLM 可用 / 档位 / OCR 协同 / 上云提质提示）
                        f = r.fields
                        avail = f.get("vision_available")
                        print(f"   VLM={'✅本地' if avail else '⚠️未配置'} "
                              f"引擎={r.provider_meta.get('provider')}"
                              + (f" tier={f.get('vision_tier')}" if f.get('vision_tier') else "")
                              + (f" OCR协同={'✅' if f.get('ocr_text') else '—'}"))
                        if f.get("caption"):
                            print(f"   解读：{f['caption'][:60]}{'…' if len(f['caption']) > 60 else ''}")
                        if not avail:
                            print(f"   ℹ️ 本地未配置 VLM（ollama），仅提供 OCR 文字；如需画面解读可上云提质（D2/§4.4）")
                    else:
                        print(f"   语言={r.fields.get('detected_language')} 时长={r.fields.get('duration_sec')}s "
                              f"置信度={r.confidence} 引擎={r.provider_meta.get('provider')}")
                        if mr.get("live"):
                            lt = "（边录边转）" if r.fields.get("live_transcribe") else "（先录后转）"
                            print(f"   直播录制{lt}：获取方式={r.fields.get('acquire_method')}；"
                                  f"副本{'已保留(--keep-live)' if not mr.get('no_copy_saved') else '未保存(D3)'}")
                            if mr.get("manifest"):
                                print(f"   摄取清单(manifest)：{mr.get('manifest')}")
                        elif mr.get("capture"):
                            lt = "（边采边转）" if r.fields.get("live_transcribe") else "（先录后转）"
                            print(f"   设备摄取{lt}：设备={mr.get('device')} 后端={mr.get('backend')}；"
                                  f"副本{'已保留(--keep-live)' if not mr.get('no_copy_saved') else '未保存(D3)'}")
                        elif mr.get("online"):
                            enc = "（加密/DRM）" if r.fields.get("encrypted") else ""
                            print(f"   在线/加密视频{enc}：获取方式={r.fields.get('acquire_method')}；"
                                  f"副本未保存(D3)，仅产出文案/字幕")
                            if r.fields.get("legal_risk_warning"):
                                print(f"   ⚠️ {r.fields.get('legal_risk_warning')}")
                    # D16 纠正版稿件状态（透明回显，D15/§4.7 同构）——组件反馈 P2-①：五态细分提示
                    cm = r.provider_meta.get("correction") if isinstance(r.provider_meta, dict) else None
                    if cm:
                        status = cm.get("status")
                        print(f"   纠正(D16)：{status}" + (f"（{cm.get('model')}）" if cm.get('model') else ""))
                        if status == "skipped:no-model":
                            print(f"   ℹ️ 本机未配置纠正模型，可运行 `ollama pull qwen2.5:7b` 启用本地纠正")
                        elif status == "skipped:error":
                            print(f"   ⚠️ 纠正失败（模型不可达/超时），已保留原始识别")
                        elif status == "skipped:empty":
                            print(f"   ⚠️ 纠正模型未返回有效文本，已保留原始识别")
                    # 组件反馈 P1-②：无纠正模型时显式降级提示（交付物=未校正识别稿）
                    if r.corrected is None and r.source in (SourceType.TRANSCRIPT, SourceType.OCR, SourceType.VISION, SourceType.VIDEO, SourceType.VIDEO_ONLINE):
                        print(f"   ⚠️ 本次未生成纠正版，以下为原始识别稿，仅供参考（未校正）")
                    # 组件反馈 P1-④：敏感信息提示行（落盘后只读扫描结果）
                    pii = r.media_ref.get("pii_scan") if isinstance(r.media_ref, dict) else None
                    if pii and pii.get("total"):
                        kinds = "、".join(f"{k.get('label')}×{k.get('count')}" for k in pii.get("kinds", []))
                        print(f"   🔒 敏感信息：检出 {pii.get('total')} 处（{kinds}），外发前请脱敏（desensitization-sop）")
                        if args.external:
                            from skill_bridge import request_external_confirmation
                            pii_hits = {k.get("label"): k.get("count") for k in pii.get("kinds", [])}
                            if not request_external_confirmation(
                                    purpose="识别稿外发（将送出本机）", pii_hits=pii_hits):
                                sys.stderr.write("✗ 外发未获确认，已阻断（请勿将含敏感信息的识别稿送出本机）。\n")
                                sys.exit(3)
                    # D15 质量评分：透明回显质量档与建议（quality_scorer 驱动自动升级）
                    q = score(r)
                    qual = f"   质量：{q['quality']}"
                    if q.get("suggestion"):
                        qual += f"（{q['suggestion']}）"
                    print(qual)
                    outs = mr.get("outputs", {})
                    print(f"   产出：{', '.join(f'{k}→{v}' for k, v in outs.items())}")
                    if r.referenced_frame and r.referenced_frame.get("frames"):
                        n = len(r.referenced_frame["frames"])
                        n_cap = sum(1 for fr in r.referenced_frame["frames"] if fr.get("vision_caption"))
                        cap_note = f"，其中 {n_cap} 张已填视觉描述" if n_cap else ""
                        print(f"   讲解画面帧(D13)：{n} 张（见输出目录 <stem>_frames/，默认落本地、不自动上云）{cap_note}")
                    if r.fields.get("keyframe_analysis"):
                        kf = r.fields["keyframe_analysis"].get("keyframes", [])
                        print(f"   关键帧视觉分析(审阅 F)：{len(kf)} 帧（场景切换采样 + 视觉描述）")
                    if mr.get("report"):
                        print(f"   批量报告：{mr['report'].get('md')}")
                elif mr.get("status") == "cached":
                    print(f"\n♻️ {mr.get('path')}（缓存命中，已刷新产出）")
                else:
                    print(f"\n⚠️ {mr.get('path')}：{mr.get('error')}")
                    if mr.get("hint"):
                        print(f"   建议：{mr.get('hint')}")

    # 异常码
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
