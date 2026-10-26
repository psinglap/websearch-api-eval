"""Automatic friction logging: every anomaly the harness sees becomes a
friction_log.csv row with source=auto, qid, provider, run id and raw JSON path.

Detected:
  non-2xx status (auth / rate limit / billing / other), in-body errors,
  timeouts, exceptions, warm-up failures, empty results, response schema
  drift vs the documented fields, a date filter that appears ignored (results
  dated before the window), a domain filter that appears ignored (results from
  other hosts), search latency over the use-case budget, cost above the price
  table, deprecation / sunset / warning headers or body warnings, and Python
  warnings raised by SDKs/libraries during the call.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from urllib.parse import urlsplit

from .settings import EVAL_DIR, prices, settings

sys.path.insert(0, str(EVAL_DIR))
from friction.log import append_row  # noqa: E402

DEPRECATION_HEADERS = ("deprecation", "sunset", "warning", "x-deprecated", "x-api-deprecated", "x-api-warn")


def a(category, step, actual, severity="green", expected=""):
    return {"category": category, "step": step, "actual": str(actual)[:600], "severity": severity, "expected": expected}


def http_status(status: int, body_excerpt: str) -> dict:
    if status in (401, 403):
        return a("auth", "search call", f"HTTP {status}: {body_excerpt}", "red", "2xx")
    if status == 429:
        return a("rate limit", "search call", f"HTTP 429: {body_excerpt}", "yellow", "2xx")
    if status in (402, 432, 433):
        return a("billing/credits", "search call", f"HTTP {status}: {body_excerpt}", "red", "2xx")
    return a("other", "search call", f"HTTP {status}: {body_excerpt}", "yellow", "2xx")


def schema_drift(raw: dict, raw_results: list[dict], adapter) -> list[dict]:
    out = []
    top = getattr(adapter, "EXPECTED_TOP_FIELDS", ())
    missing_top = [f for f in top if _get(raw, f) is None]
    if missing_top:
        out.append(a("docs", "response schema", f"documented top-level fields missing: {missing_top}", "green",
                     f"fields {list(top)} per docs"))
    exp = getattr(adapter, "EXPECTED_RESULT_FIELDS", ())
    if raw_results and exp:
        never = [f for f in exp if all(_get(r, f) in (None, "", []) for r in raw_results)]
        if never:
            out.append(a("docs", "response schema", f"documented per-result fields absent in every result: {never}",
                         "green", f"fields {list(exp)} per docs"))
    return out


def _get(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def filters_ignored(md: dict, results: list[dict], window_start, domains: list[str]) -> list[dict]:
    from .dates import parse_date
    out = []
    if window_start is not None and md.get("date_filter_applied"):
        slack = window_start - timedelta(hours=24)  # date-granular filters round to whole days
        old = [r["url"] for r in results
               if str(r.get("date_source") or "").startswith("provider")
               and not r.get("is_knowledge")
               and (d := parse_date(r.get("published_date"))) is not None and d < slack]
        if old:
            out.append(a("params", "date filter", f"{len(old)}/{len(results)} results dated before the window "
                         f"({md['date_filter_applied']}), e.g. {old[0]}", "yellow",
                         "no provider-dated result older than window start - 24h"))
    if domains and md.get("domain_filter_applied"):
        def ok(u):
            h = urlsplit(u).netloc.lower()
            return any(h == d or h.endswith("." + d) for d in domains)
        off = [r["url"] for r in results if r.get("url", "").startswith("http") and not ok(r["url"])]
        if off:
            out.append(a("params", "domain filter", f"{len(off)}/{len(results)} results outside {domains}, e.g. {off[0]}",
                         "yellow", f"only {domains}"))
    return out


def latency_over_budget(md: dict, usecase: str) -> list[dict]:
    budget = settings()["latency_budget_ms"].get(usecase)
    v = md.get("search_latency_ms") if md.get("search_latency_ms") is not None else md.get("end_to_end_ms")
    if budget and v is not None and v > budget:
        kind = "search" if md.get("search_latency_ms") is not None else "end-to-end"
        return [a("latency", "latency budget", f"{kind} latency {v:.0f} ms > budget {budget} ms", "green",
                  f"<= {budget} ms")]
    return []


def unexpected_cost(provider: str, md: dict) -> list[dict]:
    table = (prices()["search"].get(provider) or {}).get("per_request_usd")
    c = md.get("search_cost_usd")
    if table and c is not None and md.get("search_cost_source") == "provider_response" and c > 1.5 * table:
        return [a("billing/credits", "cost", f"provider-reported cost ${c:.4f} > 1.5x price table ${table:.4f}",
                  "yellow", f"~${table:.4f}")]
    return []


def deprecations(headers: dict, raw: dict) -> list[dict]:
    out = []
    for k, v in (headers or {}).items():
        if k.lower() in DEPRECATION_HEADERS:
            out.append(a("docs", "deprecation header", f"{k}: {v}", "green"))
    for key in ("warning", "warnings", "deprecation", "deprecated"):
        v = raw.get(key) if isinstance(raw, dict) else None
        if v:
            out.append(a("docs", f"response '{key}'", v, "green"))
    return out


def python_warnings(ws) -> list[dict]:
    return [a("sdk/install", "library warning", f"{w.category.__name__}: {w.message}", "green") for w in ws or []]


def flush(provider: str, items: list[dict], qid: str = "", run_id: str = "", raw_file: str = "") -> int:
    if os.environ.get("EVAL_NO_FRICTION_AUTOLOG"):
        return 0
    n = 0
    for it in items:
        try:
            append_row(provider, it["step"], it["actual"], it["severity"], expected=it.get("expected", ""),
                       source="auto", category=it["category"], qid=qid, run_id=run_id, raw_file=raw_file)
            n += 1
        except Exception:
            pass
    return n
