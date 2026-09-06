#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_bridge.py — 协同技能检测与对接（零依赖、离线、跨平台）。

扫描用户级 / 项目级技能目录，按 capabilities 关键词泛匹配 SKILL.md 的
name/description/tags，判定各能力是否可用，并返回最佳匹配技能信息。

设计目标（提升健壮性）：
- 不限定具体技能名：无论用户安装的是 desensitization-sop、自研脱敏技能，
  还是任意第三方 OCR / 语音 / 视频技能，只要其 SKILL.md 描述含候选关键词，
  都能被识别 —— 因此「非限定本机已安装技能」也能对接。
- 完全离线、纯标准库：不 import 任何外部技能或第三方包，缺失时不报错。
- 数据驱动：能力清单与关键词在 assets/capabilities.json 中可扩展；
  脚本内置同一份默认，确保该文件缺失仍可运行。

用法：
  python3 skill_bridge.py [--map assets/capabilities.json] [--roots DIR1,DIR2]
                          [--cap 能力名] [--format json|txt] [--quiet]
                          [--save-cache] [--use-cache] [--cache-path PATH]

  --cap 模式：仅检测单个能力，exit 0=可用 / 1=缺失（配合 --quiet 只返回码）。
  --save-cache：把「能力→技能」映射持久化为快照（默认 capabilities.detected.json），
                —— 安装/卸载协同技能后运行它以刷新本技能的协同设置。
  --use-cache ：优先读缓存映射加速；缓存缺失自动回退 live 重扫。默认始终 live 重扫，
                保证用户新装的协同技能在下一轮调用立即生效。
"""

import argparse
import json
import os
import re
import sys

# ---- 内置默认能力清单（与 assets/capabilities.json 保持一致；文件缺失时回退）----
DEFAULT_CAPS = {
    "capabilities": {
        "desensitization": {
            "purpose": "上云前对敏感信息脱敏（脱敏/处理/回填/复核闭环）",
            "keywords": ["脱敏", "desensitiz", "隐私", "敏感信息", "sensitive", "去标识", "脱敏网关"],
            "fallback": "local",
            "fallback_note": "缺失时仅本地处理，原始文本不出本机；若用户强制上云仅送 brief 紧凑中间产物并提示隐私风险",
        },
        "ocr": {
            "purpose": "图片 / 扫描件 / 截图转文字",
            "keywords": ["ocr", "光学字符", "图片转文字", "图像文字", "识别文字", "image to text", "截图转文字", "扫描件"],
            "fallback": "ask",
            "fallback_note": "缺失时请用户直接提供文本，或安装 OCR 技能",
        },
        "speech_transcription": {
            "purpose": "音频 / 语音转文字（ASR）",
            "keywords": ["语音", "转录", "转写", "speech", "transcription", "asr", "音频转文字", "听写", "字幕生成"],
            "fallback": "ask",
            "fallback_note": "缺失时请用户提供文字稿，或安装语音转录技能",
        },
        "video_transcript": {
            "purpose": "视频转文字 / 字幕 / 文案提取",
            "keywords": ["视频", "文案提取", "字幕", "视频转文字", "video", "transcript", "口播", "短视频文案", "视频文稿"],
            "fallback": "ask",
            "fallback_note": "缺失时请用户提供文字稿或字幕，或安装视频文案提取技能",
        },
        "document_text": {
            "purpose": "docx / pdf / office / ppt 文档落地为文本",
            "keywords": ["docx 转文本", "docx 解析", "docx 提取", "pdf 提取文字", "pdf 转文本", "document to text", "pdf to text", "office 解析", "文档解析", "文档转文本", "word 解析", "ppt 转文字"],
            "fallback": "ask",
            "fallback_note": "缺失时请用户导出为 .txt/.md 或安装文档处理技能",
        },
        "web_fetch": {
            "purpose": "按给定 URL 抓取网页内容为文本（非联网搜索；联网检索见 search 能力）",
            "keywords": ["网页抓取", "web fetch", "fetch url", "url抓取", "爬虫", "crawler", "抓取网页", "fetch webpage", "网页内容获取", "scrape url"],
            "fallback": "tool",
            "fallback_note": "缺失时回退到内置 WebFetch 工具按 URL 抓取（抓取内容可能含敏感信息，仍需过脱敏协同）；注意与 search 区分：本能力取「指定 URL 的文本」，search 取「联网检索结果」",
        },
        "knowledge_base": {
            "purpose": "摘要/要点沉淀进知识库、笔记或长期记忆",
            "keywords": ["知识管理", "知识库联动", "笔记", "笔记管理", "沉淀", "obsidian", "notion", "语雀", "flomo", "第二大脑", "卡片笔记", "kbase", "knowledge_base", "knowledge base 联动"],
            "fallback": "local",
            "fallback_note": "缺失时把「摘要 + 要点 + 来源」沉淀到本地 ./要点沉淀/YYYYMMDD.md（纯 markdown，便于日后导入任意知识库）",
        },
        "translation": {
            "purpose": "多语摘要 / 把摘要翻译为目标语言",
            "keywords": ["翻译", "translate", "多语", "多语言", "译文", "translation", "i18n", "本地化", "译后", "中英互译"],
            "fallback": "tool",
            "fallback_note": "缺失时如需多语摘要，仅对 --brief 紧凑中间产物(或本地短摘要)送云端翻译，原始长文不上云；否则提示用户安装翻译技能",
        },
        "rag": {
            "purpose": "基于原文的问答式展开（检索增强/局部精准问答），让用户就摘要要点做「溯源式」追问",
            "keywords": ["rag", "检索增强", "retrieval", "retrieval-augmented", "检索增强生成", "向量检索", "向量检索问答", "语义检索问答", "本地知识库问答", "rag 问答"],
            "fallback": "local",
            "fallback_note": "缺失时本技能「源文忠实」的索引/定位/回查机制即轻量本地 RAG：用关键词/句在原文精准取片段做局部问答，无需外部 RAG 技能",
        },
        "search": {
            "purpose": "摘要后续处理的受控联网补全（外部补充），仅当原文不足时启用且须三段标记",
            "keywords": ["联网搜索", "web search", "search", "搜索", "检索网页", "tavily", "perplexity", "搜索引擎", "联网检索", "search skill", "联网补全"],
            "fallback": "tool",
            "fallback_note": "缺失时回退内置 WebSearch 工具做受控补全，输出须按【原文】/【联网补全】/【处理结果】三段标记，外部内容不得混入看似原文",
        },
        "mindmap": {
            "purpose": "把摘要要点可视化为思维导图/结构化脑图，放大摘要可探索性",
            "keywords": ["思维导图", "mindmap", "mind map", "脑图", "markmap", "xmind", "mermaid", "可视化脑图", "结构化导图", "导图", "思维图"],
            "fallback": "local",
            "fallback_note": "缺失时本技能直接输出层级要点大纲（markdown 缩进或 mermaid 代码块），可一键粘贴进 markmap/XMind/语雀等脑图工具，无需外部技能；另含原生 mindmap_import.py 反向导入（脑图/大纲→嵌套大纲/树/json，可选还原摘要），并支持 --markmap 生成自包含 HTML 直接渲染交互脑图，形成双向闭环",
        },
        "diagram": {
            "purpose": "把摘要中的流程/结构/架构画成结构化图示（流程图/时序图/架构图/类图等），放大摘要的过程与结构",
            "keywords": ["流程图", "架构图", "时序图", "类图", "用例图", "diagram", "flowchart", "mermaid图", "plantuml", "drawio", "图示", "示意图", "结构图", "uml"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出 mermaid 代码块（flowchart/sequence/class）或 drawio 文本，可直接在支持 mermaid 的渲染器/编辑器预览，无需外部技能",
        },
        "graph": {
            "purpose": "从摘要要点抽取实体与关系，构建知识图谱/关系网络（节点-边可视化），放大要点的关联性",
            "keywords": ["知识图谱", "关系图谱", "实体关系", "图谱", "knowledge graph", "关系网络", "network graph", "实体网络", "图数据库", "关系图", "nebula", "neo4j"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出 mermaid graph（graph TD）代码块或 markdown 邻接表，标注实体与关系，可一键导入 neo4j/图数据库/可视化工具",
        },
        "entity_extract": {
            "purpose": "从摘要/原文抽取实体、关系与关键要素（命名实体识别、信息抽取、三元组/事件抽取），放大摘要的可结构化性",
            "keywords": ["实体抽取", "命名实体", "实体识别", "关系抽取", "信息抽取", "entity extraction", "entity recognition", "三元组抽取", "事件抽取", "要素抽取", "结构化抽取"],
            "fallback": "local",
            "fallback_note": "缺失时本技能用关键词/正则在原文做轻量实体候选列表（实体—类型—出现句），提示可安装 NER 技能提升质量；绝不因缺失报错",
        },
        "ppt": {
            "purpose": "把摘要/要点生成演示文稿（pptx/幻灯片），放大摘要的可呈现性",
            "keywords": ["演示文稿生成", "ppt 生成", "pptx 生成", "ppt 制作", "幻灯片制作", "演示文稿制作", "powerpoint 制作", "slides 制作", "pptx", "生成ppt", "演示文稿创作", "deck 生成"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出结构化 PPT 大纲（每页标题 + 要点 + 备注的 markdown 分级），用户可一键粘贴进 PowerPoint/语雀/腾讯文档等，无需外部技能",
        },
        "chart": {
            "purpose": "把摘要中的结构化数据/对比项渲染为图表（柱状图/折线图/饼图/数据可视化），放大摘要的可读性",
            "keywords": ["图表生成", "柱状图生成", "折线图生成", "饼图生成", "散点图生成", "echarts", "plotly", "统计图生成", "图表绘制", "生成图表", "数据可视化图表", "xychart", "图表制作", "数据图表生成"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出 markdown 数据表 + 趋势文字描述，用户可粘贴进 Excel/飞书多维表/图表工具；或给出 mermaid xychart 代码块（若渲染器支持）",
        },
        "qa_router": {
            "purpose": "把摘要/要点路由到合适的问答技能，做基于原文的多轮追问与分派（问题→技能/答案分发）",
            "keywords": ["问答路由", "问题路由", "qa router", "qa 路由", "question routing", "多轮问答", "问答分发", "问答编排", "问题分派", "faq 路由"],
            "fallback": "local",
            "fallback_note": "缺失时本技能用「源文忠实」索引/回查 + --cite 溯源在原文做局部问答，按关键词在原文精准取片段作答，无需外部问答路由技能；另含原生 qa_router.py 多轮状态机（JSON session 持久化上下文、追问指代消解、needs_external 标记）作为本地兜底",
        },
        "podcast": {
            "purpose": "把摘要/要点转为播客或口播音频（文本→语音/音频生成），放大摘要的「可听性」",
            "keywords": ["播客生成", "podcast 生成", "音频生成", "语音合成", "tts", "口播稿", "声音生成", "播客制作", "音频内容生成", "有声摘要"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出口播稿（纯文本/markdown 分级讲稿），用户可一键粘贴进任意 TTS / 播客工具生成音频，无需外部技能；另含原生 podcast.py 口播稿生成脚本（复用 summarize 抽核心句作章节、估算口播时长，零依赖），并支持 --tts 可选直接合成音频（edge-tts 免费无密钥 / openai / azure，均 import guard 优雅降级，零依赖默认不受影响）",
        },
        "spreadsheet": {
            "purpose": "把摘要中的结构化数据/对比项生成表格或解析已有表格（电子表格/CSV/多维表），放大摘要的「可计算性」",
            "keywords": ["表格处理", "电子表格", "spreadsheet", "excel 生成", "csv 生成", "表格生成", "多维表", "表格制作", "数据表生成", "表格解析"],
            "fallback": "local",
            "fallback_note": "缺失时本技能输出 markdown 表格 / CSV 文本（可由 structured_summary.py 预抽取结构），用户可粘贴进 Excel/飞书多维表，无需外部技能；另含原生 spreadsheet.py 表格生成/解析脚本（输出 CSV / 自包含 HTML 多表格 / markdown 表，零依赖），并支持 --format xlsx 经 openpyxl 生成真正 .xlsx 工作簿（未装则优雅降级提示，零依赖默认不受影响）",
        },
    }
}


def expand(path):
    """展开 ~ 与 $ENV。"""
    if not path:
        return path
    # 先展开环境变量，再展开 ~
    expanded = os.path.expandvars(path)
    return os.path.expanduser(expanded)


def load_caps(map_path):
    """优先加载外部 capabilities.json；失败或缺失则回退内置默认。"""
    if map_path:
        mp = expand(map_path)
        if os.path.exists(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    data = json.load(f)
                caps = data.get("capabilities")
                if isinstance(caps, dict) and caps:
                    return caps
            except Exception:
                pass
    return DEFAULT_CAPS["capabilities"]


def default_cache_path(map_path):
    """缓存文件默认位置：与 capabilities.json 同目录、同名 .detected.json。
    未指定 --map 时落在脚本同目录的 assets/ 下。"""
    if map_path:
        mp = expand(map_path)
        d = os.path.dirname(mp)
        stem = os.path.splitext(os.path.basename(mp))[0]
        return os.path.join(d, stem + ".detected.json")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "capabilities.detected.json")


def write_cache(path, det, scanned_skills, roots):
    """将检测结果持久化为「能力→技能」映射快照（即本技能的协同设置）。"""
    try:
        os.makedirs(os.path.dirname(expand(path)) or ".", exist_ok=True)
        payload = {
            "generated_at": int(os.environ.get("_NOW", "0")) or None,
            "scanned_skills": scanned_skills,
            "roots": [expand(r) for r in roots],
            "mapping": {
                cap: ({"skill": info["skill"], "name": info.get("name", ""),
                       "path": info["path"], "score": info["score"]}
                      if info.get("available") else {"available": False,
                                                     "fallback": info.get("fallback", "ask")})
                for cap, info in det.items()
            },
        }
        with open(expand(path), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_cache(path):
    """读取缓存的检测映射；文件缺失或异常返回 None。"""
    p = expand(path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        mapping = data.get("mapping", {})
        # 还原为与 detect() 兼容的 det 结构
        det = {}
        for cap, v in mapping.items():
            if isinstance(v, dict) and v.get("available") is False:
                det[cap] = {"available": False, "fallback": v.get("fallback", "ask")}
            elif isinstance(v, dict) and "skill" in v:
                det[cap] = {
                    "available": True,
                    "skill": v["skill"],
                    "name": v.get("name", ""),
                    "path": v.get("path", ""),
                    "score": v.get("score", 0),
                }
        return det if det else None
    except Exception:
        return None


def default_roots():
    """默认扫描：用户级技能目录 + 当前工作区项目级技能目录。"""
    roots = []
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, ".workbuddy", "skills"))
    # 项目级：支持 $WORKSPACE 与当前 cwd
    ws = os.environ.get("WORKSPACE")
    if ws:
        roots.append(os.path.join(expand(ws), ".workbuddy", "skills"))
    try:
        roots.append(os.path.join(os.getcwd(), ".workbuddy", "skills"))
    except Exception:
        pass
    return roots


def read_frontmatter(skill_md_path):
    """读取 SKILL.md 的 name / description / tags（容错：无 frontmatter 也尽力解析）。"""
    name = desc = tags = ""
    try:
        with open(skill_md_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return name, desc, tags
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    block = m.group(1) if m else text[:3000]
    for line in block.splitlines():
        low = line.lower().lstrip()
        if low.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif low.startswith("description:"):
            desc = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif low.startswith("tags:"):
            tags = line.split(":", 1)[1].strip()
    return name, desc, tags


def scan_skills(roots, exclude=None):
    """扫描所有技能目录，返回 [{dir,name,description,tags,hay,path}]。
    exclude: 需排除的技能目录名集合（调用方自身，避免其描述中的输入形态被误判为自身能力）。
    """
    skills = []
    excl = set((exclude or "").split(","))
    excl = {e.strip() for e in excl if e.strip()}
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            entries = sorted(os.listdir(root))
        except Exception:
            continue
        for d in entries:
            if d in excl:
                continue
            dp = os.path.join(root, d)
            if not os.path.isdir(dp):
                continue
            sk = os.path.join(dp, "SKILL.md")
            if not os.path.exists(sk):
                continue
            name, desc, tags = read_frontmatter(sk)
            hay = " ".join([d, name, desc, tags]).lower()
            skills.append({
                "dir": d,
                "path": dp,
                "name": name,
                "description": desc,
                "hay": hay,
            })
    return skills


def detect(caps, skills):
    """对每个能力做关键词泛匹配，返回 {cap: {available, skill, ...}}。"""
    result = {}
    for cap, cfg in caps.items():
        keywords = [str(k).lower() for k in cfg.get("keywords", [])]
        best = None
        alts = []
        for s in skills:
            score = sum(s["hay"].count(k) for k in keywords)
            if score > 0:
                rec = {
                    "skill": s["dir"],
                    "name": s["name"],
                    "path": s["path"],
                    "score": score,
                }
                alts.append(rec)
                if best is None or score > best["score"]:
                    best = rec
        base = {
            "fallback": cfg.get("fallback", "ask"),
            "purpose": cfg.get("purpose", ""),
            "fallback_note": cfg.get("fallback_note", ""),
        }
        if best:
            info = dict(base)
            info.update({
                "available": True,
                "skill": best["skill"],
                "name": best["name"],
                "path": best["path"],
                "score": best["score"],
                "alternatives": [a for a in alts if a["skill"] != best["skill"]],
            })
        else:
            info = dict(base)
            info["available"] = False
        result[cap] = info
    return result


# ---------------------------------------------------------------------------
# 隐性外发确认闸口（2026-09-04 政策细化；2026-09-06 v2.3 统一门禁：接入真实 desen scan）
# ---------------------------------------------------------------------------
EXTERNAL_CONFIRM_ENV = "OFFICE_KIT_EXTERNAL_CONFIRM"
# 与 kit.py 门禁对齐的「同意原样外发」确认标志（两套机制统一到同一语义）。
CONFIRM_RAW_ENV = "OFFICE_KIT_CONFIRM_RAW"


def _locate_desen_scan():
    """定位 office-kit 的 desen 组件脚本（components/desensitization-sop/scripts/desensitize.py）。
    返回 (脚本路径, 解释器路径) 元组，找不到返回 (None, None)（此时退化为本地 PII 预检）。"""
    root = os.environ.get("OFFICE_KIT_ROOT")
    candidates = []
    if root:
        candidates.append(os.path.join(root, "components", "desensitization-sop",
                                        "scripts", "desensitize.py"))
    # 本文件位于 components/summarize/scripts/，向上 4 层即仓库根。
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.abspath(os.path.join(
        here, "..", "..", "desensitization-sop", "scripts", "desensitize.py")))
    desen_script = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not desen_script:
        return None, None
    # 解释器：desen 依赖 cryptography 等，须用 kit 的 .venv 解释器（非系统 python）。
    kit_root = root or os.path.abspath(os.path.join(here, "..", "..", ".."))
    if os.name == "nt":
        venv_py = os.path.join(kit_root, ".venv", "Scripts", "python.exe")
    else:
        venv_py = os.path.join(kit_root, ".venv", "bin", "python")
    if not os.path.isfile(venv_py):
        # 无 venv 时退化为当前解释器（可能因缺依赖而 scan 失败，调用方会 fail-safe 处理）。
        venv_py = os.environ.get("OFFICE_KIT_PYTHON") or sys.executable
    return desen_script, venv_py


def _run_desen_scan_text(text):
    """用 office-kit 的 desen scan 扫描待外发文本，返回 (passed: bool|None, output: str)。
    passed=None 表示无法判定（desen 组件缺失 / scan 异常），由调用方退化为本地 PII 预检。"""
    import subprocess as _sp
    import tempfile as _tf
    desen_script, py = _locate_desen_scan()
    if not desen_script:
        return None, ""
    if not text or not text.strip():
        return True, ""
    try:
        with _tf.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt",
                                    prefix="office_kit_bridge_scan_", delete=False) as tf:
            tf.write(text)
            tmp = tf.name
    except Exception:
        return None, ""
    env = dict(os.environ)
    if os.path.isdir(os.path.dirname(py)):
        env["UV_PROJECT_ENVIRONMENT"] = os.path.dirname(py)
    try:
        proc = _sp.run([py, desen_script, "scan", tmp], env=env,
                       capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return None, "desen scan 调用失败：%s" % exc
    try:
        os.unlink(tmp)
    except Exception:
        pass
    out = (proc.stdout or "").strip() + ("\n" + (proc.stderr or "").strip()
                                         if proc.stderr and proc.stderr.strip() else "")
    # 与 kit.py _run_desen_scan 同语义：命中敏感会出现「汇总：」，干净出现
    # 「未发现已知敏感标识符」，两者皆无按 fail-safe 保守判定为「扫描异常」。
    if "未发现已知敏感标识符" in out:
        return True, out
    if "汇总：" in out:
        return False, out
    return None, out or "（desen scan 无有效输出）"


def _merge_stats(a, b):
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + v
    return out


def _local_pii_hits(texts):
    """用本技能自带 pii_precheck 做本地 PII 预检，返回 {类别: 数量}（无则空）。"""
    stats = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pii_precheck import precheck
        for t in texts or []:
            if not t:
                continue
            r = precheck(t, with_context=False)
            stats = _merge_stats(stats, r.get("stats") or {})
    except Exception:
        pass
    return stats


def request_external_confirmation(purpose, texts=None, paths=None, pii_hits=None):
    """隐性外发确认闸口（组件内部，confirm-or-block，安全默认=阻断；v2.3 接入真实 desen scan）。

    在组件把内容送出本机（如 podcast TTS 把讲稿全文送第三方语音合成）前调用。
    返回 True=放行 / False=阻断。

    v2.3 统一门禁逻辑（与 kit.py 门禁对齐）：
    1. 先跑真实 desen scan（office-kit desensitization-sop）扫描待外发文本；
       找不到 desen 组件时退化为本技能自带 pii_precheck 本地预检（仅提示增强）。
    2. 命中敏感 → 提示「先阻断 + 敏感确认卡」，须用户显式确认
       （OFFICE_KIT_CONFIRM_RAW=1，与 kit.py --confirm-raw 同语义；保留
       OFFICE_KIT_EXTERNAL_CONFIRM=allow 作为等价别名）才放行，并提示先
       `desen audit-log --decision raw` 留痕；或选脱敏外发（desen run 副本）。
    3. 无敏感 → 静默放行（零打扰）。
    4. 交互 TTY 下用 input() 让用户 y/N 确认；非 TTY（agent/管道）安全默认阻断。

    注：PII/desen 检测仅用于提示增强，不影响阻断决策——任何隐性外发都需用户确认。
    """
    import sys as _sys
    # 1) 真实 desen scan（优先）；失败/缺失退化为本地 PII 预检
    scan_passed, scan_out = None, ""
    if texts:
        scan_passed, scan_out = _run_desen_scan_text("\n".join(t for t in texts if t))
    if scan_passed is not None:
        # desen scan 已跑：命中敏感 → 阻断并给确认卡；干净 → 放行
        _sys.stderr.write("\n⚠ 隐性外发确认：%s\n" % purpose)
        if scan_passed:
            _sys.stderr.write("  desen scan：未发现已知敏感标识符。\n")
        else:
            _sys.stderr.write("  desen scan 命中敏感信息，已按门禁先阻断：\n%s\n" % scan_out)
    else:
        # 退化：本地 PII 预检（仅提示）
        hits = dict(pii_hits or {})
        if not hits:
            hits = _local_pii_hits(texts)
            if not hits and paths:
                try:
                    for p in paths:
                        if p and os.path.isfile(p):
                            with open(p, "r", encoding="utf-8", errors="replace") as f:
                                hits = _merge_stats(hits, _local_pii_hits([f.read()]))
                except Exception:
                    pass
        _sys.stderr.write("\n⚠ 隐性外发确认：%s\n" % purpose)
        if hits:
            kinds = "、".join("%s×%d" % (k, v) for k, v in sorted(hits.items()))
            _sys.stderr.write("  本地预检检出疑似敏感信息：%s（建议先 `desen run` 脱敏）\n" % kinds)
        else:
            _sys.stderr.write("  本地预检未发现已知 PII（仍请确认内容不含敏感信息）。\n")
    # 2) 确认（与 kit.py 对齐：CONFIRM_RAW 优先，EXTERNAL_CONFIRM 作等价别名）
    confirm = os.environ.get(CONFIRM_RAW_ENV, "").strip().lower()
    if confirm not in ("1", "true", "yes", "allow"):
        confirm = os.environ.get(EXTERNAL_CONFIRM_ENV, "").strip().lower()
    if confirm in ("1", "true", "yes", "allow"):
        _sys.stderr.write("  → 已确认（OFFICE_KIT_CONFIRM_RAW / OFFICE_KIT_EXTERNAL_CONFIRM），放行。\n"
                          "  【留痕】请先执行 `kit.py desen audit-log --decision raw` 记录本次原样外发。\n")
        return True
    if confirm == "deny":
        _sys.stderr.write("  → 已显式拒绝，外发阻断。\n")
        return False
    if _sys.stdin.isatty():
        try:
            ans = input("  是否确认执行此外发？[y/N] ").strip().lower()
        except Exception:
            return False
        if ans in ("y", "yes", "是"):
            return True
        _sys.stderr.write("  → 用户未确认，外发阻断。\n")
        return False
    _sys.stderr.write("  → 非交互环境未获确认，按安全默认阻断（已与用户确认请置 "
                      "OFFICE_KIT_CONFIRM_RAW=1 后重试）。\n")
    return False


def main():
    ap = argparse.ArgumentParser(description="协同技能检测与对接（零依赖）")
    ap.add_argument("--map", help="capabilities JSON 路径（覆盖内置默认）")
    ap.add_argument("--roots", help="额外技能根目录（逗号分隔，支持 $HOME/$WORKSPACE 等环境变量）")
    ap.add_argument("--exclude", help="排除的技能目录名（逗号分隔；通常是调用方自身，如 summarize，避免其描述中的「输入形态」被误判为自身提供该能力）")
    ap.add_argument("--cap", help="仅检测单个能力，返回可用与否（exit 0=可用,1=缺失）")
    ap.add_argument("--format", default="json", choices=["json", "txt"])
    ap.add_argument("--quiet", action="store_true", help="--cap 模式仅返回 exit code")
    ap.add_argument("--save-cache", action="store_true",
                    help="将检测结果持久化到缓存文件（刷新「能力→技能」映射快照）；默认位置与 --map 同名 .detected.json")
    ap.add_argument("--use-cache", action="store_true",
                    help="优先读取缓存映射（加速），缓存缺失则回退 live 重扫；默认始终 live 重扫以保证新装技能立即生效")
    ap.add_argument("--cache-path", help="指定缓存文件路径（覆盖默认位置）")
    args = ap.parse_args()

    caps = load_caps(args.map)
    roots = default_roots()
    if args.roots:
        for r in args.roots.split(","):
            r = r.strip()
            if r:
                roots.append(expand(r))
    # 去重
    seen, uniq = set(), []
    for r in roots:
        er = expand(r)
        if er and er not in seen:
            seen.add(er)
            uniq.append(er)

    cache_path = expand(args.cache_path) if args.cache_path else default_cache_path(args.map)

    # 读取策略：--use-cache 且未要求保存 → 读缓存；否则 live 重扫（保证新装技能立即生效）
    if args.use_cache and not args.save_cache:
        det = load_cache(cache_path)
        if det is None:
            det = None  # 缓存缺失，下方回退 live
    else:
        det = None

    if det is None:
        skills = scan_skills(uniq, exclude=args.exclude)
        det = detect(caps, skills)
    else:
        skills = []  # 缓存命中，无需再扫

    # 保存映射快照（刷新设置）
    if args.save_cache:
        ok = write_cache(cache_path, det, len(skills), uniq)
        if not args.quiet:
            sys.stderr.write("[skill_bridge] 已刷新检测缓存: {}\n".format(cache_path if ok else "(写入失败)"))

    # 单能力查询模式
    if args.cap:
        cap = args.cap
        info = det.get(cap)
        if info and info.get("available"):
            if args.quiet:
                sys.exit(0)
            payload = {
                "capability": cap,
                "available": True,
                "skill": info["skill"],
                "name": info.get("name", ""),
                "path": info["path"],
                "score": info["score"],
                "fallback": info["fallback"],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json"
                  else "{}: available -> {} ({})".format(cap, info["skill"], info["path"]))
            sys.exit(0)
        else:
            fb = caps.get(cap, {}).get("fallback", "ask") if cap in caps else "ask"
            note = caps.get(cap, {}).get("fallback_note", "") if cap in caps else ""
            if args.quiet:
                sys.exit(1)
            payload = {
                "capability": cap,
                "available": False,
                "fallback": fb,
                "fallback_note": note,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json"
                  else "{}: absent (fallback={})".format(cap, fb))
            sys.exit(1)

    # 全量输出
    if args.format == "txt":
        for cap, info in det.items():
            if info.get("available"):
                line = "[可用] {}: {}  (score={})  fallback={}".format(
                    cap, info["skill"], info["score"], info["fallback"])
                print(line)
                if info.get("alternatives"):
                    print("        备选: " + ", ".join(a["skill"] for a in info["alternatives"]))
            else:
                print("[缺失] {}: fallback={}  -> {}".format(
                    cap, info.get("fallback", "ask"), info.get("fallback_note", "")))
    else:
        print(json.dumps({
            "capabilities": det,
            "scanned_skills": len(skills),
            "roots": uniq,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
