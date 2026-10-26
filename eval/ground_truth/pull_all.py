#!/usr/bin/env python3
"""Pull every open-API ground truth for one use case (or all).

  python ground_truth/pull_all.py gtm|insurance|finance|all [--out DIR]

Default --out is eval/ground_truth (read by asserts/recall.py). Pages without an
API (Citizens, NHC graphic advisories, regulators, governors, Nasdaq, CNBC,
trending page, subreddit 'new') are archived by evidence/capture.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pull_fema  # noqa: E402
import pull_github  # noqa: E402
import pull_hn  # noqa: E402
import pull_markets  # noqa: E402
import pull_sec  # noqa: E402
import pull_stackexchange  # noqa: E402
import pull_statuspage  # noqa: E402
import pull_weather  # noqa: E402

SETS = {
    "gtm": [pull_github.main, pull_hn.main, pull_stackexchange.main, pull_statuspage.main],
    "insurance": [pull_weather.main, pull_fema.main],
    "finance": [pull_markets.main, pull_sec.main],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("usecase", choices=list(SETS) + ["all"])
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for uc in (SETS if a.usecase == "all" else [a.usecase]):
        print(f"[{uc}] -> {out}")
        for fn in SETS[uc]:
            fn(out)


if __name__ == "__main__":
    main()
