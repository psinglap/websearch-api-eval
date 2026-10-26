import json

import pytest

from conftest import load_module
from lib import llm

MD = {"provider": "youcom", "requested_at_utc": "2026-10-08T12:00:00+00:00", "error_type": None,
      "results": [{"url": f"https://fixture.invalid/r/{i}", "title": f"FIXTURE {i}", "content": f"FIXTURE body {i} kafka lag spikes",
                   "snippet": "", "published_date": f"2026-10-0{8 - (i % 3)}T10:00:00Z", "date_source": "provider:x"} for i in range(1, 6)],
      "answer_sources": [{"n": i, "url": f"https://fixture.invalid/r/{i}"} for i in range(1, 6)],
      "content_in_one_call": True, "content_chars_top5": 100, "search_latency_ms": 420.0, "tokens_in": 900, "tokens_out": 50,
      "search_cost_usd": 0.005, "llm_cost_usd": 0.004, "total_cost_usd": 0.009, "search_cost_source": "price_table"}
VARS = {"qid": "G1", "usecase": "insurance", "query": "kafka lag", "upstream_task": "FIXTURE task", "window_hours": 48,
        "score_window_hours": 48, "expected_answer": "FIXTURE gold", "expect_none": False}


def ctx(md=MD, v=VARS):
    return {"vars": v, "metadata": md, "providerResponse": {"metadata": md}, "config": {}}


def fake_grade(text=None, j=None):
    return lambda s, u, json_schema=None: {"text": text if text is not None else json.dumps(j), "json": j}


def test_simpleqa_mapping(monkeypatch):
    a = load_module("asserts/accuracy_simpleqa.py", "acc")
    assert "{predicted_answer}" in a.TEMPLATE and "{target}" in a.TEMPLATE
    for letter, score, ok in (("A", 1.0, True), ("B", 0.0, False), ("C", 0.0, False), ("no letter", 0.0, False)):
        monkeypatch.setattr(llm, "grade", fake_grade(letter))
        r = a.get_assert("FIXTURE answer", ctx())
        assert r["score"] == score and r["pass"] is ok
    r = a.get_assert("FIXTURE", ctx(v=dict(VARS, expected_answer="[FILL AT RUN TIME]", qid="ZZ")))
    assert r["reason"].startswith("UNGRADED")
    assert a.get_assert("[SEARCH ERROR] x", ctx())["named_scores"]["accuracy_0_2"] == 0


def test_correct_none(monkeypatch):
    c = load_module("asserts/correct_none.py", "cn")
    v = dict(VARS, expect_none=True)
    monkeypatch.setattr(llm, "grade", fake_grade(j={"says_none": True, "stale_or_hallucinated_as_current": False, "false_premise_rebutted": True, "reason": "x"}))
    assert c.get_assert("NONE / not found", ctx(v=v))["pass"]
    monkeypatch.setattr(llm, "grade", fake_grade(j={"says_none": True, "stale_or_hallucinated_as_current": True, "false_premise_rebutted": True, "reason": "x"}))
    assert not c.get_assert("NONE but 2020 Isaias DR-4560", ctx(v=v))["pass"]
    assert not c.get_assert("NONE / not found", ctx())["pass"]   # expect_none false -> false 'none' is a miss
    assert c.get_assert("Yes: DR-9999", ctx())["pass"]


def test_precision_and_freshness(monkeypatch):
    p = load_module("asserts/precision_at5.py", "p5")
    calls = []

    def g(s, u, json_schema=None):
        calls.append(1)
        return {"text": "", "json": {"labels": [{"n": i, "relevant": i <= 3, "reason": "r"} for i in range(1, 6)]}}
    monkeypatch.setattr(llm, "grade", g)
    assert p.get_assert("x", ctx())["score"] == pytest.approx(0.6)
    f = load_module("asserts/freshness.py", "fr")
    r = f.compute(MD, VARS, p.label_results(MD, VARS), use_network=False)
    assert len(calls) == 1, "labels are cached and reused by freshness"
    # ages 26,50,2,26,50 h -> 3 of 5 inside 48 h; newest relevant (results 1-3) is 2 h old
    assert r["pct_in_window"] == pytest.approx(0.6) and r["newest_relevant_age_h"] == pytest.approx(2.0)
    r = f.compute(MD, dict(VARS, score_window_hours=6), None, use_network=False)
    assert r["pct_in_window"] == pytest.approx(0.2)


def test_recall(tmp_path, monkeypatch):
    rc = load_module("asserts/recall.py", "rc")
    truth = {"items": [{"url": "https://fixture.invalid/r/1"}, {"url": "https://fixture.invalid/r/9"}]}
    r = rc.compute(MD, "see https://fixture.invalid/r/9", truth)
    assert r["recall"] == 0.5 and r["recall_incl_answer"] == 1.0
    monkeypatch.setenv("EVAL_GT_DIR", str(tmp_path))
    assert rc.get_assert("x", ctx())["reason"].startswith("N/A")
    (tmp_path / "G1.json").write_text(json.dumps(truth))
    assert rc.get_assert("x", ctx())["score"] == 0.5


def test_citation_validity():
    cv = load_module("asserts/citation_validity.py", "cv")
    pages = {"https://fixture.invalid/r/1": (200, "blah FIXTURE body 1 kafka lag spikes blah"),
             "https://fixture.invalid/r/2": (404, "")}
    r = cv.check("Kafka lag spikes were reported [1]. Another claim [2]. Bad ref [7].", MD, fetch=lambda u: pages.get(u, (0, "")))
    rows = {x["n"]: x for x in r["rows"]}
    assert rows[2]["valid"] is False and rows[7]["valid"] is False
    assert r["n_cited"] == 3 and r["n_url_ok"] == 1


def test_simple_measurements():
    for f, key in (("content_one_call", "content_in_one_call"), ("latency_budget", "within_latency_budget"),
                   ("token_cost", "tokens_in"), ("reliability", "call_ok")):
        m = load_module(f"asserts/{f}.py", f)
        r = m.get_assert("x", ctx())
        assert r["pass"] and key in r["named_scores"]
    lb = load_module("asserts/latency_budget.py", "lb")
    assert lb.get_assert("x", ctx())["named_scores"]["within_latency_budget"] == 1  # 420 ms <= 500 ms insurance budget
    rel = load_module("asserts/reliability.py", "rel")
    assert not rel.get_assert("x", ctx(md=dict(MD, error_type="timeout")))["pass"]
