from datetime import datetime, timezone

from lib import keys
from lib.dates import date_from_url, date_result, parse_date
from lib.urls import normalize_url


def test_normalize_url():
    assert normalize_url("https://www.Example.com/a/?utm_source=x#frag") == "https://example.com/a"
    assert normalize_url("http://news.ycombinator.com/item?id=123&p=2") == "https://news.ycombinator.com/item?id=123"
    assert normalize_url("https://stackoverflow.com/questions/77/some-slug") == "https://stackoverflow.com/questions/77"
    assert normalize_url("https://old.reddit.com/r/apachekafka/comments/abc12/title/") == "https://reddit.com/r/apachekafka/comments/abc12"


def test_parse_date_formats():
    assert parse_date("April 30, 2025").date().isoformat() == "2025-04-30"
    assert parse_date("2026-10-08T06:00:00").tzinfo is not None
    assert parse_date(1759900000).year == 2025
    assert parse_date("3 hours ago") is not None
    assert parse_date("") is None and parse_date(None) is None


def test_date_chain_provider_then_url():
    d, src = date_result({"url": "https://x.invalid/2026/10/07/post", "published_date": "2026-10-08", "date_source": "provider:x"}, use_network=False)
    assert src == "provider:x" and d.day == 8
    d, src = date_result({"url": "https://x.invalid/2026/10/07/post"}, use_network=False)
    assert src == "url_pattern" and d.day == 7
    d, src = date_result({"url": "https://x.invalid/nodate"}, use_network=False)
    assert d is None and src == "undated"
    html = '<html><head><meta property="article:published_time" content="2026-10-06T10:00:00Z"></head><body>x</body></html>'
    d, src = date_result({"url": "https://x.invalid/a", "content": html}, use_network=False)
    assert src == "htmldate" and d.date().isoformat() == "2026-10-06"


def test_date_from_url():
    assert date_from_url("https://a.invalid/2026-10-05-news") == datetime(2026, 10, 5, tzinfo=timezone.utc)


def test_keys_resolve(tmp_path):
    p = tmp_path / "k.csv"
    p.write_text("qid,expected_answer,expect_none,tolerance\nG1,FIXTURE gold,true,\nG2,[FILL AT RUN TIME],[FILL AT RUN TIME],\n")
    k = keys.resolve({"qid": "G1", "expected_answer": "[FILL AT RUN TIME]", "expect_none": "[FILL AT RUN TIME]"}, p)
    assert k["filled"] and k["expected_answer"] == "FIXTURE gold" and k["expect_none"] is True
    k = keys.resolve({"qid": "G2", "expected_answer": "[FILL AT RUN TIME]"}, p)
    assert not k["filled"] and not k["expect_none_known"]
    k = keys.resolve({"qid": "X", "expected_answer": "inline", "expect_none": False}, p)
    assert k["filled"] and k["expect_none"] is False
