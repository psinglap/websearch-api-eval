"""Metric 2 (partial credit) - list answers that are partly right earn 1/2.

Equivalent to a promptfoo llm-rubric, implemented in python because the gold
list is resolved from answer_keys.csv at run time (llm-rubric only sees vars).
Rubric (fixed): PARTIAL if the response lists at least one item that matches
the gold list AND every item it presents as within the time window is either
in the gold list or verifiably on-topic and in-window; NO otherwise.
Analysis combines: SimpleQA A -> 2; else PARTIAL -> 1; else 0.
"""
from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, is_error_output, log, not_applicable, result, ungraded
from lib import keys, llm

SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["PARTIAL", "NO"]},
                                           "matched_items": {"type": "array", "items": {"type": "string"}},
                                           "reason": {"type": "string"}},
          "required": ["verdict", "matched_items", "reason"], "additionalProperties": False}

RUBRIC = """You grade a list-style answer from a search agent against a gold list written by a human at run time.
Question: {question}
Gold list (authoritative, captured at run time): {gold}
Response: {response}

Return PARTIAL if the response contains at least one item that matches an item in the gold list (same entity/event; wording may differ) and it does not present any item that contradicts the gold list or is clearly outside the time window as current. Otherwise return NO. List the matched gold items."""


def get_assert(output, context):
    md, v = ctx(context)
    k = keys.resolve(v)
    if not k["filled"]:
        return ungraded("answer key not filled")
    if k["expect_none"]:
        return not_applicable("expect_none test (scored by correct_none)")
    if is_error_output(output):
        return result(False, 0, "provider error", {"partial_credit": 0})
    r = llm.grade("", RUBRIC.format(question=v.get("upstream_task") or v.get("query"), gold=k["expected_answer"],
                                    response=output), json_schema=SCHEMA)
    j = r["json"] or {"verdict": "NO", "matched_items": [], "reason": "unparseable grader output"}
    ok = j["verdict"] == "PARTIAL"
    log("partial_credit", md, v, j)
    return result(ok, 1 if ok else 0, f"{j['verdict']}: {j['reason']}", {"partial_credit": 1 if ok else 0})
