"""Common helpers for ground-truth pullers.

Every puller saves (1) the raw API response with a UTC timestamp under
<out>/raw/<qid>_<source>_<ts>.json and (2) a normalized key file <out>/<qid>.json:
  {"qid", "pulled_at_utc", "window_hours", "sources": [{"name", "url", "raw_file", "status"}],
   "items": [{"url", "title", "date", ...}], "notes": [...]}
asserts/recall.py reads <out>/<qid>.json (default out = eval/ground_truth/).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_DIR))
try:
    from dotenv import load_dotenv
    load_dotenv(EVAL_DIR / ".env", override=False)
except Exception:
    pass

UA = "search-eval-harness/1.0 (ground-truth puller; contact: set SEC_USER_AGENT)"


def now() -> datetime:
    return datetime.now(timezone.utc)


def since(hours: float) -> datetime:
    return now() - timedelta(hours=hours)


def ts() -> str:
    return now().strftime("%Y%m%dT%H%M%SZ")


class Puller:
    def __init__(self, qid: str, out_dir: Path, window_hours: float):
        self.qid, self.out, self.window_hours = qid, Path(out_dir), window_hours
        self.sources, self.items, self.notes = [], [], []
        (self.out / "raw").mkdir(parents=True, exist_ok=True)

    def get(self, name: str, url: str, params=None, headers=None, as_json=True, retries=3):
        h = {"User-Agent": UA, **(headers or {})}
        last = None
        for attempt in range(retries):
            try:
                r = httpx.get(url, params=params, headers=h, timeout=30, follow_redirects=True)
                last = r
                if r.status_code in (429, 502, 503) and attempt < retries - 1:
                    time.sleep(2 ** attempt * 2)
                    continue
                break
            except httpx.HTTPError as e:
                last = e
                time.sleep(2 ** attempt)
        if isinstance(last, Exception):
            self.sources.append({"name": name, "url": url, "status": f"error: {last!r}", "raw_file": None})
            return None
        body = None
        ext = "json" if as_json else ("pdf" if "pdf" in last.headers.get("content-type", "") else "html")
        if as_json:
            try:
                body = last.json()
            except Exception:
                body, ext = last.text, "txt"
        else:
            body = last.content if ext == "pdf" else last.text
        raw_path = self.out / "raw" / f"{self.qid}_{name}_{ts()}.{ext}"
        if ext == "json":
            raw_path.write_text(json.dumps({"_request_url": str(last.request.url), "_status": last.status_code,
                                            "_fetched_at_utc": now().isoformat(), "body": body}, indent=1))
        elif ext == "pdf":
            raw_path.write_bytes(body)
        else:
            raw_path.write_text(body)
        self.sources.append({"name": name, "url": str(last.request.url), "status": last.status_code,
                             "raw_file": str(raw_path.relative_to(EVAL_DIR)) if raw_path.is_relative_to(EVAL_DIR) else str(raw_path),
                             "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()})
        return body if last.status_code < 400 else None

    def add(self, url: str, title: str = "", date: str | None = None, **extra):
        if url and all(i["url"] != url for i in self.items):
            self.items.append({"url": url, "title": title, "date": date, **extra})

    def save(self) -> Path:
        p = self.out / f"{self.qid}.json"
        p.write_text(json.dumps({"qid": self.qid, "pulled_at_utc": now().isoformat(), "window_hours": self.window_hours,
                                 "sources": self.sources, "items": self.items, "notes": self.notes}, indent=1))
        ok = [s for s in self.sources if isinstance(s["status"], int) and s["status"] < 400]
        print(f"  {self.qid}: {len(self.items)} items from {len(ok)}/{len(self.sources)} sources -> {p}")
        return p


def gh_headers() -> dict:
    tok = os.environ.get("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h
