"""
agent_readiness.py — is this vendor's site set up for an agent to order
from? (2026-08-21)

WHAT THIS ANSWERS
  A vendor either publishes a machine-readable ordering manifest or it
  does not. That is a FACT we can check, not an impression to form — and
  the difference matters, because the badge it feeds tells a practitioner
  how much of an order Chief could handle. A wrong yes points somebody at
  automation that does not exist.

THE STANDARD
  UCP (Universal Commerce Protocol) publishes discovery at
  `/.well-known/ucp`. That is the one checkable artifact in the agentic-
  commerce stack: UCP discovers, ACP executes checkout, AP2 carries the
  authorization. We check discovery only — the rest is meaningless
  without it.

THE MEASURED STARTING POSITION, so nobody mistakes silence for a bug
  Probed 2026-08-21 against sixteen suppliers these practitioners
  actually use — Grainger, Uline, McMaster, SanMar, S&S Activewear,
  alphabroder, Vistaprint, Moo, Printful, Printify, 4imprint, Faire,
  Alibaba, Staples, Office Depot, WebstaurantStore:

      ZERO of sixteen.

  The same probe against known adopters found three of six (Allbirds,
  Glossier, Gymshark — all Shopify DTC). So the protocol is real and
  live, and B2B supply has simply not arrived yet. This module is a
  tripwire for the day it does, not a feature anybody can use this week.

THE SOFT-404 IS THE WHOLE DIFFICULTY
  Four of those sixteen answer `/.well-known/agent.json` with HTTP 200
  and an HTML app shell — Grainger, Faire, Alibaba and 4imprint all do
  it. A detector that trusted a 200 would have declared four major
  suppliers agent-ready on the strength of a React error page. So a
  status code proves nothing here: the body has to parse as JSON AND
  carry the structure the live manifests actually have.

WHAT THE LIVE SHAPE ACTUALLY IS
  Read off a production manifest rather than a write-up, because the two
  published descriptions disagreed with each other AND with reality:

      {"ucp": {"version": ..., "supported_versions": [...],
               "services": {"dev.ucp.shopping": {...}},
               "capabilities": [...], "payment_handlers": [...]}}

  One source called the version key `ucp_version` at the top level;
  another described a top-level `payment` object. Neither is what is
  served. So the parser accepts the nested `ucp` object as the primary
  signal and tolerates the documented variants, rather than hard-
  validating a field name that two sources cannot agree on.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("agent_readiness")

WELL_KNOWN_PATH = "/.well-known/ucp"

# Identify ourselves. Same manners as the barcode lookup: this is a
# request to somebody else's server and it should say who is asking.
_UA = ("SolutionistSystem/1.0 (vendor ordering check; "
       "+https://mysolutionist.app)")

# A vendor's site is not on the critical path of anything. If it has not
# answered in this long, the answer is "we do not know", which is the
# same as "no badge".
_TIMEOUT = 6.0

# A manifest is a deployment artifact — it changes when a merchant ships,
# not minute to minute. Misses are cached for less time than hits because
# a vendor ADOPTING the protocol is the interesting transition, and we
# would rather notice that within a day than within a week.
_HIT_TTL = 7 * 24 * 3600.0
_MISS_TTL = 24 * 3600.0
_CACHE_MAX = 2000

_CACHE: Dict[str, Any] = {}
_CACHE_AT: Dict[str, float] = {}


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    at = _CACHE_AT.get(key)
    if at is None:
        return None
    hit = _CACHE.get(key) or {}
    ttl = _HIT_TTL if hit.get("agent_ready") else _MISS_TTL
    if (time.time() - at) > ttl:
        _CACHE.pop(key, None)
        _CACHE_AT.pop(key, None)
        return None
    return hit


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        oldest = sorted(_CACHE_AT.items(), key=lambda kv: kv[1])[: _CACHE_MAX // 4]
        for k, _ in oldest:
            _CACHE.pop(k, None)
            _CACHE_AT.pop(k, None)
    _CACHE[key] = value
    _CACHE_AT[key] = time.time()


def parse_manifest(body: bytes, content_type: str = "") -> Tuple[bool, Dict[str, Any]]:
    """Is this response a real UCP manifest?

    Returns (ready, detail). Deliberately strict about the body and
    deliberately loose about which documented field-name variant it uses.

    The strictness is the soft-404 guard: several large suppliers answer
    this path with HTTP 200 and an HTML page, and an HTML page is not a
    manifest no matter what status code it arrives with.
    """
    if not body:
        return False, {"reason": "empty"}
    head = body[:400].lstrip()[:200].lower()
    if head.startswith(b"<") or b"<html" in head or b"<!doctype" in head:
        return False, {"reason": "html_not_json"}
    if content_type and "json" not in content_type.lower():
        # Not fatal on its own — some servers mislabel — but combined with
        # a parse failure below it is the end of it.
        pass
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return False, {"reason": "not_json"}
    if not isinstance(data, dict):
        return False, {"reason": "not_an_object"}

    # The live shape nests everything under `ucp`. The write-ups also
    # describe a flat form, so both are accepted.
    node = data.get("ucp") if isinstance(data.get("ucp"), dict) else data
    version = (node.get("version") or node.get("ucp_version")
               or data.get("ucp_version"))
    services = node.get("services")
    capabilities = node.get("capabilities")

    if not version and not isinstance(services, dict):
        return False, {"reason": "no_ucp_markers"}

    service_ids = sorted(services.keys()) if isinstance(services, dict) else []
    handlers = node.get("payment_handlers")
    if not isinstance(handlers, list):
        handlers = ((data.get("payment") or {}).get("handlers")
                    if isinstance(data.get("payment"), dict) else [])
    payment_ids = [h.get("id") for h in (handlers or [])
                   if isinstance(h, dict) and h.get("id")]

    return True, {
        "version": str(version) if version else None,
        "services": service_ids,
        # "can it be ordered from" is the question, so the shopping
        # service is called out rather than buried in a list.
        "shopping": any(s.endswith(".shopping") for s in service_ids),
        "capabilities": len(capabilities) if isinstance(capabilities, list) else 0,
        "payment_handlers": payment_ids,
    }


def normalise_domain(value: str) -> Optional[str]:
    """Accept a website, an address, or a bare domain; return the host."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if "@" in v:
        v = v.split("@")[-1]
    if "//" not in v:
        v = "https://" + v
    host = (urlsplit(v).netloc or "").split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def check_domain(domain: str, *, use_cache: bool = True) -> Dict[str, Any]:
    """Probe one vendor domain. Never raises.

    A vendor whose site is down is not a vendor who lacks the protocol,
    so the two are reported differently: `agent_ready` false either way,
    but `reason` says which, and only a real answer is cached long.
    """
    host = normalise_domain(domain)
    if not host:
        return {"domain": None, "agent_ready": False, "reason": "no_domain"}

    if use_cache:
        cached = _cache_get(host)
        if cached is not None:
            return {**cached, "cached": True}

    url = f"https://{host}{WELL_KNOWN_PATH}"
    out: Dict[str, Any] = {"domain": host, "agent_ready": False,
                           "checked_at": time.time()}
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": _UA, "Accept": "application/json"}) as c:
            r = c.get(url)
        if r.status_code != 200:
            out["reason"] = f"http_{r.status_code}"
        else:
            ready, detail = parse_manifest(
                r.content, r.headers.get("Content-Type") or "")
            out["agent_ready"] = ready
            if ready:
                out["manifest"] = detail
                out["reason"] = "ucp"
            else:
                out["reason"] = detail.get("reason") or "no_markers"
    except Exception as e:
        out["reason"] = f"unreachable_{type(e).__name__}"

    _cache_put(host, out)
    return out
