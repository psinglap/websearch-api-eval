"""Metrics 10 and 11 - tokens passed to the answer model and cost per query.

Tokens = usage.input_tokens (+ cache tokens) of the answer call (for the
Claude-native arm this includes the search results Claude read). Cost =
search price (provider-reported when available, else config/prices.yaml) +
LLM tokens at list price (+ $10/1k web searches for Claude-native). Tokens
and cost per CORRECT answer are computed in analysis (method of the Tavily vs
Claude token-efficiency comparison and Parallel's cost-per-correct reporting).
Always passes; values are exported as named scores."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, log, result


def get_assert(output, context):
    md, v = ctx(context)
    d = {"tokens_in": md.get("tokens_in", 0), "tokens_out": md.get("tokens_out", 0),
         "search_cost_usd": md.get("search_cost_usd") or 0.0, "llm_cost_usd": md.get("llm_cost_usd") or 0.0,
         "total_cost_usd": md.get("total_cost_usd") or 0.0}
    log("token_cost", md, v, d)
    return result(True, 1, f"{d['tokens_in']} tokens in; ${d['total_cost_usd']:.4f} total "
                  f"(search ${d['search_cost_usd']:.4f} via {md.get('search_cost_source')})", d)
