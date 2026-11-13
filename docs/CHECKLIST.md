# LectureQA 交付闭环清单

对照 DSC6021 课件：Product / Application 路径 + 交付物 + 课堂评价维度。

## A. 路径要求（Product / Application）

| 要求 | 状态 | 证据 |
|---|---|---|
| Identify real users and needs | ✅ | `docs/REPORT.md` §1：复习学生 / 出处与拒答需求 |
| Demonstrate useful behavior | ✅ | 可运行产品：问答+页码跳转、拒答、Quiz、学习闭环；`docs/DEMO.md` |
| Evaluate in its intended setting | 🟡 | 离线评估已完成；用户研究协议已就绪，**答辩前按 `docs/USER_STUDY.md` 采 5–8 人** |
| Generative model + meaningful evaluation | ✅（口径已注明） | LLM 生成答疑/出题；72 题消融 + judge 冒烟；已注明自制示例课件范围与 grounded 指标限制；`eval/reports/SUITE_RESULTS.md` |

## B. 交付物

| 交付物 | 状态 | 位置 |
|---|---|---|
| Product itself | ✅ | `streamlit run app/streamlit_app.py` / `lectureqa serve` |
| Technical report | ✅ | `docs/REPORT.md`（定稿） |
| Presentation（最后两节课） | ⬜ | 全员到场；幻灯片中写明每人负责部分 |
| Who completed each part | 🟡 | 下方分工表填真实姓名后贴进报告/幻灯片 |

### 分工表（答辩前填姓名）

| 角色 | 姓名 | 负责 |
|---|---|---|
| A · 语料与检索 | （填） | PDF 解析、分块、向量库、rerank · `prompts/01–02` |
| B · 生成与提示 | （填） | 提示词、引用约束、Quiz · `prompts/03–04` |
| C · 前端与集成 | （填） | Streamlit、出处跳转、演示 · `prompts/05` |
| D · 评估与报告 | （填） | 测试集、实验、技术报告、用户研究 · `prompts/06` |

## C. 课堂评价维度（准备怎么讲）

| 维度 | 一句话 |
|---|---|
| Novelty | 不是通用聊天机器人，而是来源可控的课程复习产品（拒答 + 引用校验 + 讲义/网络分离 + 学习闭环） |
| Usefulness | 能定位到页、能自测、材料没有时不装懂 |
| Time and effort | 完整工程 + 72 题正式评估 + 消融 + 报告与演示材料 |

## D. 答辩前 30 分钟检查

- [ ] `.env` 可用；`lectureqa documents` 能看到真实讲义
- [ ] 按 `docs/DEMO.md` 走通：有引用跳转 / 拒答 / Quiz / 评估截图
- [ ] 打开 `docs/REPORT.md` 与 `eval/reports/SUITE_RESULTS.md` 备用
- [ ] 用户研究至少完成一小批，结果写入 `eval/user_study_results.csv`
- [ ] 幻灯片写明四人分工与到场名单
- [ ] 不提交 `.env` / `.venv` / 含隐私的原始问卷（可交汇总）

## E. 可选加强（有时间再做）

- [ ] 正式集全量 `--judge`
- [ ] 阈值 0.20–0.30 再扫一版，减少过度拒答
- [ ] 录一段 3–5 分钟演示视频兜底
