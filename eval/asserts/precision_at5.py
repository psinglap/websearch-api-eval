"""Metric 6 - Relevance, precision@5 (per-result binary judgments).

Standard: TREC-style binary relevance assessment (a document is relevant if it
contains information that helps answer the request; NIST TREC guidelines,
https://trec.nist.gov/data/reljudge_eng.html) with an LLM assessor, as in
Thomas et al. 2024, "Large language models can accurately predict searcher
preferences" (https://arxiv.org/abs/2309.10621). P@5 = relevant in top 5 / 5
(missing results count as non-relevant, the standard trec_eval convention).

Why not promptfoo context-relevance: it scores the fraction of context
SENTENCES relevant to the query (one number for the whole context), not a
per-result binary label, and our freshness metric 5 needs the per-result
labels. So the grader is called here and labels are cached in
out/cache/relevance/<row>.json for asserts/freshness.py and analysis.
"""
from __future__ import annotations

import fcntl
import json

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import cache_dir, ctx, log, result, row_key
from lib import llm

SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {"n": {"type": "integer"}, "relevant": {"type": "boolean"},
                                     "reason": {"type": "string"}},
    "required": ["n", "relevant", "reason"], "additionalProperties": False}}},
    "required": ["labels"], "additionalProperties": False}

PROMPT = """You are a TREC relevance assessor. For each numbered search result decide whether it is RELEVANT to the information need: it contains information that would help answer the request as stated, including its time window. A page on the right topic that is clearly outside the requested time window, or a generic landing page with no specific answer, is NOT relevant. Judge each result independently.

Information need: {task}
Search query sent: {query}
Time window: last {window} hours (now: {now})

Results:
{block}

Return one label per result number."""


def label_results(md: dict, v: dict, k: int = 5) -> list[dict]:
    res = md.get("results", [])[:k]
    if not res:
        return []
    p = cache_dir("relevance") / f"{row_key(md, v)}.json"
    # promptfoo may run assertions concurrently (freshness also needs these labels):
    # an exclusive file lock makes the second caller wait for and reuse the first result.
    with open(str(p) + ".lock", "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        if p.exists():
            return json.loads(p.read_text())
        return _label_and_cache(md, v, res, p)


def _label_and_cache(md, v, res, p):
    block = "\n".join(f"[{i}] {r.get('title') or ''} | {r.get('url')} | published: {r.get('published_date') or 'unknown'}\n"
                      f"{(r.get('content') or r.get('snippet') or '')[:1500]}\n" for i, r in enumerate(res, 1))
    out = llm.grade("", PROMPT.format(task=v.get("upstream_task") or v.get("query"), query=v.get("query"),
                                      window=v.get("window_hours", 48), now=md.get("requested_at_utc"), block=block),
                    json_schema=SCHEMA)
    labels = (out["json"] or {}).get("labels", [])
    by_n = {int(x["n"]): x for x in labels}
    labels = [{"n": i, "url": r.get("url"), "relevant": bool(by_n.get(i, {}).get("relevant", False)),
               "reason": by_n.get(i, {}).get("reason", "missing label")} for i, r in enumerate(res, 1)]
    p.write_text(json.dumps(labels, indent=1))
    return labels


def get_assert(output, context):
    md, v = ctx(context)
    labels = label_results(md, v)
    rel = sum(1 for x in labels if x["relevant"])
    p5 = rel / 5.0
    log("precision_at5", md, v, {"p_at_5": p5, "labels": labels})
    return result(True, p5, f"P@5 = {rel}/5", {"precision_at_5": p5})
