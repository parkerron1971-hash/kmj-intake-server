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

WHERE THE ORCHESTRATOR GOES
  `post_lane(lane, payload)` (Layer Two, 2026-10-11) is the lane-based entry:
  lane_registry maps each lane to a provider and model, Anthropic by default,
  any OpenAI-compatible endpoint by config, always with the lane's Claude
  model as the fallback. `apost`/`post`/`sdk_client` keep their optional
  `task=` hint, which is still metadata and changes no routing.

WHAT THIS IS NOT
  Not a retry/fallback policy. `model_ladder.py` already owns that for the
  composer and atelier, and it keeps owning it — it now builds its client
  through `sdk_client()` so it inherits the endpoint seam, but its ladder
  logic is untouched. Folding the ladder in as a global default would
  change behavior for 30-odd callers that have never had it, which is
  exactly what this arc promised not to do.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import os
import sys
import time
from typing import Any, Dict, Mapping, Optional

import httpx
import chief_request_timing

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
    "ai_proxy", "atelier", "builder_loop", "builder_v2", "canvas",
    "chief_action_reasoner",
    "chief_insights", "chief_llm", "chief_of_staff", "chief_playbook",
    "design_coach", "design_intent", "doc_intelligence_router",
    "doc_templates_router", "passes", "platform_console", "site_composer",
    "site_concierge", "sourcing_engine", "spec_author", "vision_grader",
    "errand_driver",  # logs each browser-toolset turn under task=errand
    "chief_fast_track",  # the two-track reply's Haiku calls (/chief/opener …)
    "chief_site_view",  # view_website's written look at a screenshot, endpoint=view_website
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


# Keep persistence work alive independently of a timed-out reviewer. The loop's
# executor owns the running write; each row retains its originating billing scope.
_PENDING_METERS = set()


def _meter_finished(future):
    _PENDING_METERS.discard(future)
    if not future.cancelled() and future.exception() is not None:
        logger.warning("[llm_call] background metering failed: %s", type(future.exception()).__name__)


def _meter(response: Any, payload: Optional[Dict[str, Any]],
           caller: str, started: float,
           business_id: Optional[str] = None,
           units: Optional[int] = None, *, background: bool = False) -> None:
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
        # The routed request's own cost view (route_ledger). Here, after the
        # self-metering skip, so a call is tallied by exactly one of the two
        # places that meter it; a no-op outside a routed request.
        try:
            import route_ledger
            route_ledger.tally_usage(str((data or {}).get("model")
                                         or (payload or {}).get("model") or "unknown"), usage)
        except Exception:
            pass
        from api_usage_logger import log_api_usage_sync, cache_write_1h
        row = dict(
            endpoint=f"llm:{caller}",
            model=str((data or {}).get("model")
                      or (payload or {}).get("model") or "unknown"),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            # The 1-hour part of that write costs 2x, not 1.25x.
            cache_creation_1h_tokens=cache_write_1h(usage),
            business_id=business_id,
            units=units,
            duration_ms=int((time.time() - started) * 1000),
            # The provider's own id for this response (msg_...): proof of
            # which call produced an output. Lane and turn come from the
            # ambient turn_context inside the logger.
            response_id=str((data or {}).get("id") or "") or None,
        )
        if background:
            # The tally above is local and immediately visible to this turn.
            # Persist the same row once off-loop: a slow billing database must
            # not hold back a completed verdict or freeze all speech streams.
            # Executor submission starts now and survives caller cancellation.
            context = contextvars.copy_context()
            write = functools.partial(log_api_usage_sync, **row)
            future = asyncio.get_running_loop().run_in_executor(None, context.run, write)
            _PENDING_METERS.add(future)
            future.add_done_callback(_meter_finished)
        else:
            log_api_usage_sync(**row)
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
    operation = client.post(
        messages_url(),
        headers=headers(extra_headers, key=key),
        timeout=_CLIENT_DEFAULT if timeout is None else timeout,
        **body,
    )
    trace = chief_request_timing.CURRENT.get()
    resp = (await chief_request_timing.post_response(operation, trace,
                chief_request_timing.role_for(task, caller), (payload or {}).get("model"))
            if trace is not None else await operation)
    _meter(resp, payload, caller, started, business_id=business_id, units=units, background=True)
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


# ──────────────────────────────────────────────────────────────
# Lanes (Layer Two workstream D): one call, any provider, Claude fallback
# ──────────────────────────────────────────────────────────────

# Keys an OpenAI-compatible provider can honour. Anything else in the payload
# (tools, betas, output config...) is Anthropic-only, so the call stays on Claude.
_PORTABLE_KEYS = {"model", "max_tokens", "system", "messages", "thinking",
                  "stop_sequences", "metadata", "temperature"}


def _blocks_text(content: Any) -> Optional[str]:
    """Plain text of a system or message content, or None when it holds
    anything but text (images, documents, tool blocks, cache markers)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    out = []
    for b in content:
        if not isinstance(b, dict) or b.get("type") != "text" or b.get("cache_control"):
            return None
        out.append(str(b.get("text") or ""))
    return "\n".join(out)


def needs_anthropic(payload: Dict[str, Any]) -> Optional[str]:
    """Why this call must stay on Claude, or None if it is portable."""
    extra = sorted(k for k in (payload or {}) if k not in _PORTABLE_KEYS)
    if extra:
        return "uses " + ", ".join(extra)
    thinking = (payload or {}).get("thinking")
    if thinking and (not isinstance(thinking, dict) or thinking.get("type") != "disabled"):
        return "uses extended thinking"
    if "system" in payload and _blocks_text(payload["system"]) is None:
        return "system prompt has non-text or cached blocks"
    for m in payload.get("messages") or []:
        if _blocks_text((m or {}).get("content")) is None:
            return "a message has non-text or cached blocks"
    return None


def _openai_compatible(route, payload: Dict[str, Any], timeout: Any) -> httpx.Response:
    """Call an OpenAI-compatible /chat/completions and answer in the
    Anthropic Messages shape, so callers parse it exactly as before."""
    messages = []
    system = _blocks_text(payload.get("system")) if "system" in payload else None
    if system:
        messages.append({"role": "system", "content": system})
    for m in payload.get("messages") or []:
        messages.append({"role": m.get("role"), "content": _blocks_text(m.get("content")) or ""})
    body: Dict[str, Any] = {"model": route.model, "messages": messages,
                            "max_tokens": int(payload.get("max_tokens") or 1024)}
    if payload.get("stop_sequences"):
        body["stop"] = list(payload["stop_sequences"])[:4]
    url = f"{route.base_url}/chat/completions"
    r = httpx.post(url, json=body, timeout=DEFAULT_TIMEOUT if timeout is None else timeout,
                   headers={"Authorization": f"Bearer {os.environ.get(route.key_env or '', '')}",
                            "Content-Type": "application/json"})
    r.raise_for_status()
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    text = str(((choice.get("message") or {}).get("content")) or "").strip()
    if not text:
        raise RuntimeError("empty completion")
    usage = data.get("usage") or {}
    shaped = {
        "id": data.get("id") or "",
        "type": "message", "role": "assistant",
        "model": data.get("model") or route.model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "max_tokens" if choice.get("finish_reason") == "length" else "end_turn",
        "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0),
                  "output_tokens": int(usage.get("completion_tokens") or 0)},
        "_provider": route.provider,
    }
    return httpx.Response(200, json=shaped, request=httpx.Request("POST", url))


def post_lane(lane: str,
              payload: Dict[str, Any],
              *,
              plan: Optional[str] = None,
              timeout: Any = None,
              task: Optional[str] = None,
              business_id: Optional[str] = None,
              units: Optional[int] = None) -> httpx.Response:
    """Synchronous call on a LANE rather than a model. The lane registry
    decides provider and model (lane_registry.route_for). Anthropic lanes
    behave exactly like post(). A non-Anthropic lane is tried first and
    falls back to the lane's Claude model on any failure, and a call that
    uses Anthropic-only features never leaves Claude. Metered either way."""
    import lane_registry
    route = lane_registry.route_for(lane, plan)
    payload = dict(payload or {})
    if not route.is_anthropic:
        why = needs_anthropic(payload)
        if why:
            print(f"[route] lane {lane}: call {why}; staying on {route.fallback_model}", flush=True)
        else:
            caller, started = _caller_module(), time.time()
            try:
                resp = _openai_compatible(route, payload, timeout)
                _meter(resp, {**payload, "model": route.model}, caller, started,
                       business_id=business_id, units=units)
                return resp
            except Exception as e:
                print(f"[route] lane {lane}: {route.provider}/{route.model} failed "
                      f"({type(e).__name__}); falling back to {route.fallback_model}", flush=True)
        payload["model"] = route.fallback_model
        return post(payload, timeout=timeout, task=task or lane, business_id=business_id, units=units)
    payload.setdefault("model", route.model)
    return post(payload, timeout=timeout, task=task or lane, business_id=business_id, units=units)


def astream(client: httpx.AsyncClient,
            payload: Dict[str, Any],
            *,
            timeout: Any = None,
            extra_headers: Optional[Mapping[str, str]] = None,
            key: Optional[str] = None,
            task: Optional[str] = None,
            timing_trace=None):
    """Streaming POST with content-free timing only for an active Chief trace.
    Response operations and SSE lines retain their original behavior."""
    _route(task)
    context = client.stream(
        "POST",
        messages_url(),
        headers=headers(extra_headers, key=key),
        json=payload,
        timeout=_CLIENT_DEFAULT if timeout is None else timeout,
    )
    trace = timing_trace or chief_request_timing.CURRENT.get()
    if trace is None:
        return context
    return chief_request_timing.stream(context, trace,
        chief_request_timing.role_for(task, _caller_module()), payload.get("model"))


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
