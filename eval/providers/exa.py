"""Exa Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://exa.ai/docs/reference/search.md (OpenAPI v2.0.0)
  https://exa.ai/docs/admin/pricing.md
Verified:
  POST https://api.exa.ai/search, header x-api-key
  type instant|fast|auto(default, used)|deep-lite|deep|deep-reasoning ; numResults (1-100, default 10)
  startPublishedDate/endPublishedDate ISO 8601 ; includeDomains []
  contents.text true|{maxCharacters}; contents.maxAgeHours (0 = always livecrawl; livecrawl deprecated)
  response: results[] {url,title,publishedDate,author,text,highlights}; searchTime (ms); costDollars.total
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search

ENDPOINT = "https://api.exa.ai/search"
NAME = "exa"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("results", "costDollars.total", "searchTime")
EXPECTED_RESULT_FIELDS = ("url", "title", "publishedDate", "text")


def build_request(query, vars_, s):
    cfg = vars_.get("_config") or {}
    body = {"query": query, "type": cfg.get("type", "auto"), "numResults": s["num_results"],
            "contents": {"text": {"maxCharacters": 20000}}}
    if os.environ.get("SEARCH_ONLY") == "1":  # latency pass: default search, no page text
        body.pop("contents")
    date_filter = None
    ws = search.window_start(vars_, s)
    if ws is not None and not vars_.get("_warmup"):
        body["startPublishedDate"] = ws.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        date_filter = body["startPublishedDate"]
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        body["includeDomains"] = domains
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"x-api-key": os.environ.get("EXA_API_KEY", "")},
            "_date_filter": date_filter, "_domain_filter": domains or None, "_notes": []}


def parse(raw):
    cost = (raw.get("costDollars") or {}).get("total")
    st = raw.get("searchTime")
    return {"results": raw.get("results") or [], "provider_latency_ms": st,
            "provider_cost_usd": cost, "extra": {"requestId": raw.get("requestId")}}


def normalize(r):
    hl = r.get("highlights") or []
    text = r.get("text") or ""
    return {"url": r.get("url"), "title": r.get("title"),
            "snippet": " ".join(hl) if hl else text[:500], "content": text,
            "published_date": r.get("publishedDate"), "date_source": "provider:publishedDate"}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
