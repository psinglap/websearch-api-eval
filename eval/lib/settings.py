"""Settings loader: config/settings.yaml, overridden by env vars and eval/.env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).resolve().parents[1]

try:  # .env is optional; run.sh also passes --env-file to promptfoo
    from dotenv import load_dotenv
    load_dotenv(EVAL_DIR / ".env", override=False)
except Exception:  # pragma: no cover
    pass


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(EVAL_DIR / "config" / "settings.yaml") as f:
        s = yaml.safe_load(f)
    for k, v in list(s.items()):
        env = os.environ.get(k.upper())
        if env is not None and not isinstance(v, dict):
            s[k] = type(v)(env) if isinstance(v, (int, float)) and not isinstance(v, bool) else env
    return s


@lru_cache(maxsize=1)
def prices() -> dict:
    with open(EVAL_DIR / "config" / "prices.yaml") as f:
        return yaml.safe_load(f)


def out_dir() -> Path:
    # EVAL_OUT_DIR lets offline fixture runs write somewhere other than the live out/ folder
    p = Path(os.environ["EVAL_OUT_DIR"]).resolve() if os.environ.get("EVAL_OUT_DIR") else EVAL_DIR / settings()["out_dir"]
    p.mkdir(parents=True, exist_ok=True)
    return p


def llm_cost_usd(model: str, tokens_in: int, tokens_out: int, web_searches: int = 0) -> float:
    m = prices()["llm"][model]
    cost = tokens_in * m["input_per_mtok"] / 1e6 + tokens_out * m["output_per_mtok"] / 1e6
    cost += web_searches * prices()["claude_web_search"]["per_search_usd"]
    return round(cost, 6)
