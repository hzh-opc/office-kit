#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 输出落盘公共工具（组件反馈 P0-①/P1-④）。

提供各能力域 output 层共用的：
- 交付区/存档区分区逻辑（P0-①）：默认拆「交付/存档」两子目录，--flat-out 降级平铺。
- 敏感信息轻量预检封装（P1-④）：对识别稿文本做只读扫描，供交付卡片提示。

设计：纯标准库，不引入重型依赖；脱敏动作仍归 DESEN，此处只检测 + 提示。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

# 交付区 / 存档区子目录名（P0-① 分区方案）
DELIVER_DIR = "交付"
ARCHIVE_DIR = "存档"

# 环境变量：平铺降级开关（router --flat-out 时置 "1"；使无 options 的调用点也能生效）
FLAT_OUT_ENV = "INFO_EXTRACT_FLAT_OUT"


def resolve_flat_out(flat_out: Optional[bool] = None) -> bool:
    """解析平铺降级开关：显式参数优先，其次环境变量（INFO_EXTRACT_FLAT_OUT=1），默认分区。"""
    if flat_out is not None:
        return bool(flat_out)
    return os.environ.get(FLAT_OUT_ENV) == "1"


def resolve_output_dirs(
    out_dir: str | Path,
    flat_out: Optional[bool] = None,
) -> Tuple[Path, Path]:
    """返回 (交付区路径, 存档区路径)。

    flat_out（或环境变量 INFO_EXTRACT_FLAT_OUT=1）为真时两者均为 out_dir 本身（平铺降级）。
    分区模式下：交付区=out_dir/交付，存档区=out_dir/存档。
    """
    out_dir = Path(out_dir)
    if resolve_flat_out(flat_out):
        return out_dir, out_dir
    deliver = out_dir / DELIVER_DIR
    archive = out_dir / ARCHIVE_DIR
    return deliver, archive


def detect_pii(result_text: str) -> Optional[Dict[str, object]]:
    """对识别稿文本做敏感信息轻量预检（P1-④）。

    返回 scan_summary 结果（{total, kinds:[...]}）或 None（无文本时）。
    检测失败（理论上不抛，纯标准库）时静默返回 None，不阻断落盘。
    """
    if not result_text:
        return None
    try:
        from modules.pii_scan import scan_summary  # 延迟导入，避免启动开销
        summary = scan_summary(result_text)
        return summary if summary.get("total") else None
    except Exception:
        return None


__all__ = ["resolve_output_dirs", "detect_pii", "DELIVER_DIR", "ARCHIVE_DIR"]
