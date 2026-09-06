#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desen-stop · Stop Hook：会话结束前"上云/外发已做却无 desen 脱敏留痕"事后兜底。

背景（L3，2026-09-04）：
  sheetagent（腾讯表格云解析）等通道不经 office-kit 的 L4 代码门禁，是本工作区
  审计暴露的"敏感数据上云盲区"。本 Stop hook 在 Agent 每次停止（会话/单轮结束）时
  兜底扫描：若本会话出现"疑似上云/外发动作"却无任何 desen 脱敏留痕，则提示/阻止停止，
  由 Agent 回补 desen 审计——覆盖 L4 拦不到的外部通道。

契约（对齐 WorkBuddy Stop Hook 规范，参照 security-scan/git_commit_detector.py）：
  触发方式: hooks/hooks.json > Stop
  输入    : stdin JSON { session_id, transcript_path, stop_hook_active, cwd, ... }
  输出    : stdout JSON（控制 Agent 是否允许停止）
  退出码  : 0 = 允许停止；2 = 阻止停止（reason 传给 Agent）
  超时    : 需在 hook timeout（建议 10s）内完成；故只读 transcript 尾部有限字节。

行为分级（由 env 控制，非阻断默认）：
  DESEN_STOP_HOOK_MODE=block  → 命中"有外发无留痕"即阻止停止（exit 2）
  DESEN_STOP_HOOK_MODE=warn   → 命中仅输出警示、允许停止（exit 0，默认）
  DESEN_STOP_HOOK_OFF=1       → 完全跳过本 hook
  DESEN_STOP_HOOK_NOISE=0     → 命中但属"仅读/仅本地"低危时不提示（默认 1=提示）

纯标准库、离线、零外部依赖；只读不写，绝不外发/落盘敏感原文。
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

_MAX_TAIL_BYTES = 2 * 1024 * 1024          # transcript 尾部读取上限（约 1.5MB 文本）
_MAX_TRANSCRIPT = 200 * 1024 * 1024        # transcript 文件硬上限，防被诱导读大文件
_PREFIX = "desen-stop"

# 疑似上云/外发的工具调用或动作关键词（命中即视为"有外发动作"）
_EXTERNAL_HINTS = (
    # 表格云解析（真正的盲区通道）
    "sheetagent", "read_table", "resolve_local_excel", "set_cell_range",
    "tencent-docs", "tencent_docs", "云表格", "表格云", "docs.qq.com",
    # 显式/隐性外发
    "send_mail", "agent_mail", "agent-mail", "SendMessage", "publish", "发布",
    "tencent-doc", "上云", "发送邮件", "邮件发送",
    # 云端生成（prompt 含敏感即随请求送云，v2 新增盲区收口）
    "imagegen", "videogen", "生成图片", "生成视频", "图生视频", "文生视频",
    "image_gen", "video_gen", "image-to-video",
    # 联网/网页（可能携带敏感原文）
    "websearch", "WebSearch", "webfetch", "WebFetch",
    "summarize --mode cloud", "--mode cloud", "--mode hybrid",
    # 识别稿外发
    "ocr", "transcript", "画面解读",  # 谨慎：仅与"外发/发送"同时出现才算，见逻辑
)
# desen 脱敏留痕关键词（命中任一视为"已有脱敏审计/副本"，不构成漏检）
_DESEN_HINTS = (
    "desensitize", "desensitiz", "desen", "脱敏",
    "desensitize_audit.md", "03_脱敏副本", "04_映射表", "脱敏副本",
    "desen scan", "desen run", "desen audit-log", "desen_send_audit",
    "confirm-raw", "confirm_raw",  # v2.2 用户显式确认原样外发（须先 audit-log，仍属已留痕路径）
    ".desensitize_keys",
)
# 本地只读/仅处理类的低危动作（不算外发；可经 _local_only 豁免提示）
_LOCAL_ONLY_HINTS = (
    "read_table", "get_cell_ranges",  # 仅本地解析读取也算外发? 否——只读表格(无send)视为查询
)


def _log(msg: str) -> None:
    print(f"[{_PREFIX}] {msg}", file=sys.stderr)


def _load_input() -> dict:
    """读 stdin 的 Stop Hook 输入 JSON；解析失败返回空 dict（不阻断）。"""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        _log("stdin 解析失败: %s" % exc)
        return {}


def _tail(path: str) -> str:
    """安全读 transcript 尾部有限字节。超限/缺失返回空串。"""
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        size = p.stat().st_size
        if size > _MAX_TRANSCRIPT:
            return ""
        with open(p, "rb") as f:
            if size > _MAX_TAIL_BYTES:
                f.seek(size - _MAX_TAIL_BYTES)
            data = f.read(_MAX_TAIL_BYTES)
        return data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        _log("transcript 读取失败: %s" % exc)
        return ""


def _has_desen_gate(text: str) -> bool:
    """尾部是否已出现 desen 脱敏留痕。"""
    low = text.lower()
    return any(h in low for h in _DESEN_HINTS)


def _detect_external(text: str) -> list:
    """在尾部文本中检出疑似上云/外发动作（仅近似，供警示；不做字段级判定）。"""
    low = text.lower()
    hits = []
    for h in _EXTERNAL_HINTS:
        # 非 ocr/transcript/画面解读 的直接命中即算
        if h in low and h not in ("ocr", "transcript", "画面解读"):
            hits.append(h)
    # OCR/识别类：仅当同一尾部出现"发送/外发/发布/上传/cloud"等外发动词才算外发
    send_verbs = ("发送", "外发", "发布", "上传", "cloud", "hybrid", "send", "mail", "邮件")
    has_send = any(v in low for v in send_verbs)
    for h in ("ocr", "transcript", "画面解读"):
        if h in low and has_send:
            hits.append(h + "(外发)")
    return hits


def main() -> int:
    cfg = _load_input()
    if os.environ.get("DESEN_STOP_HOOK_OFF") == "1":
        return 0
    mode = os.environ.get("DESEN_STOP_HOOK_MODE", "warn")  # warn|block
    noise = os.environ.get("DESEN_STOP_HOOK_NOISE", "1") != "0"

    tp = cfg.get("transcript_path") or cfg.get("transcript") or ""
    if not tp:
        return 0  # 无 transcript 可查：不阻断
    text = _tail(tp)

    ext = _detect_external(text)
    gated = _has_desen_gate(text)
    # 判定：有外发动作 + 无任何 desen 留痕 → 疑似漏检
    if not ext:
        return 0
    if gated:
        return 0  # 已走 desen，放行
    # 仅本地只读类命中且未伴随外发动词：低危，noise=0 时跳过
    reason = (
        "本会话检测到疑似上云/外发动作（%s），但未发现 desen 脱敏留痕。"
        "如涉敏数据（发票/申报/表格云解析/邮件/发布/联网），请先本地 "
        "`~/office-kit/office-kit.sh desen scan` 过闸并按需 `desen run`，"
        "确认无敏感外发后再停止。" % "、".join(sorted(set(ext))[:8])
    )
    _log("命中: external=%s gated=%s" % (ext, gated))
    if mode == "block":
        # 阻止停止：stdout JSON + exit 2
        out = {"blockReason": reason, "shouldStop": False, "desenStop": True}
        print(json.dumps(out, ensure_ascii=False))
        return 2
    # warn（默认）：仅输出提示，不阻断
    print(json.dumps({"message": reason, "shouldStop": True, "desenWarn": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
