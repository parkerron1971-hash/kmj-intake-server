"""
api_usage_logger.py — record Anthropic API calls to api_usage table.

Every successful call to Anthropic (from ai_proxy.py + chief_of_staff.py
today; more agents later) calls log_api_usage(...) with the model, token
counts, and identifying context. We compute the cost using the price
table below and insert one row.

Designed to be FIRE-AND-FORGET — the logger never raises and never blocks
the caller. If Supabase is unreachable, we log the failure to stderr and
move on. We'd rather lose an audit row than fail a user-facing AI call.

═══════════════════════════════════════════════════════════════════════
USAGE
═══════════════════════════════════════════════════════════════════════

    from api_usage_logger import log_api_usage

    # After every successful Anthropic call:
    await log_api_usage(
        endpoint="/ai/proxy",
        model="claude-sonnet-4-5-20250929",
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        business_id=req.metadata.get("business_id") if req.metadata else None,
        user_id=req.metadata.get("auth_user_id") if req.metadata else None,
        task_type=req.task_type,
        duration_ms=elapsed_ms,
    )

═══════════════════════════════════════════════════════════════════════
PRICING
═══════════════════════════════════════════════════════════════════════

Anthropic's published rates (per million tokens, USD), as of 2026-05-25.
Update here when prices change — old rows keep their captured cost.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

import billing_context


logger = logging.getLogger("api_usage_logger")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] usage: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)


# Per-million-token prices in USD cents. Input first, then output.
# Source: platform.claude.com/docs/en/about-claude/pricing — VERIFIED
# 2026-07-12 (Pricing v2 Phase C; was 2026-05-25 and had gone stale:
# Opus 4.8 is $5/$25, not the old Opus-4 $15/$75, and Haiku 4.5 is
# $1/$5). Keys are matched LONGEST-PREFIX-FIRST so
# "claude-opus-4-8-..." hits its own entry, not "claude-opus-4".
MODEL_PRICING_CENTS: Dict[str, tuple[float, float]] = {
    # Fable 5 — Mythos-class flagship: $10/MTok in, $50/MTok out.
    # (Elite-tier deep/insight lanes — the launch-gate entry.)
    "claude-fable-5":    (1000.0, 5000.0),
    # Opus 5 — $5/MTok in, $25/MTok out. MISSING until 2026-08-22: the
    # sourcing engine's every call fell to the Sonnet fallback below and
    # under-booked by ~40% — the number a pricing ruling was made
    # against. When a new model ships, its row lands here BEFORE any
    # engine adopts it.
    "claude-opus-5":     (500.0, 2500.0),
    # Opus 4.5–4.8 — $5/MTok in, $25/MTok out
    "claude-opus-4-8":   (500.0, 2500.0),
    "claude-opus-4-7":   (500.0, 2500.0),
    "claude-opus-4-6":   (500.0, 2500.0),
    "claude-opus-4-5":   (500.0, 2500.0),
    # Opus 4.0/4.1 (retired/deprecated) — $15/MTok in, $75/MTok out
    "claude-opus-4":     (1500.0, 7500.0),
    # Sonnet 5 — intro $2/$10 through 2026-08-31, then $3/$15; we book
    # at the standard rate so margins are computed conservatively.
    "claude-sonnet-5":   (300.0, 1500.0),
    # Sonnet 4.x — $3/MTok in, $15/MTok out
    "claude-sonnet-4":   (300.0, 1500.0),
    # Haiku 4.5 — $1/MTok in, $5/MTok out
    "claude-haiku-4":    (100.0, 500.0),
    # Legacy fallbacks for any old model strings still in flight
    "claude-3-5-sonnet": (300.0, 1500.0),
    "claude-3-5-haiku":  (80.0, 400.0),
    "claude-3-opus":     (1500.0, 7500.0),
    # ── OpenAI (voice + embeddings + fallback brain) — metering coverage
    #    (beta-readiness audit): these paths were completely dark. For the
    #    non-token-priced ones (tts = per character, whisper = per minute)
    #    the caller computes the cost and passes cost_cents_override; the
    #    table entry here is a documented reference, priced so that passing
    #    char-count as input_tokens also yields the right number.
    "text-embedding-3-small": (2.0, 0.0),    # $0.02/MTok input
    "text-embedding-3-large": (13.0, 0.0),   # $0.13/MTok input
    "tts-1":             (1500.0, 0.0),      # $15 / 1M characters
    "tts-1-hd":          (3000.0, 0.0),      # $30 / 1M characters
    "eleven_turbo_v2_5": (2500.0, 0.0),      # ElevenLabs Turbo ≈ $25 / 1M chars (0.5 credits/char @ $0.05/1k credits)
    "whisper-1":         (0.0, 0.0),         # $0.006/min — via cost_cents_override
    "gpt-4o-mini-transcribe": (0.0, 0.0),    # per-minute — via cost_cents_override
    "gpt-4o-mini":       (15.0, 60.0),       # $0.15/$0.60 (fallback brain)
    "gpt-4o":            (250.0, 1000.0),    # $2.50/$10 (fallback brain)
}

# Anthropic prompt-cache multipliers (relative to base input rate):
# cache READ = 0.10×, cache WRITE/creation = 1.25×.
_CACHE_READ_MULT = 0.10
_CACHE_WRITE_MULT = 1.25


def _price_for_model(model: str) -> tuple[float, float]:
    """Return (input_cents_per_MTok, output_cents_per_MTok). Falls back
    to Sonnet pricing if no prefix matches (safe middle estimate).
    Longest prefix wins, so specific entries beat family entries no
    matter their dict order."""
    if not model:
        return (300.0, 1500.0)
    m = model.lower()
    best: tuple[float, float] | None = None
    best_len = -1
    for prefix, prices in MODEL_PRICING_CENTS.items():
        if m.startswith(prefix) and len(prefix) > best_len:
            best, best_len = prices, len(prefix)
    return best or (300.0, 1500.0)


def _compute_cost_cents(model: str, input_tokens: int, output_tokens: int,
                        cache_read_tokens: int = 0,
                        cache_creation_tokens: int = 0) -> float:
    in_cents_per_mtok, out_cents_per_mtok = _price_for_model(model)
    # Anthropic reports input_tokens as FRESH (uncached) input only; cache
    # reads (0.10×) and cache writes (1.25×) are separate and were being
    # dropped — understating every cached Chief turn. Fold them in.
    cost = (
        (input_tokens  / 1_000_000.0) * in_cents_per_mtok +
        (output_tokens / 1_000_000.0) * out_cents_per_mtok +
        (cache_read_tokens     / 1_000_000.0) * in_cents_per_mtok * _CACHE_READ_MULT +
        (cache_creation_tokens / 1_000_000.0) * in_cents_per_mtok * _CACHE_WRITE_MULT
    )
    return round(cost, 4)


def log_api_usage_sync(
    *,
    endpoint: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    business_id: Optional[str] = None,
    task_type: Optional[str] = None,
    ok: bool = True,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_cents_override: Optional[float] = None,
    units: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Synchronous variant for sync call sites (composer/director). Same
    row shape; never raises.

    `duration_ms` was async-only until 2026-08-09, which meant every
    composer and spec row had a NULL duration. When the Design Studio's
    blueprint call started timing out the browser, the one number that
    would have settled why — how long the call actually took — did not
    exist for any of the thirteen prior runs. Pass it wherever the call
    site can measure it.

    `units` = the PRICE of this action in credits, written onto the row.
    Pass it whenever the price is not a flat function of the endpoint —
    a build (base + per-section), a revamp, or an atelier call that is
    build-internal (0) rather than a standalone Studio rewrite. Leave it
    None to let usage_metering price the row from its endpoint."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    cost = (round(cost_cents_override, 4) if cost_cents_override is not None
            else _compute_cost_cents(model, input_tokens or 0, output_tokens or 0,
                                     cache_read_tokens, cache_creation_tokens))
    body: Dict[str, Any] = {
        "endpoint": endpoint, "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_cents": cost,
        "ok": ok,
        # Cache traffic is already PRICED into cost_cents above; these
        # two columns persist the COUNTS so the cache-hit rate is
        # measurable rather than merely paid for.
        "cache_read_tokens": int(cache_read_tokens or 0),
        "cache_creation_tokens": int(cache_creation_tokens or 0),
    }
    # Fall back to the ambient billing tenant. This is what gives
    # llm_call._meter a business to name: the seam stands in for 22
    # modules that never had one to pass. An explicit business_id
    # always wins, so the 42 call sites that pass one are untouched.
    business_id = business_id or billing_context.current()
    if business_id: body["business_id"] = business_id
    if task_type:   body["task_type"] = task_type
    if units is not None: body["units"] = int(units)
    if duration_ms is not None: body["duration_ms"] = int(duration_ms)
    try:
        httpx.post(
            f"{SUPABASE_URL}/rest/v1/api_usage",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=body, timeout=10.0,
        )
    except Exception as e:
        logger.warning(f"api_usage sync insert failed: {e}")


async def log_api_usage(
    *,
    endpoint: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    business_id: Optional[str] = None,
    user_id: Optional[str] = None,
    task_type: Optional[str] = None,
    duration_ms: Optional[int] = None,
    ok: bool = True,
    error: Optional[str] = None,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_cents_override: Optional[float] = None,
    units: Optional[int] = None,
) -> None:
    """Append one row to api_usage. Never raises.

    `units` = the PRICE of this action in credits (see log_api_usage_sync)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("api_usage: Supabase not configured; skipping log")
        return

    cost_cents = (round(cost_cents_override, 4) if cost_cents_override is not None
                  else _compute_cost_cents(model, input_tokens, output_tokens,
                                           cache_read_tokens, cache_creation_tokens))
    body: Dict[str, Any] = {
        "endpoint":      endpoint,
        "model":         model,
        "input_tokens":  int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_cents":    cost_cents,
        "ok":            ok,
        # Persist the cache COUNTS, not just their price (see the sync
        # variant): this is what makes the cache-hit rate measurable.
        "cache_read_tokens":     int(cache_read_tokens or 0),
        "cache_creation_tokens": int(cache_creation_tokens or 0),
    }
    # Fall back to the ambient billing tenant. This is what gives
    # llm_call._meter a business to name: the seam stands in for 22
    # modules that never had one to pass. An explicit business_id
    # always wins, so the 42 call sites that pass one are untouched.
    business_id = business_id or billing_context.current()
    if business_id: body["business_id"] = business_id
    if user_id:     body["user_id"] = user_id
    if task_type:   body["task_type"] = task_type
    if duration_ms is not None: body["duration_ms"] = int(duration_ms)
    if error:       body["error"] = str(error)[:500]
    if units is not None: body["units"] = int(units)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(
                f"{SUPABASE_URL}/rest/v1/api_usage",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=body,
            )
        if r.status_code >= 400:
            logger.warning(f"api_usage insert {r.status_code}: {r.text[:200]}")
    except Exception as e:
        # Never raise — usage logging must not break the live call.
        logger.warning(f"api_usage insert failed: {e}")


def now_ms() -> int:
    return int(time.time() * 1000)
