"""Resolve answer keys at grading time.

tests/*.yaml carry expected_answer: "[FILL AT RUN TIME]". The human fills
answer_keys.csv (with Wayback evidence) just before the run; graders read the
CSV when the YAML still holds the placeholder, so only one sheet is edited.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .settings import EVAL_DIR

PLACEHOLDER = "[FILL AT RUN TIME]"
import os

KEYS_CSV = Path(os.environ.get("EVAL_KEYS_CSV") or EVAL_DIR / "answer_keys.csv")


def _is_blank(v) -> bool:
    return v is None or str(v).strip() == "" or str(v).strip().upper().startswith("[FILL")


def load_keys(path: Path | None = None) -> dict[str, dict]:
    path = Path(path or KEYS_CSV)
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["qid"].strip(): r for r in csv.DictReader(f) if r.get("qid")}


def resolve(vars_: dict, path: Path | None = None) -> dict:
    """Return {expected_answer, expect_none, tolerance, filled} for a test's vars."""
    row = load_keys(path).get(str(vars_.get("qid", "")), {})
    exp = vars_.get("expected_answer")
    if _is_blank(exp):
        exp = row.get("expected_answer")
    en = vars_.get("expect_none")
    if _is_blank(en):
        en = row.get("expect_none")
    expect_none = str(en).strip().lower() in {"true", "1", "yes", "y"}
    tol = vars_.get("tolerance") or row.get("tolerance") or ""
    return {"expected_answer": None if _is_blank(exp) else str(exp).strip(),
            "expect_none": expect_none, "expect_none_known": not _is_blank(en),
            "tolerance": tol, "filled": not _is_blank(exp)}
