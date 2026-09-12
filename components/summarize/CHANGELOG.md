# 更新日志（Changelog）

本文件按时间倒序记录重大变更。日常细节以 Git 提交为准。

## v1.1.0 · 2026-09-12（TTS 外发门禁接入真实 desen scan · 独立建版）

本次为**回灌版本**：该加固先前只存在于 office-kit 套件副本，未同步回独立仓库（见 2026-09-11 全面检查报告 P0-2）。本次回灌、独立建版，并新增 `VERSION` 文件。

- **安全：`podcast.py --tts` 的隐性外发门禁统一接入真实 `desen scan`**（`scripts/skill_bridge.py`）。在把讲稿全文送出本机（第三方语音合成）之前：
  1. 先跑 office-kit 的 `desensitization-sop` 扫描待外发文本；
  2. **命中敏感 → 先阻断** + 敏感确认卡，须 `OFFICE_KIT_CONFIRM_RAW=1`（与 `kit.py --confirm-raw` 同语义；`OFFICE_KIT_EXTERNAL_CONFIRM=allow` 保留为等价别名）显式确认后才放行，并提示先 `desen audit-log --decision raw` 留痕；或改用脱敏副本外发；
  3. **无敏感 → 静默放行**（零打扰）；
  4. 找不到 desen 组件 / scan 异常 → 退化为本技能自带的本地 PII 预检（**仅提示增强**，不改变「任何隐性外发都需用户确认」的阻断决策）。
- **新增 `VERSION` 文件**（值 `1.1.0`），与 `SKILL.md` frontmatter、套件 `manifest.json` 三者一致。
- **`requirements.txt`** 未变（本组件纯标准库 + 可选 `jieba`）。

