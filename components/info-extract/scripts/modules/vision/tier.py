#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · VLM 模型档位自适应（D7，2026-08-27 决策）。

设计（呼应方案 §3 阶段四 / 资源评估 §4）：
- VLM 选型与默认量化档**不写死**，改为自适应：
  ① **安装时**探测系统配置（GPU 显存 / 统一内存 / CPU / 总 RAM）自动选「最优档」并落盘缓存
     （首次 install 时确定；缺失缓存时运行时探测兜底）。
  ② **运行时**每次调用前复探可用资源；若硬件变更（如外接/移除独显）或资源下降，
     自动下调一档（D7），并提示用户（§3.3 用户无感、仅被迫降级才告知）。
  ③ **用户覆盖**：始终允许手动指定档位（CLI `--vision-tier` 或环境变量）。
- 档位表（源自 `info-extract-资源评估.md` §4，列为「可选档位清单」而非固定默认）：
  轻量档(3B) / 标准档(7B) / 高性能档(7B-Q5) / 旗舰档(32B)。

纯标准库 + 轻量子进程探测；无 numpy/av 依赖，可在任意阶段安全 import。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 档位表：tier 升序。ollama_tag 为 ollama 拉取/运行的模型标签（量化由 ollama 自适应）。
TIERS: List[Dict] = [
    {"tier": 0, "name": "轻量档", "ollama_tag": "qwen2.5vl:3b", "min_ram_gb": 8, "vram_gb": 2,
     "note": "CPU / Apple 16GB 统一内存可跑（最慢）"},
    {"tier": 1, "name": "标准档", "ollama_tag": "qwen2.5vl:7b", "min_ram_gb": 16, "vram_gb": 5,
     "note": "8–12GB 独显（推荐甜点）"},
    {"tier": 2, "name": "高性能档", "ollama_tag": "qwen2.5vl:7b-q5_K_M", "min_ram_gb": 32, "vram_gb": 8,
     "note": "16GB+ 独显"},
    {"tier": 3, "name": "旗舰档", "ollama_tag": "qwen2.5vl:32b", "min_ram_gb": 64, "vram_gb": 20,
     "note": "多卡 / 数据中心"},
]

# 安装时缓存（scripts/.vision_tier.json），运行时用于检测「是否需下调一档」
CACHE_PATH = Path(__file__).resolve().parents[1] / ".vision_tier.json"

# 进程内资源探测缓存（避免逐帧重复 subprocess）
_RESOURCE_CACHE: Optional[Dict] = None


def probe_system_resources() -> Dict:
    """探测本机 RAM / VRAM / 是否 Apple 统一内存 / 是否有独显。best-effort，失败返回零值。"""
    global _RESOURCE_CACHE
    if _RESOURCE_CACHE is not None:
        return _RESOURCE_CACHE

    ram_gb = 0.0
    vram_gb = 0.0
    unified = False
    gpu = False

    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if out.isdigit():
                ram_gb = int(out) / 1024 ** 3
            brand = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            unified = "Apple" in brand
        elif sys.platform == "win32":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                ms = MEMORYSTATUSEX()
                ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                    ram_gb = ms.ullTotalPhys / 1024 ** 3
            except Exception:
                pass
        else:  # linux / other
            try:
                meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore")
                for line in meminfo.splitlines():
                    if line.startswith("MemTotal:"):
                        ram_gb = int(line.split()[1]) * 1024 / 1024 ** 3
                        break
            except Exception:
                pass
    except Exception:
        pass

    # VRAM：nvidia-smi（NVIDIA）；AMD/Intel 暂不探测，记 0（依赖 RAM 兜底）
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            vals = [int(x.strip()) for x in out.replace("MiB", "").splitlines() if x.strip().isdigit()]
            if vals:
                vram_gb = sum(vals) / 1024
                gpu = True
        except Exception:
            pass

    res = {"ram_gb": round(ram_gb, 1), "vram_gb": round(vram_gb, 1), "unified": unified, "gpu": gpu}
    _RESOURCE_CACHE = res
    return res


def _tier_by_resources(res: Dict) -> Dict:
    """按资源选最高可承载档位。有独显看 VRAM；无独显（纯 CPU / Apple 统一内存）看 RAM 兜底。"""
    ram = res["ram_gb"]
    vram = res["vram_gb"]
    if res["gpu"] and vram > 0:
        chosen = None
        for t in TIERS:
            if t["vram_gb"] <= vram and t["min_ram_gb"] <= ram + (vram if res["unified"] else 0):
                chosen = t
        return chosen or TIERS[0]
    # 无独显：统一内存 / 共享内存场景，避免盲目上 32B（极慢）；最高给到标准档
    if ram >= 16:
        return TIERS[1]
    if ram >= 8:
        return TIERS[0]
    # 资源极紧张也至少给最轻量档（让用户知道可用但会慢）
    return TIERS[0]


def _resolve_tier(spec) -> Optional[Dict]:
    """把手动指定（int 档位 / str 名称或 tag）解析为档位 dict。"""
    if spec is None:
        return None
    if isinstance(spec, int):
        for t in TIERS:
            if t["tier"] == spec:
                return t
        return None
    s = str(spec).strip().lower()
    for t in TIERS:
        if s in (t["ollama_tag"].lower(), t["name"].lower(), str(t["tier"])):
            return t
    return None


def detect_optimal_tier(manual=None) -> Dict:
    """探测最优档位：手动指定 > 环境变量 > 资源探测。返回档位 dict。"""
    if manual is not None:
        t = _resolve_tier(manual)
        if t:
            return t
    env = os.environ.get("INFO_EXTRACT_VISION_TIER")
    if env:
        t = _resolve_tier(env)
        if t:
            return t
    return _tier_by_resources(probe_system_resources())


def current_tier(manual=None) -> Dict:
    """当前生效档位（D7 自适应核心）：

    - 手动指定 → 直接返回（用户覆盖优先）。
    - 否则：安装时缓存的最优档为基线；运行时复探，若探测档位低于缓存（如独显被移除 /
      占用过高）则自动下调一档，并标记 downgraded，供上层提示用户（§3.3）。
    """
    if manual is not None:
        return detect_optimal_tier(manual)
    cached = load_cached_tier()
    detected = detect_optimal_tier()  # 无 manual / env
    if cached is None:
        return detected
    if detected["tier"] < cached["tier"]:
        d = dict(detected)
        d["_downgraded_from"] = cached["tier"]
        d["_downgraded"] = True
        return d
    return cached


def cache_tier(tier: Optional[Dict] = None) -> Dict:
    """安装时调用：把探测到的最优档落盘缓存。返回档位 dict。"""
    t = tier or detect_optimal_tier()
    try:
        CACHE_PATH.write_text(
            json.dumps({"tier": t["tier"], "tag": t["ollama_tag"], "name": t["name"]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return t


def load_cached_tier() -> Optional[Dict]:
    """读取安装时缓存的最优档。失败/缺失返回 None。"""
    try:
        if CACHE_PATH.exists():
            d = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            return _resolve_tier(d.get("tier") if d.get("tier") is not None else d.get("tag"))
    except Exception:
        pass
    return None


def sampling_profile(tier: Optional[Dict] = None) -> Dict:
    """帧采样自适应密度（审阅 F）：档位越高 → 关键帧越多、采样越密。"""
    t = tier or current_tier()
    table = {
        0: {"max_keyframes": 8, "interval_sec": 2.0},
        1: {"max_keyframes": 14, "interval_sec": 1.0},
        2: {"max_keyframes": 20, "interval_sec": 1.0},
        3: {"max_keyframes": 24, "interval_sec": 0.5},
    }
    return table.get(t["tier"], {"max_keyframes": 12, "interval_sec": 1.0})


__all__ = [
    "TIERS", "probe_system_resources", "detect_optimal_tier", "current_tier",
    "cache_tier", "load_cached_tier", "sampling_profile",
]
