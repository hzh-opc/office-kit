# info-extract · 信息抽取技能

跨智能体（WorkBuddy / Claude / Codex / OpenClaw）、跨平台（Windows / macOS / Linux）的**本地优先**信息抽取技能，覆盖 OCR、音频转录、视频文案、画面解读、在线/加密视频五大能力域。

> **核心原则**：本地优先 · 默认不上云 · 机器结果须经你确认。

## 能力域与阶段

| 阶段 | 能力域 | 状态 |
|------|--------|------|
| 一 | 音频转录（speech_transcription） | ✅ 已实现 |
| 二 | 视频文案提取（video_transcript） | ✅ 已实现 |
| 三 | OCR（ocr） | ✅ 已实现 |
| 四 | 画面解读（image_understanding） | ✅ 已实现 |
| 五 | 在线/加密视频（video_online） | ✅ 已实现 |
| 五增强 | 账号/合集枚举 + cookie 适配（抖音/小红书/B站） | ✅ 已实现 |
| 六 | 交付物范式（D16 纠正版稿件） | ✅ 已实现 |

## 快速开始

```bash
# 1) 安装（建隔离 venv + 依赖）
python install.py            # 或 ./install.sh

# 2) 转录音频
python scripts/router.py 录音.mp3
python scripts/router.py ./音频目录 --recursive --out ./结果
```

详见 `SKILL.md`、`AGENT_INSTALL.md`、`CHANGELOG.md`、`references/reference.md`。
