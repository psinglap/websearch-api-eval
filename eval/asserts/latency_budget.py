"""Metric 1 - Latency vs budget (non-blocking; always passes).

Search latency = client-side time.perf_counter() around the HTTP request only,
on a persistent connection, after one discarded warm-up call per worker
(lib/search.py). Claude-native has no separable search time, so its
end-to-end time is used and flagged. Budgets: insurance 500 ms, finance/GTM
3000 ms (config/settings.yaml). p50/p95 are computed across all 30 calls in
analysis (numpy percentiles), following Artificial Analysis' time-per-query
reporting and You.com's latency classes (https://you.com/docs/evaluate-us).
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, log, result
from lib.settings import settings


def get_assert(output, context):
    md, v = ctx(context)
    budget = settings()["latency_budget_ms"].get(v.get("usecase"), 3000)
    lat = md.get("search_latency_ms")
    kind = "search"
    if lat is None:
        lat, kind = md.get("end_to_end_ms"), "end_to_end"
    if lat is None:
        return result(True, 0, "no latency recorded")
    within = lat <= budget
    log("latency_budget", md, v, {"latency_ms": lat, "kind": kind, "budget_ms": budget, "within": within,
                                  "provider_reported_ms": md.get("provider_reported_latency_ms")})
    return result(True, 1 if within else 0, f"{kind} latency {lat:.0f} ms vs budget {budget} ms",
                  {"search_latency_ms": lat, "within_latency_budget": 1 if within else 0})
