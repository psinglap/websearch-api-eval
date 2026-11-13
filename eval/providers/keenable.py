"""Keenable Search API adapter (promptfoo Python provider).

Docs checked 2026-11-13:
  https://docs.keenable.ai/api-reference/search.md
  https://docs.keenable.ai/credits.md
Verified:
  POST https://api.keenable.ai/v1/search, header X-API-Key (from KEENABLE_API_KEY)
  POST https://api.keenable.ai/v1/search/public, header X-Keenable-Title (no key)
  query (required); mode pro|realtime (default pro); max_results (1-50, default 10)
  published_after/published_before date, ISO 8601, or relative offset; site (one host)
  snippet_max_length (180-10000); response: results[] {url,title,snippet,published_at,acquired_at}
  Search returns snippets only (no full page text; full pages need /v1/fetch, not called)
  keyed responses may include usage {sku,amount,credits,paid}; keyless calls have no usage
"""
from __future__ import annotations

import os

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import search

KEYED_ENDPOINT = "https://api.keenable.ai/v1/search"
PUBLIC_ENDPOINT = "https://api.keenable.ai/v1/search/public"
APP_TITLE = "websearch-api-eval"
NAME = "keenable"
# Documented fields; absence is auto-logged as schema drift (friction, category docs)
# snippet and published_at are omitted when Keenable does not know them
EXPECTED_TOP_FIELDS = ("query", "mode", "results")
EXPECTED_RESULT_FIELDS = ("url", "title")


def _api_key() -> str:
    return (os.environ.get("KEENABLE_API_KEY") or "").strip()


def build_request(query, vars_, s):
    cfg = vars_.get("_config") or {}
    body = {"query": query, "max_results": s["num_results"],
            "snippet_max_length": 2000}
    if cfg.get("mode"):
        body["mode"] = cfg["mode"]
    if os.environ.get("SEARCH_ONLY") == "1":  # latency pass: default snippet length
        body.pop("snippet_max_length")
    date_filter = None
    ws = search.window_start(vars_, s)
    if ws is not None and not vars_.get("_warmup"):
        body["published_after"] = ws.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_filter = body["published_after"]
    domains = search.domains_of(vars_)
    notes = ["full page content not available from Search (snippets only; /v1/fetch is not called)"]
    if domains and not vars_.get("_warmup"):
        # Keenable accepts one host via `site`, not an include_domains list
        body["site"] = domains[0]
        if len(domains) > 1:
            notes.append("Keenable site= takes one host; extra include-domains were omitted")
    key = _api_key()
    if key:
        url, headers = KEYED_ENDPOINT, {"X-API-Key": key, "X-Keenable-Title": APP_TITLE}
    else:
        url, headers = PUBLIC_ENDPOINT, {"X-Keenable-Title": APP_TITLE}
    return {"method": "POST", "url": url, "json": body, "headers": headers,
            "_date_filter": date_filter, "_domain_filter": domains or None, "_notes": notes}


def parse(raw):
    usage = raw.get("usage") or {}
    return {"results": raw.get("results") or [], "provider_latency_ms": None,
            "provider_cost_usd": None,
            "extra": {"mode": raw.get("mode"), "usage": usage or None, "warning": raw.get("warning")}}


def normalize(r):
    text = r.get("snippet") or r.get("description") or ""
    date = r.get("published_at")
    return {"url": r.get("url"), "title": r.get("title"), "snippet": text[:500],
            "content": text, "published_date": date,
            "date_source": "provider:published_at" if date else None}


def call_api(prompt, options, context):
    return search.run(NAME, SimpleNamespace(build_request=build_request, parse=parse, normalize=normalize), prompt, options, context)
