import csv
from datetime import timedelta

from lib import anomalies
from lib.search import now_utc


def test_friction_cli_and_note(tmp_path, monkeypatch):
    import friction.log as fl
    p = tmp_path / "f.csv"
    monkeypatch.setattr(fl, "LOG_PATH", p)
    fl.main(["tavily", "first call", "401 with Bearer header", "red", "5", "--category", "auth"])
    fl.main(["note", "exa", "dashboard lags", "--category", "dashboard"])
    rows = list(csv.DictReader(open(p)))
    assert rows[0]["severity"] == "Red" and rows[0]["category"] == "auth" and rows[0]["minutes_lost"] == "5"
    assert rows[1]["step"] == "note" and rows[1]["severity"] == "Green" and rows[1]["source"] == "manual-note"


def test_header_migration(tmp_path):
    import friction.log as fl
    p = tmp_path / "old.csv"
    p.write_text("time_utc,provider,step,expected,actual,severity,minutes_lost,feeling,docs_link,fix,source\n"
                 "t,exa,s,,a,Green,,,,,manual\n")
    fl.append_row("exa", "s2", "a2", "yellow", path=p, category="params", qid="G1")
    rows = list(csv.DictReader(open(p)))
    assert list(rows[0].keys()) == fl.COLUMNS and rows[1]["qid"] == "G1"


def test_anomaly_detectors():
    assert anomalies.http_status(401, "x")["severity"] == "red"
    assert anomalies.http_status(429, "x")["category"] == "rate limit"
    ws = now_utc() - timedelta(hours=24)
    old = (now_utc() - timedelta(days=10)).isoformat()
    res = [{"url": "https://other.invalid/a", "published_date": old, "date_source": "provider:x"}]
    found = anomalies.filters_ignored({"date_filter_applied": "day", "domain_filter_applied": ["github.com"]}, res, ws, ["github.com"])
    assert {f["step"] for f in found} == {"date filter", "domain filter"}

    class A:
        EXPECTED_TOP_FIELDS = ("results", "metadata.latency")
        EXPECTED_RESULT_FIELDS = ("url", "page_age")
    d = anomalies.schema_drift({"results": {}}, [{"url": "u"}], A)
    assert len(d) == 2
    assert anomalies.latency_over_budget({"search_latency_ms": 900}, "insurance")[0]["category"] == "latency"
    assert anomalies.deprecations({"Deprecation": "true"}, {"warning": "livecrawl deprecated"})
