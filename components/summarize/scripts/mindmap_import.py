#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mindmap_import.py — 思维导图反向导入（本地、零依赖）

把「脑图 / 大纲」反向导入回摘要技能生态：解析多种脑图源（markdown 标题层级、
嵌套列表、mermaid `mindmap` 块），保留层级结构构建节点树，再输出为：

  - md   ：嵌套要点大纲（保留层级，可一键粘贴进 markmap / XMind / 语雀等脑图工具）
  - json ：树状结构 {text, depth, children:[...]}，便于程序化消费
  - txt  ：展平为一行一节点的纯文本

并可选 `--re-summarize`：把展平文本喂回本技能 `summarize.py` 引擎，产出一份
「由脑图还原的摘要」。这是 `mindmap` 协同能力（摘要→脑图）的**反向闭环**——
用户从脑图工具导出的大纲也能重新成为可摘要、可检索、可追问的文本。

支持的输入形态：
  1. markdown 标题层级： `#`/`##`/... 数量即层级；
  2. 嵌套列表：以 `-`/`*`/`+` 或 `1.`/`（1）` 开头、按缩进表达层级；
  3. mermaid `mindmap` 块：```mermaid ... mindmap ... ``` 或独立 `mindmap` 起头的文本，
     按缩进表达层级，自动剥离 `id[text]`/`id(text)`/`id((text))`/`::icon()` 等语法噪音。

本脚本**不依赖任何外部技能**；纯标准库实现（零依赖、跨平台）。
"""

import sys
import os
import re
import json
import argparse

# ---------------------------------------------------------------------------
# 读入
# ---------------------------------------------------------------------------
def read_text(path):
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 形态识别 + 逐行 (depth, text) 解析
# ---------------------------------------------------------------------------
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LIST_BULLET = re.compile(r"^(\s*)([-*+]|\d+[.、)]\s+|（\d+）\s+|\(?\d+\)\s+)\s*(.*\S)?\s*$")
MERMAID_FENCE = re.compile(r"^\s*```(\w*)\s*$", re.I)
MERMAID_SHAPE = re.compile(r"[\[({](.+?)[\]})]")


def clean_mermaid_text(raw):
    """剥离 mermaid 节点语法噪音：id[text] / id(text) / id((text)) / ::icon(...) 。"""
    s = raw.strip()
    s = re.sub(r"::icon\([^)]*\)", "", s)          # 图标语法
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)    # 换行标签
    # 去掉 id 前缀（仅当后接括号形状，如 `root((..))`/`id[text]`；
    # 纯文本节点如 `Shor 算法` 不应被误剥）
    s = re.sub(r"^([A-Za-z0-9_\-]+)(?=\s*[\[({])", "", s)
    # 反复剥离最外层括号（兼容 ((text)) / [text] / {text} 及它们的组合）
    changed = True
    while changed:
        changed = False
        for op, cl in (("(", ")"), ("[", "]"), ("{", "}")):
            if len(s) >= 2 and s.startswith(op) and s.endswith(cl):
                s = s[1:-1].strip()
                changed = True
                break
    return s.strip()


def detect_and_parse(text):
    """返回 [(level, text), ...] 节点序列（level 为相对层级，越小越靠根）。

    解析优先级：
      1) 若内含 mermaid `mindmap` 块 → 走 mermaid 模式（按缩进表达层级）；
      2) 否则走统一混合模式：markdown `#` 标题层级 + 嵌套列表 + 纯缩进文本行，
         标题作为层级锚点，其下列表项按缩进嵌套（兼容「标题为主、列表为辅」的常见脑图导出）。
    """
    lines = text.splitlines()

    # 1) 提取 mermaid 块；命中 mindmap 进入 mermaid 模式
    mermaid_blocks = []
    in_fence = False
    fence_lang = ""
    buf = []
    for ln in lines:
        fm = MERMAID_FENCE.match(ln)
        if fm:
            if not in_fence:
                in_fence = True
                fence_lang = (fm.group(1) or "").lower()
                buf = []
            else:
                in_fence = False
                mermaid_blocks.append((fence_lang, buf))
                fence_lang = ""
        elif in_fence:
            buf.append(ln)
    if in_fence:  # 未闭合 fence 兜底
        mermaid_blocks.append((fence_lang, buf))
    mindmap_block = None
    for lang, blk in mermaid_blocks:
        if "mindmap" in (lang or "") or any(re.match(r"^\s*mindmap\s*$", l) for l in blk):
            mindmap_block = blk
            break
    if mindmap_block is not None:
        return _parse_mermaid(mindmap_block)

    # 2) 统一混合模式（标题 + 列表 + 纯缩进）
    nodes = []
    last_heading_level = 0
    for ln in lines:
        if not ln.strip():
            continue
        hm = HEADING.match(ln)
        if hm:
            lvl = len(hm.group(1))
            last_heading_level = lvl
            nodes.append((lvl, hm.group(2).strip()))
            continue
        lm = LIST_BULLET.match(ln)
        if lm:
            indent = len(lm.group(1))
            txt = (lm.group(3) or "").strip()
            if not txt:
                continue
            lvl = (last_heading_level + 1 + indent // 2) if last_heading_level else (1 + indent // 2)
            nodes.append((lvl, txt))
            continue
        # 纯缩进文本行（无 bullet）
        stripped = ln.lstrip(" ")
        if not stripped.strip():
            continue
        indent = len(ln) - len(stripped)
        lvl = (last_heading_level + 1 + indent // 2) if last_heading_level else (1 + indent // 2)
        nodes.append((lvl, stripped.strip()))
    return nodes


def _parse_mermaid(block):
    """mermaid mindmap：root 在 col0，子节点按缩进逐层加深。"""
    nodes = []
    started = False
    for ln in block:
        s = ln.rstrip()
        if not s.strip():
            continue
        if re.match(r"^\s*mindmap\s*$", s):
            started = True
            continue
        if not started:
            # mindmap 关键词前的行（如 ``` 之后直接是节点）忽略，等待 mindmap 起头
            continue
        indent = len(s) - len(s.lstrip(" "))
        depth = indent // 2 if indent >= 2 else (1 if indent > 0 else 0)
        txt = clean_mermaid_text(s.strip())
        if txt:
            nodes.append((depth, txt))
    return nodes


# ---------------------------------------------------------------------------
# 由 (level, text) 构建节点树
# ---------------------------------------------------------------------------
def build_tree(nodes):
    stack = []          # (depth, node)
    roots = []
    for depth, text in nodes:
        node = {"text": text, "depth": depth, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1]["children"].append(node)
        stack.append((depth, node))
    return roots


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------
def render_md(roots):
    lines = ["# 思维导图反向导入（嵌套大纲）", ""]
    lines.append("> 由脑图 / 大纲源反向导入，层级结构已保留。")
    lines.append("")

    def walk(node, depth):
        pad = "  " * depth
        lines.append("%s- %s" % (pad, node["text"]))
        for c in node["children"]:
            walk(c, depth + 1)

    for r in roots:
        walk(r, 0)
    return "\n".join(lines)


def render_txt(roots):
    out = []
    def walk(node):
        out.append("  " * node["depth"] + node["text"])
        for c in node["children"]:
            walk(c)
    for r in roots:
        walk(r)
    return "\n".join(out)


def flatten_text(roots):
    out = []
    def walk(node):
        out.append(node["text"])
        for c in node["children"]:
            walk(c)
    for r in roots:
        walk(r)
    return "\n".join(out)


def render_markmap_md(roots):
    """把节点树渲染为 markmap 可识别的 markdown：根作 # 标题，子节点作嵌套 - 列表。"""
    lines = []
    for r in roots:
        lines.append("# " + r["text"])
        def walk(node, depth):
            pad = "  " * depth
            lines.append("%s- %s" % (pad, node["text"]))
            for c in node["children"]:
                walk(c, depth + 1)
        for c in r["children"]:
            walk(c, 0)
    return "\n".join(lines)


def render_markmap_html(roots, title="思维导图"):
    """生成自包含 HTML，嵌入 markmap-autoloader（CDN），浏览器打开即渲染可交互脑图。

    注意：查看时需联网加载 markmap 查看器（仅查看器来自 CDN，数据本身为本地生成）；
    若需完全离线，可把 --format md 的输出粘贴进已安装的 markmap 编辑器/插件。
    """
    md = render_markmap_md(roots)
    # 转义 HTML 特殊字符，markmap 解析 textContent 时会还原为原始 markdown
    esc = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>%s · markmap</title>\n"
        "<style>body{margin:0;font-family:system-ui,-apple-system,sans-serif}</style>\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18\"></script>\n"
        "</head>\n<body>\n<div class=\"markmap\">\n%s\n</div>\n</body>\n</html>\n"
        % (title, esc)
    )


def stats_of(roots):
    nodes = 0
    max_depth = 0
    def walk(node):
        nonlocal nodes, max_depth
        nodes += 1
        max_depth = max(max_depth, node["depth"])
        for c in node["children"]:
            walk(c)
    for r in roots:
        walk(r)
    return {"node_count": nodes, "max_depth": max_depth + 1, "root_count": len(roots)}


# ---------------------------------------------------------------------------
# 可选：喂回 summarize 引擎做「由脑图还原的摘要」
# ---------------------------------------------------------------------------
def re_summarize(flat_text, length=None, keywords_k=8):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from summarize import summarize
    except Exception:
        return None
    if not flat_text.strip():
        return None
    res = summarize([flat_text], length=length, keywords_k=keywords_k,
                    do_eval=False, brief=False, multi=False, cite=False)
    return res.get("summary", "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="思维导图反向导入（脑图→大纲/树/json，可还原摘要，可 markmap 渲染）")
    ap.add_argument("input", help="脑图/大纲源文件（或 - 读 stdin）")
    ap.add_argument("--format", default="md", choices=["md", "json", "txt"])
    ap.add_argument("--out", default=None, help="输出文件路径")
    ap.add_argument("--re-summarize", action="store_true",
                    help="把展平文本喂回 summarize.py 引擎，额外输出由脑图还原的摘要")
    ap.add_argument("--length", type=int, default=3, help="--re-summarize 时的摘要句数")
    ap.add_argument("--keywords", type=int, default=6, help="--re-summarize 时的关键词数")
    ap.add_argument("--markmap", action="store_true",
                    help="生成可直接渲染的自包含 HTML（嵌入 markmap-autoloader），浏览器打开即见交互脑图")
    ap.add_argument("--title", default="", help="--markmap 时的 HTML 标题（默认取首节点文本）")
    args = ap.parse_args()

    text = read_text(args.input)
    nodes = detect_and_parse(text)
    if not nodes:
        sys.stderr.write("警告：未从输入解析出任何节点。\n")
        roots = []
    else:
        roots = build_tree(nodes)
    st = stats_of(roots)

    if args.markmap:
        title = args.title or (roots[0]["text"] if roots else "思维导图")
        out = render_markmap_html(roots, title)
        if not args.out:
            base = os.path.splitext(os.path.basename(args.input))[0] if args.input != "-" else "mindmap"
            args.out = base + ".mm.html"
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入 markmap HTML：%s（节点数=%d，最大层级=%d）\n"
                         % (args.out, st["node_count"], st["max_depth"]))
        return

    if args.format == "json":
        payload = {"stats": st, "tree": roots}
        if args.re_summarize:
            rs = re_summarize(flatten_text(roots), length=args.length, keywords_k=args.keywords)
            if rs:
                payload["resummary"] = rs
        out = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        body = render_md(roots) if args.format == "md" else render_txt(roots)
        if args.re_summarize:
            rs = re_summarize(flatten_text(roots), length=args.length, keywords_k=args.keywords)
            if rs:
                body += "\n\n## 由脑图还原的摘要\n" + rs
        out = body

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write("已写入：%s（节点数=%d，最大层级=%d）\n"
                         % (args.out, st["node_count"], st["max_depth"]))
    else:
        sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
