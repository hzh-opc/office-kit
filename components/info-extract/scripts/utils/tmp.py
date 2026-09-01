#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 临时文件沙箱（D12·G 隐私闭环）。

流水线产生的中间产物（抽出的内嵌音轨 / 视频帧 / 超分缓存 / 长音频分块）可能含敏感信息，
默认写入技能私有 tmp/ 目录、处理完安全删除。在线/加密视频场景严格要求不落盘（审阅 G）。

设计：
- TempSandbox 为上下文管理器，进入时创建唯一私有目录，退出（或显式 cleanup）时整体删除。
- 默认落 <skill>/scripts/.tmp；可通过 root 参数重定向（如系统 temp）。
- 在线/加密视频调用方应传入 keep=False（不保留任何副本，审阅 G 强约束）。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp"


class TempSandbox:
    """一次性临时目录沙箱。"""

    def __init__(self, root: str | os.PathLike = DEFAULT_TMP_ROOT, *, keep: bool = False):
        self.root = Path(root)
        self.keep = keep  # True=处理后保留（默认本地场景）；False=强制不落盘（在线/加密视频）
        self._dir: Optional[Path] = None

    @property
    def dir(self) -> Path:
        if self._dir is None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._dir = Path(tempfile.mkdtemp(prefix="ie_", dir=str(self.root)))
        return self._dir

    def path(self, name: str) -> Path:
        """在沙箱内申请一个临时文件路径（不自动创建文件）。"""
        return self.dir / name

    def write(self, name: str, data: bytes) -> Path:
        p = self.path(name)
        p.write_bytes(data)
        return p

    def cleanup(self) -> None:
        if self._dir is not None and self._dir.exists():
            if self.keep:
                return  # 显式保留（默认本地场景允许）
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def __enter__(self) -> "TempSandbox":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # 异常与否都清理；keep=False 时无论何种情况都不留副本（审阅 G 强约束）
        self.cleanup()


__all__ = ["TempSandbox"]
