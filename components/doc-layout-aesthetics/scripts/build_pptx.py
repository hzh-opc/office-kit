# -*- coding: utf-8 -*-
"""生成「版面美学观」PPTX 对照演示（本身即七大原则范例）。"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

import argparse, os
_DEFAULT_OUT_DIR = os.getcwd()  # 平台无关：默认输出当前目录，可用 --out 覆盖
_ap = argparse.ArgumentParser()
_ap.add_argument("--out", help="输出目录（默认当前目录）")
_args = _ap.parse_known_args()[0]

# ---------- 配色（主色深蓝 + 单一强调深红，克制）----------
INK    = RGBColor(0x1A, 0x1A, 0x1A)
PAPER  = RGBColor(0xFF, 0xFF, 0xFF)
NAVY   = RGBColor(0x1F, 0x3A, 0x5F)
ACCENT = RGBColor(0xC0, 0x39, 0x2B)
GREY   = RGBColor(0x6B, 0x72, 0x80)
LIGHT  = RGBColor(0xEE, 0xF1, 0xF5)
GREEN  = RGBColor(0x2E, 0x7D, 0x32)
REDBAD = RGBColor(0xB0, 0x2A, 0x1E)
SOFTRED= RGBColor(0xF7, 0xE9, 0xE7)
SOFTGRN= RGBColor(0xE7, 0xF2, 0xE9)
CODEBG = RGBColor(0xF4, 0xF5, 0xF7)

CN, EN, MONO = '思源黑体', 'Noto Sans', 'DejaVu Sans Mono'

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
TOTAL = 17

# ---------- 基础工具 ----------
def runfont(run, size=18, latin=EN, ea=CN, bold=False, color=INK, italic=False):
    run.font.size = Pt(size); run.font.bold = bold; run.font.italic = italic
    run.font.color.rgb = color; run.font.name = latin
    rPr = run._r.get_or_add_rPr()
    for tag, face in (('a:latin', latin), ('a:ea', ea), ('a:cs', latin)):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {}); rPr.append(el)
        el.set('typeface', face)

def rt(p, text, size=18, latin=EN, ea=CN, bold=False, color=INK, italic=False):
    r = p.add_run(); r.text = text
    runfont(r, size, latin, ea, bold, color, italic)
    return r

def textbox(slide, l, t, w, h, anchor=None, wrap=True):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = wrap
    if anchor is not None: tf.vertical_anchor = anchor
    return tb, tf

def rect(slide, l, t, w, h, fill, line=None, line_w=0.75):
    sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h))
    sp.shadow.inherit = False
    if fill is None: sp.fill.background()
    else: sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None: sp.line.fill.background()
    else: sp.line.color.rgb = line; sp.line.width = Pt(line_w)
    return sp

def base(title, page, subtitle=None):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid(); s.background.fill.fore_color.rgb = PAPER
    _, tf = textbox(s, 0.6, 0.32, 5, 0.3); p = tf.paragraphs[0]
    rt(p, '版面美学观', 12, CN, CN, True, NAVY)
    _, tf = textbox(s, 0.6, 0.78, 12.1, 0.85); p = tf.paragraphs[0]
    rt(p, title, 32, CN, CN, True, INK)
    rect(s, 0.62, 1.70, 1.6, 0.055, ACCENT)   # 装饰短线（重复元素）
    y0 = 2.25
    if subtitle:
        _, tf = textbox(s, 0.6, 1.82, 12.1, 0.4); p = tf.paragraphs[0]
        rt(p, subtitle, 14, CN, CN, False, GREY); y0 = 2.40
    _, tf = textbox(s, 11.4, 7.02, 1.3, 0.35); p = tf.paragraphs[0]; p.alignment = PP_ALIGN.RIGHT
    rt(p, f'{page:02d} / {TOTAL}', 11, CN, CN, False, GREY)
    rect(s, 0.6, 6.82, 12.13, 0.012, LIGHT)   # 底部分隔线（重复）
    return s, y0

def bullets(slide, l, t, w, h, items, size=18, color=INK, gap=8, bullet='• '):
    tb, tf = textbox(slide, l, t, w, h)
    first = True
    for it in items:
        lvl = 0; txt = it; bold = False; col = color
        if isinstance(it, tuple):
            txt = it[0]; lvl = it[1] if len(it) > 1 else 0
            bold = it[2] if len(it) > 2 else False
            col = it[3] if len(it) > 3 else color
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(gap); p.level = lvl
        if lvl == 0:
            r = p.add_run(); runfont(r, size, CN, CN, bold, col); r.text = bullet
        r = p.add_run(); runfont(r, size, CN, CN, bold, col); r.text = txt
    return tb

# ---------- 1 封面 ----------
s = prs.slides.add_slide(BLANK)
s.background.fill.solid(); s.background.fill.fore_color.rgb = PAPER
rect(s, 0.0, 0.0, 0.22, 7.5, NAVY)             # 左侧竖色条（对比/留白）
_, tf = textbox(s, 0.95, 2.15, 11.5, 1.5)
p = tf.paragraphs[0]; rt(p, '版面美学观', 60, CN, CN, True, INK)
_, tf = textbox(s, 0.97, 3.45, 11.5, 0.7)
p = tf.paragraphs[0]; rt(p, 'Aesthetics of Document Layout', 24, EN, EN, False, GREY)
_, tf = textbox(s, 0.97, 4.35, 11.5, 0.6)
p = tf.paragraphs[0]; rt(p, '侯捷《Word 排版艺术》提炼 · 七大原则对照演示', 20, CN, CN, False, NAVY)
rect(s, 0.99, 5.10, 2.2, 0.06, ACCENT)
_, tf = textbox(s, 0.97, 5.35, 11.5, 0.5)
p = tf.paragraphs[0]
rt(p, '来源：侯捷《Word 排版艺术》（电子工业出版社，2004）· 设计四原则 CRAP 源自 Robin Williams', 13, CN, CN, False, GREY)
_, tf = textbox(s, 0.97, 6.55, 11.5, 0.4)
p = tf.paragraphs[0]; rt(p, '本演示本身即七大原则的范例 · 由 doc-layout-aesthetics 技能生成', 13, CN, CN, True, NAVY)
# ---------- 2 核心哲学 ----------
s, y0 = base('核心哲学 · 排版是态度', 2, '工程与艺术交汇，对作品最终形貌的完全掌控')
rect(s, 0.6, y0, 5.3, 3.7, LIGHT)
_, tf = textbox(s, 0.95, y0 + 0.35, 4.7, 3.0, anchor=MSO_ANCHOR.MIDDLE)
for i, line in enumerate(['“不带 dirty work 的', '工程，', '就是一种艺术。”']):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    rt(p, line, 28, CN, CN, True, NAVY)
bullets(s, 6.3, y0 + 0.1, 6.4, 3.6, [
    ('掌握工具，专注内容创作，不为格式劳役所苦', 0, False, INK),
    ('样式（Style）是理论基石：一次定义、全局复用', 0, False, INK),
    ('自动化是规模化关键：编号 / 目录 / 索引 / 交叉引用自动生成', 0, False, INK),
    ('输出一致性：Word + Acrobat PDF 跨设备形态一致', 0, False, INK),
    ('对作品形貌的完全掌控，正是排版的“态度”', 0, True, ACCENT),
], size=18, gap=12)

# ---------- 3 七大原则总览（网格，示范重复+对齐+亲密性）----------
s, y0 = base('七大原则总览', 3, '基于对设计与内容的完全掌控：对齐 / 对比 / 亲密性 / 重复 / 留白 / 节制 / 中英文混排')
cards = [
    ('1', '对齐', 'Alignment', '元素不随意摆放，视觉成组'),
    ('2', '对比', 'Contrast', '不同就截然不同，制造焦点'),
    ('3', '亲密性', 'Proximity', '相关内容靠近成组'),
    ('4', '重复', 'Repetition', '视觉元素全文重复，建节奏'),
    ('5', '留白', 'White Space', '给版面呼吸感，最高级工具'),
    ('6', '节制', 'Restraint', '少即多，字体≤3、色克制'),
    ('7', '中英文混排', 'CJK Harmony', '字号 / 间距 / 标点和谐'),
]
cw, ch, gx, gy = 2.85, 1.85, 0.20, 0.28
x0, ytop = 0.6, 2.45
for i, (num, cn, en, desc) in enumerate(cards):
    r, c = divmod(i, 4)
    x = x0 + c * (cw + gx)
    yy = ytop + r * (ch + gy)
    rect(s, x, yy, cw, ch, PAPER, line=NAVY, line_w=1.0)
    rect(s, x, yy, 0.10, ch, ACCENT)
    _, tf = textbox(s, x + 0.28, yy + 0.18, cw - 0.4, 0.6)
    p = tf.paragraphs[0]
    rt(p, num + '  ', 22, EN, EN, True, ACCENT)
    rt(p, cn, 20, CN, CN, True, INK)
    _, tf = textbox(s, x + 0.30, yy + 0.78, cw - 0.45, 0.4)
    p = tf.paragraphs[0]; rt(p, en, 12, EN, EN, False, GREY)
    _, tf = textbox(s, x + 0.30, yy + 1.18, cw - 0.45, 0.6)
    p = tf.paragraphs[0]; rt(p, desc, 12, CN, CN, False, INK)
# ---------- 4-10 各原则 ----------
def principle(n, cn, en, oneliner, points, page):
    s, y0 = base(f'原则 {n} · {cn}', page, f'{en} — {oneliner}')
    rect(s, 0.6, y0, 1.7, 1.7, NAVY)
    _, tf = textbox(s, 0.6, y0, 1.7, 1.7, anchor=MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    rt(p, str(n), 64, EN, EN, True, PAPER)
    bullets(s, 2.7, y0 + 0.05, 10.0, 4.2, points, size=18, gap=11)

principle(1, '对齐', 'Alignment', '任何元素都不随意摆放', [
    '任何元素都不随意摆放，与页面另一项存在视觉联系',
    '中文正文两端对齐（justify）使版心左右整齐',
    '中英混排或含长英文：左对齐更安全，避免“河流”效应',
    '标题可居中（正式）或左对齐（现代），避免混用多种方式',
    '视觉对齐优先于物理对齐',
], 4)

principle(2, '对比', 'Contrast', '不同就让它截然不同', [
    '两个元素不完全相同 → 让它截然不同，制造焦点与层级',
    '手段：字号对比 / 字重对比 / 颜色对比 / 空间对比',
    '切忌“似是而非”的相似——要么相同，要么迥异',
    '本演示：深蓝主色 + 单一深红强调，即对比的克制运用',
], 5)

principle(3, '亲密性', 'Proximity', '相关内容靠近成组', [
    '相关内容靠近成组，无关内容以留白区隔',
    '标题与副标题靠近；图与图注相邻；时间 / 地点 / 主办归组',
    '仅改变间距，就能改变读者对信息分组的认知',
    '本演示：每页标题区与内容区紧邻，即亲密性的体现',
], 6)

principle(4, '重复', 'Repetition', '视觉元素全文重复', [
    '字体 / 颜色 / 线宽 / 间距 / 编号格式全文重复，建统一与节奏',
    '用“样式”固化重复，改一处即全局更新',
    '过度重复会疲劳，需在多样性中实现统一',
    '本演示：每页左上标签、装饰短线、页码、底部分隔线皆重复',
], 7)

principle(5, '留白', 'White Space', '给版面呼吸感', [
    '给版面“呼吸感”，是最高级的对齐与分组工具',
    '页边距 / 段间距 / 行距 / 图文间距都服务于留白',
    '留白不是浪费，而是引导阅读的结构手段',
    '本演示：标题下大留白、卡片间间隙，皆为刻意留白',
], 8)

principle(6, '节制', 'Restraint', '少即多', [
    '少即多（less is more）',
    '全文字体 ≤ 3 种；颜色 ≤ 主色 + 2~3 辅助',
    '慎用斜体 / 下划线 / 阴影 / 艺术字 / 多色',
    '强调靠对比与重复，不靠堆特效',
], 9)

principle(7, '中英文混排', 'CJK Harmony', '字号 / 间距 / 标点和谐', [
    '字体搭配：思源宋体 + Noto Serif（正式）/ 思源黑体 + Noto Sans（屏幕）',
    '英文比中文小 1~2pt，视觉才平衡（英文笔画简单）',
    '中英文之间、中文与数字之间加半角空格，如：中文 English 123 示例',
    '标点：中文全角、英文半角，不混用；开启避头尾与标点悬挂',
    '标题无衬线（思源黑体），正文衬线（思源宋体）',
], 10)

# ---------- 11 反例 vs 正例 对照（核心，示范对比原则本身）----------
s, y0 = base('对照演示 · 反例 vs 正例', 11, '以最容易踩坑的排版误区别，看七大原则如何落地')
rect(s, 0.6, y0, 5.9, 4.15, SOFTRED, line=REDBAD, line_w=1.25)
rect(s, 6.83, y0, 5.9, 4.15, SOFTGRN, line=GREEN, line_w=1.25)
_, tf = textbox(s, 0.9, y0 + 0.18, 5.4, 0.5)
p = tf.paragraphs[0]; rt(p, '✕  反例（常见误区）', 18, CN, CN, True, REDBAD)
_, tf = textbox(s, 7.13, y0 + 0.18, 5.4, 0.5)
p = tf.paragraphs[0]; rt(p, '✓  正例（原则落地）', 18, CN, CN, True, GREEN)
bad = [
    '用空格代替首行缩进与对齐',
    '手动输入编号、目录、页码',
    '全文居中对齐，乏味且缺设计感',
    '字体 / 颜色过载（>3 字体、花哨配色）',
    '中文用斜体、滥用下划线 / 阴影 / 艺术字',
    '两端对齐导致英文“河流”效应',
    '中英文标点混用（全角半角不分）',
]
good = [
    '用“样式”/特殊格式设缩进，不用空格',
    '编号 / 目录 / 页码 / 页眉用域自动生成',
    '以左对齐为主，必要才居中，避免混用',
    '字体 ≤ 3、单强调色，强调靠对比而非特效',
    '中文不用斜体（用加粗），克制阴影 / 艺术字',
    '混排用左对齐，杜绝“河流”',
    '中英文加半角空格，标点分全半角，开避头尾',
]
bullets(s, 0.9, y0 + 0.75, 5.4, 3.3, bad, size=15, color=REDBAD, gap=7)
bullets(s, 7.13, y0 + 0.75, 5.4, 3.3, good, size=15, color=GREEN, gap=7)

# ---------- 12 纸型速查（表格）----------
s, y0 = base('常见纸型与版心（含手账）', 12, '先定纸型与版心，原则：版心占比稳定、留白充足，页边距随纸型缩小而收紧')
rows = [
    ('纸型', '尺寸 (mm)', '典型用途', '推荐页边距 (mm)'),
    ('A4', '210 × 297', '报告 / 论文 / 合同 / 说明书', '上下 2.54，左右 3.17'),
    ('A5', '148 × 210', '小册子 / 笔记本 / 简章', '上下 1.5，左右 1.5'),
    ('A6', '105 × 148', '便签 / 卡纸 / 手账页', '上下 1.0，左右 1.0'),
    ('B5', '176 × 250', '书籍 / 杂志 / 内刊', '上下 2.0，左右 2.0'),
    ('16 开', '184 × 260', '中文图书', '上下 2.0，左右 2.0'),
    ('Letter', '215.9 × 279.4', '北美通用文档', '上下 2.54，左右 2.54'),
    ('名片', '90 × 54', '名片', '上下 5，左右 5'),
    ('明信片', '100 × 148', '明信片 / 贺卡', '上下 8，左右 8'),
    ('手账 · Hobonichi A5', '148 × 210', '日程手账', '内边 ≥ 10'),
    ('手账 · TN Passport', '124 × 89', '护照尺寸手账', '内边 ≥ 6'),
    ('手账 · Moleskine 口袋', '90 × 140', '随身本', '内边 ≥ 8'),
]
gt = s.shapes.add_table(len(rows), 4, Inches(0.6), Inches(y0), Inches(12.1), Inches(4.2)).table
gt.columns[0].width = Inches(2.9); gt.columns[1].width = Inches(2.7)
gt.columns[2].width = Inches(4.0); gt.columns[3].width = Inches(2.5)
for ri, row in enumerate(rows):
    for ci, val in enumerate(row):
        cell = gt.cell(ri, ci)
        cell.margin_left = Inches(0.08); cell.margin_right = Inches(0.08)
        cell.margin_top = Inches(0.04); cell.margin_bottom = Inches(0.04)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame; tf.word_wrap = True
        p = tf.paragraphs[0]
        if ri == 0:
            cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
            rt(p, val, 13, CN, CN, True, PAPER)
        else:
            cell.fill.solid(); cell.fill.fore_color.rgb = PAPER if ri % 2 else LIGHT
            rt(p, val, 12, CN, CN, False, INK)
# ---------- 13 网页响应式 ----------
s, y0 = base('网页排版原则（响应式）', 13, '网页是“流动版心”，用流式单位与断点适配任意宽度')
bullets(s, 0.6, y0 + 0.1, 6.2, 4.0, [
    ('版心：正文容器 max-width 65~75ch，水平居中', 0, False, INK),
    ('字号：clamp() 流式缩放，根字号 16px 起', 0, False, INK),
    ('断点：移动优先，min-width 增强（768 / 1024）', 0, False, INK),
    ('行距 1.6~1.8；段距 1~1.5em，比印刷松', 0, False, INK),
    ('对比达 WCAG AA（≥4.5:1）；深色模式切换变量', 0, False, INK),
    ('栅格：Grid auto-fit minmax 自适应列数', 0, False, INK),
    ('可达性：焦点态可见、语义标签、替代文本', 0, False, INK),
], size=16, gap=10)
code = ('font-size: clamp(1rem, 0.9rem + 0.4vw, 1.125rem);\n'
        '.container { max-width: 70ch; margin-inline: auto; }\n'
        '@media (min-width: 768px) { /* 平板增强 */ }\n'
        '@media (prefers-reduced-motion: reduce) {\n'
        '  * { animation: none; transition: none; }\n'
        '}')
rect(s, 7.1, y0 + 0.1, 5.6, 3.9, CODEBG, line=GREY, line_w=0.75)
_, tf = textbox(s, 7.35, y0 + 0.35, 5.1, 3.4, anchor=MSO_ANCHOR.TOP)
for i, line in enumerate(code.split('\n')):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.space_after = Pt(4)
    rt(p, line, 13, MONO, MONO, False, INK)
# ---------- 14 幻灯片排版（自指）----------
s, y0 = base('幻灯片排版原则（本演示即范例）', 14, '幻灯片是“远距阅读”：字要大、信息要少、对比要强')
bullets(s, 0.6, y0 + 0.1, 12.1, 4.0, [
    ('画幅：默认 16:9（13.333 × 7.5in）；老投影 4:3', 0, False, INK),
    ('字号：标题 36~44pt，正文 24~28pt，最小 ≥ 18pt（后排可读）', 0, False, INK),
    ('信息密度：每页一个观点；正文 ≤ 6 行、每行 ≤ 30 字', 0, False, INK),
    ('安全区：内容距边缘 ≥ 0.5in，避免被投影裁切', 0, False, INK),
    ('对齐与网格：左对齐为主，元素对齐隐式网格', 0, False, INK),
    ('对比：深 / 浅背景 + 单一强调色；背景勿用复杂图片', 0, False, INK),
    ('动效：克制，仅用于分步揭示；尊重 prefers-reduced-motion', 0, False, INK),
    ('→ 本演示：统一色板 / 字体 / 装饰线、≥18pt 字号、安全区，正是范例', 0, True, ACCENT),
], size=17, gap=10)

# ---------- 15 多终端显示优化 ----------
s, y0 = base('多终端显示优化（平板 / 手机）', 15, '同一内容在手机、平板、桌面都有好体验：移动优先 + 流式单位 + 响应式资源')
bullets(s, 0.6, y0 + 0.1, 12.1, 4.0, [
    ('视口：<meta name="viewport" content="width=device-width"> 必备', 0, False, INK),
    ('移动优先：先写手机基础样式，再用 min-width 增强', 0, False, INK),
    ('触控目标：按钮 / 可点元素 ≥ 44×44px，间距防误触', 0, False, INK),
    ('流式排版：clamp() 在 320~1440px 间平滑缩放', 0, False, INK),
    ('安全区：padding: env(safe-area-inset-*) 适配刘海 / 圆角', 0, False, INK),
    ('图片自适应：srcset + sizes 按 DPR 加载；max-width:100%', 0, False, INK),
    ('系统字体栈：Source Han Sans SC, "Noto Sans CJK SC", sans-serif', 0, False, INK),
    ('减少动效：prefers-reduced-motion: reduce 关闭动画', 0, False, INK),
], size=17, gap=10)

# ---------- 16 自查清单 ----------
s, y0 = base('交付前自查清单', 16, '逐条核对，确保七大原则落地（本演示亦经此清单自检）')
checks = [
    '全文只用“样式”定义格式？', '标题层级清晰（≤4 级）可自动生成目录？',
    '对齐方式统一？', '有清晰视觉焦点（对比）？',
    '相关信息成组（亲密性）？', '重复元素一致？', '留白充足？',
    '字体 ≤ 3、颜色克制？', '中英文混排字号 / 间距 / 标点处理？',
    '启用避头尾、标点悬挂？', '编号 / 目录 / 页码 / 页眉自动生成？',
    '图文有题注、编号、间距？', '输出前关闭“编辑标记”？',
]
bullets(s, 0.6, y0 + 0.1, 6.0, 4.2, [('□  ' + c) for c in checks[:7]], size=16, gap=11, bullet='')
bullets(s, 6.9, y0 + 0.1, 5.9, 4.2, [('□  ' + c) for c in checks[7:]], size=16, gap=11, bullet='')

# ---------- 17 封底 ----------
s = prs.slides.add_slide(BLANK)
s.background.fill.solid(); s.background.fill.fore_color.rgb = PAPER
rect(s, 0.0, 0.0, 0.22, 7.5, NAVY)
_, tf = textbox(s, 0.95, 2.4, 11.5, 1.2)
p = tf.paragraphs[0]; rt(p, '谢谢观看', 54, CN, CN, True, INK)
_, tf = textbox(s, 0.97, 3.7, 11.5, 0.6)
p = tf.paragraphs[0]; rt(p, '本演示由 doc-layout-aesthetics 技能生成 · 提炼自侯捷《Word 排版艺术》', 18, CN, CN, False, NAVY)
rect(s, 0.99, 4.45, 2.2, 0.06, ACCENT)
_, tf = textbox(s, 0.97, 4.7, 11.5, 1.2)
for i, line in enumerate(['原则可复用于：文档 / 网页 / 幻灯片 / 多终端',
                          '由 doc-layout-aesthetics 技能生成 · 提炼自侯捷《Word 排版艺术》']):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.space_after = Pt(6)
    rt(p, line, 15, CN, CN, False, GREY)
out = os.path.join(_args.out or _DEFAULT_OUT_DIR, '版面美学观_对照演示.pptx')
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
prs.save(out)
print('saved:', out, '| slides:', len(prs.slides._sldIdLst))
