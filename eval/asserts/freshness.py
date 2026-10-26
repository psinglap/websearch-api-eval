"""Metrics 4 and 5 - Freshness: % of results inside the window, and age of the
newest RELEVANT result.

Standard: FreshQA (Vu et al. 2023, https://arxiv.org/abs/2310.03214) for
time-sensitive evaluation; per-result dating chain provider field -> htmldate
(extensive mode) -> URL pattern -> undated (see lib/dates.py; htmldate
evaluation https://htmldate.readthedocs.io/en/latest/evaluation.html).
Window = score_window_hours (real-time: 6 h for news/status; 24/48/168 h
otherwise). Undated results count as NOT fresh in the headline % and are
reported separately (pct_undated) so missing dates are visible.
Relevance for metric 5 comes from asserts/precision_at5.py labels (cached);
if labels are missing (always in answer_mode=offline), the newest dated result of any
relevance is reported and flagged (relevance_labels_used=false).
"""
from __future__ import annotations

from datetime import datetime

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, log, result
from lib.dates import age_hours, date_result, parse_date
from precision_at5 import label_results


def compute(md: dict, v: dict, labels: list[dict] | None = None, use_network: bool = True) -> dict:
    now = parse_date(md.get("requested_at_utc")) or datetime.now().astimezone()
    window = float(v.get("score_window_hours") or v.get("window_hours") or 48)
    rows = []
    for r in md.get("results", []):
        d, src = date_result(r, use_network=use_network)
        rows.append({"url": r.get("url"), "date": d.isoformat() if d else None, "date_source": src,
                     "age_h": round(age_hours(d, now), 2) if d else None})
    n = len(rows)
    in_win = [x for x in rows if x["age_h"] is not None and -24 <= x["age_h"] <= window]
    undated = [x for x in rows if x["age_h"] is None]
    rel_urls = {x["url"] for x in (labels or []) if x.get("relevant")}
    pool = [x for x in rows if x["url"] in rel_urls and x["age_h"] is not None] if labels is not None else \
        [x for x in rows if x["age_h"] is not None]
    newest = min((max(x["age_h"], 0.0) for x in pool), default=None)
    return {"n": n, "window_h": window, "pct_in_window": (len(in_win) / n) if n else 0.0,
            "pct_undated": (len(undated) / n) if n else 0.0, "newest_relevant_age_h": newest,
            "relevance_labels_used": labels is not None, "dates": rows,
            "date_sources": {s: sum(1 for x in rows if x["date_source"] == s) for s in {x["date_source"] for x in rows}}}


def get_assert(output, context):
    md, v = ctx(context)
    labels = None
    if md.get("answer_mode", "api") == "api":  # offline mode: no LLM relevance labels at run time
        try:
            labels = label_results(md, v)
        except Exception:
            labels = None
    f = compute(md, v, labels)
    log("freshness", md, v, f)
    named = {"freshness_pct_in_window": f["pct_in_window"], "freshness_pct_undated": f["pct_undated"]}
    if f["newest_relevant_age_h"] is not None:
        named["newest_relevant_age_h"] = f["newest_relevant_age_h"]
    newest = "n/a" if f["newest_relevant_age_h"] is None else f"{f['newest_relevant_age_h']:.1f} h"
    return result(True, f["pct_in_window"],
                  f"{f['pct_in_window']:.0%} of {f['n']} results within {f['window_h']:.0f} h; undated {f['pct_undated']:.0%}; "
                  f"newest relevant {newest}", named)
