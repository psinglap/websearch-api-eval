"""Claude built-in web search arm (promptfoo Python provider).

Docs checked 2026-10-08:
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
  claude-api skill (model IDs, effort, pause_turn handling, server-tool errors)
Verified:
  tool {"type": "web_search_20260318", "name": "web_search", "max_uses": N, "allowed_domains": [...]}
  (20260209+ run with dynamic filtering by default; 20260318 adds response_inclusion, default "full")
  results: web_search_tool_result.content = list of {type: web_search_result, url, title, page_age, encrypted_content}
  errors: HTTP 200 with content = {type: web_search_tool_result_error, error_code} (too_many_requests,
          invalid_tool_input, max_uses_exceeded, query_too_long, request_too_large, unavailable)
  citations on text blocks: {type: web_search_result_location, url, title, cited_text (<=150 chars)}
  usage.server_tool_use.web_search_requests ; $10 per 1,000 searches + tokens; errored searches not billed
  stop_reason pause_turn -> resend the assistant content unchanged to continue
  No date/freshness filter exists -> recorded as a note (not a failure).
Page content is encrypted, so content_in_one_call is False and freshness uses page_age.
Latency: there is no separable "search" time; we record end-to-end time of the
Messages call(s) as both end_to_end_ms and latencyMs, and search_latency_ms = None.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402

from lib import anomalies, llm, mock, search  # noqa: E402
from lib.settings import EVAL_DIR, llm_cost_usd, settings  # noqa: E402

NAME = "claude_native"


def _blocks_to_dicts(content) -> list[dict]:
    return [b.model_dump(mode="json", exclude_none=True) for b in content]


def render_answer(content: list[dict]) -> tuple[str, list[dict]]:
    """Turn text blocks + citations into '... [n]' text and an ordered source list."""
    sources: list[str] = []
    cits: list[dict] = []
    out = []
    for b in content:
        if b.get("type") != "text":
            continue
        txt = b.get("text", "")
        marks = []
        for c in b.get("citations") or []:
            url = c.get("url")
            if not url:
                continue
            if url not in sources:
                sources.append(url)
            n = sources.index(url) + 1
            cits.append({"n": n, "url": url, "title": c.get("title"), "cited_text": c.get("cited_text"),
                         "claim_text": txt.strip()})
            if f"[{n}]" not in marks:
                marks.append(f"[{n}]")
        out.append(txt + ("".join(marks) if marks else ""))
    return "".join(out).strip(), cits


def extract_results(content: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    results, errors, queries = [], [], []
    seen = set()
    for b in content:
        t = b.get("type")
        if t == "server_tool_use" and b.get("name") == "web_search":
            q = (b.get("input") or {}).get("query")
            if q:
                queries.append(q)
        if t == "web_search_tool_result":
            c = b.get("content")
            if isinstance(c, dict):  # error object inside a 200 response
                errors.append({"error_code": c.get("error_code"), "type": c.get("type")})
                continue
            for r in c or []:
                u = r.get("url")
                if u and u not in seen:
                    seen.add(u)
                    results.append({"url": u, "title": r.get("title"), "snippet": "", "content": "",
                                    "published_date": r.get("page_age"), "date_source": "provider:page_age"})
    return results, errors, queries


def call_api(prompt, options, context):
    s = settings()
    vars_ = (context or {}).get("vars") or {}
    query = str(vars_.get("query") or prompt).strip()
    upstream = vars_.get("upstream_task") or query
    usecase, qid = str(vars_.get("usecase", "")), str(vars_.get("qid", ""))
    model = s["answer_model"]
    tool = {"type": s["claude_web_search_tool"], "name": "web_search", "max_uses": int(s["claude_web_search_max_uses"])}
    notes = ["no date/freshness filter in Claude web_search (window stated in prompt only)"]
    domains = search.domains_of(vars_)
    if domains:
        tool["allowed_domains"] = domains
    system = (EVAL_DIR / "prompts" / "claude_native_system.txt").read_text().format(
        now_utc=search.now_utc().strftime("%Y-%m-%d %H:%M"))
    user = (f"Task from the user: {upstream}\nWhat you must return: {vars_.get('needs_back') or 'a direct answer with citations'}\n"
            f"Suggested search query: {query}\nTime window: last {vars_.get('window_hours', 48)} hours.")
    md = {"provider": NAME, "qid": qid, "usecase": usecase, "query": query, "requested_at_utc": search.now_utc().isoformat(),
          "results": [], "n_results": 0, "search_latency_ms": None, "answer_latency_ms": None, "end_to_end_ms": None,
          "provider_reported_latency_ms": None, "content_in_one_call": False, "tokens_in": 0, "tokens_out": 0,
          "search_cost_usd": 0.0, "search_cost_source": "usage.server_tool_use.web_search_requests",
          "llm_cost_usd": 0.0, "error": None, "error_type": None, "answer_model": model, "notes": notes,
          "date_filter_applied": None, "domain_filter_applied": domains or None, "tool": tool,
          "repeat_index": (context or {}).get("repeatIndex"), "freshness": vars_.get("freshness"),
          "window_hours": vars_.get("window_hours"), "freshness_tier": vars_.get("freshness_tier"),
          "score_window_hours": vars_.get("score_window_hours")}
    messages = [{"role": "user", "content": user}]
    all_content: list[dict] = []
    found: list[dict] = []
    run_id = str((context or {}).get("evaluationId") or vars_.get("__evalId") or "")
    raw_turns = []
    tin = tout = nsearch = 0
    t0 = time.perf_counter()
    output = ""
    try:
        for _ in range(int(s["claude_max_pause_turn_continuations"]) + 1):
            if mock.ENABLED:  # offline fixture mode only (EVAL_MOCK=1)
                msg = mock.claude_native_message(query)
            else:
                msg = llm.client().messages.create(
                    model=model, max_tokens=int(s["answer_max_tokens"]), system=system, messages=messages,
                    tools=[tool], output_config={"effort": s["answer_effort"]})
            content = _blocks_to_dicts(msg.content)
            raw_turns.append(msg.model_dump(mode="json"))
            u = llm.usage_of(msg)
            tin, tout, nsearch = tin + u["tokens_in"], tout + u["tokens_out"], nsearch + u["web_search_requests"]
            all_content += content
            md["stop_reason"], md["answer_model_served"] = msg.stop_reason, msg.model
            if msg.stop_reason != "pause_turn":
                break
            messages = [{"role": "user", "content": user}, {"role": "assistant", "content": content}]
        final_text_blocks = [b for b in all_content if b.get("type") == "text"]
        output, cits = render_answer(final_text_blocks)
        results, errors, queries = extract_results(all_content)
        md.update(results=results, n_results=len(results), citations=cits, search_errors=errors,
                  search_queries=queries, web_search_requests=nsearch)
        if errors:
            md["error_type"] = "in_body_search_error"
            md["error"] = "; ".join(e.get("error_code") or "?" for e in errors)
            found.append(anomalies.a("rate limit" if "too_many_requests" in md["error"] else "other",
                                     "web_search (in-body error, HTTP 200)", md["error"], "yellow"))
        if not results and not errors:
            md["error_type"] = "empty_results"
            found.append(anomalies.a("results quality", "web_search", "no search results (Claude may have skipped search)", "green"))
        if md.get("stop_reason") == "refusal":
            md["error_type"], md["error"] = "refusal", "stop_reason=refusal"
            found.append(anomalies.a("other", "messages call", "stop_reason=refusal", "yellow"))
        if len(raw_turns) > 1:
            found.append(anomalies.a("other", "messages call", f"pause_turn: {len(raw_turns)} requests needed", "green"))
    except anthropic.RateLimitError as e:
        md["error_type"], md["error"] = "rate_limit", f"429: {e}"
        found.append(anomalies.a("rate limit", "messages call", md["error"], "yellow"))
    except anthropic.APITimeoutError as e:
        md["error_type"], md["error"] = "timeout", f"timeout: {e}"
        found.append(anomalies.a("latency", "messages call", md["error"], "yellow"))
    except anthropic.APIStatusError as e:
        md["error_type"], md["error"] = f"http_{e.status_code}", f"HTTP {e.status_code}: {e}"
        found.append(anomalies.http_status(e.status_code, str(e)[:300]))
    except Exception as e:
        md["error_type"], md["error"] = "exception", f"{type(e).__name__}: {e}"
        md["traceback"] = traceback.format_exc()[-2000:]
        found.append(anomalies.a("other", "messages call", md["error"], "yellow"))
    md["end_to_end_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    md["answer_latency_ms"] = md["end_to_end_ms"]
    md["tokens_in"], md["tokens_out"] = tin, tout
    md["search_cost_usd"] = round(nsearch * llm_cost_usd(model, 0, 0, 1), 6) if nsearch else 0.0
    md["llm_cost_usd"] = llm_cost_usd(model, tin, tout)
    md["total_cost_usd"] = round(md["search_cost_usd"] + md["llm_cost_usd"], 6)
    md["answer_sources"] = [{"n": c["n"], "url": c["url"]} for c in md.get("citations", [])]
    md["raw_file"] = search.save_raw(usecase, qid, NAME, {
        "provider": NAME, "qid": qid, "query": query, "requested_at_utc": md["requested_at_utc"],
        "request": {"model": model, "tools": [tool], "system": system, "user": user},
        "error": md["error"], "response_turns": raw_turns})
    found += anomalies.latency_over_budget(md, usecase)
    md["anomalies"] = found
    anomalies.flush(NAME, found, qid, run_id, md["raw_file"])
    if md["error"] and not output:
        output = f"[SEARCH ERROR] {md['error']}"
    return {"output": output, "metadata": md,
            "tokenUsage": {"total": tin + tout, "prompt": tin, "completion": tout},
            "cost": md["total_cost_usd"], "latencyMs": md["end_to_end_ms"]}
