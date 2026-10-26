"""Load promptfoo JSON exports (promptfoo 0.124.0 schema) into flat rows.

Export layout verified by a local run (2026-10-08):
  top level: evalId, results{version, timestamp, prompts, results[], stats}, config, metadata
  row: vars, provider{id,label}, response{output, metadata, tokenUsage, cost, latencyMs},
       latencyMs, cost, namedScores, success, error, gradingResult{componentResults[{pass, score, reason, assertion{type, metric}}]}
"""
from __future__ import annotations

import json
from pathlib import Path

# Claude built-in web search (claude_native) is no longer compared: rows from it are ignored by analysis/export.
PROVIDER_ORDER = ["youcom", "tavily", "exa", "parallel"]
PROVIDER_LABEL = {"youcom": "You.com", "tavily": "Tavily", "exa": "Exa", "parallel": "Parallel",
                  "firecrawl": "Firecrawl", "linkup": "Linkup", "claude_native": "Claude web_search",
                  "youcom_knowledge": "You.com (knowledge=core variant)"}
LABEL_TO_KEY = {v: k for k, v in PROVIDER_LABEL.items()} | {"Claude web search": "claude_native"}


def provider_key(row: dict) -> str:
    md = (row.get("response") or {}).get("metadata") or row.get("metadata") or {}
    if md.get("provider"):
        return md["provider"]
    p = row.get("provider") or {}
    label = p.get("label") if isinstance(p, dict) else str(p)
    if label in LABEL_TO_KEY:
        return LABEL_TO_KEY[label]
    pid = p.get("id", "") if isinstance(p, dict) else ""
    return Path(pid.replace("file://", "")).stem or label


def components(row: dict) -> dict[str, dict]:
    """metric name (or assertion type) -> {score, pass, reason}"""
    out = {}
    for c in ((row.get("gradingResult") or {}).get("componentResults") or []):
        a = c.get("assertion") or {}
        key = a.get("metric") or a.get("type")
        if key and key not in out:
            out[key] = {"score": c.get("score"), "pass": c.get("pass"), "reason": c.get("reason") or ""}
    return out


def load(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text())
    res = d.get("results") or {}
    rows = []
    for r in res.get("results", []):
        resp = r.get("response") or {}
        md = resp.get("metadata") or {}
        v = r.get("vars") or {}
        named = dict(r.get("namedScores") or {})
        named.update((r.get("gradingResult") or {}).get("namedScores") or {})
        rows.append({
            "provider": provider_key(r), "variant": md.get("variant"),
            "usecase": v.get("usecase") or md.get("usecase"), "qid": v.get("qid") or md.get("qid"),
            "repeat": md.get("repeat_index"), "test_idx": r.get("testIdx"),
            "output": resp.get("output") if resp.get("output") is not None else "",
            "error": r.get("error") or md.get("error"), "error_type": md.get("error_type"),
            "md": md, "vars": v, "named": named, "comp": components(r),
            "latency_ms_pf": r.get("latencyMs"), "cost_pf": r.get("cost"),
        })
    return {"path": str(path), "timestamp": res.get("timestamp"), "eval_id": d.get("evalId"),
            "promptfoo_version": (d.get("metadata") or {}).get("promptfooVersion"), "rows": rows}
