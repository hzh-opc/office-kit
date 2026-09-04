---
name: desen-trigger
description: "本地脱敏 / 敏感信息检测统一触发壳（跨场景 DESEN 闸门）。当任务涉及下列任一情形时**必须先本地 desen scan 过闸，命中敏感先脱敏再用脱敏副本**：①送出本机的内容或文件（上云/云端处理/发邮件/发布/分享/提交/联网搜索/网页抓取/摘要上云/腾讯文档/tencent-doc/表格云端解析/sheetagent/云表格/翻译/多语/语音合成TTS/podcast/知识库沉淀）；②任务输入含敏感字段或高发载体（PII/身份证/银行账号/电话号码/车牌/发票号/企业抬头/申报表/财务/审计/底稿/报表/金额/密钥/Token/API Key/账号密码/密级/内幕信息/未公开重大信息，以及**表格/电子表格/xlsx/csv/数据统计/对账/账册**等个人敏感高发载体）；③识别内容拟外发（OCR/转录/画面解读的稿件外发）。触发词：脱敏/去标识/匿名化/PII/个人隐私/敏感信息/身份证/手机号/银行账号/银行卡/车牌/发票/申报/底稿/财务报表/内幕/密钥/Token/API Key/密级/上云/云端处理/发送/邮件/发布/分享/提交/联网/网页抓取/翻译/多语/TTS/sheetagent/腾讯表格/表格云解析/tencent-doc/**表格/电子表格/xlsx/csv/数据统计/对账/账册**。本技能是**触发转发壳**：权威实现是 office-kit 的 desen 组件（desensitization-sop），不复制组件本体、不双轨；命中后统一走 `office-kit.sh desen <子命令>` 或 `kit.py desen <子命令>`。旧独立技能 desensitization-sop 已并入 office-kit，勿再调用独立副本。"
origin: custom
version: "1.0.1"
agent_created: true
tags: [desen, 脱敏, 去标识, pii, 敏感, 上云, security, trigger, 触发壳]
---

# desen-trigger · 本地脱敏触发壳（L1，2026-09-04）

> **定位**：DESEN 从"office-kit 的附属能力"提升为"跨场景的上云/外发安全闸门"的**独立触发入口**。
> 本壳**不包含 desensitization-sop 组件本体**（避免与 office-kit 双副本漂移）；只负责在任意任务（非仅办公抽取）中准确触发脱敏检查，并把动作转发到权威实现。

## 为什么存在
desensitization-sop（desen）并入 office-kit 后失去独立顶层入口，触发它须命中 office-kit 元技能 description（载体抽取向）。凡"非载体抽取"的敏感动作（纯对话、代码、表格云解析、发邮件、联网搜索、发布），Agent 几乎不会联想 office-kit → desen 静默失效。本壳把"脱敏/上云/财务敏感"从办公抽取词里**拆出单列**，让 desen 可被任何场景独立命中。

## 触发判据（命中任一即走 desen）
1. **外发判据**：要把本地内容送出本机（显式或隐性）——上云 / 云端处理 / 邮件 / 发布 / 分享 / 提交 / 联网补全 / 网页抓取 / 摘要上云 / 腾讯文档 / **表格云端解析（sheetagent / 云表格）**。
2. **敏感输入判据**：任务输入含敏感字段（PII / 身份证 / 银行账号 / 电话 / 车牌 / 发票号 / 企业抬头 / 申报表 / 财务 / 审计 / 底稿 / 报表 / 金额 / 密钥 / Token / API Key / 账号密码 / 密级 / 内幕或未公开信息）。
3. **识别稿外发判据**：OCR / 转录 / 画面解读产物拟外发。

## 标准动作（参考 desensitization-sop 闸门决策表）
- **步骤零（输入检测闸门，本地离线）**：
  `office-kit.sh desen scan <文件/目录> --recursive`
  （非文件输入——联网搜索/发邮件/纯对话的文本片段——用 `desen scan -` 从标准输入读取，或先落临时 `.txt` 再 scan。）
- **命中判定铁律（勿凭退出码）**：`desen scan` **命中敏感后退出码仍为 0**，且干净时也返回 0。
  判定必须**解析 stdout**，两者不可混淆：
  - stdout 含 `汇总：`（如 `汇总： {"phone": 1, "id_card": 1}`）→ **已命中敏感**，须先脱敏；
  - stdout 含 `未发现已知敏感标识符。` → 干净通过；
  - 两者皆无（含 Traceback）→ 扫描异常，按 **fail-safe 保守阻断**，不得放行。
- 命中敏感 → 先本地脱敏：
  `office-kit.sh desen run <文件/目录> --workspace <工作区>`
  用 `03_脱敏副本/` 继续任务，映射表留本地 `04_映射表_保密/`，**绝不随副本上传**。
- 未命中 → 直接执行，零额外负担。
- **密级/内部标记（desen v2.11.1 拆两类识别）**：
  - **`state_secret`（法定国家秘密等级：机密/绝密/秘密）**——命中即触发**显式确认提醒**（desen scan/run 会在 stderr 红字提示「一般企业/单位依法接触不到国家秘密载体，请确认来源合法性与载体性质」）。**Agent 收到该提示后必须 AskUserQuestion 向用户显式确认**，不得静默把涉密标记当普通字段脱敏放行上云。确认属国家秘密载体 → 严禁上云/联网，按保密规定线下处置；确认仅是内部文件误用机密字眼 → 按内部资料处理。
  - **`internal_mark`（企业内部标签：内部资料/内部文件/内参）**——非国家秘密，正常脱敏为 `[内部]`，不触发国家秘密确认。
  - **纯语义的「内幕信息 / 未公开重大信息」无固定格式、无法正则识别**，desen scan 会返回「未发现」——此类须由 Agent 按下方「财务/审计/投研上云前自查清单」人工把关，不得误以为「未发现」即「无敏感」。
- 财务 / 审计 / 投研 / 代码（密钥）场景按 desensitization-sop「上云前自查清单」逐项核对，禁止"一键脱敏即上云"。

## 权威实现与入口（唯一）
- 权威副本：`components/desensitization-sop/`（office-kit 仓库，当前 v2.11.1）。
- 调用入口（二选一，等价；`office-kit.sh` / `kit.py` 位于 office-kit 仓库根目录）：
  - `office-kit.sh desen <子命令> ...`
  - `python3 kit.py desen <子命令> ...`
- **勿调用**旧独立副本 `~/.workbuddy/skills/desensitization-sop/`（若存在仅 S4 场景生效，套件已装时以 office-kit 为权威）。
- 子命令：scan / preprocess / run / status / audit / decrypt / restore / guide（详见 office-kit）。

## 与本会话其他约定
- office-kit 外发门禁（2026-09-04 收口版）：外发登记唯一真相源 = 组件 `manifest.json` 的 `commands[].external`（`external_kind` 区分显式/隐性）。**隐性外发**（如 `extract` 识别稿外发）命中敏感 → `kit.py` 硬阻断（exit≠0），须先 `desen run` 再重试；**显式外发**（如 `tencent-doc`）命中敏感 → 仅提示、放行执行。`summarize` 脚本为纯本地（零上云），不登记为外发——其翻译/TTS/联网补全等隐性外发由 SKILL.md 层智能体动作 + `podcast.py --tts` 组件内确认闸口负责。
- **表格盲区**（sheetagent 云解析不经 office-kit 门禁）：涉敏表格送云前必须由本壳触发 `desen scan` 前置。
- 逃生口 `OFFICE_KIT_SKIP_EXTERNAL_GATE=1`（风险自负）仅当用户显式要求时才可用。

## 部署说明
本目录为 office-kit 仓库随带的**触发壳资产**，供跨场景 DESEN 闸门复用。安装方式（可选）：将本目录整体 copy 至用户级技能目录 `~/.workbuddy/skills/desen-trigger/`（实目录 copy，非 symlink）。不安装不影响 office-kit 套件内门禁（`kit.py` 已内建外发门禁）；安装后可让"非办公场景"的敏感动作也能被准确触发。
