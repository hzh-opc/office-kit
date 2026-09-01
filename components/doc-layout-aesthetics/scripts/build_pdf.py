# -*- coding: utf-8 -*-
"""把《版面美学观》docx 转成 PDF。

设计目标：尽量保证 PDF 与 Word 文档页面统一。
转换引擎按优先级自动探测（可用 --engine 强制）：

  1. LibreOffice (soffice / libreoffice)
       —— 直接把真实 docx 转 PDF，保真度最高，页面与 Word 完全一致。
  2. docx2pdf（需本机安装 Microsoft Word）
       —— 调用 Word 把真实 docx 转 PDF，保真度同样最高。
  3. WPS Office 命令行（可选引擎）
       —— Linux/Windows 的 `wps --headless --convert-to pdf`（headless 形态，
          自动探测时可信）；macOS/Windows 的 `wpscli word2pdf`（kpdfcli 契约，
          需登录 WPS 账号且具备 VIP，auto 不采用、仅 `--engine wps` 强制）。
  4. 纯 Python（reportlab）
       —— 仅当上述引擎都缺失/不可用时才启用：读取 docx 的页型 / 页边距 /
          字体配对（思源宋体衬线正文 + 思源黑体无衬线标题），按同一套美学参数重排，
          并落实「表格跨页保护」：短表整体 KeepTogether、长表 repeatRows=1。

跨平台：macOS / Linux / Windows 均支持；Windows 控制台默认 GBK 编码，
脚本已把 stdout 统一为 UTF-8 输出避免 emoji 抛错。

依赖：
  pip install reportlab python-docx          # 纯 Python 兜底必备
  pip install docx2pdf                        # 仅 Windows/macOS + Word 机器需要
  （LibreOffice / WPS 为系统应用，无需 pip 安装）
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from docx import Document
from docx.oxml.ns import qn

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)

DEFAULT_OUT_DIR = os.getcwd()  # 平台无关：默认输出到当前目录，可用 --out 覆盖
DOCX_NAME = "版面美学观_侯捷Word排版艺术提炼.docx"
PDF_NAME = "版面美学观_侯捷Word排版艺术提炼.pdf"

# 主题色与文本工具统一由 _common 提供；中文字体探测统一由 _pdf_fonts 提供
from _common import NAVY, RED, GREY, LIGHT, esc, contains_cjk, ensure_stdout_utf8
from _pdf_fonts import detect_fonts, register_fonts

# ---------- 2. docx -> reportlab flowables ----------
def run_color(run):
    try:
        c = run.font.color.rgb
        if c is not None:
            return "#%02X%02X%02X" % (c[0], c[1], c[2])
    except Exception:
        pass
    return None


def run_markup(run):
    txt = esc(run.text)
    if txt and not contains_cjk(txt):          # 纯西文/数字 -> Times
        txt = '<font name="Times-Roman">%s</font>' % txt
    if run.bold:
        txt = "<b>%s</b>" % txt
    col = run_color(run)
    if col:
        txt = '<font color="%s">%s</font>' % (col, txt)
    return txt


def para_markup(p):
    if p.runs:
        return "".join(run_markup(r) for r in p.runs)
    return esc(p.text or "")


def is_list_item(p):
    pPr = p._p.pPr
    return pPr is not None and pPr.find(qn("w:numPr")) is not None


def build_flowables(doc, CJK, CJKH):
    body = ParagraphStyle("Body", fontName=CJK, fontSize=11, leading=16.5,
                          alignment=TA_JUSTIFY, firstLineIndent=22, spaceAfter=6)
    liststyle = ParagraphStyle("List", parent=body, firstLineIndent=0,
                               leftIndent=16, spaceAfter=3)
    h1 = ParagraphStyle("H1", fontName=CJKH, fontSize=18, leading=24,
                        textColor=NAVY, spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle("H2", fontName=CJKH, fontSize=15, leading=20,
                        textColor=NAVY, spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle("H3", fontName=CJKH, fontSize=13, leading=18,
                        textColor=NAVY, spaceBefore=8, spaceAfter=3)
    cell = ParagraphStyle("Cell", fontName=CJK, fontSize=9.5, leading=13)
    cell_h = ParagraphStyle("CellH", parent=cell, fontName=CJKH,
                            textColor=colors.white)

    flow = []
    for p in doc.paragraphs:
        st = p.style.name if p.style else ""
        text = para_markup(p)
        if not text.strip():
            flow.append(Spacer(1, 4))
            continue
        if st.startswith("Heading 1"):
            flow.append(Paragraph(text, h1))
        elif st.startswith("Heading 2"):
            flow.append(Paragraph(text, h2))
        elif st.startswith("Heading 3"):
            flow.append(Paragraph(text, h3))
        elif is_list_item(p):
            flow.append(Paragraph("•&nbsp;&nbsp;" + text, liststyle))
        else:
            flow.append(Paragraph(text, body))

    # 表格可用宽度取 docx 真实版心（与正文页边距一致），保证表格与 Word 同宽
    sec = doc.sections[0]

    def _pt(v):
        return (float(v) if v is not None else 0.0) / 12700.0

    avail = (_pt(sec.page_width) - _pt(sec.left_margin) - _pt(sec.right_margin))
    if avail <= 0:
        avail = A4[0] - 2 * 3 * cm
    for t in doc.tables:
        rows = []
        for ri, row in enumerate(t.rows):
            cells = []
            for c in row.cells:
                inner = "".join(para_markup(pp) for pp in c.paragraphs)
                cells.append(Paragraph(inner or "&nbsp;",
                                       cell_h if ri == 0 else cell))
            rows.append(cells)
        ncol = len(rows[0]) if rows else 1
        colw = [avail / ncol] * ncol
        tbl = Table(rows, colWidths=colw, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ]))
        # 短表整体保持在一页；长表靠 repeatRows 续页重复表头
        if len(rows) <= 4:
            flow.append(KeepTogether([Spacer(1, 4), tbl, Spacer(1, 6)]))
        else:
            flow.append(Spacer(1, 4))
            flow.append(tbl)
            flow.append(Spacer(1, 6))
    return flow


# ---------- 3. 引擎探测 ----------
def find_soffice():
    for n in ("soffice", "libreoffice"):
        p = shutil.which(n)
        if p:
            return p
    for e in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
              "/usr/bin/soffice", "/opt/homebrew/bin/soffice"):
        if os.path.exists(e):
            return e
    if sys.platform == "win32":
        import glob
        for pat in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\LibreOffice\program\soffice.exe")):
            hits = glob.glob(pat)
            if hits and os.path.exists(hits[0]):
                return hits[0]
    return None


def _has_ms_word():
    if sys.platform == "darwin":
        return (os.path.exists("/Applications/Microsoft Word.app") or
                os.path.exists("/Applications/Microsoft Office/Microsoft Word.app"))
    if sys.platform == "win32":
        return shutil.which("winword") is not None
    return False


def find_docx2pdf():
    """docx2pdf 模块可导入、且本机确有 Microsoft Word 时返回 True。"""
    try:
        import docx2pdf  # noqa: F401
    except ImportError:
        return False
    return _has_ms_word()


def find_wps():
    """探测 WPS Office 命令行转换工具。

    返回 (binary, mode)：
      mode='subcmd'   -> wpscli <subcommand> 契约（macOS/Windows 的 kpdfcli，
                         如 `wpscli word2pdf <in> -o <out>`；**需登录 WPS 账号且
                         具备 VIP 权限**，否则退出码 100/101）
      mode='headless' -> LibreOffice 风格（Linux 的 wps / Windows 的 wps.exe，
                         如 `wps --headless --convert-to pdf --outdir <dir> <in>`）
    探测不到返回 None。
    """
    # macOS：wpsoffice.app 自带 wpscli（kpdfcli 契约）
    if sys.platform == "darwin":
        for e in ("/Applications/wpsoffice.app/Contents/MacOS/wpscli",
                  os.path.expanduser("~/Applications/wpsoffice.app/Contents/MacOS/wpscli")):
            if os.path.exists(e):
                return e, "subcmd"
    # PATH 上的 wps / wps-office / wpscli
    for n in ("wps", "wps-office", "wpscli"):
        p = shutil.which(n)
        if p:
            mode = "subcmd" if "wpscli" in os.path.basename(p).lower() else "headless"
            return p, mode
    # Linux 常见安装路径（headless 契约）
    for e in ("/usr/bin/wps", "/usr/bin/wps-office",
              "/opt/kingsoft/wps-office/office6/wps"):
        if os.path.exists(e):
            return e, "headless"
    # Windows：Kingsoft 安装目录
    if sys.platform == "win32":
        import glob
        for pat in (os.path.expandvars(r"%LOCALAPPDATA%\Kingsoft\WPS Office\*\office6\wps.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Kingsoft\WPS Office\*\office6\wps.exe"),
                    r"C:\Users\*\AppData\Local\Kingsoft\WPS Office\*\office6\wps.exe"):
            hits = glob.glob(pat)
            if hits:
                return hits[0], "headless"
    return None


def wps_auto_ok(binary, mode):
    """auto 模式是否采用 WPS：仅信任 headless 形态（Linux/Windows wps）。

    subcmd 形态（macOS/Windows 的 wpscli）需登录 + VIP 权限，且 macOS 实测
    直接崩溃（SIGTRAP/退出码 133）、会拉起 WPS 主程序 —— 不进 auto，只允许
    显式 `--engine wps` 强制尝试。
    """
    return mode == "headless"


def detect_engine():
    """按优先级返回 ('libreoffice'|'docx2pdf'|'wps'|'reportlab', payload)。"""
    soffice = find_soffice()
    if soffice:
        return "libreoffice", soffice
    if find_docx2pdf():
        return "docx2pdf", None
    wps = find_wps()
    if wps and wps_auto_ok(*wps):
        return "wps", wps
    return "reportlab", None


def resolve_engine(requested="auto"):
    """返回最终采用的引擎 kind（'libreoffice'|'docx2pdf'|'wps'|'reportlab'）。

    requested='auto' 走优先级探测；显式指定则校验可用性，不可用回退 reportlab。
    独立成纯函数以便 pytest 直接覆盖「引擎回退链」而不触发 CLI。
    """
    if requested == "auto":
        kind, _ = detect_engine()
        return kind
    if requested == "libreoffice" and not find_soffice():
        return "reportlab"
    if requested == "docx2pdf" and not find_docx2pdf():
        return "reportlab"
    if requested == "wps" and not find_wps():
        return "reportlab"
    return requested


# ---------- 4. 各引擎转换 ----------
def convert_libreoffice(docx, out_dir):
    """用 LibreOffice 把真实 docx 转 PDF。返回产出 pdf 的临时路径，失败返回 None。

    在临时目录转换，避免 LibreOffice 在 docx 旁生成锁文件污染输出目录。
    """
    soffice = find_soffice()
    if not soffice:
        return None
    tmp = tempfile.mkdtemp(prefix="doclayout_pdf_")
    try:
        r = subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                            "--outdir", tmp, docx],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print("⚠️ LibreOffice 转换失败(退出码 %s)，回退纯 Python。" % r.returncode)
            if r.stderr.strip():
                print(r.stderr.strip()[:600])
            return None
        base = os.path.splitext(os.path.basename(docx))[0] + ".pdf"
        src = os.path.join(tmp, base)
        return src if os.path.exists(src) else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def convert_docx2pdf(docx, pdf):
    """用 docx2pdf（驱动本机 Word）把真实 docx 转 PDF。成功返回 True。"""
    try:
        from docx2pdf import convert as d2p_convert
    except Exception as e:  # 模块缺失或被依赖阻断
        print("⚠️ docx2pdf 不可用：%s，回退纯 Python。" % e)
        return False
    try:
        d2p_convert(docx, pdf)
    except Exception as e:
        print("⚠️ docx2pdf 转换失败：%s，回退纯 Python。" % e)
        return False
    return os.path.exists(pdf)


def convert_wps(docx, out_dir):
    """用 WPS 命令行把真实 docx 转 PDF。返回产出 pdf 的临时路径，失败返回 None。

    兼容两种形态：
      subcmd   -> wpscli word2pdf <in> -o <out>（kpdfcli 契约；需登录 + VIP）
      headless -> wps --headless --convert-to pdf --outdir <dir> <in>
    在临时目录转换，避免在 docx 旁生成锁文件。
    """
    found = find_wps()
    if not found:
        return None
    binary, mode = found
    tmp = tempfile.mkdtemp(prefix="doclayout_wps_")
    try:
        if mode == "subcmd":
            pdf = os.path.join(tmp, os.path.splitext(os.path.basename(docx))[0] + ".pdf")
            try:
                r = subprocess.run([binary, "word2pdf", docx, "-o", pdf],
                                   capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                print("⚠️ WPS 转换超时，回退纯 Python。")
                return None
            if r.returncode in (100, 101):
                print("⚠️ WPS 转 PDF 需登录 WPS 账号且具备 VIP 权限"
                      "（退出码 %s），回退纯 Python。" % r.returncode)
                return None
            if r.returncode != 0:
                print("⚠️ WPS 转换失败（退出码 %s），回退纯 Python。" % r.returncode)
                return None
            return pdf if os.path.exists(pdf) else None
        # headless（LibreOffice 风格）
        try:
            r = subprocess.run([binary, "--headless", "--convert-to", "pdf",
                                "--outdir", tmp, docx],
                               capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("⚠️ WPS 转换超时，回退纯 Python。")
            return None
        if r.returncode != 0:
            print("⚠️ WPS 转换失败（退出码 %s），回退纯 Python。" % r.returncode)
            return None
        base = os.path.splitext(os.path.basename(docx))[0] + ".pdf"
        src = os.path.join(tmp, base)
        return src if os.path.exists(src) else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def page_geometry(doc):
    """从 docx 读取真实页型与页边距（单位 points），让兜底 PDF 尽量贴近 Word。"""
    sec = doc.sections[0]

    def pt(v):
        return (float(v) if v is not None else 0.0) / 12700.0

    w = pt(sec.page_width)
    h = pt(sec.page_height)
    if w <= 0 or h <= 0:
        w, h = A4[0], A4[1]
    return {
        "pagesize": (w, h),
        "lm": pt(sec.left_margin) or 3 * cm,
        "rm": pt(sec.right_margin) or 3 * cm,
        "tm": pt(sec.top_margin) or 2.5 * cm,
        "bm": pt(sec.bottom_margin) or 2.5 * cm,
    }


def convert_reportlab(docx, pdf):
    CJK, CJKH = register_fonts()
    doc = Document(docx)
    flow = build_flowables(doc, CJK, CJKH)
    geo = page_geometry(doc)
    avail = geo["pagesize"][0] - geo["lm"] - geo["rm"]

    def on_page(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(geo["pagesize"][0] / 2, 1.2 * cm, str(d.page))
        canvas.restoreState()

    pdfdoc = SimpleDocTemplate(pdf, pagesize=geo["pagesize"],
                               leftMargin=geo["lm"], rightMargin=geo["rm"],
                               topMargin=geo["tm"], bottomMargin=geo["bm"],
                               title="版面美学观 · 侯捷《Word 排版艺术》提炼")
    pdfdoc.build(flow, onFirstPage=on_page, onLaterPages=on_page)


# ---------- 5. 入口 ----------
def main():
    ensure_stdout_utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="输出目录（默认当前目录）")
    ap.add_argument("--docx", help="指定 docx 路径（默认取 build_docx 产物）")
    ap.add_argument("--engine", default="auto",
                    choices=["auto", "libreoffice", "docx2pdf", "wps", "reportlab"],
                    help="转换引擎：auto(按优先级探测) / libreoffice / docx2pdf / wps / reportlab")
    args = ap.parse_args()
    out_dir = args.out or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    docx = args.docx or os.path.join(out_dir, DOCX_NAME)
    if not os.path.exists(docx):
        raise SystemExit("未找到 docx: %s\n请先运行 build_docx.py 生成。" % docx)
    pdf = os.path.join(out_dir, PDF_NAME)

    # 确定引擎（auto 走优先级探测；显式指定则校验可用性，不可用回退纯 Python）
    if args.engine == "auto":
        kind = resolve_engine("auto")
        print("🔍 自动探测转换引擎 ->", kind)
    else:
        kind = resolve_engine(args.engine)
        if args.engine == "libreoffice" and kind == "reportlab":
            print("⚠️ 未检测到 LibreOffice，回退纯 Python。")
        elif args.engine == "docx2pdf" and kind == "reportlab":
            print("⚠️ 未检测到 docx2pdf / Microsoft Word，回退纯 Python。")
        elif args.engine == "wps" and kind == "reportlab":
            print("⚠️ 未检测到 WPS 命令行工具，回退纯 Python。")

    if kind == "libreoffice":
        src = convert_libreoffice(docx, out_dir)
        if src and os.path.exists(src):
            shutil.move(src, pdf)
            print("saved (libreoffice):", pdf, "| bytes:", os.path.getsize(pdf))
            return
        print("→ LibreOffice 不可用，回退纯 Python。")
        kind = "reportlab"
    elif kind == "docx2pdf":
        if convert_docx2pdf(docx, pdf):
            print("saved (docx2pdf):", pdf, "| bytes:", os.path.getsize(pdf))
            return
        print("→ docx2pdf 不可用，回退纯 Python。")
        kind = "reportlab"
    elif kind == "wps":
        src = convert_wps(docx, out_dir)
        if src and os.path.exists(src):
            shutil.move(src, pdf)
            print("saved (wps):", pdf, "| bytes:", os.path.getsize(pdf))
            return
        print("→ WPS 不可用，回退纯 Python。")
        kind = "reportlab"

    convert_reportlab(docx, pdf)
    print("saved (reportlab):", pdf, "| bytes:", os.path.getsize(pdf))


if __name__ == "__main__":
    main()
