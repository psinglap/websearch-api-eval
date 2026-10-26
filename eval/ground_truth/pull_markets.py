#!/usr/bin/env python3
"""Market / macro ground truth that has an open endpoint (F2, F3, F5, F6).

  F3 Coinbase spot price       https://api.coinbase.com/v2/prices/BTC-USD/spot (public)
  F2 Treasury daily par yields https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<year>/all?type=daily_treasury_yield_curve&_format=csv
                               (END-OF-DAY reference only; intraday 10y quote is captured as evidence/screenshot)
  F5 DOL weekly claims         https://www.dol.gov/ui/data.pdf (PDF saved with sha256; text extracted if pypdf is installed)
  F6 FOMC calendar/minutes     https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (HTML; minutes links parsed)
F1 (NVDA) and F4 (WTI) have no keyless official API: capture Nasdaq/CNBC pages with evidence/capture.py.
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, now  # noqa: E402


def f3(out):
    p = Puller("F3", out, 1)
    b = p.get("coinbase_spot", "https://api.coinbase.com/v2/prices/BTC-USD/spot")
    d = (b or {}).get("data") or {}
    if d:
        p.add("https://api.coinbase.com/v2/prices/BTC-USD/spot", f"BTC-USD {d.get('amount')}", now().isoformat(),
              price=d.get("amount"), currency=d.get("currency"))
    return p.save()


def f2(out):
    p = Puller("F2", out, 24)
    y = now().year
    txt = p.get("treasury_par_yields", f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                f"daily-treasury-rates.csv/{y}/all", params={"type": "daily_treasury_yield_curve",
                                                              "field_tdr_date_value": y, "_format": "csv"}, as_json=False)
    rows = list(csv.DictReader(io.StringIO(txt or "")))
    if rows:
        r = rows[0]
        p.add("https://home.treasury.gov/resource-center/data-chart-center/interest-rates", f"10Y par yield {r.get('10 Yr')}",
              r.get("Date"), ten_year=r.get("10 Yr"))
    p.notes.append("End-of-day par yield (reference). Grade F2 against the intraday quote captured at run time.")
    return p.save()


def f5(out):
    p = Puller("F5", out, 24)
    pdf = p.get("dol_ui_data_pdf", "https://www.dol.gov/ui/data.pdf", as_json=False)
    try:
        from pypdf import PdfReader
        raw = [s for s in p.sources if s["name"] == "dol_ui_data_pdf"][-1]["raw_file"]
        from _gt import EVAL_DIR
        text = PdfReader(str(EVAL_DIR / raw) if not Path(raw).is_absolute() else raw).pages[0].extract_text()
        m = re.search(r"initial claims was (\d[\d,]*\d)", text or "", re.I)
        w = re.search(r"week ending ([A-Z][a-z]+ \d{1,2})", text or "")
        p.add("https://www.dol.gov/ui/data.pdf", f"initial claims {m.group(1) if m else '?'} (week ending {w.group(1) if w else '?'})",
              now().isoformat(), initial_claims=m.group(1) if m else None)
        p.notes.append("First page text: " + re.sub(r"\s+", " ", text or "")[:600])
    except ImportError:
        p.notes.append("pypdf not installed: read the saved PDF by hand.")
    except Exception as e:
        p.notes.append(f"PDF parse failed ({e!r}); read the saved PDF by hand.")
    return p.save()


def f6(out):
    p = Puller("F6", out, 48)
    html = p.get("fomc_calendar", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", as_json=False)
    links = sorted(set(re.findall(r'href="(/monetarypolicy/fomcminutes(\d{8})\.htm)"', html or "")), key=lambda x: x[1])
    if links:
        path, d = links[-1]
        p.add(f"https://www.federalreserve.gov{path}", f"FOMC minutes of meeting {d}", None, meeting_date=d)
    p.notes.append("Latest minutes link on the calendar page; the RELEASE date (3 weeks after the meeting) "
                   "must be confirmed on the page and in the press release.")
    return p.save()


def main(out):
    for f in (f2, f3, f5, f6):
        try:
            f(out)
        except Exception as e:
            print(f"  {f.__name__} failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
