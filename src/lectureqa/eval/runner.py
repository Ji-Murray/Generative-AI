"""评估实验编排：read testset → 检索 / 生成 / 校验 → 指标汇总 → 报告落盘。"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from lectureqa.config import Settings
from lectureqa.eval.metrics import (
    aggregate,
    citation_precision,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)
from lectureqa.generation import prompts
from lectureqa.llm import LLM, LLMClient, LLMError
from lectureqa.schemas import EvalReport, ItemResult, TestItem
from lectureqa.service import LectureQAService

logger = logging.getLogger(__name__)
REPORT_DIR = Path(__file__).resolve().parents[3] / "eval" / "reports"


def load_testset(path: Path) -> list[TestItem]:
    items: list[TestItem] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                items.append(TestItem.model_validate(json.loads(line)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("跳过 %s 第 %s 行：%s", path.name, line_number, exc)
    return items


def _judge(llm: LLM, item: TestItem, answer: str) -> float | None:
    if not item.reference_answer:
        return None
    try:
        payload = llm.complete_json(
            [
                {"role": "system", "content": prompts.JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": prompts.JUDGE_USER.format(
                        question=item.question, reference=item.reference_answer, answer=answer
                    ),
                },
            ]
        )
    except LLMError as exc:
        logger.warning("judge 调用失败：%s", exc)
        return None
    faithful = float(payload.get("faithful", 0) or 0)
    correct = float(payload.get("correct", 0) or 0)
    return round((faithful + correct) / 2, 4)


def evaluate_item(
    service: LectureQAService, item: TestItem, *, k: int, judge_llm: LLM | None = None
) -> ItemResult:
    started = time.perf_counter()
    try:
        retrieved = service.search(item.question, top_k=k)
    except Exception as exc:  # noqa: BLE001 - 一条坏样本不应中止整次评估
        logger.exception("评估样本 %s 检索失败", item.qid)
        retrieved = []
        retrieval_error = str(exc)
    else:
        retrieval_error = ""

    answer = None
    answer_error = ""
    try:
        answer = service.ask(item.question, top_k=k)
    except Exception as exc:  # noqa: BLE001 - 无 Key / 接口异常时仍保留检索侧指标
        logger.warning("评估样本 %s 生成失败：%s", item.qid, exc)
        answer_error = str(exc)

    latency_ms = int((time.perf_counter() - started) * 1000)
    error = retrieval_error or answer_error

    if item.type == "unanswerable":
        return ItemResult(
            qid=item.qid,
            question=item.question,
            type=item.type,
            refused=bool(answer and answer.refused),
            hit_at_k=False,
            recall_at_k=0.0,
            reciprocal_rank=0.0,
            citation_precision=0.0,
            grounded=bool(answer and answer.grounded),
            answer=answer.answer if answer else "",
            latency_ms=latency_ms,
            error=error,
        )

    citations = answer.citations if answer else []
    return ItemResult(
        qid=item.qid,
        question=item.question,
        type=item.type,
        refused=bool(answer and answer.refused),
        hit_at_k=hit_at_k(retrieved, item.gold_pages, item.gold_doc_ids),
        recall_at_k=round(recall_at_k(retrieved, item.gold_pages, item.gold_doc_ids), 4),
        reciprocal_rank=round(reciprocal_rank(retrieved, item.gold_pages, item.gold_doc_ids), 4),
        citation_precision=round(
            citation_precision(citations, item.gold_pages, item.gold_doc_ids), 4
        ),
        grounded=bool(answer and answer.grounded),
        answer=answer.answer if answer else "",
        latency_ms=latency_ms,
        judge_score=_judge(judge_llm, item, answer.answer) if judge_llm and answer else None,
        error=error,
    )


def _write_report(report: EvalReport) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"report-{stamp}.json"
    json_path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# LectureQA 评估报告 {report.generated_at}",
        "",
        f"- 测试集：`{report.testset}`（{report.n} 条，k={report.k}）",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
    ]
    lines += [f"| {key} | {value} |" for key, value in report.metrics.items()]
    lines += ["", "## 逐题结果", "", "| qid | 类型 | 命中 | 引用精度 | 拒答 | 延迟(ms) | 异常 |", "|---|---|---|---|---|---|---|"]
    lines += [
        f"| {item.qid} | {item.type} | {item.hit_at_k} | {item.citation_precision} | "
        f"{item.refused} | {item.latency_ms} | {item.error[:80]} |"
        for item in report.items
    ]
    (REPORT_DIR / f"report-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def run_evaluation(
    settings: Settings,
    testset_path: Path,
    *,
    k: int = 6,
    judge: bool = False,
    service: LectureQAService | None = None,
) -> EvalReport:
    items = load_testset(testset_path)
    if not items:
        raise ValueError(f"测试集为空：{testset_path}")
    service = service or LectureQAService(settings)

    judge_llm: LLM | None = None
    if judge and settings.eval_judge_model:
        judge_llm = LLMClient(settings)
        judge_llm.model = settings.eval_judge_model  # type: ignore[misc]

    results = [evaluate_item(service, item, k=k, judge_llm=judge_llm) for item in items]
    report = EvalReport(
        testset=str(testset_path),
        k=k,
        n=len(results),
        metrics=aggregate(results),
        items=results,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    _write_report(report)
    return report
