"""Shared runner for the six search-API providers (promptfoo Python providers).

Each adapter in providers/*.py supplies three functions:
  build_request(query, vars, s) -> dict(method, url, headers, json|params)
  parse(raw_json) -> dict(results=[raw result dicts], provider_latency_ms, provider_cost_usd, extra)
  normalize(raw_result) -> {url, title, snippet, content, published_date, date_source}

The runner does everything that must be identical across providers:
  - one discarded warm-up call per worker process (settings.warmup_mode)
  - client-side search latency = time.perf_counter() around the HTTP request
    only (a persistent httpx.Client so TLS/connection reuse is the same for all)
  - raw JSON saved to out/raw/{usecase}/{qid}/{provider}_{timestamp}.json
  - answer_mode=offline (default): no LLM call; the output is a compact JSON of
    the top-k normalized results (answers/grades come later from Claude Code via
    ./run.sh export). answer_mode=api: the fixed answer model is called.
  - errors caught and returned in metadata (never raised), and auto-logged to
    friction_log.csv (timeouts, 401/403, 429, 5xx, empty results)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import anomalies, mock
from .settings import EVAL_DIR, out_dir, prices, settings


_HTTP: dict[str, httpx.Client] = {}
_WARMED: set[str] = set()
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "x-api-token"}


class MissingKey(RuntimeError):
    pass


def http(name: str) -> httpx.Client:
    if name not in _HTTP:
        _HTTP[name] = httpx.Client(timeout=settings()["request_timeout_s"], http2=False,
                                   headers={"User-Agent": "search-eval-harness/1.0"})
    return _HTTP[name]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _send(name: str, req: dict) -> httpx.Response:
    if mock.ENABLED:  # offline fixture mode only (EVAL_MOCK=1)
        return mock.search_response(name.replace("youcom_knowledge", "youcom"), req)
    c = http(name)
    return c.request(req.get("method", "POST"), req["url"], headers=req.get("headers"),
                     json=req.get("json"), params=req.get("params"))


def warm_up(name: str, adapter, vars_: dict) -> dict | None:
    mode = "off" if mock.ENABLED else settings()["warmup_mode"]
    if name in _WARMED or mode == "off":
        return None
    _WARMED.add(name)
    info = {"mode": mode}
    try:
        t0 = time.perf_counter()
        if mode == "search":
            req = adapter.build_request(settings()["warmup_query"], {**vars_, "_warmup": True}, settings())
            r = _send(name, req)
        else:  # connect: open the TLS connection to the API host without spending credits
            req = adapter.build_request("warmup", vars_, settings())
            host = httpx.URL(req["url"]).copy_with(path="/", query=None)
            r = http(name).request("HEAD", host)
        info.update(status=r.status_code, ms=round((time.perf_counter() - t0) * 1000, 1))
    except Exception as e:  # warm-up failures are logged but never fail the test
        info["error"] = repr(e)
    return info


def _redact(headers: dict | None) -> dict:
    return {k: ("***" if k.lower() in SECRET_HEADERS else v) for k, v in (headers or {}).items()}


def save_raw(usecase: str, qid: str, provider: str, payload: dict) -> str:
    ts = now_utc().strftime("%Y%m%dT%H%M%S%fZ")
    d = out_dir() / "raw" / (usecase or "misc") / (qid or "noqid")
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{provider}_{ts}.json"
    p.write_text(json.dumps(payload, indent=1, default=str))
    return str(p.relative_to(EVAL_DIR)) if p.is_relative_to(EVAL_DIR) else str(p)


def search_cost(provider: str, raw: dict, provider_cost: float | None) -> tuple[float | None, str]:
    if provider_cost is not None:
        return float(provider_cost), "provider_response"
    p = prices()["search"].get(provider, {})
    v = p.get("per_request_usd")
    return (float(v) if v is not None else None), "price_table"


def results_block(results: list[dict], k: int, chars: int) -> str:
    lines = []
    for i, r in enumerate(results[:k], 1):
        body = (r.get("content") or r.get("snippet") or "").strip().replace("\r", "")
        body = body[:chars]
        date = r.get("published_date") or "unknown"
        lines.append(f"[{i}] {r.get('title') or ''}\nURL: {r.get('url')}\nPublished: {date}\n{body}\n")
    return "\n".join(lines) if lines else "(no results returned)"


def _load_prompt(name: str) -> str:
    return (EVAL_DIR / "prompts" / name).read_text()


def answer(query: str, results: list[dict], vars_: dict | None = None) -> dict:
    """The agent's answer step: upstream task + needs_back + top-k results -> cited answer."""
    s = settings()
    vars_ = vars_ or {}
    k, chars = s["answer_top_k"], s["answer_chars_per_result"]
    system = _load_prompt("answer_system.txt").format(now_utc=now_utc().strftime("%Y-%m-%d %H:%M"))
    user = _load_prompt("answer_user.txt").format(
        upstream_task=vars_.get("upstream_task") or query,
        needs_back=vars_.get("needs_back") or "a direct answer with citations",
        query=query, k=k, results_block=results_block(results, k, chars))
    from . import llm  # api mode only: keeps the offline path free of the Anthropic SDK
    return llm.complete(system, user)


def compact_results(results: list[dict], k: int, chars: int = 500) -> str:
    """Offline-mode provider output: top-k normalized results as compact JSON (no LLM)."""
    return json.dumps([{"n": i, "title": r.get("title"), "url": r.get("url"),
                        "date": r.get("published_date"),
                        "snippet": (r.get("snippet") or r.get("content") or "")[:chars]}
                       for i, r in enumerate(results[:k], 1)], ensure_ascii=False)


def friction(provider: str, step: str, actual: str, severity: str, category: str = "other",
             qid: str = "", run_id: str = "", raw_file: str = "") -> None:
    """Single auto friction row (used by the Claude-native arm)."""
    anomalies.flush(provider, [anomalies.a(category, step, actual, severity)], qid, run_id, raw_file)


def run(provider: str, adapter, prompt: str, options: dict, context: dict) -> dict:
    """Entry point used by every providers/*.py call_api()."""
    s = settings()
    vars_ = dict((context or {}).get("vars") or {})
    vars_["_config"] = (options or {}).get("config") or {}
    query = str(vars_.get("query") or prompt).strip()
    usecase, qid = str(vars_.get("usecase", "")), str(vars_.get("qid", ""))
    run_id = str((context or {}).get("evaluationId") or vars_.get("__evalId") or "")
    md: dict = {
        "provider": provider, "qid": qid, "usecase": usecase, "query": query,
        "requested_at_utc": now_utc().isoformat(), "results": [], "n_results": 0,
        "search_latency_ms": None, "answer_latency_ms": None, "end_to_end_ms": None,
        "provider_reported_latency_ms": None, "content_in_one_call": False,
        "tokens_in": 0, "tokens_out": 0, "search_cost_usd": None, "search_cost_source": None,
        "llm_cost_usd": 0.0, "error": None, "error_type": None, "http_status": None,
        "answer_mode": s.get("answer_mode", "offline"),
        "answer_model": s["answer_model"] if s.get("answer_mode") == "api" else None,
        "date_filter_applied": None, "run_id": run_id,
        "repeat_index": (context or {}).get("repeatIndex", vars_.get("__repeatIndex")),
        "freshness": vars_.get("freshness"), "freshness_tier": vars_.get("freshness_tier"),
        "window_hours": vars_.get("window_hours"), "score_window_hours": vars_.get("score_window_hours"),
    }
    found: list[dict] = []
    t_start = time.perf_counter()
    md["warmup"] = warm_up(provider, adapter, vars_)
    if (md["warmup"] or {}).get("error") or (md["warmup"] or {}).get("status", 200) >= 400:
        found.append(anomalies.a("other", "warm-up call", f"warm-up failed: {md['warmup']}", "green"))
    raw, req, headers, t0 = None, None, {}, None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            req = adapter.build_request(query, vars_, s)
            md["date_filter_applied"] = req.pop("_date_filter", None)
            md["domain_filter_applied"] = req.pop("_domain_filter", None)
            md["notes"] = req.pop("_notes", [])
            md["variant"] = vars_["_config"].get("variant")
            auth = [v for k, v in (req.get("headers") or {}).items() if k.lower() in SECRET_HEADERS]
            if not mock.ENABLED and any(not str(v).replace("Bearer", "").strip() for v in auth):
                raise MissingKey("API key env var is empty - add it to eval/.env")
            t0 = time.perf_counter()
            resp = _send(provider, req)
            md["search_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            md["http_status"] = resp.status_code
            headers = dict(resp.headers)
            md["rate_limit_headers"] = {k: v for k, v in headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"}
            try:
                raw = resp.json()
            except Exception:
                raw = {"_non_json_body": resp.text[:5000]}
            if not 200 <= resp.status_code < 300:
                md["error_type"] = "rate_limit" if resp.status_code == 429 else f"http_{resp.status_code}"
                md["error"] = f"HTTP {resp.status_code}: {json.dumps(raw)[:400]}"
                found.append(anomalies.http_status(resp.status_code, json.dumps(raw)[:300]))
        except MissingKey as e:
            md["error_type"], md["error"] = "missing_key", str(e)
            found.append(anomalies.a("auth", "configuration", md["error"], "red", "key set in .env"))
        except httpx.TimeoutException as e:
            md["search_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1) if t0 else None
            md["error_type"], md["error"] = "timeout", f"timeout: {e!r}"
            found.append(anomalies.a("latency", "search call", md["error"], "yellow", "response within timeout"))
        except Exception as e:
            md["error_type"], md["error"] = "exception", f"{type(e).__name__}: {e}"
            md["traceback"] = traceback.format_exc()[-2000:]
            found.append(anomalies.a("other", "search call", md["error"], "yellow"))

        results: list[dict] = []
        if raw is not None and md["error"] is None:
            try:
                parsed = adapter.parse(raw)
                raw_results = parsed.get("results", [])
                results = [adapter.normalize(r) for r in raw_results]
                results = [r for r in results if r.get("url")]
                md["provider_reported_latency_ms"] = parsed.get("provider_latency_ms")
                cost, src = search_cost(provider, raw, parsed.get("provider_cost_usd"))
                md["search_cost_usd"], md["search_cost_source"] = cost, src
                md["provider_extra"] = parsed.get("extra")
                found += anomalies.schema_drift(raw, [r for r in raw_results if r.get("_kind") != "knowledge"], adapter)
            except Exception as e:
                md["error_type"], md["error"] = "parse_error", f"parse: {type(e).__name__}: {e}"
                found.append(anomalies.a("docs", "parse response", md["error"], "yellow", "documented schema"))
    found += anomalies.python_warnings(caught)
    if md["search_cost_usd"] is None and md["error_type"] not in (None, "parse_error"):
        md["search_cost_usd"], md["search_cost_source"] = 0.0, "error_not_billed_assumed"

    md["results"] = results
    md["n_results"] = len(results)
    md["content_in_one_call"] = any(len((r.get("content") or "")) > 200 for r in results)
    md["content_chars_top5"] = sum(len(r.get("content") or "") for r in results[:5])
    if md["error"] is None and not results:
        md["error_type"] = "empty_results"
        found.append(anomalies.a("results quality", "search call", "empty result list", "green", ">= 1 result"))
    if md["error"] is None:
        found += anomalies.filters_ignored(md, results, window_start(vars_, s), domains_of(vars_))
        found += anomalies.deprecations(headers, raw if isinstance(raw, dict) else {})
        found += anomalies.unexpected_cost(provider, md)
    found += anomalies.latency_over_budget(md, usecase)

    md["raw_file"] = save_raw(usecase, qid, provider, {
        "provider": provider, "qid": qid, "query": query, "requested_at_utc": md["requested_at_utc"],
        "request": {k: (v if k != "headers" else _redact(v)) for k, v in (req or {}).items()},
        "http_status": md["http_status"], "response_headers": _redact(headers),
        "search_latency_ms": md["search_latency_ms"], "error": md["error"], "response": raw,
    })

    output = ""
    if md["error"] and md["error_type"] != "empty_results":
        output = f"[SEARCH ERROR] {md['error']}"
    elif md["answer_mode"] != "api":
        output = compact_results(results, s["answer_top_k"])
    else:
        try:
            a = answer(query, results, vars_)
            output = a["text"]
            md.update(answer_latency_ms=a["latency_ms"], tokens_in=a["tokens_in"], tokens_out=a["tokens_out"],
                      llm_cost_usd=a["cost_usd"], answer_model_served=a["model"],
                      answer_stop_reason=a["stop_reason"])
            if a["stop_reason"] == "refusal":
                found.append(anomalies.a("other", "answer model", "answer model stop_reason=refusal", "yellow"))
        except Exception as e:
            md["answer_error"] = f"{type(e).__name__}: {e}"
            output = f"[ANSWER ERROR] {md['answer_error']}"
            found.append(anomalies.a("other", "answer model (Claude)", md["answer_error"], "yellow"))
    md["anomalies"] = found
    anomalies.flush(provider, found, qid, run_id, md["raw_file"])
    md["end_to_end_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
    md["total_cost_usd"] = round((md["search_cost_usd"] or 0) + (md["llm_cost_usd"] or 0), 6)
    md["answer_sources"] = [{"n": i, "url": r["url"]} for i, r in enumerate(results[: s["answer_top_k"]], 1)]
    return {
        "output": output,
        "metadata": md,
        "tokenUsage": {"total": md["tokens_in"] + md["tokens_out"], "prompt": md["tokens_in"],
                       "completion": md["tokens_out"]},
        "cost": md["total_cost_usd"],
        # promptfoo's own latency would include the answer-model call; we report
        # the search-only HTTP time so the promptfoo `latency` assertion and the
        # web view show search latency (end_to_end_ms stays in metadata).
        "latencyMs": md["search_latency_ms"] if md["search_latency_ms"] is not None else md["end_to_end_ms"],
    }


def domains_of(vars_: dict) -> list[str]:
    d = vars_.get("domains") or []
    if isinstance(d, str):
        d = [x.strip() for x in re.split(r"[,\s]+", d) if x.strip()]
    return list(d)


def window_hours(vars_: dict, s: dict) -> float | None:
    h = vars_.get("window_hours", s["date_filter_hours_default"])
    if h in (None, "", "none", "null", 0, "0"):
        return None
    return float(h)


def window_start(vars_: dict, s: dict) -> datetime | None:
    """Start of the provider-side date filter, or None when disabled for this test."""
    from datetime import timedelta
    h = window_hours(vars_, s)
    if h in (None, "", "none", "null", 0, "0"):
        return None
    return now_utc() - timedelta(hours=float(h))
