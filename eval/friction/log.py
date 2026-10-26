#!/usr/bin/env python3
"""Open-ended friction log: append timestamped rows to eval/friction_log.csv.

Three ways to log (all free text; nothing is limited to a fixed template):

  1. Classic entry (Google DevRel friction-log style):
       python friction/log.py <provider> "<step>" "<what happened>" <green|yellow|red> [minutes_lost]
              [--category docs] [--expected "..."] [--feeling "..."] [--docs URL] [--fix "..."]
     e.g.  python friction/log.py tavily "first call" "401 with Bearer header" red 5

  2. Quick note (anything you notice, severity defaults to green):
       python friction/log.py note exa "dashboard shows credits only after refresh" [--category dashboard] [--severity yellow]

  3. Automatic (source=auto): the harness appends a row for every anomaly it sees
     (non-2xx, in-body errors, timeouts, retries, rate limits, empty results,
     schema drift vs docs, ignored filters, latency over budget, unexpected cost,
     deprecation warnings/headers, SDK warnings) with qid, provider, run id and
     a pointer to the raw JSON. See friction/README.md.

Categories (optional, free text accepted too): signup, auth, docs, sdk/install,
params, results quality, latency, rate limit, billing/credits, dashboard,
support, other.  Severity: Green = minor, Yellow = slowed me down, Red = blocked me.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = Path(os.environ.get("FRICTION_LOG", EVAL_DIR / "friction_log.csv"))
COLUMNS = ["time_utc", "provider", "category", "step", "expected", "actual", "severity", "minutes_lost",
           "feeling", "docs_link", "fix", "source", "qid", "run_id", "raw_file"]
SEVERITIES = {"green": "Green", "yellow": "Yellow", "red": "Red"}
CATEGORIES = ["signup", "auth", "docs", "sdk/install", "params", "results quality", "latency",
              "rate limit", "billing/credits", "dashboard", "support", "other"]
_LOCK = threading.Lock()


def _migrate_header(path: Path) -> None:
    """Upgrade an older log file to the current columns without losing rows."""
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
        f.seek(0)
        header = next(csv.reader(f), [])
    if header == COLUMNS:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})


def append_row(provider: str, step: str, actual: str, severity: str = "green",
               minutes_lost: float | str = "", expected: str = "", feeling: str = "",
               docs_link: str = "", fix: str = "", source: str = "manual", category: str = "other",
               qid: str = "", run_id: str = "", raw_file: str = "", path: Path | None = None) -> dict:
    path = Path(path or LOG_PATH)
    sev = SEVERITIES.get(str(severity).lower())
    if sev is None:
        raise ValueError(f"severity must be one of {list(SEVERITIES)}")
    row = {"time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "provider": provider,
           "category": category or "other", "step": step, "expected": expected, "actual": str(actual)[:600],
           "severity": sev, "minutes_lost": minutes_lost, "feeling": feeling, "docs_link": docs_link, "fix": fix,
           "source": source, "qid": qid, "run_id": run_id, "raw_file": raw_file}
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        if not new:
            _migrate_header(path)
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if new:
                w.writeheader()
            w.writerow(row)
    return row


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "note":
        ap = argparse.ArgumentParser(prog="log.py note")
        ap.add_argument("provider")
        ap.add_argument("text")
        ap.add_argument("--category", default="other")
        ap.add_argument("--severity", default="green", choices=list(SEVERITIES))
        ap.add_argument("--minutes", default="")
        a = ap.parse_args(argv[1:])
        row = append_row(a.provider, "note", a.text, a.severity, a.minutes, category=a.category, source="manual-note")
    else:
        ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        ap.add_argument("provider")
        ap.add_argument("step")
        ap.add_argument("actual")
        ap.add_argument("severity", choices=list(SEVERITIES))
        ap.add_argument("minutes_lost", nargs="?", default="")
        ap.add_argument("--category", default="other", help="one of: " + ", ".join(CATEGORIES) + " (or any text)")
        ap.add_argument("--expected", default="")
        ap.add_argument("--feeling", default="")
        ap.add_argument("--docs", default="")
        ap.add_argument("--fix", default="")
        a = ap.parse_args(argv)
        row = append_row(a.provider, a.step, a.actual, a.severity, a.minutes_lost, a.expected, a.feeling,
                         a.docs, a.fix, source="manual", category=a.category)
    print(f"logged to {LOG_PATH}: {row['time_utc']} {row['provider']} [{row['category']}] {row['severity']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
