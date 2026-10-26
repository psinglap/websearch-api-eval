"""Claude calls shared by the answer step (all providers) and the graders.

Follows the claude-api skill (Python SDK, anthropic 1.x):
  - model IDs: claude-opus-5-5 (default) from the skill's model table
  - Claude Opus 5.5: thinking cannot be disabled; adaptive thinking is the
    default and `output_config.effort` is the only control (default medium,
    set explicitly here so runs are comparable)
  - structured outputs via output_config.format (json_schema)
  - errors: typed exception chain, retried by the SDK (max_retries=2)
Server-side refusal fallbacks (`fallbacks: "default"`) are deliberately NOT
enabled: a fallback would silently swap the answer model mid-eval and break
the "same model for every provider" rule. The served model and stop_reason are
recorded in metadata so a refusal is visible instead.
"""
from __future__ import annotations

import json
import threading
import time

import anthropic

from . import mock
from .settings import llm_cost_usd, settings

_client = None
_lock = threading.Lock()


def client() -> anthropic.Anthropic:
    global _client
    with _lock:
        if _client is None:
            _client = anthropic.Anthropic(max_retries=2, timeout=300.0)
        return _client


def text_of(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text")


def usage_of(message) -> dict:
    u = message.usage
    stu = getattr(u, "server_tool_use", None)
    return {
        "tokens_in": (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        + (getattr(u, "cache_creation_input_tokens", 0) or 0),
        "tokens_out": u.output_tokens or 0,
        "web_search_requests": (getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
    }


def complete(system: str, user: str, *, model: str | None = None, effort: str | None = None,
             max_tokens: int | None = None, json_schema: dict | None = None) -> dict:
    """One Messages API call. Returns {text, json, tokens_in, tokens_out, cost_usd, latency_ms, model, stop_reason}."""
    s = settings()
    model = model or s["answer_model"]
    if mock.ENABLED:  # offline fixture mode only (EVAL_MOCK=1)
        return mock.llm_complete(system, user, json_schema)
    kwargs = dict(
        model=model,
        max_tokens=max_tokens or s["answer_max_tokens"],
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort or s["answer_effort"]},
    )
    if json_schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": json_schema}
    t0 = time.perf_counter()
    msg = client().messages.create(**kwargs)
    latency_ms = (time.perf_counter() - t0) * 1000
    u = usage_of(msg)
    txt = text_of(msg)
    parsed = None
    if json_schema:
        try:
            parsed = json.loads(txt)
        except Exception:
            parsed = None
    return {
        "text": txt, "json": parsed, "latency_ms": round(latency_ms, 1),
        "tokens_in": u["tokens_in"], "tokens_out": u["tokens_out"],
        "cost_usd": llm_cost_usd(model, u["tokens_in"], u["tokens_out"]),
        "model": getattr(msg, "model", model), "stop_reason": msg.stop_reason,
    }


def grade(system: str, user: str, json_schema: dict | None = None) -> dict:
    s = settings()
    return complete(system, user, model=s["grader_model"], effort=s["grader_effort"],
                    max_tokens=s["grader_max_tokens"], json_schema=json_schema)
