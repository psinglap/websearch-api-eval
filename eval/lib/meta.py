"""Pull provider metadata out of a promptfoo assertion context.

promptfoo passes the provider response to python assertions; the exact key has
moved between versions, so we look in every documented place.
"""
from __future__ import annotations

import json


def provider_response(context: dict) -> dict:
    for k in ("providerResponse", "provider_response", "response"):
        v = context.get(k)
        if isinstance(v, dict):
            return v
    return {}


def metadata(context: dict) -> dict:
    pr = provider_response(context)
    md = pr.get("metadata") or context.get("metadata") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            md = {}
    return md


def vars_(context: dict) -> dict:
    v = context.get("vars") or (context.get("test") or {}).get("vars") or {}
    return v


def provider_id(context: dict) -> str:
    p = context.get("provider") or {}
    if isinstance(p, dict):
        return p.get("label") or p.get("id") or ""
    return str(p)


def assertion_config(context: dict) -> dict:
    return context.get("config") or {}
