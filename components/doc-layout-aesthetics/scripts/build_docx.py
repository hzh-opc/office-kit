# -*- coding: utf-8 -*-
"""生成《版面美学观》精排 Word 文档，自身即示范侯捷《Word 排版艺术》的排版原则。

说明：本模块把构建逻辑收进 build()/main()，模块顶层只保留可复用的纯函数
（protect_table 等），因此可被 selfcheck.py 与 pytest 安全 import 而不触发构建。
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import argparse
import os

DEFAULT_OUT_DIR = os.getcwd()  # 平台无关：默认输出当前目录，可用 --out 覆盖
DOCX_NAME = "版面美学观_侯捷Word排版艺术提炼.docx"


# ---------- 字体与样式工具 ----------
def set_east_asian(run, font):
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    for attr in ('w:eastAsia', 'w:ascii', 'w:hAnsi'):
        rfonts.set(qn(attr), font)


def set_style_font(style, font, size=None, bold=None, color=None):
    style.font.name = font
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    for attr in ('w:eastAsia', 'w:ascii', 'w:hAnsi'):
        rfonts.set(qn(attr), font)
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color


def shade_cell(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


def set_cell_margins(cell, top=80, bottom=80, left=120, right=120):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement('w:tcMar')
    for tag, val in (('top', top), ('bottom', bottom), ('start', left), ('end', right)):
        e = OxmlElement('w:' + tag)
        e.set(qn('w:w'), str(val))
        e.set(qn('w:type'), 'dxa')
        m.append(e)
    tcPr.append(m)


def protect_table(table, mode='long'):
    """跨页显示优化，按表格长短分两种策略。

    mode='long'（默认，长表格）：表头行重复(tblHeader) + 禁止单行跨页断行(cantSplit)，
        避免表格在行中间被截断、续页丢失表头。
    mode='short'（短表格）：整表保持在一页——对表内所有段落设 keepNext+keepLines，
        并令其与前一段(标题/引导语)同页；不逐行禁断，适合 1~2 屏可容纳的短表。
    """
    if mode == 'short':
        _keep_table_together(table)
        return
    for i, row in enumerate(table.rows):
        trPr = row._tr.get_or_add_trPr()
        if i == 0:
            h = trPr.find(qn('w:tblHeader'))
            if h is None:
                h = OxmlElement('w:tblHeader')
                trPr.append(h)
            h.set(qn('w:val'), 'true')
        cs = trPr.find(qn('w:cantSplit'))
        if cs is None:
            cs = OxmlElement('w:cantSplit')
            trPr.append(cs)
        cs.set(qn('w:val'), 'true')


def _keep_table_together(table):
    """短表格：整表保持在一页。对表内所有段落设 keepNext+keepLines，并令前一段与本表同页。"""
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                pPr = p._p.get_or_add_pPr()
                for tag in ('w:keepNext', 'w:keepLines'):
                    if pPr.find(qn(tag)) is None:
                        pPr.append(OxmlElement(tag))
    prev = table._tbl.getprevious()
    if prev is not None and prev.tag == qn('w:p'):
        pPr = prev.get_or_add_pPr()
        if pPr.find(qn('w:keepNext')) is None:
            pPr.append(OxmlElement('w:keepNext'))


# ---------- 文档构建 ----------
def build(out_dir):
    """构建完整文档并保存到 out_dir，返回生成的 docx 路径。"""
    doc = Document()

    # 纸张 A4（210×297mm）+ 页边距：上/下 2.54cm，左/右 3.17cm（示范推荐值，与规范表一致）
    for s in doc.sections:
        s.page_width = Cm(21.0)
        s.page_height = Cm(29.7)
        s.top_margin = Cm(2.54)
        s.bottom_margin = Cm(2.54)
        s.left_margin = Cm(3.17)
        s.right_margin = Cm(3.17)

    # 默认样式：思源宋体 / 小四(12pt) / 1.5 倍行距
    normal = doc.styles['Normal']
    set_style_font(normal, '思源宋体', size=12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)

    for lvl, (sz, color) in {1: (16, RGBColor(0x1a, 0x1a, 0x1a)),
                             2: (15, RGBColor(0x1a, 0x1a, 0x1a)),
                             3: (12, RGBColor(0x1a, 0x1a, 0x1a))}.items():
        st = doc.styles['Heading %d' % lvl]
        set_style_font(st, '思源黑体', size=sz, bold=True, color=color)
        st.paragraph_format.space_before = Pt(12 if lvl == 1 else 8)
        st.paragraph_format.space_after = Pt(4)
        st.paragraph_format.line_spacing = 1.3

    # ---------- 封面 ----------
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run('版面美学观')
    set_east_asian(r, '思源黑体')
    r.font.size = Pt(30); r.font.bold = True; r.font.color.rgb = RGBColor(0x10, 0x10, 0x10)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run('侯捷《Word 排版艺术》提炼 · 可复用排版规范')
    set_east_asian(r, '思源黑体')
    r.font.size = Pt(14); r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run('对齐 · 对比 · 亲密性 · 重复 · 留白 · 节制 · 中英文混排')
    set_east_asian(r, '思源宋体')
    r.font.size = Pt(11); r.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

    doc.add_paragraph()

    # ---------- 一、核心哲学 ----------
    doc.add_heading('一、核心哲学（态度论）', level=1)
    philosophy = [
        ('艺术与工程交汇', '排版不是纯技术，也不是纯艺术；「不带 dirty work 的工程，就是一种艺术」。'),
        ('排版是态度', '对作品最终形貌的完全掌控——每个字、每张图的大小、颜色、粗细、位置都在自己手里。'),
        ('工具服务于创作', '掌握 Word 是为了「专注于内容创作，不为劳役所苦」，把人从繁琐格式中解放。'),
        ('样式是理论基石', '一次定义、全局复用，是效率与一致性的根源；手动局部格式是脏活与风险来源。'),
        ('自动化是规模化关键', '章节/图表自动编号、目录、索引、交叉引用、页眉页脚均应力求自动生成。'),
        ('输出一致性', 'Word + Acrobat 制作 PDF，保证文档在不同设备上阅读形态一致。'),
    ]
    for k, v in philosophy:
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run(k + '：')
        set_east_asian(r, '思源黑体'); r.font.bold = True
        r2 = p.add_run(v)
        set_east_asian(r2, '思源宋体')

    # ---------- 二、七大原则 ----------
    doc.add_heading('二、七大美学原则（体系）', level=1)
    doc.add_paragraph('基于 Robin Williams 的 CRAP 四原则（对比 / 重复 / 对齐 / 亲密性），'
                      '扩展为中文 Word 文档的「七大原则」。').italic = True

    principles = [
        ('1. 对齐 Alignment', '任何元素都不随意摆放；每一项都与页面上另一项存在视觉联系。'
         '中文正文两端对齐使版心整齐；中英混排或含长英文单词时左对齐更安全，避免「河流」效应。'
         '标题可居中或左对齐；避免同一版面混用多种对齐。视觉对齐优先于物理对齐。'),
        ('2. 对比 Contrast', '若两元素不完全相同，就让它截然不同，制造视觉焦点与层级。'
         '手段：字号、字重、颜色、空间对比。切忌「似是而非」的相似——要么相同，要么迥异。'),
        ('3. 亲密性 Proximity', '相关内容靠近成组，无关内容以留白区隔。标题与副标题靠近；'
         '图与图注相邻；时间/地点/主办归组。仅改变间距，就能改变读者对分组的理解。'),
        ('4. 重复 Repetition', '视觉元素（字体、颜色、线宽、间距、编号格式）在全文重复，建立统一与节奏。'
         '用「样式」固化重复；过度重复会疲劳，需在多样性中实现统一。'),
        ('5. 留白 White Space', '给版面「呼吸感」，是最高级的对齐与分组工具。'
         '页边距、段距、行距、图文间距都服务于留白。留白不是浪费，而是引导阅读的结构手段。'),
        ('6. 节制 Restraint', '少即多。全文字体 ≤ 3 种；颜色 ≤ 主色 + 2~3 辅助色。'
         '慎用斜体、下划线、阴影、艺术字；强调靠对比与重复，不靠堆特效。'),
        ('7. 中英文混排和谐 CJK Harmony', '中文文档专属。字体：正文 思源宋体+Noto Serif（正式）或 '
         '思源黑体+Noto Sans（屏幕）。英文比中文小 1~2pt 才平衡；中英文间、中文与数字间加半角空格；'
         '中文全角、英文半角标点不混用，开启避头尾与标点悬挂。标题用无衬线，正文用衬线。'),
    ]
    for title, body in principles:
        doc.add_heading(title, level=2)
        p = doc.add_paragraph(body)
        set_east_asian(p.runs[0], '思源宋体')

    # ---------- 三、原则示范：同一段文字的「反例」与「正例」----------
    doc.add_heading('三、原则示范：同一段文字的「反例」与「正例」', level=1)
    doc.add_paragraph('左栏刻意违反多条原则（居中、字体杂乱、无缩进、密排），右栏套用七大原则。').italic = True

    tbl = doc.add_table(rows=2, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = 'Table Grid'
    hdr = tbl.rows[0].cells
    hdr[0].text = ''; hdr[1].text = ''
    c0 = hdr[0].paragraphs[0]; r0 = c0.add_run('反例 · 错误示范')
    set_east_asian(r0, '思源黑体'); r0.font.bold = True; r0.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
    c1 = hdr[1].paragraphs[0]; r1 = c1.add_run('正例 · 原则示范')
    set_east_asian(r1, '思源黑体'); r1.font.bold = True; r1.font.color.rgb = RGBColor(0x00, 0x60, 0x20)
    shade_cell(hdr[0], 'F7E0E0'); shade_cell(hdr[1], 'E0F2E5')
    for cell in hdr:
        set_cell_margins(cell)

    # 反例单元格：居中对齐、字体杂乱、无缩进、密排
    bad = tbl.rows[1].cells[0]
    set_cell_margins(bad)
    bp = bad.paragraphs[0]; bp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = bp.add_run('版面美学观'); set_east_asian(r, '霞鹜文楷'); r.font.size = Pt(15); r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    bp2 = bad.add_paragraph(); bp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = bp2.add_run('——来自侯捷老师的启发'); set_east_asian(r, '思源黑体'); r.font.size = Pt(9)
    bp3 = bad.add_paragraph(); bp3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = bp3.add_run('排版不是纯技术也不是纯艺术。'); set_east_asian(r, '思源宋体'); r.font.size = Pt(10)
    bp4 = bad.add_paragraph(); bp4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = bp4.add_run('掌握 Word 是为了专注于内容创作，不为劳役所苦。'); set_east_asian(r, '思源黑体'); r.font.size = Pt(11); r.font.color.rgb = RGBColor(0x00, 0x00, 0xC0)
    bp5 = bad.add_paragraph(); bp5.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = bp5.add_run('样式是理论基石，一次定义全局复用。'); set_east_asian(r, '霞鹜文楷'); r.font.size = Pt(10); r.font.color.rgb = RGBColor(0x80, 0x00, 0x80)
    for p in bad.paragraphs:
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(0)

    # 正例单元格：两端对齐、统一思源宋体、首行缩进、1.5 行距、合理段距
    good = tbl.rows[1].cells[1]
    set_cell_margins(good)
    gp = good.paragraphs[0]; gp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = gp.add_run('版面美学观'); set_east_asian(r, '思源黑体'); r.font.size = Pt(15); r.font.bold = True; r.font.color.rgb = RGBColor(0x10, 0x10, 0x10)
    gp2 = good.add_paragraph(); gp2.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = gp2.add_run('——来自侯捷老师的启发'); set_east_asian(r, '思源黑体'); r.font.size = Pt(10); r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    gp3 = good.add_paragraph(); gp3.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = gp3.add_run('排版不是纯技术，也不是纯艺术；「不带 dirty work 的工程，就是一种艺术」。')
    set_east_asian(r, '思源宋体'); r.font.size = Pt(12)
    gp3.paragraph_format.first_line_indent = Pt(24)
    gp4 = good.add_paragraph(); gp4.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = gp4.add_run('掌握 Word 是为了专注于内容创作，不为劳役所苦。样式是理论基石：一次定义、全局复用，'
                    '是效率与一致性的根源。')
    set_east_asian(r, '思源宋体'); r.font.size = Pt(12)
    gp4.paragraph_format.first_line_indent = Pt(24)
    for p in good.paragraphs:
        p.paragraph_format.line_spacing = 1.5
        p.paragraph_format.space_after = Pt(6)

    protect_table(tbl, mode='short')

    # ---------- 四、参数规范表 ----------
    doc.add_heading('四、具体参数规范（可直接套用）', level=1)
    spec = [
        ('纸张', 'A4（210×297mm）', '通用标准'),
        ('页边距', '上/下 2.54cm，左/右 3.17cm', '装订可加 2cm 装订线'),
        ('正文', '思源宋体 / 小四(12pt) 或 五号(10.5pt)', '衬线，利阅读'),
        ('一级标题', '思源黑体 / 三号(16pt) 或 22pt，加粗', '无衬线'),
        ('二级标题', '思源黑体 / 小三(15pt) 或 18pt', ''),
        ('三级标题', '思源黑体 / 小四(12pt) 或 16pt', ''),
        ('行距', '1.5 倍 或 固定值 28 磅', '混排可 1.5~2 倍'),
        ('段距', '段前/段后 0.5 行 或 6~12 磅', '标题处加大'),
        ('首行缩进', '2 字符', '用「特殊格式」，勿用空格'),
        ('对齐', '正文两端对齐(纯中文)/左对齐(混排)', ''),
        ('字体数', '≤ 3 种', '思源黑体(标题)+思源宋体(正文)+1 英文'),
        ('颜色', '正文黑；强调深蓝/深红', '主色 + ≤3 辅助'),
        ('留白', '页边距 ≥2.5cm，段间有距', '呼吸感'),
    ]
    stbl = doc.add_table(rows=1, cols=3)
    stbl.style = 'Table Grid'
    stbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    hc = stbl.rows[0].cells
    for i, h in enumerate(['维度', '推荐值', '说明']):
        set_cell_margins(hc[i]); shade_cell(hc[i], 'DCE6F1')
        pr = hc[i].paragraphs[0]; rr = pr.add_run(h); set_east_asian(rr, '思源黑体'); rr.font.bold = True
    for dim, val, note in spec:
        row = stbl.add_row().cells
        for i, txt in enumerate((dim, val, note)):
            set_cell_margins(row[i])
            pr = row[i].paragraphs[0]; rr = pr.add_run(txt)
            set_east_asian(rr, '思源宋体'); rr.font.size = Pt(10.5)

    protect_table(stbl)

    # ---------- 五、自查清单 ----------
    doc.add_heading('五、排版自查清单（交付前逐条核对）', level=1)
    checklist = [
        '全文是否只用「样式」定义格式（无手动局部格式）？',
        '标题层级是否清晰（≤4 级）且可自动生成目录？',
        '对齐方式是否统一（无多种对齐混用）？',
        '是否有清晰视觉焦点（对比）？',
        '相关信息是否成组（亲密性）？',
        '重复元素（字体/颜色/编号格式）是否一致？',
        '留白是否充足（页边距、段距、行距）？',
        '字体是否 ≤3 种、颜色是否克制？',
        '中英文混排：字号、间距、标点是否处理？',
        '是否启用避头尾、标点悬挂？',
        '编号/目录/页码/页眉是否自动生成（非手填）？',
        '图文是否有题注、编号、适当间距？',
        '打印/PDF 输出前是否关闭「编辑标记」？',
    ]
    for item in checklist:
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run('☐ ' + item)
        set_east_asian(r, '思源宋体')

    # ---------- 六、反模式 ----------
    doc.add_heading('六、反模式（务必避免）', level=1)
    anti = [
        '用空格代替首行缩进 / 对齐。',
        '手动输入编号、目录、页码。',
        '全文居中对齐（初学者陷阱，乏味且缺设计感）。',
        '字体 / 颜色过载（>3 字体、花哨配色）。',
        '滥用斜体、下划线、阴影、艺术字。',
        '两端对齐导致英文「河流」效应。',
        '中文使用斜体（中文无斜体概念，强调用加粗替代）。',
        '标点混用（中文全角与英文半角混排不分）。',
    ]
    for item in anti:
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run('✗ ' + item)
        set_east_asian(r, '思源宋体'); r.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)

    # ---------- 七、Word 实现要点 ----------
    doc.add_heading('七、Word 实现要点（工程侧）', level=1)
    impl = [
        ('样式', '基准为正文；标题样式链接「多级列表」实现自动编号；改一处即全局更新。'),
        ('分节', '封面无页码、目录罗马数字、正文阿拉伯数字；插「下一页分节符」并取消「链接到前一条页眉」。'),
        ('域', '交叉引用、题注、目录、索引均用域自动生成与更新。'),
        ('图文', '图片居中 + 适当间距；加题注并通过交叉引用引用。'),
        ('输出', 'Word → Acrobat PDF 保证跨设备一致；长文档（≥3 页加页码，≥5 页加目录）。'),
    ]
    for k, v in impl:
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run(k + '：'); set_east_asian(r, '思源黑体'); r.font.bold = True
        r2 = p.add_run(v); set_east_asian(r2, '思源宋体')

    # ---------- 八、常见纸型（含手账）与版心 ----------
    doc.add_heading('八、常见纸型（含手账）与版心', level=1)
    doc.add_paragraph('不同媒介先定纸型与版心（文字可排区域）。页边距随纸型缩小而收紧，原则是版心占比稳定、留白充足。')

    paper_rows = [
        ('A4', '210×297', '报告/论文/合同/说明书', '上下2.54，左右3.17(装订+2cm)'),
        ('A5', '148×210', '小册子/笔记本/简章', '上下1.5，左右1.5'),
        ('A6', '105×148', '便签/卡纸/手账页', '上下1.0，左右1.0'),
        ('B5', '176×250', '书籍/杂志/内刊', '上下2.0，左右2.0'),
        ('B6', '125×176', '口袋书/便携本', '上下1.2，左右1.2'),
        ('16开', '184×260(或195×270)', '中文图书', '上下2.0，左右2.0'),
        ('32开', '130×184', '中文小书/手册', '上下1.5，左右1.5'),
        ('Letter', '215.9×279.4', '北美通用文档', '上下2.54，左右2.54'),
        ('Legal', '215.9×355.6', '法律/合同长文', '上下2.54，左右2.54'),
        ('名片', '90×54', '名片', '上下5，左右5(mm)'),
        ('明信片', '100×148', '明信片/贺卡', '上下8，左右8'),
        ('手账·Hobonichi A6', '105×148', '日程手账', '内边≥8'),
        ('手账·Hobonichi A5', '148×210', '日程手账', '内边≥10'),
        ('手账·Traveler\'s Notebook', '110×210', '旅行手账', '内边≥8'),
        ('手账·TN Passport', '124×89', '护照尺寸手账', '内边≥6'),
        ('手账·Moleskine 大', '130×210', '笔记本/手账', '内边≥10'),
        ('手账·Moleskine 口袋', '90×140', '随身本', '内边≥8'),
        ('方格/网格本', '多尺寸', '手账/笔记', '跟随格线对齐'),
    ]

    def add_spec_table(title_cells, rows, mode='long'):
        t = doc.add_table(rows=1, cols=len(title_cells))
        t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(title_cells):
            c = t.rows[0].cells[i]
            set_cell_margins(c); shade_cell(c, 'DCE6F1')
            pr = c.paragraphs[0]; rr = pr.add_run(h)
            set_east_asian(rr, '思源黑体'); rr.font.bold = True
        for r in rows:
            cells = t.add_row().cells
            for i, txt in enumerate(r):
                set_cell_margins(cells[i])
                pr = cells[i].paragraphs[0]; rr = pr.add_run(txt)
                set_east_asian(rr, '思源宋体'); rr.font.size = Pt(10.5)
        protect_table(t, mode=mode)
        return t

    add_spec_table(['纸型', '尺寸(mm)', '典型用途', '推荐页边距'], paper_rows, mode='long')

    doc.add_heading('手账排版要点（小版面、强亲密性）', level=3)
    for it in [
        '版心小、留白多；以格线 / 点位（dot grid）为对齐基准，而非硬边距。',
        '字号小（8~10pt），行距紧凑（1.2~1.3）；用色块 / 胶带 / 贴纸分区，而非大字号。',
        '图文混排重亲密性：照片、贴纸、手写字成组相邻；避免满版，保留呼吸区。',
        '中英文混排同样加半角空格、开启避头尾；手写感字体仅作点缀，不伤可读。',
    ]:
        p = doc.add_paragraph(style='List Bullet'); r = p.add_run(it); set_east_asian(r, '思源宋体')

    # ---------- 九、跨媒介适配要点（网页/幻灯片/多终端）----------
    doc.add_heading('九、跨媒介适配要点（网页 / 幻灯片 / 多终端）', level=1)
    doc.add_paragraph('同一套美学原则，落到不同媒介有不同参数。以下为速查；完整说明见技能 references 第八~十一节。').italic = True

    doc.add_heading('网页（响应式）', level=3)
    add_spec_table(['维度', '推荐值'], [
        ('版心宽度', 'max-width 65~75ch，中文每行 35~45 字，居中'),
        ('流式字号', 'clamp(1rem, 0.9rem+0.4vw, 1.125rem)，根 16px'),
        ('断点', '手机<640 / 平板 640~1024 / 桌面>1024，移动优先'),
        ('行距段距', '行距 1.6~1.8；段距 1~1.5em'),
        ('对比度', '正文≥WCAG AA(4.5:1)；CSS 变量管色'),
        ('深色模式', 'prefers-color-scheme: dark 切换变量'),
        ('栅格', 'Grid auto-fit minmax(280px,1fr) / Flexbox'),
        ('可达性', '焦点可见、语义标签、prefers-reduced-motion'),
    ], mode='short')

    doc.add_heading('幻灯片', level=3)
    add_spec_table(['维度', '推荐值'], [
        ('画幅', '16:9(254×190.5mm) 默认；4:3 老投影；16:10 超宽'),
        ('字号', '标题 36~44pt，正文 24~28pt，最小≥18pt'),
        ('信息密度', '每页一观点；正文≤6 行、每行≤30 字'),
        ('安全区', '内容距边≥0.5in，防裁切'),
        ('对齐', '左对齐为主，对齐隐式网格'),
        ('对比', '深浅背景+单一强调色；背景勿抢戏'),
        ('图片', '统一边框/满幅，object-fit:cover 不变形'),
        ('动效', '克制，仅分步揭示；尊重 reduced-motion'),
    ], mode='short')

    doc.add_heading('多终端（平板 / 手机）', level=3)
    add_spec_table(['维度', '推荐值'], [
        ('视口', '<meta viewport width=device-width, initial-scale=1>'),
        ('移动优先', '先手机样式，min-width 增强；不写死 px 宽'),
        ('触控目标', '可点元素≥44×44px / 48dp，间距防误触'),
        ('流式排版', 'clamp() 在 320~1440px 平滑缩放'),
        ('安全区', 'env(safe-area-inset-*) 适配刘海/圆角'),
        ('图片', 'srcset+sizes 按 DPR 加载；max-width:100%'),
        ('可读行宽', '移动端每行 30~40 汉字'),
        ('系统字体', 'Source Han Sans SC, Noto Sans CJK SC, sans-serif'),
        ('减少动效', 'prefers-reduced-motion 关动画'),
    ], mode='short')

    # ---------- 来源 ----------
    doc.add_heading('来源与依据', level=1)
    src = doc.add_paragraph()
    src.add_run('侯捷《Word 排版艺术》，电子工业出版社，2004（ISBN 9787121004216，豆瓣 8.6）。'
                '核心哲学源自作者自序；设计四原则（CRAP）由 Robin Williams《The Non-Designer’s Design Book》'
                '提出、侯捷引入中文 Word 语境；中英文混排与标点细节参考业界中文排版规范。').italic = True
    set_east_asian(src.runs[0], '思源宋体')
    src.runs[0].font.size = Pt(10.5); src.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, DOCX_NAME)
    doc.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description="生成《版面美学观》精排 Word 文档")
    ap.add_argument("--out", help="输出目录（默认当前目录）")
    args = ap.parse_args()
    out = build(args.out or DEFAULT_OUT_DIR)
    print('saved:', out)


if __name__ == "__main__":
    main()
