from pathlib import Path
from datetime import date

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches as PptInches, Pt as PptPt

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

NAVY = "102A43"
BLUE = "1976D2"
TEAL = "00A6A6"
ORANGE = "F59E0B"
INK = "243B53"
MUTED = "627D98"
PALE = "F0F4F8"
WHITE = "FFFFFF"


def shade(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def set_cell_text(cell, text, bold=False, color=INK, size=9):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(str(text))
    run.bold = bold
    run.font.name = "Aptos"
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_cell_margins(cell, top=80, start=100, bottom=80, end=100):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def add_table(doc, headers, rows, widths=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        set_cell_text(table.rows[0].cells[i], h, bold=True, color=WHITE, size=9)
        shade(table.rows[0].cells[i], NAVY)
        set_cell_margins(table.rows[0].cells[i])
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value, size=8.5)
            shade(cells[i], "F7FAFC" if len(table.rows) % 2 == 0 else WHITE)
            set_cell_margins(cells[i])
    if widths:
        for row in table.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    doc.add_paragraph()
    return table


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    p.style.font.name = "Aptos Display" if level == 1 else "Aptos"
    p.style.font.color.rgb = RGBColor.from_string(NAVY if level == 1 else BLUE)
    return p


def add_body(doc, text, bold_prefix=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.18
    if bold_prefix and text.startswith(bold_prefix):
        r = p.add_run(bold_prefix)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(INK)
        r.font.name = "Aptos"
        r.font.size = Pt(10.5)
        text = text[len(bold_prefix):]
    r = p.add_run(text)
    r.font.name = "Aptos"
    r.font.size = Pt(10.5)
    r.font.color.rgb = RGBColor.from_string(INK)
    return p


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(item)
        r.font.name = "Aptos"
        r.font.size = Pt(10.5)
        r.font.color.rgb = RGBColor.from_string(INK)


def set_doc_defaults(doc):
    sec = doc.sections[0]
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.3)
    sec.right_margin = Cm(2.3)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    styles["Normal"].font.size = Pt(10.5)
    for name, size, color in (("Title", 30, NAVY), ("Heading 1", 18, NAVY), ("Heading 2", 13, BLUE), ("Heading 3", 11, TEAL)):
        style = styles[name]
        style.font.name = "Aptos Display"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
    header = sec.header.paragraphs[0]
    header.text = "LectureQA  |  DSC6021 Generative AI"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.runs[0].font.size = Pt(8)
    header.runs[0].font.color.rgb = RGBColor.from_string(MUTED)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("LectureQA 技术报告  ·  ")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(MUTED)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer._p.append(fld)


def build_docx():
    doc = Document()
    set_doc_defaults(doc)
    cover = doc.add_paragraph()
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover.paragraph_format.space_before = Pt(80)
    r = cover.add_run("LECTUREQA")
    r.font.name = "Aptos Display"
    r.font.size = Pt(42)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(BLUE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("面向课程复习的来源感知生成式学习助手")
    r.font.size = Pt(22)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(NAVY)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    r = p.add_run("Technical Report  ·  Product / Application Route")
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(120)
    r = p.add_run("DSC6021 Generative AI\nNovember 2026")
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor.from_string(INK)
    doc.add_page_break()

    add_heading(doc, "摘要", 1)
    add_body(doc, "LectureQA 是一个面向课程复习的来源感知生成式学习助手。它不把“回答得流畅”作为唯一目标，而是让学生能够判断答案是否来自课程讲义、依据位于哪一页，以及当讲义没有覆盖问题时系统是否会明确说明。系统将 PDF 按页切分，结合向量检索与 BM25 召回，再通过证据充分性判断、引用校验和拒答机制约束生成。")
    add_body(doc, "离线评估覆盖 72 道题和 10 份讲义。主配置 hybrid + coverage 相较 BM25-only 在 hit@6、recall@6、MRR、citation precision 和 grounded rate 上均有明显提升。项目同时提供课程地图、单讲学习、可溯源 Quiz、FastAPI、Streamlit 和可复现实验脚本。")
    add_table(doc, ["项目定位", "核心承诺", "主要证据"], [["课程复习产品", "答案可核对、来源可分清", "页码引用、拒答、Quiz 溯源"], ["生成式 AI 应用", "用模型解释与出题", "LLM 生成 + 引用约束"], ["可评估工程", "不仅演示，还测量效果", "72 题、消融、阈值实验"]], [4.0, 6.0, 6.0])
    doc.add_page_break()

    add_heading(doc, "目录", 1)
    for item in ["1. 问题与用户需求", "2. 产品设计与使用流程", "3. 系统架构与关键技术", "4. 评估设计", "5. 实验结果与分析", "6. 目标场景评估", "7. 工程交付与团队分工", "8. 局限、风险与下一步", "附录 A：演示脚本", "附录 B：复现实验命令"]:
        p = doc.add_paragraph(item)
        p.paragraph_format.space_after = Pt(7)
        p.runs[0].font.size = Pt(12)
        p.runs[0].font.color.rgb = RGBColor.from_string(INK)
    doc.add_page_break()

    add_heading(doc, "1. 问题与用户需求", 1)
    add_heading(doc, "1.1 真实复习场景中的问题", 2)
    add_body(doc, "课程复习时，学生需要的不是一个听起来合理但无法核对的答案，而是三类信息：答案是否来自本课程讲义、依据位于哪一页、以及讲义没有覆盖时系统是否诚实地说明。通用聊天机器人擅长解释，但通常不会把课程范围、证据页和外部知识边界清楚分开；纯关键词搜索又缺少解释、总结和练习。")
    add_heading(doc, "1.2 目标用户与需求", 2)
    add_table(doc, ["用户", "任务", "痛点", "产品响应"], [["课程复习学生", "查概念、准备考试", "答案来源不确定", "讲义优先 + 页码引用"], ["项目展示学生", "理解系统与准备答辩", "需要快速总结全课", "课程地图 + 跨讲义问答"], ["需要拓展知识的学生", "了解讲义外背景", "外部知识易与课程结论混淆", "网络补充单独标注"]], [3.3, 4.0, 4.4, 5.0])
    add_heading(doc, "1.3 产品主张", 2)
    add_body(doc, "LectureQA 不宣称比通用模型更全能，而是针对课程复习增加来源约束：答案必须能够回到讲义页面；证据不足时应拒答；网络补充必须单独标注；练习题也必须保留可核对出处。")

    add_heading(doc, "2. 产品设计与使用流程", 1)
    add_heading(doc, "2.1 学习闭环", 2)
    add_table(doc, ["阶段", "学生看到什么", "系统能力"], [["课程首页", "课程地图、学习目标、进度", "按语料指纹生成并缓存 outline"], ["讲义学习", "本讲概览、问答、自测", "默认限制在当前讲义范围"], ["练习", "先答题，再展开答案和出处", "Quiz 逐题校验引用"], ["全课程问答", "跨讲义比较和整体总结", "全库混合检索"], ["课程管理", "上传 PDF、重建索引、调试", "面向维护而非日常学习"]], [3.0, 7.0, 6.0])
    add_heading(doc, "2.2 两种来源模式", 2)
    add_bullets(doc, ["仅课程材料：回答必须由召回到的讲义证据支持；证据不足时明确拒答。", "课程材料 + 网络补充：只有讲义证据不足时才尝试外部检索；网络内容与课程引用分开展示。", "两种模式都保留来源标签，避免学生把外部解释误认为课程结论。"])
    add_heading(doc, "2.3 产品演示路径", 2)
    add_body(doc, "建议演示顺序为：打开课程地图 → 进入单讲 → 提问讲义覆盖的问题并点击页码 → 提问讲义没有覆盖的问题并展示拒答 → 开启网络补充查看外部来源 → 进入 Quiz 先自测再查看答案。")

    add_heading(doc, "3. 系统架构与关键技术", 1)
    add_heading(doc, "3.1 数据流", 2)
    add_body(doc, "PDF → 按页抽取 → 幻灯片感知分块 → 向量 + BM25 召回 → RRF 融合 → coverage 重排 → 证据充分性判断 → 带引用生成 → 引用校验 → Streamlit / FastAPI / CLI。")
    add_heading(doc, "3.2 关键设计决策", 2)
    add_table(doc, ["决策", "实现", "理由"], [["按页分块", "chunk 不跨页，引用为 doc_id:pN", "保证出处可以回到具体 PPT 页"], ["混合检索", "embedding + BM25 + RRF", "兼顾语义相似和术语匹配"], ["先判证据再生成", "低于阈值直接拒答", "减少没有依据时的幻觉"], ["生成后校验", "过滤不在证据集合中的引用", "防止模型误写页码"], ["Quiz 逐题验证", "结构化 JSON + 出处命中检查", "避免生成不可核对的题目"], ["组件可替换", "embedding、存储、LLM 工厂", "通过配置切换服务商和离线模式"]], [3.7, 6.0, 6.3])
    add_heading(doc, "3.3 工程接口", 2)
    add_bullets(doc, ["CLI：ingest、documents、search、ask、quiz、eval、serve、sample。", "API：health、outline、progress、documents、search、ask、ask/stream、quiz、ingest。", "前端：Streamlit 课程首页、讲义学习、练习、全课程问答和课程管理。", "降级：无 API Key 时支持 BM25；无 ChromaDB 时支持 numpy 本地存储；embedding 失败时跳过向量索引。"])

    add_heading(doc, "4. 评估设计", 1)
    add_heading(doc, "4.1 研究问题", 2)
    add_table(doc, ["问题", "指标", "对应承诺"], [["能否找到正确讲义页？", "hit@k、recall@k、MRR", "出处可核对"], ["答案是否落在讲义原文上？", "citation precision、grounded rate", "生成受证据约束"], ["未覆盖时是否乱答？", "refusal accuracy、unanswerable refusal", "宁可拒答不编造"], ["引用约束是否损害质量？", "LLM-as-judge、延迟", "有依据同时可用"]], [5.5, 5.0, 5.5])
    add_heading(doc, "4.2 测试集与实验组", 2)
    add_body(doc, "正式测试集包含 72 道题，其中可答 62 题、不可答 10 题，覆盖 10 份讲义。实验包括主配置 main-hybrid-coverage、BM25-only 消融、hybrid + cross-encoder，以及拒答阈值 0.15–0.60 的敏感性实验。")
    add_heading(doc, "4.3 评估边界", 2)
    add_body(doc, "离线指标回答系统是否按照承诺工作，但不能完全回答学生是否愿意使用、是否理解来源标签。因此另行准备目标场景用户研究协议，记录有用性、可信度、引用查看、来源归属和模式偏好。")

    add_heading(doc, "5. 实验结果与分析", 1)
    add_heading(doc, "5.1 正式全量结果", 2)
    add_table(doc, ["实验组", "hit@6", "recall@6", "MRR", "citeP", "grounded", "refuseAcc"], [["main-hybrid-coverage", "0.919", "0.887", "0.752", "0.676", "0.806", "0.847"], ["ablation-bm25-only", "0.677", "0.653", "0.504", "0.505", "0.548", "0.653"], ["hybrid-cross-encoder", "0.919", "0.887", "0.749", "0.703", "0.855", "0.875"]], [4.1, 1.7, 1.7, 1.5, 1.5, 1.7, 1.8])
    add_body(doc, "相较 BM25-only，Hybrid + coverage 的 hit@6 提升 24.2 个百分点，recall@6 提升 23.4 个百分点，MRR 提升 24.8 个百分点，citation precision 提升 17.1 个百分点，grounded rate 提升 25.8 个百分点。说明语义召回与词面召回结合后，能更稳定地定位课程证据。")
    add_heading(doc, "5.2 失败案例与阈值分析", 2)
    add_bullets(doc, ["检索未命中主要来自中英术语不对齐和跨页综合题。", "正式集有 11/62 个可答题被保守拒答，说明默认阈值仍有调整空间。", "不可答题的拒答表现整体较好，但应继续关注拒答漏判与过度拒答的平衡。", "cross-encoder 能提升 citation precision 和 grounded rate，但增加额外模型依赖，因此默认保留轻量 coverage。"])
    add_heading(doc, "5.3 LLM-as-judge 冒烟实验", 2)
    add_table(doc, ["指标", "结果"], [["judge score", "0.80"], ["citation precision", "0.80"], ["grounded rate", "0.80"], ["refusal accuracy", "1.00"], ["平均延迟", "16,659 ms"]], [7.0, 8.0])

    add_heading(doc, "6. 目标场景评估", 1)
    add_heading(doc, "6.1 用户研究协议", 2)
    add_body(doc, "协议设计为 5–8 名同课程或相关课程同学，每人完成 covered、partial、uncovered、cross 和 own 五类问题，并分别体验 lecture_only 与 lecture_plus_web 两种模式。每题记录解决情况、是否查看引用、是否采纳答案、是否希望外部解释、1–5 分有用性/信任/满意度以及来源归属。")
    add_heading(doc, "6.2 数据状态", 2)
    add_table(doc, ["文件", "用途", "状态"], [["eval/user_study_results.csv", "真实用户研究记录模板", "等待真实采样"], ["eval/user_study_results_simulated.csv", "流程演练用合成数据", "已保留，不作为真实证据"], ["docs/USER_STUDY.md", "研究协议与字段说明", "已完成"]], [6.5, 6.5, 4.0])
    add_body(doc, "项目已完成用户研究的协议、字段设计和分析流程，但当前没有把合成数据冒充真实参与者结果。正式报告应在真实采样后更新本节，并明确报告样本量、任务设置和局限。")

    add_heading(doc, "7. 工程交付与团队分工", 1)
    add_table(doc, ["成员", "负责模块", "对应产物"], [["A", "PDF 解析、分块、向量库、重排", "prompts/01–02、src/lectureqa/ingest、retrieval"], ["B", "提示工程、引用约束、Quiz", "prompts/03–04、src/lectureqa/generation"], ["C", "Streamlit、页码跳转、系统集成", "prompts/05、app/streamlit_app.py"], ["D", "测试集、实验、报告、用户研究", "prompts/06、eval、docs"]], [3.0, 7.0, 7.0])
    add_heading(doc, "7.1 交付清单", 2)
    add_bullets(doc, ["Product：Streamlit 应用、FastAPI 服务和 CLI。", "Technical report：本报告及架构、评估、用户研究协议。", "Evaluation：正式测试集、消融实验、阈值敏感性和报告。", "Presentation：5–7 分钟答辩演示，包含产品行为、实验结果、局限和分工。"])

    add_heading(doc, "8. 局限、风险与下一步", 1)
    add_heading(doc, "8.1 当前局限", 2)
    add_bullets(doc, ["扫描版 PDF 尚未覆盖 OCR，复杂公式和图表理解有限。", "多轮追问上下文仍然偏浅。", "引用精度仍低于理想水平，并存在可答题过度拒答。", "网络补充依赖外部服务，内容时效性与可用性需要单独管理。", "真实用户研究尚未完成，当前合成数据只能用于流程演练。"])
    add_heading(doc, "8.2 下一步", 2)
    add_bullets(doc, ["按协议完成 5–8 名真实同学的目标场景测试。", "根据真实反馈优化引用可见性、拒答解释和网络模式切换。", "扫描 PDF 增加 OCR 与图表解析。", "继续调节 MIN_EVIDENCE_SCORE，减少可答题过度拒答。", "准备正式全量 LLM-as-judge 和 3–5 分钟演示视频。"])

    add_heading(doc, "附录 A：演示脚本", 1)
    add_table(doc, ["时间", "动作", "要强调的点"], [["0:00–0:40", "问题与用户需求", "答案来源和页码可核对"], ["0:40–1:20", "课程地图与单讲学习", "学习闭环而非聊天框"], ["1:20–2:30", "课程问答 + 页码跳转", "引用落到具体页面"], ["2:30–3:10", "讲义未覆盖问题", "明确拒答"], ["3:10–4:00", "网络补充与来源标签", "外部内容不混入讲义结论"], ["4:00–5:00", "Quiz 与实验结果", "可溯源练习 + meaningful evaluation"]], [3.0, 7.0, 7.0])
    add_heading(doc, "附录 B：复现实验命令", 1)
    for command in ["streamlit run app/streamlit_app.py", "lectureqa ingest", "lectureqa eval --testset eval/testset.sample.jsonl -k 6", ".venv/bin/python scripts/run_eval_suite.py --only main", "python -m pytest -q", "ruff check ."]:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(1)
        r = p.add_run(command)
        r.font.name = "Menlo"
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor.from_string(NAVY)
    doc.save(DOCS / "LectureQA技术报告.docx")


# ---------- PowerPoint helpers ----------
def rgb(hex_color):
    return PptColor.from_string(hex_color)


def add_full_bg(slide, color=NAVY):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    shape.fill.solid(); shape.fill.fore_color.rgb = rgb(color); shape.line.fill.background()
    slide.shapes._spTree.remove(shape._element)
    slide.shapes._spTree.insert(2, shape._element)


def textbox(slide, text, x, y, w, h, size=20, color=INK, bold=False, align=PP_ALIGN.LEFT, font="Aptos", margin=0.04):
    box = slide.shapes.add_textbox(PptInches(x), PptInches(y), PptInches(w), PptInches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True
    tf.margin_left = PptInches(margin); tf.margin_right = PptInches(margin); tf.margin_top = PptInches(margin); tf.margin_bottom = PptInches(margin)
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text; r.font.name = font; r.font.size = PptPt(size); r.font.bold = bold; r.font.color.rgb = rgb(color)
    return box


def add_footer(slide, number, dark=False):
    color = "B8C7D9" if dark else MUTED
    textbox(slide, "LECTUREQA  ·  DSC6021 GENERATIVE AI", 0.55, 7.12, 5.5, 0.22, 8, color, True)
    textbox(slide, f"{number:02d}", 12.25, 7.12, 0.65, 0.22, 8, color, True, PP_ALIGN.RIGHT)


def add_title(slide, kicker, title, subtitle=None, dark=False):
    color = WHITE if dark else NAVY
    accent = ORANGE if dark else BLUE
    textbox(slide, kicker.upper(), 0.7, 0.46, 5.2, 0.28, 10, accent, True)
    textbox(slide, title, 0.68, 0.88, 11.3, 0.75, 29, color, True)
    if subtitle:
        textbox(slide, subtitle, 0.72, 1.66, 11.0, 0.45, 13, "D7E3F0" if dark else MUTED)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, PptInches(0.7), PptInches(2.22), PptInches(0.8), PptInches(0.06))
    bar.fill.solid(); bar.fill.fore_color.rgb = rgb(accent); bar.line.fill.background()


def card(slide, x, y, w, h, title, body, accent=BLUE, dark=False):
    fill = "183B5B" if dark else "FFFFFF"
    line = "315B7D" if dark else "D9E2EC"
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, PptInches(x), PptInches(y), PptInches(w), PptInches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = rgb(fill); shape.line.color.rgb = rgb(line); shape.line.width = PptPt(1)
    stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, PptInches(x), PptInches(y), PptInches(0.08), PptInches(h))
    stripe.fill.solid(); stripe.fill.fore_color.rgb = rgb(accent); stripe.line.fill.background()
    textbox(slide, title, x+0.25, y+0.18, w-0.45, 0.34, 15, WHITE if dark else NAVY, True)
    textbox(slide, body, x+0.25, y+0.65, w-0.45, h-0.8, 11, "D7E3F0" if dark else INK)


def stat(slide, x, y, value, label, accent=BLUE, dark=False):
    textbox(slide, value, x, y, 1.8, 0.55, 27, accent, True)
    textbox(slide, label, x, y+0.57, 2.2, 0.38, 10, "D7E3F0" if dark else MUTED)


def build_pptx():
    global prs
    prs = Presentation()
    prs.slide_width = PptInches(13.333)
    prs.slide_height = PptInches(7.5)
    blank = prs.slide_layouts[6]

    # 1 cover
    s = prs.slides.add_slide(blank); add_full_bg(s)
    textbox(s, "DSC6021  ·  GENERATIVE AI", 0.78, 0.66, 6, 0.3, 11, ORANGE, True)
    textbox(s, "LectureQA", 0.72, 1.45, 8.0, 0.9, 44, WHITE, True)
    textbox(s, "面向课程复习的来源感知生成式学习助手", 0.78, 2.48, 8.8, 0.52, 22, "D7E3F0", True)
    textbox(s, "Product / Application Route  ·  Final Presentation", 0.8, 3.2, 7.2, 0.3, 13, "B8C7D9")
    card(s, 0.78, 5.15, 3.1, 1.0, "核心主张", "不是更会聊天，而是让复习答案可核对、来源可分清。", ORANGE, True)
    textbox(s, "2026  ·  Team Presentation", 0.8, 6.75, 5, 0.25, 9, "B8C7D9")
    add_footer(s, 1, True)

    # 2 problem
    s = prs.slides.add_slide(blank); add_full_bg(s, PALE); add_title(s, "01  Problem", "复习时，学生真正缺的不是答案", "而是答案的边界、依据与可核对性")
    card(s, 0.75, 2.75, 3.75, 2.4, "通用聊天机器人", "回答流畅，但课程范围不清楚\n外部知识容易混入\n引用不一定能回到讲义", ORANGE)
    card(s, 4.8, 2.75, 3.75, 2.4, "纯关键词搜索", "能找到词，但缺少解释\n无法完成跨页总结\n没有自测与学习闭环", BLUE)
    card(s, 8.85, 2.75, 3.75, 2.4, "LectureQA", "课程优先\n页码可核对\n证据不足时拒答\n可生成带出处的练习题", TEAL)
    textbox(s, "产品机会：把“回答”升级为“有来源边界的学习过程”", 0.8, 6.15, 11.7, 0.38, 19, NAVY, True, PP_ALIGN.CENTER)
    add_footer(s, 2)

    # 3 users
    s = prs.slides.add_slide(blank); add_full_bg(s, WHITE); add_title(s, "02  Users", "为课程复习设计，而不是做通用聊天框", "围绕学生的真实复习动作组织产品")
    card(s, 0.75, 2.65, 3.7, 2.5, "查概念", "“这个概念在讲义哪一页？”\n“老师是怎么定义它的？”", BLUE)
    card(s, 4.8, 2.65, 3.7, 2.5, "辨边界", "“这是课程内容，还是外部补充？”\n“讲义没有讲，系统会不会硬答？”", TEAL)
    card(s, 8.85, 2.65, 3.7, 2.5, "做练习", "“我能不能先自测？”\n“这道题的答案能回到哪一页？”", ORANGE)
    textbox(s, "核心需求", 0.8, 5.78, 1.5, 0.3, 12, BLUE, True)
    textbox(s, "可信答疑  ·  出处跳转  ·  诚实拒答  ·  可溯源 Quiz", 2.25, 5.72, 9.5, 0.42, 18, NAVY, True)
    add_footer(s, 3)

    # 4 product loop
    s = prs.slides.add_slide(blank); add_full_bg(s, NAVY); add_title(s, "03  Product", "一个从课程地图到自测的学习闭环", "首页不是聊天框，而是学生进入课程的起点", True)
    steps = [("01", "课程首页", "地图 / 目标 / 进度", BLUE), ("02", "讲义学习", "概览 / 问答 / 自测", TEAL), ("03", "课程练习", "先答题 / 再看出处", ORANGE), ("04", "全课程问答", "比较 / 总结 / 追问", BLUE)]
    for i, (num, title, body, accent) in enumerate(steps):
        x = 0.8 + i*3.05
        circle = s.shapes.add_shape(MSO_SHAPE.OVAL, PptInches(x), PptInches(2.9), PptInches(0.58), PptInches(0.58))
        circle.fill.solid(); circle.fill.fore_color.rgb = rgb(accent); circle.line.fill.background()
        textbox(s, num, x, 3.05, 0.58, 0.18, 10, WHITE, True, PP_ALIGN.CENTER)
        textbox(s, title, x, 3.85, 2.5, 0.3, 16, WHITE, True)
        textbox(s, body, x, 4.35, 2.45, 0.5, 11, "D7E3F0")
        if i < 3:
            textbox(s, "→", x+2.45, 3.13, 0.4, 0.35, 24, "B8C7D9", True, PP_ALIGN.CENTER)
    textbox(s, "删除 var/learning/ 下的缓存文件即可重置，不需要数据库", 0.8, 6.25, 11, 0.3, 11, "B8C7D9")
    add_footer(s, 4, True)

    # 5 architecture
    s = prs.slides.add_slide(blank); add_full_bg(s, WHITE); add_title(s, "04  Architecture", "从 PDF 到可核对答案的证据链", "每一步都服务于“来源可验证”")
    stages = [("PDF", "按页抽取", BLUE), ("Chunks", "不跨页分块", TEAL), ("Retrieve", "向量 + BM25", ORANGE), ("Ground", "证据充分性", BLUE), ("Generate", "带引用生成", TEAL), ("Validate", "引用校验", ORANGE)]
    for i, (top, bottom, accent) in enumerate(stages):
        x = 0.62 + i*2.08
        shape = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, PptInches(x), PptInches(3.0), PptInches(1.55), PptInches(1.2))
        shape.fill.solid(); shape.fill.fore_color.rgb = rgb("F7FAFC"); shape.line.color.rgb = rgb(accent)
        textbox(s, top, x, 3.26, 1.55, 0.25, 14, accent, True, PP_ALIGN.CENTER)
        textbox(s, bottom, x+0.08, 3.7, 1.4, 0.25, 10, INK, False, PP_ALIGN.CENTER)
        if i < 5: textbox(s, "→", x+1.62, 3.38, 0.35, 0.3, 19, MUTED, True, PP_ALIGN.CENTER)
    card(s, 1.0, 5.1, 3.45, 1.0, "按页分块", "chunk_id = doc_id:p{page}:c{idx}", BLUE)
    card(s, 4.95, 5.1, 3.45, 1.0, "证据不足", "低于 MIN_EVIDENCE_SCORE 直接拒答", ORANGE)
    card(s, 8.9, 5.1, 3.45, 1.0, "外部补充", "网络来源单独校验、单独标注", TEAL)
    add_footer(s, 5)

    # 6 source modes
    s = prs.slides.add_slide(blank); add_full_bg(s, PALE); add_title(s, "05  Source Control", "两种模式，让学生掌握知识边界", "网络不是默认答案，而是明确开启的补充")
    card(s, 0.85, 2.65, 5.45, 2.65, "仅课程材料  ·  Lecture only", "✓ 回答必须由课程证据支持\n✓ 证据不足时明确拒答\n✓ 适合考试范围内复习\n\n目标：可信、保守、可核对", BLUE)
    card(s, 7.0, 2.65, 5.45, 2.65, "课程材料 + 网络补充", "✓ 讲义不足时才触发网络\n✓ 外部答案与讲义引用分开展示\n✓ 附外部链接和来源标签\n\n目标：拓展背景、不混淆来源", TEAL)
    textbox(s, "关键交互：学生知道“这句话从哪里来”", 0.8, 6.08, 11.7, 0.4, 20, NAVY, True, PP_ALIGN.CENTER)
    add_footer(s, 6)

    # 7 demo
    s = prs.slides.add_slide(blank); add_full_bg(s, NAVY); add_title(s, "06  Demo", "三分钟走完一次可信复习", "建议现场按以下顺序演示", True)
    demo = [("01", "讲义覆盖问题", "展示回答 + p.N 页码 + 原文片段", BLUE), ("02", "页码跳转", "点击引用，右侧课件定位到对应页", TEAL), ("03", "讲义未覆盖", "仅讲义模式拒答，不调用模型硬猜", ORANGE), ("04", "网络补充", "打开开关，外部内容单独标记", BLUE), ("05", "Quiz 自测", "先答题，再展开答案和出处", TEAL)]
    for i, (num, title, body, accent) in enumerate(demo):
        y = 2.55 + i*0.78
        textbox(s, num, 0.9, y, 0.55, 0.25, 12, accent, True)
        textbox(s, title, 1.7, y, 2.5, 0.25, 14, WHITE, True)
        textbox(s, body, 4.45, y, 7.5, 0.25, 12, "D7E3F0")
        line = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, PptInches(1.7), PptInches(y+0.48), PptInches(10.2), PptInches(0.012))
        line.fill.solid(); line.fill.fore_color.rgb = rgb("315B7D"); line.line.fill.background()
    add_footer(s, 7, True)

    # 8 evaluation
    s = prs.slides.add_slide(blank); add_full_bg(s, WHITE); add_title(s, "07  Evaluation", "我们测量的不是“看起来不错”", "而是检索、引用、拒答和真实使用价值")
    stat(s, 0.85, 2.65, "72", "正式测试题", BLUE)
    stat(s, 3.15, 2.65, "10", "不可答题", ORANGE)
    stat(s, 5.45, 2.65, "10", "课程讲义", TEAL)
    stat(s, 7.75, 2.65, "4", "核心研究问题", BLUE)
    card(s, 0.85, 4.25, 2.75, 1.4, "RQ1 召回", "hit@k · recall@k · MRR", BLUE)
    card(s, 3.8, 4.25, 2.75, 1.4, "RQ2 依据", "citation precision · grounded", TEAL)
    card(s, 6.75, 4.25, 2.75, 1.4, "RQ3 拒答", "refusal accuracy", ORANGE)
    card(s, 9.7, 4.25, 2.75, 1.4, "RQ4 体验", "judge · latency · user study", BLUE)
    add_footer(s, 8)

    # 9 results
    s = prs.slides.add_slide(blank); add_full_bg(s, PALE); add_title(s, "08  Results", "Hybrid 检索显著优于 BM25-only", "语义召回 + 词面召回让课程证据更稳定")
    headers = ["指标", "Hybrid + coverage", "BM25-only", "提升"]
    rows = [("hit@6", "0.919", "0.677", "+24.2pp"), ("recall@6", "0.887", "0.653", "+23.4pp"), ("MRR", "0.752", "0.504", "+24.8pp"), ("citation precision", "0.676", "0.505", "+17.1pp"), ("grounded rate", "0.806", "0.548", "+25.8pp")]
    for j, h in enumerate(headers):
        textbox(s, h, 0.9 + [0,2.7,5.35,8.0][j], 2.65, [2.3,2.0,2.0,2.5][j], 0.3, 12, NAVY, True)
    for i, row in enumerate(rows):
        y = 3.2 + i*0.56
        line = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, PptInches(0.88), PptInches(y-0.1), PptInches(10.7), PptInches(0.42))
        line.fill.solid(); line.fill.fore_color.rgb = rgb(WHITE if i%2==0 else "E6EEF5"); line.line.fill.background()
        for j, value in enumerate(row):
            color = TEAL if j == 3 else INK
            textbox(s, value, 0.95 + [0,2.7,5.35,8.0][j], y, [2.3,2.0,2.0,2.5][j], 0.22, 12, color, j in (0,3))
    textbox(s, "结论：Hybrid + coverage 在召回和 groundedness 上都带来实质提升。", 0.9, 6.35, 11.0, 0.3, 16, NAVY, True)
    add_footer(s, 9)

    # 10 ablation
    s = prs.slides.add_slide(blank); add_full_bg(s, WHITE); add_title(s, "09  Trade-offs", "更强的重排，换来更高成本", "默认方案在效果、依赖和延迟之间保持平衡")
    card(s, 0.85, 2.7, 3.65, 2.35, "BM25-only", "成本低、依赖少\n但语义召回弱\ngrounded rate 0.548", ORANGE)
    card(s, 4.85, 2.7, 3.65, 2.35, "Hybrid + coverage", "默认方案\n轻量、可解释\ngrounded rate 0.806", TEAL)
    card(s, 8.85, 2.7, 3.65, 2.35, "Cross-encoder", "citeP 0.703\ngrounded 0.855\n但增加模型依赖", BLUE)
    textbox(s, "设计选择：默认使用 coverage；有更高质量需求时再切换 cross-encoder", 0.85, 5.85, 11.4, 0.38, 17, NAVY, True, PP_ALIGN.CENTER)
    add_footer(s, 10)

    # 11 user study status
    s = prs.slides.add_slide(blank); add_full_bg(s, PALE); add_title(s, "10  User Study", "目标场景评估：协议和分析流程已准备", "真实采样与模拟演练严格分开")
    card(s, 0.85, 2.65, 5.45, 2.45, "已完成", "✓ 5 类任务设计\n✓ 两种来源模式\n✓ 记录字段与评分量表\n✓ 模拟数据分析流程\n✓ 真实研究空白模板", TEAL)
    card(s, 7.0, 2.65, 5.45, 2.45, "待完成", "□ 招募 5–8 名同学\n□ 每人约 20–25 分钟\n□ 记录有用性、信任、引用查看\n□ 填写真实结果并替换模板\n□ 报告真实局限", ORANGE)
    textbox(s, "模拟数据保存在 eval/user_study_results_simulated.csv，不作为真实用户证据", 0.9, 5.95, 11.6, 0.3, 13, NAVY, True, PP_ALIGN.CENTER)
    add_footer(s, 11)

    # 12 limitations
    s = prs.slides.add_slide(blank); add_full_bg(s, NAVY); add_title(s, "11  Limits", "我们知道系统还不完美", "把边界说清楚，也是来源感知产品的一部分", True)
    limits = [("检索", "中英术语不对齐、跨页综合题可能漏召回", BLUE), ("生成", "可答题存在保守拒答，引用精度仍可提升", ORANGE), ("文档", "扫描 PDF 的 OCR、公式和图表理解有限", TEAL), ("评估", "真实用户研究尚待完成，小样本不能外推", BLUE)]
    for i, (title, body, accent) in enumerate(limits):
        x = 0.85 + (i%2)*6.15; y = 2.65 + (i//2)*1.55
        card(s, x, y, 5.45, 1.2, title, body, accent, True)
    textbox(s, "下一步：真实用户采样 · OCR / 图表理解 · 阈值调优 · 全量 judge", 0.85, 6.25, 11.6, 0.3, 13, "D7E3F0", True, PP_ALIGN.CENTER)
    add_footer(s, 12, True)

    # 13 close
    s = prs.slides.add_slide(blank); add_full_bg(s, BLUE)
    textbox(s, "LectureQA", 0.8, 1.3, 6.5, 0.75, 40, WHITE, True)
    textbox(s, "让课程复习答案可核对、来源可分清。", 0.85, 2.35, 9.6, 0.48, 24, WHITE, True)
    textbox(s, "Useful when it answers. Trustworthy when it knows its boundaries.", 0.88, 3.2, 8.8, 0.3, 13, "D7E3F0")
    textbox(s, "Thank you", 0.85, 5.8, 4, 0.4, 20, ORANGE, True)
    textbox(s, "Q&A", 10.4, 5.55, 2.0, 0.6, 28, WHITE, True, PP_ALIGN.RIGHT)
    add_footer(s, 13, True)
    prs.save(DOCS / "LectureQA答辩演示.pptx")


if __name__ == "__main__":
    build_docx()
    build_pptx()
    print("Built polished DOCX and PPTX in docs/")
