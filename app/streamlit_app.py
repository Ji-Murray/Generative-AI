"""LectureQA 前端（Streamlit）：课程首页 → 讲义学习 → 练习，形成学习闭环。

启动：streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from lectureqa.config import get_settings  # noqa: E402
from lectureqa.generation.qa import MARKER_RE, display_answer  # noqa: E402
from lectureqa.ingest.pdf import PDFError, render_page_png  # noqa: E402
from lectureqa.learning.outline import parse_topic_span  # noqa: E402
from lectureqa.learning.progress import grade_quiz_answer  # noqa: E402
from lectureqa.schemas import LectureOutline, QuizAttempt, QuizSource  # noqa: E402
from lectureqa.service import LectureQAService  # noqa: E402

st.set_page_config(page_title="LectureQA · 课程学习", page_icon="📚", layout="wide")

PAGES = {
    "home": "🏠 课程首页",
    "lecture": "📖 讲义学习",
    "quiz": "📝 练习 / 错题",
    "chat": "💬 全课程问答",
    "dev": "🛠 课程管理",
}

STATUS_LABEL = {"not_started": "未开始", "learning": "学习中", "completed": "已完成"}
STATUS_ICON = {"not_started": "⚪", "learning": "🟡", "completed": "🟢"}


APP_CSS = """
<style>
:root {
  --ink: #172033;
  --muted: #727c8d;
  --line: #e3e7ed;
  --paper: #f4f5f3;
  --surface: #fff;
  --accent: #c65b3d;
  --accent-soft: #f8ece7;
  --green: #38715d;
  --green-soft: #e8f1ec;
}
html, body, [class*="css"] { font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif; }
[data-testid="stAppViewContainer"] { background: var(--paper); }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1540px; padding: 1.35rem 2.4rem 3.5rem; }
h1, h2, h3, h4 { color: var(--ink); font-family: "Avenir Next", "PingFang SC", sans-serif; letter-spacing: -.025em; }
h1 { font-size: 2rem !important; font-weight: 700 !important; line-height: 1.18 !important; }
h2 { font-size: 1.35rem !important; margin: 1.5rem 0 .75rem !important; }
h3 { font-size: 1.06rem !important; }
p, li { color: var(--ink); line-height: 1.65; }
[data-testid="stCaptionContainer"] p { color: var(--muted); font-size: .82rem; }
[data-testid="stSidebar"] { background: #202a2d; border-right: 1px solid #344044; min-width: 17rem !important; max-width: 17rem !important; }
@media (max-width: 700px) { [data-testid="stSidebar"] { min-width: min(17rem, 88vw) !important; max-width: min(17rem, 88vw) !important; } }
[data-testid="stSidebar"] * { color: #e8ece9 !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #aebbb6 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.12); }
[data-testid="stSidebar"] [data-baseweb="select"] > div, [data-testid="stSidebar"] [data-baseweb="base-input"] { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.14); }
[data-testid="stSidebar"] .stButton > button { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.15); color: #edf1ee; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: var(--accent) !important; border: 0 !important; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button { min-height: 2.25rem; justify-content: flex-start; gap: .65rem; padding-inline: .75rem; border: 0; border-radius: 6px; background: transparent; color: #bdc8c4; font-size: .86rem; font-weight: 500; text-align: left; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button:hover { background: rgba(255,255,255,.07); color: #fff; border: 0; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button svg { width: 1rem; height: 1rem; color: #95a39e; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button[kind="primary"] { background: rgba(198,91,61,.16) !important; box-shadow: inset 3px 0 0 var(--accent); color:#fff !important; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button[kind="primary"] svg { color:#e6a08e; }
[data-testid="stSidebar"] .st-key-sidebar_navigation { gap: .25rem !important; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button > div { width: 100%; justify-content: flex-start; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button [data-has-shortcut] { justify-content: flex-start; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button p { font-size: .86rem; line-height: 1.4; font-weight: 500; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button[kind="secondary"] { background: transparent !important; border: 0 !important; color: #bdc8c4 !important; }
[data-testid="stSidebar"] .st-key-sidebar_navigation button[kind="secondary"]:hover { background: rgba(255,255,255,.075) !important; }
[data-testid="stSidebar"] hr { margin: .8rem 0 .4rem; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 1rem; }
[data-testid="stSidebar"] [data-baseweb="radio"] > div { gap: .25rem; }
[data-testid="stSidebar"] [data-baseweb="radio"] label { min-height: 2.15rem; padding: .35rem .6rem; border-radius: 6px; font-size: .88rem; font-weight: 500; color: #bdc8c4 !important; }
[data-testid="stSidebar"] [data-baseweb="radio"] label:hover { background: rgba(255,255,255,.06); color: #f3f5f3 !important; }
[data-testid="stSidebar"] [data-baseweb="radio"] label:has(input:checked) { background: rgba(198,91,61,.16); color: #fff !important; box-shadow: inset 3px 0 0 var(--accent); }
[data-testid="stSidebar"] [data-baseweb="radio"] label > div:first-child { width: .85rem; height: .85rem; border: 1px solid #7b8984; background: transparent; }
[data-testid="stSidebar"] [data-baseweb="radio"] label:has(input:checked) > div:first-child { border-color: var(--accent); background: var(--accent); }
[data-testid="stSidebar"] [data-testid="stExpander"] { margin: .35rem 0; }
[data-testid="stSidebar"] [data-testid="stExpander"] details { border: 0; border-top: 1px solid rgba(255,255,255,.1); border-radius: 0; background: transparent; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: .75rem .2rem; color: #aebbb6 !important; font-size: .82rem; font-weight: 600; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { color: #fff !important; background: transparent; }
[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] { padding: .2rem 0 .65rem; }
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button { min-height: 2.1rem; border: 0; border-bottom: 1px solid rgba(255,255,255,.08); border-radius: 0; background: transparent; color: #c5cfcb; font-size: .78rem; text-align: left; }
[data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:hover { background: rgba(255,255,255,.06); border-color: transparent; }
[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stFileUploader"] { padding: .35rem 0; }
[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stFileUploaderDropzone"] { border: 1px dashed rgba(255,255,255,.2); border-radius: 6px; background: rgba(255,255,255,.03); }
[data-testid="stSidebar"] [data-testid="stExpander"] [data-baseweb="select"] > div, [data-testid="stSidebar"] [data-testid="stExpander"] [data-baseweb="slider"] { background: rgba(255,255,255,.05); }
[data-testid="stMetric"] { padding: .7rem .9rem; background: transparent; border: 0; border-left: 2px solid var(--line); border-radius: 0; box-shadow: none; }
[data-testid="stMetricLabel"] p { color: var(--muted) !important; font-size: .78rem; font-weight: 600; }
[data-testid="stMetricValue"] { color: var(--ink); font-size: 1.5rem; font-weight: 650; font-variant-numeric: tabular-nums; }
div[data-testid="stVerticalBlockBorderWrapper"] { border: 1px solid var(--line); border-radius: 10px; background: var(--surface); box-shadow: none; }
.stButton > button { min-height: 2.4rem; border-radius: 7px; font-weight: 600; transition: background-color .15s ease, border-color .15s ease; }
.stButton > button:hover { border-color: #a8b0b8; box-shadow: none; transform: none; }
.stButton > button[kind="primary"] { background: var(--accent) !important; border-color: var(--accent) !important; }
.stButton > button[kind="primary"]:hover { background: #aa4c33 !important; }
button[kind="tertiary"] { color: var(--accent) !important; font-weight: 600; }
[data-testid="stChatMessage"] { border: 1px solid var(--line); border-radius: 10px; margin: .55rem 0; background: #fff; box-shadow: none; }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] { line-height: 1.75; }
[data-testid="stChatInput"] > div { border-radius: 9px; }
[data-baseweb="tab-list"] { gap: .2rem; border-bottom: 1px solid var(--line); }
button[data-baseweb="tab"] { font-weight: 600; padding: .55rem .8rem; }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--accent); }
[data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }
[data-testid="stExpander"] details { border-radius: 8px; border-color: var(--line); }
.workspace-header { display:flex; align-items:flex-end; justify-content:space-between; gap:1.5rem; padding:.8rem 0 1.15rem; border-bottom:1px solid #d9dedb; margin-bottom:1.4rem; }
.page-kicker { color:var(--accent); font-size:.67rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; margin-bottom:.35rem; }
.page-lede { color:var(--muted); font-size:.94rem; margin:.15rem 0 1rem; line-height:1.6; max-width:780px; }
.dashboard-greeting { padding:.2rem 0 .95rem; border-bottom:1px solid #d9dedb; margin-bottom:1rem; }
.dashboard-greeting h1 { margin:.15rem 0 .2rem !important; }
.dashboard-greeting p { color:var(--muted); margin:0; font-size:.92rem; }
.resume-panel { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:1.15rem 1.35rem; border-radius:10px; background:#e9eee8; border:1px solid #d9e1d8; margin:.25rem 0 1.2rem; }
.resume-label { color:var(--green); font-size:.68rem; font-weight:700; letter-spacing:.11em; text-transform:uppercase; }
.resume-title { margin:.32rem 0 .16rem; color:var(--ink); font-size:1.18rem; font-weight:700; }
.resume-meta { color:var(--muted); font-size:.82rem; }
.resume-progress { width:132px; flex:0 0 132px; }
.resume-progress-label { display:flex; justify-content:space-between; color:var(--muted); font-size:.7rem; margin-bottom:.35rem; }
.resume-track { height:5px; background:#d3ddd4; border-radius:99px; overflow:hidden; }
.resume-fill { height:100%; background:var(--green); border-radius:99px; }
.dashboard-tools { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:1.4rem 0 .65rem; }
.dashboard-tools h2 { margin:0 !important; }
.course-row { display:flex; align-items:center; gap:.85rem; padding:.7rem .8rem; border-bottom:1px solid #edf0ed; }
.course-row:last-child { border-bottom:0; }
.course-number { display:flex; flex:0 0 2.25rem; align-items:center; justify-content:center; color:#737d79; font-size:.78rem; font-weight:700; font-variant-numeric:tabular-nums; }
.course-main { flex:1; min-width:0; }
.course-title { color:var(--ink); font-size:.93rem; font-weight:650; line-height:1.4; overflow-wrap:anywhere; }
.course-meta { color:var(--muted); font-size:.74rem; margin-top:.2rem; }
.course-state { flex:0 0 auto; font-size:.72rem; font-weight:650; white-space:nowrap; }
.course-state.learning { color:#a34f36; }
.course-state.completed { color:var(--green); }
.course-state.not_started { color:#828b91; }
.course-action { flex:0 0 112px; }
.status-pill { display:inline-block; padding:.22rem .55rem; border-radius:999px; font-size:.74rem; font-weight:650; }
.status-pill.learning { background:#f8eee8; color:#a34f36; }
.status-pill.completed { background:var(--green-soft); color:var(--green); }
.status-pill.not_started { background:#edf0ee; color:#65706b; }
.chip-row { display:flex; flex-wrap:wrap; gap:.35rem; margin:.35rem 0 .2rem; }
.chip { padding:.2rem .52rem; border-radius:6px; font-size:.75rem; font-weight:600; color:#47534e; background:#f1f3f1; }
.lecture-index { display:inline-flex; align-items:center; justify-content:center; min-width:2.3rem; height:2.3rem; padding:0 .5rem; border-radius:8px; background:var(--accent-soft); color:var(--accent); font-weight:700; font-size:.9rem; }
@media (max-width:900px) {
 .block-container { padding:1rem 1rem 2.5rem; }
 .resume-panel { align-items:flex-start; flex-direction:column; }
 .resume-progress { width:100%; flex-basis:auto; }
 .dashboard-tools { align-items:stretch; flex-direction:column; }
 .course-row { flex-wrap:wrap; }
 .course-action { flex:1 1 100%; margin-inline-start:3.05rem; }
}
@media (max-width:620px) {
 [data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; row-gap:.65rem !important; }
 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width:100% !important; flex:1 1 100% !important; }
 .course-row { gap:.55rem; padding:.65rem .35rem; }
 .course-main { flex-basis:calc(100% - 3rem); }
 .course-state, .course-action { margin-inline-start:2.8rem; }
}
</style>
"""


def render_app_styles() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-kicker">{kicker}</div>'
        f"<h1 style='margin:.45rem 0 .2rem'>{title}</h1>"
        + (f'<p class="page-lede">{subtitle}</p>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def status_pill(status: str) -> str:
    return (
        f'<span class="status-pill {status}">{STATUS_ICON.get(status, "⚪")} '
        f'{escape(STATUS_LABEL.get(status, status))}</span>'
    )


@st.cache_resource(show_spinner=False)
def get_service() -> LectureQAService:
    return LectureQAService(get_settings())


@st.cache_data(show_spinner=False)
def load_page_png(source_path: str, page: int, dpi: int = 144) -> bytes | None:
    """缓存单页 PNG；路径变化（上传哈希目录）会自动失效。"""
    if not source_path or page < 1:
        return None
    try:
        return render_page_png(source_path, page, dpi=dpi)
    except PDFError:
        return None


@st.cache_data(show_spinner=False)
def load_pdf_bytes(source_path: str) -> bytes | None:
    path = Path(source_path) if source_path else None
    if path is None or not path.is_file():
        return None
    return path.read_bytes()


def topic_page(topic: str) -> int | None:
    span = parse_topic_span(topic)
    return span[0] if span else None


def topic_span_label(topic: str) -> str:
    span = parse_topic_span(topic)
    if span is None:
        return "查看"
    start, end = span
    return f"p.{start}" if start == end else f"p.{start}-{end}"


def preview_key(scope: str) -> str:
    return f"slide_preview_{scope}"


def loading_key(scope: str) -> str:
    return f"pdf_loading_{scope}"


def jump_nonce_key(scope: str) -> str:
    return f"pdf_jump_nonce_{scope}"


def set_preview(scope: str, doc_id: str, page: int) -> None:
    previous = get_preview(scope)
    target = {"doc_id": doc_id, "page": int(page)}
    st.session_state[preview_key(scope)] = target
    changed = previous is None or previous.get("doc_id") != doc_id or int(previous.get("page", -1)) != int(page)
    if changed:
        st.session_state[loading_key(scope)] = True
        st.session_state[jump_nonce_key(scope)] = int(st.session_state.get(jump_nonce_key(scope), 0)) + 1


def get_preview(scope: str) -> dict | None:
    value = st.session_state.get(preview_key(scope))
    if isinstance(value, dict) and value.get("doc_id") and value.get("page"):
        return value
    return None


def _attach_markers_to_text(text: str) -> str:
    """把单独成行的 [[doc:pN]] 贴回上一段末尾，避免出处和正文纵向脱节。"""
    if not text:
        return ""
    # 标记前多余空行压成空格，让页码跟段落走
    cleaned = re.sub(
        r"(\S)[ \t]*\n+[ \t]*(?=\[\[(?:doc_id\s*[=:]\s*)?(?!web\s*:)[^\[\]\s:=]+\s*:\s*p?\s*\d+\s*\]\])",
        r"\1 ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def resolve_preview_target(
    service: LectureQAService,
    scope: str,
    *,
    preferred_doc_ids: list[str] | None = None,
) -> tuple[str, str, int, str]:
    """根据当前跳转状态解析右侧预览该显示哪份课件。"""
    docs = {document.doc_id: document for document in service.documents()}
    if not docs:
        return "", "", 0, ""
    preview = get_preview(scope)
    candidates = list(preferred_doc_ids or []) + list(docs)
    doc_id = None
    if preview and preview.get("doc_id") in docs:
        doc_id = preview["doc_id"]
    else:
        doc_id = next((item for item in candidates if item in docs), next(iter(docs)))
    document = docs[doc_id]
    return (
        doc_id,
        document.source_path,
        int(document.pages or 0),
        document.doc_title or doc_id,
    )


def render_split_workspace(
    *,
    service: LectureQAService,
    preview_scope: str,
    preferred_doc_ids: list[str] | None,
    left_render,
) -> None:
    """左栏内容区内滚，右栏课件钉住：问答/练习不再上下堆叠。"""
    inject_pdf_pane_styles()
    left, right = st.columns([1.2, 0.95], gap="large")
    with left:
        st.markdown('<span class="lecture-scroll-marker"></span>', unsafe_allow_html=True)
        left_render()
    with right:
        doc_id, source_path, page_count, title = resolve_preview_target(
            service, preview_scope, preferred_doc_ids=preferred_doc_ids
        )
        if not doc_id:
            st.info("暂无课件可预览。")
            return
        fallback = int((get_preview(preview_scope) or {}).get("page") or 1)
        render_pdf_pane(
            scope=preview_scope,
            doc_id=doc_id,
            source_path=source_path,
            page_count=page_count,
            title=title,
            fallback_page=fallback,
        )


def inject_pdf_pane_styles() -> None:
    """双栏学习页：左侧内容区内滚动，右侧课件始终钉在视口内。"""
    st.markdown(
        """
<style>
/* Streamlit 祖先若 hidden/auto，会让 sticky 失效 */
section.main, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"],
.block-container {
  overflow: visible !important;
}

/* 双栏行：左栏自己滚，右栏钉住，整页不必跟着答案变很长 */
div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker) {
  align-items: stretch !important;
  gap: 0.75rem !important;
}
div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker)
  > div[data-testid="stColumn"]:has(.lecture-scroll-marker),
div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker)
  > div[data-testid="column"]:has(.lecture-scroll-marker) {
  max-height: calc(100vh - 8.5rem) !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  padding-right: 0.25rem;
  scrollbar-gutter: stable;
}
div[data-testid="stColumn"]:has(.pdf-pane-marker),
div[data-testid="column"]:has(.pdf-pane-marker) {
  position: sticky !important;
  top: 1rem !important;
  align-self: flex-start !important;
  z-index: 200 !important;
  max-height: calc(100vh - 8.5rem) !important;
  overflow: hidden !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.pdf-pane-marker) {
  position: relative !important;
  height: calc(100vh - 8.5rem) !important;
  max-height: calc(100vh - 8.5rem) !important;
  overflow: auto !important;
  background: var(--background-color, rgba(14, 17, 23, 0.96));
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.28);
  border-radius: 0.75rem;
}
.pdf-loading-mask {
  position: absolute !important;
  inset: 0 !important;
  z-index: 999 !important;
  display: flex !important;
  align-items: center;
  justify-content: center;
  border-radius: 0.75rem;
  background: rgba(15, 23, 42, 0.52);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  color: #fff;
  text-align: center;
  pointer-events: none;
}
.pdf-loading-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 0.75rem;
  background: rgba(15, 23, 42, 0.55);
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.pdf-loading-card .spin {
  width: 1.6rem;
  height: 1.6rem;
  border: 3px solid rgba(255, 255, 255, 0.25);
  border-top-color: #fff;
  border-radius: 50%;
  animation: pdf-spin 0.7s linear infinite;
}
@keyframes pdf-spin { to { transform: rotate(360deg); } }

/* 窄屏：放弃钉住，改为上下堆叠，避免遮挡正文 */
@media (max-width: 900px) {
  div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker) { flex-direction: column !important; }
  div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker) > div[data-testid="stColumn"],
  div[data-testid="stHorizontalBlock"]:has(.pdf-pane-marker) > div[data-testid="column"] {
    position: relative !important;
    top: auto !important;
    max-height: none !important;
    overflow: visible !important;
    flex: 1 1 100% !important;
    min-width: 100% !important;
  }
  div[data-testid="stVerticalBlockBorderWrapper"]:has(.pdf-pane-marker) {
    height: auto !important;
    max-height: 72vh !important;
    overflow: auto !important;
  }
  div[data-testid="stHorizontalBlock"]:has(.lecture-scroll-marker) > div[data-testid="stColumn"]:has(.lecture-scroll-marker),
  div[data-testid="stHorizontalBlock"]:has(.lecture-scroll-marker) > div[data-testid="column"]:has(.lecture-scroll-marker) {
    max-height: none !important;
    overflow: visible !important;
  }
}

/* 出处页码与正文更贴：压缩横向容器上下空隙 */
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) {
  gap: 0.35rem !important;
  margin-top: 0.15rem !important;
  margin-bottom: 0.35rem !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"])
  > div[data-testid="stColumn"],
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"])
  > div[data-testid="column"] {
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def pin_pdf_pane_in_viewport() -> None:
    """用脚本强制左栏内滚、右栏钉在视口，弥补 Streamlit sticky 偶发失效。"""
    import streamlit.components.v1 as components

    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const TOP = 16;

  function apply() {
    const marker = doc.querySelector('.pdf-pane-marker');
    if (!marker) return;
    const row = marker.closest('[data-testid="stHorizontalBlock"]');
    const right = marker.closest('[data-testid="stColumn"], [data-testid="column"]');
    if (!row || !right) return;

    // 窄屏（平板竖屏 / 手机）改为上下堆叠，不做钉住，避免遮挡与横向挤压
    if (win.innerWidth < 900) {
      right.style.position = '';
      right.style.maxHeight = '';
      right.style.overflow = '';
      right.style.top = '';
      const paneNarrow = marker.closest('[data-testid="stVerticalBlockBorderWrapper"]');
      if (paneNarrow) {
        paneNarrow.style.height = '';
        paneNarrow.style.maxHeight = '';
        paneNarrow.style.overflow = '';
      }
      const leftNarrow = row.querySelector('[data-testid="stColumn"]:has(.lecture-scroll-marker), [data-testid="column"]:has(.lecture-scroll-marker)');
      if (leftNarrow) {
        leftNarrow.style.maxHeight = '';
        leftNarrow.style.overflowY = '';
      }
      return;
    }

    const left = row.querySelector('[data-testid="stColumn"]:has(.lecture-scroll-marker), [data-testid="column"]:has(.lecture-scroll-marker)')
      || Array.from(row.querySelectorAll('[data-testid="stColumn"], [data-testid="column"]')).find((col) => col !== right);
    const avail = Math.max(320, win.innerHeight - 96);

    if (left) {
      left.style.maxHeight = avail + 'px';
      left.style.overflowY = 'auto';
      left.style.overflowX = 'hidden';
    }
    right.style.position = 'sticky';
    right.style.top = TOP + 'px';
    right.style.alignSelf = 'flex-start';
    right.style.maxHeight = avail + 'px';
    right.style.zIndex = '200';
    right.style.overflow = 'hidden';

    const pane = marker.closest('[data-testid="stVerticalBlockBorderWrapper"]');
    if (pane) {
      pane.style.height = avail + 'px';
      pane.style.maxHeight = avail + 'px';
      pane.style.overflow = 'auto';
      pane.style.position = 'relative';
    }
  }

  if (win.__lecturePdfPinTimer) clearInterval(win.__lecturePdfPinTimer);
  apply();
  win.__lecturePdfPinTimer = setInterval(apply, 800);
  win.addEventListener('resize', apply);
  // Streamlit 重绘后稍后再钉一次
  setTimeout(apply, 120);
  setTimeout(apply, 480);
})();
</script>
        """,
        height=0,
    )


def render_slide_image(
    source_path: str, page: int, *, caption: str = "", dpi: int = 144
) -> bool:
    png = load_page_png(source_path, page, dpi=dpi)
    if not png:
        st.caption(f"无法预览第 {page} 页（文件缺失或页码越界）")
        return False
    st.image(png, caption=caption or f"第 {page} 页", use_container_width=True)
    return True


def page_jump_button(
    label: str,
    *,
    scope: str,
    doc_id: str,
    page: int,
    key: str,
    source_path: str = "",
    compact: bool = False,
) -> None:
    """出处/页码按钮：点击后在右侧整份课件预览中定位到对应页。"""
    clicked = st.button(
        label,
        key=key,
        type="tertiary" if compact else "secondary",
        width="content" if compact else "stretch",
        help=f"跳到 {doc_id} 第 {page} 页" if compact else None,
    )
    if clicked:
        set_preview(scope, doc_id, page)
        if source_path and load_pdf_bytes(source_path) is None:
            st.toast("课件文件不可用，无法跳转预览", icon="⚠️")
        st.rerun()


def render_pdf_pane(
    *,
    scope: str,
    doc_id: str,
    source_path: str,
    page_count: int,
    title: str = "",
    height: int = 620,
    fallback_page: int = 1,
) -> None:
    """右侧整份 PPT/PDF 预览：钉在视口内，左侧答案再长也不跟着滚走。"""
    inject_pdf_pane_styles()
    pin_pdf_pane_in_viewport()
    preview = get_preview(scope)
    current = int((preview or {}).get("page") or fallback_page or 1)
    current = min(max(current, 1), page_count) if page_count > 0 else max(current, 1)
    jumping = bool(st.session_state.get(loading_key(scope), False))
    nonce = int(st.session_state.get(jump_nonce_key(scope), 0))

    with st.container(border=True):
        st.markdown('<span class="pdf-pane-marker"></span>', unsafe_allow_html=True)
        st.markdown(f"**课件预览** · {title or doc_id}")
        nav_prev, nav_info, nav_next = st.columns([1, 2.2, 1])
        with nav_prev:
            if st.button(
                "← 上一页",
                key=f"{scope}_pdf_prev",
                use_container_width=True,
                disabled=current <= 1,
            ):
                set_preview(scope, doc_id, current - 1)
                st.rerun()
        with nav_info:
            st.caption(
                f"定位第 **{current}** 页" + (f" / 共 {page_count} 页" if page_count else "")
            )
        with nav_next:
            disabled = page_count > 0 and current >= page_count
            if st.button(
                "下一页 →",
                key=f"{scope}_pdf_next",
                use_container_width=True,
                disabled=disabled,
            ):
                set_preview(scope, doc_id, current + 1)
                st.rerun()

        pdf_bytes = load_pdf_bytes(source_path)
        if not pdf_bytes:
            st.session_state[loading_key(scope)] = False
            st.info("找不到课件文件，无法预览整份 PPT。请确认索引里的 source_path 仍指向该 PDF。")
            return

        try:
            from streamlit_pdf_viewer import pdf_viewer

            pdf_viewer(
                pdf_bytes,
                width="100%",
                height=height,
                key=f"{scope}_pdf_{current}_{nonce}",
                scroll_to_page=current,
                scroll_behavior="instant",
                zoom_level="auto",
                viewer_align="center",
                show_page_separator=True,
            )
        except Exception:  # noqa: BLE001 - 预览组件缺失时降级为单页图
            st.caption("整份预览组件不可用，降级为当前页截图。")
            render_slide_image(source_path, current, caption=f"第 {current} 页")

        if jumping:
            import streamlit.components.v1 as components

            # 直接把蒙版挂到预览边框容器上，确保盖住整块区域（含 PDF iframe）
            components.html(
                f"""
                <script>
                (() => {{
                  const doc = window.parent.document;
                  const marker = doc.querySelector('.pdf-pane-marker');
                  const pane = marker && marker.closest('[data-testid="stVerticalBlockBorderWrapper"]');
                  if (!pane) return;
                  pane.querySelectorAll('[data-pdf-loading="1"]').forEach((el) => el.remove());
                  const mask = doc.createElement('div');
                  mask.className = 'pdf-loading-mask';
                  mask.setAttribute('data-pdf-loading', '1');
                  mask.innerHTML = `
                    <div class="pdf-loading-card">
                      <div class="spin"></div>
                      <div>加载中</div>
                      <div style="font-weight:500;opacity:.92">正在跳转到第 {current} 页…</div>
                    </div>`;
                  pane.appendChild(mask);
                  setTimeout(() => {{
                    mask.style.transition = 'opacity 0.25s ease';
                    mask.style.opacity = '0';
                    setTimeout(() => mask.remove(), 280);
                  }}, 1200);
                }})();
                </script>
                """,
                height=0,
            )
        st.session_state[loading_key(scope)] = False


def render_focused_slide(
    *,
    scope: str,
    sources: dict[str, str],
    titles: dict[str, str] | None = None,
    fallback_doc_id: str | None = None,
    fallback_page: int | None = None,
) -> None:
    preview = get_preview(scope)
    doc_id = (preview or {}).get("doc_id") or fallback_doc_id
    page = (preview or {}).get("page") or fallback_page
    if not doc_id or not page:
        return
    path = sources.get(doc_id, "")
    title = (titles or {}).get(doc_id, doc_id)
    st.markdown(f"**正在查看课件 · {title} · 第 {page} 页**")
    render_slide_image(path, int(page), caption=f"{title} · p.{page}")


def save_uploads(files, settings) -> list[Path]:
    """把上传的 PDF 落盘到可配置的 UPLOAD_DIR，用内容哈希避免重名覆盖。"""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    paths: list[Path] = []
    for file in files:
        data = file.getvalue()
        if len(data) > limit:
            raise ValueError(f"{file.name} 超过 {settings.max_upload_mb} MB 限制")
        digest = hashlib.sha1(data).hexdigest()[:12]
        folder = settings.upload_dir / digest
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / Path(file.name).name
        target.write_bytes(data)
        paths.append(target)
    return paths


def scroll_lecture_pane_to_bottom() -> None:
    """回答结束后把左栏滚到对话底部，方便继续追问。"""
    import streamlit.components.v1 as components

    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const marker = doc.querySelector('.lecture-scroll-marker');
  if (!marker) return;
  const left = marker.closest('[data-testid="stColumn"], [data-testid="column"]');
  if (!left) return;
  const go = () => { left.scrollTop = left.scrollHeight; };
  go();
  setTimeout(go, 80);
  setTimeout(go, 320);
})();
</script>
        """,
        height=0,
    )


def render_thinking_status(message: str) -> None:
    """统一的思考/加载提示卡片。"""
    st.markdown(
        f"""
<div class="thinking-card">
  <div class="thinking-spin"></div>
  <div class="thinking-text">{message}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


_STATUS_PROGRESS = {
    "正在准备回答": 0.08,
    "正在扫描本讲课件要点": 0.18,
    "正在组织总结回答": 0.45,
    "正在检索相关课件页": 0.22,
    "讲义证据不足": 0.35,
    "已定位": 0.48,
    "正在生成回答": 0.55,
}


def _status_progress_value(message: str) -> float:
    text = message or ""
    for key, value in _STATUS_PROGRESS.items():
        if key in text:
            return value
    return 0.2


def render_generation_progress(bar, label: str, value: float) -> None:
    """Streamlit 进度条：value∈[0,1]。"""
    bar.progress(max(0.0, min(float(value), 1.0)), text=label)


def goto_lecture(doc_id: str) -> None:
    st.session_state["lecture_doc_id"] = doc_id
    st.session_state["nav"] = "lecture"


def render_cite_chips(
    cites: list[tuple[str, int]],
    *,
    sources: dict[str, str],
    scope: str,
    key_prefix: str,
    caption: str = "相关课件页",
) -> None:
    """紧凑页码条：一眼看到出处，点击即跳右侧预览。"""
    unique: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for doc_id, page in cites:
        key = (doc_id, int(page))
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
    if not unique:
        return
    st.caption(caption)
    with st.container(horizontal=True, vertical_alignment="center", gap="small", wrap=True):
        for index, (doc_id, page) in enumerate(unique):
            page_jump_button(
                f"p.{page}",
                scope=scope,
                doc_id=doc_id,
                page=page,
                key=f"{key_prefix}_chip_{index}_{doc_id}_{page}",
                source_path=sources.get(doc_id, ""),
                compact=True,
            )


def render_answer_body(
    text: str,
    *,
    sources: dict[str, str] | None = None,
    scope: str = "chat",
    key_prefix: str = "ans",
    interactive: bool = False,
) -> None:
    """正文连续阅读；可点出处集中在答案顶部，避免页码把段落纵向拆碎。"""
    raw = _attach_markers_to_text(text or "")
    if interactive and sources is not None and MARKER_RE.search(raw):
        markers = [(m.group(1), int(m.group(2))) for m in MARKER_RE.finditer(raw)]
        render_cite_chips(
            markers,
            sources=sources,
            scope=scope,
            key_prefix=f"{key_prefix}_top",
            caption="出处页码（点一下，右侧课件同步跳转）",
        )
    st.markdown(display_answer(raw))


def render_sources(
    answer,
    sources: dict[str, str],
    *,
    scope: str = "chat",
    key_prefix: str = "src",
) -> None:
    """出处放答案正下方短条；详情默认收起，PPT 始终在右侧对照。"""
    if answer.external_sources:
        st.warning(
            "以下内容来自**网络补充**，不属于课程讲义。讲义中没有足够证据支持该问题，"
            "请自行核对下列来源。"
        )
        for source in answer.external_sources:
            with st.expander(f"🌐 {source.title}（网络来源）", expanded=False):
                st.markdown(f"[{source.url}]({source.url})")
                st.caption(source.snippet)

    if answer.citations:
        with st.expander(
            f"出处原文（{len(answer.citations)} 处，需要核对时再展开）", expanded=False
        ):
            for index, citation in enumerate(answer.citations):
                row = st.columns([4.2, 1.3])
                with row[0]:
                    st.markdown(f"**{citation.doc_title} · p.{citation.page}**")
                    st.caption(f"chunk: `{citation.chunk_id}`")
                    st.markdown(f"> {citation.snippet}")
                    if not citation.valid:  # pragma: no cover - 防御性分支
                        st.warning("该引用未落在检索证据上")
                with row[1]:
                    page_jump_button(
                        f"→ p.{citation.page}",
                        scope=scope,
                        doc_id=citation.doc_id,
                        page=citation.page,
                        key=f"{key_prefix}_citejump_{index}_{citation.doc_id}_{citation.page}",
                        source_path=sources.get(citation.doc_id, ""),
                    )
                if index < len(answer.citations) - 1:
                    st.divider()
    elif answer.evidence and not answer.external_sources:
        st.info("模型未给出可验证的引用；可展开检索证据，点页码看右侧课件。")

    if answer.evidence:
        with st.expander(
            f"检索证据（{len(answer.evidence)} 条，默认收起）", expanded=False
        ):
            st.caption("点「→ p.N」在右侧预览跳转，不必翻到页面底部找 PPT。")
            for rank, item in enumerate(answer.evidence, start=1):
                path = sources.get(item.chunk.doc_id, "")
                cols = st.columns([4.2, 1.3])
                with cols[0]:
                    st.markdown(
                        f"**{rank}. {item.chunk.doc_title} · p.{item.chunk.page}**  "
                        f"`score={item.score:.3f}` `support={item.support:.2f}`"
                    )
                    st.caption(item.chunk.text[:220].replace("\n", " "))
                with cols[1]:
                    page_jump_button(
                        f"→ p.{item.chunk.page}",
                        scope=scope,
                        doc_id=item.chunk.doc_id,
                        page=item.chunk.page,
                        key=f"{key_prefix}_ev_{rank}_{item.chunk.chunk_id}",
                        source_path=path,
                    )


def render_refusal(answer) -> None:
    st.warning(answer.answer)


def sidebar(service: LectureQAService) -> tuple[list[str] | None, int, bool]:
    settings = service.settings
    with st.sidebar:
        st.markdown(
            '<div style="padding:.1rem .65rem .8rem">'
            '<div style="font-weight:700;font-size:1.1rem;color:#f3f4f1">LectureQA</div>'
            '<div style="font-size:.72rem;color:#91a19b;margin-top:.2rem">课程学习工作台</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        nav_labels = {
            "home": "课程首页", "lecture": "讲义学习", "quiz": "练习与错题",
            "chat": "全课程问答", "dev": "课程管理",
        }
        nav_icons = {
            "home": ":material/grid_view:", "lecture": ":material/menu_book:",
            "quiz": ":material/edit_note:", "chat": ":material/chat_bubble_outline:",
            "dev": ":material/folder_open:",
        }
        current_page = st.session_state.get("nav", "home")
        with st.container(key="sidebar_navigation"):
            for page_key, label in nav_labels.items():
                with st.container(key=f"nav_{'active' if page_key == current_page else 'idle'}_{page_key}"):
                    st.button(
                        label, icon=nav_icons[page_key], key=f"navigate_{page_key}",
                        type="primary" if page_key == current_page else "secondary",
                        use_container_width=True, on_click=st.session_state.update,
                        kwargs={"nav": page_key},
                    )
        st.divider()

        with st.expander("课程管理", expanded=not service.indexed):
            uploads = st.file_uploader(
                "上传讲义 PDF（可多选）",
                type=["pdf"],
                accept_multiple_files=True,
                help=f"上传后增量写入索引；文件保存到 {settings.upload_dir}",
            )
            if uploads and st.button("导入上传的 PDF", use_container_width=True, type="primary"):
                with st.spinner("正在解析上传文件并写入索引…"):
                    try:
                        paths = save_uploads(uploads, settings)
                        report = service.ingest(paths, reset=False)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"导入失败：{exc}")
                    else:
                        st.success(
                            f"已导入 {len(paths)} 个文件；当前 {report.documents} 份讲义 / "
                            f"{report.chunks} 块"
                        )
                        if report.skipped:
                            st.warning("；".join(report.skipped))
                        if report.notes:
                            st.info("；".join(report.notes))
                        st.session_state.pop("outline", None)
                        st.cache_resource.clear()
                        st.rerun()

            if st.button("构建 / 重建索引", use_container_width=True):
                with st.spinner("正在解析 PDF 并建立索引…"):
                    try:
                        report = service.ingest()
                    except Exception as exc:  # noqa: BLE001 - 前端需要把失败原因展示给用户
                        st.error(f"索引构建失败：{exc}")
                    else:
                        st.success(
                            f"完成：{report.documents} 份讲义 / {report.chunks} 块，"
                            f"向量化 {report.embedded} 块（{report.elapsed_ms} ms）"
                        )
                        if report.skipped:
                            st.warning("；".join(report.skipped))
                        if report.notes:
                            st.info("；".join(report.notes))
                        st.session_state.pop("outline", None)
                        st.cache_resource.clear()
                        st.rerun()

            if st.button("重新生成课程大纲", use_container_width=True):
                with st.spinner("正在根据课件生成课程地图…"):
                    try:
                        st.session_state["outline"] = service.outline(refresh=True)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"生成失败：{exc}")
                    else:
                        st.success("课程大纲已更新")

        with st.expander("检索设置", expanded=False):
            docs = service.documents()
            doc_ids = None
            if docs:
                titles = {
                    document.doc_id: f"{document.doc_id} · {document.doc_title}"
                    for document in docs
                }
                selected = st.multiselect(
                    "限定讲义（留空 = 全部）",
                    options=list(titles),
                    format_func=lambda value: titles[value],
                )
                doc_ids = selected or None
            top_k = st.slider("证据片段数 top-k", 2, 12, settings.top_k)
            answer_mode = st.radio(
                "回答来源",
                options=["course_only", "course_plus_web"],
                format_func=lambda mode: {
                    "course_only": "仅课程材料",
                    "course_plus_web": "课程材料 + 网络补充",
                }[mode],
                index=0,
                help=(
                    "仅课程材料：证据不足时明确说明材料未覆盖。"
                    "课程材料 + 网络补充：讲义证据不足时尝试网络检索，网络内容与讲义引用分开展示。"
                ),
            )
            allow_web = answer_mode == "course_plus_web"

        with st.expander("环境配置", expanded=False):
            st.caption(
                f"DATA_DIR `{settings.data_dir}`\n\n"
                f"INDEX_DIR `{settings.index_dir}`\n\n"
                f"LEARNING_DIR `{settings.learning_dir}`\n\n"
                f"分块 {settings.chunk_size} / 重叠 {settings.chunk_overlap}\n\n"
                f"重排 `{settings.rerank}` · 证据阈值 {settings.min_evidence_score}\n\n"
                f"网络补充 `{settings.web_fallback}` · LLM API Key "
                f"{'已配置' if settings.llm_configured else '未配置'}"
            )
    return doc_ids, top_k, allow_web


def get_outline(service: LectureQAService):
    outline = st.session_state.get("outline")
    if outline is None:
        with st.spinner("正在根据课件生成课程地图（首次约 10-20 秒）…"):
            outline = service.outline()
            st.session_state["outline"] = outline
    return outline


def lecture_status(service: LectureQAService, doc_id: str) -> str:
    return service.progress().status_of(doc_id)


def status_badge(status: str) -> str:
    return f"{STATUS_ICON.get(status, '⚪')} {STATUS_LABEL.get(status, status)}"


def home_page(service: LectureQAService) -> None:
    if not service.indexed:
        page_header("GET STARTED", "建立你的课程库", "上传讲义后，LectureQA 会生成课程地图、逐讲摘要和可引用问答。")
        st.info("在左侧「课程管理」上传 PDF，或把讲义放进 `data/` 后点击「构建索引」。")
        return

    outline = get_outline(service)
    progress = service.progress()
    docs = service.documents()

    completed = sum(1 for item in outline.lectures if progress.status_of(item.doc_id) == "completed")
    learning = sum(1 for item in outline.lectures if progress.status_of(item.doc_id) == "learning")
    attempts = sum(record.quiz_attempts for record in progress.lectures.values())
    correct = sum(record.quiz_correct for record in progress.lectures.values())
    accuracy = f"{correct / attempts:.0%}" if attempts else "—"
    total_lectures = max(len(outline.lectures), 1)
    percent = completed / total_lectures

    st.markdown(
        f'<div class="dashboard-greeting"><div class="page-kicker">YOUR STUDY DESK</div>'
        f'<h1>继续你的学习</h1>'
        f'<p>{len(docs)} 份讲义 · 已完成 {completed}/{len(outline.lectures)} 讲 · 自测正确率 {accuracy}</p></div>',
        unsafe_allow_html=True,
    )

    next_lecture = next(
        (item for item in outline.lectures if progress.status_of(item.doc_id) != "completed"),
        None,
    )
    if next_lecture:
        next_status = progress.status_of(next_lecture.doc_id)
        next_page_count = next((doc.pages for doc in docs if doc.doc_id == next_lecture.doc_id), 0)
        resume_left, resume_right = st.columns([4.8, 1.15], vertical_alignment="center")
        with resume_left:
            st.markdown(
                f'<div class="resume-panel"><div><div class="resume-label">推荐继续</div>'
                f'<div class="resume-title">第 {next_lecture.order} 讲 · {escape(next_lecture.title)}</div>'
                f'<div class="resume-meta">{next_page_count} 页 · {STATUS_LABEL.get(next_status, "未开始")} · 从课程地图进入原文学习</div></div>'
                f'<div class="resume-progress"><div class="resume-progress-label"><span>课程进度</span><strong>{percent:.0%}</strong></div>'
                f'<div class="resume-track"><div class="resume-fill" style="width:{percent:.0%}"></div></div></div></div>',
                unsafe_allow_html=True,
            )
        with resume_right:
            st.button("打开这一讲 →", key="continue_next", type="primary", use_container_width=True, on_click=goto_lecture, args=(next_lecture.doc_id,))
    else:
        st.success("所有讲义都已完成。可以去「练习」做综合自测或复习错题。")

    metric_left, metric_right = st.columns([1.4, 2.6])
    with metric_left:
        st.markdown("**学习概览**")
    with metric_right:
        col1, col2, col3 = st.columns(3)
        col1.metric("已完成", f"{completed}/{len(outline.lectures)}")
        col2.metric("学习中", str(learning))
        col3.metric("自测正确率", accuracy)

    st.markdown('<div class="dashboard-tools"><h2>课程目录</h2><span style="color:#727c8d;font-size:.82rem">按顺序学习，点击右侧进入</span></div>', unsafe_allow_html=True)
    with st.container(border=True):
        search_col, filter_col = st.columns([3, 1])
        with search_col:
            query = st.text_input("搜索讲义或知识点", placeholder="搜索标题、文件名或知识点…", key="course_search", label_visibility="collapsed")
        with filter_col:
            status_filter = st.selectbox("学习状态", ["全部状态", *STATUS_LABEL.values()], key="course_filter", label_visibility="collapsed")
        sources = {document.doc_id: document.source_path for document in docs}
        doc_pages = {document.doc_id: document.pages for document in docs}
        visible = [
            lecture for lecture in outline.lectures
            if (status_filter == "全部状态" or STATUS_LABEL.get(progress.status_of(lecture.doc_id)) == status_filter)
            and (not query.strip() or query.strip().casefold() in " ".join([
                lecture.title, Path(sources.get(lecture.doc_id, "")).name, *lecture.concepts,
            ]).casefold())
        ]
        st.caption(f"显示 {len(visible)} / {len(outline.lectures)} 讲")
        for lecture in visible:
            status = progress.status_of(lecture.doc_id)
            page_count = doc_pages.get(lecture.doc_id, 0)
            index_label = "示例" if lecture.order >= 100 else f"{lecture.order:02d}"
            with st.container(key=f"course_row_{lecture.doc_id}"):
                detail_col, action_col = st.columns([5.5, 1], vertical_alignment="center")
                with detail_col:
                    st.markdown(
                        f'<div class="course-row"><span class="course-number">{index_label}</span><div class="course-main">'
                        f'<div class="course-title">{escape(lecture.title)}</div>'
                        f'<div class="course-meta">{escape(Path(sources.get(lecture.doc_id, "")).name or lecture.doc_id)} · {page_count} 页</div></div>'
                        f'<span class="course-state {status}">{STATUS_LABEL.get(status, status)}</span></div>',
                        unsafe_allow_html=True,
                    )
                with action_col:
                    st.button(
                        "进入讲义", key=f"start_{lecture.doc_id}", use_container_width=True,
                        on_click=goto_lecture, args=(lecture.doc_id,),
                    )
        if not visible:
            st.info("没有匹配的讲义。试试其他关键词或切换学习状态。")

    st.markdown('<div class="dashboard-tools"><h2>课程说明</h2></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(outline.overview)
        if outline.relations:
            st.caption("课程关系")
            for relation in outline.relations:
                st.markdown(f"- {relation}")

    weak = service.weak_points(limit=5)
    if weak:
        st.markdown('<div class="dashboard-tools"><h2>需要复习</h2></div>', unsafe_allow_html=True)
        with st.container(border=True):
            for point in weak:
                st.markdown(f"- `{point.concept}`（{point.lecture_id}，错 {point.error_count} 次） — {point.recommended_action}")


def lecture_overview(
    service: LectureQAService,
    lecture: LectureOutline,
    source_path: str,
    *,
    preview_scope: str,
) -> None:
    """本讲文字概览；课件预览由外层讲次页右侧固定栏负责。"""
    if lecture.objectives:
        st.markdown("**学完这一讲，你应该能：**")
        for objective in lecture.objectives:
            st.markdown(f"- {objective}")

    if lecture.concepts:
        st.markdown("**关键概念**")
        st.markdown(" · ".join(f"`{concept}`" for concept in lecture.concepts))

    st.markdown("**本讲概要**")
    st.markdown(lecture.summary or "（暂无概要）")

    if lecture.topics:
        st.markdown("**本讲脉络（页码区间全覆盖；点击跳到右侧课件）**")
        st.caption("每条对应连续页范围，合起来覆盖整份课件，而不是零散单页。")
        for index, topic in enumerate(lecture.topics):
            span = parse_topic_span(topic)
            row_left, row_right = st.columns([5.2, 1.4])
            with row_left:
                st.markdown(f"- {topic}")
            with row_right:
                if span is None:
                    continue
                page_jump_button(
                    topic_span_label(topic),
                    scope=preview_scope,
                    doc_id=lecture.doc_id,
                    page=span[0],
                    key=f"{preview_scope}_topic_{index}_{span[0]}_{span[1]}",
                    source_path=source_path,
                )

    st.caption("点击区间页码后，右侧固定课件预览会定位到该段起始页。")


def lecture_page(
    service: LectureQAService,
    top_k: int,
    allow_web: bool,
) -> None:
    page_header("LECTURE REVIEW", "讲义学习", "概览、问答与自测共用右侧课件；点击出处页码即可对照原文。")
    if not service.indexed:
        st.info("还没有讲义。请在左侧「课程管理」上传 PDF 或构建索引。")
        return

    outline = get_outline(service)
    if not outline.lectures:
        st.info("课程地图为空，请先在左侧「课程管理」重新生成课程大纲。")
        return

    by_id = {item.doc_id: item for item in outline.lectures}
    doc_ids = [item.doc_id for item in outline.lectures]
    files = {document.doc_id: Path(document.source_path).name for document in service.documents()}
    page_counts = {document.doc_id: document.pages for document in service.documents()}
    current = st.session_state.get("lecture_doc_id")
    if current not in doc_ids:
        current = doc_ids[0]
    default_index = doc_ids.index(current)

    def _lecture_label(doc_id: str) -> str:
        item = by_id[doc_id]
        file_name = files.get(doc_id, doc_id)
        pages = page_counts.get(doc_id, 0)
        if item.order >= 100:
            return f"示例 · {file_name} · {pages} 页 · id:{doc_id}"
        return f"第 {item.order} 讲 · {file_name} · {pages} 页 · id:{doc_id}"

    selected_id = st.selectbox(
        "选择讲义",
        options=doc_ids,
        index=default_index,
        format_func=_lecture_label,
        help="「第 N 讲」与 LectureN.pdf 的编号一致；带前缀「示例」的是 sample 课件。",
    )
    st.session_state["lecture_doc_id"] = selected_id
    choice = by_id[selected_id]
    service.touch_lecture(choice.doc_id)

    progress = service.progress()
    status = progress.status_of(choice.doc_id)
    sources = {document.doc_id: document.source_path for document in service.documents()}
    source_path = sources.get(choice.doc_id, "")

    header, actions = st.columns([5, 2.2])
    with header:
        heading = (
            f"示例课件 · {choice.title}"
            if choice.order >= 100
            else f"第 {choice.order} 讲 · {choice.title}"
        )
        st.subheader(heading)
        st.caption(
            f"{status_badge(status)} · 来源 `{files.get(choice.doc_id, choice.doc_id)}`"
            f" · 共 {page_counts.get(choice.doc_id, 0)} 页 · doc_id `{choice.doc_id}`"
        )
    with actions:
        if status != "completed" and st.button(
            "标记为已完成", key=f"done_{choice.doc_id}", use_container_width=True
        ):
            service.set_lecture_status(choice.doc_id, "completed")
            st.rerun()
        if status == "completed" and st.button(
            "重新学习", key=f"reset_{choice.doc_id}", use_container_width=True
        ):
            service.set_lecture_status(choice.doc_id, "learning")
            st.rerun()

    if status == "not_started":
        service.set_lecture_status(choice.doc_id, "learning")

    # 概览 / 问答 / 自测共用右侧固定课件；左栏内滚，右栏钉在视口
    preview_scope = f"lecture_{choice.doc_id}"
    inject_pdf_pane_styles()
    left, right = st.columns([1.2, 0.95], gap="large")
    with left:
        st.markdown('<span class="lecture-scroll-marker"></span>', unsafe_allow_html=True)
        overview_tab, ask_tab, quiz_tab_view = st.tabs(
            ["📄 本讲概览", "💬 本讲问答", "📝 本讲自测"]
        )
        with overview_tab:
            lecture_overview(
                service,
                choice,
                source_path,
                preview_scope=preview_scope,
            )
        with ask_tab:
            chat_panel(
                service,
                doc_ids=[choice.doc_id],
                top_k=top_k,
                allow_web=allow_web,
                state_key=f"messages_{choice.doc_id}",
                placeholder=f"针对「{choice.title}」提问，例如：这一讲最重要的公式是什么？",
                hint=(
                    f"检索范围锁定：第 {choice.order} 讲 · `{files.get(choice.doc_id, choice.doc_id)}`"
                    f"（doc_id=`{choice.doc_id}`）。跨讲比较请用「全课程问答」。"
                    " 点出处页码会跳到右侧课件。"
                ),
                preview_scope=preview_scope,
            )
        with quiz_tab_view:
            quiz_topic = (
                "、".join(choice.concepts[:4])
                if choice.concepts
                else "本讲核心知识点、定义、公式与算法步骤"
            )
            quiz_tab(
                service,
                doc_ids=[choice.doc_id],
                default_topic=quiz_topic,
                key=f"quiz_{choice.doc_id}",
                lecture_id=choice.doc_id,
                concepts=choice.concepts,
                preview_scope=preview_scope,
            )
    with right:
        render_pdf_pane(
            scope=preview_scope,
            doc_id=choice.doc_id,
            source_path=source_path,
            page_count=page_counts.get(choice.doc_id, 0),
            title=choice.title,
            fallback_page=(choice.key_pages or [1])[0],
        )


def chat_panel(
    service: LectureQAService,
    doc_ids: list[str] | None,
    top_k: int,
    allow_web: bool,
    *,
    state_key: str,
    placeholder: str,
    hint: str = "",
    preview_scope: str | None = None,
) -> None:
    # 以 session 中当前讲为准，避免切讲后仍用旧闭包范围
    locked = st.session_state.get("lecture_doc_id")
    if locked and doc_ids and len(doc_ids) == 1:
        doc_ids = [locked]

    if hint:
        st.caption(hint)
    if doc_ids:
        file_names = {
            document.doc_id: Path(document.source_path).name or document.doc_id
            for document in service.documents()
        }
        labels = [
            f"{file_names.get(item, item)}（doc_id=`{item}`）" for item in doc_ids
        ]
        st.info("本轮检索只使用：" + "；".join(labels))
    if state_key not in st.session_state:
        st.session_state[state_key] = []
    messages = st.session_state[state_key]

    sources = {document.doc_id: document.source_path for document in service.documents()}
    # 讲次页 / 全课程问答都传入 preview_scope，PPT 固定在右侧，不再上下堆叠
    source_scope = preview_scope or f"src_{state_key}"

    for msg_index, message in enumerate(messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_answer_body(
                    message["content"],
                    sources=sources,
                    scope=source_scope,
                    key_prefix=f"{source_scope}_m{msg_index}",
                    interactive=True,
                )
            else:
                st.markdown(message["content"])
            if message.get("answer") is not None:
                render_sources(
                    message["answer"],
                    sources,
                    scope=source_scope,
                    key_prefix=f"{source_scope}_m{msg_index}",
                )

    if messages:
        st.caption("可在下方继续追问；新问题会出现在对话末尾。")

    question = st.chat_input(placeholder, key=f"input_{state_key}")
    if not question:
        if messages:
            scroll_lecture_pane_to_bottom()
        return

    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        status_box = st.empty()
        progress_box = st.empty()
        placeholder_box = st.empty()
        progress_bar = progress_box.progress(0.05, text="正在准备回答…")
        accumulated = ""
        final = None
        started_tokens = False
        try:
            with status_box:
                render_thinking_status("正在准备回答…")
            for event in service.stream(
                question, doc_ids=doc_ids, top_k=top_k, allow_web=allow_web
            ):
                if event.kind == "status":
                    label = event.text or "处理中…"
                    render_generation_progress(
                        progress_bar, label, _status_progress_value(label)
                    )
                    with status_box:
                        render_thinking_status(label)
                elif event.kind == "delta":
                    if not started_tokens:
                        started_tokens = True
                        status_box.empty()
                    accumulated += event.text
                    # 流式输出阶段：按已生成长度缓慢推进到 95%
                    stream_ratio = min(len(accumulated) / 900.0, 1.0)
                    render_generation_progress(
                        progress_bar,
                        "正在生成回答…",
                        0.55 + 0.40 * stream_ratio,
                    )
                    placeholder_box.markdown(display_answer(accumulated) + "▌")
                elif event.kind == "final":
                    final = event.answer
                    render_generation_progress(progress_bar, "回答完成", 1.0)
                elif event.kind == "error":
                    status_box.empty()
                    progress_box.empty()
                    placeholder_box.error(event.text)
        except Exception as exc:  # noqa: BLE001
            status_box.empty()
            progress_box.empty()
            placeholder_box.error(f"生成失败：{exc}")
            return

        if final is None:
            status_box.empty()
            progress_box.empty()
            return
        # 防御：出处不得落到范围外讲义
        if doc_ids and final.evidence:
            allowed = set(doc_ids)
            leaked = sorted(
                {
                    item.chunk.doc_id
                    for item in final.evidence
                    if item.chunk.doc_id not in allowed
                }
            )
            if leaked:
                st.error(
                    "检测到检索越界（不应出现）："
                    + "、".join(leaked)
                    + "。请重新选择讲义后再问一次。"
                )
        status_box.empty()
        progress_box.empty()
        placeholder_box.empty()
        msg_index = len(messages)
        if final.refused:
            render_refusal(final)
        else:
            render_answer_body(
                final.answer,
                sources=sources,
                scope=source_scope,
                key_prefix=f"{source_scope}_m{msg_index}",
                interactive=True,
            )
            render_sources(
                final,
                sources,
                scope=source_scope,
                key_prefix=f"{source_scope}_m{msg_index}",
            )
        if final.citations:
            first = final.citations[0]
            set_preview(source_scope, first.doc_id, first.page)
        elif final.evidence:
            first_ev = final.evidence[0]
            set_preview(source_scope, first_ev.chunk.doc_id, first_ev.chunk.page)

    messages.append({"role": "assistant", "content": final.answer, "answer": final})
    st.caption("回答完成，可在下方输入框继续追问。")
    scroll_lecture_pane_to_bottom()


def _render_wrong_book(service: LectureQAService, lecture_id: str | None = None) -> None:
    wrong = service.wrong_attempts(lecture_id, limit=20)
    if not wrong:
        st.caption("暂无错题。完成自测并提交后，错题会出现在这里。")
        return
    sources = {document.doc_id: document.source_path for document in service.documents()}
    for index, attempt in enumerate(wrong, start=1):
        with st.container(border=True):
            st.markdown(f"**错题 {index}.** {attempt.question}")
            st.caption(
                f"你的答案：{attempt.student_answer or '（空）'} · 正确答案：{attempt.correct_answer}"
            )
            st.markdown(attempt.explanation)
            pages = "、".join(
                f"`{source.doc_id}` p.{source.page}" for source in attempt.source_pages
            )
            if pages:
                st.caption(f"出处：{pages}")
                for source in attempt.source_pages[:2]:
                    path = sources.get(source.doc_id, "")
                    if path:
                        render_slide_image(
                            path,
                            source.page,
                            caption=f"{source.doc_id} · p.{source.page}",
                            dpi=110,
                        )


def quiz_tab(
    service: LectureQAService,
    doc_ids: list[str] | None,
    *,
    default_topic: str = "课程核心概念",
    key: str = "quiz",
    lecture_id: str | None = None,
    concepts: list[str] | None = None,
    preview_scope: str | None = None,
) -> None:
    lecture_id = lecture_id or (doc_ids[0] if doc_ids and len(doc_ids) == 1 else "course")
    concepts = concepts or []

    st.caption("围绕讲义正文知识点出题（定义/公式/步骤/对比），不会考课件标题、第几讲，也不会问 PPT 第几页。")
    with st.form(f"quiz_form_{key}"):
        col1, col2, col3 = st.columns([3, 1, 1])
        topic = col1.text_input(
            "复习主题（知识点，不是讲义标题）",
            value=default_topic,
            key=f"topic_{key}",
            help="填写要练的概念/公式范围，例如「扩散模型损失」；不要填 Lecture 标题或页码。",
        )
        count = col2.slider("题数", 1, 10, 5, key=f"count_{key}")
        difficulty = col3.selectbox(
            "难度", ["mixed", "easy", "medium", "hard"], key=f"difficulty_{key}"
        )
        types = st.multiselect(
            "题型",
            ["mcq", "true_false", "short_answer"],
            default=["mcq", "true_false"],
            key=f"types_{key}",
        )
        submitted = st.form_submit_button("生成自测", use_container_width=True)

    state_key = f"quiz_result_{key}"
    graded_key = f"quiz_graded_{key}"
    if submitted:
        progress_box = st.empty()
        status_box = st.empty()
        progress_bar = progress_box.progress(0.05, text="准备出题…")
        try:
            with status_box:
                render_thinking_status("正在生成自测题，请稍候…")

            def _on_progress(value: float, label: str) -> None:
                render_generation_progress(progress_bar, label, value)
                with status_box:
                    render_thinking_status(label)

            result = service.quiz(
                topic,
                doc_ids=doc_ids,
                n=count,
                difficulty=difficulty,
                types=types or None,
                on_progress=_on_progress,
            )
            st.session_state[state_key] = result
            st.session_state[graded_key] = {}
            dropped = len(result.dropped or [])
            kept = len(result.questions or [])
            done_label = f"出题完成：保留 {kept} 题" + (f"，丢弃 {dropped} 题" if dropped else "")
            render_generation_progress(progress_bar, done_label, 1.0)
            status_box.empty()
            st.success(done_label)
            if not result.questions:
                st.warning("没有可用题目，可换个知识点主题再试。")
        except Exception as exc:  # noqa: BLE001
            status_box.empty()
            progress_box.empty()
            st.error(f"生成失败：{exc}")
            st.session_state.pop(state_key, None)
            st.session_state.pop(graded_key, None)

    result = st.session_state.get(state_key)
    if result is None:
        st.caption("先作答再提交；系统会批改、展示解析与课件出处，并记入错题本。")
        return
    if not result.questions:
        st.warning("没有生成可用题目：主题相关的讲义证据不足，或全部题目未通过溯源校验。")
        for reason in result.dropped[:5]:
            st.caption(f"- {reason}")
        return

    sources = {document.doc_id: document.source_path for document in service.documents()}
    titles = {document.doc_id: document.doc_title for document in service.documents()}
    quiz_scope = preview_scope or f"quiz_src_{key}"
    graded: dict = st.session_state.setdefault(graded_key, {})
    letters = "ABCDEFGH"

    for index, question in enumerate(result.questions, start=1):
        qid = question.question_id or f"{key}_q{index}"
        with st.container(border=True):
            st.markdown(
                f"**{index}. [{question.type.value} · {question.difficulty}]** {question.question}"
            )
            answer_key = f"ans_{key}_{qid}"
            if question.type.value == "mcq" and question.options:
                choices = [
                    f"{letter}. {option}"
                    for letter, option in zip(letters, question.options, strict=False)
                ]
                pick = st.radio(
                    "你的答案",
                    options=choices,
                    key=answer_key,
                    disabled=qid in graded,
                    label_visibility="collapsed",
                )
                student = pick.split(".", 1)[0] if pick else ""
            elif question.type.value == "true_false":
                student = st.radio(
                    "你的答案",
                    options=["True", "False"],
                    key=answer_key,
                    disabled=qid in graded,
                    horizontal=True,
                    label_visibility="collapsed",
                )
            else:
                student = st.text_area(
                    "你的答案",
                    key=answer_key,
                    disabled=qid in graded,
                    label_visibility="collapsed",
                    placeholder="写下要点后再提交",
                )

            if qid not in graded:
                if st.button("提交本题", key=f"submit_{key}_{qid}"):
                    ok = grade_quiz_answer(
                        question_type=question.type.value,
                        correct_answer=question.answer,
                        student_answer=str(student or ""),
                        options=question.options,
                    )
                    attempt = QuizAttempt(
                        attempt_id="",
                        lecture_id=lecture_id,
                        question_id=qid,
                        question=question.question,
                        question_type=question.type.value,
                        student_answer=str(student or ""),
                        correct_answer=question.answer,
                        correct=ok,
                        explanation=question.explanation,
                        concepts=list(concepts[:4]),
                        source_pages=[
                            QuizSource(doc_id=source.doc_id, page=source.page)
                            for source in question.sources
                        ],
                    )
                    service.record_quiz_attempt(attempt)
                    graded[qid] = {"correct": ok, "student": str(student or "")}
                    st.session_state[graded_key] = graded
                    st.rerun()
            else:
                record = graded[qid]
                if record["correct"]:
                    st.success("回答正确")
                else:
                    st.error(f"回答错误。你的答案：{record['student'] or '（空）'}")
                st.markdown(f"**参考答案：** {question.answer}")
                st.markdown(f"**解析：** {question.explanation}")
                if question.sources:
                    st.markdown("**课件出处** · 点页码跳到右侧预览")
                    for s_index, source in enumerate(question.sources):
                        path = sources.get(source.doc_id, "")
                        label = f"{titles.get(source.doc_id, source.doc_id)} · p.{source.page}"
                        cols = st.columns([4, 1.2])
                        with cols[0]:
                            st.caption(label)
                        with cols[1]:
                            page_jump_button(
                                f"→ p.{source.page}",
                                scope=quiz_scope,
                                doc_id=source.doc_id,
                                page=source.page,
                                key=f"{quiz_scope}_q{index}_{s_index}_{source.page}",
                                source_path=path,
                            )

    done = len(graded)
    total = len(result.questions)
    if done:
        correct = sum(1 for item in graded.values() if item["correct"])
        st.metric("本题组正确率", f"{correct}/{done}" + (f"（共 {total} 题）" if done < total else ""))

def quiz_page(service: LectureQAService, doc_ids: list[str] | None, top_k: int) -> None:
    page_header("PRACTICE", "练习 / 错题", "按知识点生成可溯源自测题；批改后自动归入错题本与薄弱知识点。")
    if not service.indexed:
        st.info("还没有讲义。请在左侧「课程管理」上传 PDF 或构建索引。")
        return

    preview_scope = "quiz_all"

    def _left() -> None:
        practice_tab, wrong_tab, weak_tab = st.tabs(["综合练习", "错题本", "薄弱知识点"])
        with practice_tab:
            st.caption("练习按知识点出题；范围默认取左侧「限定讲义」，留空为全课程。出处页码仅用于核对，不会成为考题。")
            quiz_tab(
                service,
                doc_ids=doc_ids,
                default_topic="课程核心概念、定义与关键公式",
                key="practice",
                preview_scope=preview_scope,
            )
        with wrong_tab:
            scope = doc_ids[0] if doc_ids and len(doc_ids) == 1 else None
            _render_wrong_book(service, scope)
        with weak_tab:
            points = service.weak_points(limit=20)
            if not points:
                st.caption("完成自测并产生错题后，这里会汇总薄弱概念与推荐复习页。")
            else:
                for point in points:
                    st.markdown(
                        f"- **{point.concept}** · `{point.lecture_id}` · 错 {point.error_count} 次  \n"
                        f"  {point.recommended_action}"
                    )

    render_split_workspace(
        service=service,
        preview_scope=preview_scope,
        preferred_doc_ids=doc_ids,
        left_render=_left,
    )


def chat_page(
    service: LectureQAService,
    doc_ids: list[str] | None,
    top_k: int,
    allow_web: bool,
) -> None:
    page_header("ASK ACROSS COURSE", "全课程问答", "左侧问答、右侧课件对照；点出处页码即可同步跳转，不用上下翻找。")
    if not service.indexed:
        st.info("还没有讲义。请在左侧「课程管理」上传 PDF 或构建索引。")
        return
    preview_scope = "chat_all"

    def _left() -> None:
        chat_panel(
            service,
            doc_ids=doc_ids,
            top_k=top_k,
            allow_web=allow_web,
            state_key="messages_all",
            placeholder="例如：这门课程讲了什么？RAG 和 Transformer 有什么关系？",
            hint="点答案里的 p.N，右侧课件会跳到对应页。",
            preview_scope=preview_scope,
        )

    render_split_workspace(
        service=service,
        preview_scope=preview_scope,
        preferred_doc_ids=doc_ids,
        left_render=_left,
    )


def dev_page(service: LectureQAService, doc_ids: list[str] | None, top_k: int) -> None:
    page_header("WORKSPACE", "课程管理", "上传、索引、检索调试与系统状态；日常学习不需要进入这里。")
    if not service.indexed:
        st.info("索引为空：请在左侧「课程管理」上传 PDF 或构建索引。")
        return

    docs = service.documents()
    st.subheader("讲义清单")
    st.dataframe(
        [
            {
                "doc_id": document.doc_id,
                "标题": document.doc_title,
                "页数": document.pages,
                "分块": document.chunks,
            }
            for document in docs
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("检索调试")
    search_tab(service, doc_ids, top_k)


def search_tab(service: LectureQAService, doc_ids: list[str] | None, top_k: int) -> None:
    query = st.text_input("输入查询，直接看召回片段与打分明细")
    if not query:
        return
    try:
        results = service.search(query, doc_ids=doc_ids, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        st.error(f"检索失败：{exc}")
        return
    if not results:
        st.info("没有召回结果，检查索引是否已构建。")
        return

    import pandas as pd

    table = pd.DataFrame(
        [
            {
                "doc_id": item.chunk.doc_id,
                "page": item.chunk.page,
                "score": round(item.score, 4),
                "support": round(item.support, 3),
                "dense": None if item.dense_score is None else round(item.dense_score, 4),
                "bm25": None if item.lexical_score is None else round(item.lexical_score, 2),
                "text": item.chunk.text[:160].replace("\n", " "),
            }
            for item in results
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)


def main() -> None:
    render_app_styles()
    service = get_service()
    doc_ids, top_k, allow_web = sidebar(service)

    page = st.session_state.get("nav", "home")
    if page == "home":
        home_page(service)
    elif page == "lecture":
        lecture_page(service, top_k, allow_web)
    elif page == "quiz":
        quiz_page(service, doc_ids, top_k)
    elif page == "chat":
        chat_page(service, doc_ids, top_k, allow_web)
    else:
        dev_page(service, doc_ids, top_k)


if __name__ == "__main__":
    main()
