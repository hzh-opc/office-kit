---
name: info-extract
description: "跨智能体、跨平台的信息抽取技能：本地优先抽取 OCR 文字 / 音频转录（语音转写、字幕）/ 视频文案 / 图片与视频画面解读 / 在线·加密视频文案。五大能力均已实现（speech_transcription、video_transcript、ocr、image_understanding、video_online，含账号/合集枚举 + cookie 适配 + 防风控限速），默认本地处理、默认不上云，支持按类型自动路由与按需载入，可对接脱敏技能（DESEN）做上云前脱敏。触发词：提取文字 / 转录 / 转写 / 语音转文字 / 听写 / 字幕生成 / 视频文案 / 视频转文字 / 图片转文字 / 截图转文字 / 扫描件转文字 / PDF文字提取 / 画面解读 / 图片理解 / 图表解读 / 视频帧分析 / 在线视频 / 加密视频 / 账号视频 / 抖音 / 小红书 / bilibili / youtube。"
version: "0.6.3"
agent_created: true
tags: [ocr, speech_transcription, video_transcript, image_understanding, video_online, video_online_enum, 信息抽取, 转录, 字幕, 本地优先, 隐私, 抖音, 小红书, 账号视频]
---

# info-extract · 信息抽取技能

> **定位**：跨智能体（WorkBuddy / Claude / Codex / OpenClaw 等）、跨平台（Windows / macOS / Linux）的本地优先信息抽取技能，覆盖 OCR、音频转录、视频提取、画面解读四大能力域。
> **核心原则**：本地优先 · 默认不上云 · 机器结果须经你确认（方案 §4 / 流程规范 §1）。
> **当前阶段**：阶段一 · 音频转录（已实现）+ 阶段二 · 视频文案（已实现：PyAV 抽音轨复用 Whisper 转录 + D13 讲解段关联帧抽取）+ 阶段三 · OCR（已实现：rapidocr 本地离线 + 图片型 PDF 探测分流 + 图像预处理链 + 置信度门控上云）+ 阶段四 · 画面解读（已实现：本地 VLM 视觉理解，ollama + Qwen2.5-VL 档位自适应 D7 + OCR 协同 + D13 帧填充 + 审阅 F 关键帧采样）+ 阶段五 · 在线/加密视频文案提取（已实现：yt-dlp 优先下载 / 加密回退浏览器捕获，副本默认不保存 D3、显式法律风险提示 §4 边界 #2）。

## 一、能做什么（能力域）

| 能力域 | 状态 | 说明 |
|--------|------|------|
| ① 音频转录（speech_transcription） | ✅ 已实现（阶段一） | 本地 Whisper 转录+时间戳；长音频 VAD 分块；外语/方言轻提示；批量+聚合报告；双通道输出 |
| ② 图片 OCR（ocr） | ✅ 已实现（阶段三） | rapidocr + onnxruntime（PP-OCRv6，完全离线）；图像预处理链（归一化/去噪/deskew）；置信度门控上云（D2）；图片型/扫描件 PDF 探测分流（纯图页 OCR，原生文本层页交 document_text，D10）；逐框置信度 + provider_meta 透明回显（D15） |
| ③ 图片/视频画面解读（image_understanding） | ✅ 已实现（阶段四） | 本地 VLM（ollama + Qwen2.5-VL，档位自适应 D7，零新依赖）+ OCR 协同（§1.1 B.3）；为阶段二 D13 讲解段帧填充 vision_caption/ocr_on_frame；`--vision` 整视频场景切换关键帧采样 + 视觉描述（审阅 F）；VLM 不可用则仅交付 OCR 文字并标记建议上云提质（D2/§4.4） |
| ④ 视频文案（video_transcript） | ✅ 已实现（阶段二） | 本地 ffmpeg(PyAV) 抽音轨 → 复用 Whisper 转录；D13 讲解段关联帧抽取（标准库 PNG 写出，零新依赖）；在线/加密视频见 ⑤ |
| ⑤ 在线/加密视频文案（video_online） | ✅ 已实现（阶段五 + 方案 B 增强） | yt-dlp 优先下载至私有 tmp 沙箱（keep=False → 处理后即删，不留存副本，D3）→ PyAV 抽音轨复用 Whisper 转录；加密/DRM 或下载失败回退「浏览器播放+捕获」（依赖 browser 技能，D9）；仅产出文案/字幕/结构化，不产出视频副本（D3/⑩）；加密显式法律灰区与质量风险提示（§4 边界 #2），不静默失败。**方案 B 增强（阶段五·增强）**：账号/合集枚举——抖音/小红书/B站 等账号 URL 自动识别并枚举其下全部视频，逐条走上述下载+转录管线；cookie 登录态适配 `--cookies`/`--cookies-from-browser` 贯穿枚举与下载；枚举失败/空账号/需登录均显式提示、不静默失败；聚合报告含「账号/合集枚举明细」与 ToS 提示（§4 边界 #2/#3） |

## 二、怎么用（对话式，无需参数）

把音频交给本技能即可，例如：
- 「帮我把这段录音转成文字，并标出时间」
- 「转录这个会议录音，这是日文采访」
- 「把这摞音频都转写一下」（批量，审阅 H）

底层引擎默认本地 Whisper（small）；噪声明/方言可说「用 medium 模型」升级。所有处理默认在本地、不上云。

## 三、命令行（高级/批量）

技能目录 `scripts/` 下主入口 `router.py`：

```bash
# 转录单个音频（自动识别类型）
python router.py 录音.mp3
# 批量目录 + 递归 + 指定输出目录
python router.py ./音频 --recursive --out ./结果
# 语言/任务轻提示 + 升级模型
python router.py 会议.m4a --lang 日文 --model medium
# 仅自检能力/provider 可用性
python router.py --check
# 机器可读输出
python router.py 录音.mp3 --json

# 视频文案提取（抽音轨 → 转录，阶段二）
python router.py 课程.mp4
# 仅文案、不抽讲解画面帧（D13）
python router.py 课程.mp4 --no-frames
# 视频同样支持语言/模型轻提示与批量
python router.py ./视频 --recursive --lang 日文

# OCR（阶段三，本地 rapidocr，完全离线）
python router.py 图片.png                  # 本地 OCR 取文字
python router.py 扫描件.pdf                # 图片型 PDF → 探测分流 + 本地 OCR
python router.py 扫描件.pdf --force-ocr    # 强制全部页 OCR（含原生文本层页也走 OCR）
python router.py 图片.png --confidence-threshold 0.9   # 调高置信度门控阈值
python router.py 图片.png --no-preprocess  # 关闭图像预处理链（归一化/去噪/deskew）

# 画面解读（阶段四，本地 VLM：ollama + Qwen2.5-VL，默认本地优先、零新依赖）
python router.py 截图.png                  # 本地 VLM 解读画面（默认 OCR 协同：先取文字再结合画面）
python router.py 截图.png --no-ocr-vision  # 关闭 OCR 协同（仅视觉语义）
python router.py 截图.png --vision-tier 0  # 手动指定档位（0=轻量3B/1=标准7B/2=高性能/3=旗舰32B，或 ollama 标签/中文名）
python router.py 课程.mp4 --vision         # 整视频场景切换关键帧采样 + 视觉描述（审阅 F，需本地 VLM）
# 注：本地 VLM 需自装 ollama 并拉取模型（如 `ollama pull qwen2.5vl:7b`）；未装则仅交付 OCR 文字并提示上云提质，不静默失败。

# 在线/加密视频文案提取（阶段五，本地优先、默认不上云）
python router.py "https://www.bilibili.com/video/BV1xx"     # yt-dlp 优先下载 → 抽音轨转录（副本仅留 tmp，处理后即删 D3）
python router.py "https://www.youtube.com/watch?v=xxxx" --lang 英文
# 加密/DRM 视频：无法下载时回退「浏览器播放中捕获」，将捕获产物经 --capture-path 传入（副本不留存）
python router.py "https://enc.example/v" --capture-path ./我的录制.mp4
# 注：yt-dlp 为可选依赖（pip install yt-dlp / brew install yt-dlp）；未装则仅支持浏览器捕获回退或清晰安装引导。
#      加密/DRM 视频属法律灰区，本技能仅显式提示风险、不规避版权保护（§4 边界 #2）。

# 账号/合集枚举（方案 B 增强）：抖音/小红书/B站 等账号 URL 自动枚举其下全部视频并逐条转写
python router.py "https://www.douyin.com/user/MXoxxxx"        # 自动识别账号页→枚举→批量转写
python router.py "https://space.bilibili.com/123/video"       # B站 个人空间视频
python router.py "https://www.xiaohongshu.com/user/profile/abc"  # 小红书 账号页
# cookie 登录态适配（抖音/小红书/B站 账号视频常需登录）：从本机浏览器注入登录态
python router.py "https://www.douyin.com/user/MXoxxxx" --cookies-from-browser chrome
python router.py "https://www.douyin.com/user/MXoxxxx" --cookies ./my_cookies.txt
# 强制将任意 URL 视为账号/合集页（覆盖其它平台，如 YouTube 频道、通用 playlist）
python router.py "https://www.youtube.com/@someone" --playlist
# 防风控限速（账号批量默认开启）：相邻视频按序处理 + 随机间隔（默认约 3 秒），降低封号/限流风险
python router.py "https://www.douyin.com/user/MXoxxxx" --enum-interval 5 --enum-limit 20
#   --enum-limit 20  → 单账号最多处理 20 条（超大账号分批，进一步防风控/控成本）
#   --no-throttle    → 关闭限速（仅当你明确拥有这些内容且接受平台风控风险时）
# 注意：账号视频批量处理仅建议用于你有权访问的内容，并遵守平台服务条款与版权（§4 边界 #2/#3）；
#       副本默认不保存（D3），枚举失败/空账号/需登录均显式提示、不静默失败。
#       ⚠️ 平台风控：批量抓取/转写他人账号视频可能触发频率限制甚至封号，请勿高频、请勿用于无权访问的内容。
```

## 四、架构要点（按需载入 + 可插拔 Provider）

- **按需载入（D8）**：主入口仅做类型识别+路由，仅命中类型才加载对应模块，未命中不预载 Whisper/VLM 等重型依赖。
- **可插拔 Provider（D15）**：各能力域底层引擎为可替换 Provider（本地内置/本地增强/云端/外部技能/连接器），默认本地优先，涉及上云/外部调用须经你确认；产出 `provider_meta` 透明回显「用了谁、是否上云」。
- **输出契约（D11/D16）**：原始识别仅存一份结构化备查副本（`.json`/`.md`，含 `raw_text`）；纠正版稿件为交付物（展示用），其 `text` 导出纯文本通道供 summarize/知识库/翻译消费；字幕 `.srt` 仍按需产出。
- **交付物范式（D16）**：识别结果（OCR 文字 / 转录稿 / 视觉解读）属半成品，仅保留一份结构化备查副本、不重复落盘；由智能体基于上下文 / 按需联网检索纠正为「纠正版稿件」，向用户展示与交付的须为纠正版稿件。联网检索仅在本地不足以判断正误时触发，走 D2/D15 确认门（外传前告知、敏感先脱敏、默认不上云）。
  本 CLI 已实现本地离线纠正：默认用本机 ollama 纯文本模型（默认 `qwen2.5:7b`，零新依赖）离线把识别结果完善为纠正版稿件，并落 `corrected` 元数据；可用 `--no-correct`（跳过）/ `--context <语境>`（消歧）/ `--correct-model <ollama标签>`（指定模型）控制；未配置模型则优雅跳过、不影响既有双通道产出。
- **能力声明（D9）**：本 SKILL.md 已暴露 `ocr`/`speech_transcription`/`video_transcript`/`image_understanding`/`video_online` 关键词，供 `summarize` 的 skill_bridge 自动发现；当前五者均已就绪（`ocr` 本地 rapidocr 离线、`image_understanding` 本地 VLM 走 ollama、`video_online` 走 yt-dlp 优先 / browser 回退，`router.py --check` 可见可用性，缺失则清晰引导安装）。
- **隐私闭环（§4）**：敏感预检贯穿到上云门前强制脱敏（已装 DESEN 则调用、未装则提示）；临时文件私有 tmp、处理后即清（审阅 G）。

## 五、安装与跨平台

参见 `AGENT_INSTALL.md`（Agent 安装指引）与 `install.py`/`install.sh`（一键建隔离 venv 并安装依赖）；升级用 `upgrade.py`（从 GitHub 拉最新、原子替换、失败回滚）。
运行要求：标准 CPython ≥3.10 且 <3.14（锁定 3.13）；音频解码用 PyAV（自带 ffmpeg，无需系统安装 ffmpeg）。

### 5.1 部署场景与用法（S1 便携版 / S2 套件 / S3 共存 / S4 仅组件）

| 场景 | 形态 | 用法 |
|------|------|------|
| S1 便携版（office-kit 组件） | 仅 CLI（`components/info-extract/`） | 技能触发词不生效；用 `office-kit.sh extract <参数>`（等价 `scripts/router.py`，`--type` 取值见 manifest） |
| S2 套件作 Agent Skill | office-kit 套件内 | 技能触发词生效，智能体按 frontmatter 触发 |
| S3 套件 + 部分组件共存 | 混合 | 两者皆可 |
| S4 仅组件（独立安装） | `~/.workbuddy/skills/info-extract` | 技能触发词生效；CLI 直接 `python scripts/router.py ...` |

> `--type` 取值：`ocr` / `vision` / `transcript` / `doc_extract` / `video` / `video_online` / `video_online_enum`。

### 5.2 协同技能缺失时的降级行为

未检出 `desensitization-sop`（DESEN）时**自动降级、不报错**：本地处理正常进行，仅在需要上云脱敏时由智能体层提示「未安装脱敏技能」；同理 browser 技能缺失时在线加密视频自动回退或提示。检测逻辑见 `scripts/skill_bridge.py`（`python scripts/router.py --check` 可见协同能力可用性）。

详细设计、模块契约、Provider 接口见 `references/reference.md`；决策记录见 `CHANGELOG.md`。
