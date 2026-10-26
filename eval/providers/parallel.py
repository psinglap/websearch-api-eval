"""Parallel Search API adapter (promptfoo Python provider).

Docs checked 2026-10-08:
  https://docs.parallel.ai/api-reference/search/search.md (OpenAPI)
  https://docs.parallel.ai/search/search-migration-guide.md
  https://docs.parallel.ai/search/advanced-search-settings.md
  https://docs.parallel.ai/search/modes.md ; https://docs.parallel.ai/getting-started/pricing.md
Verified:
  POST https://api.parallel.ai/v1/search (GA; v1beta is legacy), header x-api-key, no beta header
  search_queries [..] (required), objective (optional - not sent: the agent's search call is the query string)
  mode turbo|fast|basic|advanced (default advanced) - provider default used unless config.mode set
  advanced_settings.max_results (default 10, cap 20)
  advanced_settings.source_policy.after_date "YYYY-MM-DD" ; .include_domains []
  advanced_settings.excerpt_settings.max_chars_per_result
  Search returns excerpts only (no full page text; full pages need /v1/extract, not called)
  response: results[] {url,title,publish_date,excerpts[]}, search_id, usage[] {name,count}
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search
from lib.settings import prices

ENDPOINT = "https://api.parallel.ai/v1/search"
NAME = "parallel"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
EXPECTED_TOP_FIELDS = ("results", "search_id")
EXPECTED_RESULT_FIELDS = ("url", "title", "publish_date", "excerpts")


def build_request(query, vars_, s):
    cfg = vars_.get("_config") or {}
    adv = {"max_results": s["num_results"], "excerpt_settings": {"max_chars_per_result": 10000}}
    if os.environ.get("SEARCH_ONLY") == "1":  # latency pass: default excerpts (Search always returns excerpts)
        adv.pop("excerpt_settings")
    body = {"search_queries": [query], "advanced_settings": adv}
    if cfg.get("mode"):
        body["mode"] = cfg["mode"]
    date_filter, sp = None, {}
    ws = search.window_start(vars_, s)
    if ws is not None and not vars_.get("_warmup"):
        sp["after_date"] = ws.date().isoformat()
        date_filter = sp["after_date"]
    domains = search.domains_of(vars_)
    if domains and not vars_.get("_warmup"):
        sp["include_domains"] = domains
    if sp:
        adv["source_policy"] = sp
    return {"method": "POST", "url": ENDPOINT, "json": body,
            "headers": {"x-api-key": os.environ.get("PARALLEL_API_KEY", "")},
            "_date_filter": date_filter, "_domain_filter": domains or None,
            "_notes": ["full page content not available from Search (excerpts only)"]}


def parse(raw):
    mode = (raw.get("mode") or "advanced")
    by_mode = prices()["search"]["parallel"].get("per_request_usd_by_mode", {})
    return {"results": raw.get("results") or [], "provider_latency_ms": None,
            "provider_cost_usd": by_mode.get(mode),
            "extra": {"search_id": raw.get("search_id"), "usage": raw.get("usage"), "warnings": raw.get("warnings")}}


def normalize(r):
    ex = r.get("excerpts") or []
    text = "\n".join(ex)
    return {"url": r.get("url"), "title": r.get("title"), "snippet": text[:500],
            # excerpts are long markdown passages; counted as content when > 200 chars
            "content": text, "published_date": r.get("publish_date"), "date_source": "provider:publish_date",
            "content_is_excerpt": True}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
