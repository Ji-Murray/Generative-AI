"""命令行入口：ingest / ask / quiz / search / documents / eval / serve。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from lectureqa.config import Settings, get_settings


def _print_answer(answer) -> None:
    print(answer.answer)
    if answer.refused:
        print("\n[拒答] 讲义证据不足，未生成答案。")
    if answer.external_sources:
        print("\n[注意] 以下内容来自网络，不属于课程讲义：")
        for source in answer.external_sources:
            print(f"  - {source.title}  {source.url}")
    if answer.citations:
        print("\n出处：")
        for citation in answer.citations:
            print(f"  - {citation.doc_title} p.{citation.page}  ({citation.chunk_id})")
    if answer.invalid_citations:
        print(f"\n[警告] 已剔除模型编造的引用 {len(answer.invalid_citations)} 处")
    print(f"\n模型 {answer.model} · {answer.latency_ms} ms")


def _print_evidence(items) -> None:
    for rank, item in enumerate(items, start=1):
        chunk = item.chunk
        print(
            f"{rank}. {chunk.doc_title} p.{chunk.page} "
            f"score={item.score:.3f} support={item.support:.2f} "
            f"dense={'-' if item.dense_score is None else f'{item.dense_score:.3f}'} "
            f"lexical={'-' if item.lexical_score is None else f'{item.lexical_score:.3f}'}"
        )
        print(f"   {chunk.text[:180].replace(chr(10), ' ')}")


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.ingest.pipeline import discover_pdfs, ingest

    paths: list[Path] | None = None
    if args.paths:
        paths = []
        for raw in args.paths:
            target = Path(raw).expanduser().resolve()
            if target.is_dir():
                paths.extend(discover_pdfs(target))
            else:
                paths.append(target)
    report = ingest(settings, paths=paths, reset=not args.keep)
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    return 0


def cmd_documents(_args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.service import LectureQAService

    service = LectureQAService(settings)
    for document in service.documents():
        print(f"{document.doc_id:<28} pages={document.pages:<4} chunks={document.chunks:<4} {document.doc_title}")
    print(f"\n合计 {len(service.documents())} 份讲义 / {len(service.corpus)} 个分块")
    return 0


def cmd_search(args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.service import LectureQAService

    service = LectureQAService(settings)
    _print_evidence(service.search(args.query, doc_ids=args.doc, top_k=args.top_k))
    return 0


def cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.service import LectureQAService

    service = LectureQAService(settings)
    _print_answer(
        service.ask(
            args.question,
            doc_ids=args.doc,
            top_k=args.top_k,
            allow_web=args.web,
        )
    )
    return 0


def cmd_quiz(args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.service import LectureQAService

    service = LectureQAService(settings)
    result = service.quiz(
        args.topic, doc_ids=args.doc, n=args.n, difficulty=args.difficulty, types=args.types
    )
    for index, question in enumerate(result.questions, start=1):
        print(f"\n[{index}] ({question.type.value} / {question.difficulty}) {question.question}")
        for letter, option in zip("ABCDEFGH", question.options, strict=False):
            print(f"    {letter}. {option}")
        print(f"    答案：{question.answer}")
        print(f"    解析：{question.explanation}")
        sources = ", ".join(f"{source.doc_id} p.{source.page}" for source in question.sources)
        print(f"    出处：{sources}")
    if result.dropped:
        print(f"\n丢弃 {len(result.dropped)} 题：{json.dumps(result.dropped, ensure_ascii=False)[:500]}")
    if not result.questions:
        print("未生成任何可用题目（证据不足或校验全部失败）")
    return 0


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from lectureqa.eval.runner import run_evaluation

    report = run_evaluation(settings, Path(args.testset), k=args.k, judge=args.judge)
    print(json.dumps(report.metrics, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace, _settings: Settings) -> int:
    import uvicorn

    uvicorn.run(
        "lectureqa.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_sample(args: argparse.Namespace, _settings: Settings) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from make_sample_pdfs import build_sample_decks  # type: ignore[import-not-found]

    written = build_sample_decks(Path(args.out))
    for path in written:
        print(f"已生成 {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lectureqa", description="LectureQA 课程讲义问答助手")
    parser.add_argument("--verbose", action="store_true", help="打印调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="构建索引")
    p_ingest.add_argument("paths", nargs="*", help="指定 PDF 路径（默认扫描 DATA_DIR）")
    p_ingest.add_argument("--keep", action="store_true", help="追加而不是重建索引")
    p_ingest.set_defaults(func=cmd_ingest)

    p_docs = sub.add_parser("documents", help="列已索引讲义")
    p_docs.set_defaults(func=cmd_documents)

    p_search = sub.add_parser("search", help="只做检索，查看证据")
    p_search.add_argument("query")
    p_search.add_argument("--doc", action="append", help="限定 doc_id，可重复")
    p_search.add_argument("--top-k", type=int, default=None)
    p_search.set_defaults(func=cmd_search)

    p_ask = sub.add_parser("ask", help="提问")
    p_ask.add_argument("question")
    p_ask.add_argument("--doc", action="append", help="限定 doc_id，可重复")
    p_ask.add_argument("--top-k", type=int, default=None)
    p_ask.add_argument(
        "--web",
        action="store_true",
        help="讲义证据不足时用网络补充（非讲义内容会单独标注）",
    )
    p_ask.set_defaults(func=cmd_ask)

    p_quiz = sub.add_parser("quiz", help="生成 Quiz")
    p_quiz.add_argument("--topic", required=True)
    p_quiz.add_argument("--doc", action="append")
    p_quiz.add_argument("-n", type=int, default=5)
    p_quiz.add_argument("--difficulty", default="mixed", choices=["easy", "medium", "hard", "mixed"])
    p_quiz.add_argument(
        "--types",
        nargs="+",
        default=None,
        choices=["mcq", "true_false", "short_answer"],
    )
    p_quiz.set_defaults(func=cmd_quiz)

    p_eval = sub.add_parser("eval", help="跑评估实验")
    p_eval.add_argument("--testset", default="eval/testset.sample.jsonl")
    p_eval.add_argument("-k", type=int, default=6)
    p_eval.add_argument("--judge", action="store_true", help="额外调用 LLM-as-judge")
    p_eval.set_defaults(func=cmd_eval)

    p_serve = sub.add_parser("serve", help="启动 FastAPI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_sample = sub.add_parser("sample", help="生成用于自测的示例讲义 PDF")
    p_sample.add_argument("--out", default="data/sample")
    p_sample.set_defaults(func=cmd_sample)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    try:
        return int(args.func(args, settings) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底，保证退出码可读
        print(f"错误：{exc}", file=sys.stderr)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
