"""
llm_call.py — THE model seam (layer-two build list P0.4).

Every Anthropic call in this service goes through this module. Before it
existed there were 36 independent call sites: 21 files that each declared
their own copy of the endpoint URL and hand-built the same three headers,
and 15 that constructed their own `Anthropic()` SDK client. Each one made
its own decision about where the request goes and which key signs it.

Why that mattered (docs/LAYER_TWO_SEAM_REVIEW.md, seam 6):

  - Section 8's multi-model orchestrator needs ONE place that decides which
    model serves a task. Thirty-six places is a thirty-six-file rewrite.
  - Section 5's HIPAA path needs to substitute a HIPAA-eligible endpoint
    "without touching business logic". You cannot substitute what has no
    single point of substitution.

So this module owns exactly three decisions, and deliberately nothing else:

    where the request goes   → base_url() / messages_url()
    which key signs it       → api_key()
    what headers it carries  → headers()

Everything else — model choice, max_tokens, timeouts, retry policy, how a
response is parsed, what happens on a 4xx — stays with the caller. That is
the whole reason this migration is safe to review: it is a pure
redirection, not a behavior rewrite. Callers keep passing their own
`timeout=`; nothing here silently re-tunes an existing call.

HOW TO POINT THIS SOMEWHERE ELSE
  Set ANTHROPIC_BASE_URL. Every raw-HTTP call site and every SDK client
  follows it — that is the HIPAA-eligible-endpoint swap, and it is now a
  one-env-var change instead of a 36-file edit. Unset = api.anthropic.com.

WHERE THE ORCHESTRATOR GOES LATER
  `apost`/`post`/`sdk_client` all accept an optional `task=` hint. Today it
  is metadata and changes no routing. When Section 8 lands, `_route(task)`
  becomes the one function that maps a task to a model/provider, and no
  business logic has to move to get there.

WHAT THIS IS NOT
  Not a retry/fallback policy. `model_ladder.py` already owns that for the
  composer and atelier, and it keeps owning it — it now builds its client
  through `sdk_client()` so it inherits the endpoint seam, but its ladder
  logic is untouched. Folding the ladder in as a global default would
  change behavior for 30-odd callers that have never had it, which is
  exactly what this arc promised not to do.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Dict, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Metering at the seam ────────────────────────────────────────────
#
# spend_guard is the only global brake on AI spend, and it works by
# summing api_usage.cost_cents since midnight. 23 modules call this one
# and never write an api_usage row — so the brake could not see
# growth_engine, brand_engine, module_spec_generator, foundation_agent,
# contract_agent, discovery, vertical_distill and sixteen others. The
# single control meant to stop a runaway was blind to a large slice of
# the spend it was counting, and credits under-billed by the same.
#
# Metering here rather than at those 23 call sites is the difference
# between fixing 23 files and fixing the class: this is the one
# transport seam every Anthropic call already passes through, so caller
# number 24 is covered by code that already exists.
#
# The hazard is double counting. 19 modules DO meter themselves, and
# metering them again here would inflate the very number the brake
# reads — tripping it early and blocking AI for everyone, the same
# outage from the opposite direction. So the seam skips modules that
# meter for themselves, and a drift test recomputes this set from source
# so it cannot quietly rot.
_SELF_METERING = frozenset({
    "ai_proxy", "atelier", "builder_v2", "canvas", "chief_action_reasoner",
    "chief_insights", "chief_llm", "chief_of_staff", "chief_playbook",
    "design_coach", "design_intent", "doc_intelligence_router",
    "doc_templates_router", "passes", "platform_console", "site_composer",
    "site_concierge", "sourcing_engine", "spec_author", "vision_grader",
})

# Frames to walk past when deciding who the caller is. model_ladder
# wraps this seam — blaming it would hide every real caller behind one
# name and, worse, would let a self-metering module reach the seam
# disguised as one that isn't.
_TRANSPARENT = frozenset({"llm_call", "model_ladder"})


def _caller_module() -> str:
    """The first module up the stack that is not this seam or a wrapper."""
    try:
        frame = sys._getframe(1)
        while frame is not None:
            name = (frame.f_globals.get("__name__") or "").rsplit(".", 1)[-1]
            if name and name not in _TRANSPARENT:
                return name
            frame = frame.f_back
    except Exception:
        pass
    return "unknown"


def _meter(response: Any, payload: Optional[Dict[str, Any]],
           caller: str, started: float,
           business_id: Optional[str] = None,
           units: Optional[int] = None) -> None:
    """Write one api_usage row for a call whose caller does not log it.

    Never raises and never blocks: a metering failure must not fail an
    AI call that already succeeded.

    `business_id` (2026-08-22): the seam wrote every row WITHOUT a
    business, which meant a seam-metered module could never draw down an
    allowance or be seen in per-business cost — the spend was counted
    globally and billed to nobody (live: notification_engine 123 calls
    in 14 days, all unattributed). Callers that know whose work this is
    pass it through post/apost/post_with; callers that don't keep the
    old shape. `units` rides along for the same reason — 0 is
    meaningful (proactive work the practitioner never asked for bills
    nothing, the /chief/insights doctrine), None means "price by the
    endpoint table as before"."""
    if caller in _SELF_METERING:
        return
    try:
        if getattr(response, "status_code", 500) >= 400:
            return
        data = response.json()
    except Exception:
        return
    try:
        usage = (data or {}).get("usage") or {}
        if not usage:
            return
        from api_usage_logger import log_api_usage_sync
        log_api_usage_sync(
            endpoint=f"llm:{caller}",
            model=str((data or {}).get("model")
                      or (payload or {}).get("model") or "unknown"),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            business_id=business_id,
            units=units,
            duration_ms=int((time.time() - started) * 1000),
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[llm_call] metering failed for %s: %s", caller, e)

# The Messages API version every call site was already sending.
ANTHROPIC_VERSION = "2023-06-01"

_DEFAULT_BASE = "https://api.anthropic.com"

# Used ONLY by the standalone `post()`, which owns no client and would
# otherwise inherit httpx's 5-second module default. It matches the
# HTTP_TIMEOUT constant most migrated modules had duplicated locally.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# For the client-owning helpers, "no timeout given" must keep meaning "use
# the client's own timeout" — several call sites (chief_llm's 45s client,
# brand_engine's 60s client) deliberately configure it there and pass none
# per-request. Substituting a default here would silently retune them,
# which is exactly the kind of change this arc promised not to make.
_CLIENT_DEFAULT = httpx.USE_CLIENT_DEFAULT


# ──────────────────────────────────────────────────────────────
# The three decisions this module owns
# ──────────────────────────────────────────────────────────────

def base_url() -> str:
    """API root. ANTHROPIC_BASE_URL overrides it — this is the HIPAA /
    gateway / proxy substitution point. Read per-call, never cached at
    import, so tests and a restart-free config change both work."""
    return (os.environ.get("ANTHROPIC_BASE_URL") or _DEFAULT_BASE).rstrip("/")


def messages_url() -> str:
    """Full Messages endpoint. Replaces the 21 local ANTHROPIC_API_URL
    constants."""
    return f"{base_url()}/v1/messages"


def api_key() -> str:
    """The signing key. Empty string (not None) because every migrated
    caller already tested falsiness to decide whether to skip the call."""
    return os.environ.get("ANTHROPIC_API_KEY", "")


def headers(extra: Optional[Mapping[str, str]] = None,
            *, key: Optional[str] = None) -> Dict[str, str]:
    """The three headers every call site was building by hand. `extra`
    wins on conflict, which is how the two studio modules keep their
    explicit UTF-8 content-type."""
    h = {
        "x-api-key": key if key is not None else api_key(),
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _route(task: Optional[str]) -> None:
    """Extension point for Section 8. Today: deliberately a no-op, so the
    seam can land with provably zero behavior change. Later: the single
    place that picks a model/provider from the task."""
    return None


# ──────────────────────────────────────────────────────────────
# Raw Messages API (the httpx family)
# ──────────────────────────────────────────────────────────────
# These return the httpx.Response UNTOUCHED. Callers keep their own
# status-code checks, JSON parsing, and error handling exactly as they
# were written — that is what makes this migration reviewable.

async def apost(client: httpx.AsyncClient,
                payload: Optional[Dict[str, Any]] = None,
                *,
                content: Optional[bytes] = None,
                timeout: Any = None,
                extra_headers: Optional[Mapping[str, str]] = None,
                key: Optional[str] = None,
                task: Optional[str] = None,
                business_id: Optional[str] = None,
                units: Optional[int] = None) -> httpx.Response:
    """POST on a caller-owned AsyncClient. Pass `content` instead of
    `payload` when the caller needs to control serialization (the studio
    modules send ensure_ascii=False UTF-8 bytes on purpose).

    `business_id`/`units` reach the seam's api_usage row (see _meter) —
    pass them when the caller knows whose work this is; both are
    ignored for self-metering callers."""
    _route(task)
    body = {"content": content} if content is not None else {"json": payload}
    caller, started = _caller_module(), time.time()
    resp = await client.post(
        messages_url(),
        headers=headers(extra_headers, key=key),
        timeout=_CLIENT_DEFAULT if timeout is None else timeout,
        **body,
    )
    _meter(resp, payload, caller, started, business_id=business_id, units=units)
    return resp


def post_with(client: httpx.Client,
              payload: Optional[Dict[str, Any]] = None,
              *,
              content: Optional[bytes] = None,
              timeout: Any = None,
              extra_headers: Optional[Mapping[str, str]] = None,
              key: Optional[str] = None,
              task: Optional[str] = None,
              business_id: Optional[str] = None,
              units: Optional[int] = None) -> httpx.Response:
    """POST on a caller-owned SYNCHRONOUS client — the `with httpx.Client(
    timeout=…) as client` shape. Same client-default rule as `apost`."""
    _route(task)
    body = {"content": content} if content is not None else {"json": payload}
    caller, started = _caller_module(), time.time()
    resp = client.post(
        messages_url(),
        headers=headers(extra_headers, key=key),
        timeout=_CLIENT_DEFAULT if timeout is None else timeout,
        **body,
    )
    _meter(resp, payload, caller, started, business_id=business_id, units=units)
    return resp


def post(payload: Optional[Dict[str, Any]] = None,
         *,
         content: Optional[bytes] = None,
         timeout: Any = None,
         extra_headers: Optional[Mapping[str, str]] = None,
         key: Optional[str] = None,
         task: Optional[str] = None,
         business_id: Optional[str] = None,
         units: Optional[int] = None) -> httpx.Response:
    """Synchronous one-shot POST (httpx opens and closes its own client),
    for the modules that were already calling httpx.post directly."""
    _route(task)
    body = {"content": content} if content is not None else {"json": payload}
    caller, started = _caller_module(), time.time()
    resp = httpx.post(
        messages_url(),
        headers=headers(extra_headers, key=key),
        timeout=DEFAULT_TIMEOUT if timeout is None else timeout,
        **body,
    )
    _meter(resp, payload, caller, started, business_id=business_id, units=units)
    return resp


def astream(client: httpx.AsyncClient,
            payload: Dict[str, Any],
            *,
            timeout: Any = None,
            extra_headers: Optional[Mapping[str, str]] = None,
            key: Optional[str] = None,
            task: Optional[str] = None):
    """Streaming POST. Returns httpx's async context manager unchanged, so
    `async with astream(...) as resp:` reads exactly like the client.stream
    call it replaced."""
    _route(task)
    return client.stream(
        "POST",
        messages_url(),
        headers=headers(extra_headers, key=key),
        json=payload,
        timeout=_CLIENT_DEFAULT if timeout is None else timeout,
    )


# ──────────────────────────────────────────────────────────────
# SDK clients (the anthropic.Anthropic family)
# ──────────────────────────────────────────────────────────────

def sdk_client(*,
               timeout: Any = None,
               max_retries: Optional[int] = None,
               key: Optional[str] = None,
               task: Optional[str] = None):
    """A configured `Anthropic()` client. Only passes timeout/max_retries
    when the caller asked for them, so a bare sdk_client() keeps the SDK's
    own defaults — matching the sites that constructed Anthropic(api_key=…)
    with nothing else.

    Imported lazily: several modules that use the raw HTTP path import this
    module, and they must not pay for the SDK import or fail where it isn't
    installed."""
    from anthropic import Anthropic

    _route(task)
    kwargs: Dict[str, Any] = {"api_key": key if key is not None else api_key()}
    override = os.environ.get("ANTHROPIC_BASE_URL")
    if override:
        kwargs["base_url"] = override.rstrip("/")
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return Anthropic(**kwargs)


# ──────────────────────────────────────────────────────────────
# Small shared reader
# ──────────────────────────────────────────────────────────────

def text_of(data: Any) -> str:
    """Concatenate the text blocks of a Messages response body. Mirrors the
    `''.join(b['text'] for b in content if b['type']=='text')` idiom the
    call sites each wrote themselves. Tolerates junk and returns ''."""
    try:
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            return ""
        return "".join(
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
    except Exception:
        return ""
