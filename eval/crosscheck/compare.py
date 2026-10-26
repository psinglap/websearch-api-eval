#!/usr/bin/env python3
"""Agreement between our promptfoo harness and the two vendor harnesses on the
same 20 SimpleQA questions (crosscheck/simpleqa_sample20.csv, seed 42).

Inputs (latest of each):
  ours     out/simpleqa_results.json                              (promptfoo export; provider via metadata)
  You.com  out/crosscheck/youcom_harness/*/dataset_simpleqa_raw_results_<sampler>.csv
  Tavily   out/crosscheck/tavily_harness/**/<provider>_simpleqa_results.csv
Output: out/crosscheck/agreement.csv and agreement.md with, per provider and harness pair:
  n common questions, accuracy in each harness, % per-question agreement, Cohen's kappa.
Column names in vendor CSVs are detected (question/problem/query; is_correct/score/grade).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL / "analysis"))
from pf_load import load  # noqa: E402

SAMPLER_TO_PROVIDER = {"you_search": "youcom", "exa_search_with_text": "exa", "parallel_search_basic": "parallel",
                       "tavily_search": "tavily"}


def norm_q(q: str) -> str:
    return " ".join(str(q).lower().split())


def ours(path: Path) -> pd.DataFrame:
    d = load(path)
    recs = []
    for r in d["rows"]:
        acc = r["comp"].get("accuracy") or {}
        if str(acc.get("reason", "")).startswith("UNGRADED"):
            continue
        recs.append({"provider": r["provider"], "q": norm_q(r["vars"].get("query", "")),
                     "correct": float("SimpleQA A" in acc.get("reason", ""))})
    df = pd.DataFrame(recs)
    return df.groupby(["provider", "q"], as_index=False)["correct"].mean().assign(correct=lambda x: (x.correct >= 0.5).astype(float))


def _vendor_csv(f: Path, provider: str) -> pd.DataFrame:
    df = pd.read_csv(f)
    qcol = next(c for c in ("question", "problem", "query", "prompt") if c in df.columns)
    if "is_correct" in df.columns:
        corr = df["is_correct"].astype(str).str.lower().isin(["true", "1", "1.0"])
    elif "grade" in df.columns:
        corr = df["grade"].astype(str).str.upper().str.startswith("A")
    else:
        corr = df["score"].astype(float) >= 1
    return pd.DataFrame({"provider": provider, "q": df[qcol].map(norm_q), "correct": corr.astype(float)})


def youcom_harness() -> pd.DataFrame:
    base = EVAL / "out" / "crosscheck" / "youcom_harness"
    runs = sorted(base.glob("*/"), key=lambda p: p.stat().st_mtime) if base.exists() else []
    if not runs:
        return pd.DataFrame()
    parts = []
    for f in runs[-1].rglob("dataset_simpleqa_raw_results_*.csv"):
        sampler = f.stem.split("raw_results_")[-1]
        parts.append(_vendor_csv(f, SAMPLER_TO_PROVIDER.get(sampler, sampler)))
    return pd.concat(parts) if parts else pd.DataFrame()


def tavily_harness() -> pd.DataFrame:
    base = EVAL / "out" / "crosscheck" / "tavily_harness"
    files = sorted(base.rglob("*_simpleqa_results.csv"), key=lambda p: p.stat().st_mtime) if base.exists() else []
    latest = {}
    for f in files:
        latest[f.name.split("_simpleqa_results")[0]] = f
    parts = [_vendor_csv(f, p) for p, f in latest.items()]
    return pd.concat(parts) if parts else pd.DataFrame()


def kappa(a: pd.Series, b: pd.Series) -> float:
    po = (a == b).mean()
    pa, pb = a.mean(), b.mean()
    pe = pa * pb + (1 - pa) * (1 - pb)
    return float("nan") if pe == 1 else float((po - pe) / (1 - pe))


def main():
    sets = {}
    p = EVAL / "out" / "simpleqa_results.json"
    if p.exists():
        sets["ours (promptfoo)"] = ours(p)
    for name, fn in (("You.com harness", youcom_harness), ("Tavily harness", tavily_harness)):
        df = fn()
        if not df.empty:
            sets[name] = df
    if len(sets) < 2:
        print(f"need at least two harness outputs; found: {list(sets)}")
        return 1
    rows = []
    names = list(sets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = sets[names[i]], sets[names[j]]
            m = a.merge(b, on=["provider", "q"], suffixes=("_a", "_b"))
            for prov, g in m.groupby("provider"):
                rows.append({"provider": prov, "harness_a": names[i], "harness_b": names[j], "n_common": len(g),
                             "acc_a": g.correct_a.mean(), "acc_b": g.correct_b.mean(),
                             "agreement": (g.correct_a == g.correct_b).mean(), "cohen_kappa": kappa(g.correct_a, g.correct_b)})
    out = EVAL / "out" / "crosscheck"
    out.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame(rows)
    res.to_csv(out / "agreement.csv", index=False)
    (out / "agreement.md").write_text("# Harness agreement on the SimpleQA control sample (20 q, seed 42)\n\n"
                                      + res.round(3).to_markdown(index=False))
    print(res.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
