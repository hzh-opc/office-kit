# office-kit · Install Guide for AI Agents

You are an AI agent setting up the `office-kit` skill for the user. **Done = `./bootstrap.sh` exits 0** (venv ready, components OK, skills/hooks distributed, plugin registered). **Never use `sudo`**; you cannot push to GitHub or pick the user's AI tool for them — Step 5 is the user's job.

> **适用对象（Who it's for）**：本元技能面向**个人**与**企业**使用——含政府部门、事业单位、对数据安全有特别要求的企业等；此类组织使用时**须遵循其适用的法律法规与内部数据安全管理规定**。
>
> 套件含 `desensitization-sop` 组件（本地优先、数据不出本机），全过程可追溯、可审计、可复核。

## 1. Get the skill

The skill lives at `https://github.com/hzh-opc/office-kit`. Prefer a fresh clone; fall back to a zip download if `git` is unavailable.

**macOS / Linux:**

```bash
git clone --depth 1 https://github.com/hzh-opc/office-kit /tmp/office-kit
cd /tmp/office-kit
```

**Windows (PowerShell):**

```powershell
git clone --depth 1 https://github.com/hzh-opc/office-kit $env:TEMP\office-kit
cd $env:TEMP\office-kit
```

If `git` is not available, download the zip instead:

```bash
# macOS / Linux
curl -fsSL https://github.com/hzh-opc/office-kit/archive/refs/heads/main.zip -o /tmp/ok.zip
unzip /tmp/ok.zip -d /tmp && cd /tmp/office-kit-main
```

## 2. Run the installer

```bash
# macOS / Linux
./bootstrap.sh
# 或按需：
./bootstrap.sh --force-venv            # 强制重建 .venv
./bootstrap.sh --no-enable-desen-stop  # 只分发钩子，不改 settings.json
./bootstrap.sh --inject-soul-rules     # 启用第 7 步：常驻铁律合并到 ~/.workbuddy/SOUL.md

# Windows (PowerShell)
.\bootstrap.ps1
.\bootstrap.ps1 -ForceVenv
.\bootstrap.ps1 -InjectSoulRules
```

`bootstrap.sh` will, automatically and idempotently, do **七步**（最后一步可选）：

1. create `.venv` (`uv venv --python 3.13`，已存在则跳过；`--force-venv` 强删重建)；
2. repair components (online pull via `kit.py repair` if any are missing/corrupted);
3. merge `components/*/requirements.txt` and install dependencies via `uv pip install` (PyPI 国内源 default);
4. validate four components + scaffold `workbench/` (inbox/extract/desen/summary/render/archive/logs);
5. **distribute user-level assets** (idempotent copy, not symlink):
   - `skills/office-kit/` + `skills/desen-trigger/` → `~/.workbuddy/skills/`
   - `hooks/desen-stop/` → `~/.workbuddy/hooks/`
   - auto-generate `~/.workbuddy/skills-registry.md` via `kit.py register`（幂等；`<!-- 人工备注 -->` 区块保留；新机器无须手工按 6 字段登记）;
6. **register local marketplace + CLI 真启用 desen-stop** (three sub-steps required for the plugin to actually execute):
   ① build marketplace under `~/.workbuddy/plugins/marketplaces/<市场>/` and write `"desen-stop@<市场>": true` into `~/.workbuddy/settings.json.enabledPlugins` (idempotent + auto backup);
   ② run CLI `plugin marketplace add` + `plugin install` (must use `env -i` clean env; detail `hooks/desen-stop/平台启用指引.md`);
   ③ double-validate: `installed_plugins.json` contains `desen-stop@<市场>` AND `plugins/cache/<市场>/desen-stop/<version>/` exists.
7. **(optional, behind `--inject-soul-rules`)** inject the resident "input-detection gate" rule into `~/.workbuddy/SOUL.md`, via `components/desensitization-sop/install.py --memory-file ~/.workbuddy/SOUL.md --skip-venv --skip-tests` (reuses desen's idempotent + cross-source dedup mechanism; default OFF so this script never silently rewrites the user's identity file).

## 3. Verify

```bash
./bootstrap.sh                # idempotent; exits 0 when everything is ready; 收尾自动跑 verify
python kit.py verify          # 统一部署验收闸门：组件 + 分发 + desen-stop 平台生效四校验 + registry + SOUL 铁律（警告级）
python kit.py doctor          # 环境 / 组件自检（venv、版本一致性、.env 状态、enabledPlugins）
ls ~/.workbuddy/plugins/installed_plugins.json | xargs -I{} grep -c "desen-stop" {}   # 应 ≥1
ls ~/.workbuddy/plugins/cache/hzh-local/desen-stop/                                    # 应有执行副本
ls ~/.workbuddy/skills/                                                               # 应含 office-kit/ + desen-trigger/
```

> **机器级环境（可选，与技能安装解耦）**：新机器如需复刻「uv + 国内源 uv.toml 5 源 + 默认环境 `envs/default` + Python 默认环境常驻铁律」，运行 `deploy/machine_init.sh`（macOS/Linux）或 `deploy/machine_init.ps1`（Windows，未实机验证）——不依赖部署提示词，单独安装本套件时无须此步。

Each failure prints a `hint` — follow it and re-run. A successful install ends with exit code `0` and the closing summary lines. If you only want to re-distribute assets without touching the plugin registration, pass `--no-enable-desen-stop`.

> **`.env` / 大模型配置**：复制 `config/.env.example` 到 `config/.env`，按需填写 `OPENAI_API_KEY` / `AZURE_SPEECH_KEY` / `OLLAMA_HOST` / `INFO_EXTRACT_VISION_TIER` 等；`kit.py` 启动时自动加载（仅补未设置变量、不覆盖）。`config/.env` 已被 `.gitignore` 排除，不进仓库、不进对话。

## 4. (user's job) Confirm the AI tool loads the skill

If the target AI tool was already running, tell the user to **restart it** (or reopen the session) so `office-kit` + `desen-trigger` are picked up. The framework seeds the skills directory under `~/.workbuddy/skills/` at install time — re-running the install is always safe (idempotent copy).

Then remind them of the red lines:

- 套件内的外发门禁（`kit.py` 按 `manifest.commands[].external`）覆盖"办公抽取"链路；
- **非办公场景**的敏感动作（云端生成 ImageGen/VideoGen、agent-mail/send_mail、表格云解析 sheetagent、联网搜索等）由 `skills/desen-trigger/` 触发壳独立命中，转发到 `components/desensitization-sop` 权威实现；
- 敏感文件**保留本地**，仅脱敏副本可上云，映射表（`.desensitize_keys`）**不出本机**；
- 自动化检测并非 100%，上云前**人工复核**仍然必要。

## 5. Upgrading (manual, safe zero-downtime)

The套件 ships `kit.py check / upgrade / repair` (online; against public `hzh-opc/office-kit@main`). **Upgrades are manual only** — never auto-upgrade on load. When the user explicitly asks to upgrade/update, run:

```bash
python kit.py check                  # 检测：本地完整性 + 远程新版本（只读）
python kit.py upgrade                # 升级全部组件到远程最新版（要求交互确认；--yes 跳过）
python kit.py upgrade --force        # 即使本地已最新也强制重同步
python kit.py repair                 # 修复损坏/缺失组件（默认：本地 ∪ 远程清单）
```

Components can also be upgraded independently (`python kit.py upgrade <component>`). After any upgrade, re-run `./bootstrap.sh` so the new dependency set is installed and the skills/hooks distribution is refreshed.

## 6. Troubleshooting

| 现象 | 看哪里 |
|---|---|
| `bootstrap.sh` exit 1，`uv` 不在 PATH | 安装 [uv](https://docs.astral.sh/uv/) 后重跑 |
| 组件未生效 | `python kit.py doctor` → 看版本一致性与 .env 状态 |
| desen-stop hook 没触发 | `hooks/desen-stop/平台启用指引.md` + `troubleshooting/plugin-enable.md` |
| 组件依赖装不上 | 检查 `OFFICE_KIT_PYPI_MIRROR` / 网络代理 |
| `installed_plugins.json` 没条目 | 重跑 `bootstrap.sh`（默认会重试第 6 步三子步）；或手动 `codebuddy plugin install desen-stop@hzh-local` |

## 7. Uninstall / partial rollback

```bash
# 仅撤销插件启用（保留文件分发）：
./bootstrap.sh --no-enable-desen-stop    # 这一版只"补齐"——真正撤销可用 codebuddy plugin uninstall desen-stop@hzh-local

# 撤销技能与钩子分发：
rm -rf ~/.workbuddy/skills/office-kit ~/.workbuddy/skills/desen-trigger
rm -rf ~/.workbuddy/hooks/desen-stop

# 撤销 venv：
rm -rf .venv
```
