# LectureQA —— 面向课程复习的来源感知学习助手

**LectureQA: A Source-Aware Generative Study Assistant for Course Review**

DSC6021 Generative AI 期末项目（Product / Application 路线）。LectureQA 帮助学生查找、理解和核对课程材料：
用户可选择**仅使用课程材料**，或在讲义证据不足时启用**网络补充**。课程引用提供页码与原文片段；
外部内容单独标注来源，避免把补充知识误认为课程讲义内容。系统也可根据课程材料生成可溯源练习题。

核心问题不是要求学生只能依靠 PPT，而是让学生知道答案是否来自课程材料、依据在哪里，以及材料没有覆盖什么。
项目已实现数据管线、混合检索、来源模式切换、引用校验、Quiz、课程学习闭环、FastAPI / Streamlit 与离线评估。

## 快速开始

```bash
# 1) 环境（Python 3.11+；uv 或 pip/venv 均可）
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'          # 或 pip install -e '.[dev]'

# 2) 配置：复制 .env.example 为 .env，填入任意 OpenAI 兼容接口的 Key / base_url / model
cp .env.example .env

# 3) 准备语料（二选一）
#    a. 把讲义 PDF 放进 data/（支持子目录）
#    b. 或者在网页左侧「上传讲义」直接选 PDF，自动增量入库（无需重启）
#    没有真实讲义时，可先生成示例课件跑通全链路：
lectureqa sample --out data/sample

# 4) 建索引并提问
lectureqa ingest                 # 扫描 data/ + var/uploads/
lectureqa ingest path/to/x.pdf   # 也可直接指定文件，做增量导入
lectureqa documents
lectureqa ask "多头注意力为什么要使用缩放因子？"

# 5) 前端 & API
streamlit run app/streamlit_app.py
lectureqa serve --port 8000      # FastAPI，/docs 有交互式文档
```

> 没有 API Key 也能跑：检索与评估的检索侧指标可用（自动退回 BM25 / 哈希向量）。
> 首次想零依赖验证全链路，可设 `EMBEDDING_PROVIDER=hash STORE_BACKEND=local`。

## 目录结构

```
├── data/                     # 课程讲义 PDF（真实语料；data/sample 为自测课件）
├── src/lectureqa/
│   ├── config.py             # 全部参数从 .env 读取（唯一配置入口）
│   ├── schemas.py            # 跨模块数据契约（Pydantic）
│   ├── textutils.py          # 中英混排分词、断句、归一化
│   ├── llm.py                # OpenAI 兼容客户端（重试 / JSON 修复 / FakeLLM）
│   ├── service.py            # 装配线：API/CLI/前端共用
│   ├── cli.py                # ingest / documents / search / ask / quiz / eval / serve / sample
│   ├── ingest/               # pdf 抽取 → 幻灯片感知分块 → pipeline
│   ├── retrieval/            # embeddings / store / bm25 / corpus / retriever / rerank
│   ├── generation/           # prompts / qa（引用校验+拒答）/ quiz（逐题溯源校验）
│   ├── learning/             # outline（课程地图生成与缓存）/ progress（学习进度）
│   ├── eval/                 # metrics / runner（JSON+Markdown 报告）
│   └── api/main.py           # FastAPI：/health /outline /progress /documents /search /ask /ask/stream /quiz /ingest /ingest/upload
├── app/streamlit_app.py      # 课程首页 / 讲义学习 / 练习 / 全课程问答 / 课程管理
├── eval/                     # 测试集（jsonl）与 reports/
├── docs/                     # SPEC.md（模块边界与契约）、EVALUATION.md（指标与标注规范）
├── var/learning/             # 课程地图 outline.json 与学习进度 progress.json（运行时生成）
├── prompts/                  # 按里程碑拆分的开发提示词（交接用）
└── tests/                    # 63 个单元/集成测试（离线可跑）
```

## 产品定位

目标用户是需要按课程范围复习、查找讲义出处或理解课程概念的学生。产品不假设用户始终只需要 PPT 内的信息，而是让用户控制回答来源：

- **仅课程材料**：回答必须由检索到的课程证据支持；材料未覆盖时明确说明，不猜测。
- **课程材料 + 网络补充**：只有讲义证据不足时才尝试网络检索；外部答案与讲义引用分开展示，并附外部链接。
- **课程 Quiz**：根据课程材料生成练习题，每题保留可核对的页码来源。

项目主张是降低无依据回答与来源混淆的风险，而不是保证绝对无幻觉或宣称优于通用聊天机器人。

## 学习闭环（课程首页 → 讲义学习 → 练习）

前端不再以聊天框为首页，而是按学生学习课件的顺序组织：

1. **课程首页**：自动根据课件生成课程地图（整门课总览、逐讲学习目标、关键概念、关键页码、各讲关系），显示学习进度与推荐下一讲。
2. **讲义学习**：进入单讲后看到「本讲概览 / 本讲问答 / 本讲自测」三块；问答与自测默认只检索当前讲义，并可一键标记学习中 / 已完成。
3. **练习**：按左侧「限定讲义」范围出题，题目逐题可溯源到页码；答案默认折叠，先自测再核对。
4. **全课程问答**：需要跨讲义比较或整体总结时使用。
5. **课程管理**：上传 PDF、重建索引、重新生成课程大纲、检索调试（日常学习不需要）。

课程地图缓存到 `var/learning/outline.json`（按语料指纹失效），学习进度写入 `var/learning/progress.json`；
两者都没有数据库依赖，删除文件即可重置。

## 核心设计

| 关注点 | 做法 |
|---|---|
| 精确出处 | **按页分块**（chunk 绝不跨页），引用格式 `[[doc_id:p页码]]`，`chunk_id = doc_id:p{page}:c{idx}` |
| 检索质量 | 向量召回 + BM25 召回 → RRF 融合 → 证据覆盖度重排（可选 cross-encoder） |
| 不编造 | 生成后**强制校验引用**：不在本次证据页集合里的标记会被删除并记入 `invalid_citations` |
| 不乱答 | 生成前先判证据支持度，低于 `MIN_EVIDENCE_SCORE` 直接拒答、不调用模型 |
| 讲义优先 | 可选的网络补充只在讲义证据不足且显式开启时触发；`[[web:N]]` 单独校验，答案标记为「网络来源」，绝不混入讲义出处 |
| 可靠 Quiz | 结构化 JSON + 逐题校验（题型/选项/答案可解析/**出处必须命中证据**），不合格题记入 `dropped` |
| 可替换 | Embedding / 向量库 / 重排 / LLM 都是协议 + 工厂，改 `.env` 即可切换 |
| 可降级 | 无 Key → 纯 BM25；无 chromadb → numpy 兜底；embedding 失败 → 跳过向量索引 |

## 常用配置（`.env`）

| 变量 | 说明 |
|---|---|
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 唯一换模型的入口（DeepSeek / Moonshot / Qwen / GPT / Claude 兼容端点） |
| `EMBEDDING_PROVIDER` | `openai`（默认）/ `hash`（离线确定性）/ `chroma`（内置 ONNX） |
| `STORE_BACKEND` | `chroma`（默认，本地持久化）/ `local`（numpy） |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小与重叠 |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | 上传 PDF 的保存目录 / 单文件大小上限（默认 30 MB） |
| `FETCH_K` / `TOP_K` | 召回条数 / 进提示词的证据条数 |
| `RERANK` | `coverage`（默认）/ `cross-encoder`（需 `pip install -e '.[rerank]'`）/ `none` |
| `MIN_EVIDENCE_SCORE` | 拒答阈值（评估时重点调这个） |
| `WEB_FALLBACK` | `off`（默认拒答）/ `wikipedia`（讲义证据不足时联网补充，内容单独标注） |
| `EVAL_JUDGE_MODEL` | 填了才启用 LLM-as-judge |

完整说明见 `docs/SPEC.md` 第 7 节。

## 评估

```bash
# 无需 Key：先看检索侧（hit@k / recall / MRR / 拒答率）
lectureqa eval --testset eval/testset.sample.jsonl -k 6

# 正式实验（需 Key），启用 LLM-as-judge
EVAL_JUDGE_MODEL=deepseek-chat lectureqa eval --testset eval/testset.full.jsonl -k 6 --judge
```

指标定义、测试集标注规范、三组消融与阈值敏感性实验见 `docs/EVALUATION.md`；
报告自动写入 `eval/reports/report-<时间戳>.{json,md}`。

**交付文档**

- 技术报告定稿：`docs/REPORT.md`
- 交付闭环清单：`docs/CHECKLIST.md`
- 用户研究协议：`docs/USER_STUDY.md`
- 演示手册：`docs/DEMO.md`
- 实验汇总：`eval/reports/SUITE_RESULTS.md`

## 测试

```bash
python -m pytest -q          # 离线可跑，覆盖分块/检索/引用/拒答/Quiz/指标/API/端到端
ruff check .
```

## 技术栈

Python 3.11+ · PyMuPDF · ChromaDB · openai SDK（可配置 base_url）· FastAPI · Streamlit · pydantic-settings

## 团队分工对照

| 成员 | 负责 | 对应提示词 |
|---|---|---|
| A · 语料与检索 | PDF 解析、分块、向量库、rerank | `prompts/01`、`prompts/02` |
| B · 生成与提示 | 提示工程、引用约束、Quiz 生成 | `prompts/03`、`prompts/04` |
| C · 前端与集成 | Streamlit 界面、出处跳转、演示流程 | `prompts/05` |
| D · 评估与报告 | 测试集、用户研究、技术报告 | `prompts/06` |
# Generative-AI
