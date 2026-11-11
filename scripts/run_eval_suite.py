#!/usr/bin/env python3
"""正式评估套件：主配置 + 检索消融 + 阈值敏感性，报告写入 eval/reports/。

用法（在项目根目录）：
  .venv/bin/python scripts/run_eval_suite.py
  .venv/bin/python scripts/run_eval_suite.py --quick          # 只用 sample，快速冒烟
  .venv/bin/python scripts/run_eval_suite.py --with-judge     # 额外跑 LLM-as-judge（慢/费额度）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureqa.config import Settings, get_settings  # noqa: E402
from lectureqa.eval.runner import run_evaluation  # noqa: E402
from lectureqa.service import LectureQAService  # noqa: E402


def _settings(**overrides: object) -> Settings:
    get_settings.cache_clear()
    base = Settings()
    data = base.model_dump()
    data.update(overrides)
    return Settings(**data)


def _run(
    name: str,
    settings: Settings,
    testset: Path,
    *,
    k: int,
    with_judge: bool,
    bm25_only: bool = False,
) -> Path:
    print(
        f"\n=== [{name}] testset={testset.name} k={k} rerank={settings.rerank} "
        f"embed={settings.embedding_provider} thr={settings.min_evidence_score} "
        f"bm25_only={bm25_only}"
    )
    service = LectureQAService(settings)
    if bm25_only:
        # 不换 embedding 索引，直接关掉 dense，得到近似 BM25-only 基线
        service.retriever._dense_disabled = True  # noqa: SLF001
    report = run_evaluation(settings, testset, k=k, judge=with_judge, service=service)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "eval" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 避免 threshold-0.15 这类名字被 Path.with_suffix 截断
    safe_name = name.replace(".", "p")
    json_path = out_dir / f"suite-{safe_name}-{stamp}.json"
    md_path = out_dir / f"suite-{safe_name}-{stamp}.md"
    payload = report.model_dump()
    payload["suite_name"] = name
    payload["config_snapshot"] = {
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "store_backend": settings.store_backend,
        "rerank": settings.rerank,
        "min_evidence_score": settings.min_evidence_score,
        "top_k": settings.top_k,
        "fetch_k": settings.fetch_k,
        "testset": str(testset),
        "k": k,
        "with_judge": with_judge,
        "bm25_only": bm25_only,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = payload.get("metrics") or {}
    lines = [
        f"# LectureQA 套件报告 · {name}",
        "",
        f"- 时间：{payload.get('generated_at', stamp)}",
        f"- 测试集：`{testset}`",
        f"- 配置：rerank=`{settings.rerank}` embed=`{settings.embedding_provider}` "
        f"thr=`{settings.min_evidence_score}` k=`{k}`",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
    ]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {md_path}")
    print(
        "metrics:",
        {
            key: metrics.get(key)
            for key in (
                "hit_rate",
                "recall",
                "mrr",
                "citation_precision",
                "grounded_rate",
                "refusal_accuracy",
                "unanswerable_refusal_rate",
                "error_rate",
                "avg_latency_ms",
            )
            if key in metrics
        },
    )
    return json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="LectureQA formal eval suite")
    parser.add_argument("--quick", action="store_true", help="只用 sample 测试集冒烟")
    parser.add_argument("--with-judge", action="store_true", help="启用 LLM-as-judge")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument(
        "--only",
        choices=["main", "ablation", "threshold", "cross-encoder", "all"],
        default="all",
        help="只跑某一组实验",
    )
    args = parser.parse_args()

    testset = ROOT / "eval" / ("testset.sample.jsonl" if args.quick else "testset.full.jsonl")
    if not testset.exists():
        raise SystemExit(f"找不到测试集：{testset}")

    # 避免子进程残留环境污染（本脚本用 Settings 覆盖）
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    paths: list[Path] = []
    if args.only in {"main", "all"}:
        paths.append(
            _run("main-hybrid-coverage", _settings(), testset, k=args.k, with_judge=args.with_judge)
        )

    if args.only in {"ablation", "all"}:
        # A: BM25-only + 无重排
        paths.append(
            _run(
                "ablation-bm25-only",
                _settings(rerank="none"),
                testset,
                k=args.k,
                with_judge=False,
                bm25_only=True,
            )
        )
        # B: 主配置（若 only=ablation 且刚才没跑 main，再跑一遍 hybrid）
        if args.only == "ablation":
            paths.append(
                _run(
                    "ablation-hybrid-coverage",
                    _settings(),
                    testset,
                    k=args.k,
                    with_judge=False,
                )
            )

    if args.only in {"cross-encoder", "ablation", "all"}:
        # cross-encoder（缺依赖时会失败，捕获并继续）
        try:
            paths.append(
                _run(
                    "ablation-hybrid-cross-encoder",
                    _settings(rerank="cross-encoder"),
                    testset,
                    k=args.k,
                    with_judge=False,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] cross-encoder 不可用：{exc}")

    if args.only in {"threshold", "all"}:
        for thr in (0.15, 0.30, 0.45, 0.60):
            paths.append(
                _run(
                    f"threshold-{thr:.2f}",
                    _settings(min_evidence_score=thr),
                    testset,
                    k=args.k,
                    with_judge=False,
                )
            )

    # 汇总表
    summary_rows = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        m = payload.get("metrics") or {}
        cfg = payload.get("config_snapshot") or {}
        summary_rows.append(
            {
                "suite": payload.get("suite_name"),
                "rerank": cfg.get("rerank"),
                "embed": cfg.get("embedding_provider"),
                "thr": cfg.get("min_evidence_score"),
                "hit_rate": m.get("hit_rate"),
                "recall": m.get("recall"),
                "mrr": m.get("mrr"),
                "citation_precision": m.get("citation_precision"),
                "grounded_rate": m.get("grounded_rate"),
                "refusal_accuracy": m.get("refusal_accuracy"),
                "unanswerable_refusal_rate": m.get("unanswerable_refusal_rate"),
                "error_rate": m.get("error_rate"),
                "avg_latency_ms": m.get("avg_latency_ms"),
                "report": str(path),
            }
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summary_path = ROOT / "eval" / "reports" / f"suite-summary-{stamp}.json"
    summary_path.write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ROOT / "eval" / "reports" / f"suite-summary-{stamp}.md"
    lines = [
        "# LectureQA 评估套件汇总",
        "",
        "| suite | rerank | embed | thr | hit | recall | MRR | citeP | grounded | refuseAcc | unansRefuse | err | lat(ms) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            "| {suite} | {rerank} | {embed} | {thr} | {hit_rate} | {recall} | {mrr} | "
            "{citation_precision} | {grounded_rate} | {refusal_accuracy} | "
            "{unanswerable_refusal_rate} | {error_rate} | {avg_latency_ms} |".format(**row)
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nsummary -> {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
