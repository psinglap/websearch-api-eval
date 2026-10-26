#!/usr/bin/env python3
"""Build the 20-question SimpleQA control sample (fixed seed) used by all three harnesses.

Source: the official SimpleQA test set used by openai/simple-evals simpleqa_eval.py
  https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv  (4,326 rows; metadata,problem,answer)
Sample: pandas .sample(n=20, random_state=42) -> crosscheck/simpleqa_sample20.csv (+ sha256 of the source CSV)
Outputs:
  crosscheck/simpleqa_sample20.csv     same columns as the official CSV (drop-in for both vendor harnesses)
  crosscheck/simpleqa_sample.yaml      promptfoo tests for promptfooconfig.simpleqa.yaml
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import httpx
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
URL = "https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv"
SEED, N = 42, 20


def main():
    r = httpx.get(URL, timeout=120)
    r.raise_for_status()
    (HERE / "simple_qa_test_set.sha256").write_text(hashlib.sha256(r.content).hexdigest() + f"  {URL}\n")
    df = pd.read_csv(io.BytesIO(r.content))
    s = df.sample(n=N, random_state=SEED).reset_index().rename(columns={"index": "source_row"})
    s[["metadata", "problem", "answer"]].to_csv(HERE / "simpleqa_sample20.csv", index=False)
    s[["source_row", "problem", "answer"]].to_csv(HERE / "simpleqa_sample20_with_rows.csv", index=False)
    tests = []
    for i, row in s.iterrows():
        qid = f"SQ{i + 1:02d}"
        tests.append({"description": f"{qid}: {row.problem[:80]}", "vars": {
            "qid": qid, "usecase": "simpleqa", "upstream_task": row.problem, "query": row.problem,
            "window_hours": "", "domains": "", "needs_back": "A short factual answer with a citation",
            "freshness": "static", "freshness_tier": "static", "score_window_hours": 876000,
            "expected_answer": str(row.answer), "expect_none": False, "source_urls": "",
            "answer_type": "exact", "tolerance": "", "ground_truth_file": f"ground_truth/{qid}.json",
            "simpleqa_source_row": int(row.source_row)}, "assert": []})
    (HERE / "simpleqa_sample.yaml").write_text(
        f"# SimpleQA control sample: {N} questions, pandas random_state={SEED}, from {URL}\n"
        "# window_hours is empty => no provider date filter (static facts).\n"
        + yaml.safe_dump(tests, sort_keys=False, allow_unicode=True, width=200))
    print(json.dumps({"rows_in_source": len(df), "sample": N, "seed": SEED,
                      "first_rows": s.source_row.head(5).tolist()}))


if __name__ == "__main__":
    main()
