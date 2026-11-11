# LectureQA 用户研究协议（目标场景评估）

目的：在真实复习场景中检验产品是否有用、来源是否可分清。  
结果写入：`eval/user_study_results.csv`  
报告引用：`docs/REPORT.md` §5

> 小样本（建议 5–8 人）**不作普遍结论**；只报告观察到的趋势与局限。

## 1. 参与者与材料

- 参与者：同课程或相关课程同学 5–8 人
- 系统：LectureQA Streamlit（两种模式都可切换）
- 语料：本项目已入库的课程讲义
- 每人时长：约 20–25 分钟

## 2. 任务设计（每人 5 题）

请提前准备 5 类问题（可复用测试集改写，避免直接背答案）：

| # | 类型 | 目的 |
|---|---|---|
| 1 | 讲义明确可答 | 看出处是否有用 |
| 2 | 讲义部分覆盖 | 看是否过度自信 |
| 3 | 讲义未覆盖 | 看拒答 / 外部补充是否清晰 |
| 4 | 跨讲义综合 | 看全课程问答是否有帮助 |
| 5 | 自选题（参与者自己的复习问题） | 贴近真实需求 |

每种模式各做一轮（顺序可随机）：

1. **仅课程材料**
2. **课程材料 + 网络补充**

## 3. 每题记录（写入 CSV 一行）

字段见 `eval/user_study_results.csv` 表头：

- `participant_id`：P1…P8
- `mode`：`lecture_only` / `lecture_plus_web`
- `question_type`：`covered` / `partial` / `uncovered` / `cross` / `own`
- `resolved`：是否解决需求（0/1）
- `viewed_citation`：是否点开/点击页码（0/1）
- `adopted_answer`：是否愿意采纳为复习笔记（0/1）
- `wanted_external`：是否希望外部解释（0/1）
- `usefulness` / `trust` / `satisfaction`：1–5
- `source_attr_correct`：来源归属题是否答对（0/1/NA）
- `source_confusion`：是否发生来源混淆（0/1）
- `preferred_mode`：该参与者最终偏好
- `notes`：开放反馈

### 来源归属小测（source attribution）

在含网络补充的答案中，挑 1–2 条事实性陈述，问参与者：这是「课程材料」还是「外部补充」？  
正确率写入 `source_attr_correct`。

## 4. 汇总结论模板（填进报告 §5）

```text
参与者 n=__；题次 N=__。
仅课程材料：usefulness=__ trust=__；查看引用率=__；未覆盖题拒答可理解率=__。
材料+网络：usefulness=__ trust=__；来源归属正确率=__；来源混淆事件=__。
模式偏好：lecture_only=__ / lecture_plus_web=__ / depends=__。
主要反馈：…
局限：样本小、任务由研究团队准备，外推有限。
```

## 5. 执行步骤（最短路径）

1. 启动 `streamlit run app/streamlit_app.py`
2. 说明两种模式差异（1 分钟）
3. 参与者答题并操作引用跳转（15 分钟）
4. 立即打分填 CSV（5 分钟）
5. 汇总均值与偏好，粘贴进 `docs/REPORT.md` §5
