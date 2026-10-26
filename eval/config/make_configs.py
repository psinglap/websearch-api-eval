#!/usr/bin/env python3
"""Generate promptfooconfig.{gtm,insurance,finance,smoke,simpleqa}.yaml + the F1 variant config.

  .venv/bin/python config/make_configs.py              # mode = settings.answer_mode (default: offline)
  .venv/bin/python config/make_configs.py --mode api   # legacy: Claude answers + LLM-graded assertions

offline: 6 search providers, only assertions that need no LLM (freshness, recall,
URL validity of returned results, content-in-one-call, latency budget, reliability,
search cost); no grader provider. Accuracy / P@5 / citation support are graded later
by Claude Code from ./run.sh export <uc> (grading/RUBRIC.md).
api: adds the SimpleQA grader, P@5 labels, citation support and context-faithfulness.

Verified against promptfoo 0.124.0 (docs + a local run, 2026-10-08):
  - python providers: id file://providers/x.py (call_api), config.workers / timeout / pythonExecutable;
    a returned latencyMs overrides promptfoo's own timing; workers persist between calls
  - python assertions: get_assert(output, context); context['metadata'] = provider metadata;
    dict returns with named_scores; weight 0 => auto-pass (used only for the promptfoo latency assertion)
  - context-faithfulness requires a `query` var plus contextTransform (JS expression over output/context)
  - grader: defaultTest.options.provider
"""
from pathlib import Path

import argparse
import sys

import yaml

EVAL = Path(__file__).resolve().parents[1]
PY = ".venv/bin/python"
GRADER = {"id": "anthropic:messages:claude-opus-5-5", "config": {"max_tokens": 8000, "effort": "medium"}}
BUDGET = {"gtm": 3000, "insurance": 500, "finance": 3000, "simpleqa": 3000, "smoke": 3000}

PROVIDERS = [("youcom", "You.com"), ("tavily", "Tavily"), ("exa", "Exa"), ("parallel", "Parallel")]
# Firecrawl and Linkup excluded by the user (2026-10-08); adapters kept on disk, unused.
# Claude built-in web search (providers/claude_native.py) is dropped from the comparison (kept on disk, unused).

CONTEXT_JS = (
    "(function(){const m=context.metadata||{};const rs=(m.results||[]).slice(0,5)"
    ".map((r,i)=>'['+(i+1)+'] '+r.url+'\\n'+String(r.content||r.snippet||'').slice(0,2000));"
    "const cs=(m.citations||[]).map(c=>c.url+': '+(c.cited_text||''));"
    "const t=rs.concat(cs).join('\\n\\n');return t.trim()?t:'(no retrieved context)';})()"
)


def provider(name, label, extra=None):
    cfg = {"pythonExecutable": PY, "workers": 1, "timeout": 300000}
    cfg.update(extra or {})
    return {"id": f"file://providers/{name}.py", "label": label, "config": cfg}


def asserts(usecase, mode="offline"):
    py = lambda f, metric, **kw: {"type": "python", "value": f"file://asserts/{f}.py", "metric": metric, **kw}
    if mode != "api":
        return [
            # 4/5 Freshness - provider date -> htmldate -> url -> undated (no LLM relevance labels)
            py("freshness", "freshness"),
            # 7 Recall - run-time ground truth from open APIs
            py("recall", "recall"),
            # 8 URL validity of the top-5 returned results (HTTP 200); citation support graded later
            py("citation_validity", "url_validity"),
            # 9 Content in one call
            py("content_one_call", "content_in_one_call"),
            # 1 Latency vs budget + promptfoo's built-in latency assertion (weight 0 = non-blocking)
            py("latency_budget", "latency_budget"),
            {"type": "latency", "threshold": BUDGET[usecase], "weight": 0},
            # 11 Search cost (no LLM tokens in offline mode)
            py("token_cost", "token_cost"),
            # 12 Reliability
            py("reliability", "reliability"),
        ]
    return [
        # 2 Accuracy - SimpleQA official grader (A=2, B/C=0); partial credit per-test for list answers
        py("accuracy_simpleqa", "accuracy"),
        # 6 Precision@5 - TREC-style binary relevance, LLM assessor (labels reused by freshness)
        py("precision_at5", "precision_at_5"),
        # 4/5 Freshness - provider date -> htmldate -> url -> undated; FreshQA-style windows
        py("freshness", "freshness"),
        # 7 Recall - run-time ground truth from open APIs (N/A when no ground_truth/{qid}.json)
        py("recall", "recall"),
        # 8 Citation validity - HTTP 200 + rapidfuzz support (ALCE-style)
        py("citation_validity", "citation_validity"),
        # 8 Groundedness - promptfoo context-faithfulness (RAGAS-style) over the top-5 results
        {"type": "context-faithfulness", "contextTransform": CONTEXT_JS, "threshold": 0.5, "metric": "groundedness"},
        # 9 Content in one call
        py("content_one_call", "content_in_one_call"),
        # 1 Latency - search-only latency vs budget (non-blocking measurement) ...
        py("latency_budget", "latency_budget"),
        # ... and promptfoo's built-in latency assertion on the returned latencyMs (weight 0 = non-blocking)
        {"type": "latency", "threshold": BUDGET[usecase], "weight": 0},
        # 10/11 Tokens and cost
        py("token_cost", "token_cost"),
        # 12 Reliability
        py("reliability", "reliability"),
    ]


def config(usecase, tests, providers=None, desc=None, mode="offline"):
    dt = {"assert": asserts(usecase if usecase in BUDGET else "gtm", mode)}
    if mode == "api":
        dt = {"options": {"provider": GRADER}, **dt}
    return {
        "description": desc or (f"Live web-search eval - {usecase} (6 providers, search only; graded offline by Claude Code)"
                                if mode != "api" else f"Live web-search eval - {usecase} (6 providers, same answer model)"),
        "prompts": ["file://prompts/query.txt"],
        "providers": providers or [provider(n, l) for n, l in PROVIDERS],
        "defaultTest": dt,
        "tests": tests,
        "evaluateOptions": {"maxConcurrency": 4},
        "outputPath": [f"out/{usecase}_results.json"],
    }


def write(name, cfg):
    hdr = ("# Generated by config/make_configs.py - edit that file, then: .venv/bin/python config/make_configs.py\n"
           "# Run via ./run.sh (adds --repeat 3 --no-cache and exports JSON/CSV).\n")
    (EVAL / name).write_text(hdr + yaml.safe_dump(cfg, sort_keys=False, width=200))


def main(argv=None):
    sys.path.insert(0, str(EVAL))
    from lib.settings import settings
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "api"], default=None)
    mode = ap.parse_args(argv).mode or settings().get("answer_mode", "offline")
    for uc in ("gtm", "insurance", "finance"):
        write(f"promptfooconfig.{uc}.yaml", config(uc, f"file://tests/{uc}.yaml", mode=mode))
    write("promptfooconfig.finance_f1_variant.yaml", config(
        "finance", "file://tests/finance_f1_variant.yaml",
        providers=[provider("youcom", "You.com [variant: knowledge=core]",
                            {"knowledge": "core", "variant": "knowledge=core", "provider_name": "youcom_knowledge"})],
        desc="F1 only - You.com with knowledge=core (variant, not a separate competitor)", mode=mode))
    write("promptfooconfig.smoke.yaml", config("smoke", "file://tests/smoke.yaml",
                                              desc="Smoke test - 1 query x 6 providers x 1 repeat", mode=mode))
    # the SimpleQA cross-check is optional and LLM-graded by design -> always api mode
    sq = config("simpleqa", "file://crosscheck/simpleqa_sample.yaml",
                desc="SimpleQA control sample (20 q, seed 42) - OPTIONAL harness cross-check (api mode)", mode="api")
    write("promptfooconfig.simpleqa.yaml", sq)
    print(f"configs written (answer_mode={mode})")


if __name__ == "__main__":
    main()
