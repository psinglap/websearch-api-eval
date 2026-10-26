#!/usr/bin/env python3
"""Hacker News ground truth via the Algolia HN Search API (G2, G9; G3 helper).
API: https://hn.algolia.com/api  (search_by_date with numericFilters=created_at_i>T; tags=front_page)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, since  # noqa: E402

API = "https://hn.algolia.com/api/v1"
STREAMING = re.compile(r"kafka|stream|redpanda|pulsar|\bnats\b|event[- ]?(log|driven|sourcing)|message (queue|broker)|"
                       r"flink|kinesis|iggy|real[- ]time data|pub/?sub", re.I)


def item_url(h):
    return f"https://news.ycombinator.com/item?id={h['objectID']}"


def hn_search(p: Puller, query: str, hours: float, name: str | None = None):
    body = p.get(name or f"hn_{query.replace(' ', '_')}", f"{API}/search_by_date",
                 params={"query": query, "tags": "(story,comment)", "hitsPerPage": 100,
                         "numericFilters": f"created_at_i>{int(since(hours).timestamp())}"})
    return [{"url": item_url(h), "title": h.get("title") or h.get("story_title") or "", "date": h.get("created_at"),
             "points": h.get("points")} for h in (body or {}).get("hits", [])]


def g2(out, hours=24):
    p = Puller("G2", out, hours)
    body = p.get("front_page", f"{API}/search", params={"tags": "front_page", "hitsPerPage": 100})
    hits = (body or {}).get("hits", [])
    for h in hits:
        if STREAMING.search(h.get("title") or ""):
            p.add(item_url(h), h.get("title"), h.get("created_at"), points=h.get("points"),
                  comments=h.get("num_comments"), link=h.get("url"))
    p.notes.append(f"{len(hits)} stories on the front page at pull time; kept those matching streaming terms "
                   f"({STREAMING.pattern}). Empty => correct answer is 'none'. Review the raw list by hand.")
    return p.save()


def g9(out, hours=168):
    p = Puller("G9", out, hours)
    for q in ("agent memory", "event log agents", "durable execution agents", "agent memory event sourcing"):
        for h in hn_search(p, q, hours):
            p.add(h["url"], h["title"], h["date"], points=h.get("points"))
    p.notes.append("HN stories/comments only; articles elsewhere are added by hand from the manual search.")
    return p.save()


def main(out):
    for f in (g2, g9):
        try:
            f(out)
        except Exception as e:
            print(f"  {f.__name__} failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
