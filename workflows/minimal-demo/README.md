# minimal-demo · 工作流机制验证示例

> 用途：验证 office-kit「插件/预设」机制（方案 A）端到端可用。**不依赖任何模型**，纯证明编排层。
> 对应机制设计：`规划文档/插件预设机制可行性分析.md`。

## 它验证了什么

| 机制能力 | 本示例如何证明 |
|---|---|
| 工作流发现 | `kit.py workflow list` 扫描 `workflows/*/workflow.json` 列出本工作流 |
| 契约加载 | 读取 `workflow.json`（`trigger`/`params`/`requires`/`state`/`steps`） |
| 步骤分发 · kit 内建 | 步骤 `env-check` → `uses: doctor`（真实自检 venv+组件） |
| 步骤分发 · 组件命令 | 步骤 `probe-extract` → `uses: "extract --help"`（解析到 info-extract 入口 + venv 注入） |
| 复用发现机制 | 步骤 `list-caps` → `uses: list` |
| 人工确认门 | 步骤 `confirm-plan` → `checkpoint: confirm`（交互确认；`--yes` 自动通过） |
| 工作记录链 | 每步落 `pipeline_state.json`（started/finished/status/writes/confirm） |
| 派生产物跟踪 | 步骤 `write-report` → `uses: {"shell": ...}` 写 `report.json`，`{workspace}` 占位符替换 |
| 断点续跑 | `kit.py workflow run <name> --resume` 跳过已完成步骤 |
| 单步执行 | `kit.py workflow run <name> --step N` 仅跑第 N 步 |
| 干跑 | `--dry-run` 仅打印计划，不写 `completed_at` |

## 运行

```bash
cd ~/Repositories/office-kit
python kit.py workflow list                       # 列出工作流
python kit.py workflow run minimal-demo --dry-run --workspace /tmp/d
python kit.py workflow run minimal-demo --yes     --workspace /tmp/d   # 真实跑（--yes 过确认门）
python kit.py workflow run minimal-demo --resume  --yes --workspace /tmp/d   # 断点续跑
python kit.py workflow run minimal-demo --step 3  --yes --workspace /tmp/d   # 单步
```

## 真实工作流如何接入（对照 `视频内容交付工作流`）

本示例的每一步 `uses` 改成指向真实组件能力即可，runner 不变：

```json
{ "id": "transcribe", "uses": "extract --type transcript <源>",
  "writes": ["<WORK_REC>/<节>/transcript_meta.json"] },
{ "id": "frames", "uses": "extract --type vision <源>",
  "writes": ["<WORK_REC>/<节>/frames_manifest.json"] },
{ "id": "doc", "uses": "summarize <文本>",
  "checkpoint": "confirm", "writes": ["<节>_修正版.md"] },
{ "id": "slice", "uses": {"shell": "<MEDIA_PY> -m ... 切分"},
  "when": "granularity!=none", "writes": ["cut_plan.json"] }
```

要点：
- `uses` 三态：`"组件命令 ..."` / `{"kit": "..."}` / `{"shell": "..."}`（media 环境走 shell）。
- `when` 支持极简 `k==v` / `k!=v` / 单 token 真值（参数驱动条件粒度，如按目录/转录/产品）。
- `checkpoint: confirm` 即视频工作流的「待确认.md」暂停点；`--yes` 在非交互（Agent）场景自动通过。
- `state.schema` 把视频工作流散落的 `*_manifest.json` 固化为契约，runner 自动维护 `pipeline_state.json`。
- `requires` 声明依赖能力；info-extract 的 `live`/`capture`（直播/设备）已实现于 `~/Repositories/info-extract`，
  同步到 `components/info-extract` 后即可在 `uses` 中直接调用 `extract --live` / `extract --device`。
