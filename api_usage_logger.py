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
import turn_context


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
    # Jev: $0.042/MTok input, free output. Gateway actual cost overrides this
    # conservative estimate when returned (including promotional free usage).
    "jev-1.13.0":       (4.2, 0.0),
    "typesafe-ai/jev":  (4.2, 0.0),
    # Fable 5 — Mythos-class flagship: $10/MTok in, $50/MTok out.
    # (Elite-tier deep/insight lanes — the launch-gate entry.)
    "claude-fable-5":    (1000.0, 5000.0),
    # Fable 5.1 and Mythos 5.1 — same $10/$50 as Fable 5 (cache reads are
    # 0.025x, below). Explicit rows so neither rides a prefix by accident;
    # Mythos 5.1 had a cache multiplier but no price row at all.
    # Source: platform.claude.com/docs/en/about-claude/pricing, 2026-10-11.
    "claude-fable-5-1":  (1000.0, 5000.0),
    "claude-mythos-5-1": (1000.0, 5000.0),
    # Opus 5 — $5/MTok in, $25/MTok out. MISSING until 2026-08-22: the
    # sourcing engine's every call fell to the Sonnet fallback below and
    # under-booked by ~40% — the number a pricing ruling was made
    # against. When a new model ships, its row lands here BEFORE any
    # engine adopts it.
    "claude-opus-5":     (500.0, 2500.0),
    # Opus 5.5 — $4/MTok in, $20/MTok out (claude-api skill table,
    # 2026-09-22). Without its own row it matched "claude-opus-5" above
    # and every builder call booked 25% high.
    "claude-opus-5-5":   (400.0, 2000.0),
    # Opus 4.5–4.8 — $5/MTok in, $25/MTok out
    "claude-opus-4-8":   (500.0, 2500.0),
    "claude-opus-4-7":   (500.0, 2500.0),
    "claude-opus-4-6":   (500.0, 2500.0),
    "claude-opus-4-5":   (500.0, 2500.0),
    # Opus 4.0/4.1 (retired/deprecated) — $15/MTok in, $75/MTok out
    "claude-opus-4":     (1500.0, 7500.0),
    # Sonnet 5 — $2/$10 is now permanent; the scheduled September increase
    # was cancelled. Verified 2026-09-09 against the official pricing page.
    "claude-sonnet-5":   (200.0, 1000.0),
    "claude-sonnet-5-5": (200.0, 1000.0),   # same list price as Sonnet 5 (2026-09-28)
    # Sonnet 4.x — $3/MTok in, $15/MTok out
    "claude-sonnet-4":   (300.0, 1500.0),
    # Haiku 4.5 — $1/MTok in, $5/MTok out
    "claude-haiku-4":    (100.0, 500.0),
    # Haiku 5.5 (2026-10-07) — $0.10/MTok in, $0.50/MTok out for a prompt
    # up to 100k tokens; a longer prompt pays the _LONG_PROMPT row below.
    "claude-haiku-5-5":  (10.0, 50.0),
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
    "gpt-4o-mini-tts":   (1500.0, 0.0),      # $12 / 1M audio tokens ≈ $0.015/min ≈ $15 / 1M chars (voice latency arc 9/08)
    "eleven_turbo_v2_5": (2500.0, 0.0),      # ElevenLabs Turbo ≈ $25 / 1M chars (0.5 credits/char @ $0.05/1k credits)
    # Flash v2.5 is the default voice model (whisper_proxy ELEVENLABS_MODEL)
    # and had no row, so its characters were priced as Sonnet-4 input
    # tokens: ~8x low. ElevenLabs bills Flash and Turbo at the same rate
    # (0.5 credits/char). NOTE 2026-10-11: ElevenLabs' public pay-as-you-go
    # API card reads $0.05 per 1k characters ($50 / 1M) for Flash/Turbo; if
    # the account pays that card rather than plan credits, both rows are 2x low.
    "eleven_flash_v2_5": (2500.0, 0.0),
    # ── Other providers ──
    # Kimi K3 (Moonshot; site_llm stages, vision_grader): $3 / $15 per MTok,
    # cache hits $0.30 (0.1x). Moonshot's own pricing page was unreachable on
    # 2026-10-11; figures from eesel.ai and verdent.ai guides citing it.
    "kimi-k3":           (300.0, 1500.0),
    # GPT-5.4 (studio_decoration_generator validator): $2.50 / $15 per MTok,
    # cached input $0.25 (0.1x). From pricing aggregators (morphllm,
    # cloudprice.net), 2026-10-11; not verified on openai.com.
    "gpt-5.4":           (250.0, 1500.0),
    "whisper-1":         (0.0, 0.0),         # $0.006/min — via cost_cents_override
    "gpt-4o-mini-transcribe": (0.0, 0.0),    # per-minute — via cost_cents_override
    "gpt-4o-mini":       (15.0, 60.0),       # $0.15/$0.60 (fallback brain)
    "gpt-4o":            (250.0, 1000.0),    # $2.50/$10 (fallback brain)
}

# Anthropic prompt-cache multipliers (relative to base input rate):
# cache READ = 0.10×, cache WRITE = 1.25× for the 5-minute TTL and 2× for
# the 1-hour TTL. Chief's two long segments are written at 1 hour, and
# every write was priced at 1.25×: a 1-hour write was logged at 62% of
# what it cost (found 2026-09-24).
_CACHE_READ_MULT = 0.10
_CACHE_WRITE_MULT = 1.25
_CACHE_WRITE_1H_MULT = 2.0

# Cache reads are not 0.1x on every model (Anthropic pricing page, checked
# 2026-10-07): 0.05x on Sonnet 5.5 and Opus 5.5, 0.025x on Fable 5.1 and
# Mythos 5.1. At 0.1x the ledger priced every Sonnet 5.5 cache read at
# twice its cost. Longest prefix wins, as in the price table.
_CACHE_READ_MULT_BY_MODEL: Dict[str, float] = {
    "claude-sonnet-5-5": 0.05,
    "claude-opus-5-5":   0.05,
    "claude-fable-5-1":  0.025,
    "claude-mythos-5-1": 0.025,
}

# Models priced by prompt length: above `threshold` prompt tokens (fresh
# input + cache reads + cache writes) every token category is priced from
# the long row. Haiku 5.5: 5x above 100k tokens.
_LONG_PROMPT: Dict[str, tuple] = {
    "claude-haiku-5-5": (100_000, (50.0, 250.0)),
}


def _longest_prefix(model: str, table: Dict[str, Any]):
    m = (model or "").lower()
    best, best_len = None, -1
    for prefix, value in table.items():
        if m.startswith(prefix) and len(prefix) > best_len:
            best, best_len = value, len(prefix)
    return best


def cache_read_mult(model: str) -> float:
    """What a cache read costs, as a share of the model's input price."""
    v = _longest_prefix(model, _CACHE_READ_MULT_BY_MODEL)
    return _CACHE_READ_MULT if v is None else float(v)


def cache_write_1h(usage) -> int:
    """The 1-hour part of a response's cache write, from the API's
    `usage.cache_creation` breakdown; 0 when absent."""
    try:
        return int(((usage or {}).get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


# Models already reported as unknown in this process, so the warning
# prints once per model rather than once per call.
_UNKNOWN_MODELS_SEEN: set = set()


# What a model with no row is priced at: the top current Claude list
# price (Fable 5.x, $10 / $50 per MTok). Not the column maxima of the
# whole table: those mix a per-character TTS row (tts-1-hd, 3000) with a
# retired model's output rate (Opus 4, 7500) into a price no model has,
# and an unlisted cheap model booked at that could trip the platform
# spend cap for everyone. Retired Opus 4 / Claude 3 Opus have their rows.
_UNKNOWN_MODEL_RATES: tuple[float, float] = (1000.0, 5000.0)


def _most_expensive_rates() -> tuple[float, float]:
    """The rate a model with no row is priced at (see _UNKNOWN_MODEL_RATES)."""
    return _UNKNOWN_MODEL_RATES


def _price_for_model(model: str) -> tuple[float, float]:
    """Return (input_cents_per_MTok, output_cents_per_MTok).
    Longest prefix wins, so specific entries beat family entries no
    matter their dict order.

    A model with no row is priced at the top current Claude list price
    (_UNKNOWN_MODEL_RATES) and announced on stdout (logging never reaches
    Railway). It used to get
    Sonnet-4 rates silently: a cheaper model looked fine and an expensive
    one was under-booked, so the spend guard and the Costs view could be
    wrong without anyone seeing it. Failing expensive keeps the daily cap
    on the safe side until the row is added."""
    m = (model or "").lower()
    best: tuple[float, float] | None = None
    best_len = -1
    if m:
        for prefix, prices in MODEL_PRICING_CENTS.items():
            if m.startswith(prefix) and len(prefix) > best_len:
                best, best_len = prices, len(prefix)
    if best is not None:
        return best
    worst = _most_expensive_rates()
    key = m or "<empty>"
    if key not in _UNKNOWN_MODELS_SEEN:
        _UNKNOWN_MODELS_SEEN.add(key)
        print(f"[meter] UNKNOWN MODEL '{key}' priced at the top Claude rate "
              f"({worst[0]:g}/{worst[1]:g} cents per MTok); add it to "
              f"MODEL_PRICING_CENTS", flush=True)
    return worst


def _compute_cost_cents(model: str, input_tokens: int, output_tokens: int,
                        cache_read_tokens: int = 0,
                        cache_creation_tokens: int = 0,
                        cache_creation_1h_tokens: int = 0) -> float:
    in_cents_per_mtok, out_cents_per_mtok = _price_for_model(model)
    long_row = _longest_prefix(model, _LONG_PROMPT)
    if long_row:
        prompt = int(input_tokens or 0) + int(cache_read_tokens or 0) + int(cache_creation_tokens or 0)
        if prompt > long_row[0]:
            in_cents_per_mtok, out_cents_per_mtok = long_row[1]
    # Anthropic reports input_tokens as FRESH (uncached) input only; cache
    # reads (0.10×) and cache writes (1.25× / 2× at 1 hour) are separate
    # and were being dropped — understating every cached Chief turn. Fold
    # them in. `cache_creation_tokens` is the whole write; the 1-hour part
    # of it is priced at its own rate.
    cache_creation_tokens = int(cache_creation_tokens or 0)
    one_hour = min(max(int(cache_creation_1h_tokens or 0), 0), cache_creation_tokens)
    cost = (
        (input_tokens  / 1_000_000.0) * in_cents_per_mtok +
        (output_tokens / 1_000_000.0) * out_cents_per_mtok +
        (cache_read_tokens     / 1_000_000.0) * in_cents_per_mtok * cache_read_mult(model) +
        ((cache_creation_tokens - one_hour) / 1_000_000.0) * in_cents_per_mtok * _CACHE_WRITE_MULT +
        (one_hour / 1_000_000.0) * in_cents_per_mtok * _CACHE_WRITE_1H_MULT
    )
    return round(cost, 4)


# ─── Turn linkage (Layer Two, step 1) ─────────────────────────────────
# One id joins a Chief turn's model calls to its archive row, its ledger
# rows and its drafts. These columns arrive with
# APPLY-2026-10-11-layer-two-foundation.sql; until the probe sees them the
# row is written exactly as before (an unknown column would 400 the insert
# and lose the row).
_LINK_COLS = ("turn_id", "lane", "provider", "response_id", "cache_creation_1h_tokens")

_PROVIDER_PREFIXES = (
    ("claude", "anthropic"), ("anthropic", "anthropic"),
    ("gpt-", "openai"), ("text-embedding", "openai"), ("tts-", "openai"),
    ("whisper", "openai"), ("dall-e", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
    ("eleven", "elevenlabs"), ("kimi", "moonshot"), ("moonshot", "moonshot"),
)


def provider_for(model: Optional[str]) -> Optional[str]:
    """Who served a model, from its name. None when the name says nothing;
    an explicit provider from the caller always wins over this."""
    m = str(model or "").strip().lower()
    for prefix, provider in _PROVIDER_PREFIXES:
        if m.startswith(prefix):
            return provider
    return None


def _linkage(model: Optional[str], *, lane: Optional[str], provider: Optional[str],
             response_id: Optional[str], turn_id: Optional[str],
             cache_creation_1h_tokens: Optional[int]) -> Dict[str, Any]:
    """The link fields for one row, empties left out. Pure."""
    out: Dict[str, Any] = {}
    tid = turn_id if turn_id is not None else turn_context.turn_id()
    ln = lane if lane is not None else turn_context.lane()
    pv = provider or provider_for(model)
    for key, value in (("turn_id", tid), ("lane", ln), ("provider", pv), ("response_id", response_id)):
        if value:
            out[key] = str(value)[:120]
    if cache_creation_1h_tokens:
        out["cache_creation_1h_tokens"] = int(cache_creation_1h_tokens)
    return out


# ─── One price per Chief message (2026-10-16) ─────────────────────────
# The meter used to price every ROW, so a message that took two model
# calls was charged twice, a retry after an error was charged as if it
# had answered, and the answer check rode along at 1 credit a call. The
# price is now decided here, at write time, from the turn the row
# belongs to. usage_metering still reads `units` exactly as before.

def _priced_units(endpoint: Optional[str], ok: bool, units: Optional[int]) -> Optional[int]:
    """The credits to write onto one row; None = price it from the endpoint.

      explicit units                      unchanged (builds, revamps, ...)
      a Chief call that failed            0, in or out of a turn
      a Chief call inside a turn          the message price once, then 0
      any other unpriced call in a turn   0: it rides the message's price
      everything else                     None (the endpoint table)

    Never raises: on any error the row keeps the units it came with."""
    if units is not None:
        return units
    try:
        import pricing_config
        ep = (endpoint or "").strip()
        in_turn = bool(turn_context.turn_id())
        if ep in pricing_config.CHAT_TURN_ENDPOINTS:
            if ok is False:
                return 0
            if in_turn:
                return pricing_config.chat_price() if turn_context.claim_charge() else 0
            return None
        if in_turn and ep not in pricing_config.unit_weights():
            return 0
        return None
    except Exception as e:  # pragma: no cover - pricing never costs the row
        logger.warning(f"api_usage pricing skipped: {e}")
        return units


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
    cache_creation_1h_tokens: int = 0,
    lane: Optional[str] = None,
    provider: Optional[str] = None,
    response_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> None:
    """Synchronous variant for sync call sites (composer/director). Same
    row shape; never raises.

    `cache_creation_1h_tokens` is the 1-hour part of the cache write
    (priced at 2x, not 1.25x). Until 2026-10-11 only the async variant took
    it, so every call metered at the llm_call seam priced its 1-hour writes
    at the 5-minute rate.

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
                                     cache_read_tokens, cache_creation_tokens,
                                     cache_creation_1h_tokens))
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
    units = _priced_units(endpoint, ok, units)
    if units is not None: body["units"] = int(units)
    if duration_ms is not None: body["duration_ms"] = int(duration_ms)
    try:
        import schema_probe
        if schema_probe.has_columns("api_usage", _LINK_COLS):
            body.update(_linkage(model, lane=lane, provider=provider, response_id=response_id,
                                 turn_id=turn_id, cache_creation_1h_tokens=cache_creation_1h_tokens))
    except Exception as e:  # pragma: no cover - linkage never costs the row
        logger.warning(f"api_usage linkage skipped: {e}")
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
    cache_creation_1h_tokens: int = 0,
    lane: Optional[str] = None,
    provider: Optional[str] = None,
    response_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> None:
    """Append one row to api_usage. Never raises.

    `lane` / `turn_id` default to the ambient turn_context; `provider` to
    provider_for(model). They are written only once the Layer Two columns
    exist (_LINK_COLS).

    `units` = the PRICE of this action in credits (see log_api_usage_sync)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("api_usage: Supabase not configured; skipping log")
        return

    cost_cents = (round(cost_cents_override, 4) if cost_cents_override is not None
                  else _compute_cost_cents(model, input_tokens, output_tokens,
                                           cache_read_tokens, cache_creation_tokens,
                                           cache_creation_1h_tokens))
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
    units = _priced_units(endpoint, ok, units)
    if units is not None: body["units"] = int(units)
    try:
        import schema_probe
        if await schema_probe.has_columns_async("api_usage", _LINK_COLS):
            body.update(_linkage(model, lane=lane, provider=provider, response_id=response_id,
                                 turn_id=turn_id, cache_creation_1h_tokens=cache_creation_1h_tokens))
    except Exception as e:  # pragma: no cover - linkage never costs the row
        logger.warning(f"api_usage linkage skipped: {e}")

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


def meter_openai_usage(endpoint: str, data: Any, *, fallback_model: str,
                       business_id: Optional[str] = None,
                       units: Optional[int] = None) -> None:
    """Write one api_usage row from an OpenAI-compatible chat response.

    For direct provider calls that bypass the llm_call seam (which meters
    Anthropic responses only). OpenAI's `prompt_tokens` INCLUDE cached
    tokens; api_usage stores fresh input and cache reads separately, the
    way Anthropic reports them, so the cached part is split out. Never
    raises."""
    try:
        usage = (data or {}).get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        log_api_usage_sync(
            endpoint=endpoint,
            model=str((data or {}).get("model") or fallback_model),
            input_tokens=max(prompt - cached, 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_tokens=cached,
            business_id=business_id,
            units=units,
        )
    except Exception as e:
        print(f"[meter] openai usage for {endpoint} not logged: {e}", flush=True)


def now_ms() -> int:
    return int(time.time() * 1000)


def capture_in_memory() -> list:
    """Divert every api_usage row in this process to a list instead of the
    table, and return that list (each row carries its computed `cents`).

    For offline evals and benches that drive Chief against fixture
    businesses: the rows are not real tenants, and a run should say what it
    cost. Rebinds the module-level names every already-imported module
    holds, since callers import these functions by name. Irreversible for
    the life of the process -- never call it in the server."""
    import sys
    rows: list = []
    originals = {log_api_usage_sync, log_api_usage}

    def _sync(**kw):
        try:
            kw["cents"] = kw.get("cost_cents_override") or _compute_cost_cents(
                kw.get("model") or "", kw.get("input_tokens") or 0, kw.get("output_tokens") or 0,
                kw.get("cache_read_tokens") or 0, kw.get("cache_creation_tokens") or 0,
                kw.get("cache_creation_1h_tokens") or 0)
        except Exception:
            kw["cents"] = 0
        rows.append(kw)

    async def _async(**kw):
        _sync(**kw)

    for mod in list(sys.modules.values()):
        for name, repl in (("log_api_usage_sync", _sync), ("log_api_usage", _async)):
            try:
                if getattr(mod, name, None) in originals:
                    setattr(mod, name, repl)
            except Exception:
                pass
    return rows
