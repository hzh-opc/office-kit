#!/usr/bin/env python3
"""把 Markdown 落到腾讯文档并自动套用版面美学（中英文混排字体 + 表格美化）。

依赖：tencent-docs 插件（宿主已连接腾讯文档，票据由 Workbuddy 注入）。
能力边界见 references/aesthetics-spec.md 第十二节；四类 Word 专属能力（跨页保护 /
避头尾 / 首行缩进特殊格式 / 样式画廊）云端暂缺，本脚本只做可落地的美化。

用法：
    python scripts/build_tencent_doc.py <输入.md> [--title 标题]
    示例：python scripts/build_tencent_doc.py scripts/sample_tencent.md --title 版面美学观
"""
import json
import subprocess
import base64
import sys
import glob
import os

# 跨机器/跨用户：从 $HOME 推导，不硬编码用户名；兼容 cache 与 marketplaces 两种插件安装位置
_HOME = os.path.expanduser("~")
PLUGIN_GLOBS = [
    os.path.join(_HOME, ".workbuddy", "plugins", "cache", "workbuddy-builtin",
                 "tencent-docs-plugin", "*", "skills", "tencent-docs", "tencentdocs.py"),
    os.path.join(_HOME, ".workbuddy", "plugins", "marketplaces", "workbuddy-builtin",
                 "builtin-plugins", "tencent-docs-plugin", "skills", "tencent-docs", "tencentdocs.py"),
]

HEAD_FONT = {"font_family": "思源黑体", "color": "1F4E79", "bold": True}
TABLE_BORDERS = {
    "top": {"color": "999999", "sz": 4, "space": 0},
    "bottom": {"color": "999999", "sz": 4, "space": 0},
    "left": {"color": "999999", "sz": 4, "space": 0},
    "right": {"color": "999999", "sz": 4, "space": 0},
    "inside_h": {"color": "CCCCCC", "sz": 2, "space": 0},
    "inside_v": {"color": "CCCCCC", "sz": 2, "space": 0},
}


def find_td():
    for g in PLUGIN_GLOBS:
        hits = glob.glob(g)
        if hits:
            return hits[0]
    raise SystemExit("未找到 tencentdocs.py，请确认 tencent-docs 插件已安装")


def call(td, tool, args):
    a = json.dumps(args, ensure_ascii=False)
    r = subprocess.run([sys.executable, td, "tdoc_call", "doc-mcp", tool, a],
                       capture_output=True, text=True)
    try:
        env = json.loads(r.stdout.strip())
    except Exception:
        return {"_error": r.stdout[:200]}
    if "error" in env:
        return {"_error": env["error"].get("message", str(env["error"]))}
    return json.loads(env["result"]["content"][0]["text"])


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: python build_tencent_doc.py <输入.md> [--title 标题]")
    md_path = sys.argv[1]
    title = sys.argv[sys.argv.index("--title") + 1] if "--title" in sys.argv else None
    if not os.path.exists(md_path):
        raise SystemExit(f"输入文件不存在: {md_path}")

    md = open(md_path, encoding="utf-8").read()
    td = find_td()

    # 1) 鉴权就绪检查
    init = subprocess.run([sys.executable, td, "tdoc_init"], capture_output=True, text=True).stdout
    if "READY" not in init:
        raise SystemExit("腾讯文档未就绪（请先在 Workbuddy 连接腾讯文档）: " + init.strip())

    # 2) 创建（base64_markdown）
    b64 = base64.b64encode(md.encode("utf-8")).decode("ascii")
    cargs = {"base64_markdown": b64}
    if title:
        cargs["title"] = title
    res = call(td, "create_with_markdown", cargs)
    if "_error" in res:
        raise SystemExit("创建失败: " + res["_error"])
    fid = (res.get("file_id") or res.get("structuredContent", {}).get("file_id"))
    if not fid:
        raise SystemExit("创建失败，无 file_id: " + json.dumps(res, ensure_ascii=False))
    print("已创建:", res.get("file_url"), "| file_id =", fid)

    # 3) 解析结构，定位标题与表格
    struct = call(td, "resolve_document_structure", {"file_id": fid, "mode": "full"})
    if "_error" in struct:
        print("结构解析失败，跳过自动美化:", struct["_error"]); return
    nodes = struct.get("nodes", [])
    starts = sorted(n["start_index"] for n in nodes if n.get("start_index") is not None)

    def end_of(start):
        nxt = [x for x in starts if x > start]
        return (nxt[0] - 1) if nxt else start + 50

    # 4) 标题 -> 思源黑体 + 深蓝 + 加粗
    for n in nodes:
        if n.get("type") == "Heading" and n.get("start_index") is not None:
            b, e = n["start_index"], end_of(n["start_index"])
            r = call(td, "update_text_property",
                     {"file_id": fid, "ranges": [{"begin": b, "end": e}], "property": HEAD_FONT})
            if "_error" in r:
                print(f"  标题美化失败(idx={b}):", r["_error"][:80])

    # 5) 表格 -> 边框 + 居中 + 表头底色 + 斑马纹
    for n in nodes:
        if n.get("type") == "Table" and n.get("start_index") is not None:
            r = call(td, "set_table_properties",
                     {"file_id": fid, "idx": n["start_index"], "alignment": "center",
                      "borders": TABLE_BORDERS,
                      "cell_margin": {"top": 40, "bottom": 40, "left": 80, "right": 80},
                      "cell_fills": [{"condition": "first_row", "color": "1F4E79"},
                                     {"condition": "band_row_even", "color": "F2F6FB"}]})
            if "_error" in r:
                print(f"  表格美化失败(idx={n['start_index']}):", r["_error"][:80])

    print("完成。打开:", res.get("file_url"))


if __name__ == "__main__":
    main()
