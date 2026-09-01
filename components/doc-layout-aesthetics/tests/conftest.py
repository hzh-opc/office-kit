# -*- coding: utf-8 -*-
"""pytest 共享配置：把 scripts/ 加入 sys.path，使测试可直接 import 构建脚本。"""
import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
