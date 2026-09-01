# -*- coding: utf-8 -*-
"""PDF 中文字体探测与注册（reportlab TTFont），供 build_pdf.py 与 build_md_pdf.py 复用。

历史：早期 build_pdf / build_md_pdf 各自复制了一份相同的字体探测实现（md-to-pdf
合并时整体搬入的重复代码）。现统一收敛到本模块，消除重复，并作为本技能两条 PDF
路径（docx→PDF、md→PDF）共享的字体层。

跨平台：开源可商用字体优先（思源宋体/黑体、Noto CJK、霞鹜文楷、文泉驿），系统字体
（Songti/STHeiti/SimSun/SimHei）仅作兜底并告警。reportlab TTFont 不支持 CFF/PostScript
轮廓（思源/Noto 的 .otf 与多数 Linux 发行版的 .ttc），自动跳过并告警，改用文楷/文泉驿。
"""
import glob
import os
import struct

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily


# 探测到但被跳过（CFF 轮廓，reportlab 不支持）的字体路径，供 register_fonts 告警。
_SKIPPED_CFF = []


def _truetype_outlines(path):
    """reportlab TTFont 仅支持 TrueType(glyf) 轮廓；CFF/PostScript('OTTO') 会抛
    "postscript outlines are not supported"。思源/Noto CJK 的 .otf 及多数 Linux
    发行版 .ttc 均为 CFF 轮廓，必须跳过。支持 ttc 集合（检查第一个字体表头）。"""
    try:
        with open(path, "rb") as fh:
            tag = fh.read(4)
        if tag in (b"\x00\x01\x00\x00", b"true"):
            return True
        if tag == b"OTTO":
            return False
        if tag == b"ttcf":
            with open(path, "rb") as fh:
                fh.read(4)                       # tag
                _major, _minor, num = struct.unpack(">HHI", fh.read(8))
                if num < 1:
                    return False
                off = struct.unpack(">I", fh.read(4))[0]
                fh.seek(off)
                t = fh.read(4)
            return t in (b"\x00\x01\x00\x00", b"true")
        return False
    except Exception:
        return False


def _first_truetype(*paths):
    """返回第一个「存在且为 TrueType 轮廓」的字体路径（reportlab 可用）。

    CFF 轮廓的 OTF/TTC（思源/Noto CJK）存在但不可用，会被跳过并记入
    _SKIPPED_CFF 供 register_fonts 打印可读告警。"""
    for p in paths:
        for hit in glob.glob(p):
            if not os.path.exists(hit):
                continue
            if _truetype_outlines(hit):
                return hit
            if hit not in _SKIPPED_CFF:
                _SKIPPED_CFF.append(hit)
    return None


def detect_fonts():
    """返回 (正文路径, 正文索引, 标题路径, 标题索引, 是否开源)；探测不到返回 None。

    开源可商用字体优先（思源宋体/黑体、Noto CJK、文泉驿），系统自带字体
    （Songti/STHeiti/SimSun/SimHei）仅作最后兜底——系统字体嵌入 PDF 可能受其
    许可限制，商用分发前请安装开源字体（register_fonts 会据此打印告警）。
    """
    home = os.path.expanduser("~")
    # 开源衬线（正文）：思源宋体 / Noto Serif CJK / 霞鹜文楷，SIL OFL 1.1 可商用。
    # 注意：思源/Noto 的 .otf 是 CFF(PostScript) 轮廓，reportlab TTFont 不支持，
    # _first_truetype 会自动跳过；文楷（TrueType）是开源衬线/楷体的可靠选择。
    serif_open = _first_truetype(
        os.path.join(home, "Library/Fonts/LXGWWenKai-Regular.ttf"),
        os.path.join(home, "Library/Fonts/SourceHanSerifSC-Regular.otf"),
        os.path.join(home, "Library/Fonts/NotoSerifCJKsc-Regular.otf"),
        "/Library/Fonts/LXGWWenKai-Regular.ttf",
        "/Library/Fonts/SourceHanSerifSC-Regular.otf",
        "/Library/Fonts/NotoSerifCJKsc-Regular.otf",
        os.path.join(home, ".local/share/fonts/LXGWWenKai-Regular.ttf"),
        os.path.join(home, ".local/share/fonts/SourceHanSerifSC-Regular.otf"),
        "/usr/share/fonts/opentype/source-han-serif/SourceHanSerifSC-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "C:/Windows/Fonts/LXGWWenKai-Regular.ttf",
        "C:/Windows/Fonts/SourceHanSerifSC-Regular.otf",
        "C:/Windows/Fonts/NotoSerifCJKsc-Regular.otf",
    )
    # 开源无衬线（标题）：思源黑体 / Noto Sans CJK / 文泉驿正黑（Bold 优先，Regular 兜底）
    sans_open = _first_truetype(
        os.path.join(home, "Library/Fonts/SourceHanSansSC-Bold.otf"),
        os.path.join(home, "Library/Fonts/NotoSansCJKsc-Bold.otf"),
        os.path.join(home, "Library/Fonts/wqy-zenhei.ttc"),
        "/Library/Fonts/SourceHanSansSC-Bold.otf",
        "/Library/Fonts/NotoSansCJKsc-Bold.otf",
        "/Library/Fonts/wqy-zenhei.ttc",
        os.path.join(home, ".local/share/fonts/SourceHanSansSC-Bold.otf"),
        os.path.join(home, ".local/share/fonts/wqy-zenhei.ttc"),
        "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:/Windows/Fonts/SourceHanSansSC-Bold.otf",
        "C:/Windows/Fonts/NotoSansCJKsc-Bold.otf",
        os.path.join(home, "Library/Fonts/SourceHanSansSC-Regular.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    if serif_open and sans_open:
        return serif_open, 0, sans_open, 0, True

    # 开源兜底：文泉驿（GPL + font exception，可商用，TrueType 轮廓）
    wqy = _first_truetype(
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        os.path.join(home, ".local/share/fonts/wqy-zenhei.ttc"),
        os.path.join(home, "Library/Fonts/wqy-zenhei.ttc"),
    )
    if wqy:
        return wqy, 0, wqy, 0, True

    # 系统字体兜底（嵌入 PDF 可能受许可限制，register_fonts 会告警；均为 TrueType 轮廓）
    sys_cands = [
        ("/System/Library/Fonts/Supplemental/Songti.ttc", 0,
         "/System/Library/Fonts/STHeiti Medium.ttc", 0),
        ("/System/Library/Fonts/STHeiti Light.ttc", 0,
         "/System/Library/Fonts/STHeiti Medium.ttc", 0),
        ("C:/Windows/Fonts/simsun.ttc", 0, "C:/Windows/Fonts/simhei.ttf", 0),
    ]
    for b, bi, h, hi in sys_cands:
        if os.path.exists(b) and os.path.exists(h):
            return b, bi, h, hi, False
    return None


def pick_symbols(body_path, body_idx):
    """根据正文字体的实际字形覆盖，选择确定能渲染的符号（运行时验证）。

    背景：reportlab 的 Paragraph 遇到字体缺字形的字符会**静默跳过**（渲染成空白），
    因此不能想当然用"通用符号"——实测宋体（Songti）缺 `•`(U+2022)、`☑`(U+2611)、
    `☐`(U+2610) 字形，直接用会渲染成空白。这里用 `TTFont.face.charWidths`
    实测字形，缺失时降级到备选符号并打印告警。
    """
    probe = TTFont("_symbol_probe", body_path, subfontIndex=body_idx)
    cw = probe.face.charWidths

    def has(ch):
        return ord(ch) in cw

    def pick(label, candidates):
        for ch in candidates:
            if has(ch):
                return ch
        return candidates[-1]  # 兜底（ASCII 一定可用）

    preferred = {"bullet": "●", "done": "√", "todo": "□"}
    symbols = {
        "bullet": pick("无序列表项目符号", ("●", "·", "*")),
        # 候选列表末尾必须是 ASCII 兜底（任何字体都含 ASCII），否则兜底仍可能缺字形
        "done": pick("任务已完成标记", ("√", "✓", "●", "+")),
        "todo": pick("任务未完成标记", ("□", "○", "-")),
    }
    for key, pref in preferred.items():
        if symbols[key] != pref:
            print("⚠️ 正文字体缺「%s」字形，%s 降级为「%s」"
                  % (pref, key, symbols[key]))
    return symbols


def register_fonts(with_symbols=False):
    """注册 PDF 中文字体，返回字体名。

    - 默认返回 ``("CJK", "CJKH")``（docx→PDF 路径用）；
    - ``with_symbols=True`` 时额外运行时校验关键符号字形，返回
      ``("CJK", "CJKH", symbols)``（md→PDF 路径用，避免项目符号/任务标记渲染空白）。
    """
    f = detect_fonts()
    if not f:
        raise SystemExit(
            "未检测到可用的中文字体。请安装任一开源 CJK 字体后重试：\n"
            "  macOS  : brew install --cask font-lxgw-wenkai font-wqy-zenhei\n"
            "  Linux  : sudo apt install fonts-noto-cjk\n"
            "  Windows: 从 https://github.com/lxgw/LxgwWenKai/releases 下载安装\n"
        )
    body_path, body_idx, head_path, head_idx, is_open = f
    pdfmetrics.registerFont(TTFont("CJK", body_path, subfontIndex=body_idx))
    pdfmetrics.registerFont(TTFont("CJKH", head_path, subfontIndex=head_idx))
    registerFontFamily("CJK", normal="CJK", bold="CJKH",
                       italic="CJK", boldItalic="CJKH")
    # 英文衬线（reportlab 内置 Base-14 标准字体，PDF 规范核心集，无嵌入许可问题）
    registerFontFamily("Times-Roman", normal="Times-Roman", bold="Times-Bold",
                       italic="Times-Italic", boldItalic="Times-BoldItalic")
    if is_open:
        print("✓ 已使用开源可商用中文字体渲染 PDF（文楷/思源/Noto CJK 或文泉驿，SIL OFL / GPL+font exception）。")
    else:
        print("⚠️ 未检测到开源可商用中文字体，已回退系统自带字体（嵌入 PDF 可能受许可限制，商用分发有版权风险）。")
        print("   建议安装 TrueType 轮廓的开源字体：macOS `brew install --cask font-lxgw-wenkai font-wqy-zenhei`；")
        print("   Linux `sudo apt install fonts-wqy-zenhei`；Windows 从文楷 GitHub releases 下载安装。")
    if _SKIPPED_CFF:
        print("⚠️ 已跳过 CFF(PostScript) 轮廓字体（reportlab 不支持嵌入）：")
        for p in _SKIPPED_CFF:
            print("    - %s" % p)
        print("   思源/Noto 的 .otf 供 Word/PPT/HTML 与系统显示使用；PDF 请用文楷/文泉驿等 TrueType 字体。")
    if with_symbols:
        symbols = pick_symbols(body_path, body_idx)
        return "CJK", "CJKH", symbols
    return "CJK", "CJKH"
