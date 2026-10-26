#!/usr/bin/env python3
"""OpenFEMA ground truth (I6) - disaster declarations for Isaias.
API: https://www.fema.gov/about/openfema/api ; dataset DisasterDeclarationsSummaries v2
Trap: "Isaias" is a reused name (Hurricane Isaias, 2020, DR-4560/4563/...). We save ALL
Isaias records and keep only those declared inside the window as the key.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, since  # noqa: E402

API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"


def i6(out, hours=48):
    p = Puller("I6", out, hours)
    body = p.get("fema_isaias_all", API, params={"$filter": "contains(declarationTitle,'ISAIAS')",
                                                 "$orderby": "declarationDate desc", "$top": 200})
    recs = (body or {}).get("DisasterDeclarationsSummaries", [])
    cutoff = since(hours).strftime("%Y-%m-%dT%H:%M:%S")
    old = [r for r in recs if (r.get("declarationDate") or "") < cutoff]
    for r in recs:
        if (r.get("declarationDate") or "") >= cutoff:
            p.add(f"https://www.fema.gov/disaster/{r.get('disasterNumber')}", f"{r.get('declarationType')}-{r.get('disasterNumber')} "
                  f"{r.get('state')} {r.get('declarationTitle')}", r.get("declarationDate"), state=r.get("state"),
                  declaration_string=r.get("femaDeclarationString"))
    p.notes.append(f"{len(recs)} Isaias records total; {len(old)} are older than the window (e.g. 2020) - stale traps.")
    if not p.items:
        p.notes.append("No Isaias declaration in the window => correct answer is 'none yet'.")
    return p.save()


def main(out):
    try:
        i6(out)
    except Exception as e:
        print(f"  i6 failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
