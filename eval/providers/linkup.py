"""Linkup Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://docs.linkup.so/pages/documentation/endpoints/search/reference.md (OpenAPI)
  https://docs.linkup.so/pages/documentation/endpoints/search/overview.md
  https://docs.linkup.so/pages/documentation/platform/pricing.md
Verified:
  POST https://api.linkup.so/v1/search, header Authorization: Bearer <key>
  q, depth flash|fast|standard|deep (standard used), outputType searchResults
  maxResults (min 1), fromDate/toDate YYYY-MM-DD, includeDomains [] (<=100)
  response: results[] {name,url,content,type}; no date field, no latency/cost field
  no full-page flag: `content` is an extracted passage (counted as content when > 200 chars)
  exhausted balance returns 429 (not 402)
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search

ENDPOINT = "https://api.linkup.so/v1/search"
NAME = "linkup"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("results",)
EXPECTED_RESULT_FIELDS = ("name", "url", "content")


def build_request(query, vars_, s):
    cfg = vars_.get("_config") or {}
    body = {"q": query, "depth": cfg.get("depth", "standard"), "outputType": "searchResults",
            "maxResults": s["num_results"], "includeImages": False}
    date_filter = None
    ws = search.window_start(vars_, s)
    if ws is not None and not vars_.get("_warmup"):
        body["fromDate"] = ws.date().isoformat()
        body["toDate"] = search.now_utc().date().isoformat()
        date_filter = f"{body['fromDate']}..{body['toDate']}"
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        body["includeDomains"] = domains
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"Authorization": f"Bearer {os.environ.get('LINKUP_API_KEY', '')}"},
            "_date_filter": date_filter, "_domain_filter": domains or None,
            "_notes": ["no per-result date field in Linkup response; dates from htmldate"]}


def parse(raw):
    res = [r for r in raw.get("results") or [] if r.get("type", "text") == "text"]
    return {"results": res, "provider_latency_ms": None, "provider_cost_usd": None, "extra": None}


def normalize(r):
    c = r.get("content") or ""
    return {"url": r.get("url"), "title": r.get("name"), "snippet": c[:500], "content": c,
            "published_date": None, "date_source": None}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
