# CHANGELOG · info-extract

## [0.6.3] — 2026-08-29 · 全面审查修复（缓存正确性 + 机器可读输出 + 文档对齐）

### 修复（P0/P1 实质缺陷）
- **缓存选项哈希白名单漏配（P0）**：`hash_cache._options_hash` 原白名单仅含阶段一 6 字段，OCR/视觉/视频/D16 传入的 `force_ocr`/`preprocess`/`conf_threshold`/`ocr_coop`/`vision_tier`/`vision`/`extract_frames`/`context`/`correct_model`/`no_correct` 等全被过滤，导致关键选项变化时缓存错误命中、返回过期结果。改为「仅排除 `out_dir`/`use_cache` 无关项的全量哈希」；各模块 `cache_key_opts` 补齐 D16 纠正选项与 `extract_frames`。
- **segments 不入输出契约（P0）**：`ExtractResult.to_contract()` 缺失 `segments`，缓存命中后 `.srt` 字幕与 MD「带时间戳备查」全空。已在 `to_contract()` 纳入 `segments`，并新增统一还原函数 `base.contract_to_result()`（收敛原先 audio/ocr/vision 三处重复的 `_contract_to_result_kwargs`）。
- **`--json` 输出被横幅污染（P1）**：router 原在 stdout 先打印横幅再打印 JSON，下游 `json.loads` 必然失败。改为 `--json` 时抑制横幅（仅输出纯 JSON，`default=str` 兜底序列化）。
- **`quality_scorer` 死代码（P1）**：`score()` 原定义了却从未调用，文档却宣称生效。已在 router 汇总展示接入，透明回显「质量档 + 建议」。

### 修复（P2 优化）
- router：argparse `description` 与 URL 分支注释过期更正；删除空实现的 `_safe_media`；`ready=False` 分支判空防 IndexError。
- `io.py`：消除 `.webm` 在音频/视频双重归类（统一归视频，纯音频 webm 会因「无音轨」清晰报错）。
- `video_online`：修复 yt-dlp 失败回退浏览器捕获时 `sandbox.cleanup()` 后再访问 `sandbox.dir` 造成的空目录泄漏；`_stem` 的 md5 注释措辞更正。
- `install.py`：`find_python` 补 `<3.14` 版本上限；uv 分支补 `--python`；依赖清单与 `--python` 参数语义注释更正。
- `provider_registry.register`：修复 priority 排序死逻辑（升序插入 + 同名去重）。
- `ocr/output.py`/`vision/output.py`：补 `Tuple` 导入。

### 文档对齐
- `README.md` 阶段状态（二/三/四/五）从「规划中」更正为「已实现」，补阶段五增强与 D16。
- `AGENT_INSTALL.md`：OCR 状态、依赖清单、验证入口（phase1~7）、磁盘说明更新。
- `assets/capabilities.json` / `scripts/pyproject.toml`：版本同步至 0.6.3、描述与依赖补全。
- `SKILL.md`：frontmatter `description` 精简（修正 `olama` 拼写 → `ollama`）。

### 验证
- `tests/verify_phase1.py` 补 5 项断言：`force_ocr`/`preprocess`/`context` 缓存键隔离、`segments` 入契约 + 还原、`--json` 纯 JSON；`verify_phase7.py` 改用统一 `contract_to_result`。
- 七阶段回归 42/34/42/76/51/56/31 全绿（合计 332/332）。

## [0.6.2] — 2026-08-28 · 交付物范式落地（D16：识别结果单一备查副本 + 纠正版稿件）

### 新增（D16 交付物范式）
- **契约扩展（base.ExtractResult）**：新增 `raw_text`（识别结果备查副本，单一）与 `corrected`（纠正版稿件元数据 dict）字段；`to_contract()` 输出二者。原始识别结果只保留一份（随 .json/.md 落盘），不另存多份独立副本。
- **纠正版稿件模块（modules/corrector.py）**：新增 `maybe_correct(result, options)`——默认调用本机 ollama 纯文本模型（默认 `qwen2.5:7b`，零新依赖，经 stdlib urllib 调 REST API）离线纠正 OCR/ASR/视觉原始文本；纠正结果挂 `result.corrected`（含 text/notes/source/model/时间）。
- **优雅降级（D16/§4）**：未安装 ollama / 未拉取文本模型 / `--no-correct` → 跳过纠正，`raw_text` 照常保留、`text` 不变、`corrected=None`，`provider_meta.correction` 透明标注状态（skipped:disabled / no-model / error / empty / applied）。
- **语境消歧（D16）**：`--context` 提供领域/术语/专有名词等背景，作为本地纠正依据（`correction_source="context"`）；无 context 时为 `correction_source="local-model"`。
- **不联网红线（D16/D2/D15）**：CLI 仅做本地离线纠正，**绝不自动上云、不发起联网检索**；联网检索纠正明确为 agent 层职责（D2/D15 确认门），本 CLI 不实现。
- **输出落地（D11 双通道对齐）**：
  - 音频/视频：`.txt`=纠正版稿件（clean）；`.srt`=原始带时间戳备查；`.json/.md` 含 `raw_text`+`corrected`；MD 置顶「纠正版稿件（交付物）」、下附「识别结果备查（原始时间戳）」。
  - OCR：`.txt`=纠正版稿件；`.md` 置顶纠正版稿件、下附原始识别文本与逐框明细；`.json` 含 `raw_text`+`corrected`。
  - 视觉：`.txt`=纠正版稿件；`.md` 置顶纠正版稿件、下附原始描述与图中 OCR 文字备查。
- **CLI**：`--no-correct` / `--context <语境>` / `--correct-model <ollama标签>`；`router.build_options` 透传 `no_correct`/`context`/`correct_model`；汇总展示纠正状态（D15/§4.7 透明）。
- **缓存兼容（D12·L）**：`to_contract()` 含 `raw_text`/`corrected`，缓存命中自动还原；旧缓存缺字段则优雅回退为 None。

### 验证
- 新增 `tests/verify_phase7.py`（31 项）校验 D16 契约（raw_text/corrected 落盘、.txt 为纠正版稿件、--no-correct 跳过、缓存还原、纠正 applied 路径 mock）；
  阶段一/二/三/四/五/六回归 35/35、34/34、42/42、76/76、51/51、56/56 无回归（七阶段合计 325/325；阶段一含 D16 契约断言 +1）。
- 注：纠正版稿件依赖本机 ollama 文本模型；未配置时自动跳过、不影响既有双通道产出。

### 决策落实（D16 拍板）
- 联网检索策略=按需联网+确认门（CLI 不联网，仅 agent 层触发）。
- 改动范围=设计文档（方案 §3.6/§4/§5、流程规范 §1/§3.4/§4.1/§4.6/§7）+ 已部署 SKILL.md + 代码实现。

## [0.6.1] — 2026-08-28 · 账号批量防风控限速（方案 B 后续强化）

### 新增（防风控）
- **顺序处理 + 随机间隔限速**：账号/合集批量展开后，逐条视频**顺序**处理，相邻视频之间随机休眠（默认约 `enum_interval=3.0` 秒，抖动 0.5x~1.5x），避免固定节奏被平台识别为爬虫，降低封号/限流风险。
- **单账号数量上限 `--enum-limit`**：单账号最多处理的视频数（默认不限制）；超大账号建议分批，进一步降低风控与成本。
- **退出开关 `--no-throttle`**：关闭限速间隔（仅当用户明确拥有这些内容、接受平台风控风险时）；关闭时聚合报告显式标注「已关闭防风控限速」。
- **透明提示**：聚合报告新增「防风控限速」说明；`VideoOnlineModule` 在账号批量模式自动启用限速，`--no-throttle` 时给出明确警示。
- **CLI**：`--enum-interval <秒>` / `--enum-limit <条数>` / `--no-throttle`；`router.build_options` 透传 `enum_interval` / `no_throttle` / `enum_limit`。
- **验证**：`tests/verify_phase6.py` 新增 [11] 防风控限速测试（time.sleep 被调用 / --no-throttle 关闭 / --enum-limit 上限），**56 项全绿**；阶段一/二/三/四/五回归 34/34、34/34、42/42、76/76、51/51 无回归（六阶段合计 293/293）。

### 风控原则（明确写入文档）
- 批量处理他人账号视频可能触发平台频率限制甚至封号；请勿高频、请勿用于无权访问的内容（§4 边界 #2/#3）。
- 仅处理你有权访问的内容，遵守平台服务条款与版权，不规避任何登录/版权保护机制；副本默认不保存（D3）。

## [0.6.0] — 2026-08-28 · 阶段五增强（方案 B：账号/合集枚举 + cookie 登录态适配，抖音/小红书/B站 等）

### 新增
- **账号/合集枚举 Provider（方案 B，阶段五增强）**：新增 `IAccountEnumProvider` 接口 + `YtDlpEnumProvider`（默认 yt-dlp `--flat-playlist -j` 枚举账号/合集/频道下全部视频），注册为 `VIDEO_ONLINE_ENUM` 能力（D15）；`VideoOnlineModule.run` 识别账号 URL（或 `--playlist` 强制）后先枚举、再逐条走现有「下载+转录」管线，零新增必需依赖。
- **抖音/小红书/B站 账号 URL 识别**：`detect_account_url()` 覆盖抖音（user / v.douyin）、小红书（user/profile / xhslink）、B站（space / channel / list / medialist / b23.tv）、YouTube 频道、通用 playlist 参数；单条视频 URL（bilibili.com/video/BV…、youtube.com/watch）不误判。
- **cookie 登录态适配**：新增 `--cookies <cookies.txt>` / `--cookies-from-browser <chrome/firefox/edge/...>`，经 `yt_common.build_cookie_args` 贯穿枚举与下载命令（抖音/小红书/B站 账号视频常需登录态）；枚举/下载命中登录态错误 → 显式提示注入 cookie（§4 边界 #2/#3），不静默失败。
- **透明标注与聚合报告增强**：枚举来源账号写入每条结果 `media_ref.from_account` 与 `provider_meta.enum_provider`；聚合报告新增「账号/合集枚举明细」（平台/条目数/各视频 URL）与 ToS 提示（§4 边界 #2/#3）；JSON 报告含 `account_enum` 与 `from_account`。
- **强约束沿用**：枚举不产出本地文件（external=False）；逐条视频仍走 D3 不留存副本 / 审阅 G 不落盘；加密/空账号/缺 yt-dlp 均显式错误、不静默失败。
- **验证**：新增 `tests/verify_phase6.py`（账号 URL 识别 / Provider 注册 / 枚举单元含登录态与空账号 / cookie 透传 / 集成枚举→批量转录 / 强制 --playlist / 枚举不可用引导 / 登录失败引导 / router 选项与 --check，**47 项全绿**，mock 绕过网络与模型）；阶段一/二/三/四/五回归 34/34、34/34、42/42、76/76、51/51 无回归。

### 决策落实
- 账号视频批量处理仅建议用于有权访问的内容，尊重平台服务条款与版权（§4 边界 #2/#3），不规避任何登录/版权保护机制；副本默认不保存（D3）。
- 沿用各阶段隐私红线：本地优先、默认不上云、缓存仅落本地私有 `.cache`、临时沙箱 keep=False 不留存副本（D3/审阅 G）。
- yt-dlp 为「用户自装的外部工具」（可选 pip 依赖，非强制）；抖音/小红书 等平台支持随其策略变动，失败即显式提示、不静默失败。

### 待办（后续）
- 小红书/抖音 受平台反爬与签名 URL 影响，yt-dlp 覆盖率可能随平台更新波动；必要时可经浏览器捕获回退（browser 技能）或外部连接器增强。
- D14 OCR 复杂版面增强仍列可选增强模块（未实现）。

## [0.5.0] — 2026-08-28 · 阶段五落地（在线/加密视频文案提取：yt-dlp 优先下载 / 加密回退浏览器捕获，副本不保存 D3、法律风险提示 §4 边界 #2）

### 新增
- **阶段五 · 在线/加密视频文案提取（video_online，已实现，本地优先、默认不上云）**：
  - `modules/video_online/`：`VideoOnlineModule`（ready=True）+ `providers/`（IVideoOnlineProvider 接口 + `YtDlpProvider` 默认本地引擎：yt-dlp 优先下载至私有 tmp 沙箱 + `BrowserCaptureProvider` 加密/DRM 回退：依赖 browser 技能做「播放中捕获」）+ `__init__.py`（PROVIDERS 注册）。
  - **yt-dlp 优先（本地内置、可选依赖）**：下载至 `TempSandbox`（keep=False → 处理后即删，不留存副本，D3/审阅 G）；抽音轨复用阶段一/二 Whisper 管线（`transcribe_core`）；D13 讲解段帧 + 双通道输出（D11）；全程仅产出文案/字幕/结构化，**不产出视频副本**（D3/⑩）。
  - **加密/DRM 回退（D9 协同）**：yt-dlp 报加密或失败时回退 `BrowserCaptureProvider`（依赖 browser 技能）；用户提供 `--capture-path` 本地录制文件 → 模块不留存副本（external，不删）；无捕获文件则显式抛错（不静默失败）。
  - **强约束透明回显（D15/§4.7）**：产出 `fields.online`/`no_copy_saved`/`acquire_method`/`encrypted` + `legal_risk_warning`（加密场景，§4 边界 #2 法律灰区 + 质量风险提示）；`provider_meta` 透明「用了谁、是否上云」。
  - **哈希缓存（D12·L）**：按 URL 缓存转写结果（key 对 URL 求哈希，避免把 URL 当文件路径打开）；仅落本地私有 `.cache`，不外传。
  - **批量聚合报告（D12·H）**：多 URL 聚合 `info-extract-video-online-report.{md,json}`（含异常清单，不静默放过）。
  - 双通道输出（D11）+ 审阅 F 关键帧（--vision）+ 路由/汇总/选项对齐（`router.py --capture-path`、`build_options` 对缺失字段健壮）。
- **Provider 注册（D15）**：`provider_registry` 注册 `VIDEO_ONLINE`（默认 `yt-dlp`，本地内置、离线；回退 `browser-capture`）；`router --check` 可见 video_online 两类 provider 可用性（yt-dlp 缺则提示安装；browser 依赖外部技能）。
- **验证**：新增 `tests/verify_phase5.py`（IO/URL 路由、Provider 注册、yt-dlp 单元、浏览器捕获单元含 D9 自检/加密法律提示、全链路 mock 下载+fake 推理、加密回退、无 provider 引导、哈希缓存命中、router 路由/--capture-path/--check，51 项全绿，mock provider 绕过网络与模型）；阶段一/二/三/四回归 34/34、34/34、42/42、76/76 无回归。

### 决策落实
- 沿用各阶段隐私红线：本地优先、默认不上云、缓存仅落本地私有 `.cache`、临时沙箱 keep=False 不留存副本（D3/审阅 G）、敏感内容走 DESEN 闸门（如已装）。
- yt-dlp 为「用户自装的外部工具」（可选 pip 依赖，非强制），本技能零新增必需依赖即可接入（未装则优雅降级为浏览器捕获回退或清晰安装引导）；browser 为外部技能（D9 协同），非 pip 依赖。
- 加密/DRM 视频属法律灰区：仅显式提示风险、不规避版权保护机制（§4 边界 #2），不静默失败。

### 待办（后续阶段）
- D14 OCR 复杂版面增强：公式 OCR + 版面分析 + VLM 拓扑重建列可选增强模块（首版先交付纯文本）。
- 视觉栈后续可接入本地增强（D14）/ 云端 / 外部技能 / 连接器（§0.6），经可插拔 Provider 扩展。
- `doc_extract`（复合文档原生文本抽取）仍占位：原生文本层页按 D10 分工交外部 `document_text` 技能，本技能只做媒体抽取。

## [0.4.0] — 2026-08-28 · 阶段四落地（画面解读 / 本地 VLM 视觉理解：档位自适应 D7 + OCR 协同 + D13/审阅 F 衔接）

### 新增
- **阶段四 · 画面解读（image_understanding，已实现，本地优先、默认不上云）**：
  - `modules/vision/`：`VisionModule` + `providers/`（IVisionProvider 接口 + `LocalVLMProvider` 默认本地引擎：ollama + Qwen2.5-VL，权重本地、数据不出本机）+ `tier.py`（D7 档位自适应）+ `frame_sampling.py`（审阅 F 场景切换关键帧采样）+ `vision_caption.py`（核心：提示词构造 / OCR 协同 / caption / D13 填充 / 整视频关键帧分析）+ `output.py`（D11 双通道）。
  - **共享视觉栈**：图片与视频帧共用同一套 caption 逻辑（方案 §3 阶段四）；视频帧经 D13 抽帧 / 审阅 F 关键帧采样后，由同一视觉栈解读（见 modules.video 衔接）。
  - **OCR 协同（§1.1 B.3）**：默认先取图中文字（复用 OCR provider），再结合画面语义整体理解；可由 `--no-ocr-vision` 关闭。
  - **本地 VLM（默认 provider：local-vlm / ollama + Qwen2.5-VL，零新依赖）**：经 ollama 的 HTTP REST API（标准库 `urllib`，`http://localhost:11434`）发送图片 base64 + 提示词，**不引入 ollama Python 包或额外网络库**。
  - **档位自适应（D7）**：安装时按硬件探测选最优档并落盘缓存（`.vision_tier.json`）；运行时复探可自动下调一档（标记 `_downgraded`，§3.3 仅被迫降级才告知）；用户可用 `--vision-tier`（0/1/2/3 或完整 ollama 标签或中文名）/ 环境变量 `INFO_EXTRACT_VISION_TIER` 覆盖。帧采样密度随档位递增（审阅 F：轻量 8 帧/2s → 旗舰 24 帧/0.5s）。
  - **D13 视觉填充**：为阶段二讲解段帧填充 `vision_caption` / `ocr_on_frame`（语义重合度判定的视觉栈部分；VLM 不可用则留 None + note，不静默失败）。
  - **审阅 F 整视频关键帧采样 + 视觉描述**：`--vision` 开启，对视频做场景切换检测（average hash 感知哈希 + 关键帧去重）抽关键帧并逐帧 VLM 解读 + OCR 协同；VLM 不可用则仅保留帧图与 OCR 文字。
  - **云端升级（D2 交互范式）**：本地 VLM 不可用（未装 ollama / 算力不足）→ 标记 `suggest_cloud_upgrade` + `upgrade_hint`（提及脱敏闸门、原始图留本机），**不自动上云、上云前须经脱敏闸门**（§4.4）；拒绝则仅交付 OCR 文字、保证不上云。
  - 双通道输出（D11）+ 哈希缓存（D12·L）+ `provider_meta` 透明回显（D15/§4.7，含 provider/source_layer/cost/ocr_provider）+ 批量聚合报告（D12·H，含异常清单）。
- **Provider 注册（D15）**：`provider_registry` 注册 `VISION`（默认 `local-vlm`，本地内置、离线）；`router --check` 可见 vision provider 可用性（未装 ollama 显示 ⬜ local）。
- **路由与配置**：`utils/io.py` 图片归 `OCR`（视觉栈在 VisionModule 内经 OCR 协同 + VLM 复用）；`router.py` 新增画面解读选项 `--vision`（整视频关键帧视觉分析）/ `--vision-tier` / `--no-ocr-vision`；汇总展示对 VISION 源友好（VLM 可用 / 档位 / OCR 协同 / 上云提质提示 / D13 已填描述帧数 / 审阅 F 关键帧数）。
- **验证**：新增 `tests/verify_phase4.py`（IO 路由/注册、提示词构造、全链路 mock VLM+OCR 协同、VLM 不可用上云提质、关闭 OCR 协同、哈希缓存命中、批量聚合、D13 帧填充、审阅 F 关键帧、LocalVLMProvider 单元含异常路径、档位自适应、router 选项，76 项全绿，mock provider 绕过 ollama）；阶段一/二/三回归 34/34、34/34、42/42 无回归。

### 决策落实
- 沿用各阶段隐私红线：本地优先、默认不上云、哈希缓存仅落本地私有 `.cache`、敏感内容走 DESEN 闸门（如已装）。
- ollama 为「用户自装的外部运行时」（非 pip 依赖），本技能零新增 Python 依赖即可接入（标准库 urllib 直连）；未装时优雅降级、清晰引导，不静默失败。

### 待办（后续阶段）
- 阶段五：在线/加密视频受限场景（yt-dlp / 浏览器捕获，副本默认不保存）。
- D14 OCR 复杂版面增强：公式 OCR + 版面分析 + VLM 拓扑重建列可选增强模块（首版先交付纯文本）。
- 视觉栈后续可接入本地增强（D14）/ 云端 / 外部技能 / 连接器（§0.6），经可插拔 Provider 扩展。

## [0.3.0] — 2026-08-28 · 阶段三落地（OCR：rapidocr 本地离线 + PDF 探测分流 + 图像预处理 + 置信度门控上云）

### 新增
- **阶段三 · OCR（已实现，本地优先、完全离线）**：
  - `modules/ocr/`：`OCRModule` + `providers/`（`IOCRProvider` 接口 + `RapidOcrProvider` 默认本地引擎 rapidocr+onnxruntime，PP-OCRv6，模型随 wheel 捆绑）+ `preprocess.py`（图像预处理链：归一化/EXIF 校正/可选去噪/超分/deskew）+ `pdf.py`（pypdfium2 页面渲染 + 类型探测）+ `output.py`（D11 双通道）。
  - 路由：图片（.png/.jpg/.jpeg/.webp…）→ `SourceType.OCR` → `OCRModule`；**图片型/扫描件 PDF（.pdf）从复合文档抽出，单独归 OCR**（阶段三），模块内做类型探测分流。
  - PDF 类型探测分流（审阅 E / D10 分工）：`detect_pdf_pages` 判定每页是否含原生文本层；纯图页渲染+OCR，文本层页默认跳过并提示走 `document_text`（原生文本抽取交外部技能，info-extract 只做媒体抽取）；加密 PDF 捕获提示密码（审阅 I），不静默失败。
  - 图像预处理链（审阅 D）：归一化（最长边≤2000px，DESEN 实测稳定区）、EXIF 方向校正、可选去噪（中值滤波）/超分/deskew（优先 cv2 霍夫，缺失降级），逐步骤透明回显。
  - 置信度门控上云（D2 / 审阅 D，替代旧「手写/模糊一刀切」）：本地平均置信度<阈值 → 标记 `local_quality_limited` + `suggest_cloud_upgrade`（D2 交互范式），**不自动上云、上云前须经脱敏闸门**（§4.4）。
  - 双通道输出（D11）+ 哈希缓存（D12·L）+ `provider_meta` 透明回显（D15/§4.7，含 provider/source_layer/cost）+ 批量聚合报告（D12·H，含异常清单）。
  - 引擎惰性实例化+跨调用缓存；`available()` 仅探测 import，缺失即降级引导（不静默失败）。
- **Provider 注册（D15）**：`provider_registry` 注册 `OCR`（默认 `rapidocr`，本地内置、离线）；`router --check` 可见 OCR provider 可用性（缺依赖显示 ⬜ local）。
- **路由与配置**：`utils/io.py` 将 .pdf 从 `DOC_EXT` 抽出、归 `OCR`；`router.py` 新增 OCR 选项 `--confidence-threshold` / `--force-ocr` / `--no-preprocess`，汇总展示对 OCR 源友好（页数/框数/质量受限提示/文本层页提示）。
- **依赖**：`requirements.txt` 补 Pillow / rapidocr>=3.9 / onnxruntime>=1.19 / pypdfium2>=4.30（均本地、离线）。
- **验证**：新增 `tests/verify_phase3.py`（IO 路由/预处理降级/双通道输出/全链路/置信度门控/PDF 分流/缓存/批量/注册与路由/可选真实 rapidocr，37 项全绿，mock provider 绕过模型下载）；阶段二 `verify_phase2.py` 回归 34/34 无回归。

### 决策落实
- 沿用阶段一/二隐私红线：本地优先、默认不上云、哈希缓存仅落本地私有 `.cache`、敏感内容走 DESEN 闸门（如已装）。
- PDF 原生文本层抽取严格按 D10 分工交 `document_text`，info-extract 不重造。

### 待办（后续阶段）
- 阶段四：本地 VLM 画面解读（档位自适应 D7），与视频帧共用视觉栈；为 D13 填充 `vision_caption`/`ocr_on_frame`。
- 阶段五：在线/加密视频受限场景（yt-dlp / 浏览器捕获，副本默认不保存）。
- D14 OCR 复杂版面增强：公式 OCR + 版面分析 + VLM 拓扑重建列可选增强模块（首版先交付纯文本）。

## [0.2.0] — 2026-08-28 · 阶段二落地（视频文案提取 + D13 讲解段关联帧）

### 新增
- **阶段二 · 视频文案提取（本地视频文件，已实现）**：
  - `modules/video/`：`VideoModule` + `frames.py`。从视频容器用 PyAV 抽取音轨，复用阶段一 Whisper 转录管线（`transcribe_core`），产出与音频一致的双通道（txt/srt/json/md）。
  - 路由：本地视频文件（.mp4/.mov/.mkv…）→ `SourceType.VIDEO` → `VideoModule`；在线视频 URL（http/ftp）→ `SourceType.VIDEO_ONLINE` → 阶段五占位模块。
  - 无音轨视频清晰报错（不静默失败），并引导改用画面解读能力（阶段四）。
- **D13 讲解段关联帧抽取（规划项落地）**：
  - 规则信号：转录含「如图 / 如图所示 / 这张图 / 这个流程图 …」等指代词（中英）即判为讲解画面段。
  - 取该段中点时间戳 → PyAV seek 解码 → 转 rgb24 → **标准库 `zlib` 手写 PNG 写出**（规避本机 ffmpeg 图像编码器受限，零新依赖）。
  - 帧图落本地 `<out>/<stem>_frames/`，默认不自动上云；`referenced_frame` 含 `frames` 列表（timestamp / frame_path / segment_text / is_visual_explanation），`vision_caption`/`ocr_on_frame` 预留待阶段四视觉栈填充。
  - `--no-frames` 可关闭帧抽取，仅产出文案。
- **转录核心重构（D15 复用）**：阶段一的转录逻辑抽为 `transcribe_core(samples, sr, …)`，音频/视频共用，保证输出/缓存行为一致；阶段一既有逻辑与缓存键不变。
- **类型与路由扩展**：`SourceType` 新增 `VIDEO`；`utils/io.py` 视频扩展名改路由到 `VIDEO`、`is_url()` 识别在线视频；`provider_registry` 注册 `VIDEO`（复用音频 Whisper provider 供 `--check`）。
- **文档对齐**：`SKILL.md` / `assets/capabilities.json` 标记 `video_transcript` `ready=true`；`references/reference.md` 更新目录/契约/D13/阶段衔接。

### 决策落实
- D13（视频讲解段关联帧）落地规则信号部分；语义重合度判定（需视觉栈）留待阶段四。
- 阶段二沿用阶段一隐私红线：本地优先、默认不上云、哈希缓存仅落本地私有目录、敏感内容走 DESEN 闸门（如已装）。

### 待办（后续阶段）
- 阶段三：OCR（rapidocr+onnxruntime）、PDF 类型探测分流、图像预处理+置信度门控上云。
- 阶段四：本地 VLM 画面解读（档位自适应 D7），与视频帧共用视觉栈；为 D13 填充 `vision_caption`/`ocr_on_frame`。
- 阶段五：在线/加密视频受限场景（yt-dlp / 浏览器捕获，副本默认不保存）。

## [0.1.0] — 2026-08-28 · 三仓库初始化 + 阶段一落地

### 新增
- **三处仓库初始化**（方案 §0 / D5）：本地仓库 `~/Repositories/info-extract`（git 源）建好；技能仓库 `~/.workbuddy/skills/info-extract` 软链到本地仓库（干净部署副本）；工作空间保留规划文档与开发记忆。
- **技能骨架（D8/D9/D11/D15）**：
  - 主入口 `scripts/router.py`：类型识别 + 按需路由（命中类型才加载模块，未命中不预载重型依赖）。
  - `provider_registry.py`：可插拔 Provider 注册表（默认本地优先、显式指定覆盖、全不可用降级）。
  - `quality_scorer.py`：质量评分驱动自动升级。
  - `skill_bridge.py`：协同能力自检（DESEN/document_text/browser，D9）。
  - `utils`：io（发现+类型识别）、hash_cache（D12·L）、tmp（D12·G 隐私闭环）。
  - `base.py`：标准输出契约 `ExtractResult`（D11 双通道 source/confidence/fields/media_ref/provider_meta）。
  - `SKILL.md` 暴露 `ocr`/`speech_transcription`/`video_transcript` 关键词（D9）；`assets/capabilities.json` 声明能力（含 `ready` 标志）。
- **阶段一 · 音频转录（已实现）**：
  - 本地 Whisper 转录 + 时间戳（SRT/TXT）+ 结构化 JSON/MD（D11）。
  - `FasterWhisperProvider`（默认，faster-whisper，离线）+ `WhisperCppProvider`（可选二进制）。
  - VAD/静音分块长音频（D12·J，内存切片、不落盘临时分块）。
  - 语言/任务轻提示（文件名/对话 hint，D12·K）。
  - 批量输入 + 聚合报告（D12·H，含异常清单）。
  - 哈希缓存（D12·L）、provider_meta 透明回显（D15/§4.7）。
  - 音频解码用 PyAV（自带 ffmpeg），免去系统 ffmpeg 依赖。
- **占位模块**：OCR / 视觉 / 文档抽取 / 在线视频 先置惰性桩，命中即清晰提示「规划中」，不静默失败（D9/D15）。

### 决策落实
- D1–D15 全部收敛（见 `info-extract-方案.md` §5）。
- 复用 DESEN 的 venv/安装范式（CPython 3.13 锁定、隔离 venv、依赖不污染系统）。

### 待办（后续阶段）
- 阶段二/五：视频文案（ffmpeg 抽轨复用音频）、在线/加密视频受限场景。
- 阶段三：OCR（rapidocr+onnxruntime）、PDF 类型探测分流、图像预处理+置信度门控上云。
- 阶段四：本地 VLM 画面解读（档位自适应 D7），与视频帧共用视觉栈。
