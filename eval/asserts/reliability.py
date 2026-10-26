"""Metric 12 - Reliability: error / timeout / rate-limit / empty / in-body error.

Counted per call (30 per provider per use case = 10 queries x 3 repeats) and
summarised in analysis. Claude reports search errors inside an HTTP 200, so
the Claude-native provider inspects the body (web_search_tool_result_error).
Passes when the call produced results without error."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, log, result

FAIL_TYPES = {"timeout", "rate_limit", "exception", "parse_error", "in_body_search_error", "refusal"}


def get_assert(output, context):
    md, v = ctx(context)
    et = md.get("error_type")
    ok = et is None
    log("reliability", md, v, {"error_type": et, "error": md.get("error"), "http_status": md.get("http_status")})
    named = {"call_ok": 1 if ok else 0, "call_error": 1 if (et and et != "empty_results") else 0,
             "call_empty": 1 if et == "empty_results" else 0}
    return result(ok, 1 if ok else 0, f"error_type={et or 'none'}", named)
