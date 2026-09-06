# desen-stop · L3 Stop Hook（上云无脱敏留痕事后兜底）

> 建立：2026-09-04 · 对应机制建议 L3（Stop hook 事后兜底，覆盖 sheetagent 等不经 office-kit L4 门禁的插件通道）
> 形态：**标准 WorkBuddy Hook 插件包**（`.codebuddy-plugin/plugin.json` 声明 hooks，对齐 security-scan / sheetagent 同款契约）
> 模式：**warn（默认，非阻断）**——命中仅提示、允许停止；设 `DESEN_STOP_HOOK_MODE=block` 才阻止停止

## 目的
sheetagent（腾讯表格云解析，远程 `https://docs.qq.com/api/v6/sheet/mcp`）、邮件、发布等**非 office-kit 通道**，
不经 kit.py 的 L4 代码门禁。本 Stop hook 在 Agent **每次停止（会话/单轮结束）**时扫描本轮 transcript：
若检出疑似上云/外发动作、却无任何 desen 脱敏留痕，则提示（warn，默认）/ 阻止停止（block），由 Agent 回补 desen 审计。

## 插件包结构（插件根 = 本目录）
```
desen-stop/
├── .codebuddy-plugin/plugin.json   # 插件 manifest，声明 "hooks": "hooks/hooks.json"
├── hooks/hooks.json                # Stop hook 注册（command 指向 scripts/desen_stop_hook.py，${CODEBUDDY_PLUGIN_ROOT}）
├── scripts/desen_stop_hook.py      # 检测脚本（纯标准库、离线、只读 transcript 尾部 ≤2MB、零外发）
└── README.md
```

## 行为（由 env 控制）
| 变量 | 取值 | 效果 |
|---|---|---|
| `DESEN_STOP_HOOK_MODE` | `warn`（默认） | 命中仅输出 JSON 提示，允许停止（exit 0） |
| `DESEN_STOP_HOOK_MODE` | `block` | 命中输出 `shouldStop:false` + 阻止停止（exit 2，reason 传 Agent） |
| `DESEN_STOP_HOOK_OFF` | `1` | 完全跳过本 hook |

> 注：旧版曾支持 `DESEN_STOP_HOOK_NOISE`（低危提示开关），其对应脚本内变量属死代码、已于 2026-09-06
> 死代码清理时删除——现在行为统一为「有外发动作即提示」，不再区分低危/高危提示档。

## 本机自测（已验证通过）
```bash
cd ~/office-kit/hooks/desen-stop
echo '{"transcript_path":"/tmp/含sheetagent无desen.txt"}' | python3 scripts/desen_stop_hook.py  # warn: exit 0 + JSON提示
echo '{"transcript_path":"/tmp/含sheetagent无desen.txt"}' | DESEN_STOP_HOOK_MODE=block python3 scripts/desen_stop_hook.py  # block: exit 2
# 含 desen 留痕的 transcript → exit 0（放行）
```

## 启用（让 WorkBuddy 每次会话停止时执行）
> Stop hook 运行时契约：stdin 注入 JSON（含 transcript_path/session_id/cwd），stdout JSON 控停，
> exit 0 允许 / exit 2 阻止（同 security-scan/git_commit_detector 范式）。WorkBuddy 按「插件目录 →
> `.codebuddy-plugin/plugin.json` 的 hooks 字段 → hooks/hooks.json」加载。

1. **经插件界面导入/启用（推荐，最可靠）**：把本 `desen-stop/` 目录作为本地插件加入 WorkBuddy 插件管理页，
   启用后其 Stop hook 即随会话停止执行（warn 默认，非阻断，低风险）。
2. **随现有已启用 Hook 插件挂载**：将本 `hooks.json` 的 Stop 片段并入你已启用且被加载的插件 hooks.json
   （如 security-scan / 任一已启用 Hook 插件），把 `command` 改指本机绝对路径 `scripts/desen_stop_hook.py`。
3. **全局/项目级用户 hooks**：若你的 WorkBuddy 版本暴露用户级 hooks 配置入口（`~/.workbuddy/` 下或 settings），
   将该 Stop 片段并入即可跨项目生效。

## 落地状态
- ✅ 脚本 + hooks.json + plugin.json + 自测完成（warn 默认）。
- ✅ 已选 **warn 模式**（用户 2026-09-04 拍板），非阻断，仅会话结束提示。
- ✅ 2026-09-06 同步 kit.py v2.2「默认阻断 + 显式确认放行」：`_DESEN_HINTS` 增补 `confirm-raw`/`confirm_raw`，
  使「用户 `--confirm-raw` 确认外发（前置 `desen audit-log` 留痕）」不再误判为漏检。
- 🟡 **全局自动执行需经上述任一启用路径**（插件页导入 / 并入已启用 hook 载体 / 用户级 hooks 入口）；
  因 WorkBuddy 未公开用户级全局 hooks.json 的确切文件路径，本机能否在无 GUI 下直接扫描到此插件
  取决于运行时——若经插件页启用后未触发，请核对插件发现根目录与 hooks.json 语法。

## 风险与注意
- **误报**：关键词近似检测（如 `read_table`）可能对"仅本地只读未外发"也提示；可用
  `DESEN_STOP_HOOK_OFF=1` 整体跳过，或按实际动作收紧脚本内 `_EXTERNAL_HINTS`。
- **安全**：脚本仅读 transcript 尾部 ≤2MB，不写盘、不联网、不外发，符合"只读审计"定位。
- **逃生口**：`DESEN_STOP_HOOK_OFF=1` 完全跳过（对齐 security-scan Skip 档）。
- **数据佐证**：sheetagent MCP env 含 `SHEET_REMOTE_MCP_URL=https://docs.qq.com/api/v6/sheet/mcp`
  与 `SHEET_API_MODE=local`，印证"本地 xlsx 复杂解析存在 docs.qq.com 云上传路径"——正是本 hook 兜底对象。
