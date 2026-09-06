# video-to-content-pack —— 视频转内容包工作流（契约）

可执行契约：`workflow.json`（由 `kit.py workflow` 加载）。
人类可读蓝本：**不在本仓库**——位于用户工作区 `~/WorkBuddy/Skill-Dev/office-kit/规划文档/视频转内容包工作流.md`（唯一权威副本，隐私隔离，不随仓库分发；同 `DEVELOPMENT.md` 先例）。

## 契约速查

| 项 | 值 |
|---|---|
| 版本 | 0.1.0 |
| 步骤数 | 21（其中 6 个来源摄取步按 `when` 互斥） |
| requires | info-extract 组件 + office-kit venv + media 环境 |
| optional | `live` / `capture`（原生摄取已同步组件；`*_fallback` 保留为录制完整性兜底） |
| 关键 params | `workspace`（必填）/ `source` / `source_uri` / `section` / `deliverable_types` / `granularity` / `copywriting` / `ffmpeg_bin` |

## 执行模型（Agent + runner 协作）

本工作流与 `minimal-demo` 的关键差异：**含创作类步骤**（写逐字稿/交付文档/文案/裁切计划）。

- `uses` 步骤（kit / 组件 / shell）：runner 直接分发执行——`preflight`、`prepare_dirs`、6 个摄取步、`transcribe`。
- `"executor": "agent"` 步骤：runner **标记 `await_agent` 并暂停**，打印醒目提示（含蓝本对应章节 + `step-done` 回填指引）。实际执行由 Agent 按蓝本对应章节完成（画面态压缩、抽帧 OCR、去边、逐字稿修正、交付文档、目录/产品确认、裁切、导出、校验），完成后 `kit workflow step-done <name> <step_id>` 回填该步为 done，再 `--resume` 续跑。这样设计的原因：这些步骤是「读上游记录 → 生成内容 → 人工确认」的闭环，本质是 Agent 创作而非 CLI 调用；强行脚本化会重造蓝本中已沉淀的实践。
- 每步 `writes` 与 `state_schema.records` 把蓝本 §0.4 工作记录链固化为契约（owner + consumers）。

## 降级矩阵（live/capture）

**原生路径已生效**（2026-09-03 已把独立仓 live/capture 同步进 `components/info-extract`，manifest 登记 `live`/`capture` 能力；部署副本 `~/office-kit` 同步）：

| params.source | 路径 | 前提 |
|---|---|---|
| `file` | cp 归一化 → `transcribe` | 无 |
| `online` | `extract`（yt-dlp） | yt-dlp 可选依赖 |
| `live` | `extract --live`（边录边转 + 增强 A–E） | ✅ 已可用 |
| `live_fallback` | media ffmpeg 先录制 → `transcribe` | 录制完整性兜底，保留 |
| `device` | `extract --device` | ✅ 已可用 |
| `device_fallback` | Agent 按平台组装 ffmpeg 采集命令 | 兜底，保留 |

> ⚠ **upgrade 保护**：源仓 7 个提交尚未推送远程——推送前对 info-extract 执行 `kit upgrade` 会从 origin/main 拉旧版覆盖本同步（manifest sync.warning 已记录）。推送后恢复常规 upgrade 流程，`*_fallback` 继续作为边转失败时的兜底（蓝本 §10 机制二原则）。

## 运行

```sh
./kit workflow list
# 干跑（验证契约与 when 门控）
./kit workflow run video-to-content-pack --dry-run --workspace /tmp/vcd
# 单节交付（文件来源，默认粒度 none）
./kit workflow run video-to-content-pack --yes \
  --workspace ~/内容工作区 --param source=file --param source_uri=~/录屏.mp4 --param section=第1节
# 电商场景（按产品切片 + 文案）
./kit workflow run video-to-content-pack --yes \
  --workspace ~/内容工作区 --param source=online --param source_uri=<回放URL> \
  --param granularity=product --param copywriting=on
```

断点续跑：`--resume`（跳过已完成步）；确认门暂停后同样用 `--resume` 继续。

## 验证记录（2026-09-03）

- `workflow list` 正常识别（21 步）。
- `--dry-run`：默认 `source=file / granularity=none / copywriting=off` 下，live/device/copywriting/catalog/product/切片类步骤全部按 `when` 正确跳过，自动步打印 dry-run 计划。
- 真实跑（`--step` 逐段）：`preflight`（kit doctor）与 `prepare_dirs`（目录骨架）真实执行成功；`ingest_file` 用哑文件验证 cp 归一化成功。
- 全量真实执行需真实视频内容，属内容交付场景而非机制验证范围。

## 踩坑 / 约定

- `uses` 写组件命令用字符串形式 `"extract ..."`（首 token 命中注册命令即按组件分发）；shell 必须用 `{"shell": "..."}` 显式形式。
- `when` 条件支持 `k==v` / `k!=v` / `k in a,b,c` / `k not in a,b,c` / 单 token 真值；**布尔开关用 `on/off` 字符串 + `==` 比较**（单 token `"off"` 也是真值，勿用）。
- `executor: agent` 步：runner 暂停于 `await_agent`，Agent 完成后 `kit workflow step-done <name> <step_id>` 回填再 `--resume`；`--dry-run` 下 agent 步只打印计划不暂停。
- 确认门（`checkpoint: confirm`）在 CLI 交互挂起等待 `input()`；Agent 驱动时传 `--yes` 由 Agent 自行在确认点向用户求证（蓝本「待确认门」模式的契约化）。
- `*_fallback` 步的 ffmpeg 探测链：`ffmpeg_bin` > `media_py`（默认 `~/.workbuddy/binaries/python/envs/media/bin/python`）的 imageio_ffmpeg > 系统 `ffmpeg`；`media_py` 可经 `--param media_py=...` 覆盖。
