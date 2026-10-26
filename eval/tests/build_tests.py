#!/usr/bin/env python3
"""Generate tests/{gtm,insurance,finance}.yaml and answer_keys.csv.

Source of truth: reports/Agent queries.md (each test is an agent's search tool
call: upstream task -> exact query string + params -> what it needs back).

  python tests/build_tests.py            # writes YAML; creates answer_keys.csv only if missing
  python tests/build_tests.py --force-keys   # also overwrites answer_keys.csv (loses filled answers!)

Per-test vars:
  qid, usecase, upstream_task, query (sent verbatim), window_hours (48|24),
  domains (only to providers with domain filters), needs_back, freshness
  (48h|real-time), expected_answer "[FILL AT RUN TIME]", expect_none,
  source_urls, answer_type (exact|list|numeric), tolerance, ground_truth_file.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

EVAL = Path(__file__).resolve().parents[1]
FILL = "[FILL AT RUN TIME]"

# (qid, upstream_task, query, window_hours, domains, needs_back, freshness, none_possible, answer_type, tolerance, source_urls)
# window_hours = provider-side filter. Real-time rows use the tightest filter each provider
# supports: hours-based where the API takes a timestamp (Exa), else 'day' / today's date.
GTM = [
    ("G1", "Find developers hitting Kafka latency problems right now", "kafka consumer lag high latency issue", 6, ["github.com"],
     "Issue URLs opened in the last 6 hours, repo/org, time, the error described", "real-time", True, "list", "",
     ["https://github.com/search?q=kafka+consumer+lag+latency&type=issues&s=created&o=desc"]),
    ("G2", "Account signal: anything new at Confluent today?", "Confluent news", 24, [],
     "Headline, date, link - or \"none\" in the last 24h", "real-time", True, "list", "",
     ["https://www.confluent.io/blog/", "https://investors.confluent.io/news-releases", "https://news.google.com/search?q=Confluent"]),
    ("G3", "Any new mentions of Apache Iggy in the last day?", '"Apache Iggy"', 24, [],
     "Every mention (repo, blog, forum) in 24h, date - or \"none\"", "real-time", True, "list", "",
     ["https://github.com/apache/iggy", "https://hn.algolia.com/?query=iggy&sort=byDate"]),
    ("G4", "Draft a note on Apache Iggy's latest release for a prospect", "Apache Iggy release notes", 168, ["github.com", "iggy.apache.org"],
     "Latest release version, date, key changes, link", "week", False, "exact", "",
     ["https://github.com/apache/iggy/releases"]),
    ("G5", "Coding agent fixing a consumer-lag bug needs the official tuning guidance", "kafka consumer lag max.poll.records fetch.min.bytes", 8760, ["kafka.apache.org", "docs.confluent.io"],
     "Official doc URL, what each setting does, recommended direction", "year", False, "exact", "",
     ["https://kafka.apache.org/documentation/#consumerconfigs", "https://docs.confluent.io/platform/current/installation/configuration/consumer-configs.html"]),
    ("G6", "Competitive brief: what's the latest NATS server release?", "NATS server release", 168, ["github.com"],
     "Version, release date, link", "week", False, "exact", "",
     ["https://github.com/nats-io/nats-server/releases"]),
    ("G7", "Is Confluent Cloud having an incident right now? (outage = switching trigger)", "Confluent Cloud incident", 24, ["status.confluent.cloud"],
     "Active incident yes/no, component, start time - or \"none\"", "real-time", True, "exact", "",
     ["https://status.confluent.cloud/", "https://status.confluent.cloud/api/v2/incidents/unresolved.json"]),
    ("G8", "Which AI-agent / data-infra startups just raised money?", "AI agent infrastructure startup funding round", 48, [],
     "Company, amount, lead investor, date, link", "48h", False, "list", "",
     ["https://techcrunch.com/category/venture/", "https://news.crunchbase.com/"]),
    ("G9", "Find this week's content about memory/event logs for AI agents", "durable event log memory for AI agents", 168, [],
     "Article URLs, author/org, date", "week", True, "list", "",
     ["https://hn.algolia.com/?query=agent%20memory&sort=byDate"]),
    ("G10", "Competitive brief: published Redpanda vs Kafka latency benchmarks", "Redpanda vs Kafka p99 latency benchmark", 8760, [],
     "Benchmark source, date, p99 numbers, who ran it", "year", False, "list", "",
     ["https://www.redpanda.com/blog", "https://www.confluent.io/blog/"]),
]
INS = [
    ("I1", "Caller wants a new Florida homeowners policy", "Citizens Property Insurance binding suspension Florida", 24, ["citizensfla.com"],
     "Suspended yes/no, scope, effective date/time", "real-time", False, "exact", "",
     ["https://www.citizensfla.com/"]),
    ("I2", "Caller in Pensacola asks if the storm is coming", "Hurricane Isaias latest advisory NHC", 24, [],
     "Advisory #, time, location, max winds, landfall forecast", "real-time", False, "exact", "within the latest advisory",
     ["https://www.nhc.noaa.gov/"]),
    ("I3", "Agent must check warnings for the policy's county before binding", "hurricane warning Escambia County Florida active", 24, [],
     "Active warning types, issued time", "real-time", True, "list", "",
     ["https://api.weather.gov/alerts/active?zone=FLC033,FLZ201,FLZ202"]),
    ("I4", "Claims agent validating a wind-damage report in progress", "Pensacola weather wind speed", 24, [],
     "Current wind speed/gusts, observation time", "real-time", False, "numeric", "wind within +/-5 mph of the KPNS observation; observation <= 1 h old",
     ["https://api.weather.gov/stations/KPNS/observations/latest"]),
    ("I5", "Policyholder asks if they must evacuate", "Baldwin County Alabama evacuation order Isaias", 24, [],
     "Order in effect yes/no, zones, time", "real-time", True, "exact", "",
     ["https://baldwincountyal.gov/departments/EMA", "https://api.weather.gov/alerts/active?zone=ALC003"]),
    ("I6", "Claims ops checks whether federal aid applies", "FEMA disaster declaration Hurricane Isaias 2026", 48, [],
     "Declaration number + date - or \"none yet\" (beware older \"Isaias\")", "48h", True, "exact", "",
     ["https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries", "https://www.fema.gov/disaster/declarations"]),
    ("I7", "Compliance agent checks for new regulator orders", "Florida OIR OR Alabama DOI emergency order Isaias insurance", 48, [],
     "Order/bulletin, issuer, date - or \"none\"", "48h", True, "list", "",
     ["https://floir.com/", "https://www.aldoi.gov/"]),
    ("I8", "Underwriting checks which states declared emergencies", "governor state of emergency Hurricane Isaias", 168, [],
     "States, date of each declaration", "week", True, "list", "",
     ["https://www.flgov.com/eog/news/press", "https://governor.alabama.gov/newsroom/",
      "https://gov.louisiana.gov/news", "https://governor.ms.gov/"]),
    ("I9", "Claims agent validating a Texas hail claim", "Texas hail storm reports", 24, ["spc.noaa.gov"],
     "Locations, dates, hail size - or \"none\"", "24h", True, "list", "",
     ["https://www.spc.noaa.gov/climo/reports/today.html", "https://www.spc.noaa.gov/climo/reports/yesterday.html"]),
    ("I10", "Caller asks whether their 2024 Toyota RAV4 has an open recall", "NHTSA recall 2024 Toyota RAV4", 8760, ["nhtsa.gov"],
     "Recall campaign number(s), component, date", "year", False, "list", "",
     ["https://api.nhtsa.gov/recalls/recallsByVehicle?make=toyota&model=rav4&modelYear=2024", "https://www.nhtsa.gov/recalls"]),
]
FIN = [
    ("F1", "Where is NVIDIA trading?", "NVDA stock price", 24, [],
     "Price, % change, timestamp", "real-time", False, "numeric", "price within +/-0.5% of the quote at run time",
     ["https://finance.yahoo.com/quote/NVDA/", "https://www.nasdaq.com/market-activity/stocks/nvda"]),
    ("F2", "Where's the 10-year?", "US 10-year Treasury yield", 24, [],
     "Yield %, timestamp", "real-time", False, "numeric", "within +/-3 basis points",
     ["https://www.cnbc.com/quotes/US10Y", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"]),
    ("F3", "Bitcoin price?", "BTC USD price", 24, [],
     "Price, timestamp", "real-time", False, "numeric", "within +/-1%",
     ["https://www.coinbase.com/price/bitcoin", "https://api.coinbase.com/v2/prices/BTC-USD/spot"]),
    ("F4", "How's oil moving today?", "WTI crude oil price", 24, [],
     "Price, change, timestamp", "real-time", False, "numeric", "within +/-1%",
     ["https://www.cnbc.com/quotes/@CL.1"]),
    ("F5", "What did jobless claims print?", "initial jobless claims weekly report", 24, ["dol.gov"],
     "Number, week ending, release time", "real-time", False, "exact", "",
     ["https://www.dol.gov/ui/data.pdf", "https://www.dol.gov/newsroom/releases"]),
    ("F6", "Summarize the latest Fed minutes", "FOMC minutes", 168, ["federalreserve.gov"],
     "Release date, 3 key points, federalreserve.gov link", "week", False, "exact", "",
     ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"]),
    ("F7", "List $1B+ M&A deals announced in the last two days", "definitive agreement to acquire billion", 48, [],
     "Acquirer, target, value, date, source", "48h", False, "list", "",
     ["https://efts.sec.gov/LATEST/search-index?q=%22definitive%20agreement%22&forms=8-K"]),
    ("F8", "Monitoring account Stryker: what did its latest 8-K report?", "Stryker 8-K item 5.02", 168, ["sec.gov"],
     "Filing date, items, what changed (officer/director), EDGAR link", "week", False, "exact", "",
     ["https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000310764&type=8-K", "https://efts.sec.gov/LATEST/search-index?q=%22Stryker%22&forms=8-K"]),
    ("F9", "Analyst asks about the Chilwa Minerals listing", "Chilwa Minerals IPO price per share", 168, [],
     "IPO price, ticker, exchange, pricing date", "week", False, "exact", "",
     ["https://www.nasdaq.com/market-activity/ipos", "https://api.nasdaq.com/api/ipo/calendar?date=2026-10"]),
    ("F10", "When does JPMorgan report Q3?", "JPMorgan third quarter 2026 earnings release date", 168, [],
     "Date, time of release and call", "week (upcoming)", False, "exact", "",
     ["https://www.jpmorganchase.com/ir"]),
]
SETS = {"gtm": GTM, "insurance": INS, "finance": FIN}


SCORE_WINDOW = {"real-time": 6, "24h": 24, "48h": 48, "week": 168, "year": 8760}


def tier_of(fresh: str) -> str:
    f = fresh.lower()
    return "real-time" if f.startswith("real") else "week" if f.startswith("week") else f.split()[0]


def answer_mode() -> str:
    import sys
    sys.path.insert(0, str(EVAL))
    from lib.settings import settings
    return settings().get("answer_mode", "offline")


def test_case(usecase, row):
    (qid, task, query, wh, domains, needs, fresh, none_possible, atype, tol, srcs) = row
    vars_ = {
        "qid": qid, "usecase": usecase, "upstream_task": task, "query": query, "window_hours": wh,
        # promptfoo expands array-valued vars into one test per element, so lists are strings
        "domains": ",".join(domains), "needs_back": needs, "freshness": fresh,
        "freshness_tier": tier_of(fresh),
        # window used to SCORE freshness (metrics 4/5). Real-time: <= 6 h for news/status pages;
        # quote/observation pages are scored on "reflects the state at run time" via the answer key.
        "score_window_hours": SCORE_WINDOW[tier_of(fresh)],
        "expected_answer": FILL, "expect_none": FILL if none_possible else False,
        "source_urls": " ; ".join(srcs), "answer_type": atype, "tolerance": tol,
        "ground_truth_file": f"ground_truth/{qid}.json",
    }
    asserts = []
    if answer_mode() != "api":  # offline (default): correct-none / partial credit are graded later by Claude Code
        return {"description": f"{qid}: {task}", "vars": vars_, "assert": asserts}
    if none_possible:
        asserts.append({"type": "python", "value": "file://asserts/correct_none.py", "metric": "correct_none"})
    if atype == "list" and none_possible is not None:
        asserts.append({"type": "python", "value": "file://asserts/partial_credit.py", "metric": "partial_credit"})
    return {"description": f"{qid}: {task}", "vars": vars_, "assert": asserts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-keys", action="store_true")
    a = ap.parse_args()
    for uc, rows in SETS.items():
        tests = [test_case(uc, r) for r in rows]
        hdr = (f"# Generated by tests/build_tests.py from reports/Agent queries.md - edit there, then rebuild.\n"
               f"# expected_answer / expect_none are filled at run time in answer_keys.csv (graders read it).\n")
        (EVAL / "tests" / f"{uc}.yaml").write_text(hdr + yaml.safe_dump(tests, sort_keys=False, allow_unicode=True, width=200))
    # F1 variant (You.com knowledge=core) runs only F1
    f1 = [t for t in (test_case("finance", r) for r in FIN) if t["vars"]["qid"] == "F1"]
    (EVAL / "tests" / "finance_f1_variant.yaml").write_text(
        "# F1 only: You.com with knowledge=core, reported as a variant (not a separate competitor)\n"
        + yaml.safe_dump(f1, sort_keys=False, width=200))
    keys = EVAL / "answer_keys.csv"
    if a.force_keys or not keys.exists():
        cols = ["qid", "usecase", "upstream_task", "query", "window_hours", "domains", "needs_back", "freshness", "freshness_tier", "score_window_hours",
                "expected_answer", "expect_none", "tolerance", "source_url", "wayback_url", "captured_at_utc",
                "captured_before_run_utc", "rechecked_after_run_utc", "answer_changed_during_run", "notes"]
        with keys.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for uc, rows in SETS.items():
                for r in rows:
                    t = test_case(uc, r)["vars"]
                    w.writerow({"qid": t["qid"], "usecase": uc, "upstream_task": t["upstream_task"], "query": t["query"],
                                "window_hours": t["window_hours"], "domains": t["domains"],
                                "needs_back": t["needs_back"], "freshness": t["freshness"], "freshness_tier": t["freshness_tier"],
                                "score_window_hours": t["score_window_hours"], "expected_answer": FILL,
                                "expect_none": FILL if t["expect_none"] == FILL else "false", "tolerance": t["tolerance"],
                                "source_url": t["source_urls"], "wayback_url": "", "captured_at_utc": "",
                                "captured_before_run_utc": "", "rechecked_after_run_utc": "",
                                "answer_changed_during_run": "", "notes": ""})
        print(f"wrote {keys}")
    print("wrote tests/{gtm,insurance,finance}.yaml and tests/finance_f1_variant.yaml")


if __name__ == "__main__":
    main()
