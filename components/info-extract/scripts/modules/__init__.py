#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 能力域模块包（按需载入，D8）。

各能力域为独立模块，主入口 router 仅按命中类型 import 对应模块（未命中不预载重型依赖）。
"""

from modules.base import SourceType  # noqa: F401

__all__ = ["SourceType"]
