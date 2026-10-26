"""Metric 8 - Citation validity (does each cited URL load and support the claim?).

Standard: attribution/citation checks as in ALCE (Gao et al. 2023,
https://arxiv.org/abs/2305.14627 - citation recall/precision) and the
"verifiability" audit of generative search engines (Liu et al. 2023,
https://arxiv.org/abs/2304.09848). Groundedness of the whole answer in the
retrieved context is graded separately by promptfoo `context-faithfulness`
(RAGAS-style faithfulness) in the configs.

For every [n] in the answer:
  1. HTTP GET the URL (follow redirects, 15 s timeout): ok = status 200
  2. take the sentence containing [n], strip markers, and fuzzy-match it
     (rapidfuzz.partial_ratio, token-set fallback) against
       a) the live page text and b) the text the provider returned
     supported = max score >= citation_support_threshold (default 70)
  valid = ok AND supported. Score = valid / cited.
Claude-native citations carry cited_text (<=150 chars) from the API; we match
the claim against cited_text and the live page. You.com knowledge results
(urn:youcom:knowledge:*) are licensed data, not URLs: they are reported as
"licensed_data" and excluded from the denominator.

answer_mode=offline (default): there is no answer yet, so this assertion checks
the URL validity of the top-5 RETURNED results instead (HTTP 200 after redirects;
urn: licensed data excluded) and reports metric `url_validity`. Whether a cited
result supports the answer is graded later by Claude Code (grading/RUBRIC.md).
"""
from __future__ import annotations

import html
import os
import re
import threading

import httpx
from rapidfuzz import fuzz

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, is_error_output, log, not_applicable, result
from lib.settings import settings

_PAGE_CACHE: dict[str, tuple[int, str]] = {}
_LOCK = threading.Lock()
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) search-eval-citation-check/1.0"}


def page_text(url: str) -> tuple[int, str]:
    if os.environ.get("EVAL_MOCK") == "1":  # offline fixture mode: no network
        return (200, "")
    with _LOCK:
        if url in _PAGE_CACHE:
            return _PAGE_CACHE[url]
    try:
        r = httpx.get(url, follow_redirects=True, timeout=settings()["citation_fetch_timeout_s"], headers=UA)
        t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text)
        t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))
        out = (r.status_code, re.sub(r"\s+", " ", t))
    except Exception as e:
        out = (0, f"fetch error: {e!r}")
    with _LOCK:
        _PAGE_CACHE[url] = out
    return out


def claim_sentences(answer: str) -> dict[int, list[str]]:
    sents = re.split(r"(?<=[.!?])\s+|\n+", answer)
    out: dict[int, list[str]] = {}
    for s in sents:
        ns = [int(n) for n in re.findall(r"\[(\d+)\]", s)]
        clean = re.sub(r"\[\d+\]", "", s).strip(" -*#\t")
        for n in ns:
            if clean:
                out.setdefault(n, []).append(clean)
    return out


def support_score(claim: str, text: str) -> float:
    if not claim or not text:
        return 0.0
    return float(max(fuzz.partial_ratio(claim.lower(), text.lower()),
                     fuzz.token_set_ratio(claim.lower(), text.lower()) if len(text) < 5000 else 0))


def check(output: str, md: dict, fetch=page_text) -> dict:
    thr = settings()["citation_support_threshold"]
    claims = claim_sentences(output or "")
    srcs = {s["n"]: s["url"] for s in md.get("answer_sources", [])}
    returned = {r.get("url"): (r.get("content") or "") + " " + (r.get("snippet") or "") for r in md.get("results", [])}
    for c in md.get("citations", []) or []:  # claude-native cited_text
        returned[c["url"]] = returned.get(c["url"], "") + " " + (c.get("cited_text") or "")
    rows = []
    for n, sents in sorted(claims.items()):
        url = srcs.get(n)
        if url is None:
            rows.append({"n": n, "url": None, "status": None, "valid": False, "why": "citation number not in sources"})
            continue
        if url.startswith("urn:"):
            rows.append({"n": n, "url": url, "status": None, "valid": None, "why": "licensed_data"})
            continue
        status, text = fetch(url)
        claim = max(sents, key=len)
        s_live = support_score(claim, text) if status == 200 else 0.0
        s_ret = support_score(claim, returned.get(url, ""))
        supported = max(s_live, s_ret) >= thr
        rows.append({"n": n, "url": url, "status": status, "support_live": s_live, "support_returned": s_ret,
                     "supported": supported, "valid": status == 200 and supported, "claim": claim[:300]})
    graded = [r for r in rows if r["valid"] is not None]
    valid = sum(1 for r in graded if r["valid"])
    return {"n_cited": len(graded), "n_valid": valid, "n_url_ok": sum(1 for r in graded if r.get("status") == 200),
            "score": (valid / len(graded)) if graded else None, "rows": rows}


def url_check(md: dict, k: int = 5, fetch=page_text) -> dict:
    rows = []
    for i, r in enumerate(md.get("results", [])[:k], 1):
        url = r.get("url") or ""
        if url.startswith("urn:"):
            rows.append({"n": i, "url": url, "status": None, "ok": None, "why": "licensed_data"})
            continue
        status, _ = fetch(url)
        rows.append({"n": i, "url": url, "status": status, "ok": status == 200})
    graded = [x for x in rows if x["ok"] is not None]
    ok = sum(1 for x in graded if x["ok"])
    return {"n_checked": len(graded), "n_ok": ok, "score": (ok / len(graded)) if graded else None, "rows": rows}


def get_assert(output, context):
    md, v = ctx(context)
    if md.get("answer_mode", "api") != "api":
        if is_error_output(output):
            return result(False, 0, "provider error - no results", {"url_validity": 0})
        r = url_check(md)
        log("url_validity", md, v, r)
        if r["score"] is None:
            return not_applicable("no URL results to check")
        return result(True, r["score"], f"{r['n_ok']}/{r['n_checked']} top-5 result URLs return 200",
                      {"url_validity": r["score"]})
    if is_error_output(output):
        return result(False, 0, "provider error - no citations", {"citation_validity": 0})
    r = check(str(output), md)
    log("citation_validity", md, v, r)
    if r["score"] is None:
        return not_applicable("answer has no [n] citations" if not r["rows"] else "only licensed-data citations")
    return result(True, r["score"], f"{r['n_valid']}/{r['n_cited']} citations load (200) and support the claim; "
                  f"{r['n_url_ok']}/{r['n_cited']} URLs returned 200",
                  {"citation_validity": r["score"], "citation_url_ok": r["n_url_ok"] / r["n_cited"]})
