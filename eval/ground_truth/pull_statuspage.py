#!/usr/bin/env python3
"""Confluent Cloud status (G7) via the Atlassian Statuspage public JSON API.
Endpoints: https://status.confluent.cloud/api/v2/incidents/unresolved.json and /summary.json
(Statuspage API docs: https://doers.statuspage.io/api/v2/ ; probed at run time - if the
page is not Statuspage-hosted the HTML is saved instead and the key is written by hand.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller  # noqa: E402

BASE = "https://status.confluent.cloud"


def g7(out, hours=24):
    p = Puller("G7", out, hours)
    unresolved = p.get("incidents_unresolved", f"{BASE}/api/v2/incidents/unresolved.json")
    summary = p.get("summary", f"{BASE}/api/v2/summary.json")
    if unresolved is None and summary is None:
        p.get("status_page_html", BASE, as_json=False)
        p.notes.append("No Statuspage JSON API responded; key must be written from the saved HTML/screenshot.")
    for inc in (unresolved or {}).get("incidents", []):
        p.add(inc.get("shortlink") or f"{BASE}/incidents/{inc.get('id')}", inc.get("name"), inc.get("started_at") or inc.get("created_at"),
              status=inc.get("status"), impact=inc.get("impact"),
              components=[c.get("name") for c in inc.get("components", [])])
    if summary:
        p.notes.append(f"status indicator: {(summary.get('status') or {}).get('indicator')} - "
                       f"{(summary.get('status') or {}).get('description')}")
    if not p.items:
        p.notes.append("No unresolved incidents at pull time => correct answer is 'none'.")
    return p.save()


def main(out):
    try:
        g7(out)
    except Exception as e:
        print(f"  g7 failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
