# -*- coding: utf-8 -*-
"""build_pdf.py 与 build_md_pdf.py 共享的主题色与文本工具。

历史：两条 PDF 路径（docx→PDF、md→PDF）早期各自复制了一份相同的 esc /
contains_cjk / 主题色常量实现（md-to-pdf 合并时整体搬入的重复代码）。现统一收敛
到本模块，与 _pdf_fonts.py（字体层）并列，作为两条 PDF 路径共享的公共层。

仅被 build_pdf.py / build_md_pdf.py 引用；selfcheck.py 保持纯标准库可导入
（需在第三方依赖缺失时仍能启动并报告「依赖缺失」），故不共享 ensure_stdout_utf8。
"""
import sys

from reportlab.lib import colors

# ---------- 主题色（主色深蓝 + 单一强调深红，克制） ----------
NAVY    = colors.HexColor("#1F4E79")   # 主色深蓝
NAVY_H2 = colors.HexColor("#23527C")   # 二级标题蓝
NAVY_H3 = colors.HexColor("#2F6B3E")   # 三级标题绿（与 H1/H2 深蓝形成层级色彩对比）
RED     = colors.HexColor("#9E2B25")   # 单一强调深红
GREY    = colors.HexColor("#595959")
META    = colors.HexColor("#666666")
HEAD_BG = colors.HexColor("#1F4E79")   # 表头深蓝
ZEBRA   = colors.HexColor("#F3F7FB")   # 斑马纹
LINE    = colors.HexColor("#9AA7B4")   # 表格网格线
CODE_BG = colors.HexColor("#F4F6F8")   # 代码块浅灰底
LIGHT   = colors.HexColor("#F2F2F2")   # 浅灰（docx→PDF 斑马纹）


# ---------- 文本工具 ----------
def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def contains_cjk(t):
    return any("\u4e00" <= ch <= "\u9fff" for ch in t)


def ensure_stdout_utf8():
    """Windows 控制台默认 GBK 编码，emoji/生僻字可能抛 UnicodeEncodeError；
    统一以 UTF-8 输出（errors=replace 兜底），保证跨平台不崩溃。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
