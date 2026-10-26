"""Shared helpers for promptfoo python assertions (get_assert(output, context))."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from lib import meta  # noqa: E402
from lib.settings import out_dir  # noqa: E402

_LOCK = threading.Lock()
NONE_RX = re.compile(r"^\s*\**\s*NONE\b|\bnot found\b|\bno (?:such|matching|qualifying)\b|\bnone (?:yet|found)\b", re.I)


def ctx(context):
    md = meta.metadata(context)
    v = meta.vars_(context)
    return md, v


def is_error_output(output: str) -> bool:
    return str(output or "").startswith(("[SEARCH ERROR]", "[ANSWER ERROR]"))


def says_none(output: str) -> bool:
    first = (str(output or "").strip().splitlines() or [""])[0]
    return bool(NONE_RX.search(first))


def row_key(md: dict, v: dict) -> str:
    urls = "|".join(r.get("url", "") for r in md.get("results", [])[:10])
    h = hashlib.sha1(f"{v.get('qid')}|{md.get('provider')}|{md.get('requested_at_utc')}|{urls}".encode()).hexdigest()[:16]
    return h


def cache_dir(name: str) -> Path:
    p = out_dir() / "cache" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def log(assertion: str, md: dict, v: dict, details: dict) -> None:
    rec = {"t": datetime.now(timezone.utc).isoformat(), "assertion": assertion, "qid": v.get("qid"),
           "usecase": v.get("usecase"), "provider": md.get("provider"), "variant": md.get("variant"),
           "repeat_index": md.get("repeat_index"), "requested_at_utc": md.get("requested_at_utc"), **details}
    with _LOCK, open(out_dir() / "assert_log.jsonl", "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def result(passed: bool, score: float, reason: str, named: dict | None = None) -> dict:
    out = {"pass": bool(passed), "score": float(score), "reason": reason}
    if named:
        out["named_scores"] = {k: float(v) for k, v in named.items() if v is not None}
    return out


def not_applicable(reason: str) -> dict:
    # pass=True, score=1 keeps promptfoo's row pass-rate meaningful; analysis
    # skips N/A rows by reading the reason prefix.
    return {"pass": True, "score": 1.0, "reason": "N/A: " + reason}


def ungraded(reason: str) -> dict:
    return {"pass": False, "score": 0.0, "reason": "UNGRADED: " + reason}
