"""URL normalization used for recall matching and dedup."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src|source$|s$)")


def normalize_url(url: str) -> str:
    """Lower-case scheme/host, drop www., fragments, tracking params and trailing slash.

    Also canonicalises a few hosts that appear in our ground truth:
    news.ycombinator.com/item?id=N, old/www.reddit.com, stackoverflow.com/q/N.
    """
    if not url:
        return ""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p = urlsplit(url)
    host = p.netloc.lower().removeprefix("www.").removeprefix("old.").removeprefix("m.")
    path = re.sub(r"/+$", "", p.path) or "/"
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k.lower())]
    if host == "news.ycombinator.com":
        q = [(k, v) for k, v in q if k == "id"]
    # stackoverflow.com/questions/123/slug -> stackoverflow.com/questions/123
    m = re.match(r"^/(?:questions|q)/(\d+)", path)
    if host.endswith("stackoverflow.com") and m:
        path, q = f"/questions/{m.group(1)}", []
    # github.com/org/repo/issues/1#comment -> keep path only
    if host == "github.com":
        q = []
    # reddit comments: /r/sub/comments/<id>/slug -> /r/sub/comments/<id>
    m = re.match(r"^(/r/[^/]+/comments/[a-z0-9]+)", path, re.I)
    if host.endswith("reddit.com") and m:
        path, q = m.group(1).lower(), []
    return urlunsplit(("https", host, path, urlencode(sorted(q)), ""))


def same_url(a: str, b: str) -> bool:
    return normalize_url(a) == normalize_url(b)
