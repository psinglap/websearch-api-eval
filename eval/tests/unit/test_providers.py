import json

import httpx
import pytest

from conftest import FIX, load_module
from lib import search
from lib.settings import settings

RESP = json.loads((FIX / "unit" / "provider_responses.json").read_text())
NAMES = ["youcom", "tavily", "exa", "parallel", "firecrawl", "linkup"]
VARS = {"qid": "G1", "usecase": "gtm", "query": "kafka lag", "window_hours": 48, "domains": "github.com",
        "upstream_task": "FIXTURE task", "needs_back": "list"}


@pytest.mark.parametrize("name", NAMES)
def test_parse_normalize(name):
    m = load_module(f"providers/{name}.py", f"prov_{name}")
    parsed = m.parse(RESP[name])
    res = [m.normalize(r) for r in parsed["results"]]
    assert res and all(r["url"] for r in res)
    assert set(res[0]) >= {"url", "title", "snippet", "content", "published_date", "date_source"}


@pytest.mark.parametrize("name", NAMES)
def test_build_request_filters(name):
    m = load_module(f"providers/{name}.py", f"prov_{name}")
    req = m.build_request("kafka lag", dict(VARS, _config={}), settings())
    body = json.dumps(req["json"])
    assert req["_date_filter"], "every search API here supports a date filter"
    assert "github.com" in body, "domain filter passed where supported"
    assert req["url"].startswith("https://")


def test_youcom_specifics():
    m = load_module("providers/youcom.py", "prov_y")
    r = m.build_request("q", dict(VARS, window_hours=24, _config={"knowledge": "core"}), settings())
    assert r["json"]["freshness"] == "day" and r["json"]["knowledge"] == "core"
    assert r["json"]["extraction"]["extraction_mode"] == "full_page" and "livecrawl" not in r["json"]
    p = m.parse(RESP["youcom"])
    assert p["provider_latency_ms"] == 342.0
    k = m.normalize(p["results"][0])
    assert k["is_knowledge"] and k["url"].startswith("urn:youcom:knowledge")
    r = m.build_request("q", dict(VARS, window_hours=168, _config={}), settings())
    assert r["json"]["freshness"] == "week"


def test_firecrawl_tbs_and_exa_timestamp():
    f = load_module("providers/firecrawl.py", "prov_f")
    assert f.build_request("q", dict(VARS, window_hours=24, _config={}), settings())["json"]["tbs"] == "qdr:d"
    assert f.build_request("q", dict(VARS, window_hours=48, _config={}), settings())["json"]["tbs"].startswith("cdr:1,cd_min:")
    e = load_module("providers/exa.py", "prov_e")
    j = e.build_request("q", dict(VARS, window_hours=6, _config={}), settings())["json"]
    assert j["startPublishedDate"].endswith("Z") and j["contents"]["text"]


def test_runner_offline_mode_no_llm(monkeypatch):
    """Default answer_mode=offline: search only, output = compact JSON of top results, no LLM call."""
    import json
    from lib import llm
    m = load_module("providers/tavily.py", "prov_t1")
    monkeypatch.setattr(search, "_send", lambda name, req: httpx.Response(200, json=RESP["tavily"], request=httpx.Request("POST", req["url"])))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called in offline mode")))
    monkeypatch.setattr(search, "_WARMED", {"tavily"})
    assert settings()["answer_mode"] == "offline"
    out = m.call_api("kafka lag", {"config": {}}, {"vars": VARS, "repeatIndex": 0})
    md = out["metadata"]
    res = json.loads(out["output"])
    assert res[0]["n"] == 1 and res[0]["url"].endswith("/t/1") and md["answer_mode"] == "offline"
    assert md["tokens_in"] == 0 and md["llm_cost_usd"] == 0.0 and md["total_cost_usd"] == md["search_cost_usd"]


def test_runner_end_to_end_api_mode(monkeypatch):
    """answer_mode=api: search.run with a mocked HTTP response and a mocked answer model."""
    from lib import llm
    m = load_module("providers/tavily.py", "prov_t2")
    monkeypatch.setitem(settings(), "answer_mode", "api")
    monkeypatch.setattr(search, "_send", lambda name, req: httpx.Response(200, json=RESP["tavily"], request=httpx.Request("POST", req["url"])))
    monkeypatch.setattr(llm, "complete", lambda s, u, **k: {"text": "FIXTURE answer [1]", "json": None, "latency_ms": 5,
                                                            "tokens_in": 100, "tokens_out": 10, "cost_usd": 0.001,
                                                            "model": "fixture", "stop_reason": "end_turn"})
    monkeypatch.setattr(search, "_WARMED", {"tavily"})
    out = m.call_api("kafka lag", {"config": {}}, {"vars": VARS, "repeatIndex": 2})
    md = out["metadata"]
    assert out["output"] == "FIXTURE answer [1]" and md["n_results"] == 1 and md["repeat_index"] == 2
    assert md["search_latency_ms"] is not None and out["latencyMs"] == md["search_latency_ms"]
    assert md["provider_reported_latency_ms"] == 1250.0 and md["search_cost_source"] == "provider_response"
    assert md["raw_file"] and md["answer_sources"][0]["url"].endswith("/t/1")
    assert any(a["step"] == "domain filter" for a in md["anomalies"])  # fixture host is not github.com


def test_runner_http_error_is_returned_not_raised(monkeypatch):
    m = load_module("providers/exa.py", "prov_e2")
    monkeypatch.setattr(search, "_send", lambda name, req: httpx.Response(429, json={"error": "FIXTURE"}, request=httpx.Request("POST", req["url"])))
    monkeypatch.setattr(search, "_WARMED", {"exa"})
    out = m.call_api("q", {"config": {}}, {"vars": VARS})
    assert out["output"].startswith("[SEARCH ERROR]") and out["metadata"]["error_type"] == "rate_limit"
    assert out["metadata"]["anomalies"][0]["category"] == "rate limit"


def test_runner_timeout(monkeypatch):
    m = load_module("providers/linkup.py", "prov_l2")

    def boom(name, req):
        raise httpx.ReadTimeout("FIXTURE timeout")
    monkeypatch.setattr(search, "_send", boom)
    monkeypatch.setattr(search, "_WARMED", {"linkup"})
    out = m.call_api("q", {"config": {}}, {"vars": VARS})
    assert out["metadata"]["error_type"] == "timeout"


def test_missing_key_is_reported(monkeypatch):
    m = load_module("providers/firecrawl.py", "prov_f3")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "")
    monkeypatch.setattr(search, "_WARMED", {"firecrawl"})
    out = m.call_api("q", {"config": {}}, {"vars": VARS})
    assert out["metadata"]["error_type"] == "missing_key" and out["metadata"]["anomalies"][0]["severity"] == "red"


def test_claude_native_parsing():
    c = load_module("providers/claude_native.py", "prov_c")
    content = [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "q1"}},
        {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://fixture.invalid/c/1", "title": "t", "page_age": "October 7, 2026"}]},
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "too_many_requests"}},
        {"type": "text", "text": "Answer A.", "citations": [{"url": "https://fixture.invalid/c/1", "cited_text": "FIXTURE cited"}]},
        {"type": "text", "text": " More."},
    ]
    res, errs, qs = c.extract_results(content)
    assert len(res) == 1 and errs[0]["error_code"] == "too_many_requests" and qs == ["q1"]
    text, cits = c.render_answer([b for b in content if b["type"] == "text"])
    assert text == "Answer A.[1] More." and cits[0]["n"] == 1
