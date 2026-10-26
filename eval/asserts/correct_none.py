"""Metric 3 - Correct "none".

Standard: SimpleQA grading with the gold target "NONE" (nothing qualifying in
the window), applied with FreshQA's STRICT mode (Vu et al. 2023,
https://arxiv.org/abs/2310.03214 ; https://github.com/freshllms/freshqa):
under strict mode an answer is credited only if it is correct AND contains no
outdated or hallucinated information presented as current; false-premise
questions must be explicitly rebutted.

Logic:
  expect_none = true  -> pass if the answer says none/not yet AND the strict grader
                         finds no stale item presented as in-window (score 1), else 0
  expect_none = false -> pass if the answer does NOT claim none (score 1); a false
                         "none" is a miss (0). Rows where the key is unfilled are UNGRADED.
"""
from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, is_error_output, log, result, says_none, ungraded
from lib import keys, llm

SCHEMA = {"type": "object", "properties": {
    "says_none": {"type": "boolean"}, "stale_or_hallucinated_as_current": {"type": "boolean"},
    "false_premise_rebutted": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["says_none", "stale_or_hallucinated_as_current", "false_premise_rebutted", "reason"],
    "additionalProperties": False}

STRICT = """FreshQA STRICT grading. The current time is the time of the run. The correct answer to the question below is that NOTHING qualifying exists within the requested time window (gold: NONE). Context from the human answer key: {note}

Question: {question} (time window: last {window} hours)
Response: {response}

Decide:
- says_none: does the response clearly say that nothing qualifying was found / has happened yet?
- stale_or_hallucinated_as_current: does the response present any older item (outside the window, e.g. a 2020 or 2024 event with the same name) or an invented item as if it were current?
- false_premise_rebutted: if the question presumes something happened, does the response say plainly that it has not? (true if the response says none)
Under strict mode the response is correct only if says_none is true and stale_or_hallucinated_as_current is false."""


def get_assert(output, context):
    md, v = ctx(context)
    k = keys.resolve(v)
    if not k["expect_none_known"]:
        return ungraded("expect_none not filled in answer_keys.csv")
    out = str(output)
    if is_error_output(out):
        return result(False, 0, "provider error", {"correct_none": 0})
    if not k["expect_none"]:
        ok = not says_none(out)
        log("correct_none", md, v, {"expect_none": False, "says_none": not ok})
        return result(ok, 1 if ok else 0, "answer exists; response " + ("did not" if ok else "wrongly") + " claim none",
                      {"correct_none": 1 if ok else 0})
    r = llm.grade("", STRICT.format(note=k.get("expected_answer") or "none", question=v.get("upstream_task") or v.get("query"),
                                    window=v.get("window_hours", 48), response=out), json_schema=SCHEMA)
    j = r["json"] or {}
    ok = bool(j.get("says_none")) and not j.get("stale_or_hallucinated_as_current", True)
    log("correct_none", md, v, {"expect_none": True, **j})
    return result(ok, 1 if ok else 0, f"strict: says_none={j.get('says_none')} stale={j.get('stale_or_hallucinated_as_current')}: {j.get('reason','')}",
                  {"correct_none": 1 if ok else 0})
