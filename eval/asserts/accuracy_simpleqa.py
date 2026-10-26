"""Metric 2 - Accuracy (0-2) via the official SimpleQA grader.

Standard: OpenAI simple-evals SimpleQA grader template, verbatim from
https://github.com/openai/simple-evals/blob/5e623c2b400af62a1278e23595f95b0853d7fe8a/simpleqa_eval.py
(GRADER_TEMPLATE; sha256 of our copy 063c04ea798f91c4706c050b66a721afc77a458b12d8f0d72286d4b0eee8a3ee,
fetched 2026-10-08; also byte-identical to youdotcom-oss/web-search-api-evals).
Grades: A=CORRECT -> 2, B=INCORRECT -> 0, C=NOT_ATTEMPTED -> 0 (parsed exactly as
simple-evals does: re.search(r"(A|B|C)"), default C). List answers that are
INCORRECT under SimpleQA can still earn 1 from asserts/partial_credit.py; the
0-2 combination is done in analysis/analyze.py.
Tolerances from the answer key are appended to the gold target, e.g.
"183.20 USD (acceptable tolerance: within +/-0.5%)".
"""
from __future__ import annotations

import re

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, is_error_output, log, result, ungraded, EVAL_DIR
from lib import keys, llm

TEMPLATE = (EVAL_DIR / "asserts" / "simpleqa_grader_template.txt").read_text()
GRADE_TO_SCORE = {"A": 2, "B": 0, "C": 0}
GRADE_NAME = {"A": "CORRECT", "B": "INCORRECT", "C": "NOT_ATTEMPTED"}


def simpleqa_grade(question: str, target: str, predicted: str) -> tuple[str, str]:
    prompt = TEMPLATE.format(question=question, target=target, predicted_answer=predicted)
    r = llm.grade("", prompt)
    m = re.search(r"(A|B|C)", r["text"])
    return (m.group(0) if m else "C"), r["text"]


def gold_target(k: dict) -> str:
    t = k["expected_answer"]
    if k.get("tolerance"):
        t += f" (acceptable tolerance: {k['tolerance']})"
    return t


def get_assert(output, context):
    md, v = ctx(context)
    k = keys.resolve(v)
    if not k["filled"]:
        return ungraded(f"answer key for {v.get('qid')} not filled in answer_keys.csv")
    if is_error_output(output):
        log("accuracy_simpleqa", md, v, {"grade": "C", "score": 0, "note": "provider error"})
        return result(False, 0, "provider error -> NOT_ATTEMPTED (0/2)", {"accuracy_0_2": 0})
    question = v.get("upstream_task") or v.get("query")
    grade, raw = simpleqa_grade(question, gold_target(k), str(output))
    score = GRADE_TO_SCORE[grade]
    log("accuracy_simpleqa", md, v, {"grade": grade, "score": score, "gold": gold_target(k), "grader_raw": raw})
    return result(grade == "A", score / 2, f"SimpleQA {grade}={GRADE_NAME[grade]} -> {score}/2",
                  {"accuracy_0_2": score, "simpleqa_correct": 1 if grade == "A" else 0,
                   "simpleqa_not_attempted": 1 if grade == "C" else 0})
