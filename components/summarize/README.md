# summarize · 智能摘要技能

为长文本 / 文档 / 网页 / OCR 稿 / 音频转录稿 / 视频文案提取稿自动生成摘要、提取要点与关键词，支持自定义摘要长度。

- **本地优先（离线、零依赖、跨平台）**：`scripts/summarize.py` 纯 Python 标准库实现，Windows / macOS / Linux 直接 `python3 summarize.py` 运行。
- **云端取方法、本地处理信息**：`--brief` 模式仅把「关键词 + 候选句 + 结构骨架」紧凑中间产物交云端大模型，原始长文不出本机、省 TOKEN。
- **质量评估与改进闭环**：`--eval` 输出压缩比/关键词覆盖/综合评分；`scripts/compare.py` 对比云端与本地结果并记录改进建议。
- **源文忠实（展开优先索引原文）**：对摘要做后续处理（展开/细化/追问/多语/沉淀）需补充细节时，优先回原文索引取片段；仅当原文确实不足时才联网补全，且须明确区分【原文】/【联网补全】/【处理结果】三类，全程可追溯。

## 目录

```
summarize/
├── SKILL.md                    # 技能主指令（供 WorkBuddy 等智能体加载）
├── scripts/
│   ├── summarize.py            # 本地抽取式摘要 + 关键词 + 质量评估（含 --cite/--tldr）
│   ├── compare.py              # 云端×本地对比与改进建议
│   ├── skill_bridge.py         # 协同技能检测与对接（零依赖，关键词泛匹配）
│   ├── diff_summary.py         # 两份文档的差异/变更摘要
│   ├── batch_summary.py        # 目录批量摘要 + 索引
│   ├── consistency_check.py    # 摘要-原文一致性自检（守护源文忠实）
│   ├── pii_precheck.py         # 上云前 PII 预检（隐私守门员）
│   ├── hierarchical_summary.py # 层级摘要（概览→要点→细节）
│   ├── structured_summary.py   # 结构化抽取（问答/列表/定义/表格）
│   ├── mindmap_import.py       # 思维导图反向导入（含 --markmap 渲染）
│   ├── qa_router.py            # 问答路由多轮状态机（本地兜底）
│   ├── podcast.py              # 口播稿生成（可选 --tts 合成音频）
│   └── spreadsheet.py          # 表格生成/解析（可选 --format xlsx）
├── references/
│   ├── config.md               # 配置项说明
│   └── quality-eval.md         # 质量评估方法
└── assets/
    ├── summarize.config.yaml   # 默认配置模板
    └── capabilities.json       # 协同能力清单（可扩展，不限定具体技能名）
```

## 快速使用

```bash
# 单文档 + 质量评估
python3 scripts/summarize.py 输入.txt --length 3 --keywords 8 --eval --format md

# 多文档联合摘要（跨文档统一关键词，输出标注 [文档N]）
python3 scripts/summarize.py 文档1.txt 文档2.txt --length 5 --format md

# 超长文本：超过 --max-input-chars 自动滑动窗口分块抽取后合并
python3 scripts/summarize.py 长文.txt --max-input-chars 200000 --ratio 0.2

# 取紧凑中间产物送云端（云端取方法、本地处理信息）；可指定语气
python3 scripts/summarize.py 输入.txt --brief --tone concise --format json

# 云端×本地对比与改进建议
python3 scripts/compare.py --local 本地摘要.txt --cloud 云端摘要.txt --original 原文.txt --format md
```

- **可选 jieba**：运行环境装了 `jieba` 则中文分词自动升级；未装则回退内置二元/三元组分词，功能不受影响、零依赖。
- **零耦合脱敏**：脚本不依赖 `desensitization-sop`；该技能缺失时由智能体层跳过脱敏步骤，脚本本身不会出错。

## 协同技能检测、对接与容错（健壮性核心）

本技能不假定任何外部技能已安装。`scripts/skill_bridge.py` 扫描用户级/项目级技能目录，按 `assets/capabilities.json` 的关键词泛匹配各技能 SKILL.md 描述，判定 19 项能力是否可用——**不限定具体技能名**，故用户安装的任意脱敏/OCR/转录/知识库/翻译技能都能被识别对接：

- 取文类：`desensitization` / `ocr` / `speech_transcription` / `video_transcript` / `document_text` / `web_fetch`
- 输出后协同：`knowledge_base`(要点沉淀) / `translation`(多语摘要) / `rag`(基于原文问答) / `search`(受控联网补全) / `mindmap`(脑图) / `diagram`(图示) / `graph`(关系图谱) / `entity_extract`(实体抽取) / `ppt`(演示文稿) / `chart`(图表) / `qa_router`(问答路由) / `podcast`(口播音频) / `spreadsheet`(表格)

```bash
# 全量检测（排除调用方自身，避免描述中的输入形态被误判为自身能力）
python3 scripts/skill_bridge.py --map assets/capabilities.json --exclude summarize --format txt

# 单能力查询（exit 0=可用 / 1=缺失）
python3 scripts/skill_bridge.py --exclude summarize --cap ocr --quiet && echo 有OCR || echo 无OCR

# 新装/卸载协同技能后刷新「能力→技能」映射快照（写入 capabilities.detected.json）
python3 scripts/skill_bridge.py --map assets/capabilities.json --exclude summarize --save-cache --format txt
```

- **对接**：取文类命中后用 Skill 工具加载对应技能产出文本，作为 `summarize.py` 的输入；输出后协同类（`knowledge_base`/`translation`/`rag`/`search` 等）在摘要产出后调用，把摘要/要点写入知识库、做目标语翻译或可视化。本技能脚本只消费纯文本。
- **容错降级**：每个能力有 `fallback` 策略——`local`（脱敏→仅本地处理；`knowledge_base` 缺失→沉淀到本地 `./要点沉淀/YYYYMMDD.md`）、`ask`（OCR/语音/视频/文档缺失→请用户提供文本）、`tool`（网页缺失→回退内置 WebFetch；`translation` 缺失→仅对 brief/短摘要送云端翻译，原始长文不上云）。**外部技能缺失只阻断「取文」、不阻断「摘要」。**
- **新装技能即时生效**：`skill_bridge.py` 默认每次调用 live 重扫技能目录，用户新装的协同技能无需改配置即被识别。
- **可扩展**：在 `capabilities.json` 追加任意能力键即自动生效，无需改脚本。

## 源文忠实原则（后续展开必守）

摘要是原文的「压缩投影」，不是独立知识源。对摘要做**后续处理**（展开/细化/追问/多语/沉淀）时：

- **优先索引原文**：先用原文的索引 / 定位 / 回查取相关片段作为展开依据，展开内容标回具体句/段落。
- **原文不足才联网补全**：默认不脱离原文联网搜索；仅当原文确实不足以满足需求时才可联网补全。
- **三段强标记**：一旦联网补全，输出须清晰区分——【原文】（可溯源句/段落）、【联网补全】（附来源链接/出处+获取时间）、【处理结果】（说明分别依赖了哪些原文与补全），不得让外部内容混入看似原文。

> 与「本地优先 / 云端取方法」一致：扩充细节优先以原文为权威来源，联网补全只是原文不足时的受控补充，且全程可追溯。详见 `SKILL.md` 的「源文忠实」专节。

供 Claude / Codex / OpenClaw 使用时，复制本目录即可；运行需 Python 3.8+。详见 `SKILL.md`。
