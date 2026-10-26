import math

import numpy as np
import pandas as pd

from conftest import FIX
import analyze


def test_wilson_and_sign():
    lo, hi = analyze.wilson(7, 10)
    assert math.isclose(lo, 0.397, abs_tol=0.01) and math.isclose(hi, 0.892, abs_tol=0.01)
    assert analyze.sign_test(6, 0) < 0.05 and analyze.sign_test(3, 3) == 1.0


def test_fixture_end_to_end(tmp_path):
    """analysis on the FAKE promptfoo exports + FAKE Claude Code grades produced by tests/fixtures/make_fixtures.py"""
    out = tmp_path / "fx"
    assert analyze.main(["--fixture", "--out", str(out)]) == 0
    sc = pd.read_csv(out / "gtm_scorecard.csv")
    assert set(["latency_p50_ms", "latency_p95_ms", "accuracy_0_2", "correct_none", "freshness_pct", "newest_relevant_age_h",
                "precision_at_5", "recall", "citation_validity", "url_validity", "content_in_one_call", "tokens_per_correct",
                "cost_per_correct", "error_rate", "included", "exclusion_reason"]).issubset(sc.columns)
    assert len(sc) == 4 and "claude_native" not in set(sc.provider) and (sc.n_calls == 30).all()
    # graded metrics come from tests/fixtures/grades/grades_gtm.csv (run 1 only -> 10 graded rows per provider)
    assert (sc.n_graded == 10).all() and sc.accuracy_0_2.notna().all() and sc.precision_at_5.notna().all()
    assert sc.tokens_per_correct.notna().any() and sc.cost_per_correct.notna().any()
    charts = list((out / "charts" / "gtm").glob("*.png"))
    assert len(charts) >= 15
    assert (out / "charts" / "cross_industry_youcom_rank.png").exists()
    summ = (out / "summary.md").read_text()
    assert "FIXTURE DATA" in summ and "search cost only, no LLM" in summ and "approximate" in summ
    hc = pd.read_csv(out / "grading" / "gtm_human_check.csv")
    assert len(hc) == 12 and {"human_accuracy_0_2", "human_agree"} <= set(hc.columns)


def test_grades_loading_and_apply(tmp_path):
    p = tmp_path / "grades_gtm.csv"
    p.write_text("qid,provider,answer_text,accuracy_0_2,simpleqa_label,correct_none,rel_r1,rel_r2,rel_r3,rel_r4,rel_r5,"
                 "precision_at_5,cited_result_ids,citation_supported,grader,human_check,notes\n"
                 "G1,youcom,a,2,CORRECT,1,1,1,0,,1,,r1,yes,claude-code,,\n"
                 "G1,tavily,b,,,,,,,,,,,,claude-code,,\n")
    g = analyze.load_grades(p)
    assert g.loc[0, "precision_at_5"] == 0.6 and g.loc[0, "citation_supported"] == 1.0
    assert np.isnan(g.loc[1, "accuracy_0_2"])  # blank = ungraded, not wrong
    df = pd.DataFrame({"qid": ["G1"] * 4, "provider": ["youcom", "youcom", "tavily", "tavily"], "repeat": [0, 1, 0, 1],
                       "accuracy_0_2": [np.nan] * 4, "correct": [np.nan] * 4, "correct_none": [np.nan] * 4,
                       "precision_at_5": [np.nan] * 4, "citation_validity": [np.nan] * 4})
    d = analyze.apply_grades(df, g)
    assert d.accuracy_0_2.tolist()[0] == 2.0 and d.correct.tolist()[0] == 1.0
    assert d.accuracy_0_2.isna().tolist() == [False, True, True, True]  # run 1 only; blank grade stays ungraded


def test_human_check_sample_is_reproducible_and_keeps_entries(tmp_path):
    rows = [{"qid": f"G{i}", "provider": "youcom", "answer_text": "x", "simpleqa_label": "CORRECT", "accuracy_0_2": 2.0,
             "correct_none": np.nan, "precision_at_5": 0.4, "citation_supported": 1.0} for i in range(10)]
    g = pd.DataFrame(rows)
    a = analyze.human_check("gtm", g, tmp_path)
    first = pd.read_csv(a["path"], dtype=str, keep_default_na=False)
    assert a["n_sample"] == 2 and math.isnan(a["agreement"])
    first.loc[0, "human_accuracy_0_2"] = "2"
    first.loc[1, "human_agree"] = "no"
    first.to_csv(a["path"], index=False)
    b = analyze.human_check("gtm", g, tmp_path)
    again = pd.read_csv(b["path"], dtype=str, keep_default_na=False)
    assert list(again.qid) == list(first.qid) and b["reviewed"] == 2 and b["agreement"] == 0.5


def _calls(provider, n, n_err=0, n_empty=0):
    return [{"provider": provider, "variant": None, "usecase": "gtm", "qid": f"G{i % 10}", "repeat": i // 10,
             "search_latency_ms": 100.0, "latency_is_end_to_end": False, "end_to_end_ms": 100.0,
             "accuracy_0_2": np.nan, "correct": np.nan, "correct_none": np.nan, "freshness_pct": 0.5,
             "newest_relevant_age_h": np.nan, "precision_at_5": np.nan, "recall": np.nan, "citation_validity": np.nan,
             "url_validity": 1.0, "groundedness": np.nan, "content_in_one_call": 1.0, "tokens_in": 0,
             "total_cost_usd": 0.01, "result_tokens_top5": 100, "search_cost_usd": 0.01,
             "error": float(i < n_err), "call_ok": float(i >= n_err),
             "empty": float(n_err <= i < n_err + n_empty),
             "has_url_result": float(i >= n_err + n_empty),
             "timeout": 0.0, "rate_limit": 0.0, "in_body_error": 0.0,
             "error_type": "http_500" if i < n_err else ("empty_results" if i < n_err + n_empty else None)}
            for i in range(n)]


def test_inclusion_rule():
    df = pd.DataFrame(_calls("youcom", 30) + _calls("tavily", 30, n_err=7) + _calls("exa", 30, n_empty=7)
                      + _calls("parallel", 30, n_err=3, n_empty=3))
    sc = analyze.scorecard(df).set_index("provider")
    assert sc.loc["youcom", "included"] and sc.loc["parallel", "included"]  # 90% ok, 80% with URL -> included
    assert not sc.loc["tavily", "included"] and "succeeded" in sc.loc["tavily", "exclusion_reason"]
    assert sc.loc["exa", "included"] and sc.loc["exa", "with_url_rate"] < 0.8  # empty results are scored, not excluded
    assert sc.loc["tavily", "exclusion_reason"].startswith("excluded: insufficient evidence")
