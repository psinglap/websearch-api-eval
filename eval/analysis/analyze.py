#!/usr/bin/env python3
"""Compute all 12 metrics per provider per use case, write scorecards, a markdown
summary and charts.

  python analysis/analyze.py                      # latest out/{gtm,insurance,finance}_results.json
  python analysis/analyze.py --results out/gtm_results.json --results out/finance_results.json
  python analysis/analyze.py --fixture            # tests/fixtures/*.json -> out/fixture_charts/ (FIXTURE DATA)
  python analysis/analyze.py --grades-dir grading # where grades_{usecase}.csv live (default grading/)

Grades (answer_mode=offline, the default): accuracy, correct-none, precision@5 and
citation support come from grading/grades_{usecase}.csv, written by Claude Code from
out/grading/{usecase}_to_grade.jsonl (grading/RUBRIC.md). They apply to run 1 of each
(qid, provider). A 20% random sample (seed 42) goes to out/grading/{usecase}_human_check.csv
for the user to confirm/override; the agreement rate is reported in summary.md.
Token efficiency = approximate tiktoken cl100k count of the top-5 result content;
cost per correct = search cost only (no LLM).
Inclusion rule: a provider is ranked in a use case only if >= 80% of its calls succeed (no error/timeout);
otherwise "excluded: insufficient evidence". Empty-result rate is reported, not used for exclusion.

Outputs (live):   out/{usecase}_scorecard.csv, out/{usecase}_per_query.csv, out/summary.md,
                  out/charts/{usecase}/*.png, out/charts/cross_industry_youcom_rank.png,
                  out/charts/friction_*.png, out/friction_summary.md
Outputs (fixture): the same under out/fixture_charts/ with every title prefixed
                  "FIXTURE DATA – not results".

Statistics (n = 10 queries x 3 repeats = 30 calls per provider per use case):
  latency p50/p95  numpy.percentile over all calls with a measured latency
  accuracy         mean 0-2 score per call; % correct with a Wilson 95% interval computed on the
                   10 per-query majority outcomes (repeats are not independent samples)
  paired test      per query: provider vs You.com mean accuracy -> win/loss/tie; exact two-sided
                   sign test (scipy.stats.binomtest) on wins vs losses (ties dropped)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(HERE))

from pf_load import PROVIDER_LABEL, PROVIDER_ORDER, load  # noqa: E402

USECASES = ["gtm", "insurance", "finance"]
UC_LABEL = {"gtm": "GTM (developer signals)", "insurance": "Insurance", "finance": "Finance", "simpleqa": "SimpleQA control"}
BUDGET = {"gtm": 3000, "insurance": 500, "finance": 3000, "simpleqa": 3000}

# metric key -> (label, higher_is_better, unit)
METRICS = {
    "latency_p50_ms": ("1 Search latency p50 (ms)", False, "ms"),
    "latency_p95_ms": ("1 Search latency p95 (ms)", False, "ms"),
    "accuracy_0_2": ("2 Accuracy (0-2)", True, ""),
    "correct_none": ("3 Correct 'none'", True, "%"),
    "freshness_pct": ("4 Results in window", True, "%"),
    "newest_relevant_age_h": ("5 Newest relevant result age (h)", False, "h"),
    "precision_at_5": ("6 Precision@5", True, "%"),
    "recall": ("7 Recall", True, "%"),
    "url_validity": ("8a URL validity (top-5 results load)", True, "%"),
    "citation_validity": ("8 Citation support (graded)", True, "%"),
    "groundedness": ("8 Groundedness (faithfulness, api mode)", True, "%"),
    "content_in_one_call": ("9 Content in one call", True, "%"),
    "tokens_per_correct": ("10 Result tokens per correct (approx., cl100k)", False, "tok"),
    "cost_per_correct": ("11 Search cost per correct ($, search only, no LLM)", False, "$"),
    "error_rate": ("12 Error rate (errors+timeouts+empty)", False, "%"),
}

# Validated categorical palette (dataviz skill reference palette, light mode; validator PASS,
# contrast WARN -> every bar carries a direct value label). Fixed order, never cycled.
COLORS = {"youcom": "#2a78d6", "tavily": "#eb6834", "exa": "#1baf7a", "parallel": "#eda100",
          "firecrawl": "#e87ba4", "linkup": "#008300", "claude_native": "#4a3aa7", "youcom_knowledge": "#2a78d6"}
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
EXCLUDED: set[str] = set()  # providers failing the inclusion rule in the use case being charted
MIN_SUCCESS, MIN_WITH_URL = 0.8, 0.8
GRADE_NUM = ["accuracy_0_2", "correct_none", "rel_r1", "rel_r2", "rel_r3", "rel_r4", "rel_r5", "precision_at_5",
             "citation_supported"]
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]


# ----------------------------------------------------------------------------- stats
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    from scipy.stats import binomtest
    return float(binomtest(wins, n, 0.5).pvalue)


def pct(values):
    v = [x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return float(np.mean(v)) if v else float("nan")


# ----------------------------------------------------------------------------- per-row extraction
def is_na(c: dict | None) -> bool:
    return c is None or str(c.get("reason", "")).startswith(("N/A", "UNGRADED"))


def row_accuracy(r: dict) -> float | None:
    """0-2: SimpleQA A -> 2; else partial credit PARTIAL -> 1; else 0. None if ungraded."""
    acc = r["comp"].get("accuracy")
    if acc is None or str(acc.get("reason", "")).startswith("UNGRADED"):
        return None
    m = re.search(r"SimpleQA ([ABC])", acc.get("reason", ""))
    if m and m.group(1) == "A":
        return 2.0
    pc = r["comp"].get("partial_credit")
    if pc is not None and not is_na(pc) and (pc.get("score") or 0) >= 1:
        return 1.0
    return 0.0


def comp_score(r, key):
    c = r["comp"].get(key)
    return None if is_na(c) else c.get("score")


def named(r, key):
    v = r["named"].get(key)
    return None if v is None else float(v)


_ENC = None


def result_tokens(md: dict) -> int:
    """APPROXIMATE tokens of the top-5 result content an agent would pass on (tiktoken cl100k_base;
    falls back to chars/4 if tiktoken is unavailable)."""
    global _ENC
    text = "\n".join((r.get("content") or r.get("snippet") or "") for r in (md.get("results") or [])[:5])
    if not text:
        return 0
    if _ENC is None:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC = False
    return len(_ENC.encode(text, disallowed_special=())) if _ENC else len(text) // 4


def extract(rows: list[dict]) -> pd.DataFrame:
    recs = []
    for r in rows:
        md = r["md"]
        et = md.get("error_type") or r.get("error_type")
        lat = md.get("search_latency_ms")
        recs.append({
            "provider": r["provider"], "variant": r.get("variant"), "usecase": r["usecase"], "qid": r["qid"],
            "repeat": r["repeat"],
            "search_latency_ms": lat if lat is not None else (md.get("end_to_end_ms") if r["provider"] == "claude_native" else None),
            "latency_is_end_to_end": lat is None and r["provider"] == "claude_native",
            "end_to_end_ms": md.get("end_to_end_ms"),
            "accuracy_0_2": row_accuracy(r),
            "correct": None if row_accuracy(r) is None else float(row_accuracy(r) == 2.0),
            "correct_none": comp_score(r, "correct_none"),
            "freshness_pct": named(r, "freshness_pct_in_window") if not is_na(r["comp"].get("freshness")) else None,
            "newest_relevant_age_h": named(r, "newest_relevant_age_h"),
            "precision_at_5": comp_score(r, "precision_at_5"),
            "recall": comp_score(r, "recall"),
            "citation_validity": comp_score(r, "citation_validity"),
            "url_validity": comp_score(r, "url_validity"),
            "result_tokens_top5": result_tokens(md),
            "search_cost_usd": md.get("search_cost_usd") or 0.0,
            "has_url_result": float(et is None and (md.get("n_results") or 0) >= 1),
            "call_ok": float(not (bool(et) and et != "empty_results")),
            "groundedness": comp_score(r, "groundedness"),
            "content_in_one_call": float(bool(md.get("content_in_one_call"))),
            "tokens_in": md.get("tokens_in") or 0,
            "total_cost_usd": md.get("total_cost_usd") or 0.0,
            "error": float(bool(et) and et != "empty_results"),
            "timeout": float(et == "timeout"),
            "rate_limit": float(et == "rate_limit"),
            "empty": float(et == "empty_results"),
            "in_body_error": float(et == "in_body_search_error"),
            "error_type": et,
        })
    return pd.DataFrame(recs)


# ----------------------------------------------------------------------------- offline grades (Claude Code)
def _bin(v):
    t = str(v).strip().lower()
    if t in ("", "nan", "none", "n/a", "na"):
        return np.nan
    if t in ("1", "1.0", "true", "yes", "y", "supported"):
        return 1.0
    if t in ("0", "0.0", "false", "no", "n", "unsupported"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return np.nan


def load_grades(path: Path) -> pd.DataFrame | None:
    """grading/grades_{usecase}.csv -> DataFrame (numeric columns coerced; blank = ungraded)."""
    if not Path(path).exists():
        return None
    g = pd.read_csv(path, dtype=str, keep_default_na=False)
    if g.empty:
        return None
    for c in GRADE_NUM:
        g[c] = g[c].map(_bin) if c in g else np.nan
    rel = g[[f"rel_r{i}" for i in range(1, 6)]]
    # P@5 from the per-result labels when given (missing label = not relevant, trec_eval convention)
    g["precision_at_5"] = np.where(rel.notna().any(axis=1), rel.fillna(0).sum(axis=1) / 5.0, g["precision_at_5"])
    return g


def apply_grades(df: pd.DataFrame, grades: pd.DataFrame | None) -> pd.DataFrame:
    """Overwrite graded metrics from Claude Code's grades on run 1 of each (qid, provider);
    other repeats are left ungraded for these metrics."""
    if grades is None or df.empty:
        return df
    df = df.copy()
    first = df.groupby(["qid", "provider"])["repeat"].transform(lambda s: s.fillna(10**6).min())
    is_first = df["repeat"].fillna(10**6) == first
    gi = grades.drop_duplicates(["qid", "provider"]).set_index(["qid", "provider"])
    for col, src in (("accuracy_0_2", "accuracy_0_2"), ("correct_none", "correct_none"),
                     ("precision_at_5", "precision_at_5"), ("citation_validity", "citation_supported")):
        vals = [gi[src].get((q, p), np.nan) if f else np.nan for q, p, f in zip(df.qid, df.provider, is_first)]
        df[col] = pd.to_numeric(pd.Series(vals, index=df.index), errors="coerce")
    df["correct"] = np.where(df["accuracy_0_2"].notna(), (df["accuracy_0_2"] == 2.0).astype(float), np.nan)
    return df


HUMAN_COLS = ["human_accuracy_0_2", "human_agree", "human_notes"]


def human_check(uc: str, grades: pd.DataFrame | None, outdir: Path, frac: float = 0.2, seed: int = 42) -> dict:
    """Reproducible 20% sample of graded rows -> {uc}_human_check.csv (keeps the user's entries);
    agreement = share of reviewed rows where the human accepts the grade."""
    if grades is None:
        return {}
    graded = grades[grades["accuracy_0_2"].notna()].sort_values(["qid", "provider"]).reset_index(drop=True)
    if graded.empty:
        return {}
    n = max(1, int(math.ceil(frac * len(graded))))
    smp = graded.sample(n=n, random_state=seed)[["qid", "provider", "answer_text", "simpleqa_label", "accuracy_0_2",
                                                   "correct_none", "precision_at_5", "citation_supported"]]
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{uc}_human_check.csv"
    prev = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None
    for c in HUMAN_COLS:
        smp[c] = ""
    if prev is not None and set(HUMAN_COLS) <= set(prev.columns):
        keep = prev.set_index(["qid", "provider"])[HUMAN_COLS]
        for i, r in smp.iterrows():
            if (r.qid, r.provider) in keep.index:
                for c in HUMAN_COLS:
                    smp.at[i, c] = keep.loc[(r.qid, r.provider), c]
    smp.to_csv(path, index=False)
    reviewed, agree = 0, 0
    for r in smp.itertuples():
        h_acc, h_ok = _bin(r.human_accuracy_0_2), str(r.human_agree).strip().lower()
        if not np.isnan(h_acc):
            reviewed += 1
            agree += int(h_acc == r.accuracy_0_2)
        elif h_ok in ("y", "yes", "agree", "1", "true", "n", "no", "disagree", "0", "false"):
            reviewed += 1
            agree += int(h_ok in ("y", "yes", "agree", "1", "true"))
    return {"path": path, "n_sample": len(smp), "n_graded": len(graded), "reviewed": reviewed,
            "agreement": (agree / reviewed) if reviewed else float("nan")}


# ----------------------------------------------------------------------------- scorecard
def scorecard(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for p, g in df.groupby("provider", sort=False):
        lat = g["search_latency_ms"].dropna().to_numpy(dtype=float)
        acc = g["accuracy_0_2"].dropna()
        n_correct = int(g["correct"].fillna(0).sum())
        perq = g.dropna(subset=["correct"]).groupby("qid")["correct"].mean()
        k_major = int((perq >= 0.5).sum())
        lo, hi = wilson(k_major, len(perq))
        e2e = g["end_to_end_ms"].dropna().to_numpy(dtype=float)
        graded = g[g["accuracy_0_2"].notna()]
        ok_rate, url_rate = float(g["call_ok"].mean()), float(g["has_url_result"].mean())
        why = []
        if ok_rate < MIN_SUCCESS:
            why.append(f"{ok_rate:.0%} of calls succeeded (< {MIN_SUCCESS:.0%})")
        # Empty result sets are a scored outcome (often the correct answer on 'none' queries), not missing
        # evidence, so only failed calls count toward exclusion. with_url_rate is still reported.
        out.append({
            "provider": p, "label": PROVIDER_LABEL.get(p, p), "n_calls": len(g), "n_graded": int(acc.size),
            "success_rate": ok_rate, "with_url_rate": url_rate, "included": not why,
            "exclusion_reason": ("excluded: insufficient evidence - " + "; ".join(why)) if why else "",
            "latency_p50_ms": float(np.percentile(lat, 50)) if lat.size else np.nan,
            "latency_p95_ms": float(np.percentile(lat, 95)) if lat.size else np.nan,
            "latency_is_end_to_end": bool(g["latency_is_end_to_end"].any()),
            "e2e_p50_ms": float(np.percentile(e2e, 50)) if e2e.size else np.nan,
            "e2e_p95_ms": float(np.percentile(e2e, 95)) if e2e.size else np.nan,
            "within_budget_pct": float((lat <= BUDGET.get(g["usecase"].iloc[0], 3000)).mean()) if lat.size else np.nan,
            "accuracy_0_2": float(acc.mean()) if acc.size else np.nan,
            "pct_correct_calls": float(g["correct"].dropna().mean()) if acc.size else np.nan,
            "pct_correct_queries": (k_major / len(perq)) if len(perq) else np.nan,
            "pct_correct_ci_low": lo, "pct_correct_ci_high": hi,
            "correct_none": pct(g["correct_none"]),
            "freshness_pct": pct(g["freshness_pct"]),
            "newest_relevant_age_h": float(g["newest_relevant_age_h"].dropna().median()) if g["newest_relevant_age_h"].notna().any() else np.nan,
            "precision_at_5": pct(g["precision_at_5"]),
            "recall": pct(g["recall"]),
            "citation_validity": pct(g["citation_validity"]),
            "url_validity": pct(g["url_validity"]),
            "groundedness": pct(g["groundedness"]),
            "content_in_one_call": pct(g["content_in_one_call"]),
            "tokens_in_mean": float(g["tokens_in"].mean()),
            "result_tokens_top5_mean_approx": float(g["result_tokens_top5"].mean()),
            # over graded rows (run 1): approx. cl100k tokens of top-5 result content / correct answers
            "tokens_per_correct": float(graded["result_tokens_top5"].sum() / n_correct) if n_correct else np.nan,
            "cost_per_query": float(g["total_cost_usd"].mean()),
            "search_cost_per_query": float(g["search_cost_usd"].mean()),
            # search cost only, no LLM (answers/grades are produced offline by Claude Code)
            "cost_per_correct": float(graded["search_cost_usd"].sum() / n_correct) if n_correct else np.nan,
            "n_correct": n_correct,
            "errors": int(g["error"].sum()), "timeouts": int(g["timeout"].sum()), "rate_limits": int(g["rate_limit"].sum()),
            "empty_results": int(g["empty"].sum()), "in_body_errors": int(g["in_body_error"].sum()),
            "error_rate": float((g["error"] + g["empty"]).clip(upper=1).mean()),
        })
    sc = pd.DataFrame(out)
    order = {p: i for i, p in enumerate(PROVIDER_ORDER + ["youcom_knowledge"])}
    return sc.sort_values("provider", key=lambda s: s.map(lambda x: order.get(x, 99))).reset_index(drop=True)


def ranks(sc: pd.DataFrame) -> dict[str, int]:
    """You.com's rank (1 = best) among the 7 providers for each metric."""
    base = sc[sc.provider.isin(PROVIDER_ORDER) & sc["included"].astype(bool)]
    out = {}
    for m, (_, hib, _) in METRICS.items():
        s = base.set_index("provider")[m].dropna()
        if "youcom" not in s.index:
            continue
        r = s.rank(ascending=not hib, method="min")
        out[m] = int(r["youcom"])
        out[m + "__tie"] = int((s == s["youcom"]).sum()) > 1
    return out


def paired(df: pd.DataFrame, excluded: set[str] | None = None) -> pd.DataFrame:
    df = df[~df.provider.isin(excluded or set())]
    perq = df.dropna(subset=["accuracy_0_2"]).groupby(["provider", "qid"])["accuracy_0_2"].mean().unstack(0)
    rows = []
    if "youcom" not in perq.columns:
        return pd.DataFrame()
    for p in perq.columns:
        if p == "youcom":
            continue
        both = perq[["youcom", p]].dropna()
        w = int((both["youcom"] > both[p]).sum())
        l_ = int((both["youcom"] < both[p]).sum())
        t = int((both["youcom"] == both[p]).sum())
        rows.append({"rival": p, "youcom_wins": w, "youcom_losses": l_, "ties": t, "n_queries": len(both),
                     "sign_test_p": sign_test(w, l_),
                     "meaningful_6_wins_0_losses": w >= 6 and l_ == 0})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- charts
def _col(p):
    return MUTED if p in EXCLUDED else COLORS.get(p, MUTED)


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                         "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
                         "axes.titlecolor": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                         "savefig.facecolor": SURFACE})
    return plt


def _logx(ax):
    """Log x-axis with plain millisecond tick labels (no 3x10^2 style labels)."""
    from matplotlib.ticker import FixedLocator, NullLocator
    ax.set_xscale("log")
    ticks = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_xticklabels([f"{t:,}" for t in ticks])


def _title(ax, text, ctx):
    pre = "FIXTURE DATA – not results · " if ctx["fixture"] else ""
    ax.set_title(f"{pre}{text}\n{ctx['uc_label']} · run {ctx['run_date']}", loc="left", fontsize=11, color=INK)


def _fmt(v, unit):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if unit == "%":
        return f"{v * 100:.0f}%"
    if unit == "$":
        return f"${v:.3f}"
    if unit == "ms":
        return f"{v:,.0f}"
    if unit == "tok":
        return f"{v:,.0f}"
    if unit == "h":
        return f"{v:.1f}"
    return f"{v:.2f}"


def bar_chart(sc, metric, ctx, path, extra_note=""):
    plt = _plt()
    label, hib, unit = METRICS[metric]
    d = sc[["provider", "label", metric]].copy()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    y = np.arange(len(d))[::-1]
    vals = d[metric].to_numpy(dtype=float)
    plot_vals = np.nan_to_num(vals * (100 if unit == "%" else 1))
    for yi, (p, v, pv) in enumerate(zip(d.provider, vals, plot_vals)):
        ax.barh(y[yi], pv, height=0.62, color=_col(p), edgecolor=SURFACE, linewidth=2,
                hatch="//" if p == "youcom_knowledge" else None)
        ax.text(pv, y[yi], "  " + _fmt(v, unit), va="center", ha="left", color=INK, fontsize=9)
    if metric == "accuracy_0_2" and "pct_correct_ci_low" in sc:
        pass
    ax.set_yticks(y, d.label)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel(("higher is better" if hib else "lower is better") + (f" · {extra_note}" if extra_note else ""), color=MUTED)
    xmax = np.nanmax(plot_vals) if np.isfinite(plot_vals).any() and np.nanmax(plot_vals) > 0 else 1
    if unit == "%":
        ax.set_xlim(0, 115)
    elif metric == "accuracy_0_2":
        ax.set_xlim(0, 2.3)
    else:
        ax.set_xlim(0, xmax * 1.25)
    _title(ax, label, ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def latency_chart(sc, ctx, path):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    y = np.arange(len(sc))[::-1]
    for yi, row in enumerate(sc.itertuples()):
        c = _col(row.provider)
        ax.plot([row.latency_p50_ms, row.latency_p95_ms], [y[yi]] * 2, color=c, linewidth=2)
        ax.scatter([row.latency_p50_ms], [y[yi]], s=64, color=c, zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.scatter([row.latency_p95_ms], [y[yi]], s=64, color=SURFACE, zorder=3, edgecolor=c, linewidth=2)
        tag = " (end-to-end)" if row.latency_is_end_to_end else ""
        ax.text(np.nanmax([row.latency_p95_ms, row.latency_p50_ms]) if not np.isnan(row.latency_p95_ms) else 0, y[yi],
                f"   p50 {_fmt(row.latency_p50_ms, 'ms')} · p95 {_fmt(row.latency_p95_ms, 'ms')} ms{tag}",
                va="center", fontsize=8.5, color=INK)
    b = BUDGET.get(ctx["usecase"], 3000)
    ax.axvline(b, color=INK2, linestyle="--", linewidth=1)
    ax.text(b, y.max() + 0.6, f" budget {b} ms", color=INK2, fontsize=8.5, va="bottom")
    ax.set_yticks(y, sc.label)
    _logx(ax)
    ax.set_xlabel("search latency, ms (log scale) · filled dot = p50, open dot = p95 · lower is better", color=MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_ylim(-0.7, len(sc) + 0.2)
    _title(ax, "1 Search latency p50 / p95", ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def accuracy_chart(sc, ctx, path):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    y = np.arange(len(sc))[::-1]
    for yi, row in enumerate(sc.itertuples()):
        v = 0 if np.isnan(row.pct_correct_queries) else row.pct_correct_queries * 100
        ax.barh(y[yi], v, height=0.62, color=_col(row.provider), edgecolor=SURFACE, linewidth=2)
        if not np.isnan(row.pct_correct_ci_low):
            ax.plot([row.pct_correct_ci_low * 100, row.pct_correct_ci_high * 100], [y[yi]] * 2, color=INK2, linewidth=1.2)
        ax.text(102, y[yi], f"{v:.0f}% · mean {_fmt(row.accuracy_0_2, '')}/2", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, sc.label)
    ax.set_xlim(0, 135)
    ax.set_xlabel("% of queries answered correctly (SimpleQA grade A, majority of repeats); line = Wilson 95% CI", color=MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    _title(ax, "2 Accuracy", ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def reliability_chart(sc, ctx, path):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    y = np.arange(len(sc))[::-1]
    parts = [("errors", "error (non-2xx / exception)", "#d03b3b"), ("timeouts", "timeout", "#ec835a"),
             ("in_body_errors", "in-body error (HTTP 200)", "#fab219"), ("empty_results", "empty results", "#898781")]
    for yi, row in enumerate(sc.itertuples()):
        left = 0
        errs = row.errors - row.timeouts - row.in_body_errors - row.rate_limits
        vals = {"errors": max(errs + row.rate_limits, 0), "timeouts": row.timeouts,
                "in_body_errors": row.in_body_errors, "empty_results": row.empty_results}
        for k, lab, col in parts:
            if vals[k]:
                ax.barh(y[yi], vals[k], left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=2,
                        label=lab if yi == 0 or lab not in [h.get_label() for h in ax.patches] else None)
                left += vals[k]
        ax.text(left, y[yi], f"  {left}/{row.n_calls} calls", va="center", fontsize=8.5, color=INK)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in parts]
    ax.legend(handles, [l for _, l, _ in parts], loc="lower right", frameon=False, fontsize=8)
    ax.set_yticks(y, sc.label)
    ax.set_xlim(0, max(4, sc.n_calls.max() * 0.5))
    ax.set_xlabel("failed or empty calls (status colors) · lower is better", color=MUTED)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    _title(ax, "12 Reliability", ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def heatmap(matrix: pd.DataFrame, title, ctx, path, fmt=lambda v: f"{v:.2f}", vmin=0, vmax=1, xlabel="", annot=None):
    plt = _plt()
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    h = 0.45 * len(matrix.index) + 1.8
    w = max(9, 0.85 * len(matrix.columns) + 3)
    fig, ax = plt.subplots(figsize=(w, h))
    data = matrix.to_numpy(dtype=float)
    ax.imshow(np.ma.masked_invalid(data), cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            txt = (annot.iloc[i, j] if annot is not None else ("n/a" if np.isnan(v) else fmt(v)))
            light = not np.isnan(v) and (v - vmin) / ((vmax - vmin) or 1) > 0.55
            ax.text(j, i, txt, ha="center", va="center", fontsize=8, color="#ffffff" if light else INK)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=35, ha="right")
    ax.set_yticks(range(len(matrix.index)), matrix.index)
    ax.set_xticks(np.arange(-.5, len(matrix.columns), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(matrix.index), 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    if xlabel:
        ax.set_xlabel(xlabel, color=MUTED)
    _title(ax, title, ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def scatter_chart(sc, ctx, path):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 5))
    cpc = sc["cost_per_correct"].to_numpy(dtype=float)
    finite = cpc[np.isfinite(cpc)]
    smax = finite.max() if finite.size else 1
    pts = []
    for row in sc.itertuples():
        if np.isnan(row.latency_p50_ms) or np.isnan(row.accuracy_0_2):
            continue
        size = 80 + 900 * ((row.cost_per_correct / smax) if np.isfinite(row.cost_per_correct) else 1)
        ax.scatter(row.latency_p50_ms, row.accuracy_0_2, s=size, color=_col(row.provider), alpha=0.85,
                   edgecolor=SURFACE, linewidth=2, zorder=3)
        pts.append(row)
    # labels: greedy vertical de-overlap in display space, with a thin leader line
    _logx(ax)
    ax.set_ylim(-0.05, 2.2)
    fig.canvas.draw()
    placed = []
    for row in sorted(pts, key=lambda r: -r.accuracy_0_2):
        x, y = ax.transData.transform((row.latency_p50_ms, row.accuracy_0_2))
        ty = y + 14
        while any(abs(ty - py) < 26 and abs(x - px) < 150 for px, py in placed):
            ty -= 28
        placed.append((x, ty))
        ax.annotate(f"{row.label} · {_fmt(row.cost_per_correct, '$')}/correct", xy=(row.latency_p50_ms, row.accuracy_0_2),
                    xytext=(16, ty - y), textcoords="offset pixels", fontsize=8, color=INK,
                    arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.6})
    b = BUDGET.get(ctx["usecase"], 3000)
    ax.axvline(b, color=INK2, linestyle="--", linewidth=1)
    ax.text(b, 2.05, f" latency budget {b} ms", fontsize=8.5, color=INK2)
    ax.set_xlabel("search latency p50, ms (log) · grey = excluded: insufficient evidence", color=MUTED)
    ax.set_ylabel("accuracy, mean 0-2")
    ax.grid(color=GRID, linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    _title(ax, "Quality vs speed (bubble size = cost per correct answer)", ctx)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def charts_for_usecase(uc, sc, df, ctx, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    base = sc[sc.provider.isin(PROVIDER_ORDER)].reset_index(drop=True)
    EXCLUDED.clear()
    EXCLUDED.update(base.loc[~base["included"].astype(bool), "provider"])
    base["label"] = [lab + ("\n(excluded: insufficient evidence)" if p in EXCLUDED else "")
                     for p, lab in zip(base.provider, base.label)]
    latency_chart(base, ctx, outdir / "01_latency_p50_p95.png")
    accuracy_chart(base, ctx, outdir / "02_accuracy.png")
    bar_chart(base, "correct_none", ctx, outdir / "03_correct_none.png", "FreshQA strict, 'none' queries only")
    bar_chart(base, "freshness_pct", ctx, outdir / "04_freshness_in_window.png", "undated results count as not fresh")
    bar_chart(base, "newest_relevant_age_h", ctx, outdir / "05_newest_relevant_age.png", "median over calls")
    bar_chart(base, "precision_at_5", ctx, outdir / "06_precision_at_5.png", "TREC-style binary relevance, run 1")
    bar_chart(base, "recall", ctx, outdir / "07_recall.png", "vs run-time ground truth (queries with an API list)")
    bar_chart(base, "citation_validity", ctx, outdir / "08_citation_validity.png", "cited result supports the answer (graded)")
    bar_chart(base, "url_validity", ctx, outdir / "08a_url_validity.png", "top-5 returned URLs return HTTP 200")
    if base["groundedness"].notna().any():  # api mode only
        bar_chart(base, "groundedness", ctx, outdir / "08b_groundedness.png", "promptfoo context-faithfulness")
    bar_chart(base, "content_in_one_call", ctx, outdir / "09_content_in_one_call.png", "share of calls with page text")
    bar_chart(base, "tokens_per_correct", ctx, outdir / "10_tokens_per_correct.png", "approximate: cl100k tokens of top-5 results / correct")
    bar_chart(base, "cost_per_correct", ctx, outdir / "11_cost_per_correct.png", "search cost only, no LLM")
    reliability_chart(base, ctx, outdir / "12_reliability.png")
    # scorecard heatmap: each metric normalized 0-1 across providers (1 = best), raw value annotated
    cols, norm, ann = [], {}, {}
    for m, (label, hib, unit) in METRICS.items():
        s = base.set_index("label")[m].astype(float)
        if s.notna().sum() == 0:
            continue
        lo, hi = s.min(), s.max()
        n = (s - lo) / (hi - lo) if hi > lo else s * 0 + 1
        norm[label] = n if hib else 1 - n
        ann[label] = s.map(lambda v: _fmt(v, unit))
        cols.append(label)
    if cols:
        heatmap(pd.DataFrame(norm)[cols], "Scorecard: every metric, normalized per column (dark = best)", ctx,
                outdir / "13_scorecard_heatmap.png", annot=pd.DataFrame(ann)[cols].fillna("n/a"))
    scatter_chart(base, ctx, outdir / "14_quality_vs_speed.png")
    perq = df[df.provider.isin(PROVIDER_ORDER)].dropna(subset=["accuracy_0_2"]).groupby(["provider", "qid"])["accuracy_0_2"].mean().unstack(1)
    if not perq.empty:
        perq = perq.reindex([p for p in PROVIDER_ORDER if p in perq.index])
        perq.index = [PROVIDER_LABEL[p] for p in perq.index]
        perq = perq[sorted(perq.columns, key=lambda q: (re.sub(r"\d+", "", q), int(re.sub(r"\D", "", q) or 0)))]
        heatmap(perq, "Per-query accuracy (0-2, mean of repeats)", ctx, outdir / "15_per_query_heatmap.png",
                fmt=lambda v: f"{v:.1f}", vmin=0, vmax=2, xlabel="query")


def cross_industry_chart(rank_tbl: pd.DataFrame, ties: pd.DataFrame, ctx, path):
    if rank_tbl.empty:
        return
    m = rank_tbl.astype(float)
    ann = m.copy().astype(object)
    for i in m.index:
        for c in m.columns:
            v = m.loc[i, c]
            ann.loc[i, c] = "n/a" if np.isnan(v) else f"#{int(v)}" + (" (tie)" if bool(ties.loc[i, c]) else "")
    n = len(PROVIDER_ORDER)
    heatmap(n + 1 - m, f"You.com rank per metric per industry (1 = best of the included providers, max {n})",
            {**ctx, "uc_label": "All use cases"}, path, vmin=1, vmax=n, annot=ann)


# ----------------------------------------------------------------------------- friction
def friction(ctx, outdir: Path, log_path: Path, summary_path: Path):
    plt = _plt()
    outdir.mkdir(parents=True, exist_ok=True)
    md = []
    if log_path.exists():
        fl = pd.read_csv(log_path)
        if not fl.empty:
            fl["source_kind"] = np.where(fl["source"].astype(str).str.startswith("auto"), "auto", "manual")
            fl["category"] = fl.get("category", pd.Series(["other"] * len(fl))).fillna("other")
            tab = fl.groupby(["provider", "category"]).size().unstack(fill_value=0)
            sev = fl.groupby(["provider", "severity"]).size().unstack(fill_value=0)
            kind = fl.groupby(["provider", "source_kind"]).size().unstack(fill_value=0)
            md.append("## Friction rows per provider and category (manual + auto)\n")
            md.append(tab.to_markdown())
            md.append("\n\n## Severity counts\n")
            md.append(sev.to_markdown())
            md.append("\n\n## Manual vs automatic rows\n")
            md.append(kind.to_markdown())
            # stacked horizontal bars by category
            provs = [p for p in PROVIDER_ORDER if p in tab.index] + [p for p in tab.index if p not in PROVIDER_ORDER]
            tab = tab.reindex(provs)
            cats = list(tab.columns)
            cat_colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
            fig, ax = plt.subplots(figsize=(10, 4.5))
            y = np.arange(len(tab))[::-1]
            left = np.zeros(len(tab))
            for i, c in enumerate(cats):
                col = cat_colors[i] if i < len(cat_colors) else MUTED  # >8 categories fold into gray
                ax.barh(y, tab[c].to_numpy(), left=left, color=col, edgecolor=SURFACE, linewidth=2, height=0.62, label=c)
                left += tab[c].to_numpy()
            for yi, tot in zip(y, left):
                ax.text(tot, yi, f"  {int(tot)}", va="center", fontsize=8.5, color=INK)
            ax.set_yticks(y, [PROVIDER_LABEL.get(p, p) for p in tab.index])
            ax.legend(frameon=False, fontsize=8, loc="center left", bbox_to_anchor=(1.01, 0.5))
            ax.set_xlabel("friction rows (manual notes + harness auto-log)", color=MUTED)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            _title(ax, "Friction log by category", {**ctx, "uc_label": "All use cases"})
            fig.tight_layout()
            fig.savefig(outdir / "friction_by_category.png", dpi=150)
            plt.close(fig)
    if summary_path.exists():
        s = pd.read_csv(summary_path)
        s["ttfc_minutes"] = pd.to_numeric(s["ttfc_minutes"], errors="coerce")
        md.append("\n\n## Provider setup summary\n")
        md.append(s.to_markdown(index=False))
        if s["ttfc_minutes"].notna().any():
            s = s.set_index("provider").reindex([p for p in PROVIDER_ORDER if p in set(s.provider)])
            fig, ax = plt.subplots(figsize=(8, 4))
            y = np.arange(len(s))[::-1]
            for yi, (p, v) in enumerate(s["ttfc_minutes"].items()):
                ax.barh(y[yi], 0 if np.isnan(v) else v, color=COLORS.get(p, MUTED), height=0.62, edgecolor=SURFACE, linewidth=2)
                ax.text(0 if np.isnan(v) else v, y[yi], "  n/a" if np.isnan(v) else f"  {v:.0f} min", va="center", fontsize=8.5, color=INK)
            ax.set_yticks(y, [PROVIDER_LABEL.get(p, p) for p in s.index])
            ax.set_xlabel("minutes from opening signup to first successful API call · lower is better", color=MUTED)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
            _title(ax, "Time to first successful call", {**ctx, "uc_label": "Friction log"})
            fig.tight_layout()
            fig.savefig(outdir / "friction_time_to_first_call.png", dpi=150)
            plt.close(fig)
    return "\n".join(md)


# ----------------------------------------------------------------------------- main
def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return str(p.relative_to(EVAL)) if p.is_relative_to(EVAL) else str(p)


def latest(pattern: str, base: Path) -> Path | None:
    c = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime)
    return c[-1] if c else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", action="append", default=[])
    ap.add_argument("--fixture", action="store_true", help="use tests/fixtures (FAKE data) -> out/fixture_charts/")
    ap.add_argument("--out", default=None)
    ap.add_argument("--grades-dir", default=None, help="dir with grades_{usecase}.csv (default grading/)")
    a = ap.parse_args(argv)
    if a.fixture:
        src = EVAL / "tests" / "fixtures"
        files = sorted(src.glob("fixture_*_results.json"))
        out = Path(a.out or EVAL / "out" / "fixture_charts")
        flog, fsum = src / "fixture_friction_log.csv", src / "fixture_friction_summary.csv"
        gdir = Path(a.grades_dir or src / "grades")
    else:
        gdir = Path(a.grades_dir or EVAL / "grading")
        files = [Path(f) for f in a.results] or [p for p in (latest(f"{uc}_results*.json", EVAL / "out") for uc in USECASES + ["finance_f1_variant"]) if p]
        out = Path(a.out or EVAL / "out")
        flog, fsum = EVAL / "friction_log.csv", EVAL / "friction" / "friction_summary.csv"
    if not files:
        print("no promptfoo result files found (run ./run.sh run <usecase> first, or use --fixture)")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    allrows, run_dates = [], []
    for f in files:
        d = load(f)
        allrows += d["rows"]
        if d["timestamp"]:
            run_dates.append(str(d["timestamp"])[:10])
    run_date = max(run_dates) if run_dates else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = extract([r for r in allrows if r["provider"] in PROVIDER_ORDER + ["youcom_knowledge"]])  # Claude web search dropped
    summary = [f"# {'FIXTURE DATA – not results. ' if a.fixture else ''}Search API live eval summary (run {run_date})\n",
               f"Inputs: {', '.join(str(f.relative_to(EVAL)) if f.is_relative_to(EVAL) else str(f) for f in files)}\n"]
    rank_tbl = {}
    for uc in [u for u in USECASES + ["simpleqa", "smoke"] if u in set(df.usecase)]:
        grades = load_grades(gdir / f"grades_{uc}.csv")
        g = apply_grades(df[df.usecase == uc], grades)
        hc = human_check(uc, grades, out / "grading")
        sc = scorecard(g)
        sc.to_csv(out / f"{uc}_scorecard.csv", index=False)
        perq = g.groupby(["qid", "provider"]).agg(accuracy=("accuracy_0_2", "mean"), latency_ms=("search_latency_ms", "median"),
                                                  freshness=("freshness_pct", "mean"), p_at_5=("precision_at_5", "mean")).reset_index()
        perq.to_csv(out / f"{uc}_per_query.csv", index=False)
        pr = paired(g, set(sc.loc[~sc["included"].astype(bool), "provider"]))
        if not pr.empty:
            pr.to_csv(out / f"{uc}_paired_vs_youcom.csv", index=False)
        rk = ranks(sc)
        rank_tbl[UC_LABEL.get(uc, uc)] = rk
        ctx = {"fixture": a.fixture, "uc_label": UC_LABEL.get(uc, uc), "run_date": run_date, "usecase": uc}
        charts_for_usecase(uc, sc, g, ctx, out / "charts" / uc)
        show = ["label", "n_calls", "latency_p50_ms", "latency_p95_ms", "accuracy_0_2", "pct_correct_queries",
                "pct_correct_ci_low", "pct_correct_ci_high", "correct_none", "freshness_pct", "newest_relevant_age_h",
                "precision_at_5", "recall", "url_validity", "citation_validity", "content_in_one_call",
                "tokens_per_correct", "cost_per_correct", "error_rate", "included"]
        if sc["groundedness"].notna().any():
            show.insert(show.index("content_in_one_call"), "groundedness")
        summary.append(f"\n## {UC_LABEL.get(uc, uc)}\n")
        summary.append(f"Grades: {_rel(gdir / f'grades_{uc}.csv') + ' (Claude Code, run 1 of each query x provider)' if grades is not None else 'none found - accuracy/P@5/citation support are n/a until Claude Code grades the export'}. "
                       "Tokens per correct = approximate (tiktoken cl100k over top-5 result content); "
                       "cost per correct = search cost only, no LLM.\n")
        summary.append(sc[show].round(3).to_markdown(index=False))
        for r in sc[~sc["included"].astype(bool)].itertuples():
            summary.append(f"\n- **{r.label}**: {r.exclusion_reason} (not ranked)")
        if hc:
            ag = "not reviewed yet" if np.isnan(hc["agreement"]) else f"{hc['agreement']:.0%} of {hc['reviewed']} reviewed rows"
            summary.append(f"\n\nHuman check: {hc['n_sample']} of {hc['n_graded']} graded rows sampled (20%, seed 42) -> "
                           f"{hc['path'].name}; agreement with Claude Code grades: {ag}.\n")
        if not pr.empty:
            summary.append("\n\nPaired per-query accuracy vs You.com (sign test; 'meaningful' = >=6 wins and 0 losses):\n")
            summary.append(pr.round(4).to_markdown(index=False))
        summary.append(f"\n\nYou.com rank per metric (1 = best of the included providers): {json.dumps({k: v for k, v in rk.items() if not k.endswith('__tie')})}\n")
        if (sc.provider == "youcom_knowledge").any():
            summary.append("\nYou.com knowledge=core variant (F1 only) is listed in the scorecard and excluded from ranks.\n")
    rt_all = pd.DataFrame(rank_tbl)
    rt_all = rt_all[[c for c in rt_all.columns if c in [UC_LABEL[u] for u in USECASES]]] if not rt_all.empty else rt_all
    if not rt_all.empty:
        rt = rt_all.loc[[i for i in rt_all.index if not str(i).endswith("__tie")]]
        ties = rt_all.loc[[i for i in rt_all.index if str(i).endswith("__tie")]].fillna(False)
        ties.index = [i.removesuffix("__tie") for i in ties.index]
        ties = ties.reindex(rt.index).fillna(False)
        rt.index = ties.index = [METRICS[m][0] for m in rt.index]
        rt.to_csv(out / "cross_industry_youcom_rank.csv")
        cross_industry_chart(rt, ties, {"fixture": a.fixture, "run_date": run_date, "usecase": "all"},
                             (out / "charts").joinpath("cross_industry_youcom_rank.png"))
    fr = friction({"fixture": a.fixture, "run_date": run_date, "usecase": "all"}, out / "charts", flog, fsum)
    if fr:
        (out / "friction_summary.md").write_text(("# FIXTURE DATA – not results\n\n" if a.fixture else "# Friction summary\n\n") + fr)
        summary.append("\n\nSee friction_summary.md for the friction log summary.\n")
    (out / "summary.md").write_text("\n".join(summary))
    print(f"wrote scorecards, summary.md and charts to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
