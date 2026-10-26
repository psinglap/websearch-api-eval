"""OFFLINE MOCK MODE (EVAL_MOCK=1) - produces clearly FAKE data so the whole
pipeline (promptfoo -> providers -> assertions -> export -> analysis/charts)
can be exercised without API keys. Never used in a live run.

Every fake URL is on the reserved `.invalid` TLD (RFC 2606) and every fake
text contains the word FIXTURE. Randomness is seeded per call, so fixture runs
are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

ENABLED = os.environ.get("EVAL_MOCK") == "1"

# fake per-provider characteristics (NOT measurements): median latency ms, accuracy skill, date coverage
PROFILE = {
    "youcom": (380, 0.70, 0.9), "tavily": (900, 0.62, 0.7), "exa": (450, 0.60, 0.95), "parallel": (1100, 0.66, 0.8),
    "firecrawl": (1500, 0.50, 0.3), "linkup": (1200, 0.55, 0.0), "claude_native": (9000, 0.68, 0.6),
    "youcom_knowledge": (420, 0.80, 0.9),
}


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12], 16))


def _sleep(provider: str, rng: random.Random):
    med = PROFILE.get(provider, (500, 0.5, 0.5))[0]
    ms = min(med * rng.lognormvariate(0, 0.35), 1500) * float(os.environ.get("EVAL_MOCK_LATENCY_SCALE", "1"))
    time.sleep(ms / 1000.0)


def qhash(query: str) -> str:
    return hashlib.sha1(query.encode()).hexdigest()[:8]


def _results(provider, query, rng, n=10):
    now = datetime.now(timezone.utc)
    cov = PROFILE.get(provider, (0, 0, 0.5))[2]
    out = []
    for i in range(n):
        age = rng.choice([0.5, 2, 5, 12, 20, 30, 47, 70, 150, 400]) * rng.uniform(0.7, 1.3)
        dated = rng.random() < cov
        out.append({"url": f"https://fixture.invalid/{provider}/{qhash(query)}/{i}",
                    "title": f"FIXTURE result {i + 1} for '{query[:40]}'",
                    "date": (now - timedelta(hours=age)).isoformat() if dated else None,
                    "text": f"FIXTURE page text {i + 1}. This fake page discusses {query}. " * 6})
    return out


def search_response(provider: str, req: dict) -> httpx.Response:
    body = req.get("json") or {}
    query = body.get("query") or body.get("q") or (body.get("search_queries") or [""])[0]
    rng = _rng(provider, query, time.time_ns())
    _sleep(provider, rng)
    if rng.random() < 0.03:
        return httpx.Response(rng.choice([429, 500, 503]), json={"error": "FIXTURE simulated failure"},
                              request=httpx.Request("POST", req["url"]))
    rs = _results(provider, query, rng, 0 if rng.random() < 0.03 else 10)
    if provider == "youcom":
        j = {"results": {"web": [{"url": r["url"], "title": r["title"], "description": r["text"][:120],
                                  "snippets": [r["text"][:200]], "page_age": r["date"],
                                  "contents": {"markdown": r["text"]}} for r in rs]},
             "metadata": {"latency": 0.2}}
        if body.get("knowledge"):
            j["results"]["knowledge"] = [{"type": "answer", "title": "FIXTURE knowledge", "description": "FIXTURE value 123.45",
                                          "attribution": [{"name": "FIXTURE data vendor"}], "as_of": datetime.now(timezone.utc).date().isoformat()}]
    elif provider == "tavily":
        j = {"results": [{"url": r["url"], "title": r["title"], "content": r["text"][:300], "raw_content": r["text"],
                          "published_date": r["date"], "score": 0.5} for r in rs], "response_time": 0.8,
             "usage": {"credits": 1}}
    elif provider == "exa":
        j = {"results": [{"url": r["url"], "title": r["title"], "publishedDate": r["date"], "text": r["text"]} for r in rs],
             "searchTime": 300, "costDollars": {"total": 0.007}}
    elif provider == "parallel":
        j = {"search_id": "FIXTURE", "results": [{"url": r["url"], "title": r["title"],
                                                  "publish_date": r["date"][:10] if r["date"] else None,
                                                  "excerpts": [r["text"]]} for r in rs]}
    elif provider == "firecrawl":
        j = {"data": {"web": [{"url": r["url"], "title": r["title"], "description": r["text"][:120], "markdown": r["text"],
                               "metadata": {"publishedTime": r["date"]} if r["date"] else {}} for r in rs]},
             "creditsUsed": 12}
    else:  # linkup
        j = {"results": [{"type": "text", "name": r["title"], "url": r["url"], "content": r["text"]} for r in rs]}
    return httpx.Response(200, json=j, request=httpx.Request("POST", req["url"]))


def _skill_for(text: str) -> tuple[str, float]:
    m = re.search(r"fixture\.invalid/([a-z_]+)/", text or "")
    p = m.group(1) if m else "claude_native"
    return p, PROFILE.get(p, (0, 0.5, 0))[1]


def llm_complete(system: str, user: str, json_schema: dict | None = None, model: str = "mock") -> dict:
    rng = _rng(user, time.time_ns())
    time.sleep(0.01)
    props = (json_schema or {}).get("properties", {})
    if "labels" in props:
        n = len(re.findall(r"^\[\d+\]", user, re.M))
        p, skill = _skill_for(user)
        j = {"labels": [{"n": i, "relevant": rng.random() < skill, "reason": "FIXTURE label"} for i in range(1, n + 1)]}
        text = json.dumps(j)
    elif "verdict" in props:
        p, skill = _skill_for(user)
        j = {"verdict": "PARTIAL" if rng.random() < skill else "NO", "matched_items": [], "reason": "FIXTURE"}
        text = json.dumps(j)
    elif "says_none" in props:
        p, skill = _skill_for(user)
        ok = rng.random() < skill
        j = {"says_none": ok, "stale_or_hallucinated_as_current": not ok and rng.random() < 0.5,
             "false_premise_rebutted": ok, "reason": "FIXTURE"}
        text = json.dumps(j)
    elif "Gold target:" in user and "Predicted answer:" in user:
        p, skill = _skill_for(user)
        r = rng.random()
        text = "A" if r < skill else ("C" if r < skill + 0.1 else "B")
        j = None
    else:  # answer generation
        urls = re.findall(r"URL: (\S+)", user)
        text = (f"FIXTURE ANSWER (fake, generated offline). The answer is based on the results [1][2].\n"
                f"- FIXTURE supporting point from {urls[0] if urls else 'no results'} [1]")
        if not urls:
            text = "NONE / not found\nFIXTURE: no results were returned."
        j = None
    tin = len(system + user) // 4
    return {"text": text, "json": j, "latency_ms": 10.0, "tokens_in": tin, "tokens_out": 60,
            "cost_usd": round(tin * 4e-6 + 60 * 2e-5, 6), "model": "mock-fixture", "stop_reason": "end_turn"}


class _Block(SimpleNamespace):
    def model_dump(self, **_):
        return {k: v for k, v in self.__dict__.items()}


def claude_native_message(query: str):
    rng = _rng("claude_native", query, time.time_ns())
    _sleep("claude_native", rng)
    rs = _results("claude_native", query, rng, 8)
    content = [
        _Block(type="server_tool_use", id="srvtoolu_fixture", name="web_search", input={"query": query}),
        _Block(type="web_search_tool_result", tool_use_id="srvtoolu_fixture",
               content=[{"type": "web_search_result", "url": r["url"], "title": r["title"],
                         "page_age": (datetime.fromisoformat(r["date"]).strftime("%B %d, %Y") if r["date"] else None),
                         "encrypted_content": "FIXTURE"} for r in rs]),
        _Block(type="text", text="FIXTURE ANSWER (fake). The answer is X.", citations=[
            {"type": "web_search_result_location", "url": rs[0]["url"], "title": rs[0]["title"],
             "cited_text": "FIXTURE page text 1. This fake page discusses", "encrypted_index": "FIXTURE"}]),
    ]
    if rng.random() < 0.05:
        content[1].content = {"type": "web_search_tool_result_error", "error_code": "unavailable"}
    usage = SimpleNamespace(input_tokens=6000, output_tokens=400, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=1))
    msg = SimpleNamespace(content=content, usage=usage, stop_reason="end_turn", model="mock-fixture")
    msg.model_dump = lambda **_: {"FIXTURE": True, "content": [b.model_dump() for b in content]}
    return msg
