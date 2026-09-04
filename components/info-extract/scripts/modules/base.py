#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 跨模块基础契约与接口。

本文件只依赖标准库，是各能力域模块共享的最小契约来源：
- SourceType：资料来源类型（ocr / vision / transcript / doc_extract / video_online）。
- Segment：带时间戳的片段（音频/视频文案的基本单位）。
- ExtractResult：标准输出契约对象（D11），下游 summarize / knowledge_base / translation 可直接消费。
- IModule：能力域模块统一接口（按需载入，D8）。

设计原则（呼应方案 §0.6 / §3.6 / 流程规范 §4.6）：
- 所有模块产出统一为 ExtractResult，落「双通道」（纯文本 .txt + 结构化 .json/.md）。
- provider_meta 透明回显「用了谁、是否上云」（D15 / 流程规范 §4.7）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


class SourceType:
    """资料来源类型常量。"""

    OCR = "ocr"
    VISION = "vision"
    TRANSCRIPT = "transcript"
    DOC_EXTRACT = "doc_extract"
    VIDEO = "video"            # 本地视频文件：阶段二（文案提取，复用音频转录）
    VIDEO_ONLINE = "video_online"  # 在线/加密视频 URL：阶段五（受限场景）
    VIDEO_ONLINE_ENUM = "video_online_enum"  # 账号/合集枚举（阶段五增强，方案 B）
    LIVE = "live"              # 直播链接录制（上游需求 P0）：阶段六
    CAPTURE = "capture"        # 视频采集设备摄取（上游需求 P1）：阶段六


@dataclass
class Segment:
    """带时间戳的片段（音频转录 / 视频文案的基本单位）。"""

    start: float  # 秒，相对整段素材
    end: float  # 秒
    text: str
    words: List[Dict[str, Any]] = field(default_factory=list)  # [{word,start,end,prob}]
    # D16/组件反馈 P0-②：校正版逐字稿——text 为校正后文本，raw_text 保留原始识别
    raw_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class ExtractResult:
    """标准输出契约对象（方案 §3.6 / 流程规范 §4.6，D11；D16 交付物范式）。

    双通道：
    - 纯文本通道：text（D16 后 = 纠正版稿件，可直接喂 summarize）。
    - 结构化通道：to_contract() 的字段（source/confidence/fields/media_ref/...）。
    D16 交付物范式：
    - raw_text：识别结果备查副本（单一，raw）；不另存多份独立副本。
    - corrected：纠正版稿件元数据（dict：text/notes/source/model/时间）；无纠正则为 None。
      text = 纠正版稿件（无纠正时即原始识别）；raw_text = 原始识别（备查）。
    """

    source: str  # ocr / vision / transcript
    text: str  # 纯文本主体（D16：纠正版稿件 / 交付物）
    confidence: Optional[float] = None  # 平均置信度 / 不确定项清单
    fields: Dict[str, Any] = field(default_factory=dict)  # 抽取关键字段（语言/时长等）
    media_ref: Dict[str, Any] = field(default_factory=dict)  # 来源文件/时间戳/页码，便于溯源
    referenced_frame: Optional[Dict[str, Any]] = None  # 视频专属（D13）
    provider_meta: Dict[str, Any] = field(default_factory=dict)  # D15 透明回显
    segments: List[Segment] = field(default_factory=list)  # 带时间戳片段（供 srt/txt 通道）
    # D16 交付物范式：原始识别（单一备查副本）与纠正版稿件（交付物）
    raw_text: Optional[str] = None   # 识别结果备查副本（单一，raw）；不另存多份
    corrected: Optional[Dict[str, Any]] = None  # 纠正版稿件元数据（见 modules.corrector），无则 None
    # 组件反馈 P0-②/P1-③：校正后的带时间戳片段 + 逐条改动清单（供逐字稿与校正过程文件落盘）
    corrected_segments: Optional[List[Segment]] = None  # text=校正后、raw_text=原始，时间码对齐
    correction_entries: Optional[List[Dict[str, Any]]] = None  # [{start, raw, corrected, kind}]

    def to_contract(self) -> Dict[str, Any]:
        """序列化为结构化通道字典（供 JSON / MD 输出 / 缓存）。

        segments 纳入契约：既是下游（翻译/对齐/知识库）拿时间戳的结构化通道，
        也保证哈希缓存命中后能完整还原带时间戳片段（否则 .srt 会因 segments 丢失而变空）。
        """
        return {
            "source": self.source,
            "text": self.text,            # 交付物：纠正版稿件（无纠正时即原始识别）
            "raw_text": self.raw_text,    # 识别结果备查副本（单一）
            "confidence": self.confidence,
            "fields": self.fields,
            "media_ref": self.media_ref,
            "referenced_frame": self.referenced_frame,
            "corrected": self.corrected,  # D16：纠正版稿件元数据
            "provider_meta": self.provider_meta,
            "segments": [seg.to_dict() for seg in self.segments],  # 带时间戳片段（音频/视频）
            # 组件反馈 P0-②/P1-③：校正后片段 + 逐条改动清单（进入契约，缓存可还原）
            "corrected_segments": [seg.to_dict() for seg in self.corrected_segments] if self.corrected_segments else None,
            "correction_entries": self.correction_entries,
        }


class InfoExtractError(Exception):
    """info-extract 统一异常，便于 router 区分「本技能可处理的失败」与系统错误。"""

    def __init__(self, message: str, *, recoverable: bool = True, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable  # True=用户可本地补充/换 provider 解决
        self.hint = hint  # 给用户的可执行建议


def contract_to_result(contract: Dict[str, Any]) -> "ExtractResult":
    """把缓存的 contract（to_contract 产出）还原为 ExtractResult（统一实现，避免各模块重复）。

    含 segments 重建（D12·L 缓存命中后仍保留带时间戳片段，供 .srt/.md 备查）；
    旧缓存缺 D16 字段（raw_text/corrected）时优雅回退 None。
    """
    segs = [
        Segment(
            start=s["start"], end=s["end"], text=s["text"],
            words=s.get("words", []),
            raw_text=s.get("raw_text"),
        )
        for s in contract.get("segments", [])
    ]
    corrected_segs = None
    if contract.get("corrected_segments"):
        corrected_segs = [
            Segment(
                start=s["start"], end=s["end"], text=s["text"],
                words=s.get("words", []),
                raw_text=s.get("raw_text"),
            )
            for s in contract["corrected_segments"]
        ]
    return ExtractResult(
        source=contract["source"],
        text=contract["text"],
        confidence=contract.get("confidence"),
        fields=contract.get("fields", {}),
        media_ref=contract.get("media_ref", {}),
        referenced_frame=contract.get("referenced_frame"),
        provider_meta=contract.get("provider_meta", {}),
        segments=segs,
        raw_text=contract.get("raw_text"),
        corrected=contract.get("corrected"),
        corrected_segments=corrected_segs,
        correction_entries=contract.get("correction_entries"),
    )


class IModule:
    """能力域模块统一接口（D8 按需载入）。

    主入口 router 仅做「类型识别 + 路由」，仅在命中某类型时才 import 对应模块、
    调用 run()。未命中类型不预载对应重型依赖（如 Whisper / VLM）。
    """

    name: str = ""
    source_type: str = ""
    # 是否已实现（阶段未到的能力域置 False，router 给出清晰提示而非静默失败，D9/D15）
    ready: bool = True

    def run(self, inputs: List[str], options: Dict[str, Any]) -> List[ExtractResult]:
        """处理一批同类型输入，返回 ExtractResult 列表。

        inputs：已校验存在的文件路径列表。
        options：来自 router 的全局选项（lang / task / model / provider / out_dir / ...）。
        """
        raise NotImplementedError


__all__ = [
    "SourceType",
    "Segment",
    "ExtractResult",
    "InfoExtractError",
    "IModule",
    "contract_to_result",
]
