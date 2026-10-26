#!/usr/bin/env python3
"""SEC EDGAR full-text search ground truth (F8; F7 candidates).

EDGAR full-text search JSON: https://efts.sec.gov/LATEST/search-index?q=...&forms=8-K&dateRange=custom&startdt=&enddt=
SEC requires a descriptive User-Agent with contact details
(https://www.sec.gov/os/accessing-edgar-data) - set SEC_USER_AGENT in .env, e.g.
  SEC_USER_AGENT="Jane Doe jane@example.com"
Rate limit: <= 10 requests/second.
F8: 8-Ks whose items include 5.02, filtered to S&P 500 constituents (CIKs from the
Wikipedia constituents table, saved raw; best effort - verify by hand).
F7: 8-Ks mentioning "merger agreement" (candidates; the $1B threshold is checked by hand).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, now, since  # noqa: E402

FTS = "https://efts.sec.gov/LATEST/search-index"


def _ua():
    ua = os.environ.get("SEC_USER_AGENT", "").strip().strip('"')
    if not ua or "example.com" in ua:
        raise SystemExit("SEC_USER_AGENT is not set (needs 'Name email@domain'); skipping EDGAR pulls.")
    return {"User-Agent": ua}


def _hits(p, name, q, hours):
    body = p.get(name, FTS, params={"q": q, "forms": "8-K", "dateRange": "custom",
                                    "startdt": since(hours).date().isoformat(), "enddt": now().date().isoformat()},
                 headers=_ua())
    return (body or {}).get("hits", {}).get("hits", [])


def _url(h):
    src = h.get("_source", {})
    cik = (src.get("ciks") or [""])[0].lstrip("0")
    adsh = h.get("_id", "").split(":")[0]
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{adsh}-index.htm" if cik and adsh else ""


def sp500_ciks(p):
    try:
        import pandas as pd
        html = p.get("sp500_constituents_wikipedia", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", as_json=False)
        tbl = pd.read_html(__import__("io").StringIO(html))[0]
        col = [c for c in tbl.columns if "CIK" in str(c)][0]
        return {str(int(c)) for c in tbl[col].dropna()}
    except Exception as e:
        p.notes.append(f"S&P 500 list unavailable ({e!r}); F8 items are NOT filtered to S&P 500.")
        return None


def f8(out, hours=24):
    p = Puller("F8", out, hours)
    hits = _hits(p, "fts_item_5_02", '"Item 5.02"', hours)
    spx = sp500_ciks(p)
    for h in hits:
        src = h.get("_source", {})
        if "5.02" not in (src.get("items") or []):
            continue
        ciks = {c.lstrip("0") for c in src.get("ciks") or []}
        if spx is not None and not (ciks & spx):
            continue
        p.add(_url(h), "; ".join(src.get("display_names") or []), src.get("file_date"), items=src.get("items"))
    p.notes.append("8-K Item 5.02 covers director/officer departures AND appointments/comp changes: "
                   "keep only CEO/CFO departures when writing the answer key.")
    return p.save()


def f7(out, hours=48):
    p = Puller("F7", out, hours)
    for h in _hits(p, "fts_merger_agreement", '"merger agreement"', hours):
        src = h.get("_source", {})
        p.add(_url(h), "; ".join(src.get("display_names") or []), src.get("file_date"), items=src.get("items"))
    p.notes.append("Candidates only: deal value >= $1B must be checked by hand (press releases, archived).")
    return p.save()


def main(out):
    for f in (f8, f7):
        try:
            f(out)
        except SystemExit as e:
            print(f"  {f.__name__}: {e}")
            break
        except Exception as e:
            print(f"  {f.__name__} failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
