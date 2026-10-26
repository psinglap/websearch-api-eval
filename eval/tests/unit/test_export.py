import json

from conftest import EVAL, FIX, load_module

export = load_module("grading/export.py", "grading_export")


def test_export_one_line_per_qid_provider_run1(tmp_path):
    out, gdir = tmp_path / "grading_out", tmp_path / "grades"
    rc = export.main(["gtm", "--results", str(FIX / "fixture_gtm_results.json"), "--keys", str(FIX / "fixture_answer_keys.csv"),
                      "--out", str(out), "--grades-dir", str(gdir)])
    assert rc == 0
    lines = [json.loads(x) for x in (out / "gtm_to_grade.jsonl").read_text().splitlines()]
    assert len(lines) == 40 and len({(x["qid"], x["provider"]) for x in lines}) == 40
    assert {x["provider"] for x in lines} == {"youcom", "tavily", "exa", "parallel"}
    x = lines[0]
    for k in ("upstream_task", "query", "needs_back", "expected_answer", "answer_source", "wayback_url", "run", "results"):
        assert k in x
    assert x["run"] == 1 and x["expected_answer"] == "FIXTURE ANSWER (fake key)"
    assert all(len(r["content"]) <= 1500 and set(r) >= {"id", "title", "url", "date", "snippet", "content"}
               for ln in lines for r in ln["results"]) and max(len(ln["results"]) for ln in lines) == 5
    hdr = (gdir / "grades_gtm.csv").read_text().splitlines()[0].split(",")
    assert hdr == export.GRADE_COLUMNS and "rel_r5" in hdr and "grader" in hdr


def test_export_keeps_existing_grades(tmp_path):
    gdir = tmp_path / "g"
    gdir.mkdir()
    (gdir / "grades_gtm.csv").write_text("qid,provider\nKEEP,me\n")
    export.main(["gtm", "--results", str(FIX / "fixture_gtm_results.json"), "--out", str(tmp_path / "o"), "--grades-dir", str(gdir)])
    assert "KEEP" in (gdir / "grades_gtm.csv").read_text()


def test_grading_files_present():
    assert (EVAL / "grading" / "RUBRIC.md").exists()
    assert (EVAL / "grading" / "simpleqa_grader_template.txt").read_text() == (EVAL / "asserts" / "simpleqa_grader_template.txt").read_text()


def test_offline_configs_have_no_llm_assertions():
    import sys
    sys.path.insert(0, str(EVAL / "config"))
    import make_configs as mc
    off = mc.config("gtm", "file://tests/gtm.yaml", mode="offline")
    types = {a["type"] for a in off["defaultTest"]["assert"]}
    metrics = {a.get("metric") for a in off["defaultTest"]["assert"]}
    assert "options" not in off["defaultTest"] and "context-faithfulness" not in types and "llm-rubric" not in types
    assert not metrics & {"accuracy", "precision_at_5", "citation_validity"} and "url_validity" in metrics
    assert len(off["providers"]) == 4 and not any("claude_native" in p["id"] for p in off["providers"])
    api = mc.config("gtm", "file://tests/gtm.yaml", mode="api")
    assert "context-faithfulness" in {a["type"] for a in api["defaultTest"]["assert"]} and api["defaultTest"]["options"]


def test_url_validity_offline_assert():
    cv = load_module("asserts/citation_validity.py", "cv_off")
    md = {"answer_mode": "offline", "results": [{"url": "https://a.invalid/1"}, {"url": "urn:youcom:knowledge:0"},
                                                {"url": "https://a.invalid/2"}]}
    r = cv.url_check(md, fetch=lambda u: (200, "") if u.endswith("1") else (404, ""))
    assert r["n_checked"] == 2 and r["score"] == 0.5
