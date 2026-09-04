#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""info-extract · 组件反馈整改（2026-09-02）精准回归测试。

覆盖本轮 7 个 commit 改动的纯标准库可测部分（无需重型运行时 / 无需联网）：
  - skill_bridge.py：SKILL_ROOTS 对称性（P1-①）、COOP_CAPS 数据驱动、document_text 删除（P2-①）
  - router.py：_venv_python 解析顺序（UV_PROJECT_ENVIRONMENT > VIRTUAL_ENV > .venv）
  - upgrade.py：parse_version / verify / apply（备份+原子替换+回滚）
  - assets/capabilities.json：coop_caps 结构
  - office-kit manifest.json：dependencies 含 desensitization-sop（P1-②）

运行（受管 python，纯标准库）：
  python3 -B tests/verify_feedback_fix.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import skill_bridge  # noqa: E402
import upgrade  # noqa: E402
from router import _venv_python  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ " + name)
    else:
        FAIL += 1
        print("  ❌ " + name + ("  " + detail if detail else ""))


# --------------------------------------------------------------------------- #
# A. skill_bridge.py
# --------------------------------------------------------------------------- #
print("\n[A] skill_bridge.py（P1-① 对称性 / P2-① document_text 删除 / coop_caps 数据驱动）")

# A1. 未设 OFFICE_KIT_ROOT 时，_skill_roots 不含 components
roots_default = skill_bridge._skill_roots()
check("未设 OFFICE_KIT_ROOT 时 _skill_roots 不含 components",
      not any(p.endswith("components") for p in roots_default))
check("未设 OFFICE_KIT_ROOT 时含 4 个标准 skills 目录",
      sum(1 for p in roots_default if p.rstrip("/").endswith("skills")) >= 4)

# A2. 设 OFFICE_KIT_ROOT 后，_skill_roots 纳入 components（P1-① 核心）
with mock.patch.dict(os.environ, {"OFFICE_KIT_ROOT": "/tmp/office-kit"}):
    roots_kit = skill_bridge._skill_roots()
    check("设 OFFICE_KIT_ROOT 后 _skill_roots 纳入 components",
          any(p.endswith(os.path.join("office-kit", "components")) or
              p.endswith("components") for p in roots_kit))
    check("设 OFFICE_KIT_ROOT 后 components 指向该根",
          any("/tmp/office-kit/components" in p for p in roots_kit))

# A3. document_text 已删除（P2-①）
check("COOP_CAPS 不含 document_text（已删除）", "document_text" not in skill_bridge.COOP_CAPS)
check("COOP_CAPS 仅含 desensitization + browser",
      set(skill_bridge.COOP_CAPS.keys()) == {"desensitization", "browser"})

# A4. COOP_CAPS 数据驱动：与 assets/capabilities.json 的 coop_caps 一致
caps = json.loads((REPO / "assets" / "capabilities.json").read_text(encoding="utf-8"))
check("COOP_CAPS 与 capabilities.json coop_caps 数据一致",
      skill_bridge.COOP_CAPS == caps.get("coop_caps"))

# A5. self_check 在 mock 环境正确检出 desensitization / browser
tmp = Path(tempfile.mkdtemp())
(tmp / "desensitization-sop").mkdir()
(tmp / "browser-skill").mkdir()
with mock.patch.object(skill_bridge, "SKILL_ROOTS", [str(tmp)]):
    res = skill_bridge.self_check()
    check("mock 环境 self_check 检出 desen", res["desensitization"] == "desensitization-sop")
    check("mock 环境 self_check 检出 browser", res["browser"] == "browser-skill")

# A6. 防误判：仅匹配目录名关键词；a-stock-data（SKILL.md 含文档/网页）不被误判
tmp2 = Path(tempfile.mkdtemp())
(tmp2 / "a-stock-data").mkdir()
with mock.patch.object(skill_bridge, "SKILL_ROOTS", [str(tmp2)]):
    res2 = skill_bridge.self_check()
    check("a-stock-data 不被误判为 desen（仅目录名匹配）", res2["desensitization"] is None)
    check("a-stock-data 不被误判为 browser", res2["browser"] is None)

# A7. has_desensitization 返回 bool
check("has_desensitization 返回 bool", isinstance(skill_bridge.has_desensitization(), bool))

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)


# --------------------------------------------------------------------------- #
# B. router.py · _venv_python 解析顺序
# --------------------------------------------------------------------------- #
print("\n[B] router.py · _venv_python 解析顺序（UV > VIRTUAL_ENV > .venv）")

def _fake_venv(parent: Path, rel: str) -> Path:
    """造一个含 bin/python 的假 venv 目录，供 _venv_python 命中 is_file。"""
    v = parent / rel
    (v / "bin").mkdir(parents=True)
    (v / "bin" / "python").write_text("#!/bin/sh\n")
    return v


# B1. UV_PROJECT_ENVIRONMENT 优先（造真实假文件，否则 is_file 不命中）
root1 = Path(tempfile.mkdtemp())
uv_dir = _fake_venv(root1, "uv_env")
with mock.patch.dict(os.environ, {"UV_PROJECT_ENVIRONMENT": str(uv_dir), "VIRTUAL_ENV": "/no/such/virt"}):
    p = _venv_python()
    check("UV_PROJECT_ENVIRONMENT 优先解析", p is not None and str(uv_dir) in str(p))
shutil.rmtree(root1, ignore_errors=True)

# B2. 仅 VIRTUAL_ENV 次之
root2 = Path(tempfile.mkdtemp())
virt_dir = _fake_venv(root2, "virt_env")
with mock.patch.dict(os.environ, {}, clear=True):
    os.environ["VIRTUAL_ENV"] = str(virt_dir)
    p = _venv_python()
    check("仅 VIRTUAL_ENV 时解析到它", p is not None and str(virt_dir) in str(p))
shutil.rmtree(root2, ignore_errors=True)

# B3. 回退 scripts/.venv（构造假 bin/python）
fake_root = Path(tempfile.mkdtemp())
fake_venv = fake_root / "scripts" / ".venv"
(fake_venv / "bin").mkdir(parents=True)
(fake_venv / "bin" / "python").write_text("#!/bin/sh\n")
with mock.patch.dict(os.environ, {}, clear=True), \
        mock.patch.object(sys.modules["router"], "SCRIPT_DIR", fake_root / "scripts"):
    p = _venv_python()
    check("回退到 scripts/.venv", p is not None and "scripts/.venv" in str(p))
shutil.rmtree(fake_root, ignore_errors=True)

# B4. 三者皆无且 .venv 不存在 → 返回 None
with mock.patch.dict(os.environ, {}, clear=True), \
        mock.patch.object(sys.modules["router"], "SCRIPT_DIR", Path(tempfile.mkdtemp())):
    p = _venv_python()
    check("无候选环境时返回 None", p is None)


# --------------------------------------------------------------------------- #
# C. upgrade.py
# --------------------------------------------------------------------------- #
print("\n[C] upgrade.py（parse_version / verify / apply 备份+回滚）")

# C1. parse_version 多种格式
check("parse_version('0.6.3') == (0,6,3)", upgrade.parse_version("0.6.3") == (0, 6, 3))
check("parse_version('v1.2') == (1,2)", upgrade.parse_version("v1.2") == (1, 2))
check("parse_version('\"2.0\"') == (2,0)", upgrade.parse_version('"2.0"') == (2, 0))
check("parse_version('') is None", upgrade.parse_version("") is None)
check("parse_version('abc') is None（纯非数字垃圾输入返回 None，避免误判已最新）", upgrade.parse_version("abc") is None)
check("parse_version('1.2.3.4') == (1,2,3,4)", upgrade.parse_version("1.2.3.4") == (1, 2, 3, 4))

# C2. read_local_version 读真实 VERSION
lv = upgrade.read_local_version()
check("read_local_version 读到真实版本", lv is not None and len(lv.split(".")) >= 2)

# C3. verify 语法编译通过 / 失败
good_root = Path(tempfile.mkdtemp())
(good_root / "scripts").mkdir()
(good_root / "scripts" / "x.py").write_text("print('ok')\n")
check("verify 语法编译通过返回 True", upgrade.verify(good_root) is True)

bad_root = Path(tempfile.mkdtemp())
(bad_root / "scripts").mkdir()
(bad_root / "scripts" / "y.py").write_text("print('ok'\n")  # 语法错误
check("verify 语法编译失败返回 False", upgrade.verify(bad_root) is False)
shutil.rmtree(good_root, ignore_errors=True)
shutil.rmtree(bad_root, ignore_errors=True)

# C4. apply 备份 + 原子替换成功（临时目录，不碰真实仓库）
base = Path(tempfile.mkdtemp())
live = base / "info-extract"
live.mkdir()
(live / "VERSION").write_text("0.6.3")
staged = base / "staged"
staged.mkdir()
(staged / "VERSION").write_text("0.7.0")
ok_apply = upgrade.apply(live, staged)
check("apply 成功返回 True", ok_apply is True)
check("apply 后 live 为新版本", (live / "VERSION").read_text() == "0.7.0")
check("apply 后 staged 已被消费（原子 rename）", not staged.exists())
check("apply 后备份目录已生成", any(p.name.startswith("info-extract.backup.") for p in base.iterdir()))
shutil.rmtree(base, ignore_errors=True)

# C5. apply 替换失败自动回滚（mock os.rename 让原子替换抛错）
base2 = Path(tempfile.mkdtemp())
live2 = base2 / "info-extract"
live2.mkdir()
(live2 / "VERSION").write_text("0.6.3")
staged2 = base2 / "staged"
staged2.mkdir()
(staged2 / "VERSION").write_text("0.7.0")
real_rename = os.rename


def _side_effect(src, dst):
    if "staged" in str(src):  # 第二次 rename（staged -> skill_dir）模拟失败
        raise OSError("simulated atomic replace failure")
    real_rename(src, dst)  # 第一次 rename（skill_dir -> backup）真实执行


raised = False
with mock.patch.object(upgrade.os, "rename", _side_effect):
    try:
        upgrade.apply(live2, staged2)
    except OSError:
        raised = True
check("apply 替换失败抛异常", raised)
check("回滚后 live 恢复旧版本 0.6.3", (live2 / "VERSION").read_text() == "0.6.3")
check("回滚后 staged 未被消费", staged2.exists())
shutil.rmtree(base2, ignore_errors=True)


# --------------------------------------------------------------------------- #
# D. assets/capabilities.json
# --------------------------------------------------------------------------- #
print("\n[D] assets/capabilities.json（coop_caps 结构）")
check("capabilities.json 为合法 JSON", isinstance(caps, dict))
coop = caps.get("coop_caps")
check("含 coop_caps 字段", isinstance(coop, dict) and bool(coop))
check("coop_caps 含 desensitization", "desensitization" in coop)
check("coop_caps 含 browser", "browser" in coop)
check("coop_caps 值为 [str,...]", all(isinstance(v, list) and v and all(isinstance(k, str) for k in v) for v in coop.values()))


# --------------------------------------------------------------------------- #
# E. office-kit manifest.json（P1-②）
# --------------------------------------------------------------------------- #
print("\n[E] office-kit · components/info-extract/manifest.json（P1-② dependencies）")
mf = Path("/Users/hzh/Repositories/office-kit/components/info-extract/manifest.json")
if mf.exists():
    m = json.loads(mf.read_text(encoding="utf-8"))
    check("manifest.json 为合法 JSON", True)
    check("dependencies 含 desensitization-sop（P1-②）", "desensitization-sop" in m.get("dependencies", []))
    check("version 字段存在", bool(m.get("version")))
else:
    check("manifest.json 存在", False, "路径: " + str(mf))


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print("\n" + "=" * 56)
print("通过 {}/{}  ·  失败 {}".format(PASS, PASS + FAIL, FAIL))
print("=" * 56)
sys.exit(1 if FAIL else 0)
