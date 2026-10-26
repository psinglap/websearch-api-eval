"""You.com Web Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://you.com/docs/openapi/web-search.json (OpenAPI)
  https://you.com/docs/guides/search.md
  https://you.com/docs/guides/search/request-controls.md
  https://you.com/docs/guides/search/retrieve-page-content.md
  https://you.com/docs/guides/search/knowledge.md
Verified:
  POST https://ydc-index.io/v1/search, header X-API-Key
  count (1-100, default 10, PER SECTION: web and news each up to count)
  freshness: day|week|month|year or "YYYY-MM-DDtoYYYY-MM-DD"
  extraction: {extraction_mode: full_page, full_page: {extraction_formats: [markdown]}} (POST only)
  livecrawl / livecrawl_formats are deprecated (not used)
  include_domains: strict allowlist (POST body)
  knowledge: "core" -> results.knowledge[] {type,title,description,attribution[],as_of} (POST only)
  response: results.web[] / results.news[] {url,title,description,snippets[],page_age,contents.markdown}
  metadata.latency (units not documented; example 0.342 looks like seconds -> converted when < 100)
Fairness choices: web+news are merged in API order (web first) and capped at
num_results (10) so every provider is judged on <= 10 results.
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search

ENDPOINT = "https://ydc-index.io/v1/search"
NAME = "youcom"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("results", "metadata.latency")
EXPECTED_RESULT_FIELDS = ("url", "title", "page_age", "contents.markdown")


def build_request(query, vars_, s):
    cfg = vars_.get("_config") or {}
    body = {"query": query, "count": s["num_results"],
            "extraction": {"extraction_mode": "full_page", "full_page": {"extraction_formats": ["markdown"]}}}
    if os.environ.get("SEARCH_ONLY") == "1":  # latency pass: provider's default search, no page content
        body.pop("extraction")
    notes, date_filter = [], None
    wh = search.window_hours(vars_, s)
    if wh is not None and not vars_.get("_warmup"):
        if wh <= 24:  # real-time / 24h: tightest preset (no hour-level filter in the API)
            body["freshness"] = "day"
        elif wh == 168:
            body["freshness"] = "week"
        else:
            start = search.window_start(vars_, s).date().isoformat()
            body["freshness"] = f"{start}to{search.now_utc().date().isoformat()}"
        date_filter = body["freshness"]
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        body["include_domains"] = domains
    if cfg.get("knowledge"):
        body["knowledge"] = cfg["knowledge"]
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"X-API-Key": os.environ.get("YDC_API_KEY", ""), "Content-Type": "application/json"},
            "_date_filter": date_filter, "_domain_filter": domains or None, "_notes": notes}


def parse(raw):
    res = raw.get("results") or {}
    items = []
    for i, k in enumerate(res.get("knowledge") or []):
        items.append({**k, "_kind": "knowledge", "_i": i})
    web = [{**r, "_kind": "web"} for r in res.get("web") or []]
    news = [{**r, "_kind": "news"} for r in res.get("news") or []]
    items += (web + news)[:10]
    lat = (raw.get("metadata") or {}).get("latency")
    lat_ms = None
    if isinstance(lat, (int, float)):
        lat_ms = round(lat * 1000, 1) if lat < 100 else float(lat)
    return {"results": items, "provider_latency_ms": lat_ms, "provider_cost_usd": None,
            "extra": {"n_web": len(web), "n_news": len(news), "n_knowledge": len(res.get("knowledge") or []),
                      "metadata_latency_raw": lat}}


def normalize(r):
    if r.get("_kind") == "knowledge":
        src = ", ".join(a.get("name", "") for a in r.get("attribution") or [])
        return {"url": f"urn:youcom:knowledge:{r.get('_i')}", "title": r.get("title"),
                "snippet": r.get("description"), "content": f"{r.get('description','')} (source: {src})",
                "published_date": r.get("as_of"), "date_source": "provider:as_of",
                "is_knowledge": True, "attribution": src}
    contents = r.get("contents") or {}
    snippets = r.get("snippets") or []
    return {"url": r.get("url"), "title": r.get("title"),
            "snippet": " ".join(snippets) or r.get("description") or "",
            "content": contents.get("markdown") or contents.get("html") or "",
            "published_date": r.get("page_age"), "date_source": "provider:page_age",
            "section": r.get("_kind")}


def call_api(prompt, options, context):
    label = ((options or {}).get("config") or {}).get("provider_name", NAME)
    return search.run(label, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
