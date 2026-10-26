"""Tavily Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://docs.tavily.com/documentation/api-reference/endpoint/search.md (OpenAPI)
  https://docs.tavily.com/documentation/api-credits.md
Verified:
  POST https://api.tavily.com/search, header Authorization: Bearer tvly-...
  max_results (0-20, default 10); search_depth basic|advanced|fast|ultra-fast (default basic, used)
  time_range day|week|month|year ; start_date/end_date YYYY-MM-DD ("days" no longer in the spec)
  include_raw_content true|"markdown"|"text"; include_published_date true; include_usage true
  include_domains []; topic general|news|finance (default general, used for all queries)
  response: results[] {url,title,content,raw_content,published_date,score}; response_time (s); usage.credits
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search
from lib.settings import prices

ENDPOINT = "https://api.tavily.com/search"
NAME = "tavily"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("results", "response_time", "usage.credits")
EXPECTED_RESULT_FIELDS = ("url", "title", "content", "raw_content", "published_date")


def build_request(query, vars_, s):
    body = {"query": query, "max_results": s["num_results"], "search_depth": "basic",
            "include_raw_content": "markdown", "include_published_date": True, "include_usage": True}
    if os.environ.get("SEARCH_ONLY") == "1":  # latency pass: default basic search, no raw page content
        body.pop("include_raw_content")
    date_filter = None
    wh = search.window_hours(vars_, s)
    if wh is not None and not vars_.get("_warmup"):
        if wh <= 24:  # tightest preset; no hour-level filter
            body["time_range"] = "day"
        elif wh == 168:
            body["time_range"] = "week"
        else:
            body["start_date"] = search.window_start(vars_, s).date().isoformat()
            body["end_date"] = search.now_utc().date().isoformat()
        date_filter = body.get("time_range") or f"{body['start_date']}..{body['end_date']}"
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        body["include_domains"] = domains
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"Authorization": f"Bearer {os.environ.get('TAVILY_API_KEY', '')}"},
            "_date_filter": date_filter, "_domain_filter": domains or None, "_notes": []}


def parse(raw):
    rt = raw.get("response_time")
    credits = (raw.get("usage") or {}).get("credits")
    cost = credits * prices()["search"]["tavily"]["per_credit_usd"] if isinstance(credits, (int, float)) else None
    return {"results": raw.get("results") or [],
            "provider_latency_ms": round(float(rt) * 1000, 1) if rt is not None else None,
            "provider_cost_usd": cost, "extra": {"credits": credits}}


def normalize(r):
    return {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content") or "",
            "content": r.get("raw_content") or "", "published_date": r.get("published_date"),
            "date_source": "provider:published_date", "score": r.get("score")}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
