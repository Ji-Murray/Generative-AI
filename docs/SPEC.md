# LectureQA 技术规格（SPEC）

本文件是项目的「宪法」：模块边界与数据契约以实现为准，任何改动都要先改这里。

## 1. 目标与非目标

**目标**

1. 学生用自然语言查找、理解和核对课程讲义，并在课程材料模式下为每个论断给出可核对的页码出处。
2. 让用户控制回答来源：仅课程材料，或在讲义证据不足时请求网络补充；两类来源必须清楚分离。
3. 课程材料不足时，在严格模式下明确拒答，绝不编造；补充模式下只使用检索到的外部片段并附链接。
4. 基于讲义原文生成可溯源的练习题（Quiz）。
5. 提供可复现的评估实验（检索侧 + 生成侧 + 拒答能力 + 来源区分）。

**非目标**

- 不做多轮复杂对话规划（当前为无状态单轮，多轮由前端拼接历史后自行决策）。
- 不做 OCR。扫描版 PDF 会进入 `skipped` 列表并显式提示。
- 不做用户账号与权限体系。

## 2. 架构

```text
data/*.pdf
   │  pymupdf 逐页抽取（保留 page）
   ▼
ingest/pdf.py ──► ParsedDocument(pages)
   │  幻灯片感知分块：不跨页 + 句界打包 + 重叠
   ▼
ingest/chunker.py ──► Chunk[]
   │
   ├─► var/index/chunks.jsonl        事实源（BM25 / 引用回溯都读它）
   ├─► var/index/manifest.json       讲义清单、构建参数
   └─► embeddings.make_embedder ──► 向量 ──► store.make_store
                                                ├─ ChromaStore（默认）
                                                └─ LocalStore（numpy 兜底）

用户问题
   ▼
retrieval/retriever.py
   向量召回(top fetch_k) + BM25 召回(top fetch_k) ──RRF融合──► 候选
   ──rerank──► RetrievedChunk[top_k]（含 support 证据支持度）
   ▼
generation/qa.py
   support < MIN_EVIDENCE_SCORE
        ├─ 未开启联网 → 直接拒答（不调用 LLM）
        └─ 已开启联网 → retrieval/web.py 取网络片段 → LLM 生成 [[web:N]] → 校验 → Answer(scope=external)
   否则 LLM 生成 → 解析 [[doc_id:pN]] → 校验 → 剔除编造引用 → Answer
   ▼
FastAPI / CLI / Streamlit
```

## 3. 模块边界

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `ingest/pdf.py` | PDF → 页文本 + 标题猜测 | 不做分块、不碰向量 |
| `ingest/chunker.py` | 页文本 → `Chunk`（不跨页） | 不认识 LLM |
| `ingest/pipeline.py` | 编排解析→分块→落盘→向量化 | 不组装检索/生成 |
| `retrieval/embeddings.py` | 文本 → 向量（3 种 provider） | 不关心存储 |
| `retrieval/store.py` | 向量存取，返回 `(chunk_id, 余弦)` | 不读 chunks.jsonl |
| `retrieval/corpus.py` | chunks.jsonl 的内存视图 + BM25 | 不做生成 |
| `retrieval/retriever.py` | 混合召回 + 融合 + 重排 + support | 不构造提示词 |
| `retrieval/rerank.py` | coverage / cross-encoder 重排 | 不调用 LLM |
| `retrieval/web.py` | 网络补充检索（默认关闭） | 不生成答案、不写引用 |
| `generation/prompts.py` | 全部提示词 | 不写业务逻辑 |
| `generation/qa.py` | 拒答判定、引用解析与校验 | 不直接访问向量库 |
| `generation/quiz.py` | 结构化出题 + 逐题校验 | 不渲染 UI |
| `learning/outline.py` | 课程地图：每讲概述块 → 结构化学习卡片，按语料指纹缓存 | 不做检索、不管 UI |
| `learning/progress.py` | 学习进度与自测成绩持久化（JSON 原子写） | 不调用 LLM |
| `service.py` | 装配线（唯一入口） | 不承载路由/渲染 |
| `api/main.py` / `cli.py` / `app/` | 传输层 | 不写业务规则 |
| `eval/*` | 指标与实验编排 | 不改动线上逻辑 |

## 4. 数据契约（`src/lectureqa/schemas.py`）

```python
Chunk(chunk_id, doc_id, doc_title, page, chunk_index, text, char_start, char_end)
RetrievedChunk(chunk, score, dense_score, lexical_score, support)   # support ∈ [0,1]
Citation(doc_id, doc_title, page, chunk_id, snippet, valid)
ExternalSource(title, url, snippet, provider)                      # 非讲义来源（网络补充）
Answer(question, answer, citations, evidence, external_sources, answer_scope,
       grounded, refused, invalid_citations, model, latency_ms)
# answer_scope: lecture = 仅讲义；external = 讲义证据不足、使用网络补充；none = 拒答
QuizQuestion(question_id, type, difficulty, question, options, answer, explanation, sources, grounded)
QuizResult(topic, questions, dropped, evidence, model)
TestItem(qid, question, type, gold_doc_ids, gold_pages, reference_answer, notes)
ItemResult(... , error)     # error 非空表示该题生成失败（指标计算时排除）
EvalReport(testset, k, n, metrics, items, generated_at)
LectureOutline(doc_id, order, title, summary, objectives, concepts, key_pages)
CourseOutline(course_title, overview, learning_path, lectures, relations, generated_at, fingerprint)
LectureProgress(status, updated_at, quiz_attempts, quiz_correct)     # status: not_started/learning/completed
LearningState(lectures, updated_at)
```

**硬约束**

- `chunk_id` 全局唯一，格式 `{doc_id}:p{page}:c{idx}`；`page` 为 1-based。
- 一个 `Chunk` 绝不跨页 —— 这是引用能精确到页码的前提。
- `doc_id` 由文件名 slug 化得到（`lecture01_course_overview` → `lecture01-course-overview`），
  评估集里的 gold 标注会做同样的归一化后比较，两种写法都可用。

### 4.1 学习闭环（课程地图 / 学习进度）

- 课程地图由 `learning/outline.py` 生成：每份讲义取第 1 个分块（概述块）→ 一次 JSON 调用同时得到课程总览、
  逐讲学习目标 / 关键概念 / 关键页码、各讲关系。
- 结果缓存到 `var/learning/outline.json`；`fingerprint` 由 `(doc_id, pages, chunks, 总分块数)` 计算，
  语料变化或上传新讲义后自动失效并重建。
- LLM 不可用或返回非法 JSON 时退回**抽取式大纲**（标题 + 概述块前 160 字），保证首页始终可用。
- 学习进度写入 `var/learning/progress.json`（原子写），前端与 API 共用；记录每讲状态与自测累计正确数。

## 5. 引用协议

- 模型必须输出 `[[doc_id:p页码]]`，例如 `[[lecture02-transformer:p3]]`。
- 生成后由 `generation/qa.py` 做**强制校验**：
  - 标记必须命中本次实际检索到的 `(doc_id, page)` 集合；
  - 未命中的标记从正文中删除，并记录到 `Answer.invalid_citations`；
  - `grounded = 至少有一条有效引用`。
- 引用去重后按出现顺序返回，`snippet` 为证据原文前 300 字，供前端展开核对。

### 5.1 网络补充协议（可选）

- 仅当 `WEB_FALLBACK != off` 或调用方显式传 `allow_web=true`，且讲义 support 低于阈值时触发。
- 网络片段由 `retrieval/web.py` 返回 `ExternalSource`，模型必须输出 `[[web:N]]`（N 为本次片段编号）。
- 校验规则：越界编号删除并记入 `invalid_citations`；同时**删除所有 `[[doc_id:pN]]` 讲义引用**
  （因为未通过讲义证据校验），避免把网络内容伪装成讲义出处。
- 若最终没有任何有效 `[[web:N]]`，按拒答处理。
- 网络答案固定 `answer_scope=external`、`grounded=false`、`citations=[]`；前端必须用独立区块标注
  「以下内容来自网络，不属于课程讲义」并给出 URL。

## 6. 拒答策略

1. 检索结果为空，或 `max(support) < MIN_EVIDENCE_SCORE` → **不调用 LLM**，直接拒答（省 token、可解释）。
2. 模型输出 `NO_ANSWER` → 拒答。
3. `support = max(问题实词覆盖率, 余弦归一化值)`，见 `retrieval/rerank.py:coverage_score`
   与 `retriever._dense_to_support`。阈值可通过 `MIN_EVIDENCE_SCORE` 调节。
4. 拒答文案跟随提问语言（中文提问给中文拒答）。
5. **总结/概括类问题**（"总结一下""这讲了什么内容""课程概述"等）走独立路径：
   每份讲义取「概述块 + 与问题最相关的块」组成跨讲义证据，不受单点 `support` 阈值限制；
   引用仍要按第 5 节规则校验，证据为空时照样拒答。

## 7. 配置项（`.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | — / deepseek / deepseek-chat | 唯一换模型的入口 |
| `EMBEDDING_PROVIDER` | openai | `openai` / `hash` / `chroma` |
| `EMBEDDING_MODEL` | text-embedding-3-small | 需服务端支持 |
| `STORE_BACKEND` | chroma | `chroma` / `local` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 900 / 150 | 分块参数（按讲义页长度调） |
| `UPLOAD_DIR` | `<项目根>/var/uploads` | 前端/API 上传 PDF 的落盘目录 |
| `MAX_UPLOAD_MB` | 30 | 单个上传文件大小上限 |
| `FETCH_K` / `TOP_K` | 30 / 6 | 召回数 / 进提示词的证据数 |
| `RERANK` | coverage | `coverage` / `cross-encoder` / `none` |
| `MIN_EVIDENCE_SCORE` | 0.30 | 拒答阈值，评估时重点调这个 |
| `DEFAULT_LANGUAGE` | auto | `auto` / `zh` / `en` |
| `WEB_FALLBACK` | off | `off`（默认拒答）/ `wikipedia`（允许网络补充并单独标注） |
| `WEB_LANG` | auto | 网络检索语言，`auto` 跟随提问语言 |
| `WEB_MAX_RESULTS` | 3 | 网络补充片段上限 |
| `WEB_TIMEOUT` | 8 | 网络检索超时（秒） |
| `WEB_MIN_COVERAGE` | 0.30 | 网络结果与问题的覆盖度下限，低于则放弃补充、按拒答处理 |
| `EVAL_JUDGE_MODEL` | 空 | 填了才启用 LLM-as-judge |

## 8. 降级与容错

| 场景 | 行为 |
|---|---|
| 未配 LLM Key | 检索/评估（检索侧指标）仍可用；问答与出题明确报错 `LLMError` |
| embedding 服务不可用 | 建库时跳过向量索引；查询时自动退化为纯 BM25，日志可见 |
| chromadb 缺失/损坏 | 自动降级为 `LocalStore`（numpy 余弦） |
| 模型返回非法 JSON | 回灌错误让模型自修复一次，仍失败则抛错 |
| 模型引用编造页码 | 删除该标记并在 `invalid_citations` 里记录 |
| 网络补充不可用/超时 | 记日志并退回拒答，不影响讲义链路 |
| 网络答案混入讲义引用 | 删除 `[[doc:pN]]` 并记录，保留 `[[web:N]]` |
| 单条评估样本异常 | 该题记录 `error`，不中断整轮实验 |

## 9. 扩展点

- 新 embedding / 新向量库：实现 `Embedder` / `VectorStore` 协议，改 `make_*` 工厂即可。
- 新题型：扩展 `QuestionType` 与 `validate_question`。
- 换 UI：`LectureQAService` 是唯一依赖点，FastAPI 与 Streamlit 都是薄壳。
