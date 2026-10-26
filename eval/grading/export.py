#!/usr/bin/env python3
"""Grading export: saved search results -> one JSONL line per (qid, provider, run=1).

  .venv/bin/python grading/export.py gtm                     # latest out/gtm_results*.json
  .venv/bin/python grading/export.py gtm --results out/gtm_results_X.json

Writes out/grading/{usecase}_to_grade.jsonl for Claude Code to answer + grade
(rules in grading/RUBRIC.md, SimpleQA grader text in grading/simpleqa_grader_template.txt)
and creates grading/grades_{usecase}.csv (header + qid/provider pre-filled) if it
does not exist yet. No LLM / API call is made here.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

GRADING = Path(__file__).resolve().parent
EVAL = GRADING.parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL / "analysis"))

from pf_load import PROVIDER_ORDER, load  # noqa: E402

TOP_K = 5
CONTENT_CHARS = 1500
GRADE_COLUMNS = ["qid", "provider", "answer_text", "accuracy_0_2", "simpleqa_label", "correct_none",
                 "rel_r1", "rel_r2", "rel_r3", "rel_r4", "rel_r5", "precision_at_5", "cited_result_ids",
                 "citation_supported", "grader", "human_check", "notes"]


def _blank(v) -> bool:
    return v is None or str(v).strip() == "" or str(v).strip().upper().startswith("[FILL")


def first_run_rows(rows: list[dict]) -> list[dict]:
    """One row per (qid, provider): the first repeat (run=1, lowest repeat_index)."""
    best: dict[tuple, dict] = {}
    for r in rows:
        if r["provider"] not in PROVIDER_ORDER:  # drops variants (youcom_knowledge) and claude_native
            continue
        k = (r["qid"], r["provider"])
        rep = r.get("repeat") if r.get("repeat") is not None else 10**6
        if k not in best or rep < (best[k].get("repeat") if best[k].get("repeat") is not None else 10**6):
            best[k] = r
    order = {p: i for i, p in enumerate(PROVIDER_ORDER)}
    return sorted(best.values(), key=lambda r: (str(r["qid"]), order.get(r["provider"], 99)))


def result_items(md: dict) -> list[dict]:
    out = []
    for i, r in enumerate((md.get("results") or [])[:TOP_K], 1):
        out.append({"id": f"r{i}", "title": r.get("title"), "url": r.get("url"),
                    "date": r.get("published_date"), "snippet": (r.get("snippet") or "")[:500],
                    "content": (r.get("content") or "")[:CONTENT_CHARS]})
    return out


def build(rows: list[dict], keys: dict[str, dict]) -> list[dict]:
    lines = []
    for r in first_run_rows(rows):
        v, md, k = r["vars"], r["md"], keys.get(str(r["qid"]), {})
        exp = v.get("expected_answer")
        exp = k.get("expected_answer") if _blank(exp) else exp
        en = v.get("expect_none")
        en = k.get("expect_none") if _blank(en) else en
        lines.append({
            "qid": r["qid"], "provider": r["provider"], "run": 1, "usecase": r["usecase"],
            "upstream_task": v.get("upstream_task"), "query": v.get("query") or md.get("query"),
            "needs_back": v.get("needs_back"), "window_hours": v.get("window_hours"),
            "answer_type": v.get("answer_type"),
            "expected_answer": None if _blank(exp) else exp,
            "expect_none": None if _blank(en) else str(en).strip().lower() in {"true", "1", "yes", "y"},
            "tolerance": v.get("tolerance") or k.get("tolerance") or "",
            "answer_source": k.get("source_url") or v.get("source_urls"),
            "wayback_url": k.get("wayback_url") or "", "captured_at_utc": k.get("captured_at_utc") or "",
            "requested_at_utc": md.get("requested_at_utc"), "error_type": md.get("error_type"),
            "n_results": md.get("n_results", 0), "results": result_items(md),
        })
    return lines


def write_grades_template(path: Path, lines: list[dict]) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GRADE_COLUMNS)
        w.writeheader()
        for ln in lines:
            w.writerow({"qid": ln["qid"], "provider": ln["provider"], "grader": "claude-code"})
    return True


def latest(usecase: str, base: Path) -> Path | None:
    c = sorted(base.glob(f"{usecase}_results*.json"), key=lambda p: p.stat().st_mtime)
    return c[-1] if c else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("usecase")
    ap.add_argument("--results", default=None)
    ap.add_argument("--keys", default=None, help="answer key CSV (default answer_keys.csv or $EVAL_KEYS_CSV)")
    ap.add_argument("--out", default=None, help="output dir (default out/grading)")
    ap.add_argument("--grades-dir", default=None, help="where grades_{usecase}.csv lives (default grading/)")
    a = ap.parse_args(argv)
    from lib import keys as keymod
    src = Path(a.results) if a.results else latest(a.usecase, EVAL / "out")
    if not src or not src.exists():
        print(f"no results for {a.usecase} (run ./run.sh run {a.usecase} first)")
        return 1
    lines = build(load(src)["rows"], keymod.load_keys(Path(a.keys) if a.keys else None))
    lines = [ln for ln in lines if ln["usecase"] in (a.usecase, None)]
    out = Path(a.out or EVAL / "out" / "grading")
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{a.usecase}_to_grade.jsonl"
    with open(p, "w") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False, default=str) + "\n")
    gp = Path(a.grades_dir or GRADING) / f"grades_{a.usecase}.csv"
    made = write_grades_template(gp, lines)
    ungraded = sum(1 for ln in lines if ln["expected_answer"] is None and ln["expect_none"] is None)
    print(f"wrote {len(lines)} rows -> {p} (from {src.name}); "
          f"{'created' if made else 'kept existing'} {gp}; rows without an answer key: {ungraded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
