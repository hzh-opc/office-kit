# -*- coding: utf-8 -*-
"""把本地 Markdown 直接渲染成排版良好的中文 PDF（无需经过 docx）。

设计目标：与《版面美学观》规范对齐——正文衬线（思源宋体）左对齐、标题无衬线
（思源黑体）制造层级对比、主题色统一（深蓝 NAVY）、行距约 1.5 倍、首行缩进 2 字符、
表格跨页保护（repeatRows 续页重复表头）。中文段落用左对齐而非两端对齐，是因
为 Markdown 文档几乎一定含中英混排，两端对齐会拉出"河流"效应（字间距被强
行撑满行宽），违反美学规范第七条。

跨平台：macOS / Linux / Windows 均可运行——中文字体按「开源优先」探测（思源
宋体/黑体、Noto CJK、文泉驿，系统字体仅作最后兜底并告警），stdout 统一 UTF-8
避免 Windows GBK 控制台对 emoji/生僻字报错。

依赖：
  reportlab（纯 Python PDF 库，随宿主技能 pyproject.toml 由 uv 统一管理）
  Pillow（可选，仅当 Markdown 内嵌图片时用于读取尺寸）

用法：
  uv run python scripts/build_md_pdf.py -i in.md [-o out.pdf] [-t 标题]
  uv run python scripts/build_md_pdf.py -i in.md --subtitle "副标题" --author "作者"
"""
import argparse
import datetime
import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, Image, KeepTogether)

# 主题色与文本工具统一由 _common 提供；中文字体探测统一由 _pdf_fonts 提供
from _common import (NAVY, NAVY_H2, NAVY_H3, RED, GREY, META,
                     HEAD_BG, ZEBRA, LINE, CODE_BG, esc, contains_cjk,
                     ensure_stdout_utf8)
from _pdf_fonts import register_fonts

# ---------- 2. 内联样式解析 ----------
def inline(text):
    """把 Markdown 内联语法转成 reportlab 迷你 HTML。"""
    text = esc(text)
    # 行内代码 `code`：纯 ASCII 用等宽 Courier，含中文用 CJK + 深红强调
    def _code(m):
        c = m.group(1)
        if contains_cjk(c):
            return '<font name="CJK" color="#9E2B25">%s</font>' % c
        return '<font name="Courier" color="#9E2B25" size="9">%s</font>' % c
    text = re.sub(r'`([^`]+)`', _code, text)
    # 加粗
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # 斜体（中文不用斜体，但兼容英文斜体）
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'<i>\1</i>', text)
    # 链接 [text](url) -> 保留 text（PDF 不可点击，去掉长 URL 干扰阅读）
    text = re.sub(r'\[([^\]]+)\]\([^)\s]+\)', r'\1', text)
    # 图片占位（块级图片在 parse_blocks 单独处理，这里仅兜底行内残留）
    text = re.sub(r'!\[([^\]]*)\]\([^)\s]+\)', r'\1', text)
    return text


# ---------- 3. 块级解析 ----------
def parse_blocks(lines):
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if s == "":
            i += 1
            continue
        # 标题（兼容 "# 标题" 与 "#标题" 两种写法）
        if s.startswith("#"):
            lv = len(s) - len(s.lstrip("#"))
            blocks.append(("h", lv, s[lv:].strip()))
            i += 1
            continue
        # 代码块 ``` 围栏
        if s.startswith("```"):
            lang = s[3:].strip()
            code = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            blocks.append(("code", lang, code))
            continue
        # 水平分隔线
        if s in ("---", "***", "___") or (set(s) <= set("-*_") and len(s) >= 3):
            blocks.append(("hr", None))
            i += 1
            continue
        # 图片 ![alt](path)
        m = re.match(r'!\[([^\]]*)\]\(([^)\s]+)\)', s)
        if m:
            blocks.append(("img", m.group(1), m.group(2)))
            i += 1
            continue
        # 表格
        if s.startswith("|") or s.count("|") >= 2:
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            sep = len(rows) >= 2 and all(
                set(c) <= set("-: ") for c in rows[1])
            header = rows[0]
            data = rows[2:] if sep else rows[1:]
            blocks.append(("table", header, data))
            continue
        # 任务清单 - [ ] / - [x]
        if re.match(r'^\s*[-*]\s+\[[ xX]\]\s+', line):
            items = []
            while i < n:
                cur = lines[i]
                if re.match(r'^\s*[-*]\s+\[[ xX]\]\s+', cur):
                    mm = re.match(r'^\s*[-*]\s+\[([ xX])\]\s+(.*)', cur)
                    items.append([mm.group(1).lower() == "x", mm.group(2).rstrip()])
                    i += 1
                    # 续行：2+ 空格缩进的非空行
                    while i < n and re.match(r'^ {2,}\S', lines[i]):
                        cont = re.sub(r'^ {2,}', '', lines[i]).rstrip()
                        items[-1][1] += "\n" + cont
                        i += 1
                else:
                    break
            blocks.append(("task", items))
            continue
        # 无序列表（支持缩进续行）
        if re.match(r'^\s*[-*+]\s+', line):
            items = []
            while i < n and re.match(r'^\s*[-*+]\s+', lines[i]):
                items.append([re.sub(r'^\s*[-*+]\s+', "", lines[i]).rstrip()])
                i += 1
                # 续行：2+ 空格缩进的非空、非新列表项行
                while i < n and re.match(r'^ {2,}\S', lines[i]) \
                        and not re.match(r'^\s*[-*+]\s+', lines[i]) \
                        and not re.match(r'^\s*\d+\.\s+', lines[i]) \
                        and not re.match(r'^\s*[-*]\s+\[[ xX]\]\s+', lines[i]):
                    cont = re.sub(r'^ {2,}', '', lines[i]).rstrip()
                    items[-1][0] += "\n" + cont
                    i += 1
            blocks.append(("list", items, False))
            continue
        # 有序列表（支持缩进续行）
        if re.match(r'^\s*\d+\.\s+', line):
            items = []
            while i < n and re.match(r'^\s*\d+\.\s+', lines[i]):
                items.append([re.sub(r'^\s*\d+\.\s+', "", lines[i]).rstrip()])
                i += 1
                # 续行：2+ 空格缩进的非空、非新列表项行
                while i < n and re.match(r'^ {2,}\S', lines[i]) \
                        and not re.match(r'^\s*[-*+]\s+', lines[i]) \
                        and not re.match(r'^\s*\d+\.\s+', lines[i]) \
                        and not re.match(r'^\s*[-*]\s+\[[ xX]\]\s+', lines[i]):
                    cont = re.sub(r'^ {2,}', '', lines[i]).rstrip()
                    items[-1][0] += "\n" + cont
                    i += 1
            blocks.append(("list", items, True))
            continue
        # 引用块：连续以 > 开头的行，行内保留换行与硬换行（用 \n 标记硬换行）
        if s.startswith(">"):
            quote_lines = []
            while i < n and lines[i].lstrip().startswith(">"):
                ql = re.sub(r'^>\s*', "", lines[i])
                if ql.endswith("  ") or ql.rstrip().endswith("\\"):
                    ql = ql.rstrip().rstrip("\\") + "\n"  # \n 标记硬换行
                else:
                    ql = ql.strip()
                quote_lines.append(ql)
                i += 1
            blocks.append(("quote", quote_lines))
            continue
        # 段落（支持行尾两空格 / 反斜杠硬换行）
        para = []
        while i < n:
            ls = lines[i].strip()
            if (ls == "" or ls.startswith("#") or ls.startswith("|")
                    or ls.startswith("```") or ls.startswith(">")
                    or ls in ("---", "***", "___")
                    or re.match(r'^\s*[-*+]\s+', ls)
                    or re.match(r'^\s*\d+\.\s+', ls)
                    or re.match(r'^\s*[-*]\s+\[[ xX]\]\s+', ls)
                    or re.match(r'!\[[^\]]*\]\([^)\s]+\)', ls)):
                break
            raw = lines[i]
            # 行尾两空格（hard break）或反斜杠 → 标记硬换行
            if raw.rstrip().endswith("\\"):
                para.append(raw.rstrip().rstrip("\\").rstrip() + "\n")
            elif raw.endswith("  "):
                para.append(raw.rstrip() + "\n")
            else:
                para.append(raw.strip())
            i += 1
        # 段落：行尾两空格 / 反斜杠标记硬换行（用 \n），其余段内行用空格连接（Markdown 标准）
        if para:
            blocks.append(("p", " ".join(para)))
    return blocks


# ---------- 4. 表格宽度估算 ----------
def est_width(s):
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o > 0x2E80:
            w += 1.0
        elif ch.isdigit() or ch.isalpha():
            w += 0.55
        else:
            w += 0.3
    return w


def compute_colwidths(header, data, available):
    cols = max([len(header)] + [len(r) for r in data])
    def norm(row):
        row = list(row) + [""] * (cols - len(row))
        return row[:cols]
    header = norm(header)
    data = [norm(r) for r in data]
    maxw = [0.0] * cols
    for r in [header] + data:
        for c in range(cols):
            maxw[c] = max(maxw[c], est_width(r[c]))
    total = sum(maxw) or 1
    raw = [available * w / total for w in maxw]
    MIN = 44
    for i in range(cols):
        if raw[i] < MIN:
            raw[i] = MIN
    s = sum(raw)
    if s > available:
        raw = [r * available / s for r in raw]
    return header, data, [float(x) for x in raw]


# ---------- 5. 渲染 ----------
def _render_heading(b, h1, h2, h3):
    """渲染标题为 flowable 列表（H1/H2 附带分隔线）。"""
    lv, text = b[1], b[2]
    if lv == 1:
        return [Paragraph(inline(text), h1),
                HRFlowable(width="100%", thickness=1.2, color=NAVY, spaceAfter=8)]
    if lv == 2:
        return [Paragraph(inline(text), h2),
                HRFlowable(width="100%", thickness=0.6,
                           color=colors.HexColor("#CCD6E0"), spaceAfter=6)]
    return [Paragraph(inline(text), h3)]


def _render_block(b, available, body, list_s, cell, cell_h, code_s,
                  symbols, md_dir):
    """渲染单个非标题 block 为 flowable 列表。"""
    kind = b[0]
    out = []
    if kind == "hr":
        out.append(Spacer(1, 3))
        out.append(HRFlowable(width="100%", thickness=0.8,
                              color=colors.HexColor("#BBBBBB"), spaceAfter=8))
    elif kind == "p":
        # 段落里的 \n 是硬换行（行尾两空格 / \ 产生），渲染为 <br/>
        text = inline(b[1]).replace("\n", "<br/>")
        out.append(Paragraph(text, body))
    elif kind == "list":
        items, ordered = b[1], b[2]
        for idx, it in enumerate(items):
            # 项目符号经 pick_symbols 运行时验证（宋体缺「•」，已自动选「●」）
            prefix = ("%d. " % (idx + 1)) if ordered else (symbols["bullet"] + "  ")
            # items 现在是 list[str]（含续行 \n），渲染时把 \n 转 <br/>
            if isinstance(it, list):
                content = it[0]
            else:
                content = it
            content = inline(content).replace("\n", "<br/>")
            out.append(Paragraph(prefix + content, list_s))
        out.append(Spacer(1, 5))
    elif kind == "task":
        for entry in b[1]:
            done, it = entry[0], entry[1]
            # 标记经 pick_symbols 运行时验证（宋体缺「☑/☐」，已自动选「√/□」）
            if done:
                mark = ('<font color="#2F6B3E">%s</font>&nbsp;&nbsp;'
                        % symbols["done"])
            else:
                mark = ('<font color="#8A8F98">%s</font>&nbsp;&nbsp;'
                        % symbols["todo"])
            content = inline(it).replace("\n", "<br/>")
            out.append(Paragraph(mark + content, list_s))
        out.append(Spacer(1, 5))
    elif kind == "quote":
        # 引用块：行间 + 硬换行统一用 \n 标记，渲染为 <br/>；
        # 视觉：左边深蓝竖线 + 缩进 + 浅蓝底 + 灰色字
        quote_s = ParagraphStyle("Quote", fontName="CJK", fontSize=10.5,
                                 leading=17, textColor=GREY,
                                 leftIndent=12, rightIndent=8,
                                 spaceBefore=2, spaceAfter=2)
        joined = "\n".join(b[1])
        cell_para = Paragraph(inline(joined).replace("\n", "<br/>"), quote_s)
        tbl = Table([[cell_para]], colWidths=[available])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7FB")),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, NAVY),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        out.append(Spacer(1, 2))
        out.append(tbl)
        out.append(Spacer(1, 8))
    elif kind == "code":
        lang, code_lines = b[1], b[2]
        if lang:
            out.append(Paragraph(
                '<font name="CJK" color="#595959" size="8">%s</font>' % esc(lang),
                ParagraphStyle("lang", parent=code_s, fontSize=8,
                               textColor=META, spaceAfter=0)))
        # reportlab Paragraph 会折叠连续空格，代码缩进须把空格转成 &nbsp; 保留
        body_text = "<br/>".join(
            (esc(l).replace(" ", "&nbsp;") if l else "&nbsp;")
            for l in code_lines)
        cell_para = Paragraph(body_text, code_s)
        tbl = Table([[cell_para]], colWidths=[available])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D5DA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", ( 0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        out.append(Spacer(1, 2))
        out.append(tbl)
        out.append(Spacer(1, 9))
    elif kind == "img":
        alt, path = b[1], b[2]
        # 图片相对路径须相对「md 文件所在目录」解析，而非脚本运行时的 cwd
        img_path = path if os.path.isabs(path) else os.path.join(md_dir, path)
        if os.path.exists(img_path):
            try:
                img = Image(img_path)
                iw, ih = img.imageWidth, img.imageHeight
                w = min(available, iw)
                h = ih * w / iw
                img.drawWidth, img.drawHeight = w, h
                img.hAlign = "CENTER"
                out.append(Spacer(1, 4))
                out.append(img)
                out.append(Spacer(1, 4))
            except Exception:
                out.append(Paragraph(
                    '<font color="#9E2B25">[图片缺失: %s]</font>'
                    % esc(alt or path), cell))
        else:
            out.append(Paragraph(
                '<font color="#9E2B25">[图片缺失: %s]</font>' % esc(alt or path),
                cell))
    elif kind == "table":
        header, data, colw = compute_colwidths(b[1], b[2], available)
        head_cells = [Paragraph(inline(c), cell_h) for c in header]
        body_rows = [[Paragraph(inline(c), cell) for c in row]
                     for row in data]
        t = Table([head_cells] + body_rows, colWidths=colw, repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, LINE),
            ("BOX", (0, 0), (-1, -1), 1.0, HEAD_BG),
            ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ]))
        # 短表整体保持一页；长表 repeatRows 续页重复表头
        if len(body_rows) <= 4:
            out.append(KeepTogether([Spacer(1, 2), t, Spacer(1, 6)]))
        else:
            out.append(Spacer(1, 2))
            out.append(t)
            out.append(Spacer(1, 6))
    return out


def build_flowables(blocks, available, styles, symbols, md_dir):
    """渲染全部 block 为 flowable 列表。

    章节级「标题孤行」保护：每个标题与其后「直到下一个标题之前」的全部内容
    被整体 KeepTogether 包裹。剩余空间不足容纳整段时，整段下移；若段落本身
    超过一页，reportlab 会自动拆分（不会无限溢出），标题因此总是落在章节起始
    处而非页底——彻底杜绝「标题在页底、内容在页首」的割裂。
    """
    flow = []
    body, list_s, h1, h2, h3, cell, cell_h, code_s = styles
    i = 0
    n = len(blocks)
    while i < n:
        if blocks[i][0] == "h":
            # 收集「标题 + 其后直至下一标题之前」的全部 block，整体打包
            group = _render_heading(blocks[i], h1, h2, h3)
            j = i + 1
            while j < n and blocks[j][0] != "h":
                group += _render_block(blocks[j], available, body, list_s,
                                       cell, cell_h, code_s, symbols, md_dir)
                j += 1
            flow.append(KeepTogether(group))
            i = j
        else:
            flow.extend(_render_block(blocks[i], available, body, list_s,
                                      cell, cell_h, code_s, symbols, md_dir))
            i += 1
    return flow


def build_cover(title, subtitle, author):
    today = datetime.date.today().strftime("%Y-%m-%d")
    cover = [Paragraph(title, ParagraphStyle(
        "cover_title", fontName="CJKH", fontSize=26, leading=34,
        alignment=TA_CENTER, textColor=NAVY, spaceBefore=60, spaceAfter=10))]
    if subtitle:
        cover.append(Paragraph(subtitle, ParagraphStyle(
            "cover_sub", fontName="CJK", fontSize=13, leading=20,
            alignment=TA_CENTER, textColor=colors.HexColor("#444444"),
            spaceAfter=6)))
    cover.append(HRFlowable(width="46%", thickness=2, color=NAVY,
                            spaceBefore=8, spaceAfter=10, hAlign="CENTER"))
    cover.append(Paragraph("生成日期：%s" % today, ParagraphStyle(
        "cover_meta", fontName="CJK", fontSize=10, leading=16,
        alignment=TA_CENTER, textColor=META, spaceAfter=4)))
    if author:
        cover.append(Paragraph("作者：%s" % author, ParagraphStyle(
            "cover_author", fontName="CJK", fontSize=10, leading=16,
            alignment=TA_CENTER, textColor=META, spaceAfter=4)))
    return cover


def on_page(canvas, doc):
    canvas.saveState()
    # 页眉
    canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
    canvas.setLineWidth(0.6)
    canvas.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canvas.setFont("CJK", 8)
    canvas.setFillColor(META)
    canvas.drawString(2 * cm, A4[1] - 1.35 * cm, doc.title or "Markdown PDF")
    canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.35 * cm, doc.author or "")
    # 页脚
    canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
    canvas.line(2 * cm, 1.4 * cm, A4[0] - 2 * cm, 1.4 * cm)
    canvas.drawCentredString(A4[0] / 2, 1.0 * cm, "第 %d 页" % doc.page)
    canvas.restoreState()


def convert_md_to_pdf(in_path, out_path, title=None, subtitle=None,
                      author="WorkBuddy", no_cover=False):
    with open(in_path, "r", encoding="utf-8") as f:
        text = f.read()
    CJK, CJKH, symbols = register_fonts(with_symbols=True)
    blocks = parse_blocks(text.split("\n"))
    available = A4[0] - 2 * 2.5 * cm  # 左右页边距各 2.5cm
    md_dir = os.path.dirname(os.path.abspath(in_path))

    body = ParagraphStyle("Body", fontName=CJK, fontSize=11, leading=16.5,
                          alignment=TA_LEFT, firstLineIndent=22, spaceAfter=7)
    list_s = ParagraphStyle("List", parent=body, firstLineIndent=0,
                            leftIndent=16, spaceAfter=3)
    h1 = ParagraphStyle("H1", fontName=CJKH, fontSize=18, leading=24,
                        textColor=NAVY, spaceBefore=16, spaceAfter=6,
                        keepWithNext=True)
    h2 = ParagraphStyle("H2", fontName=CJKH, fontSize=15, leading=20,
                        textColor=NAVY_H2, spaceBefore=13, spaceAfter=5,
                        keepWithNext=True)
    h3 = ParagraphStyle("H3", fontName=CJKH, fontSize=13, leading=18,
                        textColor=NAVY_H3, spaceBefore=9, spaceAfter=4,
                        keepWithNext=True)
    cell = ParagraphStyle("Cell", fontName=CJK, fontSize=9.2, leading=12.8,
                          spaceAfter=0)
    cell_h = ParagraphStyle("CellH", parent=cell, fontName=CJKH,
                            textColor=colors.white)
    code_s = ParagraphStyle("Code", fontName=CJK, fontSize=9, leading=13,
                            spaceAfter=0)
    styles = (body, list_s, h1, h2, h3, cell, cell_h, code_s)

    doc_title = title or os.path.splitext(os.path.basename(in_path))[0]
    flow = build_flowables(blocks, available, styles, symbols, md_dir)
    if not no_cover:
        flow = build_cover(doc_title, subtitle, author) + \
            [Spacer(1, 14)] + flow

    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                            topMargin=2.5 * cm, bottomMargin=2.2 * cm,
                            title=doc_title, author=author)
    doc.build(flow, onFirstPage=on_page, onLaterPages=on_page)
    print("PDF 已生成:", out_path)


def main():
    ensure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Convert Markdown to a styled Chinese PDF")
    ap.add_argument("-i", "--input", required=True, help="输入 Markdown 文件")
    ap.add_argument("-o", "--output", default=None,
                    help="输出 PDF（默认与输入同名同目录）")
    ap.add_argument("-t", "--title", default=None,
                    help="PDF 标题（默认用输入文件名）")
    ap.add_argument("--subtitle", default=None, help="封面副标题（可选）")
    ap.add_argument("--author", default="WorkBuddy",
                    help="作者（默认 WorkBuddy，页眉/封面显示）")
    ap.add_argument("--no-cover", action="store_true",
                    help="不生成封面页，直接从正文开始")
    args = ap.parse_args()
    out = args.output or os.path.splitext(args.input)[0] + ".pdf"
    convert_md_to_pdf(args.input, out, args.title, args.subtitle,
                      args.author, args.no_cover)


if __name__ == "__main__":
    main()
