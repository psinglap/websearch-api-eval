"""Result dating for freshness metrics (metrics 4 and 5).

Chain (first hit wins; the source is recorded as date_source):
  1. provider    - the provider's own date field (page_age, published_date, ...)
  2. htmldate    - htmldate.find_date(..., extensive_search=True) on returned HTML content
  3. htmldate_url- htmldate on the live URL (downloads the page; cached per URL)
  4. url_pattern - a /YYYY/MM/DD/ or YYYY-MM-DD pattern in the URL
  5. undated

htmldate is the best-scoring open-source date extractor in its published
comparison (extensive mode accuracy 0.865 on 1,000 pages):
https://htmldate.readthedocs.io/en/latest/evaluation.html
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as dtparser

_CACHE_LOCK = threading.Lock()


def _cache_path() -> Path:
    from .settings import out_dir
    p = out_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "htmldate_url_cache.json"


def parse_date(value) -> datetime | None:
    """Parse provider date strings ('April 30, 2025', ISO, epoch seconds/ms)."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            if v > 1e12:
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        s = str(value).strip()
        if re.fullmatch(r"\d{10,13}", s):
            return parse_date(int(s))
        # relative ages such as "3 hours ago" (some APIs return these)
        m = re.fullmatch(r"(\d+)\s*(minute|hour|day|week)s?\s+ago", s, re.I)
        if m:
            from datetime import timedelta
            n, unit = int(m.group(1)), m.group(2).lower()
            return datetime.now(timezone.utc) - timedelta(**{unit + "s": n})
        d = dtparser.parse(s, fuzzy=True, default=datetime(1900, 1, 1))
        if d.year == 1900:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


_URL_DATE = [
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|$|-)"),
    re.compile(r"(20\d{2})-(\d{2})-(\d{2})"),
    re.compile(r"/(20\d{2})(\d{2})(\d{2})/"),
]


def date_from_url(url: str) -> datetime | None:
    for rx in _URL_DATE:
        m = rx.search(url or "")
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _htmldate(doc: str) -> datetime | None:
    try:
        from htmldate import find_date
        s = find_date(doc, extensive_search=True, original_date=False, outputformat="%Y-%m-%dT%H:%M:%S")
        return parse_date(s) if s else None
    except Exception:
        return None


def htmldate_for_url(url: str, use_network: bool = True) -> datetime | None:
    path = _cache_path()
    with _CACHE_LOCK:
        cache = json.loads(path.read_text()) if path.exists() else {}
    if url in cache:
        return parse_date(cache[url])
    if not use_network:
        return None
    d = _htmldate(url)
    with _CACHE_LOCK:
        cache = json.loads(path.read_text()) if path.exists() else {}
        cache[url] = d.isoformat() if d else None
        path.write_text(json.dumps(cache, indent=0))
    return d


def looks_like_html(text: str) -> bool:
    return bool(text) and bool(re.search(r"<(html|head|meta|article|time)\b", text[:5000], re.I))


def date_result(result: dict, use_network: bool = True) -> tuple[datetime | None, str]:
    """Return (datetime_utc | None, date_source) for one normalized result."""
    import os
    if os.environ.get("EVAL_MOCK") == "1":
        use_network = False  # offline fixture mode
    d = parse_date(result.get("published_date"))
    if d:
        return d, result.get("date_source") or "provider"
    content = result.get("content") or ""
    if looks_like_html(content):
        d = _htmldate(content)
        if d:
            return d, "htmldate"
    url = result.get("url") or ""
    if url and use_network:
        d = htmldate_for_url(url, use_network=True)
        if d:
            return d, "htmldate_url"
    d = date_from_url(url)
    if d:
        return d, "url_pattern"
    return None, "undated"


def age_hours(d: datetime, now: datetime) -> float:
    return (now - d).total_seconds() / 3600.0
