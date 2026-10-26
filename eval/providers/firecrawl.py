"""Firecrawl Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://docs.firecrawl.dev/api-reference/endpoint/search.md (OpenAPI)
  https://docs.firecrawl.dev/features/search.md ; https://docs.firecrawl.dev/billing.md
Verified:
  POST https://api.firecrawl.dev/v2/search, header Authorization: Bearer fc-...
  query (<=500 chars), limit (1-100, default 10), sources ["web"] (default)
  tbs: qdr:h|d|w|m|y or "cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY"
  includeDomains [] (mutually exclusive with excludeDomains)
  scrapeOptions {formats:["markdown"], onlyMainContent:true}
  response: data.web[] {url,title,description,markdown,metadata{...}}; creditsUsed
UNVERIFIED: a published-date field on web results (spec has none); we read
metadata.publishedTime / article:published_time if present, else htmldate.
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search
from lib.settings import prices

ENDPOINT = "https://api.firecrawl.dev/v2/search"
NAME = "firecrawl"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("data", "creditsUsed")
EXPECTED_RESULT_FIELDS = ("url", "title", "description", "markdown")
_DATE_KEYS = ("publishedTime", "article:published_time", "publishedDate", "datePublished",
              "og:published_time", "modifiedTime", "article:modified_time")


def build_request(query, vars_, s):
    body = {"query": query[:500], "limit": s["num_results"],
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
    date_filter = None
    wh = search.window_hours(vars_, s)
    if wh is not None and not vars_.get("_warmup"):
        if wh <= 1:
            body["tbs"] = "qdr:h"
        elif wh <= 24:  # qdr:h is a 1-hour window; multi-hour qdr values are not documented
            body["tbs"] = "qdr:d"
        elif wh == 168:
            body["tbs"] = "qdr:w"
        else:
            st = search.window_start(vars_, s)
            body["tbs"] = f"cdr:1,cd_min:{st:%m/%d/%Y},cd_max:{search.now_utc():%m/%d/%Y}"
        date_filter = body["tbs"]
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        body["includeDomains"] = domains
    if vars_.get("_warmup"):
        body.pop("scrapeOptions")
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"Authorization": f"Bearer {os.environ.get('FIRECRAWL_API_KEY', '')}"},
            "_date_filter": date_filter, "_domain_filter": domains or None, "_notes": []}


def parse(raw):
    data = raw.get("data") or {}
    web = data.get("web") if isinstance(data, dict) else data
    credits = raw.get("creditsUsed")
    cost = credits * prices()["search"]["firecrawl"]["per_credit_usd"] if isinstance(credits, (int, float)) else None
    return {"results": web or [], "provider_latency_ms": None, "provider_cost_usd": cost,
            "extra": {"creditsUsed": credits, "warning": raw.get("warning")}}


def normalize(r):
    md = r.get("metadata") or {}
    date, src = None, None
    for k in _DATE_KEYS:
        if md.get(k):
            date, src = md[k], f"provider:metadata.{k}"
            break
    return {"url": r.get("url") or md.get("sourceURL"), "title": r.get("title") or md.get("title"),
            "snippet": r.get("description") or md.get("description") or "",
            "content": r.get("markdown") or "", "published_date": date, "date_source": src}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
