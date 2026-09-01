# info-extract · 设计参考（按需读取，不自动加载）

> 本文件是模块契约与架构的单一事实来源，供实现阶段参考；日常使用请看 `SKILL.md`。

## 1. 目录布局

```
scripts/
  router.py                # 主入口：类型识别 + 按需路由（D8）
  provider_registry.py     # Provider 注册表（D15）
  quality_scorer.py        # 质量评分（D15 自动升级依据）
  skill_bridge.py          # 协同能力自检（D9）
  modules/
    base.py                # SourceType / Segment / ExtractResult / IModule
    audio/                 # 阶段一（已实现）
      transcribe.py        # AudioModule 编排
      vad.py               # 音频加载(PyAV) + VAD 分块(D12·J)
      language.py          # 语言/任务轻提示(D12·K)
      output.py            # 双通道输出(D11) + SRT/TXT/JSON/MD
      providers/           # ITranscriptProvider + faster-whisper + whisper.cpp
    ocr/                    # 阶段三（已实现）：OCRModule + providers/(IOCRProvider+rapid_ocr) + preprocess.py + pdf.py + output.py
    vision/                 # 阶段四（已实现）：VisionModule + providers/(IVisionProvider+local_vlm) + tier.py(D7) + frame_sampling.py(审阅F) + vision_caption.py + output.py
    doc_extract/            # 占位桩（原生文本层页按 D10 交 document_text，本技能只做媒体抽取）
    video_online/          # 阶段五（已实现）+ 方案 B 增强：VideoOnlineModule + providers/(IVideoOnlineProvider+YtDlpProvider+BrowserCaptureProvider+YtDlpEnumProvider(IAccountEnumProvider)+yt_common)
  utils/
    io.py                  # 发现 + 类型识别
    hash_cache.py          # 哈希缓存(D12·L)
    tmp.py                 # 临时沙箱(D12·G)
```

## 2. 标准输出契约（D11）

每条结果 = `ExtractResult`：
- `source`：`ocr` / `vision` / `transcript`
- `text`：纯文本主体（喂 summarize 纯文本通道）
- `confidence`：平均置信度（音频=词级概率均值）
- `fields`：关键字段（检测语言 / 时长 / 模型 / 段数）
  - **OCR 专属 fields**：`num_boxes`（框数）、`confidence_threshold`、`local_quality_limited`（置信度门控 D2 标记）、`pdf_pages`（逐页页数/框数/平均置信度）、`text_layer_pages_skip`（原生文本层页，D10 分工交 `document_text`）、`preprocess_steps`（预处理步骤日志）；`media_ref` 含 `is_pdf`/`pages`/`suggest_cloud_upgrade`/`upgrade_hint`。
- `media_ref`：来源路径 / 时间戳 / 产出文件路径 / 状态
- `referenced_frame`：视频专属（D13，阶段二已实现抽帧、阶段四已填视觉描述）：结构为 `{frames:[{timestamp, frame_path, vision_caption, ocr_on_frame, vision_tier, is_visual_explanation, segment_text, extracted}], note}`；`vision_caption`/`ocr_on_frame` 由阶段四视觉栈（本地 VLM + OCR 协同）填充，VLM 不可用时留 null 并追加 note（不静默失败）。
- `provider_meta`：用了哪个 provider、是否上云（D15/§3.7 透明回显）
  - **video_online 专属 fields（阶段五已实现）**：`online`（=True）、`no_copy_saved`（副本不保存 D3）、`acquire_method`（yt-dlp / browser-capture）、`encrypted`（是否加密/DRM）、`legal_risk_warning`（加密场景，§3 边界 #2 法律灰区 + 质量风险）；`media_ref` 含 `url`/`status`(ok|cached|error)/`online`/`no_copy_saved`/`acquire_method`/`encrypted`/`outputs`/`legal_risk_warning`，并产出聚合报告 `info-extract-video-online-report.{md,json}`（D12·H，含异常清单）。**方案 B 增强**：`media_ref` 增加 `from_account`（来自账号/合集枚举展开）；`provider_meta.enum_provider` 标注枚举 provider（="yt-dlp-enum"）；聚合报告 JSON 增加 `account_enum`（账号→枚举明细），报告正文增加「账号/合集枚举明细」与 ToS 提示（§3 边界 #2/#3）。

落盘双通道：`*.txt`（纯文本）、`*.srt`（字幕）、`*.json` + `*.md`（结构化，含 source/confidence/fields/media_ref/provider_meta）。批量时额外生成 `info-extract-transcript-report.{md,json}` 聚合报告（D12·H）。

## 3. Provider 可插拔（D15）

- 每个能力域一个统一接口（`ITranscriptProvider` 等），签名：输入(路径/ndarray + 语言/任务/约束) → 输出(Segment 列表 + info)。
- 来源分层：① 本地内置（faster-whisper/whisper.cpp）② 本地增强 ③ 云端 ④ 外部技能 ⑤ 连接器。
- 选择：默认本地优先；显式指定 > 自动；全不可用 → 首个 provider（available=False），调用方给降级提示，不静默失败。
- 涉及上云/外部调用 → 穿透交互确认门（⑧⑨）+ 上云前脱敏闸门（DESEN，§3.4）。

## 4. 关键实现决策

- **音频解码走 PyAV**：本机实测无系统 ffmpeg，PyAV 自带 ffmpeg 库，零系统依赖、离线、数据不出本机。
- **视频抽音轨复用同一 PyAV 链路**：`load_audio` 对视频容器同样有效（解码其音轨），故阶段二视频文案直接复用阶段一转录管线（`transcribe_core`），无需重写。
- **视频帧写出零新依赖**：本机 ffmpeg 构建的 mjpeg/png 图像编码器受限，故 D13 帧抽取用 PyAV 解码 + 标准库 `zlib` 手写 PNG 写出（`modules/video/frames.py`），不引入 Pillow 等额外依赖。
- **OCR 本地离线（阶段三）**：默认 `rapidocr + onnxruntime`（PP-OCRv6，模型随 wheel 捆绑，完全离线、数据不出本机）；统一 RGB 输入 → 内部翻转 BGR 适配；引擎惰性实例化 + 跨调用缓存；`available()` 仅探测 import，缺失即降级引导安装、不静默失败。
- **图像预处理链（审阅 D）**：归一化（最长边≤2000px，DESEN 实测稳定区 1000–2100px）+ EXIF 方向校正 + 可选中值滤波去噪 / 轻量超分 / deskew（优先 cv2 霍夫直线检测，缺失降级跳过）；逐步骤透明回显（`preprocess_steps`）。PIL/cv2 缺失均优雅降级不崩。
- **PDF 类型探测分流（审阅 E / D10）**：`pypdfium2` 探测每页是否含原生文本层；纯图页渲染+OCR，文本层页默认跳过并提示走 `document_text`（分工 B，原生文本抽取交外部技能）；加密 PDF 捕获异常提示输入密码（审阅 I），不静默失败。
- **置信度门控上云（D2 / 审阅 D，替代旧「手写/模糊一刀切」）**：本地平均置信度 < 阈值 → 标记 `local_quality_limited` + `suggest_cloud_upgrade`（D2 交互范式），**不自动上云、上云前须经脱敏闸门**（§3.4）；原始图绝不整份留云。
- **长音频分块不落盘**：faster-whisper 直接接受 float32 16k ndarray，故 VAD 分块在内存切片后直传，无需写临时 WAV（更省、更隐私）。
- **能力声明 vs 就绪**：SKILL.md 暴露 ocr/speech_transcription/video_transcript/image_understanding/video_online 关键词（D9 机器可发现）；`assets/capabilities.json` 用 `ready` 标志标注当前五者均已就绪——命中规划中能力时模块给出清晰提示，不静默失败。
- **画面解读本地 VLM（阶段四）**：默认 `LocalVLMProvider`（ollama + Qwen2.5-VL，权重本地、数据不出本机）；经 ollama HTTP REST（`stdlib urllib`，`http://localhost:11434`）发送图片 base64 + 提示词，**零新增 Python 依赖**。VLM 无干净置信度 → `confidence=None`（§3.1 透明），由 quality_scorer 给「请人工核对」建议。
- **OCR 协同（§1.1 B.3）**：画面解读默认先取图中文字（复用 OCR provider，同源 RGB 输入），再结合画面语义整体理解；可由 `--no-ocr-vision` 关闭。
- **VLM 档位自适应（D7）**：`tier.py` 安装时按硬件（GPU 显存 / 统一内存 / RAM）探测选最优档并落盘缓存（`.vision_tier.json`）；运行时复探可自动下调一档（标记 `_downgraded`）；用户可用 `--vision-tier`（0/1/2/3 或完整 ollama 标签或中文名）/ 环境变量 `INFO_EXTRACT_VISION_TIER` 覆盖。帧采样密度随档位递增（审阅 F：轻量 8 帧/2s → 旗舰 24 帧/0.5s）。
- **场景切换关键帧采样（审阅 F）**：`frame_sampling.py` 以固定间隔解码视频帧，计算 average hash（8×8 感知哈希），相邻帧哈希距离超阈值即判场景切换、记为关键帧，近邻关键帧过近则去重；关键帧 PNG 落 `<out>/<stem>_keyframes/`（标准库 `utils.image.write_png_rgb`，零新依赖）。容错：解码失败返回已采部分，不静默抛错。
- **D13 视觉填充**：阶段二抽出的讲解段帧由 `vision_caption.fill_d13_frames` 经同一 VLM 视觉栈填 `vision_caption`/`ocr_on_frame`（规则信号已在阶段二落地）；VLM 不可用则留 null + note。
- **审阅 F 整视频视觉分析**：`--vision` 开启时 `analyze_video_frames` 对视频做场景切换关键帧采样 + 逐帧 VLM 描述 + OCR 协同，供视频「画面识别分类」；VLM 不可用则仅保留帧图与 OCR 文字。
- **在线/加密视频（阶段五，已实现）**：URL 经 router 路由到 `video_online` 模块；`YtDlpProvider` 优先用 yt-dlp 下载至 `TempSandbox`（keep=False → 处理后即删，不留存副本，D3/审阅 G）→ PyAV 抽音轨复用 `transcribe_core`；加密/DRM 或下载失败时回退 `BrowserCaptureProvider`（依赖 browser 技能做「播放中捕获」，D9），用户提供 `--capture-path` 本地录制文件则标记为 external（模块不删）；全程仅产出文案/字幕/结构化，**不产出视频副本**（D3/⑩）。yt-dlp 为可选 pip 依赖（非强制），未装则优雅降级为浏览器捕获回退或清晰安装引导；加密场景显式提示法律灰区与质量风险（§3 边界 #2），不静默失败。
  - **哈希缓存按 URL（D12·L，阶段五）**：`hash_cache` 的 `key` 对 URL 求哈希（`sha256_text`）而非打开文件，避免把在线视频 URL 当本地文件路径打开；缓存仅落本地私有 `.cache`，不外传。
  - **账号/合集枚举（方案 B，阶段五增强）**：新增 `IAccountEnumProvider` 接口 + `YtDlpEnumProvider`（默认 yt-dlp `--flat-playlist -j` 列出账号/合集/频道下全部视频，不去重下载整份播放列表）；注册为 `VIDEO_ONLINE_ENUM` 能力（D15）。`VideoOnlineModule.run` 经 `detect_account_url()` 识别抖音/小红书/B站 账号页、频道、播放列表（单条视频 URL 不误判），或 `--playlist` 强制枚举；枚举出视频 URL 列表后逐条走 `YtDlpProvider` 下载 + `transcribe_core` 转录。枚举不产出本地文件（`external=False`）；枚举失败/空账号/需登录态均显式抛 `InfoExtractError`（recoverable + hint），不静默失败。
  - **cookie 登录态适配（方案 B）**：`yt_common.build_cookie_args(options)` 把 `--cookies <cookies.txt>` / `--cookies-from-browser <browser>` 翻译为 yt-dlp 参数，贯穿枚举与下载命令（抖音/小红书/B站 账号视频常需登录态）；命中登录态错误即提示注入 cookie（§3 边界 #2/#3）。`DRM_KEYWORDS`/`LOGIN_KEYWORDS` 统一判定加密与需登录。
  - **账号来源透明标注（方案 B）**：枚举展开的每条视频结果写入 `media_ref.from_account`（来源账号/合集 URL）与 `provider_meta.enum_provider="yt-dlp-enum"`；聚合报告 `info-extract-video-online-report.{md,json}` 新增「账号/合集枚举明细」（平台/条目数/各视频 URL）与 ToS 提示（§3 边界 #2/#3），JSON 含 `account_enum` 与 `from_account`。
  - **防风控限速（方案 B 后续强化，0.6.1）**：账号/合集批量展开后逐条视频**顺序**处理，相邻视频之间随机休眠（默认 `enum_interval=3.0` 秒，抖动 0.5x~1.5x），避免固定节奏被平台识别为爬虫；`--enum-limit <条数>` 限制单账号处理数量（超大账号分批）；`--no-throttle` 关闭限速（仅当用户明确拥有内容并接受风控风险时，且聚合报告显式标注）；聚合报告含「防风控限速」说明。风控原则：批量处理他人账号视频可能触发频率限制甚至封号，请勿高频、请勿用于无权访问的内容（§3 边界 #2/#3）。
  - **隐私闭环**：哈希缓存仅落本地私有 `.cache`；临时文件走 `TempSandbox`（默认 `.tmp`，处理后清理）；在线/加密视频场景 `keep=False` 强制不落盘（审阅 G）。

## 5. 后续阶段衔接

- 阶段二（已实现）：视频 `PyAV` 抽音轨 → 复用 `audio` 模块 `transcribe_core`；D13 讲解段关联帧（规则信号命中即抽帧，标准库 PNG）。
- 阶段五（已实现）：在线/加密视频文案提取（video_online）：URL 经 router 路由到 `video_online` 模块；yt-dlp 优先下载至私有 tmp 沙箱（keep=False 不留存副本，D3/审阅 G）→ PyAV 抽音轨复用 Whisper 转录；加密/DRM 回退「浏览器播放中捕获」（BrowserCaptureProvider，依赖 browser 技能，D9），用户提供 `--capture-path` 本地录制文件；仅产出文案/字幕/结构化（不产出视频副本，D3/⑩），加密显式法律灰区与质量风险提示（§3 边界 #2），不静默失败。
- 阶段三（已实现）：OCR `rapidocr+onnxruntime` 接入，PDF 类型探测分流（审阅 E），图像预处理链 + 置信度门控上云（D2）。
- 阶段四（已实现）：本地 VLM（ollama + Qwen2.5-VL，档位自适应 D7，零新依赖）视觉理解；OCR 协同（§1.1 B.3）；与视频帧共用视觉栈（方案 §2 阶段四）；为 D13 的 `vision_caption`/`ocr_on_frame` 填充视觉描述；`--vision` 整视频场景切换关键帧采样 + 视觉描述（审阅 F）；VLM 不可用则仅交付 OCR 文字并标记建议上云提质（D2/§3.4）。
