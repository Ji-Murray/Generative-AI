# LectureQA 评估实验设计（EVALUATION）

技术报告里最容易被扣分的两件事：**测试集没规范**、**指标和产品承诺对不上**。
本文件把两者都钉死。

## 1. 研究问题

| 编号 | 问题 | 对应指标 |
|---|---|---|
| RQ1 | 混合检索能否把正确讲义页召回进 top-k？ | hit@k、recall@k、MRR |
| RQ2 | 生成的答案有多少论断真正落在讲义原文上？ | 引用精度、接地率、grounded_rate |
| RQ3 | 面对讲义没覆盖的问题，系统会不会编？ | 不可回答题拒答率、refusal_accuracy |
| RQ4 | 加引用约束对答案质量有无代价？ | LLM-as-judge 分数、平均延迟 |

## 2. 测试集标注规范（`eval/testset.*.jsonl`）

一行一题，字段与 `schemas.TestItem` 一致：

```json
{"qid":"q002","question":"缩放点积注意力里的 sqrt(d_k) 起什么作用？",
 "type":"answerable","gold_doc_ids":["lecture02_transformer"],"gold_pages":[2],
 "reference_answer":"防止点积随维度增大导致方差过大、softmax 梯度消失。","notes":"解释型问题"}
```

**标注规则**

1. **gold_pages 写「必须读到的页」**：能回答该问题的最小页码集合。多写会虚高 recall，少写会虚低。
2. **gold_doc_ids 可写文件名或 slug 形式**（`lecture02_transformer` 与 `lecture02-transformer` 等价，
   指标里统一归一化）。
3. **必须包含 20% 以上的 `unanswerable` 题**：讲义未覆盖、或与课程无关（例如「课程是否允许换模型」）。
   这类题 `gold_pages` 留空。
4. **每个 `answerable` 题都写 `reference_answer`**：用于人工/LLM 判分，不能省。
5. `type` 与 gold 冲突（写 answerable 却没有 gold_pages）视为标注错误，`load_testset` 不报错但评估结果会失真 —— 提交前自查。

**建议规模**：60–100 题，覆盖全部 11 份讲义，问题类型分布约
定义类 30% / 解释类 30% / 数值与细节 20% / 跨页综合 10% / 不可回答 10–20%。

## 3. 指标定义

检索侧（只看 `answerable` 题）：

- `hit@k` = top-k 中是否至少有一页命中 gold_pages（同一 doc）
- `recall@k` = 命中的 gold 页数 / gold 页数
- `MRR` = 首个命中页排名倒数

生成侧：

- `citation_precision` = 引用中页码落在 gold 的比例（衡量引用是否指向正确位置）
- `grounded_rate` = 至少含一条通过证据页校验的有效引用的答案比例；它不等同于答案中每个论断都完成语义级事实核验
- `judge_score` = `(faithful + correct) / 2`，由 `EVAL_JUDGE_MODEL` 打分（0/1 各半）；当前没有无引用约束对照组，因此不能仅凭该分数判断引用约束是否带来质量代价

拒答侧：

- `unanswerable_refusal_rate` = 不可回答题中正确拒答的比例
- `refusal_accuracy` = 所有**未出错**样本上「该拒答的拒答、该回答的回答」的比例
- `error_rate` = 生成失败（接口异常、无 Key）的样本比例，不参与其他比率计算

## 4. 消融设置（至少跑这三组）

| 组 | 配置 | 目的 |
|---|---|---|
| A · BM25 only | `RERANK=none` 且 `EMBEDDING_PROVIDER=hash` | 词面基线 |
| B · Hybrid + coverage rerank | `RERANK=coverage` + 真实 embedding | 主实验 |
| C · Hybrid + cross-encoder | `RERANK=cross-encoder` | 重排收益 |

阈值敏感性：把 `MIN_EVIDENCE_SCORE` 在 `[0.15, 0.6]` 上扫一遍，画「拒答率 vs 引用精度」曲线，
这是技术报告里最有说服力的一张图（宁可少答也不能乱答）。

## 5. 运行方式

```bash
# 快速自测（无需 API Key，只有检索侧指标有意义）
lectureqa eval --testset eval/testset.sample.jsonl -k 6

# 正式实验（需 .env 配好 Key），并启用 LLM-as-judge
EVAL_JUDGE_MODEL=deepseek-chat lectureqa eval --testset eval/testset.full.jsonl -k 6 --judge
```

报告自动写到 `eval/reports/report-<时间戳>.json` 与 `.md`，`.md` 可直接粘进技术报告附录。

## 6. 用户研究（验证来源模式是否符合真实需求）

建议邀请 5–8 名同学，每人使用 5 个真实复习问题，覆盖：讲义明确回答、讲义部分涉及但不完整、讲义未覆盖、跨讲义综合。让参与者体验两种来源模式：

- **仅课程材料**：检查页码引用与材料未覆盖提示是否有帮助。
- **课程材料 + 网络补充**：检查用户是否注意到来源切换，并能区分讲义结论和外部内容。

每题记录是否解决需求、是否查看引用、是否采纳答案、是否希望获得外部解释，以及模式偏好。每种模式后用 1–5 分评价答案有用性、来源可信度和整体满意度，并收集开放反馈。条件允许时随机化模式先后顺序，减少顺序影响。

新增产品指标 **source attribution accuracy**：展示答案后，请参与者将若干事实性陈述归类为“课程材料”或“外部补充”，计算分类正确率；同时记录来源混淆事件。不要把小样本用户反馈表述为普遍结论，应报告样本数与局限。

关键研究问题：学生在什么任务下希望严格遵循课程材料？材料未覆盖时，他们偏好明确提示还是外部补充？页码与来源分离是否帮助他们核对和理解答案？

## 7. 技术报告建议结构

1. 问题与动机（课程复习场景的真实痛点）
2. 系统架构（贴 `docs/SPEC.md` 的图）
3. 关键设计决策：为什么按页分块、为什么混合检索、为什么先判证据再生成
4. 评估：测试集规模、三组消融、阈值敏感性图、失败案例分析（编造引用、跨页问题）
5. 局限与改进：扫描版 PDF、公式与图、多轮追问、rerank 成本


## 7. 当前复现状态

正式 72 题主配置、BM25 消融、交叉编码器消融和阈值实验已有结果，汇总见 `eval/reports/SUITE_RESULTS.md`。LLM-as-judge 已完成 6 题冒烟（`judge_score=0.80`）；运行正式全量 judge 时，当前配置模型返回 403，因此报告不记录该次失败运行的分数。

如需补跑全量 judge，先在 `.env` 配置当前账号可访问的 `EVAL_JUDGE_MODEL`，再执行：

```bash
EVAL_JUDGE_MODEL=<可访问模型> TMPDIR=/tmp .venv/bin/python scripts/run_eval_suite.py --only main --with-judge
```
