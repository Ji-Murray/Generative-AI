from __future__ import annotations

from lectureqa.learning.outline import order_lectures
from lectureqa.learning.progress import ProgressStore, grade_quiz_answer
from lectureqa.schemas import LectureOutline, QuizAttempt, QuizSource
from lectureqa.textutils import lecture_sort_key


def test_lecture_sort_key_prefers_real_lectures_then_samples() -> None:
    items = ["lecture10", "lecture2", "lecture01-course-overview", "appendix"]
    ordered = sorted(items, key=lecture_sort_key)
    # 正式 lecture2 / lecture10 在前；示例 lecture01-... 其次；无编号最后
    assert ordered.index("lecture2") < ordered.index("lecture10")
    assert ordered.index("lecture10") < ordered.index("lecture01-course-overview")
    assert ordered[-1] == "appendix"


def test_order_lectures_uses_filename_number_not_list_index() -> None:
    lectures = [
        LectureOutline(doc_id="lecture02-transformer", order=1, title="Transformer", summary=""),
        LectureOutline(doc_id="lecture3", order=2, title="Lecture 3: CNN", summary=""),
        LectureOutline(doc_id="lecture5", order=3, title="Lecture 5: Diffusion", summary=""),
        LectureOutline(doc_id="lecture2", order=4, title="Lecture 2: Bayes", summary=""),
    ]
    ordered = order_lectures(lectures)
    by_id = {item.doc_id: item.order for item in ordered}
    # 正式课件：第 N 讲 = LectureN
    assert by_id["lecture2"] == 2
    assert by_id["lecture3"] == 3
    assert by_id["lecture5"] == 5
    # 示例课件不占正式讲次
    assert by_id["lecture02-transformer"] >= 100
    assert [item.doc_id for item in ordered][:3] == ["lecture2", "lecture3", "lecture5"]


def test_grade_quiz_answer_mcq_and_bool() -> None:
    assert grade_quiz_answer(
        question_type="mcq", correct_answer="B", student_answer="B", options=["a", "b", "c"]
    )
    assert not grade_quiz_answer(
        question_type="mcq", correct_answer="B", student_answer="A", options=["a", "b", "c"]
    )
    assert grade_quiz_answer(
        question_type="true_false", correct_answer="True", student_answer="对"
    )
    assert not grade_quiz_answer(
        question_type="true_false", correct_answer="False", student_answer="True"
    )


def test_progress_store_records_attempts_and_weak_points(settings) -> None:
    store = ProgressStore(settings)
    store.record_attempt(
        QuizAttempt(
            attempt_id="a1",
            lecture_id="lecture5",
            question_id="q1",
            question="What is diffusion?",
            question_type="mcq",
            student_answer="A",
            correct_answer="B",
            correct=False,
            explanation="nope",
            concepts=["diffusion", "score matching"],
            source_pages=[QuizSource(doc_id="lecture5", page=12)],
        )
    )
    store.record_attempt(
        QuizAttempt(
            attempt_id="a2",
            lecture_id="lecture5",
            question_id="q2",
            question="Flow matching?",
            question_type="mcq",
            student_answer="B",
            correct_answer="B",
            correct=True,
            explanation="ok",
            concepts=["flow matching"],
            source_pages=[QuizSource(doc_id="lecture5", page=20)],
        )
    )

    state = store.load()
    assert state.lectures["lecture5"].quiz_attempts == 2
    assert state.lectures["lecture5"].quiz_correct == 1
    wrong = store.wrong_attempts("lecture5")
    assert len(wrong) == 1
    assert wrong[0].question_id == "q1"
    weak = store.weak_points()
    assert weak
    assert weak[0].lecture_id == "lecture5"
    assert "diffusion" in weak[0].concept or weak[0].error_count >= 1
