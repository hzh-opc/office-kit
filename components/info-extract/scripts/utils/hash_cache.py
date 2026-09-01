#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 结果哈希缓存（D12·L）。

基于输入文件哈希 + 关键选项哈希缓存抽取结果，重跑同文件跳过，避免重复算力。
隐私：缓存仅落本地私有目录（默认 <skill>/scripts/.cache），绝不外传（呼应 §4 隐私闭环）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    """分块读取大文件计算 sha256，避免一次性读入内存（长音频/视频友好）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(path: str) -> str:
    """对路径/URL 字符串本身求哈希（用于在线视频 URL 等「非本地文件」场景，D12·L）。"""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _is_file_path(path: str) -> bool:
    """判断 path 是否可当作本地文件求哈希（URL 或不存在的路径按字符串处理）。"""
    if path.startswith(("http://", "https://", "ftp://", "ftps://")):
        return False
    return os.path.isfile(path)


def _options_hash(options: dict) -> str:
    """对影响结果的关键选项求稳定哈希。

    调用方（各模块）传入的 options 应是「精选后影响结果的关键选项」集合：
    - audio/video：lang/task/model/provider/vad_threshold/min_silence_ms/container/vision_frames
    - ocr：ocr/force_ocr/preprocess/conf_threshold
    - vision：vision/ocr_coop/vision_tier/task
    - D16 纠正：context/correct_model/no_correct（影响纠正版稿件）
    此处对全部字段做稳定哈希、仅排除明确与结果无关的项（out_dir/use_cache 等），
    不做白名单过滤——避免新阶段新增选项漏配导致缓存错误命中、返回过期结果。
    """
    relevant = {
        k: v for k, v in options.items()
        if k not in ("out_dir", "use_cache")
    }
    blob = json.dumps(relevant, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResultCache:
    """本地结果缓存。key = sha256(文件) + 选项哈希；value = ExtractResult.to_contract()。"""

    def __init__(self, cache_dir: str | os.PathLike = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.cache_dir / "index.json"
        self._index = self._load_index()

    def _load_index(self) -> dict:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_index(self) -> None:
        self._index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def key(self, path: str, options: dict) -> str:
        # 在线视频等场景 path 为 URL（非本地文件）：对字符串求哈希，避免把 URL 当文件路径打开
        file_hash = sha256_file(path) if _is_file_path(path) else sha256_text(path)
        return f"{file_hash}:{_options_hash(options)}"

    def get(self, path: str, options: dict) -> Optional[dict]:
        k = self.key(path, options)
        entry = self._index.get(k)
        if not entry:
            return None
        result_path = self.cache_dir / f"{k}.json"
        if not result_path.exists():
            # 索引与文件不一致，清理索引
            self._index.pop(k, None)
            return None
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(self, path: str, options: dict, contract: dict) -> None:
        k = self.key(path, options)
        result_path = self.cache_dir / f"{k}.json"
        result_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._index[k] = {
            "source": path,
            "options_hash": _options_hash(options),
            "result": str(result_path),
        }
        self._save_index()


__all__ = ["sha256_file", "ResultCache"]
