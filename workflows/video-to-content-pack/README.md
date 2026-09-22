# video-to-content-pack —— 视频转内容包工作流（契约）

可执行契约：`workflow.json`（由 `kit.py workflow` 加载）。
机械步脚本：`tools/vcp.py`（跨平台纯 Python，16 个子命令）。
人类可读蓝本：`./蓝本.md`（**唯一权威内容来源**；随工作流分发，跨平台、跨设备可复用）。
配图通用方法：`./illustration-spec.md`。

## 契约速查

| 项 | 值 |
|---|---|
| 版本 | 0.4.0 |
| 步骤数 | 27 = 机械 20 + 创作 7（其中 6 个来源摄取步按 `when` 互斥） |
| requires | info-extract + summarize + doc-layout-aesthetics 组件 + office-kit 所用的虚拟环境（**唯一必需环境**，默认复用 `~/office-kit/.venv`，不自建） |
| optional | `live` / `capture`（原生摄取已同步组件；`*_fallback` 保留为录制完整性兜底）；`vision`（整视频关键帧+VLM，按需显式调用） |
| 关键 params | `workspace`（必填）/ `source` / `source_uri` / `section` / `deliverable_types` / `granularity` / `copywriting` / `digest` / `deliverable_render` / `cloud_upload` / `desen_gate` / `whisper_model` / `device_duration` / `ffmpeg_bin` |
| 不再需要 | ~~media 隔离环境~~（2026-09-22 起，仅作可选兜底：抽帧由 info-extract 完成、去边用套件 venv 的 PIL、ffmpeg 用套件 venv 的 imageio-ffmpeg） |

## 执行模型（Agent + runner 协作）

- **机械步 20 个**，由 runner 直接分发：
  - `uses.script`（**16 个，主力**）→ `tools/vcp.py`：`precheck` / `prepare_dirs` / `ingest_file` / `ingest_live_fallback` / `ingest_device_fallback` / `transcribe` / `index_records` / `digest` / `frames_ocr` / `crop_shots` / `cutting` / `export` / `render` / `cloud_upload` / `desen_gate` / `verify`；
  - `uses.kit`（1 个）→ `doctor`；
  - `uses.component`（3 个）→ `extract`（`online` / `live` 原生 / `device` 原生），**经 `cmd_run` 分发，从而继承「外发必扫 DESEN」闸门**（v0.3.0 直连组件入口会绕过闸门，已修）。
- **创作步 7 个**（`executor: agent` + `checkpoint: confirm`）：`frame_pick`（选帧与命名归位）、`authoring`（修正稿 + 交付文档）、`illustrate`（配图）、`copywriting`（文案）、`catalog_acquire` / `product_catalog`（目录 / 产品）、`cut_plan`（裁切计划）。runner 遇到此类步**标记 `await_agent` 并暂停**，打印该步 desc 与回填指引；Agent 按蓝本对应章节完成后 `kit workflow step-done video-to-content-pack <step_id> [<step_id> ...]` 回填为 done（**支持一次多步**），再 `--resume` 续跑。
- **为什么这样切分**：机械活（建目录 / 归一化 / 帧去重 / 拼 ffmpeg 命令 / 导出 / 渲染）交脚本 —— 可复现、可续跑、不消耗 Agent 往返；「读上游记录 → 生成内容 → 人工确认」的本质是创作，交 Agent 按蓝本执行。v0.3.0 有 12 个 agent 步（机械活也交给了 Agent）→ v0.4.0 压到 7 个，**减少 5 次 resume 往返**。
- 每步 `writes` 与 `state_schema.records` 把蓝本 §0.4 工作记录链固化为契约（owner + consumers）；每步完成时对该步 `writes` glob 命中的文件登记 **sha256 指纹**（写入 `pipeline_state.json`）。

## 配图阶段（illustration）

`video-to-content-pack` 覆盖抽帧 / 去边 / OCR / 讲义写作 / 切片 / 文案，但「把截图配到对应文字 + 数量按需 + 多处合成 + 图文位置判据」这一**配图阶段**原未独立成文——其通用方法已沉淀为 [`illustration-spec.md`](./illustration-spec.md)（随工作流分发，可跨项目复用）。

- **管线位置**：作为 `illustrate` 步（`executor: agent` + `checkpoint: confirm`）执行，位于 `frame_pick`（选帧）→ `crop_shots`（去边）→ `authoring`（交付文档写作）**之后**、`copywriting` 与 `verify`（全量校验）**之前**。
  > **顺序修正（v0.4.0）**：去边必须**先于**配图——配图引用的应是去边后的成品图。v0.3.0 把去边排在配图之后（逻辑倒置），已在 §3.6 步序与契约 `steps` 中改正。
- **三条标准**：① 内容匹配最合适的截图 ② 配图数量由内容 / 展示需求决定 ③ 同一段文字配图较多时裁切合成一张。
- **图文位置判据**：A 真错位 / B 多图堆叠 / C 图先于文 / D 裸图堆叠（均硬违例，必须为 0）；E 类合法例外（节首例图、一条 bullet 一对多、成组对比图、作品罗列段）。
- **项目专属实例化**：命名规则、源视频路径、本地脚本、调整历史等见各项目文档，不写入本通用规范（避免污染跨项目可移植性）。
- **契约化状态（2026-09-22）**：`illustrate` 步在 `workflow.json` 中位于 `authoring` 之后、`copywriting` 之前，`executor: agent` + `checkpoint: confirm`；`state_schema.records` 登记 `illustration_index.json`（owner=`illustrate`，consumers=[`verify`]）。蓝本 §3.7 已载「交付文档配图」小节，三处对齐。

## 降级矩阵（live/capture）

**原生路径已生效**（2026-09-03 已把独立仓 live/capture 同步进 `components/info-extract`，manifest 登记 `live`/`capture` 能力；部署副本 `~/office-kit` 同步）：

| params.source | 路径 | 前提 |
|---|---|---|
| `file` | `vcp.py ingest` 归一化 → `transcribe` | 无 |
| `online` | `extract`（yt-dlp，**已含转录**） | yt-dlp 可选依赖 |
| `live` | `extract --live`（边录边转 + 增强 A–E；**固定带 `--keep-live`**，切片与复核需源视频） | ✅ 已可用 |
| `live_fallback` | `vcp.py record-live`（套件 venv ffmpeg，`-c copy`）先录制 → `transcribe` | 录制完整性兜底，保留 |
| `device` | `extract --device` | ✅ 已可用 |
| `device_fallback` | `vcp.py record-device` 按平台组装后端（avfoundation / dshow / v4l2 / decklink）先采集 → `transcribe` | 兜底，保留 |

> ⚠ **upgrade 保护**：源仓 7 个提交尚未推送远程——推送前对 info-extract 执行 `kit upgrade` 会从 origin/main 拉旧版覆盖本同步（manifest sync.warning 已记录）。推送后恢复常规 upgrade 流程，`*_fallback` 继续作为边转失败时的兜底（蓝本 §10）。

## 运行

```sh
./kit workflow list
# 契约自检：版本一致性 + 步骤/记录链一致性（6 类校验）
./kit workflow check video-to-content-pack
# 干跑：只打印计划，不执行、不写状态（零污染）
./kit workflow run video-to-content-pack --dry-run --workspace /tmp/vcd
# 单节交付（文件来源；默认 粒度 none、形态讲义、渲染 PDF、digest 与 DESEN 闸门开）
./kit workflow run video-to-content-pack --yes \
  --workspace ~/内容工作区 --param source=file --param source_uri=~/录屏.mp4 --param section=第1节
# 电商场景（自媒体回放 + 按产品切片 + 文案 + 上传腾讯文档）
./kit workflow run video-to-content-pack --yes \
  --workspace ~/内容工作区 --param source=online --param source_uri=<回放URL> \
  --param granularity=product --param copywriting=on --param cloud_upload=tencent
# 断点续跑 / 定点重跑某一步
./kit workflow run video-to-content-pack --resume --workspace ~/内容工作区
./kit workflow run video-to-content-pack --step 16 --workspace ~/内容工作区
# Agent 完成创作步后回填（支持一次多步）
./kit workflow step-done video-to-content-pack frame_pick authoring --workspace ~/内容工作区
```

## 验证记录（2026-09-22 · v0.4.0 全量架构升级）

`workflow list` 识别 **27 步**；`workflow check` **通过（0 警告）**。夹具端到端冒烟全部通过：

| 项 | 结果 |
|---|---|
| `uses` 引号/空格 | ✅ 正确切分为 `['extract','/tmp/a b.mp4','--out','/tmp/My Dir']`（v0.3.0 会误判为 shell，带字面引号下发） |
| `--dry-run` 零污染 | ✅ 干跑后 `_work/` 为空、`pipeline_state.json` 未创建（v0.3.0 会写入 4 步 done） |
| 外发闸门不被绕过 | ✅ 组件步改走 `cmd_run` 后，敏感文本被「隐性外发·高敏感确认卡」拦截 `rc=3` |
| `~` 展开 | ✅ `--workspace '~/内容工作区'` 展开为绝对路径 |
| 产物指纹 | ✅ 逐步逐 glob 登记 sha256（precheck 1 / index_records 3 / frames_ocr 2 / export 5 / render 4 …） |
| `uses.script` 跨平台 | ✅ 16 个 script 步 dry-run 展开正确，注入 `OFFICE_KIT_ROOT`/`OFFICE_KIT_PY`/`OFFICE_KIT_WORKFLOW` |
| 帧去重（16×16 灰度 MAD） | ✅ 识别 `frame_0021_00.png` 为 `frame_0006_00.png` 的重复帧，保留 3/4（aHash 在幻灯片场景实测失效，距离为 0） |
| 去边算法 | ✅ 黑边图 box `[40,40,861,481]` keep 0.774；无黑边图保持原样（护栏生效） |
| 切片 | ✅ 3 段 stream-copy 全成功；`.part` 临时名修正后 ffmpeg 不再 `rc=234` |
| 导出 / 渲染 | ✅ 4 文件 + csv / 3 份 PDF（图片内联、中文精排正常） |
| DESEN 闸门步 / 机械校验 | ✅ `desen_report.json` 无命中；`verify` 11 项全过 |
| 续跑 / 暂停 / 多步回填 | ✅ `--resume` 跳过已完成步；`frame_pick` 正确停在 `await_agent`；一次回填双步成功 |

> **已知限制**：本机 faster-whisper 模型快照不完整（`models--Systran--faster-whisper-tiny` 缺 `model.bin`，下载 502），**未跑真实转录**；改用伪契约夹具验证下游全链路，转录步本身由 info-extract 组件既有测试覆盖。
>
> 历史记录（21 步 / 22 步）见蓝本 §11 的 2026-09-03 与 2026-09-17 两条机制验证记录。

## 踩坑 / 约定

- `uses` 三种形态：`{"kit": …}` / `{"component": …}` / `{"script": …}`；**命令字符串统一走 `shlex` 切分**，路径含空格或引号不再误判为 shell。POSIX shell 步骤已全部迁移到 `script`（Windows 原生可用）。
- `when` 条件支持 `k==v` / `k!=v` / `k in a,b,c` / `k not in a,b,c` / 单 token 真值；**布尔开关用 `on/off` 字符串 + `==` 比较**（单 token `"off"` 也是真值，勿用）。
- `executor: agent` 步：runner 暂停于 `await_agent`，Agent 完成后 `kit workflow step-done <name> <step_id> [...]` 回填再 `--resume`；`--dry-run` 下 agent 步只打印计划不暂停。
- 确认门（`checkpoint: confirm`）在 CLI 交互挂起等待 `input()`；Agent 驱动时传 `--yes`，由 Agent 自行在确认点向用户求证（蓝本「待确认门」模式的契约化）。
- **ffmpeg 四级探测链**：`--param ffmpeg_bin` > 套件 venv 的 `imageio_ffmpeg`（**推荐，本机实测可用**）> media 环境 > 系统 `PATH`；全部落空时明确报错并给三选一指引，不静默失败。（`media_py` 参数已随 media 环境一起降级移除。）

## 蓝本同步状态

- **v0.4.0（2026-09-22，全量架构升级）**：① 契约重构——`requires.components` 补 `summarize`/`doc-layout-aesthetics`、`state_schema.records` 全面重写为 info-extract v0.6.4 的真实产物名（删除并不存在的 `course_raw/*_raw.states.tsv`、`unique_states.json`）、22 → **27 步**、agent 步 12 → 7、新增 `digest`/`render`/`cloud_upload`/`desen_gate` 步；② 新增 `tools/vcp.py`（16 子命令，机械步 runner 直跑）；③ kit.py 分发层修 6 处缺陷（引号/空格、dry-run 污染状态、组件步绕过外发闸门、`~` 不展开、无 sha256 指纹、无 `script` kind）+ 新增 `kit workflow check`（6 类契约自检）；④ 蓝本 §0.1–§0.4、§1.2、§2、§3.6、§5–§8、§11 全面同步；⑤ 本 README 同步至 0.4.0。
- **v0.3.0（2026-09-22）**：① 蓝本由「工作区隐私隔离、不随仓库分发」改为**随工作流分发**——本体迁入 `workflows/video-to-content-pack/蓝本.md`（与 `workflow.json` / `illustration-spec.md` 同包），跨平台、跨设备可复用；frontmatter 版本 `v0.2.0 → v0.3.0`，两处硬编码 `~/Repositories` / `~/office-kit` 路径归一为 `<OFFICE_KIT>` 占位符；② 通用规范 `illustration-spec.md` 新增「七、配图四原则（存储与呈现层）」「八、渲染与导出纪律（源文件零硬换行·方案 C）」「九、布局校验标准（verify_layout）」「十、操作红线」，并补第二验证项目《细味情感拍人像·安菲菲》；③ 契约 `blueprint_doc` 改指 `./蓝本.md`。
- **v0.2.0（2026-09-17）**：① frontmatter 版本 `v0.1.0 → v0.2.0`；② §3.7 补「交付文档配图」小节（三条标准 + 图文位置判据 A/B/C/D/E，引用 `illustration-spec.md`）；③ §3.6 单节流水线表加「步 6b 交付文档配图」、§11.2 创作步清单加「配图」、§11.3 步骤对照表加 `illustrate` 行；④ §11 末尾补 2026-09-17 机制验证记录。蓝本实为 UTF-8 编码（非此前误判的 GBK），可直接按字面安全编辑。
