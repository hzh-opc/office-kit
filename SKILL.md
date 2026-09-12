---
name: office-kit
description: "【薄指针 / thin pointer】office-kit 元技能的正文、触发词与外发铁律，唯一真相源是 skills/office-kit/SKILL.md（bootstrap 第 5a 步分发到 ~/.workbuddy/skills/office-kit/，即平台实际加载的入口）。读取本技能时一律以该文件为准；本根文件不承载铁律正文与独立版本号。"
agent_created: true
---

# office-kit · 仓库根薄指针（thin pointer）

> ⚠ **本文件不是技能正文**，只是仓库根目录的导航指针，防止「双源漂移」。

office-kit 元技能的唯一真相源：

| 项 | 位置 |
|---|---|
| 技能正文（触发词 / 路由定位 / 编排说明 / **外发必扫 DESEN 铁律** / 展示规范） | [`skills/office-kit/SKILL.md`](skills/office-kit/SKILL.md) |
| 套件版本号 | [`VERSION`](VERSION)——与 `skills/office-kit/SKILL.md` 的 `version` 保持一致，`kit.py doctor` / `verify` 会校验一致性 |
| 安装 / 部署 | [`AGENT_INSTALL.md`](AGENT_INSTALL.md) / [`README.md`](README.md)；`./bootstrap.sh` 第 5a 步把 `skills/office-kit/` 复制到 `~/.workbuddy/skills/office-kit/` |
| 分发后的运行入口 | `~/office-kit/office-kit.sh <command>`（Windows：`office-kit.ps1`）→ 委托 `kit.py` |

**为何降级为指针（2026-09-12 反馈 D1）**：此前根 `SKILL.md` 与 `skills/office-kit/SKILL.md` 长期双源，出现「版本号更高（0.2.2）而铁律口径更旧（2026-09-04 收口版）」的倒挂——根文件写「显式外发命中敏感 → 仅提示、放行执行」，而 `kit.py` 的实际实现是「显式 / 隐性一律**先阻断** + 敏感信息确认卡，用户 `--confirm-raw`（或 `OFFICE_KIT_CONFIRM_RAW=1`）确认并 `desen audit-log --decision raw` 留痕后才放行」。任何以根文件为准的判断都会得到**更宽松**的外发口径，与现网行为不符。

自 v0.2.3 起：根文件不再承载铁律正文、也不再有独立版本号——从结构上消除双源漂移；活跃文件 `skills/office-kit/SKILL.md` 的 `version` 与套件 `VERSION` 同步，并由 `kit.py doctor` / `verify` 把关。
