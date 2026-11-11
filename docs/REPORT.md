# LectureQA：面向课程复习的来源感知学习助手

**LectureQA: A Source-Aware Generative Study Assistant for Course Review**

DSC6021 Generative AI · Product / Application 路线 · 技术报告（定稿）

配套材料：`docs/SPEC.md`（架构）· `docs/EVALUATION.md`（指标）· `docs/DEMO.md`（演示）· `docs/USER_STUDY.md`（用户研究）· `docs/CHECKLIST.md`（交付闭环）· `eval/reports/SUITE_RESULTS.md`（实验汇总）

---

## 1. 问题与动机

课程复习时，学生真正需要的不只是“一个听起来对的答案”，而是：

1. 答案是否来自**本课程讲义**；
2. 依据在**哪一页**，能否当场核对；
3. 讲义没覆盖时，系统是**明确拒答 / 标注外部来源**，还是把外部知识伪装成课件结论。

通用聊天机器人往往做不到来源可控；纯关键词搜索又缺少解释与练习。LectureQA 把“来源可控 + 可核对”作为产品主张：用生成模型完成答疑与出题，但用检索证据、引用校验与拒答机制约束生成行为。

**目标用户**：需要按课程范围复习、查找讲义出处、理解概念并自测的学生。  
**核心需求**：可信答疑、出处跳转、材料未覆盖时的诚实行为、可溯源练习题。

---

## 2. 产品与系统架构

### 2.1 产品能力

| 能力 | 说明 |
|---|---|
| 仅课程材料问答 | 答案必须有讲义证据；不足则拒答 |
| 课程材料 + 网络补充 | 仅在讲义不足时触发；外部内容单独标注 |
| 页码出处 | 正文内联可点页码，右侧课件跳转；可展开原文片段 |
| 课程学习闭环 | 课程地图 → 单讲学习 → 自测/错题 → 全课程问答 |
| 可溯源 Quiz | 结构化出题，逐题校验出处必须落在证据页 |

### 2.2 数据流

```text
PDF → 按页抽取 → 不跨页分块 → 向量+BM25 混合检索
    → 证据充分性判定 → 带引用生成 → 引用校验 → Streamlit / FastAPI / CLI
```

详细模块边界与契约见 `docs/SPEC.md`。

### 2.3 关键设计决策

| 决策 | 理由 |
|---|---|
| 按页分块、禁止跨页 | 引用必须落到具体 PPT 页 |
| 混合检索 + coverage rerank | 兼顾语义与关键词；默认无额外重排模型 |
| 先判证据再生成 | 降低“没依据也硬答” |
| 生成后校验 `[[doc_id:pN]]` | 删除不在证据集中的引用；兼容模型误写的 `[[doc_id:xxx:pN]]` |
| Quiz 结构化 + 丢弃不合格题 | 禁止元问题，强制知识点与可溯源出处 |
| 网络补充默认关闭且单独标注 | 避免外部知识混进讲义出处 |

---

## 3. 评估设计

对应课件要求：**meaningful evaluation**，并尽量贴近 *evaluate the product in its intended setting*。

### 3.1 研究问题

| RQ | 问题 | 指标 |
|---|---|---|
| RQ1 | 混合检索能否召回正确讲义页？ | hit@k、recall@k、MRR |
| RQ2 | 答案论断是否落在讲义原文上？ | citation_precision、grounded_rate |
| RQ3 | 讲义未覆盖时是否乱答？ | unanswerable_refusal_rate、refusal_accuracy |
| RQ4 | 引用约束对答案质量有无代价？ | LLM-as-judge、延迟 |

### 3.2 测试集

- 正式集：`eval/testset.full.jsonl`（72 题；可答 62 / 不可答 10；覆盖 10 份讲义）
- 冒烟集：`eval/testset.sample.jsonl`（6 题）
- 标注规范见 `docs/EVALUATION.md`

### 3.3 实验组

| 组 | 含义 |
|---|---|
| main-hybrid-coverage | 主配置 |
| ablation-bm25-only | 仅词面召回 |
| ablation-hybrid-cross-encoder | 交叉编码器重排 |
| threshold-0.15…0.60 | 拒答阈值敏感性（sample） |
| sample-with-judge | 冒烟集 + LLM-as-judge（RQ4） |

复现：

```bash
.venv/bin/python scripts/run_eval_suite.py --only main
.venv/bin/python scripts/run_eval_suite.py --only ablation
.venv/bin/python scripts/run_eval_suite.py --only cross-encoder
.venv/bin/python scripts/run_eval_suite.py --quick --only threshold
# RQ4（需配置 EVAL_JUDGE_MODEL）
EVAL_JUDGE_MODEL=<model> lectureqa eval --testset eval/testset.sample.jsonl -k 6 --judge
```

---

## 4. 结果

### 4.1 正式全量（72 题，k=6）

| suite | hit | recall | MRR | citeP | grounded | refuseAcc | unansRefuse | err | lat(ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| main-hybrid-coverage | 0.919 | 0.887 | 0.752 | 0.676 | 0.806 | 0.847 | 1.0 | 0.0 | 14884 |
| ablation-bm25-only | 0.677 | 0.653 | 0.504 | 0.505 | 0.548 | 0.653 | 1.0 | 0.0 | 10427 |
| ablation-hybrid-cross-encoder | 0.919 | 0.887 | 0.749 | 0.703 | 0.855 | 0.875 | 1.0 | 0.0 | 15080 |

**结论**

- Hybrid+coverage 相对 BM25-only：hit +24pp、recall +23pp、MRR +25pp、citeP +17pp、grounded +26pp。
- cross-encoder 相对 coverage：召回持平，citeP/grounded/refuseAcc 略升；默认仍用轻量 coverage。
- 不可答题拒答率 **100%**，符合“宁可少答也不能乱答”。

### 4.2 RQ4：LLM-as-judge（sample，6 题）

| 指标 | 数值 |
|---|---:|
| judge_score | 0.80 |
| citation_precision | 0.80 |
| grounded_rate | 0.80 |
| refusal_accuracy | 1.00 |
| avg_latency_ms | 16659 |

在引用约束下，冒烟集 judge 分数为 0.80，未出现“有引用但整体不可用”的崩塌；正式全量 judge 可作为答辩前可选加强项。原始报告：`eval/reports/suite-sample-with-judge-20261110-145513.*`。

### 4.3 阈值敏感性（sample）

| thr | citeP | grounded | refuseAcc | unansRefuse | lat(ms) |
|---:|---:|---:|---:|---:|---:|
| 0.15 | 0.800 | 0.800 | 1.0 | 1.0 | 10397 |
| 0.30 | 0.800 | 0.800 | 1.0 | 1.0 | 10851 |
| 0.45 | 0.808 | 1.000 | 1.0 | 1.0 | 13052 |
| 0.60 | 0.800 | 0.800 | 1.0 | 1.0 | 13397 |

sample 偏易，曲线较平；正式集上仍有 11/62 可答题被保守拒答，说明默认阈值 0.30 偏严，可在 0.20–0.30 再调。

### 4.4 失败案例（主配置）

- **检索未命中（5/62）**：中英术语不对齐、跨页综合题。
- **可答题过度拒答（11）**：证据分低于阈值或召回页偏移。
- **引用精度偏低**：大意正确但页码与 gold 不完全重合，或有效引用缺失。
- **不可答题**：全部正确拒答。

完整汇总见 `eval/reports/SUITE_RESULTS.md`。

---

## 5. 目标场景评估（用户研究）

离线指标回答“系统是否按承诺工作”；用户研究回答“在复习场景里是否真有用、来源是否可分清”。

协议与记录表见 `docs/USER_STUDY.md`、`eval/user_study_results.csv`：

- 5–8 名同学 × 每人约 5 题 × 两种来源模式；
- 记录有用性 / 可信度 / 是否查看引用 / 来源归属正确率 / 模式偏好；
- **小样本不作普遍结论**，报告样本数与局限。

答辩前按该协议完成采集，把汇总填入本节与附录即可闭环 *evaluate in its intended setting*。

---

## 6. 对照课程评分维度

| 维度 | 本项目对应点 |
|---|---|
| Novelty | 来源可控的课程复习助手：拒答 + 引用校验 + 讲义/网络分开展示 + 学习闭环，而不是通用 RAG 聊天框 |
| Usefulness | 页码可核对、Quiz 可溯源、课程地图与进度服务真实复习流程 |
| Time and effort | 完整管线、混合检索、评估套件、消融、前后端与测试；见分工与仓库提交历史 |

---

## 7. 局限与改进

- 扫描版 PDF 无 OCR；复杂公式/图理解有限。
- 多轮追问上下文仍偏浅。
- 引用精度约 0.68，仍有提升空间；可答题存在过度拒答。
- Streamlit 内联页码跳转受布局限制，观感仍可打磨。
- 正式全量 LLM-as-judge、完整用户研究样本建议在答辩前补齐。

---

## 8. 演示与交付

- 5 分钟演示：`docs/DEMO.md`（问答引用 → 拒答 → Quiz → 评估截图）
- 交付闭环清单：`docs/CHECKLIST.md`
- 启动：`streamlit run app/streamlit_app.py`

---

## 附录 A · 主要产物路径

| 产物 | 路径 |
|---|---|
| 产品 | `app/streamlit_app.py`、`src/lectureqa/` |
| 正式测试集 | `eval/testset.full.jsonl` |
| 实验汇总 | `eval/reports/SUITE_RESULTS.md` |
| Judge 冒烟 | `eval/reports/suite-sample-with-judge-20261110-145513.md` |
| 用户研究 | `docs/USER_STUDY.md` |
