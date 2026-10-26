"""Metric 9 - Content in one call: did the search call itself return usable
page text (> 200 chars for at least one result), so the agent needs no second
extract/fetch call?  Standard: You.com's bundled-content claim, measured
directly from the response (boolean per call) plus characters returned for the
top 5. Parallel (excerpts) and Linkup (passages) are counted when their text
exceeds 200 chars, and noted as excerpts; Claude-native content is encrypted (False)."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _common import ctx, log, result


def get_assert(output, context):
    md, v = ctx(context)
    ok = bool(md.get("content_in_one_call"))
    chars = md.get("content_chars_top5", 0)
    log("content_one_call", md, v, {"content_in_one_call": ok, "content_chars_top5": chars})
    return result(True, 1 if ok else 0, f"content in one call: {ok} ({chars} chars in top 5)",
                  {"content_in_one_call": 1 if ok else 0})
