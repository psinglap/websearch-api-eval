#!/usr/bin/env python3
"""GitHub ground truth (G1, G3, G6, G10).

APIs (no key needed; GITHUB_TOKEN raises the search limit 10 -> 30 req/min):
  search issues  https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests
  releases       https://docs.github.com/en/rest/releases/releases#list-releases
G10 has no API: github.com/trending is saved as HTML (evidence/capture.py also archives it).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gt import Puller, gh_headers, since  # noqa: E402

API = "https://api.github.com"
RELEASE_REPOS = ["apache/kafka", "redpanda-data/redpanda", "nats-io/nats-server", "apache/pulsar"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def g1(out, hours=6):
    p = Puller("G1", out, hours)
    for q in ("kafka consumer lag", "kafka latency"):
        body = p.get(f"search_{q.replace(' ', '_')}", f"{API}/search/issues",
                     params={"q": f"{q} is:issue created:>={iso(since(hours))}", "sort": "created", "order": "desc",
                             "per_page": 100}, headers=gh_headers())
        for it in (body or {}).get("items", []):
            p.add(it["html_url"], it["title"], it["created_at"], repo=it["repository_url"].split("/repos/")[-1])
    p.notes.append("Issues matching 'kafka consumer lag' or 'kafka latency' created in the window (GitHub search).")
    return p.save()


def g3(out, hours=168):
    p = Puller("G3", out, hours)
    body = p.get("iggy_repo_issues_prs", f"{API}/search/issues",
                 params={"q": f"repo:apache/iggy created:>={iso(since(hours))}", "per_page": 100}, headers=gh_headers())
    p.notes.append(f"apache/iggy issues+PRs created in window: {(body or {}).get('total_count')}")
    body = p.get("mentions_outside_repo", f"{API}/search/issues",
                 params={"q": f'"apache iggy" -repo:apache/iggy created:>={iso(since(hours))}', "per_page": 100},
                 headers=gh_headers())
    for it in (body or {}).get("items", []):
        repo = it["repository_url"].split("/repos/")[-1]
        r = repo.lower()
        if r.startswith("apache/") or r.endswith("/iggy") or it["title"].lower().startswith("apache/iggy#"):
            # project-internal activity (apache org repos, forks named */iggy) is not a "mention";
            # it is counted in the notes instead. Keep third-party mentions only.
            continue
        p.add(it["html_url"], it["title"], it["created_at"], kind="github_mention", repo=repo)
    rel = p.get("iggy_releases", f"{API}/repos/apache/iggy/releases", params={"per_page": 10}, headers=gh_headers())
    for r in rel or []:
        if r.get("published_at") and r["published_at"] >= iso(since(hours)):
            p.add(r["html_url"], r.get("name") or r.get("tag_name"), r["published_at"], kind="release")
    try:
        from pull_hn import hn_search
        for h in hn_search(p, "iggy", hours):
            p.add(h["url"], h["title"], h["date"], kind="hn")
    except Exception as e:
        p.notes.append(f"HN lookup failed: {e!r}")
    p.notes.append("Blog/news mentions need a manual search (archived via evidence/capture.py).")
    return p.save()


def g6(out, hours=24):
    p = Puller("G6", out, hours)
    for repo in RELEASE_REPOS:
        rel = p.get(f"releases_{repo.replace('/', '_')}", f"{API}/repos/{repo}/releases", params={"per_page": 20},
                    headers=gh_headers())
        for r in rel or []:
            if r.get("published_at") and r["published_at"] >= iso(since(hours)):
                p.add(r["html_url"], f"{repo} {r.get('tag_name')}", r["published_at"], prerelease=r.get("prerelease"))
    p.notes.append("Releases published in the window; empty list => correct answer is 'none'.")
    p.notes.append("apache/kafka publishes few GitHub releases; also check kafka.apache.org/downloads (evidence).")
    return p.save()


def g10(out, hours=24):
    p = Puller("G10", out, hours)
    html = p.get("trending_daily", "https://github.com/trending", params={"since": "daily"}, as_json=False)
    for m in re.finditer(r'<h2 class="h3 lh-condensed">\s*<a[^>]*href="/([^"/]+/[^"/]+)"', html or ""):
        p.add(f"https://github.com/{m.group(1)}", m.group(1))
    p.notes.append("Full daily trending list (all topics); the answer key should keep streaming/data-infra repos only.")
    return p.save()


def main(out):
    for f in (g1, g3, g6, g10):
        try:
            f(out)
        except Exception as e:
            print(f"  {f.__name__} failed: {e!r}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
