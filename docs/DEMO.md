# LectureQA — 演示与交接操作手册

适用于课堂演示、团队交接、录屏前检查。目标是在没有真实课程语料/API Key 的情况下，也能展示检索证据、拒答与 UI；正式回答需要配置可用的 Chat Completion API。

## 建议演示流程（5 分钟）

1. 打开 Streamlit，左侧确认索引状态为 3 份示例讲义 / 11 个分块。
2. 问答：提问「缩放因子 sqrt(d_k) 起什么作用？」展示逐页引用及可展开原文。
3. 检索调试：输入「多头注意力默认几个头」，展示 top 结果的 dense / BM25 / support 分数。
4. Quiz：主题「RAG 分块策略」，生成 3 道题，展开答案与出处。
5. 拒答：问「课程是否允许用 Moonshot 替代 Claude？」若真实讲义没有覆盖，系统会拒答。
6. 展示评估报告：打开 `eval/reports/SUITE_RESULTS.md`（主结果 + BM25 消融）与 `docs/REPORT.md`；需要复现时跑 `python scripts/run_eval_suite.py --only main`。
7. （可选）展示用户研究记录表 `eval/user_study_results.csv` 与协议 `docs/USER_STUDY.md`。

## 演示前检查

```bash
# 终端 A：在项目根目录启动 UI
EMBEDDING_PROVIDER=hash STORE_BACKEND=chroma streamlit run app/streamlit_app.py

# 终端 B：确认索引；若为空重建
EMBEDDING_PROVIDER=hash STORE_BACKEND=chroma lectureqa ingest data/sample
EMBEDDING_PROVIDER=hash STORE_BACKEND=chroma lectureqa documents
EMBEDDING_PROVIDER=hash STORE_BACKEND=chroma lectureqa search "多头注意力默认几个头" -k 3
```

如果配置环境变量后无法使用旧索引（embedding provider / 模型与建库不一致），请用同样的环境配置重新 `ingest`。不同 embedding 模型的向量不能混用。

## 模型 Key

复制 `.env.example` 为 `.env`，设置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。嵌入接口可单独配置 `EMBEDDING_PROVIDER` 与 `EMBEDDING_MODEL`。只有 `hash` embedding 时检索偏词面；正式演示推荐稳定的语义 embedding。

## 常见问题

- **`NO_ANSWER` 看不见答案**：检查 `data/` 下讲义是否包含相应信息，使用 `lectureqa search` 查看实际召回证据。
- **PDF 没被读到**：确认不是扫描图片版；当前不含 OCR。检查 ingest 报告的 `skipped`。
- **讲义名不同**：评估集 gold_doc_ids 需对应 manifest 的 doc_id；下划线和连字符在指标里归一化。
- **API 端口被占用**：`lectureqa serve --port 8001`。
- **需要重新建库**：`lectureqa ingest` 默认 reset；`lectureqa ingest --keep` 是追加，不建议用于替换已有语料。

## 收尾

演示结束后无需提交 `var/`、`.env`、`.venv/` 或 `eval/reports/`。`data/sample/` 是脚本生成的测试 PDF；真实课程 PDF 的分发与提交应遵循课程授权要求。
