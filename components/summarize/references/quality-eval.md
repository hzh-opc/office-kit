# summarize 技能 · 摘要质量评估方法（references/quality-eval.md）

用于「形成适当的摘要质量评估方法，促进技能本身不断完善」。本地引擎每次运行（`--eval`）即输出评分；
云端结果对比后亦用本节指标量化差异。

## 一、核心指标

| 指标 | 定义 | 含义 |
|---|---|---|
| 压缩比 `compression_ratio` | `1 - len(摘要)/len(原文)` | 信息浓缩程度，越高越省时 |
| 句数缩减 `sentence_reduction` | `1 - 选中句数/总句数` | 冗余去除比例 |
| 关键词覆盖 `keyword_coverage` | 摘要出现的关键词数 / 提取关键词总数 | 要点保留度 |
| 平均句长 `avg_sentence_len` | 摘要句平均字数 | 可读性代理指标，25~70 为佳 |
| 综合评分 `score` | 加权 `0.35*压缩 + 0.30*覆盖 + 0.20*句减 + 0.15*可读` | 0~100，越高越好 |

## 二、综合评分权重（可调）

```
score = 100 * (0.35·compression + 0.30·keyword_coverage
             + 0.20·sentence_reduction + 0.15·readability)
readability = 1.0  (25≤avg_len≤70)
            = 0.6  (avg_len<25)
            = max(0.5, 1-(avg_len-70)/150)  (avg_len>70)
```

## 三、本地 × 云端对比指标（compare.py）

| 指标 | 含义 |
|---|---|
| `keyword_jaccard` | 本地与云端摘要关键词集合的 Jaccard 相似度（0~1），越高越一致 |
| `only_in_local` | 本地有、云端漏掉的关键词 → 提示本地权重/候选句提示可上调 |
| `only_in_cloud` | 云端有、本地未提取的关键词 → 提示本地词表/规则待补充 |
| `suggestions` | 由上述差异自动生成的改进建议（可执行） |

## 四、改进闭环

1. 本地引擎默认离线产出抽取式摘要（eval 评分可见基线）。
2. 启用 `compare_cloud` 或 `mode=cloud/hybrid` 时，把云端抽象摘要与本地副本交 `compare.py` 比对。
3. 差异与建议落盘至 `feedback_dir`，周期性可打包反馈给开发者（`feedback_email`）。
4. 依据建议迭代 `scripts/summarize.py` 的打分权重、停用词、候选词生成规则，使本地能力逐步逼近云端。

## 五、多文档与超长文本

- **多文档联合摘要**：关键词跨文档统一提取，`keyword_coverage` 反映联合摘要对全部文档要点的覆盖；输出摘要以 `[文档N]` 标注来源，便于溯源核对。
- **滑动窗口（超长文本）**：输入超过 `max_input_chars` 时分块抽取再合并。由于合并后已二次压缩，`sentence_reduction` 与 `compression_ratio` 会显著偏高，属预期；重点看 `keyword_coverage` 是否覆盖跨块要点。
