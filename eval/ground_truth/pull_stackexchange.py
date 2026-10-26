#!/usr/bin/env python3
"""Stack Overflow ground truth via the Stack Exchange API (G5).
API: https://api.stackexchange.com/docs/questions (no key needed; 300 req/day per IP)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, since  # noqa: E402

LAG = re.compile(r"lag|latenc|slow|delay|throughput|rebalanc|backlog", re.I)


def g5(out, hours=24):
    p = Puller("G5", out, hours)
    body = p.get("questions_apache_kafka", "https://api.stackexchange.com/2.3/questions",
                 params={"tagged": "apache-kafka", "site": "stackoverflow", "sort": "creation", "order": "desc",
                         "fromdate": int(since(hours).timestamp()), "pagesize": 100})
    qs = (body or {}).get("items", [])
    for q in qs:
        d = datetime.fromtimestamp(q["creation_date"], tz=timezone.utc).isoformat()
        if LAG.search(q.get("title", "")):
            p.add(q["link"], q["title"], d, tags=q.get("tags"))
    p.notes.append(f"{len(qs)} apache-kafka questions in the window; kept {len(p.items)} about lag/latency.")
    return p.save()


def main(out):
    try:
        g5(out)
    except Exception as e:
        print(f"  g5 failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
