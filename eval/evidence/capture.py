#!/usr/bin/env python3
"""Capture original, timestamped evidence for every answer-key source URL.

For each URL (from answer_keys.csv `source_url`, ';'-separated, or --urls):
  1. Wayback Machine Save Page Now
       anonymous: GET https://web.archive.org/save/<url>  (archived URL from Content-Location / Location)
       SPN2 (if IA_ACCESS_KEY + IA_SECRET_KEY are set): POST https://web.archive.org/save
            Authorization: LOW <access>:<secret>, then poll /save/status/<job_id>
            (API doc: https://docs.google.com/document/d/1Nsv52MvSjbLb2PCpHlat0gkzw0EvtSgpKHu4mk0MnrA)
     Rate limits are respected: a pause between captures (default 15 s anonymous, 5 s SPN2) and
     exponential backoff on 429/5xx. On failure we fall back to the availability API
     (https://archive.org/wayback/available) to record the closest existing snapshot (flagged).
  2. A local HTML copy (out/evidence/<phase>/<qid>/...) with sha256
  3. A full-page PNG screenshot with Playwright/Chromium if installed (skipped gracefully if not)
Rows are appended to evidence/evidence_log.csv:
  qid, phase, source_url, wayback_url, wayback_status, captured_at_utc, local_copy, http_status,
  screenshot, sha256, notes

Usage:
  python evidence/capture.py --usecase insurance --phase before            # all insurance keys
  python evidence/capture.py --usecase finance --phase after --realtime-only
  python evidence/capture.py --urls https://www.nhc.noaa.gov/ --qid I2 --phase test
Run it BEFORE and AFTER each provider run for real-time questions (run.sh does this).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

EVAL_DIR = Path(__file__).resolve().parents[1]
LOG = EVAL_DIR / "evidence" / "evidence_log.csv"
COLS = ["qid", "phase", "source_url", "wayback_url", "wayback_status", "captured_at_utc", "local_copy", "http_status",
        "screenshot", "sha256", "notes"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) search-eval-evidence/1.0"

try:
    from dotenv import load_dotenv
    load_dotenv(EVAL_DIR / ".env", override=False)
except Exception:
    pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1])[:120]


def spn_anonymous(url: str, tries: int = 4) -> tuple[str | None, str]:
    last = ""
    for i in range(tries):
        try:
            r = httpx.get(f"https://web.archive.org/save/{url}", headers={"User-Agent": UA}, timeout=120,
                          follow_redirects=False)
            loc = r.headers.get("content-location") or r.headers.get("location") or ""
            if loc and "/web/" in loc:
                return (loc if loc.startswith("http") else f"https://web.archive.org{loc}"), f"saved ({r.status_code})"
            if r.status_code == 200:
                m = re.search(r'(/web/\d{14}/[^"\'\s<>]+)', r.text)
                if m:
                    return f"https://web.archive.org{m.group(1)}", "saved (200)"
            last = f"HTTP {r.status_code}: {r.text[:200]!r}"
            if r.status_code in (429, 520, 523, 502, 503, 504):
                time.sleep(min(60, 10 * 2 ** i))
                continue
            break
        except httpx.HTTPError as e:
            last = repr(e)
            time.sleep(5 * 2 ** i)
    return None, f"SPN failed: {last}"


def spn2(url: str, access: str, secret: str) -> tuple[str | None, str]:
    h = {"Authorization": f"LOW {access}:{secret}", "Accept": "application/json", "User-Agent": UA}
    try:
        r = httpx.post("https://web.archive.org/save", headers=h, data={"url": url, "capture_all": "1"}, timeout=60)
        j = r.json()
        job = j.get("job_id")
        if not job:
            return None, f"SPN2 submit failed: {j}"
        for _ in range(40):
            time.sleep(5)
            s = httpx.get(f"https://web.archive.org/save/status/{job}", headers=h, timeout=60).json()
            if s.get("status") == "success":
                return f"https://web.archive.org/web/{s['timestamp']}/{s.get('original_url', url)}", "saved (SPN2)"
            if s.get("status") == "error":
                return None, f"SPN2 error: {s.get('status_ext')} {s.get('message')}"
        return None, "SPN2 timeout waiting for job"
    except Exception as e:
        return None, f"SPN2 exception: {e!r}"


def closest_snapshot(url: str) -> str | None:
    try:
        r = httpx.get("https://archive.org/wayback/available", params={"url": url}, timeout=30)
        c = (r.json().get("archived_snapshots") or {}).get("closest") or {}
        return c.get("url")
    except Exception:
        return None


def local_copy(url: str, folder: Path) -> tuple[str, int | None, str]:
    folder.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=45, follow_redirects=True)
        ext = "pdf" if "pdf" in r.headers.get("content-type", "") else (
            "json" if "json" in r.headers.get("content-type", "") else "html")
        p = folder / f"{slug(url)}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.{ext}"
        p.write_bytes(r.content)
        return str(p.relative_to(EVAL_DIR)), r.status_code, hashlib.sha256(r.content).hexdigest()
    except Exception as e:
        return f"error: {e!r}", None, ""


def screenshot(url: str, folder: Path) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "skipped: playwright not installed (./run.sh setup --playwright)"
    p = folder / f"{slug(url)}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.png"
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1366, "height": 900}, user_agent=UA)
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(2500)
            # stamp the capture time into the page so the PNG itself carries the timestamp
            pg.evaluate("""ts => { const d=document.createElement('div'); d.textContent='Captured '+ts+' UTC';
                d.style.cssText='position:fixed;top:0;right:0;z-index:2147483647;background:#ff0;color:#000;font:14px monospace;padding:4px';
                document.body.appendChild(d); }""", now_iso())
            pg.screenshot(path=str(p), full_page=True)
            b.close()
        return str(p.relative_to(EVAL_DIR))
    except Exception as e:
        return f"error: {e!r}"[:300]


def append(row: dict):
    new = not LOG.exists() or LOG.stat().st_size == 0
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def targets(args) -> list[tuple[str, str]]:
    if args.urls:
        return [(args.qid or "adhoc", u) for u in args.urls]
    out = []
    with (EVAL_DIR / "answer_keys.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            if args.usecase not in ("all", r["usecase"]):
                continue
            if args.qids and r["qid"] not in args.qids.split(","):
                continue
            if args.realtime_only and r.get("freshness_tier") != "real-time":
                continue
            for u in re.split(r"\s*;\s*", r.get("source_url") or ""):
                if u.startswith("http"):
                    out.append((r["qid"], u))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usecase", default="all", choices=["all", "gtm", "insurance", "finance"])
    ap.add_argument("--phase", default="before", help="before | after | test | any label")
    ap.add_argument("--qids", default="")
    ap.add_argument("--qid", default="")
    ap.add_argument("--urls", nargs="*")
    ap.add_argument("--realtime-only", action="store_true")
    ap.add_argument("--no-wayback", action="store_true")
    ap.add_argument("--no-screenshot", action="store_true")
    ap.add_argument("--pause", type=float, default=None, help="seconds between Wayback captures")
    a = ap.parse_args(argv)
    access, secret = os.environ.get("IA_ACCESS_KEY"), os.environ.get("IA_SECRET_KEY")
    pause = a.pause if a.pause is not None else (5 if access and secret else 15)
    tl = targets(a)
    print(f"capturing {len(tl)} URLs (phase={a.phase}, wayback={'SPN2' if access and secret else 'anonymous'})")
    for i, (qid, url) in enumerate(tl):
        folder = EVAL_DIR / "out" / "evidence" / a.phase / qid
        lc, status, sha = local_copy(url, folder)
        shot = "skipped" if a.no_screenshot else screenshot(url, folder)
        wb, wbs = (None, "skipped")
        notes = ""
        if not a.no_wayback:
            wb, wbs = spn2(url, access, secret) if access and secret else spn_anonymous(url)
            if not wb:
                prev = closest_snapshot(url)
                if prev:
                    notes = f"closest EXISTING snapshot (not captured now): {prev}"
        row = {"qid": qid, "phase": a.phase, "source_url": url, "wayback_url": wb or "", "wayback_status": wbs,
               "captured_at_utc": now_iso(), "local_copy": lc, "http_status": status, "screenshot": shot,
               "sha256": sha, "notes": notes}
        append(row)
        print(f"  {qid} {url}\n     wayback: {wb or wbs}\n     local: {lc} ({status})  screenshot: {shot}")
        if i < len(tl) - 1 and not a.no_wayback:
            time.sleep(pause)


if __name__ == "__main__":
    main()
