#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video-to-content-pack · 机械步 CLI（跨平台，纯标准库 + 套件 venv 已有依赖）

定位
----
本工作流的**机械环节**（建目录、来源归一化、记录链索引、帧 OCR、去边、切片、
清单导出、交付物渲染、外发扫描、机械校验）由此 CLI 承担，由工作流契约
`workflow.json` 以 `uses: {"script": "tools/vcp.py", "args": [...]}` 声明、runner
用套件 venv 解释器执行。

为什么不做成 shell 步
--------------------
历史契约用 POSIX shell 实现这些步骤（`mkdir -p` / `cp -n` / `[ -n ]`），而 runner
以 `subprocess(shell=True)` 执行——在 Windows 上是 `cmd.exe`，这些方言全部失败，
与蓝本「跨平台」的宣称冲突。改为 Python 脚本后：跨平台一致、可断点续跑、
退出码语义明确、产物可校验。

解释器与依赖
------------
由 runner 用**套件虚拟环境**（`OFFICE_KIT_ROOT/.venv`，套件唯一真相源）执行，
故可直接使用 `PIL`（去边 / 帧去重）、`imageio_ffmpeg`（内置静态 ffmpeg，
裁切与录制）、`av`。三者均已在套件 venv 内，**不需要** media 隔离环境。
缺失时明确报错并给安装指引，不静默降级。

输出与状态
----------
所有机器可读记录落 `<WORKSPACE>/_work/<节名>/`（工作记录链，蓝本 §0.4）；
人类可读产物落 `<WORKSPACE>/课程交付/` 与 `<WORKSPACE>/按章节/<节名>/`（蓝本 §7）。

退出码：0 成功 / 2 用法错误 / 3 业务失败（含需用户确认的外发阻断）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

VIDEO_EXTS = [".mp4", ".mkv", ".mov", ".m4v", ".webm", ".flv", ".ts", ".avi", ".wmv", ".mpg", ".mpeg"]
TEXT_DELIVER_EXTS = {".md", ".txt", ".csv"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
# 课程级汇总产物（**跨节**内容，文件名不带章节号）。
# 节级过滤时一律排除——否则「单节拆解执行」会把别节内容计进本节：
# 计数虚高、门禁假报，严重时「别节的敏感内容阻断本节外发」。
COURSE_LEVEL_FILES = frozenset({
    "README.md", "00_课程总览_索引.md",
    "小节视频清单.csv", "产品切片清单.csv", "文案汇总.md", "小节视频索引.md",
})
# 交付文档形态（与蓝本 §0.5 一致）
DELIVERABLE_TYPES = {"讲义", "文档", "参考文档", "教程", "知识点汇总", "文案"}
SOURCE_ENUM = {"file", "online", "live", "live_fallback", "device", "device_fallback"}
GRANULARITY_ENUM = {"none", "transcript", "catalog", "product"}
GRANULARITY_DIR = {"transcript": "小节_按转录", "catalog": "小节_按目录", "product": "小节_按产品"}
ON_OFF = {"on", "off"}

KIT_ROOT = Path(os.environ.get("OFFICE_KIT_ROOT") or Path(__file__).resolve().parents[3])
KIT_PY = Path(os.environ.get("OFFICE_KIT_PY") or sys.executable)

# 帧文件名解析（info-extract 命名约定）
RE_D13_FRAME = re.compile(r"^frame_(\d+)_(\d+)\.png$")            # frame_0006_00.png → 6.00s
RE_KEYFRAME = re.compile(r"^.+_kf_\d+_(\d+)\.png$")               # <stem>_kf_001_600.png → 6.00s
RE_MD_IMG = re.compile(r"!\[[^\]]*\]\(<?([^)>]+)>?\)")
# 截图命名约定（蓝本 §0.5/§2.2/§3.7）：第NN节_图MM_中文短描述.{png|jpg}，章号/图号零填充
RE_SHOT_NAME = re.compile(r"^第(\d{2,3})节_图(\d{2,3})_(.+)\.(png|jpe?g)$", re.I)
# 视频时间锚点（蓝本 §3.1）：▶ **MM:SS** / ▶ **HH:MM:SS**
RE_ANCHOR = re.compile(r"▶\s*\*{0,2}\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*\*{0,2}")
# 转录成品逐字稿的行首时间码（info-extract 输出格式：`[MM:SS] 文本`；无 ▶ 时的兜底锚点源）
RE_TS_LINE = re.compile(r"^\s*\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]\s*")
RE_MD_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
# 章节号提取（容忍 第7章 / 第07章 / 第7节 三种写法）；组2＝单位字（章|节）
RE_CHAPTER = re.compile(r"^\s*第\s*(\d+)\s*([章节])")
# 「有意义的 OCR 文本」判据：至少 1 个汉字，或 2 个以上连续英数。
# 纯图/构图页 OCR 常只吐标点噪声（如 `_\n_\n_`），这类不算「可核对」，
# 否则文件名↔画面核对会大面积假告警（W10 门禁可信度前提）。
RE_MEANINGFUL = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]{2,}")
# 自动汇总区标记（consolidate 幂等改写，绝不覆盖人工内容）
INDEX_BEGIN = "<!-- vcp:auto-index:begin -->"
INDEX_END = "<!-- vcp:auto-index:end -->"

# 通用小标题（画面多半只写课程/课件名，不含这类词）——命中失败时不作「漂移」结论，避免误报
GENERIC_HEADINGS = frozenset({"开场", "引言", "前言", "介绍", "导入", "概述", "正文", "结语", "结束",
                              "收尾", "导论", "引入", "背景", "本节", "本课"})

# 关键词停用词（锚点/命名核对时过滤口语与结构词）
_STOP = frozenset("""
的 了 是 和 与 在 有 我 你 他 她 它 这 那 一个 我们 你们 他们 就是 什么 怎么 可以 这个 那个
然后 因为 所以 但是 如果 已经 还是 不是 没有 时候 这样 一样 非常 其实 大家 可能 需要 知道 看到
觉得 东西 问题 视频 课程 本节 这一 一张 第一 第二 第三 以及 而且 只是 还有 比如 例如 那么 这么
一些 一下 部分 内容 图片 截图 例子 情况 时候 地方 上面 下面 里面 出来 起来 进去 一下
""".split())


class VcpError(Exception):
    """业务失败（退出码 3）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise VcpError("记录文件损坏，无法解析：%s（%s）" % (path, exc)) from exc


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rel_ws(ws: Path, p) -> str:
    """路径相对工作区的展示写法；口径不一致时回退绝对路径，绝不抛错。

    典型触发：macOS `/tmp` 与 `/private/tmp`（realpath 口径）、软链工作区——`ws`
    已 `resolve()`，而记录（如 `cut_manifest.json` 的 `dest_dir`）可能是未解析写法，
    直接 `relative_to` 会抛 `ValueError` 让整个 export 步崩掉；这本属展示层可容错之事。
    """
    p = Path(p)
    try:
        return str(p.relative_to(ws))
    except ValueError:
        pass
    try:
        return str(p.resolve().relative_to(ws))
    except (ValueError, OSError):
        return str(p)


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 共用文本 / 图像判据（配图分类、锚点核对、命名一致性共用，2026-09-23 新增）
# ---------------------------------------------------------------------------

def chapter_digits(name: str) -> str:
    """取字符串里的章节号（去前导零）；用于跨零填充写法匹配同名章节。

    `第7章_用光` / `第07章_图01_x.jpg` → `"7"`；无章节号 → `""`。
    """
    m = RE_CHAPTER.match(name or "")
    return (m.group(1).lstrip("0") or "0") if m else ""


def section_prefix(section: str) -> str:
    """节级产物文件名前缀 `第NN节_`（章号零填充到 2 位，与 W2 命名铁律同口径）。

    `第7节` / `第07章` → `第07节_`；无章节号 → `<section>_`。用于把「节级产物」
    与「课程级汇总产物」在**同一平铺目录**里区分开（单节拆解执行的前提）。
    """
    m = RE_CHAPTER.match(section or "")
    if not m:
        return ("%s_" % section) if section else ""
    return "第%02d%s_" % (int(m.group(1)), m.group(2))


def tokens(text: str) -> list:
    """抽取关键词候选：中文连续串（≥2 字）+ 英文/数字词（≥2 字符），去停用词。"""
    out = []
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_&+.-]{1,}", text or ""):
        t = m.group(0).strip("、，。：；！？·()（）【】[]《》\"'")
        if len(t) < 2 or t in _STOP or t.isdigit():
            continue
        out.append(t)
    return out


def kw_hit(kw: str, text: str) -> bool:
    """关键词命中判定：整词子串命中；长词（≥5 字）另允许 3 字窗口命中（容忍 OCR 噪声）。"""
    if not kw or not text:
        return False
    if kw in text:
        return True
    if len(kw) >= 5:
        return any(text.find(kw[i:i + 3]) >= 0 for i in range(len(kw) - 2))
    return False


def ocr_lines(text: str) -> list:
    """把 OCR 文本切成「行」：兼容 `\\n`（boxes_to_text）与 ` | `（历史工程脚本）。"""
    raw = text or ""
    parts = raw.split("\n") if "\n" in raw else raw.split(" | ")
    return [p.strip() for p in parts if p and p.strip()]


def ink_ratio(path: Path, size: int = 96, quant: int = 32, dist: int = 60) -> float:
    """画面「墨量」＝与主色差异显著的像素占比（0~1）。

    用途：区分「纯文字幻灯片」（底色占绝对多数、墨量低）与「含照片/图解的画面」
    （墨量高）。96×96 缩放后固定 9216 像素；用 `tobytes()` 取原始字节（不依赖
    Pillow 已弃用的 `getdata()`，Pillow 12 实测无告警）。
    """
    from PIL import Image  # type: ignore
    from collections import Counter
    im = Image.open(path).convert("RGB").resize((size, size))
    raw = im.tobytes()
    q = Counter((raw[i] // quant, raw[i + 1] // quant, raw[i + 2] // quant)
                for i in range(0, len(raw), 3))
    bg0 = q.most_common(1)[0][0]
    bg = (bg0[0] * quant, bg0[1] * quant, bg0[2] * quant)
    diff = 0
    for i in range(0, len(raw), 3):
        if (abs(raw[i] - bg[0]) + abs(raw[i + 1] - bg[1]) + abs(raw[i + 2] - bg[2])) > dist:
            diff += 1
    return diff / (size * size)


def parse_anchors(md_text: str) -> list:
    """解析逐字稿里的视频时间锚点。

    两种来源：① 修正版约定 `▶ **MM:SS**` / `▶ **HH:MM:SS**`（蓝本 §3.1）；
    ② 无 ▶ 时退回转录成品的行首时间码 `[MM:SS] 文本`（info-extract 输出格式）。
    每条记录：`time_sec` / `timecode` / `heading`（最近一个 Markdown 标题，作
    「锚点核心关键词」来源）/ `body`（锚点同行或紧随正文，作辅助关键词来源）/
    `mode`（`arrow`＝有标题可依，`ts`＝仅正文、关键词精度较低）。
    """
    lines = (md_text or "").splitlines()
    mode = "arrow" if RE_ANCHOR.search(md_text or "") else "ts"
    head_at, cur = {}, ""
    for i, ln in enumerate(lines):
        m = RE_MD_HEAD.match(ln)
        if m:
            cur = m.group(2).strip()
        head_at[i] = cur
    out = []
    for i, ln in enumerate(lines):
        m = RE_TS_LINE.match(ln) if mode == "ts" else RE_ANCHOR.search(ln)
        if not m:
            continue
        h, mm, ss = m.group(1), m.group(2), m.group(3)
        t = (int(h) * 3600 if h else 0) + int(mm) * 60 + int(ss)
        body = ln[m.end():].strip(" *|　-—")
        if not body:
            body = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
        out.append({
            "time_sec": t,
            "timecode": ("%02d:" % int(h) if h else "") + "%02d:%02d" % (int(mm), int(ss)),
            "heading": head_at.get(i, ""),
            "body": body[:120],
            "line_no": i + 1,
            "mode": mode,
        })
    return out


def sec_only(files, digits: str, *, drop_course_level: bool = False) -> list:
    """按章节号过滤文件列表——用于**多节共用的平铺目录**（`课程交付/*`）。

    规则：带章节号的文件只保留与本节同号者；不带章节号的（无法判归属）一律保留，
    除非 `drop_course_level=True`（节级隔离场景下排除课程级汇总产物）。
    **不可**写成「匹配为空则返回全部」——那会让多节工作区里各节互相吞并
    （实测 第08节 误计 第07节 的 4 张配图 / 误把别节逐字稿当锚点文档）。
    """
    files = sorted(files, key=lambda p: str(getattr(p, "name", p)))
    if not digits:
        return files
    hit = [p for p in files if chapter_digits(p.name) == digits]
    plain = [p for p in files if not chapter_digits(p.name)]
    if drop_course_level:
        plain = [p for p in plain if p.name not in COURSE_LEVEL_FILES]
    return hit + plain


def collect_records(rec_dir: Path, kind: str, digits: str = "") -> list:
    """列出某节在交付目录下的文件（按章节号过滤）。

    匹配规则见 `sec_only`：**带章节号的文件**只保留与本节同号的；**不带章节号的
    文件**（如 `讲义.md`）无法判归属，一律保留——这是「无章节号时按全部」的
    可解释形态。
    """
    if not rec_dir.is_dir():
        return []
    files = [p for p in rec_dir.glob(kind) if p.is_file()]
    return sec_only(files, digits)


class Ctx:
    """工作区路径集合（蓝本 §7 目录结构的唯一实现处）。"""

    def __init__(self, workspace: str, section: str):
        if not workspace:
            raise VcpError("缺少 --workspace（内容工作区根目录必填）")
        self.ws = Path(workspace).expanduser().resolve()
        self.section = section or "第1节"
        self.work = self.ws / "_work" / self.section
        self.chapter = self.ws / "按章节" / self.section
        self.deliver = self.ws / "课程交付"
        self.sub_transcript = self.deliver / "逐字稿_修正版"
        self.sub_doc = self.deliver / "讲义"
        self.shots = self.deliver / "讲义截图"
        self.shots_text = self.deliver / "讲义截图_文字页替代"
        self.shots_bak = self.deliver / "讲义截图_原始备份"
        self.pdf = self.deliver / "PDF"
        self.dig = chapter_digits(self.section)     # 本节章节号（去前导零）
        self.sec_prefix = section_prefix(self.section)  # 节级产物文件名前缀 第NN节_

    def all_dirs(self):
        return [
            self.work,
            self.chapter,
            self.deliver,
            self.sub_transcript,
            self.sub_doc,
            self.shots,
            self.shots_text,
            self.shots_bak,
            self.pdf,
        ] + [self.chapter / d for d in GRANULARITY_DIR.values()]

    # 记录链路径
    def rec(self, name: str) -> Path:
        return self.work / name

    # ── 节级视图（「单节拆解执行」的全部入口；平铺目录一律经此过滤，禁止裸 glob/iterdir）──

    def mine(self, files) -> list:
        """按本节章节号过滤任意文件列表（course-level 汇总产物一并排除）。"""
        return sec_only(files, self.dig, drop_course_level=True)

    def _files(self, d: Path, exts=None) -> list:
        if not d.is_dir():
            return []
        out = [p for p in d.iterdir() if p.is_file()]
        if exts:
            out = [p for p in out if p.suffix.lower() in exts]
        return self.mine(out)

    def transcripts(self) -> list:
        """本节的修正版逐字稿（`课程交付/逐字稿_修正版/`）。"""
        return self._files(self.sub_transcript, (".md",))

    def docs(self) -> list:
        """本节的交付文档（`课程交付/讲义/`）。"""
        return self._files(self.sub_doc, (".md",))

    def shots_files(self) -> list:
        """本节的交付截图（`讲义截图/` 下 png/jpg，去边后的成品图）。"""
        return self._files(self.shots, IMAGE_EXTS)

    def shots_text_files(self) -> list:
        """本节的纯文字页替代原图（`讲义截图_文字页替代/`，不得被交付文档引用）。"""
        return self._files(self.shots_text, IMAGE_EXTS)

    def pdfs(self) -> list:
        """本节的精排 PDF（`课程交付/PDF/`）。"""
        return self._files(self.pdf, (".pdf",))

    def deliver_files(self) -> list:
        """本节在 `课程交付/` 下的全部交付文件（含子目录，按节过滤）。

        供外发扫描等「按节界定外发面」的场景使用；课程级汇总产物被排除，
        避免「别节的敏感内容阻断本节」。
        """
        if not self.deliver.is_dir():
            return []
        return self.mine([p for p in self.deliver.rglob("*") if p.is_file()])

    def find_anchor_doc(self, explicit: str = "") -> tuple:
        """定位含视频时间锚点的逐字稿：显式指定 > 修正版逐字稿 > 转录成品逐字稿。

        返回 `(Path | None, 来源说明)`。修正版在 `课程交付/逐字稿_修正版/`，
        成品逐字稿在 `_work/<节>/交付/`——两处都按章节号匹配本节的文档
        （兼容 `第7章` 与 `第07章` 两种零填充写法）。
        """
        if explicit:
            p = Path(explicit).expanduser()
            if not p.is_file():
                raise VcpError("指定的锚点文档不存在：%s" % explicit)
            return p, "显式指定"
        d = chapter_digits(self.section)
        for base, tag in ((self.sub_transcript, "修正版逐字稿"),
                          (self.work / "交付", "转录成品逐字稿")):
            hit = collect_records(base, "*.md", d)
            if hit:
                return hit[0], tag
        return None, ""


def kit_call(args, *, capture=True, check=False):
    """通过 kit.py 调用套件命令（保留外发必扫 DESEN 闸门等统一策略）。

    脚本内**不**直接 subprocess 组件入口——那样会绕过 kit.py 的外发门禁与
    入口校验（历史缺陷：工作流内 extract 未经 DESEN 扫描）。
    """
    cmd = [str(KIT_PY), str(KIT_ROOT / "kit.py")] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace", check=check)


def resolve_ffmpeg(explicit: str = "") -> tuple[str, str]:
    """解析 ffmpeg 可执行文件。返回 (路径, 来源说明)。

    探测顺序：① --ffmpeg-bin/param 显式指定 → ② 套件 venv 的 imageio_ffmpeg
    （内置静态二进制，本机实测可用）→ ③ media 隔离环境（历史兼容，可选）
    → ④ 系统 PATH。全部落空则明确报错 + 三选一指引，不静默失败。
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return str(p), "参数 ffmpeg_bin"
        w = shutil.which(explicit)
        if w:
            return w, "参数 ffmpeg_bin（PATH 命中）"
        raise VcpError("指定的 ffmpeg 不存在：%s" % explicit)

    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe, "套件 venv 的 imageio_ffmpeg"
    except Exception:  # noqa: BLE001
        pass

    for cand in (
        Path.home() / ".workbuddy/binaries/python/envs/media/bin/python",
        Path.home() / ".workbuddy/binaries/python/envs/media/Scripts/python.exe",
    ):
        if not cand.is_file():
            continue
        try:
            out = subprocess.run(
                [str(cand), "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=30,
            )
            exe = (out.stdout or "").strip()
            if exe and Path(exe).is_file():
                return exe, "media 环境的 imageio_ffmpeg"
        except Exception:  # noqa: BLE001
            continue

    w = shutil.which("ffmpeg")
    if w:
        return w, "系统 PATH 的 ffmpeg"

    raise VcpError(
        "未找到 ffmpeg。三选一：\n"
        "  ① 指定二进制：--param ffmpeg_bin=/path/to/ffmpeg\n"
        "  ② 依赖套件 venv 内置 ffmpeg（重装依赖：cd %s && ./bootstrap.sh）\n"
        "  ③ 安装到系统 PATH（macOS: brew install ffmpeg）" % KIT_ROOT
    )


# ---------------------------------------------------------------------------
# 子命令：precheck
# ---------------------------------------------------------------------------

def cmd_precheck(a) -> int:
    errors, warns = [], []

    if not a.workspace:
        errors.append("--workspace 必填（内容工作区根目录）")
    if a.source not in SOURCE_ENUM:
        errors.append("source=%s 非法；可选：%s" % (a.source, " | ".join(sorted(SOURCE_ENUM))))
    if a.granularity not in GRANULARITY_ENUM:
        errors.append("granularity=%s 非法；可选：%s" % (a.granularity, " | ".join(sorted(GRANULARITY_ENUM))))
    for key, val in (("copywriting", a.copywriting), ("digest", a.digest),
                     ("desen_gate", a.desen_gate)):
        if val not in ON_OFF:
            errors.append("%s=%s 非法；可选 on | off" % (key, val))
    if a.deliverable_render not in ("off", "pdf"):
        errors.append("deliverable_render=%s 非法；可选 off | pdf" % a.deliverable_render)
    if a.cloud_upload not in ("off", "tencent"):
        errors.append("cloud_upload=%s 非法；可选 off | tencent" % a.cloud_upload)

    types = [t.strip() for t in (a.deliverable_types or "").split(",") if t.strip()]
    if not types:
        errors.append("deliverable_types 不能为空（可选：%s）" % " / ".join(sorted(DELIVERABLE_TYPES)))
    for t in types:
        if t not in DELIVERABLE_TYPES:
            errors.append("deliverable_types 含未知形态 `%s`；可选：%s"
                          % (t, " / ".join(sorted(DELIVERABLE_TYPES))))

    if a.source in SOURCE_ENUM and not (a.source_uri or "").strip():
        hint = {
            "file": "本地视频文件路径",
            "online": "自媒体/在线视频 URL",
            "live": "直播 URL",
            "live_fallback": "直播 URL",
            "device": "设备描述符，如 avfoundation:1:0（macOS）/ USB Video（Windows）/ /dev/video0（Linux）",
            "device_fallback": "设备描述符，同 device",
        }.get(a.source, "来源地址")
        errors.append("source=%s 时必须提供 source_uri（%s）" % (a.source, hint))
    if a.source == "file" and a.source_uri:
        p = Path(a.source_uri).expanduser()
        if not p.is_file():
            errors.append("source=file 但文件不存在：%s" % p)

    if a.whisper_model and a.whisper_model not in (
            "tiny", "base", "small", "medium", "large-v3", "turbo"):
        errors.append("whisper_model=%s 非法；可选 tiny/base/small/medium/large-v3/turbo（留空=组件默认 small）"
                      % a.whisper_model)

    # ffmpeg：仅在确需时才硬要求（录制降级 / 切片）
    need_ffmpeg = a.source in ("live_fallback", "device_fallback") or a.granularity != "none"
    ffmpeg, ff_src = "", ""
    if need_ffmpeg or a.ffmpeg_bin:
        try:
            ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)
        except VcpError as exc:
            if need_ffmpeg:
                errors.append(str(exc))
            else:
                warns.append(str(exc))
    else:
        try:
            ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)
        except VcpError:
            warns.append("未解析到 ffmpeg（当前参数组合用不到；如需录制降级/切片请先解决）")

    # 运行解释器自检：脚本步由 runner 用套件 venv 解释器执行，这里校验「当前解释器」
    # 是否真的具备本工作流依赖（比检查固定 .venv 目录更准确——套件允许 venv 位于
    # 部署副本 ~/office-kit/.venv，而开发副本通常不自建 .venv）。
    if not (KIT_ROOT / "kit.py").is_file():
        errors.append("kit.py 未找到（OFFICE_KIT_ROOT=%s 是否正确？）" % KIT_ROOT)
    missing_mods = []
    for mod, why in (("PIL", "截图去边 / 帧去重"), ("imageio_ffmpeg", "内置静态 ffmpeg（录制降级与切片）")):
        try:
            __import__(mod)
        except ImportError:
            missing_mods.append("%s（%s）" % (mod, why))
    if missing_mods:
        errors.append(
            "当前解释器缺少依赖：%s\n     解释器=%s\n     → 脚本步须由套件 venv 解释器执行"
            "（如 %s/.venv/bin/python）；如确为套件 venv 仍缺，请运行 ./bootstrap.sh 补齐"
            % ("；".join(missing_mods), sys.executable, KIT_ROOT))
    warns.append("运行解释器：%s" % sys.executable)

    ctx = Ctx(a.workspace or ".", a.section)
    ctx.work.mkdir(parents=True, exist_ok=True)
    ctx.rec("run_context.json")  # 触发父目录创建

    ctx_obj = {
        "workflow": "video-to-content-pack",
        "generated_at": now_iso(),
        "workspace": str(ctx.ws),
        "section": ctx.section,
        "params": {
            "source": a.source, "source_uri": a.source_uri, "granularity": a.granularity,
            "copywriting": a.copywriting, "digest": a.digest,
            "deliverable_types": types, "deliverable_render": a.deliverable_render,
            "cloud_upload": a.cloud_upload, "desen_gate": a.desen_gate,
            "whisper_model": a.whisper_model or "small(组件默认)", "device_duration": a.device_duration,
        },
        "env": {
            "office_kit_root": str(KIT_ROOT),
            "kit_python": str(KIT_PY),
            "ffmpeg": ffmpeg,
            "ffmpeg_source": ff_src,
        },
    }
    write_json(ctx.rec("run_context.json"), ctx_obj)

    for w in warns:
        log("  ⚠ %s" % w)
    if errors:
        log("✗ 入参/环境校验未通过：")
        for e in errors:
            log("  · %s" % e)
        return 3
    log("  ✓ 入参与环境校验通过（ffmpeg=%s；%s）" % (ffmpeg or "未解析（当前用不到）", ff_src or "—"))
    log("  ✓ 运行上下文已落盘：%s" % ctx.rec("run_context.json"))
    return 0


# ---------------------------------------------------------------------------
# 子命令：mkdirs
# ---------------------------------------------------------------------------

def cmd_mkdirs(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    for d in ctx.all_dirs():
        d.mkdir(parents=True, exist_ok=True)
    log("  ✓ 目录骨架就绪（%d 个）：%s" % (len(ctx.all_dirs()), ctx.ws))
    for d in ctx.all_dirs():
        log("      %s" % d.relative_to(ctx.ws))
    return 0


# ---------------------------------------------------------------------------
# 子命令：ingest（本地文件归一化）
# ---------------------------------------------------------------------------

def cmd_ingest(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    src = Path(a.source_uri).expanduser().resolve()
    if not src.is_file():
        raise VcpError("来源文件不存在：%s" % src)
    ext = src.suffix.lower() or ".mp4"
    dst = ctx.chapter / ("%s%s" % (ctx.section, ext))
    ctx.chapter.mkdir(parents=True, exist_ok=True)
    if src == dst:
        log("  ✓ 来源已在归一化目录，无需复制：%s" % dst)
        return 0

    def _same(p: Path) -> bool:
        try:
            return p.stat().st_size == src.stat().st_size
        except OSError:
            return False

    if dst.exists() and not _same(dst):
        # 幂等重跑：内容不同才覆盖（避免重复消耗大文件 IO）
        shutil.copy2(src, dst)
        log("  ✓ 已覆盖归一化：%s" % dst)
    elif not dst.exists():
        shutil.copy2(src, dst)
        log("  ✓ 已归一化：%s → %s" % (src, dst))
    else:
        log("  ✓ 归一化文件已存在且大小一致，跳过复制：%s" % dst)
    return 0


# ---------------------------------------------------------------------------
# 子命令：record-live / record-device（降级路径：先录制为本地文件）
# ---------------------------------------------------------------------------

def _record(ctx: Ctx, ffmpeg: str, extra_in: list, out_name: str, duration: int, *, copy: bool) -> int:
    out = ctx.chapter / out_name
    ctx.chapter.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-nostdin"] + extra_in
    # 直播流是无损转封装（-c copy）；采集设备是原始信号，必须编码
    cmd += ["-c", "copy"] if copy else [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
    ]
    if duration and duration > 0:
        cmd += ["-t", str(int(duration))]
    cmd += [str(out)]
    log("  ▶ %s" % " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc != 0 or not out.is_file():
        raise VcpError(
            "录制失败（ffmpeg rc=%s）。常见原因：URL/设备不可达、需登录态（请改走原生路径 "
            "`kit extract <URL> --live --cookies-from-browser chrome`）、或设备被占用。"
            "产物未生成：%s" % (rc, out))
    log("  ✓ 已录制：%s（%.1f MB）" % (out, out.stat().st_size / 1024 / 1024))
    return 0


def cmd_record_live(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    ffmpeg, src = resolve_ffmpeg(a.ffmpeg_bin)
    log("  · ffmpeg=%s（%s）" % (ffmpeg, src))
    return _record(ctx, ffmpeg, ["-i", a.source_uri], "%s.mkv" % ctx.section, a.device_duration, copy=True)


def cmd_record_device(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    ffmpeg, src = resolve_ffmpeg(a.ffmpeg_bin)
    dev = a.source_uri
    # 设备描述符可带后端前缀（与 info-extract 约定一致）：avfoundation:1:0 / dshow:USB Video / v4l2:/dev/video0
    backend, sep, target = dev.partition(":")
    if not sep or backend not in ("avfoundation", "dshow", "v4l2", "decklink"):
        if sys.platform == "darwin":
            backend, target = "avfoundation", dev
        elif sys.platform.startswith("win"):
            backend, target = "dshow", dev
        else:
            backend, target = "v4l2", dev
    if backend == "dshow":
        extra = ["-f", "dshow", "-i", "video=%s" % target]
    elif backend == "decklink":
        extra = ["-f", "decklink", "-i", target]
    else:
        extra = ["-f", backend, "-i", target]
    log("  · 设备后端=%s，目标=%s" % (backend, target))
    return _record(ctx, ffmpeg, extra, "%s.mkv" % ctx.section, a.device_duration, copy=False)


# ---------------------------------------------------------------------------
# 子命令：transcribe（经 kit.py 调用组件，保留统一外发闸门）
# ---------------------------------------------------------------------------

def _find_normalized(ctx: Ctx) -> Path:
    """定位本节的归一化源视频（§1.1 各来源归一后的落点）。"""
    cands = [p for p in sorted(ctx.chapter.glob("%s.*" % ctx.section)) if p.suffix.lower() in VIDEO_EXTS]
    if not cands:
        cands = [p for p in sorted(ctx.chapter.glob("*")) if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not cands:
        raise VcpError(
            "未找到归一化源视频：%s/%s.<视频扩展名>。请先确认摄取步成功"
            "（source=live/device 原生路径由组件边录边转，无需本步）。" % (ctx.chapter, ctx.section))
    prio = {e: i for i, e in enumerate(VIDEO_EXTS)}
    cands.sort(key=lambda p: prio.get(p.suffix.lower(), 99))
    return cands[0]


def cmd_transcribe(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    src_video = _find_normalized(ctx)
    args = ["extract", str(src_video), "--out", str(ctx.work)]
    if a.whisper_model:
        args += ["--model", a.whisper_model]
    log("  ▶ kit %s" % " ".join(args))
    proc = kit_call(args, capture=False)
    if proc.returncode != 0:
        raise VcpError(
            "转录失败（kit extract rc=%s）。若为模型下载失败：受限网络可用本地缓存并设 "
            "HF_HUB_OFFLINE=1；或改用 whisper.cpp（WHISPER_CPP_BIN/WHISPER_CPP_MODEL）。" % proc.returncode)
    # 产物即时报验：不静默成功
    n_arch = len(list((ctx.work / "存档").glob("*.json"))) if (ctx.work / "存档").is_dir() else 0
    if not n_arch:
        raise VcpError("转录结束但未发现结构化产物（%s/存档/*.json），请检查上方日志。" % ctx.work)
    log("  ✓ 转录产物已落盘（存档/ 下 %d 个 json）" % n_arch)
    return 0


# ---------------------------------------------------------------------------
# 子命令：index-records（记录链索引：ingestion_manifest / transcript_meta / frame_index）
# ---------------------------------------------------------------------------

def _img_signature(path: Path, size: int = 16):
    """帧指纹：16×16 灰度缩略（用于近似重复判定）。

    为何不用 aHash/dHash：课程/直播画面多为「大面积纯底 + 少量元素」的幻灯片，
    均值哈希会因纯底占绝对多数而把不同帧哈希成同一个值（实测：两张内容不同的
    幻灯片 aHash 距离 = 0）。改为**逐像素平均绝对差（MAD）**，在同类画面上区分度
    明显更好（实测：完全相同帧 MAD=0.0，内容不同帧 MAD≥3.8）。
    """
    from PIL import Image  # type: ignore
    return list(Image.open(path).convert("L").resize((size, size)).getdata())


def _mad(a, b) -> float:
    """两个指纹的平均绝对差（0=完全相同）。"""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _dedup(frames: list, threshold: float) -> int:
    """原地标记重复帧（dup_of + dup_mad）。返回去重后保留数。

    判据保守：仅把「视觉几乎完全相同」的帧判重，保证选帧时仍有足够候选
    （相似度只是筛子不是裁判——配图规范 §六 通用铁律）。
    """
    kept, kept_sig = [], []
    for f in frames:
        sig = f.get("_sig")
        best, best_mad = None, None
        for k, ksig in zip(kept, kept_sig):
            d = _mad(ksig, sig)
            if best_mad is None or d < best_mad:
                best, best_mad = k, d
        if best is not None and best_mad is not None and best_mad <= threshold:
            f["selected"] = False
            f["dup_of"] = best["frame_id"]
            f["dup_mad"] = round(best_mad, 2)
        else:
            f["selected"] = True
            kept.append(f)
            kept_sig.append(sig)
    return len(kept)


def cmd_index_records(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    rc = read_json(ctx.rec("run_context.json"), {}) or {}
    params = rc.get("params", {})

    arch_dir = ctx.work / "存档"
    contracts = []
    for p in sorted(arch_dir.glob("*.json")) if arch_dir.is_dir() else []:
        if p.name.endswith(".correction.json"):
            continue
        try:
            contracts.append((p.stem, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            continue
    if not contracts:
        raise VcpError("未发现转录契约（%s/*.json）。请先完成 transcribe 或原生摄取。" % arch_dir)

    items, all_frames = [], []
    for stem, c in contracts:
        fields = c.get("fields") or {}
        dur = fields.get("duration_sec") or 0
        segs = c.get("segments") or []
        deliver = ctx.work / "交付"
        item = {
            "stem": stem,
            "duration_sec": round(float(dur), 2) if dur else 0.0,
            "language": fields.get("detected_language") or fields.get("language") or "",
            "segments_count": len(segs),
            "confidence": c.get("confidence"),
            "provider": (c.get("provider_meta") or {}).get("provider", ""),
            "srt": str(arch_dir / ("%s.srt" % stem)) if (arch_dir / ("%s.srt" % stem)).is_file() else "",
            "json": str(arch_dir / ("%s.json" % stem)),
            "txt": str(deliver / ("%s.txt" % stem)) if (deliver / ("%s.txt" % stem)).is_file()
                   else (str(deliver / ("%s.raw.txt" % stem)) if (deliver / ("%s.raw.txt" % stem)).is_file() else ""),
            "md": str(deliver / ("%s.md" % stem)) if (deliver / ("%s.md" % stem)).is_file() else "",
            "correction_md": str(arch_dir / ("%s.correction.md" % stem))
                             if (arch_dir / ("%s.correction.md" % stem)).is_file() else "",
            "degraded_no_correction": (deliver / ("%s.raw.txt" % stem)).is_file(),
        }
        # 帧目录（D13 讲解段帧免费产出；--vision 时另有 keyframes）
        fr_dirs = [d for d in (ctx.work / ("%s_frames" % stem), ctx.work / ("%s_keyframes" % stem)) if d.is_dir()]
        item["frame_dirs"] = [str(d) for d in fr_dirs]
        items.append(item)

        # 段文本（供帧定位说明）：segment_start/end → text
        seg_text = {}
        for s in segs:
            try:
                seg_text[(round(float(s["start"]), 2), round(float(s["end"]), 2))] = (s.get("text") or "").strip()
            except Exception:  # noqa: BLE001
                continue

        for d in fr_dirs:
            is_kf = d.name.endswith("_keyframes")
            for png in sorted(d.glob("*.png")):
                m = RE_KEYFRAME.match(png.name) if is_kf else RE_D13_FRAME.match(png.name)
                ts = None
                if m:
                    # D13：frame_<整秒:04d>_<百分秒:02d>.png → 6 + 0.00；关键帧：..._kf_<序号>_<ts*100>.png
                    ts = (int(m.group(1)) / 100.0) if is_kf else (int(m.group(1)) + int(m.group(2)) / 100.0)
                all_frames.append({
                    "frame_id": "%s/%s" % (d.name, png.name),
                    "path": str(png),
                    "kind": "keyframe" if is_kf else "d13",
                    "stem": stem,
                    "timestamp_sec": ts,
                    "size_bytes": png.stat().st_size,
                    "segment_text": "",
                    "ocr_text": "",
                    "ocr_head": "",
                    "selected": True,
                    "dup_of": None,
                    "_hash": None,
                })
        # 回填 D13 帧所在段文本
        for fr in all_frames:
            if fr["kind"] != "d13" or fr["stem"] != stem:
                continue
            rf = (c.get("referenced_frame") or {}).get("frames") or []
            for r in rf:
                try:
                    if abs(float(r.get("timestamp", -1)) - (fr["timestamp_sec"] or -1)) < 0.01:
                        fr["segment_text"] = (r.get("segment_text") or "").strip()
                        fr["ocr_text"] = r.get("ocr_on_frame") or ""
                        break
                except Exception:  # noqa: BLE001
                    continue

    # 帧去重（16×16 灰度 MAD；与组件关键帧的 phash 去重互补，覆盖 D13 段帧）
    warn_img = ""
    try:
        from PIL import Image  # noqa: F401  # type: ignore
        for f in all_frames:
            try:
                f["_sig"] = _img_signature(Path(f["path"]))
            except Exception:  # noqa: BLE001
                f["_sig"] = None
        kept = _dedup(all_frames, a.dup_mad)
    except ImportError:
        kept = len(all_frames)
        warn_img = "（未安装 Pillow，跳过帧去重；请确认套件 venv 完整）"

    for f in all_frames:
        f.pop("_sig", None)
        if f["ocr_text"]:
            f["ocr_head"] = f["ocr_text"][:60]

    # 归一化源文件
    src_file = ""
    try:
        src_file = str(_find_normalized(ctx))
    except VcpError:
        for p in sorted(ctx.work.glob("*")):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                src_file = str(p)
                break

    primary = items[0] if items else {}
    write_json(ctx.rec("transcript_meta.json"), {
        "section": ctx.section,
        "generated_at": now_iso(),
        "primary_stem": primary.get("stem"),
        "duration_sec": primary.get("duration_sec"),
        "items": items,
        "note": "本文件是转录产物的轻量索引（原 transcript_meta.json 曾指向不存在的产物，2026-09-22 起改为"
                "由 存档/<stem>.json 抽取；时间戳与段落的唯一真源仍是 存档/<stem>.srt 与 存档/<stem>.json）。",
    })
    write_json(ctx.rec("ingestion_manifest.json"), {
        "section": ctx.section,
        "source_type": params.get("source", ""),
        "source_uri": params.get("source_uri", ""),
        "method": {
            "file": "本地文件归一化（--param source=file）",
            "online": "info-extract 在线下载+转录（yt-dlp）",
            "live": "info-extract 直播原生摄取（边录边转）",
            "live_fallback": "media/套件 ffmpeg 先录制为本地回放，再转录",
            "device": "info-extract 采集设备原生摄取（边采边转）",
            "device_fallback": "套件 ffmpeg 设备后端先采集为本地文件，再转录",
        }.get(params.get("source", ""), "未知（请人工补记）"),
        "normalized_file": src_file,
        "duration_sec": primary.get("duration_sec"),
        "fetched_at": now_iso(),
        "compliance": "仅处理用户有权访问的内容；批量抓取遵守平台 ToS 并默认限速；"
                      "直播/设备录制产物留存于本工作区，留存与销毁由用户负责。",
    })
    write_json(ctx.rec("frame_index.json"), {
        "section": ctx.section,
        "generated_at": now_iso(),
        "source": "info-extract D13 讲解段帧（转录时免费产出）+ --vision 关键帧（如已启用）",
        "dedup": "16×16 灰度平均绝对差（MAD ≤ %.1f 判重；组件关键帧另有 phash 去重，两者互补）" % a.dup_mad
                 + "——判据保守，保证选帧时仍有足够候选",
        "total": len(all_frames),
        "selected": sum(1 for f in all_frames if f["selected"]),
        "frames": all_frames,
    })

    log("  ✓ 转录契约 %d 份；帧 %d 张（去重后保留 %d 张）%s"
        % (len(contracts), len(all_frames), kept, warn_img))
    log("  ✓ 已落盘：transcript_meta.json / ingestion_manifest.json / frame_index.json")
    if not all_frames:
        log("  ⚠ 未发现任何帧：该视频可能无「讲解画面」指代（D13 未命中）。"
            "如需更多画面素材，可对源视频显式启用画面解读：kit extract <视频> --vision --out %s" % ctx.work)
    return 0


# ---------------------------------------------------------------------------
# 子命令：digest（summarize 接入：速览/关键词，供 authoring 写「本节速览」）
# ---------------------------------------------------------------------------

def cmd_digest(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json")) or {}
    items = meta.get("items") or []
    if not items:
        raise VcpError("缺少 transcript_meta.json（请先执行 index-records）")

    out = {"section": ctx.section, "generated_at": now_iso(), "provider": "summarize（本地抽取式，零上云）",
           "items": []}
    for it in items:
        txt = it.get("txt") or ""
        if not txt or not Path(txt).is_file():
            out["items"].append({"stem": it.get("stem"), "skipped": "无可用文本（交付区 .txt 缺失）"})
            continue
        tmp = ctx.work / ("_digest_%s.json" % it["stem"])
        proc = kit_call(["summarize", txt, "--keywords", str(a.keywords),
                         "--format", "json", "--out", str(tmp)])
        data = read_json(tmp, None) if tmp.is_file() else None
        if proc.returncode != 0 or not data:
            out["items"].append({"stem": it.get("stem"), "skipped": "summarize 失败（rc=%s）" % proc.returncode})
            continue
        out["items"].append({
            "stem": it["stem"],
            "tldr": data.get("tldr") or "",
            "summary": data.get("summary") or "",
            "keywords": data.get("keywords") or [],
            "keyword_weights": data.get("keyword_weights") or {},
            "sentences": [s.get("text") for s in (data.get("chosen_sentences") or [])],
        })
        try:
            tmp.unlink()
        except OSError:
            pass

    write_json(ctx.rec("digest.json"), out)
    ok = sum(1 for i in out["items"] if not i.get("skipped"))
    log("  ✓ 摘要/关键词已落盘：digest.json（成功 %d/%d 节）" % (ok, len(out["items"])))
    return 0


# ---------------------------------------------------------------------------
# 子命令：frames-ocr（逐帧独立子进程 + 断点续跑，防内存累积 OOM）
# ---------------------------------------------------------------------------

def cmd_frames_ocr(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    idx = read_json(ctx.rec("frame_index.json"))
    if idx is None:
        raise VcpError("缺少 frame_index.json（请先执行 index-records）")
    frames = idx.get("frames") or []
    selected = [f for f in frames if f.get("selected")]
    if not selected:
        log("  · 无可 OCR 的帧（frame_index 为空或无选中帧），跳过")
        write_json(ctx.rec("ocr_review.json"), {"section": ctx.section, "generated_at": now_iso(),
                                                "items": [], "note": "无选中帧"})
        return 0

    ocr_root = ctx.work / "frames_ocr"
    ocr_root.mkdir(parents=True, exist_ok=True)
    review, done, cached, failed = [], 0, 0, 0
    for f in selected:
        fid = f["frame_id"].split("/")[-1].rsplit(".", 1)[0]
        out_dir = ocr_root / fid
        arch = out_dir / "存档" / ("%s.json" % fid)
        if arch.is_file():
            cached += 1
        else:
            # subprocess-per-image：每图独立进程，避免单进程反复初始化推理引擎导致 OOM（配图规范 §六-8）
            proc = kit_call(["extract", f["path"], "--type", "ocr", "--out", str(out_dir)])
            if proc.returncode != 0 or not arch.is_file():
                failed += 1
                review.append({"frame_id": f["frame_id"], "hit": False, "ocr_text": "",
                               "score": None, "num_boxes": None,
                               "error": "OCR 失败（rc=%s）" % proc.returncode})
                continue
            done += 1
        data = read_json(arch, {}) or {}
        text = (data.get("text") or data.get("raw_text") or "").strip()
        fields = data.get("fields") or {}
        score = data.get("confidence", fields.get("avg_confidence"))
        review.append({"frame_id": f["frame_id"], "hit": bool(text), "ocr_text": text,
                       "ocr_head": text[:60], "score": score,
                       "num_boxes": fields.get("num_boxes"), "error": ""})
        f["ocr_text"] = text
        f["ocr_head"] = text[:60]

    write_json(ctx.rec("ocr_review.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "note": "hit 仅代表「该帧 OCR 有文本输出」；是否命中预期锚点属语义判断，"
                "在 frame_pick（选帧归位）步由 Agent/用户复核。",
        "items": review, "stats": {"total": len(selected), "new": done, "cached": cached, "failed": failed},
    })
    write_json(ctx.rec("frame_index.json"), idx)  # 回写 ocr_text / ocr_head
    log("  ✓ OCR 复核完成：共 %d 帧（新算 %d / 命中缓存 %d / 失败 %d）→ ocr_review.json"
        % (len(selected), done, cached, failed))
    if failed:
        log("  ⚠ %d 帧 OCR 失败，已在 ocr_review.json 标记 error，未静默放过" % failed)
    return 0


# ---------------------------------------------------------------------------
# 子命令：crop（截图去边，保守算法）
# ---------------------------------------------------------------------------

def _crop_one(path: Path, pad: int, keep_min: float, max_side: int):
    """估算内容边界并保守裁剪；返回 (裁剪框, 保留面积比) 或 None（无需/不宜裁剪）。"""
    from PIL import Image, ImageChops  # type: ignore
    im = Image.open(path).convert("RGB")
    w, h = im.size
    gray = im.convert("L")

    # 以四边内侧 3% 采样估背景灰度；仅当边缘为「近纯色暗底」才裁
    px = gray.load()
    samples = []
    for x in range(0, w, max(1, w // 200)):
        samples += [px[x, 0], px[x, 1], px[x, h - 2]]
    for y in range(0, h, max(1, h // 200)):
        samples += [px[0, y], px[1, y], px[w - 2, y]]
    if not samples:
        return None
    bg = sum(samples) / len(samples)
    if bg > 60:  # 边缘不是暗底 → 没有可裁的黑边
        return None
    # 标准差护栏：纯色带才裁，避免误裁暗调画面
    var = sum((s - bg) ** 2 for s in samples) / len(samples)
    if var > 400:  # std > 20
        return None

    mask = gray.point(lambda v: 255 if v > max(40, bg + 18) else 0)
    bbox = mask.getbbox()
    if not bbox:
        return None
    l, t, r, b = bbox
    l, t = max(0, l - pad), max(0, t - pad)
    r, b = min(w, r + pad), min(h, b + pad)
    box_w, box_h = r - l, b - t
    if box_w <= 0 or box_h <= 0:
        return None
    # 保守护栏：保留面积 ≥ keep_min；单边裁掉不超过 max_side px
    if (box_w * box_h) / float(w * h) < keep_min:
        return None
    if l > max_side or t > max_side or (w - r) > max_side or (h - b) > max_side:
        return None
    if (l, t, r, b) == (0, 0, w, h):
        return None
    im.crop((l, t, r, b)).save(path)
    return (l, t, r, b), round((box_w * box_h) / float(w * h), 3)


def cmd_crop(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if not ctx.shots.is_dir():
        raise VcpError("截图目录不存在：%s（请先完成 frame_pick 的命名归位）" % ctx.shots)
    try:
        import PIL  # noqa: F401  # type: ignore
    except ImportError as exc:
        raise VcpError("缺少 Pillow，无法去边。请补依赖：cd %s && ./bootstrap.sh（%s）" % (KIT_ROOT, exc)) from exc

    ctx.shots_bak.mkdir(parents=True, exist_ok=True)
    manifest, cropped, skipped = [], 0, 0
    mine = ctx.shots_files()   # 只处理**本节**截图：缺此过滤会重裁别节已裁好的图并污染 crop_manifest
    if not mine:
        log("  ⚠ `%s` 下未发现本节（%s）截图，去边步无操作——请确认 frame_pick 已按节命名归位"
            % (ctx.shots.name, ctx.section))
    for src in mine:
        bak = ctx.shots_bak / src.name
        if not bak.exists():          # 先备份原图（幂等：已备份不覆盖）
            shutil.copy2(src, bak)
        try:
            res = _crop_one(src, a.pad, a.keep_min, a.max_side)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"file": src.name, "cropped": False, "error": str(exc), "keep_ratio": None})
            skipped += 1
            continue
        if res is None:
            manifest.append({"file": src.name, "cropped": False, "box": None, "keep_ratio": 1.0})
            skipped += 1
        else:
            box, ratio = res
            manifest.append({"file": src.name, "cropped": True, "box": list(box), "keep_ratio": ratio})
            cropped += 1

    write_json(ctx.rec("crop_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "algorithm": "边缘背景灰度估计 → 前景掩码 → 内容边界+pad；护栏：保留面积 ≥%.2f、单边裁掉 ≤%dpx、"
                     "边缘须为近纯色暗底（std ≤20）" % (a.keep_min, a.max_side),
        "backup_dir": str(ctx.shots_bak),
        "items": manifest,
        "stats": {"total": len(manifest), "cropped": cropped, "unchanged": skipped},
    })
    log("  ✓ 去边完成：共 %d 张（实际裁剪 %d / 保持原样 %d）→ crop_manifest.json" % (len(manifest), cropped, skipped))
    log("      原图备份：%s" % ctx.shots_bak)
    return 0


# ---------------------------------------------------------------------------
# 子命令：cut（按 cut_plan.json 执行切片；增量重切）
# ---------------------------------------------------------------------------

def cmd_cut(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    plan = read_json(ctx.rec("cut_plan.json"))
    if not plan:
        raise VcpError("缺少 cut_plan.json（裁切计划是唯一真源，请先完成 cut_plan 步）")
    granularity = plan.get("granularity") or a.granularity
    out_dir = ctx.chapter / GRANULARITY_DIR.get(granularity, "小节_按转录")
    out_dir.mkdir(parents=True, exist_ok=True)

    src = Path(plan.get("source_video") or "").expanduser()
    if not src.is_file():
        try:
            src = _find_normalized(ctx)
        except VcpError as exc:
            raise VcpError("源视频不可用：%s（cut_plan.source_video=%s）"
                           % (exc, plan.get("source_video"))) from exc
    src_sha = sha256_file(src)
    ffmpeg, ff_src = resolve_ffmpeg(a.ffmpeg_bin)

    prev = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    prev_map = {i.get("filename"): i for i in (prev.get("items") or [])}

    items, cut, reused = [], 0, 0
    for seg in plan.get("segments") or []:
        fn = seg.get("filename")
        if not fn:
            raise VcpError("cut_plan 段缺少 filename 字段（第 %s 段）" % seg.get("idx"))
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        if end <= start:
            raise VcpError("cut_plan 段时间区间非法：%s（%.2f→%.2f）" % (fn, start, end))
        dst = out_dir / fn
        old = prev_map.get(fn)
        same = (old and old.get("src_sha256") == src_sha
                and abs(float(old.get("start", -1)) - start) < 0.01
                and abs(float(old.get("end", -1)) - end) < 0.01
                and dst.is_file())
        if same:
            reused += 1
        else:
            # 临时文件名保留真实扩展名（ffmpeg 靠扩展名推断容器格式，`.mp4.part` 会直接失败）
            tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
            cmd = [ffmpeg, "-y", "-nostdin", "-ss", "%.3f" % start, "-to", "%.3f" % end,
                   "-i", str(src), "-c", "copy", "-avoid_negative_ts", "make_zero", str(tmp)]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            rc = proc.returncode
            if rc != 0 or not tmp.is_file():
                # stream-copy 失败（关键帧/容器不兼容等）→ 回退重编码，保证段可用（不静默）
                cmd2 = [ffmpeg, "-y", "-nostdin", "-ss", "%.3f" % start, "-to", "%.3f" % end,
                        "-i", str(src), "-c:v", "libx264", "-crf", "20", "-c:a", "aac", str(tmp)]
                proc2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8", errors="replace")
                rc2 = proc2.returncode
                if rc2 != 0 or not tmp.is_file():
                    tail = "\n".join((proc.stderr or "").strip().splitlines()[-4:]
                                     + (proc2.stderr or "").strip().splitlines()[-4:])
                    raise VcpError("切片失败：%s（stream-copy rc=%s / 重编码 rc=%s）\n%s"
                                   % (fn, rc, rc2, tail))
            tmp.replace(dst)
            cut += 1
        items.append({
            "filename": fn, "dest_dir": str(out_dir), "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3),
            "transcript_title": seg.get("transcript_title") or "",
            "product_name": seg.get("product_name") or "",
            "basis": seg.get("basis") or granularity,
            "src_video": str(src), "src_sha256": src_sha,
            "size_bytes": dst.stat().st_size if dst.is_file() else 0,
        })

    write_json(ctx.rec("cut_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(), "granularity": granularity,
        "output_dir": str(out_dir), "src_video_sha256": src_sha,
        "ffmpeg": ffmpeg, "ffmpeg_source": ff_src,
        "stats": {"total": len(items), "cut": cut, "reused": reused},
        "items": items,
    })
    log("  ✓ 切片完成：共 %d 段（新切 %d / 复用 %d）→ %s" % (len(items), cut, reused, out_dir))
    return 0


# ---------------------------------------------------------------------------
# 子命令：export（由记录派生清单/索引/文案汇总/交付总索引）
# ---------------------------------------------------------------------------

def cmd_export(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json"), {}) or {}
    cm = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    catalog = read_json(ctx.rec("catalog.json"), {}) or {}
    pcatalog = read_json(ctx.rec("product_catalog.json"), {}) or {}
    cw = read_json(ctx.rec("copywriting.json"), {}) or {}
    written = []

    # 交付清单（始终产出）：逐字稿 + 交付文档 + 截图（**只列本节**，见 Ctx 节级视图）
    transcript_docs = ctx.transcripts()
    deliver_docs = ctx.docs()
    shots = ctx.shots_files()

    lines = ["# %s 交付索引" % ctx.section, "",
             "> 由工作流 `video-to-content-pack` 于 %s 自动生成（源头记录见 `_work/%s/`）。" % (now_iso(), ctx.section),
             "> **本节级索引**：全部路径均为本节的 `%s*` 产物；课程级总索引见 `课程交付/README.md`（`consolidate` 汇总）。"
             % ctx.sec_prefix, "",
             "## 交付物", "", "| 类别 | 文件 | 大小 |", "|---|---|---|"]
    for p in transcript_docs:
        lines.append("| 修正版逐字稿 | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))
    for p in deliver_docs:
        lines.append("| 交付文档 | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))
    if shots:
        lines.append("| 去边截图 | 共 %d 张（`讲义截图/`） | — |" % len(shots))
    pdfs = ctx.pdfs()
    for p in pdfs:
        lines.append("| 精排 PDF | `%s` | %.1f KB |" % (p.name, p.stat().st_size / 1024))

    # 配图核对（W5：配图数一律由磁盘/记录实际计数，杜绝手工填写错漏）
    ill = read_json(ctx.rec("illustration_index.json"), None)
    if isinstance(ill, dict):
        ill = ill.get("items")
    text_pages = ctx.shots_text_files()
    refs = set()
    for md in transcript_docs + deliver_docs:
        for m in RE_MD_IMG.finditer(md.read_text(encoding="utf-8")):
            refs.add(m.group(1).strip())
    lines += ["", "## 配图核对（自动计数，勿手工填写）", "",
              "| 项 | 数量 |", "|---|---|",
              "| 磁盘截图（`讲义截图/`） | %d |" % len(shots),
              "| 交付文档引用（去重） | %d |" % len(refs),
              "| 文字页替代（`讲义截图_文字页替代/`，不计入截图） | %d |" % len(text_pages)]
    if ill is not None:
        active = [e for e in ill if isinstance(e, dict) and not e.get("text_replaced")]
        lines.append("| 配图索引有效条目（`illustration_index.json`） | %d |" % len(active))

    if meta.get("items"):
        lines += ["", "## 转录概览", "", "| 文件 | 时长(秒) | 语言 | 段落数 | 置信度 |", "|---|---|---|---|---|"]
        for it in meta["items"]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                it.get("stem"), it.get("duration_sec"), it.get("language") or "—",
                it.get("segments_count"), it.get("confidence") if it.get("confidence") is not None else "—"))
    if cm.get("items"):
        lines += ["", "## 视频切片", "",
                  "粒度：`%s`　输出目录：`%s`　段数：%d" % (
                      cm.get("granularity"), Path(cm.get("output_dir", "")).name, len(cm["items"])), "",
                  "| # | 文件名 | 起 | 止 | 时长(秒) |", "|---|---|---|---|---|"]
        for i, it in enumerate(cm["items"], 1):
            lines.append("| %d | `%s` | %.1f | %.1f | %.1f |"
                         % (i, it["filename"], it["start"], it["end"], it["duration"]))
    idx_md = ctx.deliver / ("%s交付索引.md" % ctx.sec_prefix)
    idx_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(str(idx_md))

    # 小节视频清单 CSV / 索引 MD（按粒度；**节级文件名带前缀**，多节互不覆盖）
    if cm.get("items"):
        csv_path = ctx.deliver / ("%s小节视频清单.csv" % ctx.sec_prefix)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["节次", "节标题", "段号", "段标题", "逐字稿对应标题", "文件名", "相对路径",
                        "起始", "结束", "时长_秒", "粒度来源"])
            for i, it in enumerate(cm["items"], 1):
                title = Path(it["filename"]).stem
                rel = rel_ws(ctx.ws, Path(it["dest_dir"]) / it["filename"])
                w.writerow([ctx.section, ctx.section, i, title, it.get("transcript_title", ""),
                            it["filename"], rel, "%.2f" % it["start"], "%.2f" % it["end"],
                            "%.2f" % it["duration"], it.get("basis", "")])
        written.append(str(csv_path))

        idx_lines = ["# %s 小节视频索引" % ctx.section, "",
                     "粒度：`%s`　共 %d 段" % (cm.get("granularity"), len(cm["items"])), ""]
        for i, it in enumerate(cm["items"], 1):
            t = it.get("transcript_title") or Path(it["filename"]).stem
            idx_lines.append("%d. **%s**（%.1f–%.1f 秒，%.1f 秒）" % (i, t, it["start"], it["end"], it["duration"]))
            if it.get("product_name"):
                idx_lines.append("   - 产品：%s" % it["product_name"])
        idx_sect = ctx.deliver / ("%s小节视频索引.md" % ctx.sec_prefix)
        idx_sect.write_text("\n".join(idx_lines) + "\n", encoding="utf-8")
        written.append(str(idx_sect))

        if any(it.get("product_name") for it in cm["items"]):
            pcsv = ctx.deliver / ("%s产品切片清单.csv" % ctx.sec_prefix)
            with pcsv.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["产品名", "对应节次", "段号", "视频文件", "起始", "结束", "时长_秒", "文案文件"])
                for i, it in enumerate(cm["items"], 1):
                    if not it.get("product_name"):
                        continue
                    cw_file = "%s_%s_文案.md" % (ctx.section, it["product_name"])
                    w.writerow([it["product_name"], ctx.section, i, it["filename"],
                                "%.2f" % it["start"], "%.2f" % it["end"], "%.2f" % it["duration"],
                                cw_file if (ctx.chapter / cw_file).is_file() else ""])
            written.append(str(pcsv))

    # 文案汇总（copywriting==on 时，任何粒度都要出）
    entries = cw.get("items") if isinstance(cw, dict) else cw
    if entries:
        cl = ["# %s 文案汇总" % ctx.section, "", "> 由 `copywriting.json` 派生；合规提示须人工核对后方可外发。", ""]
        for e in entries:
            cl.append("## %s" % (e.get("ref") or e.get("scope") or "文案"))
            if e.get("selling_points"):
                cl.append("**卖点**：" + "；".join(map(str, e["selling_points"])))
            if e.get("script"):
                cl += ["", "**口播**：", "", str(e["script"])]
            if e.get("title"):
                cl += ["", "**标题**：%s" % e["title"]]
            if e.get("body"):
                cl += ["", "**正文**：", "", str(e["body"])]
            if e.get("compliance_notes"):
                cl += ["", "**合规提示**：" + "；".join(map(str, e["compliance_notes"]))]
            cl.append("")
        cw_path = ctx.deliver / ("%s文案汇总.md" % ctx.sec_prefix)
        cw_path.write_text("\n".join(cl) + "\n", encoding="utf-8")
        written.append(str(cw_path))

    # 目录/产品差异报告（有则归档到交付区，便于交付时一并查阅；节级文件名带前缀）
    for src_name, dst_name in (("catalog_diff.json", "目录差异报告.md"),
                               ("product_catalog_diff.json", "产品切片差异报告.md")):
        rec = read_json(ctx.rec(src_name), None)
        if rec:
            body = rec.get("report_md") if isinstance(rec, dict) else None
            if body:
                dst = ctx.deliver / ("%s%s" % (ctx.sec_prefix, dst_name))
                dst.write_text(str(body), encoding="utf-8")
                written.append(str(dst))

    # 视频时间轴与来源说明（W12：列为**独立交付物**，讲义只留一行指针，不把大表塞进每章）
    ing = read_json(ctx.rec("ingestion_manifest.json"), {}) or {}
    tl = ["# %s · 视频时间轴与来源说明" % ctx.section, "",
          "> 由工作流 `video-to-content-pack` 于 %s 自动派生（源头记录见 `_work/%s/`）。"
          % (now_iso(), ctx.section),
          "> 讲义正文只保留内联 `▶ MM:SS` 轻锚点 + 一行指针，**完整时间轴以本文件为准**。", "",
          "## 一、来源与合规", "", "| 项 | 值 |", "|---|---|",
          "| 来源类型 | `%s` |" % (ing.get("source_type") or "—"),
          "| 来源地址 / 设备描述符 | `%s` |" % (ing.get("source_uri") or "—"),
          "| 摄取方法 | %s |" % (ing.get("method") or "—"),
          "| 归一化文件 | `%s` |" % (ing.get("normalized_file") or "—"),
          "| 时长(秒) | %s |" % (ing.get("duration_sec") if ing.get("duration_sec") is not None else "—"),
          "| 获取时间 | %s |" % (ing.get("fetched_at") or "—"),
          "", "> %s" % (ing.get("compliance") or "—"), ""]
    adoc, atag = ctx.find_anchor_doc()
    anchors = parse_anchors(adoc.read_text(encoding="utf-8")) if adoc else []
    if anchors:
        tl += ["## 二、章节时间轴（源：%s `%s`，共 %d 条锚点）" % (atag, adoc.name, len(anchors)), "",
               "| # | 时间码 | 小节 | 对应内容节选 |", "|---|---|---|---|"]
        for i, an in enumerate(anchors, 1):
            body = (an["body"] or "—").replace("|", "／")[:40]
            tl.append("| %d | `%s` | %s | %s |"
                      % (i, an["timecode"], (an["heading"] or "—").replace("|", "／")[:24], body))
        tl.append("")
    if cm.get("items"):
        tl += ["## 三、切片对照（粒度 `%s`，共 %d 段）" % (cm.get("granularity"), len(cm["items"])), "",
               "| # | 文件名 | 起(秒) | 止(秒) | 时长(秒) | 依据 |", "|---|---|---|---|---|---|"]
        for i, it in enumerate(cm["items"], 1):
            tl.append("| %d | `%s` | %.1f | %.1f | %.1f | %s |"
                      % (i, it["filename"], it["start"], it["end"], it["duration"], it.get("basis", "")))
        tl.append("")
    tl_path = ctx.deliver / ("%s视频时间轴与来源说明.md" % ctx.sec_prefix)
    tl_path.write_text("\n".join(tl) + "\n", encoding="utf-8")
    written.append(str(tl_path))

    write_json(ctx.rec("export_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "scope": "section", "sec_prefix": ctx.sec_prefix,
        "note": "节级产物一律以 sec_prefix 开头；课程级汇总产物（README/合并清单）由 consolidate 步生成。",
        "granularity": cm.get("granularity") or a.granularity,
        "copywriting": bool(entries), "catalog": bool(catalog), "product_catalog": bool(pcatalog),
        "files": written,
    })
    log("  ✓ 导出完成，共 %d 个文件：" % len(written))
    for p in written:
        log("      %s" % rel_ws(ctx.ws, p))
    return 0


# ---------------------------------------------------------------------------
# 子命令：render（doc-layout md-pdf：交付文档 → 精排 PDF）
# ---------------------------------------------------------------------------

def cmd_render(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if a.deliverable_render == "off":
        log("  · deliverable_render=off，跳过渲染")
        return 0
    ctx.pdf.mkdir(parents=True, exist_ok=True)

    candidates = ctx.docs() + ctx.transcripts()   # 只渲染**本节**交付物（节级拆解）
    if not candidates:
        log("  ⚠ 未找到本节（%s）可渲染的 Markdown 交付物（%s / %s），跳过"
            % (ctx.section, ctx.sub_doc, ctx.sub_transcript))
        write_json(ctx.rec("render_manifest.json"),
                   {"section": ctx.section, "items": [], "note": "无 Markdown 交付物"})
        return 0

    items, ok, fail = [], 0, 0
    for md in candidates:
        if not md.name.startswith(ctx.sec_prefix):
            log("  ⚠ 命名不合节级规范（缺前缀 `%s`）：%s" % (ctx.sec_prefix, md.name))
        out = ctx.pdf / (md.stem + ".pdf")
        title = md.stem.replace("_", " ")
        proc = kit_call(["md-pdf", "-i", str(md), "-o", str(out), "-t", title])
        good = proc.returncode == 0 and out.is_file() and out.stat().st_size > 1024
        items.append({"src": str(md), "pdf": str(out) if out.is_file() else "",
                      "ok": good, "bytes": out.stat().st_size if out.is_file() else 0,
                      "rc": proc.returncode})
        ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
        log("  %s %s" % ("✓" if good else "✗", md.name))

    write_json(ctx.rec("render_manifest.json"), {
        "section": ctx.section, "generated_at": now_iso(), "scope": "section",
        "renderer": "doc-layout-aesthetics · md-pdf（Markdown→中文精排 PDF；图片按相对路径内联）",
        "output_dir": str(ctx.pdf), "stats": {"ok": ok, "failed": fail}, "items": items,
    })
    if fail:
        log("  ⚠ %d 份渲染失败（见 render_manifest.json），未静默放过" % fail)
        return 3
    log("  ✓ 渲染完成：%d 份 → %s" % (ok, ctx.pdf))
    return 0


# ---------------------------------------------------------------------------
# 子命令：cloud-upload（doc-layout tencent-doc：显式外发，经 kit 外发闸门）
# ---------------------------------------------------------------------------

def cmd_cloud_upload(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    if a.cloud_upload != "tencent":
        log("  · cloud_upload=off，跳过云端上传")
        return 0
    docs = ctx.docs()   # 只上传**本节**交付文档：缺此过滤会把别节文档一并外发（严重）
    if not docs:
        log("  ⚠ 无可上传的交付文档，跳过")
        write_json(ctx.rec("cloud_manifest.json"),
                   {"section": ctx.section, "scope": "section", "items": [], "note": "无交付文档"})
        return 0
    items = []
    for md in docs:
        proc = kit_call(["tencent-doc", str(md), "--title", md.stem.replace("_", " ")])
        items.append({"src": str(md), "rc": proc.returncode,
                      "ok": proc.returncode == 0,
                      "note": "（显式外发：命中敏感信息时由 kit 外发闸门阻断，须 --confirm-raw 确认）"})
        log("  %s %s" % ("✓" if proc.returncode == 0 else "✗", md.name))
    write_json(ctx.rec("cloud_manifest.json"), {"section": ctx.section, "generated_at": now_iso(),
                                                "scope": "section", "target": "腾讯文档（docs.qq.com）",
                                                "items": items})
    bad = [i for i in items if not i["ok"]]
    if bad:
        log("  ⚠ %d 份上传未成功（常见的非缺陷原因：宿主未连接腾讯文档 / 命中敏感被闸门阻断）。"
            "详见 cloud_manifest.json" % len(bad))
        return 3
    log("  ✓ 云端上传完成：%d 份" % len(items))
    return 0


# ---------------------------------------------------------------------------
# 子命令：desen-gate（交付物外发前强制 DESEN 扫描）
# ---------------------------------------------------------------------------

_SCAN_CLEAN = "未发现已知敏感标识符"
_SCAN_HIT = "汇总："


def cmd_desen_gate(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    scope = a.scope
    if a.desen_gate == "off":
        log("  ⚠ desen_gate=off：交付物**未经**本地敏感信息扫描（用户显式关闭，风险自负）")
        write_json(ctx.rec("desen_report.json"), {"section": ctx.section, "scope": scope, "skipped": True,
                                                  "reason": "desen_gate=off（用户显式关闭）"})
        return 0

    work_deliver = ctx.work / "交付"      # 转录成品逐字稿（按节路径，天然归属本节）
    dirs, files = [], []
    if scope == "workspace":
        # 课程级外发（「汇总交付」后整包发送）：`课程交付/` 全量递归
        if ctx.deliver.is_dir():
            dirs.append(ctx.deliver)
            files += [p for p in ctx.deliver.rglob("*") if p.is_file()]
    else:
        # 节级（默认）：只扫**本节**交付物。课程级汇总产物（README / 合并清单）被排除——
        # 它们含别节内容，计入会让「别节的敏感内容阻断本节」，与单节拆解执行相悖。
        files = ctx.deliver_files()
    if work_deliver.is_dir():
        files += [p for p in work_deliver.rglob("*") if p.is_file()]

    if not dirs and not files:
        log("  ⚠ 未发现待扫描的交付物（课程交付/ 为空），跳过并将跳过写入报告")
        write_json(ctx.rec("desen_report.json"), {"section": ctx.section, "scope": scope,
                                                  "targets": [], "clean": None, "note": "无交付物"})
        return 0

    text_files = [p for p in files if p.suffix.lower() in TEXT_DELIVER_EXTS]
    binary_files = [p for p in files if p.suffix.lower() in (set(IMAGE_EXTS) | {".pdf"})]
    results, hit_detail, clean_all = [], [], True

    # ① 目录级扫描（仅课程级；快）：命中即确定性阻断，出现「未发现」标记即通过
    for d in dirs:
        proc = kit_call(["desen", "scan", str(d), "--recursive"])
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        results.append({"target": str(d), "mode": "dir", "rc": proc.returncode, "output": out[-4000:]})
        if _SCAN_HIT in out:
            clean_all = False
            hit_detail.append({"target": str(d), "output": out[-4000:]})
        elif _SCAN_CLEAN not in out:
            clean_all = None          # 无法判定 → 降级逐文件扫描
    # ② 文本交付物逐文件扫描（单文件扫描必定产出明确标记；节级模式下这是主路径）
    if clean_all is None or not dirs:
        clean_all = True
        for f in sorted(set(text_files)):
            proc = kit_call(["desen", "scan", str(f)])
            out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            results.append({"target": str(f), "mode": "file", "rc": proc.returncode, "output": out[-2000:]})
            if _SCAN_HIT in out:
                clean_all = False
                hit_detail.append({"target": str(f), "output": out[-2000:]})
            elif _SCAN_CLEAN not in out:
                clean_all = False
                hit_detail.append({"target": str(f), "output": out[-2000:] or "（扫描无有效输出，按 fail-safe 判定）"})
    # ③ 影像 / PDF：desen 不做 OCR，无法自动判定 → 显式记为「待人工确认」，绝不静默算过
    if binary_files:
        results.append({
            "target": "%d 个影像/PDF 文件" % len(binary_files), "mode": "manual-required", "rc": 0,
            "samples": [p.name for p in sorted(binary_files)[:5]],
            "output": "desen 对影像/图片型 PDF 不做 OCR，无法自动判定；须先 preprocess 识别为文本再纳入脱敏，"
                      "原始图片/图片型 PDF **严禁外传**",
        })

    report = {
        "section": ctx.section, "generated_at": now_iso(), "scope": scope,
        "policy": "外发必扫 DESEN 铁律（SOUL.md 常驻规则 / SKILL.md 硬约束）——交付物外发前强制扫描",
        "scope_note": ("课程级：课程交付/ 全量递归" if scope == "workspace"
                       else "节级：仅本节交付物（排除课程级汇总产物）"),
        "targets": [str(t) for t in dirs], "text_files": [str(p) for p in sorted(set(text_files))],
        "binary_files": [str(p) for p in sorted(set(binary_files))],
        "manual_required": bool(binary_files),
        "clean": bool(clean_all), "hits": hit_detail, "runs": results,
    }
    write_json(ctx.rec("desen_report.json"), report)

    if clean_all:
        log("  ✓ 交付物本地敏感信息扫描通过（未发现已知敏感标识符）→ desen_report.json")
        if binary_files:
            log("  ⚠ %d 个影像/PDF 文件 desen 不做 OCR、无法自动判定，须人工确认后方可外发"
                % len(binary_files))
        return 0
    log("  ✗ 交付物命中敏感信息，已按铁律**阻断交付**：")
    for h in hit_detail:
        log("      · %s" % h["target"])
    log("  处置三选一（详见 desen_report.json）：")
    log("    ① 脱敏副本外发：kit desen run <文件> --out workbench/desen/ → 用脱敏副本交付")
    log("    ② 确认原样外发（风险自负）：kit desen audit-log --target 交付物 --decision raw，再经用户确认为相关文件放行")
    log("    ③ 定位并修改源内容后重跑本步")
    return 3


# ---------------------------------------------------------------------------
# 子命令：verify（机械校验；语义判据由 verify 步的确认门交用户/Agent）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 子命令：classify-slides（幻灯片价值分类器 —— 文字页不截图，2026-09-23 新增）
# ---------------------------------------------------------------------------

# 纯文字页特征（封面 / 目录 / 总结 / 过渡 / 条目页）
TEXT_PAGE_PATTERNS = (
    ("toc", re.compile(r"目录|CONTENTS|课程大纲|课程内容|本课内容|本节内容|内容提要|课程结构|课程安排")),
    ("summary", re.compile(r"小[结节]|总结|回顾|要点|综上所述|本节课我们|我们学习了|谢谢观看|感谢观看|"
                           r"感谢收看|下节课|预告|思考题|结语|再见")),
    ("cover", re.compile(r"课程封面|入门篇|进阶篇|系列课|讲师|主讲|授课|第\s*\d+\s*课|课时安排")),
)


def _classify_one(text: str, num_boxes, ink, a) -> tuple:
    """判定单帧为 `knowledge`（知识承载型）还是 `text_only`（纯文字型）。

    回退链：OCR 文本特征（subtype）→ 结构特征（boxes/行数/短行比）→ 墨量复核。
    **墨量是唯一否决项**：判定为文字页特征但墨量高（含照片/图解）时仍归
    `knowledge`，宁可多留图也不漏知识画面（与「相似度只是筛子不是裁判」同源）。
    """
    lines = ocr_lines(text)
    chars = len(re.sub(r"\s", "", text or ""))
    nb = num_boxes if isinstance(num_boxes, int) else len(lines)
    short_ratio = (sum(1 for l in lines if len(l) <= 18) / len(lines)) if lines else 0.0
    ink_val = 0.0 if ink is None else ink

    subtype = ""
    for name, pat in TEXT_PAGE_PATTERNS:
        if pat.search(text or ""):
            subtype = name
            break
    if not subtype:
        if nb <= 3 and chars <= 24:
            subtype = "transition"
        elif len(lines) >= 3 and short_ratio >= 0.8 and nb <= int(a.list_box_max):
            subtype = "item_list"

    texty = bool(subtype) and chars <= a.char_max and nb <= a.box_max
    if texty and ink_val <= a.ink_max:
        return "text_only", subtype, "文字页特征（%s）+ 墨量 %.3f ≤ %.3f" % (subtype, ink_val, a.ink_max)
    if texty:
        return "knowledge", subtype, ("疑似文字页（%s）但墨量 %.3f > %.3f：画面含照片/图解，保留截图"
                                     % (subtype, ink_val, a.ink_max))
    return "knowledge", subtype, "无文字页特征（boxes=%s chars=%d ink=%.3f）" % (nb, chars, ink_val)


def cmd_classify_slides(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    idx = read_json(ctx.rec("frame_index.json"), None)
    if idx is None:
        raise VcpError("缺少 frame_index.json（请先执行 index-records）")
    rev = read_json(ctx.rec("ocr_review.json"), {}) or {}
    ocr = {it.get("frame_id"): it
           for it in ((rev.get("items") if isinstance(rev, dict) else rev) or [])}
    frames = [f for f in (idx.get("frames") or []) if f.get("selected")]

    base = {"section": ctx.section, "generated_at": now_iso(),
            "thresholds": {"ink_max": a.ink_max, "box_max": a.box_max,
                           "char_max": a.char_max, "list_box_max": a.list_box_max},
            "note": "分类是**建议**不是裁判：text_only（纯文字/封面/目录/总结/过渡/条目页）建议在交付文档中"
                    "转为 Markdown 文字版、不生成截图；判为 knowledge 但 review_required=true 的仍须人眼复核。"
                    "判据见蓝本 §2.5 / illustration-spec「幻灯片价值分类器」。"}
    if not frames:
        write_json(ctx.rec("slide_class.json"), dict(base, stats={"total": 0, "knowledge": 0, "text_only": 0},
                                                     items=[], text_only=[]))
        log("  · 无可分类帧（frame_index 为空或无选中帧），跳过")
        return 0

    items, texty, warn = [], [], ""
    for f in frames:
        o = ocr.get(f["frame_id"], {})
        text = o.get("ocr_text") or f.get("ocr_text") or ""
        nb = o.get("num_boxes")
        ink = None
        try:
            ink = ink_ratio(Path(f["path"]))
        except Exception as exc:  # noqa: BLE001
            warn = "（墨量计算不可用：%s）" % exc
        kind, subtype, reason = _classify_one(text, nb, ink, a)
        entry = {"frame_id": f["frame_id"], "path": f["path"],
                 "timestamp_sec": f.get("timestamp_sec"), "kind": kind, "subtype": subtype,
                 "ink_ratio": None if ink is None else round(ink, 4),
                 "num_boxes": nb, "char_count": len(re.sub(r"\s", "", text)),
                 "ocr_head": text[:60], "reason": reason,
                 "review_required": subtype in ("cover", "transition", "item_list")}
        items.append(entry)
        if kind == "text_only":
            texty.append(entry)

    write_json(ctx.rec("slide_class.json"), dict(
        base, stats={"total": len(items), "knowledge": len(items) - len(texty), "text_only": len(texty)},
        items=items, text_only=[e["frame_id"] for e in texty]))
    log("  ✓ 幻灯片价值分类：%d 帧 → 知识承载 %d / 纯文字 %d（省下约 %d 张截图）%s"
        % (len(items), len(items) - len(texty), len(texty), len(texty), warn))
    for e in texty[:12]:
        log("      · [%s] %s @%.1fs %s" % (e["subtype"], Path(e["frame_id"]).name,
                                           e["timestamp_sec"] or -1, e["ocr_head"][:28]))
    if len(texty) > 12:
        log("      · …另有 %d 帧，详见 slide_class.json" % (len(texty) - 12))
    log("  → 建议：text_only 帧在交付文档中转为 Markdown 列表/缩进/引用块呈现，并移入 "
        "课程交付/讲义截图_文字页替代/（不生成截图，蓝本 §3.7 / illustration-spec 三-2）")
    return 0


# ---------------------------------------------------------------------------
# 子命令：anchor-check（锚点自检 + 最佳帧建议，2026-09-23 新增）
# ---------------------------------------------------------------------------

def cmd_anchor_check(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    idx = read_json(ctx.rec("frame_index.json"), None)
    if idx is None:
        raise VcpError("缺少 frame_index.json（请先执行 index-records）")
    rev = read_json(ctx.rec("ocr_review.json"), {}) or {}
    ocr = {it.get("frame_id"): it
           for it in ((rev.get("items") if isinstance(rev, dict) else rev) or [])}
    frames = [f for f in (idx.get("frames") or [])
              if f.get("selected") and f.get("timestamp_sec") is not None]

    doc, tag = ctx.find_anchor_doc(getattr(a, "doc", "") or "")
    base = {"section": ctx.section, "generated_at": now_iso(), "window_sec": a.window,
            "min_hit": a.min_hit, "doc": str(doc) if doc else "", "doc_source": tag,
            "note": "锚点漂移自检（W13）+ 最佳帧建议（W11）：对每条 ▶ 锚点在 ±窗口内取帧，"
                    "按「标题/正文关键词是否出现在该帧 OCR 文本」打分；drift=窗口内有帧但关键词全不命中"
                    "（锚点疑似漂移或截到了相邻页），no_frame=窗口内无候选帧，"
                    "indeterminate=无标题可依或标题为「开场/结语」类通用词（成品逐字稿 `[MM:SS]` 行的"
                    "关键词来自口语正文，与画面文字本就不必重合，故不下漂移结论）。"
                    "`best` 即建议采用的最佳帧（OCR 匹配度最高）。"}
    if not doc:
        write_json(ctx.rec("anchor_check.json"), dict(base, anchors=[], checked=0,
                                                     drift_count=0, no_frame_count=0))
        log("  ⚠ 未找到含 ▶ 时间锚点的逐字稿（修正版 / 转录成品均无），锚点自检跳过")
        return 0

    anchors = parse_anchors(doc.read_text(encoding="utf-8"))
    if not anchors:
        write_json(ctx.rec("anchor_check.json"), dict(base, anchors=[], checked=0,
                                                     drift_count=0, no_frame_count=0))
        log("  ⚠ %s 内未解析到 ▶ 时间锚点（约定 `▶ **MM:SS**`，蓝本 §3.1），自检跳过" % doc.name)
        return 0

    results, drift, noframe, indet = [], 0, 0, 0
    # 转录成品（`[MM:SS]` 行）没有「知识点小标题」，其标题只是文档结构标题（如「纠正版逐字稿」），
    # 不能据此判漂移——该模式下所有未命中一律记 indeterminate，仅给候选帧。
    ts_mode = bool(anchors) and anchors[0].get("mode") == "ts"
    for an in anchors:
        cands = [f for f in frames if abs(f["timestamp_sec"] - an["time_sec"]) <= a.window]
        head_kw = tokens(an["heading"])[:8]
        alt = tokens(an["body"])[:8]
        kws = head_kw or alt
        generic_head = (an["heading"] or "").strip() in GENERIC_HEADINGS
        ranked = []
        for f in cands:
            text = ocr.get(f["frame_id"], {}).get("ocr_text") or f.get("ocr_text") or ""
            hit = [k for k in kws if kw_hit(k, text)]
            hit_alt = [k for k in alt if kw_hit(k, text)]
            ranked.append({"frame_id": f["frame_id"], "path": f["path"],
                           "ts": round(f["timestamp_sec"], 2), "score": len(hit),
                           "alt_score": len(hit_alt),
                           "delta_sec": round(f["timestamp_sec"] - an["time_sec"], 1),
                           "matched": (hit or hit_alt)[:5], "ocr_head": text[:60]})
        ranked.sort(key=lambda x: (x["score"], x["alt_score"], -abs(x["delta_sec"])), reverse=True)
        best = ranked[0] if ranked else None
        if best and (best["score"] >= a.min_hit or best["alt_score"] >= a.min_hit):
            status = "ok"
        elif ts_mode or not head_kw or generic_head:
            # 锚点无知识点标题可依（成品逐字稿的 `[MM:SS]` 行 / 通用小标题「开场·结语」）：
            # 关键词来自口语正文，与画面文字本就不必重合 → 不下漂移结论。
            status, indet = "indeterminate", indet + 1
        elif best:
            status, drift = "drift", drift + 1
        else:
            status, noframe = "no_frame", noframe + 1
        results.append({"line_no": an["line_no"], "timecode": an["timecode"], "mode": an.get("mode", ""),
                        "time_sec": an["time_sec"], "heading": an["heading"], "body": an["body"],
                        "keywords": kws, "alt_keywords": alt, "status": status,
                        "drift_sec": None if not best else best["delta_sec"],
                        "best": best, "candidates": ranked[:3]})

    write_json(ctx.rec("anchor_check.json"), dict(
        base, checked=len(results), ok_count=len(results) - drift - noframe - indet,
        drift_count=drift, no_frame_count=noframe, indeterminate_count=indet, anchors=results))
    log("  ✓ 锚点自检：%d 条（源：%s %s）→ 命中 %d / 漂移 %d / 无候选帧 %d / 无标题不下结论 %d"
        % (len(results), tag, doc.name, len(results) - drift - noframe - indet, drift, noframe, indet))
    for r in results:
        if r["status"] == "ok":
            continue
        b = r["best"]
        tail = ("；建议改用 %s（%.1fs，Δ%+.1fs，OCR 命中 %s）"
                % (Path(b["frame_id"]).name, b["ts"], b["delta_sec"], "/".join(b["matched"]) or b["ocr_head"][:20])) \
            if b else ""
        log("      ⚠ [%s] %s《%s》%s" % (r["status"], r["timecode"], r["heading"] or r["body"][:18], tail))
    if drift or noframe:
        log("  → drift/no_frame 项须按「抽帧目视确认」重新定位（勿盲信锚点），再据 best 候选重截；"
            "确认后可在 illustration_index.json 追加 recaptured 审计字段")
    return 0


# ---------------------------------------------------------------------------
# 子命令：name-check（命名规范 + 文件名↔画面一致性，2026-09-23 新增）
# ---------------------------------------------------------------------------

def _ocr_cached(path: Path, cache_dir: Path):
    """对图片做 OCR 并落缓存（subprocess-per-image + 断点续跑，防内存累积 OOM）。"""
    arch = cache_dir / path.stem / "存档" / ("%s.json" % path.stem)
    if not arch.is_file():
        proc = kit_call(["extract", str(path), "--type", "ocr", "--out", str(cache_dir / path.stem)])
        if proc.returncode != 0 or not arch.is_file():
            return None
    data = read_json(arch, {}) or {}
    return (data.get("text") or data.get("raw_text") or "").strip()


def cmd_name_check(a) -> int:
    ctx = Ctx(a.workspace, a.section)
    shots = ctx.shots_files()
    base = {"section": ctx.section, "generated_at": now_iso(), "ocr": a.ocr,
            "note": "① 命名规范：`第NN节_图MM_中文短描述.{png|jpg}`，章号/图号**零填充**、无空格与特殊字符；"
                    "② 文件名↔画面一致性：把文件名描述词（以及 illustration_index.json 的 anchor_para）"
                    "与**该图自身 OCR 文本**比对，0 命中即告警（W10：命名须由帧内容驱动，不得凭段落主题猜）。"}
    if not shots:
        write_json(ctx.rec("naming_report.json"), dict(base, stats={"total": 0, "name_bad": 0, "mismatch": 0,
                                                                   "unverifiable": 0, "checked": 0}, items=[]))
        log("  · 讲义截图/ 下无图片，命名核对跳过")
        return 0

    index = read_json(ctx.rec("illustration_index.json"), None)
    if isinstance(index, dict):
        index = index.get("items")
    anchor_of = {}
    for e in (index or []):
        if isinstance(e, dict) and e.get("img"):
            anchor_of[e["img"]] = e.get("anchor_para") or ""

    items, name_bad, mismatch, unverifiable, checked = [], [], [], [], 0
    pads = {"ch": set(), "idx": set()}
    for p in shots:
        m = RE_SHOT_NAME.match(p.name)
        issues = []
        if m:
            pads["ch"].add(len(m.group(1)))
            pads["idx"].add(len(m.group(2)))
            if not re.search(r"[\u4e00-\u9fff]", m.group(3)):
                issues.append("描述无中文（可读性差）")
        else:
            issues.append("命名不符「第NN节_图MM_描述.ext」")
            if re.search(r"^第\d{1}节|_图\d{1}(?!\d)", p.name):
                issues.append("章号/图号未零填充")
        if " " in p.stem or "　" in p.stem:
            issues.append("含空格")
        if re.search(r'[<>:"/\\|?*]', p.name):
            issues.append("含特殊字符")
        items.append({"file": p.name, "path": str(p), "pattern_ok": bool(m), "issues": issues,
                      "chapter": m.group(1) if m else "", "index": m.group(2) if m else "",
                      "desc": m.group(3) if m else "", "verdict": "ok", "anchor_para": anchor_of.get(p.name, ""),
                      "ocr_head": "", "overlap": None})
        if issues:
            name_bad.append(p.name)

    pad_issue = len(pads["ch"]) > 1 or len(pads["idx"]) > 1
    if a.ocr == "on":
        cache = ctx.work / "naming_ocr"
        limit = a.limit if a.limit and a.limit > 0 else len(items)
        for it in items[:limit]:
            text = _ocr_cached(Path(it["path"]), cache)
            checked += 1
            if text is None:
                it["verdict"] = "ocr_failed"
                continue
            it["ocr_head"] = text[:60]
            kws = tokens(it["desc"]) + tokens(it["anchor_para"])
            if not RE_MEANINGFUL.search(text) or not kws:
                # 画面无文字（纯图/构图页，OCR 只吐标点噪声）或文件名无可比对关键词
                # → 记「无法核对」，不作名实不符结论（宁可漏报，不可误报）
                it["verdict"], it["overlap"] = "unverifiable", None
                unverifiable.append(it["file"])
                continue
            hit = [k for k in kws if kw_hit(k, text)]
            it["overlap"] = len(hit)
            it["matched"] = hit[:5]
            if not hit:
                it["verdict"] = "mismatch"
                mismatch.append(it["file"])

    write_json(ctx.rec("naming_report.json"), dict(
        base, stats={"total": len(items), "name_bad": len(name_bad), "pad_inconsistent": pad_issue,
                     "checked": checked, "mismatch": len(mismatch), "unverifiable": len(unverifiable)},
        name_bad=name_bad, pad_inconsistent=pad_issue, mismatch=mismatch,
        unverifiable=unverifiable, items=items))
    log("  ✓ 命名核对：%d 张 → 命名不规范 %d / 零填充混用 %s / 文件名↔画面不一致 %d / 无法核对 %d"
        % (len(items), len(name_bad), "是" if pad_issue else "否", len(mismatch), len(unverifiable)))
    for n in name_bad[:8]:
        log("      ⚠ 命名：%s" % n)
    for n in mismatch[:8]:
        log("      ⚠ 名实疑似不符：%s" % n)
    if a.ocr == "on" and mismatch:
        log("  → 名实不符项须抽帧目视确认后重命名/重截（W10/W11），勿仅凭段落主题改回原名")
    return 0


# ---------------------------------------------------------------------------
# 子命令：consolidate（跨节状态自动汇总，取代手工补 pipeline_state，2026-09-23 新增）
# ---------------------------------------------------------------------------

def _auto_index_block(ctx, sections) -> str:
    lines = [INDEX_BEGIN,
             "> 以下「课程总览自动汇总」由工作流 `video-to-content-pack` 的 `consolidate` 步生成"
             "（%s）——**配图数取自磁盘实际计数**，勿手工编辑该区块。" % now_iso(), "",
             "| 节 | 交付文档 | 修正版逐字稿 | 配图数 | 校验（失败/警告） | 记录链 |",
             "|---|---|---|---|---|---|"]
    for s in sections:
        vf, vw = s["verify_failed"], s["verify_warned"]
        # 未做校验的节（无 verify_report.json）：显式标「未校验」，
        # 绝不以 0 冒充「校验通过」；此处也必须容忍 None 而非崩溃（consolidate 可单独调用）
        cell = "未校验" if vf is None else "%d / %d" % (vf, vw or 0)
        lines.append("| %s | %d | %d | %d | %s | %d/%d |" % (
            s["section"], s["docs"], s["transcripts"], s["shots"], cell,
            len(s["records_present"]), len(s["records_present"]) + len(s["records_missing"])))
    lines.append(INDEX_END)
    return "\n".join(lines) + "\n"


def _sec_sources(deliver: Path, name: str) -> list:
    """收集各节的节级同类产物（`第NN节_<name>`）。

    `name` 前的 `*` 会匹配空串，故课程级同名文件（`<name>` 本体）也命中——
    用 `chapter_digits()` 过滤，只认带章节号前缀的文件。
    """
    if not deliver.is_dir():
        return []
    return sorted(p for p in deliver.glob("*%s" % name)
                  if p.is_file() and chapter_digits(p.name))


def _merge_csv(deliver: Path, name: str) -> dict:
    """各节 CSV → 课程级同名 CSV（表头保留一次，按节号升序拼接）。"""
    srcs, out = _sec_sources(deliver, name), deliver / name
    if not srcs:
        removed = out.is_file()
        if removed:      # 源已消失（某节改回 granularity=none）→ 清掉陈旧汇总，避免误导
            out.unlink()
        return {"file": str(out), "written": False, "rows": 0, "sections": 0, "removed_stale": removed}
    header, rows = None, []
    for p in srcs:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            data = [r for r in csv.reader(fh) if r]
        if not data:
            continue
        if header is None:
            header = data[0]
        rows += data[1:]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header or [])
        w.writerows(rows)
    return {"file": str(out), "written": True, "rows": len(rows), "sections": len(srcs)}


def _merge_md(deliver: Path, name: str, title: str, intro: str) -> dict:
    """各节 Markdown → 课程级同名 MD（各节内容降为二级标题，剥掉自身的 H1/引言块）。"""
    srcs, out = _sec_sources(deliver, name), deliver / name
    if not srcs:
        removed = out.is_file()
        if removed:
            out.unlink()
        return {"file": str(out), "written": False, "sections": 0, "removed_stale": removed}
    parts = ["# %s" % title, "", "> %s" % intro,
             "> 由 `video-to-content-pack` 的 `consolidate` 步汇总生成（%s），**勿手工编辑**。" % now_iso(), ""]
    for p in srcs:
        body = p.read_text(encoding="utf-8").splitlines()
        while body and (not body[0].strip() or body[0].startswith("# ") or body[0].startswith(">")):
            body.pop(0)      # 剥掉源文件自身的一级标题与引言块，改挂到本节二级标题下
        parts += ["## %s" % (p.stem.split("_")[0]), ""] + body + [""]
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return {"file": str(out), "written": True, "sections": len(srcs)}


def _course_index(ctx: Ctx, sections, total) -> str:
    """课程级交付总索引（`课程交付/README.md`，跨节汇总，**全量重生成**）。"""
    def link(name):
        return "[`%s`](%s)" % (name, name) if (ctx.deliver / name).is_file() else "—"

    lines = ["# 课程交付总索引", "",
             "> 由 `video-to-content-pack` 的 `consolidate` 步于 %s 汇总生成——**本文件全量重生成，勿手工编辑**；"
             % now_iso(),
             "> 人工内容请写入 `00_课程总览_索引.md`（该文件的自动区块之外）。",
             "> 命名约定：**节级产物一律以 `第NN节_` 前缀命名，课程级汇总产物（本文件与合并清单）不带前缀**。",
             "> 权威计数见 `_work/aggregated_sections.json`。", "",
             "## 一、课程合计", "", "| 项 | 数量 |", "|---|---|",
             "| 节数 | %d |" % total["sections"],
             "| 交付文档 | %d |" % total["docs"],
             "| 修正版逐字稿 | %d |" % total["transcripts"],
             "| 配图（去边后） | %d |" % total["shots"],
             "| 纯文字页替代原图 | %d |" % total["shots_text_only"],
             "| 配图索引有效条目 | %d |" % total["illustrations"],
             "| 机械校验 硬失败 / 软告警 | %d / %d |" % (total["verify_failed"], total["verify_warned"]),
             "", "## 二、逐节交付物导航", "",
             "| 节 | 交付索引 | 时间轴与来源 | 小节视频清单 | 文案汇总 | 配图 | 校验(失败/警告) | 记录链 |",
             "|---|---|---|---|---|---|---|---|"]
    for s in sections:
        pre = section_prefix(s["section"])
        vf, vw = s["verify_failed"], s["verify_warned"]
        cell = "未校验" if vf is None else "%d / %d" % (vf, vw or 0)
        lines.append("| %s | %s | %s | %s | %s | %d | %s | %d/%d |" % (
            s["section"], link("%s交付索引.md" % pre), link("%s视频时间轴与来源说明.md" % pre),
            link("%s小节视频清单.csv" % pre), link("%s文案汇总.md" % pre),
            s["shots"], cell, len(s["records_present"]),
            len(s["records_present"]) + len(s["records_missing"])))

    # 全课配图核对（W5：一律实际计数，杜绝手工填错）
    refs = set()
    if ctx.deliver.is_dir():
        for md in sorted(p for p in ctx.deliver.rglob("*.md")
                         if p.is_file() and p.name not in COURSE_LEVEL_FILES):
            for m in RE_MD_IMG.finditer(md.read_text(encoding="utf-8")):
                raw = m.group(1).strip()
                if not raw.startswith(("http://", "https://")):
                    refs.add(str((md.parent / raw).resolve()))
    lines += ["", "## 三、配图核对（自动计数，勿手工填写）", "",
              "| 范围 | 磁盘截图 | 交付文档引用（去重） | 文字页替代 | 索引有效条目 |",
              "|---|---|---|---|---|",
              "| **全课** | %d | %d | %d | %d |" % (
                  total["shots"], len(refs), total["shots_text_only"], total["illustrations"])]

    todo = []
    if total["sections_without_verify"]:
        todo.append("未做机械校验的节：%s（该节 `verify` 步未执行）"
                    % "、".join(total["sections_without_verify"]))
    if total["verify_failed"]:
        todo.append("仍有机械校验硬失败 %d 项——逐节见 `_work/<节>/verify_report.json`" % total["verify_failed"])
    lines += ["", "## 四、待办", ""]
    lines += (["- %s" % t for t in todo] if todo else ["- 无（各节机械校验硬项均通过）"])
    lines += ["- 语义项（图文位置判据 / 配图三条标准 / 形态结构 / 文案合规）须在确认门逐项复核，见各节 `verify_report.json`。"]
    return "\n".join(lines) + "\n"


def cmd_consolidate(a) -> int:
    """汇总各节状态 → `_work/aggregated_sections.json` + `课程交付/` 课程级汇总产物。

    「单节拆解执行 → 汇总交付」的收口步：各节产物带 `第NN节_` 前缀（export 生成），
    本步**跨节汇总**出课程级产物（`README.md` 交付总索引 + 合并的清单/索引，均不带前缀），
    全部全量重生成以保证幂等。

    为何不写 `pipeline_state.json`：该文件由 runner 独占（每步 `_save()` 用内存态
    整体覆写），脚本侧写入会被下一次保存覆盖，属竞态。故汇总落**独立记录**
    `aggregated_sections.json`，索引区块用标记包裹幂等改写、不覆盖人工内容。
    """
    ctx = Ctx(a.workspace, a.section)
    work_root = ctx.ws / "_work"
    records = ["run_context.json", "ingestion_manifest.json", "transcript_meta.json",
               "frame_index.json", "ocr_review.json", "slide_class.json", "anchor_check.json",
               "crop_manifest.json", "delivery_spec.json", "illustration_index.json",
               "naming_report.json", "cut_manifest.json", "desen_report.json", "verify_report.json"]
    sections = []
    for d in (sorted(p for p in work_root.iterdir() if p.is_dir()) if work_root.is_dir() else []):
        dig = chapter_digits(d.name)
        vr = read_json(d / "verify_report.json", {}) or {}
        checks = vr.get("mechanical_checks") or []
        illust = read_json(d / "illustration_index.json", []) or []
        if isinstance(illust, dict):
            illust = illust.get("items") or []
        active = [e for e in illust if isinstance(e, dict) and not e.get("text_replaced")]
        present = [r for r in records if (d / r).is_file()]
        sections.append({
            "section": d.name, "chapter_digits": dig,
            "docs": len(collect_records(ctx.sub_doc, "*.md", dig)),
            "transcripts": len(collect_records(ctx.sub_transcript, "*.md", dig)),
            "shots": len(collect_records(ctx.shots, "*", dig)),
            "shots_text_only": len(collect_records(ctx.shots_text, "*", dig)),
            "illustrations": len(active),
            "illustrations_total": len(illust),
            "verify_failed": vr.get("failed", 0) if vr else None,
            "verify_warned": vr.get("warned", 0) if vr else None,
            "verify_checks": len(checks),
            "records_present": present,
            "records_missing": [r for r in records if r not in present],
        })

    total = {
        "sections": len(sections),
        "docs": sum(s["docs"] for s in sections),
        "transcripts": sum(s["transcripts"] for s in sections),
        "shots": sum(s["shots"] for s in sections),
        "shots_text_only": sum(s["shots_text_only"] for s in sections),
        "illustrations": sum(s["illustrations"] for s in sections),
        "verify_failed": sum(s["verify_failed"] or 0 for s in sections),
        "verify_warned": sum(s["verify_warned"] or 0 for s in sections),
        "sections_without_verify": [s["section"] for s in sections if s["verify_failed"] is None],
    }
    # ── 课程级汇总交付（「单节拆解执行 → 汇总交付」）──
    # 节级产物带 `第NN节_` 前缀（export 生成），课程级产物不带前缀（本步生成，全量重生成保幂等）
    ctx.deliver.mkdir(parents=True, exist_ok=True)
    (ctx.deliver / "README.md").write_text(_course_index(ctx, sections, total), encoding="utf-8")
    course = {
        "readme": str(ctx.deliver / "README.md"),
        "小节视频清单.csv": _merge_csv(ctx.deliver, "小节视频清单.csv"),
        "产品切片清单.csv": _merge_csv(ctx.deliver, "产品切片清单.csv"),
        "文案汇总.md": _merge_md(ctx.deliver, "文案汇总.md", "全课文案汇总",
                                 "由各节 `第NN节_文案汇总.md` 汇总；合规提示须人工核对后方可外发。"),
        "小节视频索引.md": _merge_md(ctx.deliver, "小节视频索引.md", "全课小节视频索引",
                                  "由各节 `第NN节_小节视频索引.md` 汇总；完整时间轴见各节"
                                  " `第NN节_视频时间轴与来源说明.md`。"),
    }

    write_json(work_root / "aggregated_sections.json", {
        "workflow": "video-to-content-pack", "generated_at": now_iso(),
        "note": "跨节状态汇总（W6）。pipeline_state.json 由 runner 独占，脚本不回写以避免竞态覆盖。",
        "index": "课程交付/00_课程总览_索引.md",
        "course_deliverables": course,
        "sections": sections, "total": total,
    })

    # 自动索引区块（标记包裹，幂等；无标记时追加，绝不覆盖人工内容）
    idx = ctx.deliver / "00_课程总览_索引.md"
    block = _auto_index_block(ctx, sections)
    if idx.is_file():
        text = idx.read_text(encoding="utf-8")
        if INDEX_BEGIN in text and INDEX_END in text:
            head = text.split(INDEX_BEGIN)[0]
            tail = text.split(INDEX_END, 1)[1]
            # block 自身以 \n 结尾，而 tail 通常也以 \n 开头——不归一化就会**每次重跑多出一个空行**
            # （尾部空行无限累积，属非幂等）。故 head 去尾空行补两行、tail 去首空行。
            idx.write_text(head.rstrip() + "\n\n" + block + tail.lstrip("\n"), encoding="utf-8")
        else:
            idx.write_text(text.rstrip() + "\n\n" + block, encoding="utf-8")
    else:
        idx.write_text("# 课程总览与索引\n\n" + block, encoding="utf-8")

    log("  ✓ 跨节汇总：%d 节 / 交付文档 %d / 配图 %d（文字页替代 %d）/ 校验失败 %d 警告 %d"
        % (total["sections"], total["docs"], total["shots"], total["shots_text_only"],
           total["verify_failed"], total["verify_warned"]))
    log("  ✓ 已落盘：%s" % (work_root / "aggregated_sections.json").relative_to(ctx.ws))
    log("  ✓ 自动索引区块已写入：%s（标记 %s…%s）" % (idx.relative_to(ctx.ws), INDEX_BEGIN, INDEX_END))
    log("  ✓ 课程级汇总交付（节级产物带 `第NN节_` 前缀，课程级不带前缀）：")
    log("      %s ← 逐节导航 + 全课合计 + 配图核对（全量重生成）"
        % (ctx.deliver / "README.md").relative_to(ctx.ws))
    for name, v in course.items():
        if name == "readme":
            continue
        rel = str((ctx.deliver / name).relative_to(ctx.ws))
        if v.get("written"):
            log("      %s ← 合并 %d 节%s" % (rel, v["sections"],
                                          ("，%d 行" % v["rows"]) if "rows" in v else ""))
        elif v.get("removed_stale"):
            log("      %s 已移除（各节源均不存在，避免陈旧汇总误导）" % rel)
        else:
            log("      %s 未生成（各节无对应产物）" % rel)
    if total["sections_without_verify"]:
        log("  ⚠ 未做校验的节：%s" % "、".join(total["sections_without_verify"]))
    return 0


def _duration_of(path: Path, ffmpeg: str) -> float:
    """用 ffprobe 同源能力取时长：ffmpeg -i 输出解析（无 ffprobe 依赖）。"""
    proc = subprocess.run([ffmpeg, "-nostdin", "-i", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
    if not m:
        return -1.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def cmd_verify(a) -> int:
    """交付前机械校验（6 项门禁，W15）——硬项不过即阻断，软项显式告警不阻断。

    门禁 1 引用完整性 / 2 命名规范（含量名一致）/ 3 最佳截取核对 /
    4 配图覆盖 / 5 时间锚点下传 / 6 记录链·备份链·切片·外发·渲染·索引。
    语义判据（图文位置 A–E、配图三条标准、形态结构、文案合规）仍交确认门。
    """
    ctx = Ctx(a.workspace, a.section)
    meta = read_json(ctx.rec("transcript_meta.json"), {}) or {}
    cm = read_json(ctx.rec("cut_manifest.json"), {}) or {}
    checks, failed, warned = [], 0, 0

    def add(name, ok, detail="", level="hard"):
        nonlocal failed, warned
        ok = bool(ok)
        checks.append({"check": name, "ok": ok, "level": level, "detail": detail})
        if not ok:
            if level == "soft":
                warned += 1
            else:
                failed += 1
        mark = "✓" if ok else ("⚠" if level == "soft" else "✗")
        log("  %s %s%s%s" % (mark, name, "　[告警]" if (not ok and level == "soft") else "",
                             ("　— %s" % detail) if detail else ""))

    def gate(no, title):
        log("  ── 门禁 %s：%s ──" % (no, title))

    # ═══ 门禁 1：引用完整性 ═══
    gate(1, "引用完整性")
    # 节级视图（Ctx.docs/transcripts）：平铺交付目录只取**本节**文件，多节不互相串味
    docs = ctx.docs()
    trans = ctx.transcripts()
    add("交付文档存在（课程交付/讲义/，本节）", bool(docs), "%d 份" % len(docs))
    add("修正版逐字稿存在（课程交付/逐字稿_修正版/，本节）", bool(trans), "%d 份" % len(trans))

    refs, missing, textpage_refs = set(), [], []
    for md in docs + trans:
        for m in RE_MD_IMG.finditer(md.read_text(encoding="utf-8")):
            raw = m.group(1).strip()
            if raw.startswith(("http://", "https://")):
                continue
            p = (md.parent / raw).resolve()
            refs.add(str(p))
            if not p.is_file():
                missing.append("%s → %s" % (md.name, raw))
            elif ctx.shots_text.resolve() in p.parents:
                textpage_refs.append("%s → %s" % (md.name, raw))
    add("截图引用零缺失", not missing,
        ("缺失 %d 处：%s" % (len(missing), "; ".join(missing[:5]))) if missing else "引用 %d 个" % len(refs))
    shots = {str(p.resolve()) for p in ctx.shots_files()}
    orphan = sorted(shots - refs)
    add("截图零冗余（无未被引用的孤儿图）", not orphan,
        ("孤儿 %d 张：%s" % (len(orphan), ", ".join(Path(o).name for o in orphan[:5])))
        if orphan else "共 %d 张" % len(shots))
    add("纯文字页未被当作截图引用（讲义截图_文字页替代/ 应转文字呈现）", not textpage_refs,
        "; ".join(textpage_refs[:3]) if textpage_refs else "0 处")

    # ═══ 门禁 2：命名规范 + 文件名↔画面一致 ═══
    gate(2, "命名规范与名实一致")
    nrep = read_json(ctx.rec("naming_report.json"), None)
    bad_names, pads_ch, pads_idx = [], set(), set()
    for p in sorted(Path(s) for s in shots):
        m = RE_SHOT_NAME.match(p.name)
        if not m:
            bad_names.append(p.name)
            continue
        pads_ch.add(len(m.group(1)))
        pads_idx.add(len(m.group(2)))
        if re.search(r'[<>:"/\\|?*]', p.name) or " " in p.stem:
            bad_names.append(p.name)
    pad_mix = len(pads_ch) > 1 or len(pads_idx) > 1
    add("截图命名符合「第NN节_图MM_描述.ext」", not bad_names,
        ("不规范 %d 张：%s" % (len(bad_names), ", ".join(bad_names[:5]))) if bad_names else "全部合规")
    add("章号/图号零填充一致（无 1 位与 2 位混用）", not pad_mix,
        "宽度：章 %s / 图 %s" % (sorted(pads_ch), sorted(pads_idx)))
    # 节级产物必须带节前缀——「单节拆解执行」的前提：平铺目录里靠前缀区分归属
    unprefixed = [p.name for p in (docs + trans) if not p.name.startswith(ctx.sec_prefix)]
    add("节级产物文件名带节前缀（%s）" % ctx.sec_prefix, not unprefixed,
        ("缺前缀 %d 个：%s" % (len(unprefixed), ", ".join(unprefixed[:5]))) if unprefixed
        else "全部合规", level="soft")
    if nrep is None:
        add("文件名↔画面一致性（需先跑 name-check 步）", False,
            "缺少 naming_report.json", level="soft")
    else:
        st = nrep.get("stats") or {}
        mism, chk = st.get("mismatch") or 0, st.get("checked") or 0
        if mism:
            add("文件名↔画面一致性（OCR 关键词命中）", False,
                "疑似名实不符 %d 张：%s" % (mism, ", ".join((nrep.get("mismatch") or [])[:5])),
                level="soft")
        elif chk == 0:
            # 一张都没实际核对过（`name-check --ocr off` 或全部未跑到）：不得显示为「已核对通过」，
            # 否则门禁 2 形同虚设——这是「告警而非绿灯」的诚实性要求（W10/W15）。
            add("文件名↔画面一致性（OCR 关键词命中）", False,
                "未做画面 OCR 核对（naming_report.checked=0，ocr=%s）——请以 `name-check --ocr on` 重跑"
                % (nrep.get("ocr") or "?"), level="soft")
        else:
            add("文件名↔画面一致性（OCR 关键词命中）", True,
                "核对 %d 张，0 不符（无法核对 %d 张）" % (chk, st.get("unverifiable") or 0),
                level="soft")

    # ═══ 门禁 3：最佳截取核对（锚点 ± 窗口 OCR） ═══
    gate(3, "最佳截取核对")
    arep = read_json(ctx.rec("anchor_check.json"), None)
    if arep is None:
        add("锚点自检（需先跑 anchor-check 步）", False, "缺少 anchor_check.json", level="soft")
    else:
        add("锚点无漂移（±%ss 窗口内 OCR 命中核心词）" % arep.get("window_sec", 10),
            not arep.get("drift_count"),
            ("漂移 %d 条 / 无候选帧 %d 条 / 无标题不下结论 %d 条（共 %d 条，源 %s）"
             % (arep.get("drift_count"), arep.get("no_frame_count"),
                arep.get("indeterminate_count") or 0, arep.get("checked"),
                Path(arep.get("doc") or "—").name)) if arep.get("drift_count")
            else "核对 %d 条锚点，0 漂移" % arep.get("checked", 0))
        add("锚点均有候选帧（无 no_frame）", not arep.get("no_frame_count"),
            "无候选帧 %s 条" % arep.get("no_frame_count"), level="soft")

    # ═══ 门禁 4：配图覆盖（知识点段 → 配图，W7） ═══
    gate(4, "配图覆盖")
    uncovered = []
    for md in docs:      # docs 已由 Ctx 按本节过滤（多节工作区不会串味），无需二次筛
        text = md.read_text(encoding="utf-8")
        heads = [h for h in RE_MD_HEAD.finditer(text)]
        lvl = 3 if any(len(h.group(1)) >= 3 for h in heads) else 2
        picked = [h for h in heads if len(h.group(1)) == lvl]
        for i, h in enumerate(picked):
            end = picked[i + 1].start() if i + 1 < len(picked) else len(text)
            body = text[h.end():end]
            body_chars = len(re.sub(r"\s", "", RE_MD_IMG.sub("", body)))
            if body_chars >= a.coverage_min_chars and not RE_MD_IMG.search(body):
                uncovered.append("%s §%s（%d 字无图）" % (md.name, h.group(2)[:16], body_chars))
    add("每个知识点段（≥%d 字）至少 1 图" % a.coverage_min_chars, not uncovered,
        ("%d 段无图：%s" % (len(uncovered), "; ".join(uncovered[:4]))) if uncovered
        else "0 段无图（纯文字段已转文字呈现）", level="soft")

    # ═══ 门禁 5：时间锚点下传与精度（W1） ═══
    gate(5, "时间锚点下传")
    adoc, atag = ctx.find_anchor_doc()
    n_src = n_dst = 0
    if adoc:
        n_src = len(parse_anchors(adoc.read_text(encoding="utf-8")))
    for md in docs:      # 同上：docs 已按节过滤
        n_dst += len(RE_ANCHOR.findall(md.read_text(encoding="utf-8")))
    if n_src:
        add("时间锚点已下传至交付文档（讲义内联 ▶）", n_dst > 0,
            "源 %s %d 条 → 交付文档 %d 处" % (atag or "逐字稿", n_src, n_dst))
    else:
        add("时间锚点下传（逐字稿暂无 ▶ 锚点，跳过）", True, "源 0 条", level="soft")

    # ═══ 门禁 6：记录链·备份链·切片·外发·渲染·索引 ═══
    gate(6, "记录链 / 备份链 / 切片 / 外发 / 渲染 / 索引")
    if shots:
        have = {p.name for p in ctx.shots_bak.iterdir() if p.is_file()} if ctx.shots_bak.is_dir() else set()
        # 按「本节每张图是否都有备份」判定（旧写法比总数，多节共目录时会假通过）
        missing_bak = sorted(Path(s).name for s in shots if Path(s).name not in have)
        add("去边前原图备份齐全（讲义截图_原始备份/）", not missing_bak,
            ("缺 %d 张：%s" % (len(missing_bak), ", ".join(missing_bak[:5]))) if missing_bak
            else "本节 %d 张均已备份（备份目录共 %d 张，含其他节）" % (len(shots), len(have)))

    if cm.get("items"):
        items = cm["items"]
        add("切片文件全部存在", all(Path(i["dest_dir"], i["filename"]).is_file() for i in items),
            "%d 段" % len(items))
        csv_path = ctx.deliver / ("%s小节视频清单.csv" % ctx.sec_prefix)
        csv_rows = 0
        if csv_path.is_file():
            with csv_path.open(encoding="utf-8-sig", newline="") as fh:
                csv_rows = max(0, sum(1 for _ in csv.reader(fh)) - 1)
        idx_path = ctx.deliver / ("%s小节视频索引.md" % ctx.sec_prefix)
        idx_rows = 0
        if idx_path.is_file():
            idx_rows = len(re.findall(r"^\d+\.\s\*\*", idx_path.read_text(encoding="utf-8"), re.M))
        add("段数一致（磁盘 = CSV = 索引）", len(items) == csv_rows == idx_rows,
            "磁盘 %d / CSV %d / 索引 %d" % (len(items), csv_rows, idx_rows))
        try:
            ffmpeg, _ = resolve_ffmpeg(a.ffmpeg_bin)
            bad, small = [], []
            for i in items:
                p = Path(i["dest_dir"], i["filename"])
                if not p.is_file():
                    continue
                if p.stat().st_size <= 200 * 1024:
                    small.append(i["filename"])
                d = _duration_of(p, ffmpeg)
                if d > 0 and abs(d - float(i["duration"])) >= 5.0:
                    bad.append("%s 实测 %.1fs ≠ 计划 %.1fs" % (i["filename"], d, i["duration"]))
            add("每段时长误差 <5s", not bad, "; ".join(bad[:5]) if bad else "%d 段核验通过" % len(items))
            if small:
                log("  ⚠ %d 个片段 ≤200KB，可能过短或损坏：%s" % (len(small), ", ".join(small[:5])))
        except VcpError as exc:
            add("时长核验（需 ffmpeg）", False, str(exc))

    required = ["run_context.json", "ingestion_manifest.json", "transcript_meta.json", "frame_index.json",
                "export_manifest.json"]
    if a.granularity != "none":
        required += ["cut_plan.json", "cut_manifest.json"]
    miss = [r for r in required if not ctx.rec(r).is_file()]
    add("工作记录链完整", not miss, ("缺失：%s" % ", ".join(miss)) if miss else "%d 项齐全" % len(required))

    ill = read_json(ctx.rec("illustration_index.json"), None)
    if isinstance(ill, dict):
        ill = ill.get("items")
    if ill is not None:
        active = [e for e in ill if isinstance(e, dict) and not e.get("text_replaced")]
        gone = [e.get("img") for e in active if e.get("img") and not (ctx.shots / e["img"]).is_file()]
        add("配图索引与磁盘一致（illustration_index ↔ 讲义截图/）",
            len(active) == len(shots) and not gone,
            "索引有效条目 %d / 磁盘 %d%s" % (len(active), len(shots),
                                            ("；索引指向缺失文件 %s" % gone[:3]) if gone else ""))
    else:
        add("配图索引存在（illustration_index.json）", False, "缺少（illustrate 步未执行）", level="soft")

    drep = read_json(ctx.rec("desen_report.json"), None)
    if a.desen_gate == "on":
        add("交付物已经本地敏感信息扫描且通过", bool(drep and drep.get("clean")),
            "见 desen_report.json" if drep else "缺少 desen_report.json（desen_gate 步未执行）")

    if a.deliverable_render == "pdf":
        rman = read_json(ctx.rec("render_manifest.json"), {}) or {}
        expect = {p.stem for p in docs + trans}
        got = {Path(i["src"]).stem for i in (rman.get("items") or []) if i.get("ok")}
        add("Markdown 交付物均已产出精排 PDF", expect <= got,
            "缺 %s" % ", ".join(sorted(expect - got)) if expect - got else "%d 份" % len(got))

    write_json(ctx.rec("verify_report.json"), {
        "section": ctx.section, "generated_at": now_iso(),
        "granularity": cm.get("granularity") or a.granularity,
        "gates": ["1 引用完整性", "2 命名规范与名实一致", "3 最佳截取核对",
                  "4 配图覆盖", "5 时间锚点下传", "6 记录链/备份链/切片/外发/渲染/索引"],
        "mechanical_checks": checks, "failed": failed, "warned": warned,
        "semantic_pending": [
            "图文位置判据 A 真错位 / B 多图堆叠 / C 图先于文 / D 裸图堆叠 必须为 0（E 类合法例外放行）"
            "——见 illustration-spec.md，属语义判断，由确认门交用户/Agent 复核",
            "配图三条标准（内容匹配 / 数量按需 / 密集合成）复核；纯文字页是否已转文字呈现（slide_class.json）",
            "交付文档结构符合 delivery_spec.json 指定形态；降级/未校对声明是否置顶（W3）",
            "文案合规提示齐全（极限词/价格/功效需人工核对）",
            "目录/产品差异报告已确认",
        ],
    })
    log("  ── 机械校验：%d 项，失败 %d 项，告警 %d 项 ──" % (len(checks), failed, warned))
    if failed:
        log("  ✗ 机械校验未通过（%d 项硬失败），请修复后重跑本步（详见 verify_report.json）" % failed)
        return 3
    log("  ✓ 机械校验硬项全部通过（告警 %d 项须逐条处置）；语义判据见 verify_report.json 的 "
        "semantic_pending，须在确认门由用户确认" % warned)
    return 0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vcp.py",
        description="video-to-content-pack 机械步 CLI（由 kit workflow 以 uses.script 调用）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, workspace=True):
        if workspace:
            sp.add_argument("--workspace", required=True, help="内容工作区根目录")
        sp.add_argument("--section", default="第1节", help="节名（默认 第1节）")
        return sp

    sp = common(sub.add_parser("precheck", help="入参与环境前置校验"))
    sp.add_argument("--source", default="file")
    sp.add_argument("--source-uri", dest="source_uri", default="")
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--copywriting", default="off")
    sp.add_argument("--digest", default="on")
    sp.add_argument("--deliverable-types", dest="deliverable_types", default="讲义")
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.add_argument("--cloud-upload", dest="cloud_upload", default="off")
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.add_argument("--whisper-model", dest="whisper_model", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_precheck)

    common(sub.add_parser("mkdirs", help="建工作区目录骨架")).set_defaults(func=cmd_mkdirs)

    sp = common(sub.add_parser("ingest", help="本地文件归一化到 按章节/<节>/"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.set_defaults(func=cmd_ingest)

    sp = common(sub.add_parser("record-live", help="直播降级：ffmpeg 先录制为本地文件"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.set_defaults(func=cmd_record_live)

    sp = common(sub.add_parser("record-device", help="设备降级：ffmpeg 设备后端采集为本地文件"))
    sp.add_argument("--source-uri", dest="source_uri", required=True)
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.add_argument("--device-duration", dest="device_duration", type=int, default=0)
    sp.set_defaults(func=cmd_record_device)

    sp = common(sub.add_parser("transcribe", help="转录（经 kit.py 调用 info-extract，保留外发闸门）"))
    sp.add_argument("--whisper-model", dest="whisper_model", default="")
    sp.set_defaults(func=cmd_transcribe)

    sp = common(sub.add_parser("index-records",
                               help="记录链索引：ingestion_manifest / transcript_meta / frame_index"))
    sp.add_argument("--dup-mad", dest="dup_mad", type=float, default=2.0,
                    help="帧判重的 MAD 阈值（0~255，越小越严；默认 2.0）")
    sp.set_defaults(func=cmd_index_records)

    sp = common(sub.add_parser("digest", help="summarize 接入：速览/关键词"))
    sp.add_argument("--keywords", type=int, default=12)
    sp.set_defaults(func=cmd_digest)

    common(sub.add_parser("frames-ocr", help="逐帧 OCR（subprocess-per-image + 断点续跑）")
           ).set_defaults(func=cmd_frames_ocr)

    sp = common(sub.add_parser("crop", help="截图去边（保守算法 + 原图备份）"))
    sp.add_argument("--pad", type=int, default=8)
    sp.add_argument("--keep-min", dest="keep_min", type=float, default=0.55)
    sp.add_argument("--max-side", dest="max_side", type=int, default=200)
    sp.set_defaults(func=cmd_crop)

    sp = common(sub.add_parser("cut", help="按 cut_plan.json 切片（增量重切）"))
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_cut)

    sp = common(sub.add_parser("export", help="派生**节级**清单/索引/文案汇总/交付索引/时间轴"))
    sp.add_argument("--granularity", default="none")
    sp.set_defaults(func=cmd_export)

    sp = common(sub.add_parser("render", help="交付文档 → 精排 PDF（doc-layout md-pdf）"))
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.set_defaults(func=cmd_render)

    sp = common(sub.add_parser("cloud-upload", help="交付文档 → 腾讯文档（显式外发，经 kit 闸门）"))
    sp.add_argument("--cloud-upload", dest="cloud_upload", default="off")
    sp.set_defaults(func=cmd_cloud_upload)

    sp = common(sub.add_parser("desen-gate", help="交付物外发前 DESEN 扫描（命中即阻断）"))
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.add_argument("--scope", default="section", choices=["section", "workspace"],
                    help="扫描范围：section=仅本节交付物（默认，单节拆解执行）；"
                         "workspace=课程交付/ 全量递归（汇总交付后整包外发时用）")
    sp.set_defaults(func=cmd_desen_gate)

    sp = common(sub.add_parser("classify-slides",
                               help="幻灯片价值分类器：纯文字页（封面/目录/总结/过渡/条目）不截图"))
    sp.add_argument("--ink-max", dest="ink_max", type=float, default=0.12,
                    help="墨量上限（0~1，越小越严；低墨量+文字页特征才判 text_only；默认 0.12）")
    sp.add_argument("--box-max", dest="box_max", type=int, default=12,
                    help="文字框数上限（超过视为非纯文字页；默认 12）")
    sp.add_argument("--char-max", dest="char_max", type=int, default=320,
                    help="OCR 字符数上限（超过视为非纯文字页；默认 320）")
    sp.add_argument("--list-box-max", dest="list_box_max", type=int, default=12,
                    help="判「条目页」允许的最大文字框数（默认 12）")
    sp.set_defaults(func=cmd_classify_slides)

    sp = common(sub.add_parser("anchor-check",
                               help="锚点自检（±窗口 OCR 纠漂）+ 最佳帧建议（录最佳截取）"))
    sp.add_argument("--window", type=float, default=10.0, help="锚点附近抽样窗口秒数（默认 10）")
    sp.add_argument("--min-hit", dest="min_hit", type=int, default=1,
                    help="判定「命中」所需的最少关键词数（默认 1）")
    sp.add_argument("--doc", default="", help="锚点来源文档（留空=自动：修正版逐字稿 > 转录成品逐字稿）")
    sp.set_defaults(func=cmd_anchor_check)

    sp = common(sub.add_parser("name-check",
                               help="命名规范校验 + 文件名↔画面 OCR 一致性核对"))
    sp.add_argument("--ocr", default="on", choices=["on", "off"],
                    help="是否做画面 OCR 一致性核对（on 较慢但能抓名实不符；默认 on）")
    sp.add_argument("--limit", type=int, default=0, help="最多核对多少张（0=全部；默认 0）")
    sp.set_defaults(func=cmd_name_check)

    common(sub.add_parser("consolidate",
                          help="跨节状态自动汇总 → aggregated_sections.json + 交付索引区块")
           ).set_defaults(func=cmd_consolidate)

    sp = common(sub.add_parser("verify", help="机械校验（6 项门禁：引用/命名/最佳截取/覆盖/锚点/记录链）"))
    sp.add_argument("--granularity", default="none")
    sp.add_argument("--desen-gate", dest="desen_gate", default="on")
    sp.add_argument("--deliverable-render", dest="deliverable_render", default="pdf")
    sp.add_argument("--coverage-min-chars", dest="coverage_min_chars", type=int, default=200,
                    help="「知识点段无图」告警的字数门槛（默认 200 字）")
    sp.add_argument("--ffmpeg-bin", dest="ffmpeg_bin", default="")
    sp.set_defaults(func=cmd_verify)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except VcpError as exc:
        log("✗ %s" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
