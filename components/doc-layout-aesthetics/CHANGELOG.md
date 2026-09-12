# 更新日志（Changelog）

本文件按时间倒序记录重大变更。日常细节以 Git 提交为准。

## v1.0.1 · 2026-09-12（shell 崩溃修复 + venv 解析补齐 + 独立建版）

- **fix(scripts)：裸变量 → `${VAR}`**（`install.sh`、`fonts/install_fonts.sh`、`scripts/upgrade_skill.sh` 共 5 处）。变量紧邻多字节字符（`（ ： ）` 等）时，macOS 自带 bash 3.2.57 会把后续多字节字节序列并入变量名，在 `set -u` 下直接 `unbound variable` 退出（已实测复现 exit 127）。加花括号后不再需要历史上 `LC_ALL=C` 的规避手段。
- **fix(venv)：`scripts/_venv.py` 补齐「复用 office-kit 生产 venv」档位**——`OFFICE_KIT_ROOT/.venv` → `~/office-kit/.venv`，与套件 `kit.py` 的解析顺序一致；开发副本 / 测试工具不再自建 `.venv`（用户 2026-09-11 明确）。
- **新增 `VERSION` 文件**（值 `1.0.1`），与 `SKILL.md` frontmatter、套件 `manifest.json` 三者一致。

