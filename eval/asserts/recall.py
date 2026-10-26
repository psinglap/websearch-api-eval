"""Metric 7 - Recall against a run-time ground-truth list.

Standard: set recall as used by DeepSearchQA-style list questions and classic
IR recall (|retrieved AND relevant| / |relevant|). The relevant set is pulled
at run time from open APIs by ground_truth/pull_*.py and saved to
ground_truth/{qid}.json as {"items": [{"url", "title", "date"}...]}.
URLs are compared after normalization (lib/urls.py). Both the search results
and the URLs cited in the answer count as "retrieved" (reported separately).
Rows without a ground-truth file are N/A.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import EVAL_DIR, ctx, log, not_applicable, result
from lib.urls import normalize_url


def load_truth(v: dict) -> dict | None:
    gt_dir = os.environ.get("EVAL_GT_DIR")  # fixture runs point this at tests/fixtures/ground_truth
    p = (Path(gt_dir) / f"{v.get('qid')}.json") if gt_dir else EVAL_DIR / (v.get("ground_truth_file") or f"ground_truth/{v.get('qid')}.json")
    if not p.exists():
        return None
    return json.loads(p.read_text())


def compute(md: dict, output: str, truth: dict) -> dict:
    gold = {normalize_url(i["url"]) for i in truth.get("items", []) if i.get("url")}
    got = {normalize_url(r.get("url", "")) for r in md.get("results", [])}
    cited = {normalize_url(u) for u in re.findall(r"https?://[^\s)\]>\"']+", output or "")}
    cited |= {normalize_url(s["url"]) for s in md.get("answer_sources", [])
              if f"[{s['n']}]" in (output or "")}
    hit = gold & got
    hit_any = gold & (got | cited)
    return {"n_gold": len(gold), "n_hit": len(hit), "recall": (len(hit) / len(gold)) if gold else None,
            "recall_incl_answer": (len(hit_any) / len(gold)) if gold else None, "hits": sorted(hit)}


def get_assert(output, context):
    md, v = ctx(context)
    truth = load_truth(v)
    if truth is None:
        return not_applicable(f"no ground_truth/{v.get('qid')}.json")
    r = compute(md, str(output), truth)
    if r["recall"] is None:
        return not_applicable("ground truth list is empty (correct answer may be 'none')")
    log("recall", md, v, r)
    return result(True, r["recall"], f"recall {r['n_hit']}/{r['n_gold']}", {"recall": r["recall"]})
