# 04 · Quiz 生成

> 里程碑：主题 → 结构化题目（MCQ / 判断 / 简答）→ 逐题溯源校验。

## 本轮要实现

1. `generation/prompts.py` 中增加出题提示词（严格 JSON 结构，含 sources）。
2. `generation/quiz.py`：
   - 用主题检索证据，证据不足直接返回空题 + 原因；
   - 调用 LLM 拿 JSON，容忍 markdown 围栏与多余解释；
   - **逐题校验**：题型白名单、选项数量、答案可解析、sources 必须命中本次证据；
   - 校验不过的题目进 `dropped`，说明丢弃原因（可解释，不静默）。
3. `/quiz`、CLI `quiz`、Streamlit Quiz 标签页接线。

## 约束

- 题目只能来自讲义原文，`sources` 中至少一条命中证据的 `(doc_id, page)`。
- MCQ 答案统一为 `A/B/C/D` 字母且必须落在选项范围内；判断题答案统一为 `True/False`；
  简答题必须给参考答案要点。
- 题数与请求题数一致（超出丢弃，并在 `dropped` 记录）。
- 不允许出现两个正确选项：靠“答案可解析 + 干选项清理”保证结构层面一致（语义层面靠提示词约束）。

## 验收命令

```bash
lectureqa quiz --topic "RAG 分块策略" -n 3
python -m pytest tests/test_quiz.py -q
```

通过标准：出题全部带 `doc_id + page`；无证据主题返回空题并给出原因；非法 JSON 不抛裸异常。
